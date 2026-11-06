import json
import sys

from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Status
from eolfi.core.sarif import build_sarif
from eolfi.flows.diff_flow import run_diff, split_command
from eolfi.flows.triage_flow import run_triage
from eolfi.providers.base import Provider
from eolfi.providers.binfmt import BinaryFormatProvider
from eolfi.providers.triage import FileTriageProvider
from tests.elfgen import build_elf64


class Boom(Provider):
    name = "boom"

    def available(self):
        return True

    def run(self, target):
        raise RuntimeError("kaput")


def test_triage_isolates_failing_provider(tmp_path):
    f = tmp_path / "a.elf"
    f.write_bytes(build_elf64())
    s = EvidenceStore(":memory:")
    rep = run_triage(str(f), s, [FileTriageProvider(), Boom(), BinaryFormatProvider()])
    assert rep["providers_failed"] == ["boom"]
    assert rep["providers_run"] == ["eolfi.triage", "eolfi.binfmt"]
    assert rep["summary"]["format"] == "elf"
    assert rep["summary"]["mitigations"]["pie"] is True
    # Pregunta estable (sin el texto del error, que cambia en cada ejecución; B15).
    assert any("'boom' falló" in i["question"] for i in s.list_incognitas())


def _script(path, body):
    path.write_text(body, encoding="utf-8")
    return path


def _cmd(script):
    return [sys.executable, str(script), "{input}"]


def test_diff_open_and_close(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for i, txt in enumerate(["hola", "mundo", "", "ÁÉÍ"]):
        (corpus / f"in{i}.txt").write_text(txt, encoding="utf-8")
    ref = _script(tmp_path / "ref.py",
                  "import sys\nd=open(sys.argv[1],'rb').read()\nprint(len(d))\nsys.exit(1 if not d else 0)\n")
    bad = _script(tmp_path / "cand.py", "import sys\nd=open(sys.argv[1],'rb').read()\nprint(len(d))\n")
    s = EvidenceStore(":memory:")

    rep = run_diff(_cmd(ref), _cmd(bad), corpus, s)
    assert rep["passed"] is False
    assert rep["mismatches"] == 1 and rep["equivalent"] == 3
    assert rep["mismatched_inputs"] == ["in2.txt"]
    assert len(s.list_incognitas(Status.OPEN)) == 1

    # Arreglamos el candidato: la incógnita se cierra sola.
    _script(tmp_path / "cand.py",
            "import sys\nd=open(sys.argv[1],'rb').read()\nprint(len(d))\nsys.exit(1 if not d else 0)\n")
    rep2 = run_diff(_cmd(ref), _cmd(bad), corpus, s)
    assert rep2["passed"] is True and rep2["incognitas_closed"] == 1
    assert s.list_incognitas(Status.OPEN) == []
    # Cambió el candidato (otra huella en params): no es un "conflicto".
    assert not any("Conflicto" in i["question"] for i in s.list_incognitas())


def test_diff_stdin_and_mutation(tmp_path):
    seed = tmp_path / "seed.bin"
    seed.write_bytes(b"abcdef" * 10)
    echo = _script(tmp_path / "echo.py",
                   "import sys,hashlib\nprint(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())\n")
    s = EvidenceStore(":memory:")
    cmd = [sys.executable, str(echo)]
    rep = run_diff(cmd, cmd, seed, s, mutate=5)
    assert rep["total"] == 6 and rep["passed"] is True


def test_split_command_windows_paths():
    assert split_command('"C:\\Program Files\\x.exe" --a {input}') == ["C:\\Program Files\\x.exe", "--a", "{input}"] \
        or sys.platform != "win32"


def test_sarif_structure(tmp_path):
    f = tmp_path / "a.elf"
    f.write_bytes(build_elf64())
    s = EvidenceStore(":memory:")
    run_triage(str(f), s, [FileTriageProvider(), Boom(), BinaryFormatProvider()])
    doc = build_sarif(s, [f])
    assert doc["version"] == "2.1.0"
    names = {r["tool"]["driver"]["name"] for r in doc["runs"]}
    assert {"eolfi.triage", "eolfi.binfmt", "eolfi"} <= names
    for run in doc["runs"]:
        rule_ids = [r["id"] for r in run["tool"]["driver"]["rules"]]
        for res in run["results"]:
            assert rule_ids[res["ruleIndex"]] == res["ruleId"]
            loc = res["locations"][0]["physicalLocation"]["artifactLocation"]
            assert loc["uri"].startswith("file:")
            assert run["artifacts"][loc["index"]]["hashes"]["sha-256"]
    inc = next(r for r in doc["runs"] if r["tool"]["driver"]["name"] == "eolfi")
    assert any(r["kind"] == "fail" and r["level"] == "warning" for r in inc["results"])
    json.dumps(doc)  # serializable


def test_create_over_source_makes_backup(tmp_path):
    from pathlib import Path
    from eolfi.flows.create_flow import create_project
    from tests.fixtures import build_site
    site = Path(build_site(tmp_path / "site"))
    (site / "mio.txt").write_text("original", encoding="utf-8")
    store = EvidenceStore(str(tmp_path / "e.db"))
    import pytest
    from eolfi.flows.create_flow import OverwriteSourceError
    with pytest.raises(OverwriteSourceError):   # sin confirmación explícita no se toca el origen
        create_project([str(site)], store, site, name="Sitio", target="static")
    r = create_project([str(site)], store, site, name="Sitio", target="static", do_verify=True, force=True)
    backup = Path(r["backup"])
    assert backup.name.startswith("site.eolfi-backup-")
    assert (backup / "mio.txt").read_text(encoding="utf-8") == "original"
    # Se verificó en una carpeta limpia (sin mio.txt ni restos del original) y luego se copió.
    assert r["verification"]["ok"], r["verification"]
    assert (site / "index.html").is_file() and (site / "mio.txt").read_text(encoding="utf-8") == "original"


def test_fs_list(tmp_path):
    from eolfi.server import EolfiApp as App
    (tmp_path / "a").mkdir()
    (tmp_path / "b.txt").write_text("x")
    app = App(str(tmp_path / "e.db"), tmp_path / "s", roots=[])
    r = app.fs_list({"path": str(tmp_path)})
    assert [d["name"] for d in r["dirs"]] == ["a"]
    assert app.fs_list({})["dirs"]
