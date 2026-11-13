import http.client
import json
import threading

import pytest

from eolfi.server import make_server
from tests.elfgen import build_elf64


def test_failed_assisted_creation_is_error_and_keeps_result(tmp_path, monkeypatch):
    from eolfi.server import EolfiApp
    app = EolfiApp(str(tmp_path / 'jobs.db'))
    result = {'assist': {'ok': False, 'restored': True}, 'verification': {'ok': True}}
    monkeypatch.setattr(app, 'create', lambda body: result)
    saved = []
    finished = threading.Event()
    def save(job):
        saved.append(dict(job))
        finished.set()
    monkeypatch.setattr(app, '_save_job', save)
    app.start_job({'kind': 'create', 'body': {}})
    assert finished.wait(5)
    assert saved[-1]['status'] == 'error'
    assert saved[-1]['result'] == result
    assert 'restaurados' in saved[-1]['error']


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
    monkeypatch.setattr(app, "eolas_e2e", lambda body: (app._progress("qwen14_q4: caso 1/8"), result)[1])
    job_id = app.start_job({"kind": "eolas-e2e", "body": {"profiles": ["qwen14_q4"], "suite": True}})["job_id"]
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
        app._save_job({"id": f"t{i}", "kind": "eolas-e2e", "status": "done", "started": 1000.0 + i, "finished": 1001.0 + i,
                       "body": {}, "result": {"n": i}, "log": []})
    ids = [j["id"] for j in app.job_status({})["jobs"]]
    assert ids == ["t6", "t5", "t4", "t3"]
    assert app.job_status({"id": "t6"})["result"] == {"n": 6}


def test_trabajo_de_banco_lleva_etiqueta(tmp_path, monkeypatch):
    from eolfi.server import EolfiApp
    app = EolfiApp(str(tmp_path / "l.db"))
    monkeypatch.setattr(app, "eolas_e2e", lambda body: {})
    jid = app.start_job({"kind": "eolas-e2e", "body": {"battery": "codigo", "profiles": ["qwen14_q3"], "suite": True}})["job_id"]
    assert app.jobs[jid]["label"] == "Banco · codigo · qwen14_q3"


def test_recarga_no_corta_trabajos_si_el_servidor_tarda_en_responder(capsys):
    """12/11/2026: una respuesta lenta se tomaba como «0 trabajos» y la recarga mató una ronda de motores."""
    from eolfi import server

    class Proc:
        def poll(self):
            return None

    readings = iter([None, None, 1, None, 0, 1, 0, 0])
    seen = []
    server._wait_jobs_idle(Proc(), 8777, sleep=lambda s: None,
                           active=lambda port: seen.append(1) or next(readings))
    assert len(seen) == 8                              # solo dos lecturas SEGUIDAS de 0 permiten recargar
    assert "recargaré al terminar" in capsys.readouterr().out

    class Dead:
        def poll(self):
            return 1

    server._wait_jobs_idle(Dead(), 8777, sleep=lambda s: None, active=lambda port: None)   # hijo caído: no espera


def test_trabajo_cortado_por_un_reinicio_queda_como_interrumpido(tmp_path, monkeypatch):
    """12/11/2026: un reinicio cortó dos pruebas de horas y desaparecieron sin rastro del historial."""
    import time as _time

    from eolfi.server import EolfiApp

    db = str(tmp_path / "i.db")
    app = EolfiApp(db)
    job = {"id": "a" * 16, "kind": "eolas-e2e", "status": "running", "label": "Banco", "started": _time.time() - 60,
           "log": [{"t": 1, "msg": "gemma: 3/19"}], "body": {"suite": True}}
    app._save_job(job)                                            # instantánea mientras corre
    s = app._history()
    s.conn.execute("UPDATE job_live SET pid=999999999")            # su proceso ya no existe
    s.conn.commit()
    s.close()
    otra = EolfiApp(db)                                           # el servidor tras el reinicio
    listed = {j["id"]: j for j in otra.job_status({})["jobs"]}
    assert listed["a" * 16]["status"] == "interrupted" and "reinició" in listed["a" * 16]["error"]
    stored = otra.job_status({"id": "a" * 16})
    assert stored["log"][0]["msg"] == "gemma: 3/19"               # conserva el registro hasta el último guardado
    vivo = {**job, "id": "b" * 16}
    otra._save_job(vivo)                                          # uno de un servidor vivo no se toca
    EolfiApp(db)
    assert otra.job_status({"id": "b" * 16})["status"] == "running"
    otra._save_job({**vivo, "status": "done", "finished": _time.time()})
    s = otra._history()
    assert s.conn.execute("SELECT COUNT(*) FROM job_live").fetchone()[0] == 0
    s.close()


def test_prueba_en_vivo_solo_lista_motores_instalados(srv, monkeypatch):
    """14/11/2026: la lista de la prueba en vivo no ofrece motores retirados ni sin GGUF."""
    from eolfi import eolas_v2

    monkeypatch.setattr(eolas_v2, "available_evaluation_profiles", lambda cfg=None: ["gemma_q4", "gemma3_q4"])
    port, _ = srv
    status, data, _h = req(port, "GET", "/api/eolas/perfiles")
    assert status == 200 and data == {"perfiles": ["gemma_q4", "gemma3_q4"]}


def test_perfiles_disponibles_excluyen_retirados_y_sin_gguf(tmp_path, monkeypatch):
    from eolfi import eolas_v2

    cfg_path = tmp_path / "eolas.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(cfg_path))
    cfg = eolas_v2.load_config()
    for name in ("gemma_q4", "qwen14_q5"):
        cfg["profiles"][name]["model"] = str(tmp_path / f"{name}.gguf")
        (tmp_path / f"{name}.gguf").write_bytes(b"x")
    for name in cfg["profiles"]:
        if name not in ("gemma_q4", "qwen14_q5"):
            cfg["profiles"][name]["model"] = str(tmp_path / "no-existe.gguf")
    cfg["retired_profiles"] = ["qwen14_q5"]
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    assert eolas_v2.available_evaluation_profiles() == ["gemma_q4"]
