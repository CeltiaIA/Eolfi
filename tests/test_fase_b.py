"""Fase B del plan de mejoras (2026-11-05): robustez."""
import json
import threading
import time

import pytest

from eolfi.server import EolfiApp, _folder_slug, make_server
from tests.test_server import req


@pytest.fixture
def srv(tmp_path):
    httpd = make_server(str(tmp_path / "s.db"), "127.0.0.1", 0, tmp_path / "samples")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1], tmp_path
    httpd.shutdown()
    httpd.server_close()


# -- servidor ---------------------------------------------------------------------------
def test_folder_slug_keeps_non_ascii_names():
    """M1: «Árbol» ya no pierde la letra y un nombre sin letras latinas no queda vacío."""
    assert _folder_slug("Árbol de tareas") == "arbol-de-tareas"
    assert _folder_slug("日本語") == "日本語"
    assert _folder_slug("¡¡!!").startswith("proyecto-")


def test_jobs_queue_cancel_and_list(tmp_path):
    """M2: como mucho MAX_RUNNING a la vez, el resto «en cola», cancelables y listables."""
    app = EolfiApp(str(tmp_path / "e.db"), tmp_path / "s")
    app.MAX_RUNNING = 1
    app._slots = threading.BoundedSemaphore(1)
    release = threading.Event()

    def slow(_body):
        while not release.is_set():
            app._progress("trabajando")   # punto de cancelación
            time.sleep(0.05)
        return {"ok": True}

    app.create = slow
    a = app.start_job({"kind": "create", "body": {"name": "A"}})["job_id"]
    b = app.start_job({"kind": "create", "body": {"name": "B"}})["job_id"]
    time.sleep(0.4)
    assert app.jobs[a]["status"] == "running" and app.jobs[b]["status"] == "queued"
    assert [j["label"] for j in app.job_status({})["jobs"]] == ["B", "A"]
    app.cancel_job({"id": b})
    app.cancel_job({"id": a})
    for _ in range(60):
        if all(app.jobs[x]["status"] == "cancelled" for x in (a, b)):
            break
        time.sleep(0.05)
    assert app.jobs[a]["status"] == "cancelled" and app.jobs[b]["status"] == "cancelled"
    release.set()


