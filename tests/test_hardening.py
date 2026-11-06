"""Regresiones de la auditoría (PLAN_CORRECCIONES.md, fase 1): entradas hostiles terminan rápido y sin tumbar nada."""
import json
import struct
import time

import pytest

from eolfi.providers.binfmt import EntropyBudget, ParseError, Reader


def _pool(offsets: list[int], strings_blob: bytes) -> bytes:
    count = len(offsets)
    header = 28
    strings_start = header + 4 * count
    size = strings_start + len(strings_blob)
    head = struct.pack("<HHIIIIII", 0x0001, header, size, count, 0, 0, strings_start, 0)
    return head + b"".join(struct.pack("<I", o) for o in offsets) + strings_blob


def test_string_pool_repeated_huge_string_is_shared():
    from eolfi.providers.axml import _string_pool
    n = 300_000
    blob = struct.pack("<HH", 0x8000 | (n >> 16), n & 0xFFFF) + "A".encode("utf-16-le") * n
    data = _pool([0] * 2000, blob)
    t = time.time()
    out = _string_pool(Reader(data), 0)
    assert time.time() - t < 2 and len(out) == 2000 and out[0] is out[-1]


def test_string_pool_overlapping_strings_hit_budget():
    from eolfi.providers.axml import _string_pool
    n = 100_000
    blob = b"".join(struct.pack("<H", 0x7FFF) for _ in range(n))   # cada posición "dice" 32767 caracteres
    with pytest.raises(ParseError):
        _string_pool(Reader(_pool([2 * i for i in range(3000)], blob)), 0)


def test_string_out_of_pool_rejected():
    from eolfi.providers.axml import _string_pool
    with pytest.raises(ParseError):
        _string_pool(Reader(_pool([10_000], b"\x01\x00A\x00\x00\x00")), 0)


def test_entropy_budget_caches_and_caps():
    data = bytes(range(256)) * 4096   # 1 MB
    ent = EntropyBudget(data, len(data))
    t = time.time()
    values = [ent.of(0, 1 << 40) for _ in range(400)]
    assert time.time() - t < 3 and values[0] == values[-1] == 8.0
    for i in range(1, 400):   # solapadas pero distintas: el presupuesto corta
        ent.of(i, 1 << 40)
    assert ent.exhausted and ent.of(999, 1 << 40) is None


def test_apk_with_fake_encryption_flag_keeps_inventory(tmp_path):
    from eolfi.providers.dex import analyze_zip
    from tests.fixtures import build_apk
    apk = build_apk(tmp_path / "a.apk")
    raw = bytearray(apk.read_bytes())
    for sig, flag_at in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        i = raw.find(sig)
        while i >= 0:
            raw[i + flag_at] |= 1   # bit 0 = "cifrado"
            i = raw.find(sig, i + 4)
    apk.write_bytes(bytes(raw))
    rep = analyze_zip(apk)   # no lanza RuntimeError
    assert rep["kind"]


def test_hostile_title_and_resources_are_sanitized():
    from eolfi.generador.spec import safe_resource, safe_title
    t = safe_title('X"""\nimport os{alert(1)}<img src=x onerror=y> {{ request.META }} {% debug %} `$x` \\n')
    assert not any(c in t for c in '"`{}<>$\\%\n')
    assert safe_title("") == "Nuevo proyecto"
    for bad in ("auth", "app", "class", "import", "with", "async", "delete", "users"):
        assert not safe_resource(bad), bad
    assert safe_resource("products") and safe_resource("blog-posts")


def test_verify_env_drops_secrets(monkeypatch):
    from eolfi.generador.verify import safe_env
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secreto")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    env = safe_env()
    assert "ANTHROPIC_API_KEY" not in env and "GEMINI_API_KEY" not in env
    assert any(k.upper() == "PATH" for k in env) and env["CI"] == "true"


def test_external_tools_get_safe_staged_target(tmp_path):
    from eolfi.providers.external import CapaProvider, GhidraProvider, check_cmd_safe
    evil = tmp_path / "-c!calc & whoami.exe"
    evil.write_bytes(b"MZ" + b"\0" * 100)
    with CapaProvider()._staged(str(evil)) as staged:
        name = staged.replace("\\", "/").rsplit("/", 1)[1]
        assert name.endswith(".bin") and not name.startswith("-") and "&" not in staged
        assert open(staged, "rb").read(2) == b"MZ"
    for bad in ("a&b", "x|y", "%PATH%", "-c", 'a"b', "a^b"):
        with pytest.raises(ValueError):
            check_cmd_safe(bad)
    assert GhidraProvider(decompile=["main", "entry", "main&calc", "FUN_00401000"]).decompile == \
        ["main", "entry", "FUN_00401000"]


def test_hostile_html_and_css_finish_fast():
    from eolfi.sites.webpage import PageParser, analyze_css, strip_css_comments
    t = time.time()
    p = PageParser()
    p.feed("<button>x" * 20000 + "<label>y" * 20000 + "<div>" * 30000)
    p.close()
    analyze_css([("a.css", "/*a" * 300000)])
    assert time.time() - t < 5
    assert strip_css_comments("a{}/* c */b{}/* abierto") == "a{}b{}"


def test_ssrf_pinned_connection_blocks_private(monkeypatch):
    import socket as s
    from eolfi.sites import fetch
    real = s.getaddrinfo
    monkeypatch.setattr(fetch.socket, "getaddrinfo",
                        lambda host, *a, **k: real("127.0.0.1", *a, **k) if host == "rebind.example" else real(host, *a, **k))
    with pytest.raises(OSError, match="anti-SSRF"):
        fetch._pinned_socket("rebind.example", 80, 5, allow_private=False)
    assert fetch.ip_is_private("100.64.1.1") and fetch.ip_is_private("::ffff:127.0.0.1")
    assert not fetch.ip_is_private("93.184.216.34")
    assert fetch.host_is_private("no-existe.invalid")


