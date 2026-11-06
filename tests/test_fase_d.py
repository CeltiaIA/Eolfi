"""Fase D del plan de mejoras (2026-11-05): los huecos de pruebas de cada sección."""
import json
import os
import struct
import sys
import threading
import time
from pathlib import Path

import pytest

from eolfi.core.evidence import EvidenceStore
from tests.elfgen import build_elf64


# ======================================================================== parsers y core
@pytest.mark.parametrize("flags", [0, 1, 2], ids=["denso", "sparse", "offset16"])
def test_arsc_all_index_layouts(flags):
    from eolfi.providers.arsc import resolve
    from tests.fixtures import build_arsc

    got = resolve(build_arsc(flags), [0x7F010000, 0x7F010001, 0x7F010002])
    assert got[0x7F010000]["value"] == "Demo Eolfi"
    assert got[0x7F010001]["value"] == "@0x7f010000"
    assert 0x7F010002 not in got


def test_strings_crossing_block_boundaries(monkeypatch, tmp_path):
    """Una cadena partida entre dos bloques de lectura se cuenta una sola vez y entera."""
    from eolfi.providers import strings as S

    monkeypatch.setattr(S, "CHUNK", 16)
    f = tmp_path / "x.bin"
    f.write_bytes(b"\x00" * 10 + b"CADENA_LARGA_QUE_CRUZA" + b"\x00" + b"otra1" + b"\x00")
    [r] = S.StringsProvider().run(str(f))
    assert r["result"]["count"] == 2
    assert r["result"]["sample"] == ["CADENA_LARGA_QUE_CRUZA", "otra1"]


def test_slim_functions_tolerates_odd_sizes():
    from eolfi.providers.external import MAX_FUNCTIONS, _slim_functions

    out = _slim_functions([{"name": "a", "size": "12"}, {"name": "b", "size": 40}, {"name": "c"}])
    assert [f["name"] for f in out["functions"]][0] == "b" and out["count"] == 3
    big = _slim_functions([{"name": str(i), "size": i} for i in range(MAX_FUNCTIONS + 3)])
    assert big["truncated"] and len(big["functions"]) == MAX_FUNCTIONS


def test_fuzz_file_survives_and_cleans_up(tmp_path, monkeypatch):
    import tempfile

    from eolfi.security.resilience import fuzz_file

    seed = tmp_path / "seed.elf"
    seed.write_bytes(build_elf64())
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    r = fuzz_file(str(seed), EvidenceStore(str(tmp_path / "e.db")), iters=4, timeout=60)
    assert r["survived"] and r["iterations"] == 4
    if not r["repro_cases"]:
        assert not list((tmp_path / "tmp").glob("eolfi-fuzz-*"))


def test_sarif_with_hostile_imported_package(tmp_path):
    """Un paquete importado con resultados raros no tumba SARIF ni STIX."""
    from eolfi.core.models import Authority, Confidence, Evidence
    from eolfi.core.sarif import build_sarif
    from eolfi.core.stix import build_stix

    s = EvidenceStore(str(tmp_path / "e.db"))
    for op, res in [("pe_security", {"aslr": "quizá"}), ("detect_capabilities", {"rules": "no-lista", "attack": {}}),
                    ("android_manifest", {"security_findings": [None, 3, "x"]}), ("web_sourcemaps", [1, 2])]:
        s.add_evidence(Evidence(subject="a" * 64, provider="p", provider_version="1", operation=op, params={},
                                result=res, authority=list(Authority)[0], confidence=list(Confidence)[0]))
    assert build_sarif(s)["runs"]
    assert build_stix(s, {})["objects"]


@pytest.mark.parametrize("kind", ["axml_pools", "arsc_types", "macho_cmds"])
def test_directed_fuzz_repeated_structures(kind):
    """El fuzz de mutación no fabrica estructuras repetidas: estas sí. Deben fallar rápido y limpio."""
    from eolfi.providers.binfmt import ParseError

    if kind == "axml_pools":
        from eolfi.providers.axml import parse_axml

        pool = struct.pack("<HHIIIII", 0x0001, 28, 28 + 4 * 1000, 1000, 0, 28 + 4 * 1000, 0) + b"\x00" * 4000
        data = struct.pack("<HHI", 0x0003, 8, 8 + len(pool) * 300) + pool * 300
        fn = lambda: parse_axml(data)  # noqa: E731
    elif kind == "arsc_types":
        from eolfi.providers.arsc import resolve
        from tests.fixtures import build_arsc

        base = bytearray(build_arsc())
        fn = lambda: resolve(bytes(base) + bytes(base[12:]) * 200, [0x7F010000])  # noqa: E731
    else:
        from eolfi.providers.macho import parse_macho
        from tests.fixtures import build_macho64

        thin = bytearray(build_macho64())
        struct.pack_into("<I", thin, 16, 0xFFFF)   # ncmds enorme
        fn = lambda: parse_macho(bytes(thin))  # noqa: E731
    t = time.time()
    try:
        fn()
    except ParseError:
        pass
    assert time.time() - t < 3


# ======================================================================== CLI
def test_cli_triage_export_import_roundtrip(tmp_path, capsys, monkeypatch):
    from eolfi import cli

    monkeypatch.chdir(tmp_path)
    f = tmp_path / "a.elf"
    f.write_bytes(build_elf64())
    a, b = str(tmp_path / "a.db"), str(tmp_path / "b.db")
    assert cli.main(["--db", a, "triage", str(f), "--local"]) in (0, None)
    assert cli.main(["--db", a, "export", str(tmp_path / "p.json")]) in (0, None)
    assert cli.main(["--db", b, "import", str(tmp_path / "p.json")]) in (0, None)
    capsys.readouterr()
    assert cli.main(["--db", b, "evidence"]) in (0, None)
    assert "elf_headers" in capsys.readouterr().out


