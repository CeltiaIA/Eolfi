import http.client
import json
import threading

import pytest

from eolfi.server import make_server
from tests.elfgen import build_elf64


@pytest.fixture
def srv(tmp_path):
    httpd = make_server(str(tmp_path / "s.db"), "127.0.0.1", 0, tmp_path / "samples")
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd.server_address[1], tmp_path
    httpd.shutdown()
    httpd.server_close()


def req(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    c.close()
    ctype = r.getheader("Content-Type", "")
    return r.status, (json.loads(data) if "json" in ctype else data), dict(r.getheaders())


def test_static_and_health(srv):
    port, _ = srv
    st, body, hdrs = req(port, "GET", "/")
    assert st == 200 and b"<title>Eolfi" in body
    assert b'id="create-verify" checked disabled' in body
    assert "script-src 'self'" in hdrs["Content-Security-Policy"]
    assert req(port, "GET", "/app.js")[0] == 200
    for path in ("/runtime.js", "/subjects.js"):
        status, body, headers = req(port, "GET", path)
        assert status == 200 and body
        assert headers["Content-Type"].startswith("text/javascript")
    st, h, _ = req(port, "GET", "/api/health")
    assert st == 200 and h["ok"] is True


@pytest.mark.parametrize("disconnect", [BrokenPipeError, ConnectionResetError, ConnectionAbortedError])
def test_response_write_ignores_closed_client(tmp_path, disconnect):
    from types import SimpleNamespace

    httpd = make_server(str(tmp_path / "s.db"), "127.0.0.1", 0, tmp_path / "samples")
    response = SimpleNamespace(close_connection=False, command="GET")
    response.send_response = lambda _status: None
    response.send_header = lambda _name, _value: None
    response.end_headers = lambda: None

    def abort(_body):
        raise disconnect("the client closed the connection")

    response.wfile = SimpleNamespace(write=abort)
    try:
        httpd.RequestHandlerClass._send(response, 200, b"body", "text/plain")
        assert response.close_connection is True
    finally:
        httpd.server_close()


def test_upload_triage_and_browse(srv):
    port, tmp = srv
    st, rep, _ = req(port, "POST", "/api/upload?name=prueba%3Cb%3E.elf&mode=local",
                     body=build_elf64(), headers={"X-Eolfi": "1"})
    assert st == 200, rep
    assert rep["summary"]["format"] == "elf"
    sha = rep["subject"]
    assert (tmp / "samples" / f"{sha}.bin").is_file()          # nombre por huella

    _, subs, _ = req(port, "GET", "/api/subjects")
    s = subs["subjects"][0]
    assert s["subject"] == sha and s["format"] == "elf"
    assert s["names"] == ["prueba_b_.elf"]                        # nombre saneado

    _, ev, _ = req(port, "GET", f"/api/evidence?subject={sha}&operation=elf_security")
    assert ev["evidence"][0]["result"]["pie"] is True

    _, sarif, hdrs = req(port, "GET", "/api/export.sarif")
    assert sarif["version"] == "2.1.0"
    assert "attachment" in hdrs["Content-Disposition"]


def test_resolve_flow(srv, monkeypatch):
    port, tmp = srv
    # La prueba simula que capa y rizin NO están (en el equipo pueden estar instalados).
    from eolfi.providers import external

    monkeypatch.setenv("EOLFI_TOOLS_DIR", str(tmp / "sin-herramientas"))
    monkeypatch.setattr(external.shutil, "which", lambda *a, **k: None)
    from eolfi.flows.triage_flow import DEFAULT_PROVIDERS

    for prov in DEFAULT_PROVIDERS:
        if isinstance(prov, external.ExternalCommandProvider):
            monkeypatch.setattr(prov, "_resolved", None)
    target = tmp / "x.bin"
    target.write_bytes(b"\x00" * 10)
    st, rep, _ = req(port, "POST", "/api/triage", json.dumps({"path": str(target), "mode": "default"}),
                     {"X-Eolfi": "1"})
    assert st == 200
    _, incs, _ = req(port, "GET", f"/api/incognitas?subject={rep['subject']}&status=open")
    assert incs["incognitas"], "capa/rizin no disponibles deberían abrir incógnitas"
    iid = incs["incognitas"][0]["incognita_id"]
    st, _, _ = req(port, "POST", f"/api/incognitas/{iid}/resolve", "{}", {"X-Eolfi": "1"})
    assert st == 200
    _, incs2, _ = req(port, "GET", f"/api/incognitas?subject={rep['subject']}&status=resolved")
    assert any(i["incognita_id"] == iid for i in incs2["incognitas"])


def test_post_requires_custom_header(srv):
    port, _ = srv
    st, body, _ = req(port, "POST", "/api/triage", json.dumps({"path": "C:/x"}))
    assert st == 403 and "X-Eolfi" in body["error"]


def test_foreign_host_rejected(srv):
    port, _ = srv
    st, _, _ = req(port, "GET", "/api/subjects", headers={"Host": "evil.example:80"})
    assert st == 421


def test_errors_are_json(srv):
    port, _ = srv
    assert req(port, "GET", "/api/nada")[0] == 404
    assert req(port, "GET", "/api/incognitas?status=raro")[0] == 400
    st, body, _ = req(port, "POST", "/api/triage", "{no json", {"X-Eolfi": "1"})
    assert st == 400 and "JSON" in body["error"]
    assert req(port, "POST", "/api/triage", json.dumps({"path": "Z:/no/existe"}), {"X-Eolfi": "1"})[0] == 404
    assert req(port, "DELETE", "/api/subjects")[0] == 403          # sin X-Eolfi: anti-CSRF primero
    assert req(port, "DELETE", "/api/subjects", None, {"X-Eolfi": "1"})[0] == 405


def test_rejected_post_body_is_consumed(srv):
    """Un POST rechazado no se lee: se cierra la conexión (Connection: close) y el cliente reabre otra."""
    port, _ = srv
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.request("POST", "/api/triage", body=json.dumps({"path": "C:/x"}))
    r = c.getresponse(); r.read()
    assert r.status == 403
    c.request("GET", "/api/health")
    r2 = c.getresponse()
    assert r2.status == 200 and json.loads(r2.read())["ok"]
    c.close()


def test_port_cannot_be_hijacked(srv):
    port, tmp = srv
    with pytest.raises(OSError):
        make_server(str(tmp / "otra.db"), "127.0.0.1", port, tmp / "s2")


def test_learn_create_and_stix(srv):
    from tests.fixtures import build_site

    port, tmp = srv
    site = build_site(tmp / "site")
    st, rep, _ = req(port, "POST", "/api/web", json.dumps({"source": str(site)}), {"X-Eolfi": "1"})
    assert st == 200, rep
    assert rep["summary"]["title"] == "Demo"
    out = tmp / "nuevo"
    st, rep, _ = req(port, "POST", "/api/create",
                     json.dumps({"sources": [rep["subject"]], "name": "Desde API", "target": "static", "out": str(out),
                                 "verify": False}),
                     {"X-Eolfi": "1"})
    assert st == 200, rep
    assert (out / "index.html").is_file() and rep["target"] == "static"
    assert rep["verification"]["ok"] is True  # la API ignora el bypass antiguo y verifica siempre
    st, again, _ = req(port, "POST", "/api/create",
                       json.dumps({"sources": [rep["sources"][0]["subject"]], "target": "static", "out": str(out)}),
                       {"X-Eolfi": "1"})
    assert st == 409                                     # no pisa una carpeta con contenido
    _, subs, _ = req(port, "GET", "/api/subjects")
    kinds = {s["kind"] for s in subs["subjects"]}
    assert {"web", "proyecto"} <= kinds
    st, stix, _ = req(port, "GET", "/api/export.stix")
    assert st == 200 and stix["type"] == "bundle"


def test_cross_site_post_rejected_before_body(srv):
    port, _ = srv
    st, body, _ = req(port, "POST", "/api/triage", json.dumps({"path": "C:/x"}),
                      {"X-Eolfi": "1", "Sec-Fetch-Site": "cross-site"})
    assert st == 403
    st, _, _ = req(port, "POST", "/api/triage", json.dumps({"path": "C:/x"}),
                   {"X-Eolfi": "1", "Origin": "https://evil.example"})
    assert st == 403
    big = "x" * (5 * 1024 * 1024)
    try:   # el servidor responde 413 sin leer el cuerpo y cierra: el cliente puede ver el reset antes
        assert req(port, "POST", "/api/triage", big, {"X-Eolfi": "1"})[0] == 413
    except (ConnectionError, OSError):
        pass
    assert req(port, "GET", "/api/health")[0] == 200   # el servidor sigue vivo


def test_remote_mode_requires_token(tmp_path):
    import threading
    httpd = make_server(str(tmp_path / "r.db"), "127.0.0.1", 0, tmp_path / "s", token="secreto123")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    try:
        assert req(port, "GET", "/api/health")[0] == 401
        assert req(port, "GET", "/api/health?token=malo")[0] == 401
        assert req(port, "GET", "/api/health?token=secreto123")[0] == 200
    finally:
        httpd.shutdown()


def test_resultado_y_registro_sobreviven_a_un_reinicio(tmp_path, monkeypatch):
    """12/11/2026: tras un --reload, una batería de una hora quedó sin resultados (solo se guardaba la petición)."""
    import time as _time

    from eolfi.server import ApiError, EolfiApp
    db = str(tmp_path / "jobs.db")
    app = EolfiApp(db)
    result = {"summary": {"qwen14_q4": {"correctos": 6, "casos": 8}}, "results": [{"case": "palindromo", "passed": True}]}
    monkeypatch.setattr(app, "create", lambda body: (app._progress("qwen14_q4: caso 1/8"), result)[1])
    job_id = app.start_job({"kind": "create", "body": {"name": "prueba"}})["job_id"]
    deadline = _time.time() + 10
    while app.job_status({"id": job_id}).get("status") != "done" and _time.time() < deadline:
        _time.sleep(0.05)
    otra = EolfiApp(db)                                        # el servidor tras un reinicio: sin trabajos en memoria
    stored = otra.job_status({"id": job_id})
    assert stored["status"] == "done" and stored["stored"] is True
    assert stored["result"] == result
    assert any("caso 1/8" in e.get("msg", "") for e in stored["log"])
    try:
        otra.job_status({"id": "no-existe"})
        raise AssertionError("debía dar 404")
    except ApiError as exc:
        assert exc.status == 404


def test_historial_guarda_solo_los_ultimos_4(tmp_path):
    from eolfi.server import EolfiApp
    app = EolfiApp(str(tmp_path / "h.db"))
    for i in range(7):
        app._save_job({"id": f"t{i}", "kind": "create", "status": "done", "started": 1000.0 + i, "finished": 1001.0 + i,
                       "body": {}, "result": {"n": i}, "log": []})
    ids = [j["id"] for j in app.job_status({})["jobs"]]
    assert ids == ["t6", "t5", "t4", "t3"]
    assert app.job_status({"id": "t6"})["result"] == {"n": 6}