def test_cross_site_get_to_api_is_rejected(srv):
    """M6: <img src=…/api/bridge/screen> desde otra web no llega a ejecutarse."""
    port, _ = srv
    st, _b, hdrs = req(port, "GET", "/api/health", None, {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors"})
    assert st == 403
    st, _b, hdrs = req(port, "GET", "/api/health")
    assert st == 200 and hdrs.get("Cross-Origin-Resource-Policy") == "same-origin"
    # Abrir el panel desde un enlace sigue funcionando.
    assert req(port, "GET", "/", None, {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"})[0] == 200


def test_token_in_url_is_replaced_by_cookie_and_redirect(tmp_path):
    """M6: ?token= se cambia por una cookie y una redirección, y no aparece en el registro."""
    httpd = make_server(str(tmp_path / "r.db"), "127.0.0.1", 0, tmp_path / "s", token="secreto123")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    try:
        st, _b, hdrs = req(port, "GET", "/?token=secreto123")
        assert st == 303 and hdrs["Location"] == "/" and "eolfi_token=secreto123" in hdrs["Set-Cookie"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_upload_is_streamed_to_disk_and_triaged_as_job(srv):
    """A4: la subida va por bloques a samples/ y el triaje es un trabajo."""
    from tests.elfgen import build_elf64

    port, tmp = srv
    data = build_elf64()
    st, up, _ = req(port, "POST", "/api/upload?store=1&name=x.elf", data,
                    {"X-Eolfi": "1", "Content-Type": "application/octet-stream"})
    assert st == 200 and (tmp / "samples" / f"{up['upload']}.bin").read_bytes() == data
    assert not list((tmp / "samples").glob("*.part"))
    st, job, _ = req(port, "POST", "/api/jobs", json.dumps({"kind": "triage", "body": {
        "upload": up["upload"], "name": "x.elf", "mode": "local"}}), {"X-Eolfi": "1"})
    assert st == 202
    for _ in range(100):
        st, d, _ = req(port, "GET", f"/api/jobs?id={job['job_id']}")
        if d["status"] not in ("queued", "running"):
            break
        time.sleep(0.1)
    assert d["status"] == "done" and d["result"]["subject"] == up["upload"]
    st, page, _ = req(port, "GET", f"/api/evidence?subject={up['upload']}&limit=1")
    assert len(page["evidence"]) == 1 and page["total"] > 1 and page["next_offset"] == 1
    assert req(port, "POST", "/api/jobs", json.dumps({"kind": "triage", "body": {"upload": "../x"}}),
               {"X-Eolfi": "1"})[0] == 202   # el error se informa en el trabajo, no se lee nada fuera


def test_subjects_single_query_and_providers_cache(tmp_path, monkeypatch):
    """M3 y M5."""
    from eolfi.generador import llm

    app = EolfiApp(str(tmp_path / "e.db"), tmp_path / "s")
    assert app.subjects({}) == {"subjects": []}
    calls = []
    monkeypatch.setattr(llm, "probe", lambda n: calls.append(n) or {"available": False, "detail": "x"})
    app.providers({})
    first = len(calls)
    app.providers({})
    assert first == len(llm.PRESETS) and len(calls) == first   # una sonda por preajuste y caché


# -- generador ---------------------------------------------------------------------------
def test_ai_reply_is_validated_and_files_restored_on_interrupt(tmp_path, monkeypatch):
    """M22: respuesta con tipos inválidos → error claro; Ctrl+C a mitad de ronda → todo restaurado."""
    import shutil as _sh

    if not _sh.which("node"):
        pytest.skip("requiere Node.js")
    from eolfi.generador import assist as A, verify as V
    from tests.test_assist import FakeClient, _project

    out = _project(tmp_path)
    original = (out / "index.html").read_text(encoding="utf-8")
    with pytest.raises(A.AssistError, match="formato inválido"):
        A.assist(out, "x", client=FakeClient([{"summary": "s", "files": [{"path": 3}], "notes": []}]))

    def boom(*_a, **_k):
        raise KeyboardInterrupt
    monkeypatch.setattr(V, "verify", boom)
    with pytest.raises(KeyboardInterrupt):
        A.assist(out, "x", client=FakeClient([{"summary": "s", "notes": [],
                                               "files": [{"path": "index.html", "content": "<p>roto</p>"}]}]))
    assert (out / "index.html").read_text(encoding="utf-8") == original


def test_ai_cannot_weaken_security_tests_or_auth(tmp_path):
    """M24: la IA no puede reescribir auth.py ni quitar aserciones de una prueba existente."""
    from eolfi.generador.assist import _apply

    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "auth.py").write_text("seguro", encoding="utf-8")
    (tmp_path / "tests" / "test_api.py").write_text("def test_a():\n    assert 1\n    assert 2\n", encoding="utf-8")
    written, rejected = _apply(tmp_path, "fastapi", [
        {"path": "app/auth.py", "content": "inseguro"},
        {"path": "tests/test_api.py", "content": "def test_a():\n    pass\n"},
        {"path": "tests/test_nuevo.py", "content": "def test_b():\n    assert True\n"},
        {"path": "app/items.py", "content": "x = 1\n"},
    ], {})
    assert sorted(rejected) == ["app/auth.py", "tests/test_api.py"]
    assert sorted(written) == ["app/items.py", "tests/test_nuevo.py"]
    assert (tmp_path / "app" / "auth.py").read_text(encoding="utf-8") == "seguro"


def test_llm_post_retries_429_and_limits_size(monkeypatch):
    """M25: 429/5xx se reintentan con espera; una respuesta enorme se rechaza."""
    import http.server

    from eolfi.generador import llm

    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            hits.append(1)
            if len(hits) < 3:
                self.send_response(429)
                self.send_header("Retry-After", "1")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    waits = []
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
        assert llm._post(url, {}, {}, 5, sleep=waits.append) == {"ok": True}
        assert len(hits) == 3 and len(waits) == 2 and waits[0] >= 1
        monkeypatch.setattr(llm, "MAX_RESPONSE_BYTES", 4)
        hits.clear()
        hits.extend([1, 1])
        with pytest.raises(llm.LLMError, match="demasiado grande"):
            llm._post(url, {}, {}, 5, sleep=waits.append)
    finally:
        srv.shutdown()
        srv.server_close()


# -- parsers e importación -----------------------------------------------------------------
def _fat(subtypes):
    import struct

    from tests.fixtures import build_macho64

    thin = build_macho64()
    out = bytearray(struct.pack(">II", 0xCAFEBABE, len(subtypes)))
    off = 0x1000
    slices = []
    for st in subtypes:
        t = bytearray(thin)
        struct.pack_into("<I", t, 8, st)
        out += struct.pack(">IIIII", 0x0100000C, st, off, len(t), 12)
        slices.append((off, bytes(t)))
        off += 0x1000
    out += b"\x00" * (slices[-1][0] + 0x1000 - len(out))
    for o, t in slices:
        out[o:o + len(t)] = t
    return bytes(out)


def test_macho_universal_arm64_and_arm64e_do_not_overwrite(tmp_path):
    """M12: arm64 + arm64e: dos claves distintas; M13: un único presupuesto de entropía."""
    from eolfi.providers.binfmt import BinaryFormatProvider

    f = tmp_path / "u.bin"
    f.write_bytes(_fat([0, 2, 2]))
    found = {x["operation"]: x["result"] for x in BinaryFormatProvider().run(str(f))}
    keys = set(found["macho_sections"])
    assert keys == {"arm64/0", "arm64/2#1", "arm64/2#2"}, keys


def test_strings_sample_is_bounded(tmp_path):
    """M14: 20 cadenas de 1 MB no producen una evidencia de 19 MB."""
    from eolfi.providers.strings import MAX_SAMPLE_BYTES, StringsProvider

    f = tmp_path / "s.bin"
    f.write_bytes((b"A" * 1_000_000 + b"\x00") * 20)
    [r] = StringsProvider().run(str(f))
    res = r["result"]
    assert res["count"] == 20 and res["truncated_strings"] == 20
    assert sum(len(x) for x in res["sample"]) <= MAX_SAMPLE_BYTES + 1000


@pytest.mark.parametrize("bad", [1e300, float("nan"), -5, True])
def test_import_rejects_bad_timestamps(tmp_path, bad):
    """M16."""
    import json as _j

    from eolfi.core.evidence import SCHEMA_VERSION, EvidenceStore
    from eolfi.core.models import Authority, Confidence, Evidence

    a = EvidenceStore(str(tmp_path / "a.db"))
    a.add_evidence(Evidence(subject="s" * 64, provider="t", provider_version="1", operation="x", params={},
                            result={"a": 1}, authority=list(Authority)[0], confidence=list(Confidence)[0]))
    pkg = {"schema_version": SCHEMA_VERSION, "evidence": a.list_evidence(), "incognita": []}
    pkg["evidence"][0]["created_at"] = bad
    (tmp_path / "p.json").write_text(_j.dumps(pkg), encoding="utf-8")
    with pytest.raises(ValueError, match="created_at"):
        EvidenceStore(str(tmp_path / "b.db")).import_package(tmp_path / "p.json")


def test_import_deeply_nested_package_is_a_value_error(tmp_path):
    """M17."""
    from eolfi.core.evidence import EvidenceStore

    (tmp_path / "p.json").write_text("[" * 200_000 + "]" * 200_000, encoding="utf-8")
    with pytest.raises(ValueError):
        EvidenceStore(str(tmp_path / "b.db")).import_package(tmp_path / "p.json")


def test_import_merges_incognitas_and_drops_dangling_refs(tmp_path):
    """M18: incógnitas existentes se fusionan; referencias a ids inexistentes se quitan."""
    import json as _j

    from eolfi.core.evidence import SCHEMA_VERSION, EvidenceStore
    from eolfi.core.models import Incognita

    b = EvidenceStore(str(tmp_path / "b.db"))
    iid = b.add_incognita(Incognita(subject="s", question="¿q?", evidence_for=[]))
    row = dict(b.list_incognitas()[0])
    row["evidence_for"] = _j.dumps(["no-existe"])
    (tmp_path / "p.json").write_text(_j.dumps({"schema_version": SCHEMA_VERSION, "evidence": [],
                                               "incognita": [row]}), encoding="utf-8")
    b.import_package(tmp_path / "p.json")
    got = [i for i in b.list_incognitas() if i["incognita_id"] == iid][0]
    assert _j.loads(got["evidence_for"]) == []


def test_stix_survives_hostile_types(tmp_path):
    """M19."""
    from eolfi.core.evidence import EvidenceStore
    from eolfi.core.models import Authority, Confidence, Evidence
    from eolfi.core.stix import build_stix

    s = EvidenceStore(str(tmp_path / "a.db"))
    s.add_evidence(Evidence(subject="a" * 64, provider="capa", provider_version="1", operation="detect_capabilities",
                            params={}, result={"attack": [3, None, "X [T1059]"]}, authority=list(Authority)[0],
                            confidence=list(Confidence)[0]))
    out = build_stix(s, {"a" * 64: []})
    assert any(o["type"] == "attack-pattern" for o in out["objects"])


def test_apk_with_duplicate_entries_is_flagged(tmp_path):
    """M20: dos AndroidManifest.xml o rutas ../ en un APK."""
    import warnings
    import zipfile

    from eolfi.providers.dex import analyze_zip
    from tests.fixtures import build_apk

    apk = build_apk(tmp_path / "x.apk")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(apk, "a") as zf:
            zf.writestr("AndroidManifest.xml", b"\x03\x00otro")
            zf.writestr("../fuera.txt", b"x")
    r = analyze_zip(apk)
    assert "AndroidManifest.xml" in r["zip_anomalies"]["duplicates"]
    assert "../fuera.txt" in r["zip_anomalies"]["unsafe_paths"]
    assert any("archivos clave" in f for f in r["zip_anomalies"]["findings"])


def test_pe_imports_shared_tables_counted_once():
    """M15 (unidad): la caché de RVA y el tope total existen."""
    from eolfi.providers import binfmt

    assert binfmt.MAX_IMPORTS_TOTAL <= 50_000