# ======================================================================== servidor
def test_upload_with_provider_selection_and_job_eviction(tmp_path):
    from eolfi.server import EolfiApp

    app = EolfiApp(str(tmp_path / "e.db"), tmp_path / "s")
    import io

    data = build_elf64()
    up = app.store_upload(io.BytesIO(data), len(data), "x.elf")
    rep = app.triage_path({"upload": up["upload"], "name": "x.elf", "mode": "local", "providers": ["eolfi.triage"]})
    assert rep["providers_run"] == ["eolfi.triage"]
    with pytest.raises(Exception):
        app.triage_path({"upload": up["upload"], "mode": "local", "providers": ["no.existe"]})
    app.MAX_JOBS = 3
    app.create = lambda body: {"ok": True}
    ids = [app.start_job({"kind": "create", "body": {"name": str(i)}})["job_id"] for i in range(6)]
    for _ in range(100):
        if all(app.jobs.get(i, {}).get("status", "done") == "done" for i in ids):
            break
        time.sleep(0.02)
    app.start_job({"kind": "create", "body": {"name": "último"}})
    assert len(app.jobs) <= 4 and ids[0] not in app.jobs


def test_guess_folder_does_not_depend_on_this_machine(tmp_path, monkeypatch):
    from eolfi.flows import create_flow

    monkeypatch.setattr(create_flow.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(create_flow, "_local_drive", lambda d: False)
    (tmp_path / "MiProyecto").mkdir()
    assert create_flow.guess_folder("MiProyecto") == (tmp_path / "MiProyecto").resolve()
    assert create_flow.guess_folder("NoExiste") is None
    assert create_flow.guess_folder("../fuera") is None


def test_backup_folder_skips_dependencies_and_refuses_roots(tmp_path):
    from eolfi.flows.create_flow import backup_folder

    src = tmp_path / "app"
    (src / "node_modules" / "x").mkdir(parents=True)
    (src / "src").mkdir()
    (src / "src" / "a.js").write_text("1", encoding="utf-8")
    dst = backup_folder(src)
    assert (dst / "src" / "a.js").read_text(encoding="utf-8") == "1" and not (dst / "node_modules").exists()
    with pytest.raises(ValueError):
        backup_folder(Path(tmp_path.anchor))


# ======================================================================== generador
def test_pin_nuget_versions_with_long_output(tmp_path, monkeypatch):
    """La salida de «dotnet list package» puede pasar de 2500 caracteres: se lee entera."""
    from eolfi.generador import verify as V

    (tmp_path / "src" / "App").mkdir(parents=True)
    proj = tmp_path / "src" / "App" / "App.csproj"
    proj.write_text('<Project><ItemGroup><PackageReference Include="Avalonia" Version="*" /></ItemGroup></Project>',
                    encoding="utf-8")
    doc = {"projects": [{"frameworks": [{"topLevelPackages": [{"id": "Avalonia", "resolvedVersion": "11.3.0"}]
                                          + [{"id": f"P{i}", "resolvedVersion": "1.0"} for i in range(300)]}]}]}
    monkeypatch.setattr(V, "_run", lambda *a, **k: {"tail": "aviso\n" + json.dumps(doc), "exit": 0})
    got = V.pin_nuget_versions(tmp_path, "dotnet")
    assert got["Avalonia"] == "11.3.0" and 'Version="11.3.0"' in proj.read_text(encoding="utf-8")


@pytest.mark.skipif(os.name == "nt", reason="killpg solo en POSIX")
def test_kill_tree_posix(tmp_path):
    from eolfi.generador.verify import _run

    child = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); time.sleep(60)"
    t = time.time()
    assert _run([sys.executable, "-c", child], tmp_path, timeout=2)["tail"] == "timeout"
    assert time.time() - t < 20


# ======================================================================== sites
def test_manifest_parsers():
    from eolfi.sites.repo import parse_csproj, parse_go_mod, parse_gradle, parse_pubspec

    deps, info = parse_go_mod("module x\n\ngo 1.22\n\nrequire (\n\tgithub.com/a/b v1\n\tgithub.com/c/d v2 // indirect\n)\n")
    assert deps == {"github.com/a/b", "github.com/c/d"} and info["module"] == "x"
    n, info = parse_csproj('<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><PackageReference Include="Avalonia" /></ItemGroup>'
                           '<PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
    assert "avalonia" in n and info["target_framework"] == "net10.0"
    assert "androidx.core:core-ktx" in parse_gradle('implementation "androidx.core:core-ktx:1.0"')
    assert parse_pubspec("name: x\ndependencies:\n  flutter:\n    sdk: flutter\n  http: ^1.0\n") >= {"flutter", "http"}


def test_disk_loader_never_leaves_the_site(tmp_path):
    from eolfi.sites.webpage import DiskLoader

    (tmp_path / "site").mkdir()
    (tmp_path / "secreto.txt").write_text("no", encoding="utf-8")
    (tmp_path / "site" / "a.css").write_text("x", encoding="utf-8")
    d = DiskLoader(tmp_path / "site")
    assert d.load((tmp_path / "site" / "a.css").as_uri()).text == "x"
    assert d.load((tmp_path / "secreto.txt").as_uri()).error


def test_five_megabytes_of_newlines_are_fast(tmp_path):
    from eolfi.sites.webpage import analyze_web

    (tmp_path / "index.html").write_text("<html><body>" + "\n" * 5_000_000 + "<h1>x</h1></body></html>",
                                         encoding="utf-8")
    t = time.time()
    analyze_web(str(tmp_path / "index.html"))
    assert time.time() - t < 10