def test_clone_rejects_internal_and_options(tmp_path):
    from eolfi.sites.repo import clone
    for url in ("http://169.254.169.254/a/b.git", "https://127.0.0.1/a/b.git", "ext::sh -c x", "-oProxyCommand=x"):
        with pytest.raises(ValueError):
            clone(url, tmp_path)


def test_hostile_manifests_do_not_break_repo_analysis(tmp_path):
    from eolfi.sites.repo import analyze_repo
    (tmp_path / "package.json").write_text('{"dependencies": ["a"], "scripts": "x"}', encoding="utf-8")
    (tmp_path / "composer.json").write_text("[1, 2]", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = [1]\n", encoding="utf-8")
    (tmp_path / "x.json").write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
    _subject, findings = analyze_repo(str(tmp_path))
    man = next(f for f in findings if f["operation"] == "repo_manifests")
    assert len(man["result"]["errors"]) >= 2


def test_profile_matching_is_exact(tmp_path, monkeypatch):
    import subprocess
    from eolfi import cli
    prof = tmp_path / "browser-profile"
    lines = "\n".join([
        f'101|"C:/chrome.exe" --user-data-dir="{prof}" --remote-debugging-port=0',
        f"102|chrome --user-data-dir={prof}2",
        f"103|chrome --user-data-dir={prof} --type=renderer",
        "104|chrome --profile-directory=Default",
        f"105|chrome --user-data-dir {str(prof).replace(chr(92), '/')}",
    ])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, lines, ""))
    assert cli._profile_browsers(prof) == [(101, True), (105, False)]
    def boom(*a, **k):
        raise subprocess.TimeoutExpired("ps", 1)
    monkeypatch.setattr(subprocess, "run", boom)
    assert cli._profile_browsers(prof) == []


def test_assist_paths_need_segment_boundary(tmp_path):
    from eolfi.generador.assist import _allowed, _apply
    assert not _allowed("static", "index.htmlx/evil.js")
    assert not _allowed("expo", "App.tsx2/a.ts")
    assert not _allowed("django", "config/urls.pyx/a.py")
    assert not _allowed("fastapi", "tests/conftest.py")
    assert _allowed("expo", "App.tsx") and _allowed("fastapi", "tests/test_x.py")
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "0001_init.sql").write_text("-- x", encoding="utf-8")
    (tmp_path / "migrations" / "0002_a.sql").write_text("-- y", encoding="utf-8")
    files = [{"path": "migrations/0002_b.sql", "content": "-- dup"},
             {"path": "migrations/0001_otra.sql", "content": "-- vieja"},
             {"path": "migrations/0003_ok.sql", "content": "-- nueva"}]
    written, rejected = _apply(tmp_path.resolve(), "fastapi", files, {})
    assert written == ["migrations/0003_ok.sql"] and len(rejected) == 2


def test_repeated_conflict_reopens_incognita(tmp_path):
    from eolfi.core.evidence import EvidenceStore
    from eolfi.core.models import Incognita, Status
    st = EvidenceStore(str(tmp_path / "e.db"))
    iid = st.add_incognita(Incognita(subject="s", question="q", evidence_for=["a"]))
    st.resolve_incognita(iid, Status.RESOLVED)
    st.add_incognita(Incognita(subject="s", question="q", evidence_for=["b"]))
    row = st.conn.execute("SELECT status, evidence_for FROM incognita WHERE incognita_id=?", (iid,)).fetchone()
    assert row["status"] == "open" and json.loads(row["evidence_for"]) == ["a", "b"]
    st.close()


def test_import_rejects_bad_enums_and_marks_provenance(tmp_path):
    from eolfi.core.evidence import EvidenceStore
    from eolfi.core.models import Authority, Confidence, Evidence
    a = EvidenceStore(str(tmp_path / "a.db"))
    a.add_evidence(Evidence(subject="s", provider="p", provider_version="1", operation="op", params={},
                            result={"x": 1}, authority=Authority.ANALYST_INFERENCE, confidence=Confidence.LOW))
    pkg = tmp_path / "p.json"
    a.export_package(pkg)
    a.close()
    b = EvidenceStore(str(tmp_path / "b.db"))
    assert b.import_package(pkg) == 1
    lim = b.conn.execute("SELECT limitations FROM evidence").fetchone()[0]
    assert "declaradas por el paquete" in lim
    doc = json.loads(pkg.read_text(encoding="utf-8"))
    doc["evidence"][0]["authority"] = "dios"
    pkg.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError):
        EvidenceStore(str(tmp_path / "c.db")).import_package(pkg)


def test_save_collisions_do_not_abort(tmp_path):
    from eolfi.sites.webpage import _save
    assert _save(tmp_path, "s", "https://x.example/a", "uno")
    _save(tmp_path, "s", "https://x.example/a/b.css", "dos")   # no lanza
    p = _save(tmp_path, "s", "https://x.example/con", "tres")
    assert p and p.endswith("con_")


def test_repo_walk_skips_symlinked_files(tmp_path):
    import os
    from eolfi.sites.repo import walk
    secret = tmp_path / "secreto.txt"
    secret.write_text("clave", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("x", encoding="utf-8")
    try:
        os.symlink(secret, repo / "README.md")
    except (OSError, NotImplementedError):
        pytest.skip("sin permiso para crear enlaces simbólicos")
    files, skipped, _ = walk(repo)
    assert files == ["a.txt"] and skipped.get("(enlace simbólico)") == 1
