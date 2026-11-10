"""Fase 2: observación de caja negra reproducible (solo muestras sintéticas propias, ver observe_samples.py)."""
import base64
import hashlib
import json
import os
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from eolfi.core.case_report import build_case_report, render_case_html
from eolfi.core.cases import CaseStore
from eolfi.core.evidence import EvidenceStore
from eolfi.observe import ScriptError, compare_sessions, run_compare, run_observation, run_replay, validate_script
from eolfi.observe import probes
from eolfi.observe.session import load_session
from tests import observe_samples as samples

AUTH = "muestra sintética propia generada por la prueba"


@pytest.fixture
def store(tmp_path):
    s = EvidenceStore(tmp_path / "e.db")
    yield s
    s.close()


def _script(target, steps, **extra):
    s = {"eolfi_observation_script": 1, "name": "prueba", "authorization": AUTH, "steps": steps}
    if target is not None:
        s["target"] = {"path": str(target), "version": "1", "provenance": "sintética"}
    s.update(extra)
    return s


def _app_steps(stdin="hola", flags=()):
    return [{"id": "arranque", "action": "run", "argv": ["{python}", "{target}", *flags],
             "stdin": {"text": stdin}, "timeout": 30}]


# -- guion -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad, msg", [
    ({"eolfi_observation_script": 2}, "eolfi_observation_script"),
    ({"authorization": ""}, "authorization"),
    ({"steps": [{"action": "write_file", "path": "../fuera.txt", "text": "x"}]}, "relativa"),
    ({"steps": [{"action": "write_file", "path": "C:/x.txt", "text": "x"}]}, "relativa"),
    ({"steps": [{"action": "run", "argv": ["{target}"]}]}, "target"),
    ({"steps": [{"action": "magia"}]}, "action"),
    ({"steps": [{"id": "a", "action": "delete_file", "path": "x"}, {"id": "a", "action": "delete_file", "path": "y"}]},
     "repetido"),
    ({"steps": [{"action": "run", "argv": ["x"], "rm": True}]}, "no admitidas"),
    ({"scope": {"registry": ["HKCR\\x"]}}, "registro"),
    ({"scope": {"capture_contents": ["../secreto.txt"]}}, "capture_contents"),
    ({"steps": [{"action": "browser", "url": "http://127.0.0.1/", "actions": [{"do": "click"}]}]}, "selector"),
    ({"extra": 1}, "no admitidas"),
])
def test_script_validation_rejects(bad, msg):
    base = _script(None, [{"action": "delete_file", "path": "x"}])
    base.update(bad)
    with pytest.raises(ScriptError, match=msg):
        validate_script(base)


def test_script_normalized_defaults():
    s = validate_script(_script(None, [{"action": "write_file", "path": "a\\b.txt", "text": "x"}]))
    assert s["environment"] == {"inherit": False, "vars": {}, "passthrough": [], "redirect_home": True}
    assert s["scope"] == {"files": ["."], "registry": [], "children": True, "capture_contents": []}
    assert s["steps"][0] == {"id": "paso1", "action": "write_file", "path": "a/b.txt", "content": {"text": "x"}}
    assert s["cleanup"] == {"remove_sandbox": True}


def test_file_content_capture_is_explicit_and_bounded(tmp_path):
    from eolfi.observe.probes import capture_file_contents

    path = tmp_path / "output.bin"
    path.write_bytes(b"\x00authorized-output\xff")
    key = "{sandbox}/output.bin"
    result, remaining = capture_file_contents([("{sandbox}", tmp_path)], [key], 100)
    capture = result[key]
    assert capture["status"] == "captured"
    assert base64.b64decode(capture["data_base64"]) == path.read_bytes()
    assert capture["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert remaining == 100 - path.stat().st_size
    result, _ = capture_file_contents([("{sandbox}", tmp_path)], [key], 1)
    assert result[key]["status"] == "session_budget_exceeded"
    result, _ = capture_file_contents([("{sandbox}", tmp_path)], [key], 100,)
    assert result[key]["status"] == "captured"


def test_file_content_capture_rejects_symlinked_parent(tmp_path):
    import subprocess

    from eolfi.observe.probes import capture_file_contents

    root = tmp_path / "scope"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.bin").write_bytes(b"must not be read")
    linked = root / "linked"
    if os.name == "nt":
        created = subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(outside)],
                                 capture_output=True, text=True)
        if created.returncode:
            pytest.skip("el entorno no permite crear una junction de directorio")
    else:
        try:
            linked.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("el entorno no permite crear enlaces de directorio")
    result, _ = capture_file_contents([("{sandbox}", root)], ["{sandbox}/linked/secret.bin"], 100)
    assert result["{sandbox}/linked/secret.bin"]["status"] == "symlink_not_captured"
    outside.joinpath("secret.bin").unlink()
    outside.rmdir()


def test_requires_explicit_authorization(store, tmp_path):
    t = samples.write(tmp_path, "app.py", samples.APP_V1)
    with pytest.raises(PermissionError):
        run_observation(_script(t, _app_steps()), store, authorized=False)
    assert store.list_evidence() == []


# -- procesos, archivos, hijos y entorno -----------------------------------------------------------------
def test_process_session_captures_io_files_children_and_cleans_up(store, tmp_path, monkeypatch):
    monkeypatch.setenv("EOLFI_OBS_SECRETO_PRUEBA", "no-debe-verse")
    t = samples.write(tmp_path, "app.py", samples.APP_V1)
    script = _script(t, _app_steps("hola", ["--hijo"]) + [
        {"id": "entrada", "action": "write_file", "path": "estado/extra.txt", "text": "x"},
        {"id": "borrado", "action": "delete_file", "path": "inicial.txt"},
        {"id": "vacio", "action": "run", "argv": ["{python}", "{target}"], "stdin": {"text": ""}},
    ], setup={"files": {"inicial.txt": {"text": "semilla"}}})
    rep = run_observation(script, store, authorized=True)
    assert rep["status"] == "done"
    s1, s2, s3, s4 = rep["steps"]
    assert s1["exit_code"] == 0 and s1["exit_status"] == {"kind": "exit", "code": 0}
    out = s1["stdout"]["preview"]
    assert "cwd={sandbox}" in out, out                       # ruta del sandbox normalizada
    assert "secreto_visible=False" in out                     # entorno del operador no heredado
    assert "eco=hola" in out and s1["stderr"]["preview"] == "aviso v1\n"
    assert s1["stdin"]["size"] == 4
    changed = {e["path"]: e["change"] for e in s1["effects"]["files"]}
    assert changed["{sandbox}/estado/datos.txt"] == "created"
    assert changed["{sandbox}/.home/AppData/Roaming/muestra.ini"] == "created"   # HOME/APPDATA redirigidos
    kids = s1["children"]["processes"]
    assert kids and kids[0]["depth"] == 1 and "python" in kids[0]["name"].lower()
    assert s1["children"]["survivors"] == []
    assert [e["change"] for e in s2["effects"]["files"]] == ["created"]
    assert s3["effects"]["files"][0]["path"] == "{sandbox}/inicial.txt" and s3["effects"]["files"][0]["change"] == "deleted"
    assert s4["exit_code"] == 3
    assert rep["initial_state"]["files"]["{sandbox}/inicial.txt"]["size"] == 7
    assert rep["setup"]["inicial.txt"]["size"] == 7
    assert rep["cleanup"]["sandbox"] == "eliminado"
    assert rep["coverage"]["system_calls"]["status"] == "not_available"
    assert rep["coverage"]["ui_mobile"]["status"] == "not_available" and rep["coverage"]["ui_desktop"] == "not_requested"
    assert rep["coverage"]["children"]["status"] == "sampled"
    assert {f["factor"] for f in rep["unfixed_factors"]} >= {"reloj", "planificación y PID", "rutas conocidas del SO"}
    assert "no es un sandbox de seguridad" in rep["isolation"]
    assert rep["target"]["sha256"] == rep["subject"] and rep["programs"][0]["sha256"]
    ev = store.get_evidence(rep["evidence_id"])
    assert ev["authority"] == "controlled_repro" and ev["operation"] == "observation_session"
    loaded = load_session(store, rep["evidence_id"])
    assert loaded["params"]["script"]["steps"][0]["id"] == "arranque"
    assert "no-debe-verse" not in json.dumps(loaded)


def test_timeout_kills_process_tree(store, tmp_path):
    t = samples.write(tmp_path, "dormilon.py", samples.SLEEPER)
    rep = run_observation(_script(t, [{"id": "d", "action": "run", "argv": ["{python}", "{target}"], "timeout": 2}]),
                          store, authorized=True)
    step = rep["steps"][0]
    assert step["status"] == "timeout" and rep["status"] == "partial"
    assert step["duration_ms"] < 20_000
    alive = {(pid, name) for pid, _pp, name in probes.process_table()}
    assert not [p for p in step["children"]["processes"] if (p["pid"], p["name"]) in alive]


def test_crash_reports_signal_or_ntstatus(store, tmp_path):
    t = samples.write(tmp_path, "crash.py", samples.CRASH)
    rep = run_observation(_script(t, [{"id": "c", "action": "run", "argv": ["{python}", "{target}"]}]),
                          store, authorized=True)
    st = rep["steps"][0]["exit_status"]
    if os.name == "nt":
        assert st == {"kind": "ntstatus", "code": "0xC0000005", "name": "STATUS_ACCESS_VIOLATION"}
    else:
        assert st["kind"] == "signal" and st["signal_name"] == "SIGTERM"


def test_missing_program_is_step_error_not_crash(store, tmp_path):
    rep = run_observation(_script(None, [{"id": "x", "action": "run", "argv": ["no-existe-eolfi-xyz"]}]),
                          store, authorized=True)
    assert rep["steps"][0]["status"] == "error" and rep["status"] == "partial"
    assert rep["subject"].startswith("cmd:observe:")


def test_exit_status_mapping():
    assert probes.exit_status(0) == {"kind": "exit", "code": 0}
    if os.name == "nt":
        assert probes.exit_status(0xC00000FD)["name"] == "STATUS_STACK_OVERFLOW"
        assert probes.exit_status(-1073741819)["name"] == "STATUS_ACCESS_VIOLATION"
    else:
        assert probes.exit_status(-9)["signal_name"] == "SIGKILL"


def test_diff_mapping():
    assert probes.diff_mapping({"a": 1, "b": 2}, {"b": 3, "c": 4}) == [
        {"path": "a", "change": "deleted", "before": 1},
        {"path": "b", "change": "modified", "before": 2, "after": 3},
        {"path": "c", "change": "created", "after": 4}]


@pytest.mark.skipif(sys.platform != "win32", reason="el registro solo existe en Windows")
def test_registry_effects_windows(store, tmp_path):
    import winreg

    key = f"Software\\EolfiObservePrueba-{uuid.uuid4().hex[:12]}"
    t = samples.write(tmp_path, "app.py", samples.APP_V1)
    try:
        rep = run_observation(_script(t, _app_steps("hola", ["--registro", key]),
                                      scope={"registry": ["HKCU\\" + key]}), store, authorized=True)
        assert rep["initial_state"]["registry_missing"] == ["HKCU\\" + key]
        eff = {e["path"]: e for e in rep["steps"][0]["effects"]["registry"]}
        assert eff[f"HKEY_CURRENT_USER\\{key}::arranques"]["after"] == "type1:v1"
        assert rep["coverage"]["registry"] == "observed"
        assert rep["cleanup"]["registry"] == "no se restaura"
        assert any(f["factor"] == "estado externo" for f in rep["unfixed_factors"])
    finally:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except OSError:
            pass


# -- HTTP/API autorizada ---------------------------------------------------------------------------------
class _Api(BaseHTTPRequestHandler):
    count = 0

    def log_message(self, *_a):
        pass

    def do_GET(self):
        if self.path == "/redir-fuera":
            self.send_response(302)
            self.send_header("Location", "http://ejemplo.invalid/x")
            self.end_headers()
            return
        if self.path == "/":
            body = (b"<!doctype html><html lang='es'><title>Contador</title><body><h1 id='n'>0</h1>"
                    b"<button id='mas'>Sumar</button><script>document.getElementById('mas').onclick=async()=>{"
                    b"const r=await fetch('/api/sumar',{method:'POST'});const j=await r.json();"
                    b"document.getElementById('n').textContent=j.n;localStorage.setItem('n',j.n);"
                    b"fetch('http://ejemplo.invalid/rastreo').catch(()=>{});console.log('sumado '+j.n);};"
                    b"</script></body></html>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        else:
            body = json.dumps({"n": _Api.count, "auth": self.headers.get("Authorization") is not None}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", "sesion=abc123; Path=/")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        _Api.count += 1
        body = json.dumps({"n": _Api.count}).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def api():
    _Api.count = 0
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Api)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def test_http_steps_link_traces_and_block_unauthorized_hosts(store, api):
    script = _script(None, [
        {"id": "estado", "action": "http", "url": "http://127.0.0.1:{var:port}/api/estado",
         "headers": {"Authorization": "Bearer muy-secreto"}},
        {"id": "sumar", "action": "http", "method": "POST", "url": "http://127.0.0.1:{var:port}/api/sumar",
         "body": {"json": {"x": 1}}},
        {"id": "fuera", "action": "http", "url": "http://ejemplo.invalid/"},
        {"id": "redir", "action": "http", "url": "http://127.0.0.1:{var:port}/redir-fuera"},
    ])
    rep = run_observation(script, store, authorized=True, variables={"port": str(api)})
    s_estado, s_sumar, s_fuera, s_redir = rep["steps"]
    tr = s_estado["traces"][0]
    assert tr["step_id"] == "estado" and tr["response"]["status"] == 200
    assert tr["request"]["url"] == "http://127.0.0.1:{var:port}/api/estado"
    assert tr["request"]["headers"]["Authorization"].startswith("<redactado")
    assert "muy-secreto" not in json.dumps(rep)
    assert tr["response"]["set_cookie_names"] == ["sesion"] and "abc123" not in json.dumps(rep)
    assert [c["name"] for c in s_estado["storage"]["cookies"]] == ["sesion"]
    assert json.loads(tr["response"]["body"]["preview"]) == {"n": 0, "auth": True}
    assert s_sumar["traces"][0]["response"]["status"] == 201
    assert s_sumar["traces"][0]["request"]["body"]["size"] > 0
    assert s_fuera["status"] == "error" and "no autorizado" in s_fuera["traces"][0]["blocked"]
    assert s_redir["status"] == "error" and s_redir["traces"][0]["redirects"][0]["blocked"]
    assert rep["coverage"]["network"]["status"] == "observed"


def test_browser_step_without_node_is_unavailable_not_verified(store, monkeypatch):
    import eolfi.observe.session as ses

    real = ses.shutil.which
    monkeypatch.setattr(ses.shutil, "which", lambda n, *a, **k: None if n == "node" else real(n, *a, **k))
    rep = run_observation(_script(None, [{"id": "ui", "action": "browser", "url": "http://127.0.0.1:1/"}]),
                          store, authorized=True)
    assert rep["steps"][0]["status"] == "unavailable"
    assert rep["coverage"]["ui_web"]["status"] == "partial" and rep["status"] == "partial"


# -- comparación, repetición y caso ---------------------------------------------------------------------
def test_compare_versions_first_change_and_hypothesis_attribution(store, tmp_path):
    t1 = samples.write(tmp_path, "app_v1.py", samples.APP_V1)
    (tmp_path / "v2").mkdir()
    t2 = samples.write(tmp_path / "v2", "app_v1.py", samples.APP_V2)
    a = run_observation(_script(t1, _app_steps()), store, authorized=True)
    b = run_observation(_script(t2, _app_steps()), store, authorized=True)
    cmp = run_compare(store, a["evidence_id"], b["evidence_id"])
    assert not cmp["identical"]
    assert cmp["first_change"]["step"] == "arranque" and cmp["first_change"]["aspect"] == "stderr"
    assert any("aviso v2" in line for line in cmp["first_change"]["detail"])
    aspects = {d["aspect"] for d in cmp["differences"]}
    assert "archivos" in aspects and "stdout" not in aspects     # stdout igual entre versiones
    assert "objetivo (sha256)" in cmp["attribution"]["candidates"]
    assert cmp["attribution"]["status"] == "hypothesis"
    assert cmp["subject"].startswith("compare:observe:")
    # Con entrada «fallo» la v2 cambia antes: el código de salida.
    c = run_observation(_script(t1, _app_steps("fallo")), store, authorized=True)
    d = run_observation(_script(t2, _app_steps("fallo")), store, authorized=True)
    assert compare_sessions(c, d)["first_change"]["aspect"] == "código de salida"


def test_replay_reproducible_and_nondeterministic(store, tmp_path):
    t = samples.write(tmp_path, "app.py", samples.APP_V1)
    a = run_observation(_script(t, _app_steps()), store, authorized=True)
    rep = run_replay(store, a["evidence_id"], authorized=True)
    assert rep["reproducible"] is True, rep["non_reproducible"]
    assert rep["non_reproducible"] == [] and rep["prechecks"] == []
    assert {f["factor"] for f in rep["unfixed_factors"]} >= {"reloj"}
    ev = store.get_evidence(rep["evidence_id"])
    assert set(json.loads(ev["links"])) == {a["evidence_id"], rep["replay"]}
    assert load_session(store, rep["replay"])["params"]["replay_of"] == a["evidence_id"]

    n = samples.write(tmp_path, "azar.py", samples.NONDETERMINISTIC)
    b = run_observation(_script(n, [{"id": "azar", "action": "run", "argv": ["{python}", "{target}"]}]),
                        store, authorized=True)
    rep2 = run_replay(store, b["evidence_id"], authorized=True)
    assert rep2["reproducible"] is False
    assert {"step": "azar", "aspect": "stdout", "reason": "difiere entre dos ejecuciones del mismo guion"} \
        in rep2["non_reproducible"]

    t.write_text(samples.APP_V2, encoding="utf-8")       # el objetivo cambió: la repetición lo marca
    rep3 = run_replay(store, a["evidence_id"], authorized=True)
    assert rep3["reproducible"] is False and rep3["prechecks"][0]["factor"] == "objetivo"
    with pytest.raises(PermissionError):
        run_replay(store, a["evidence_id"], authorized=False)


def test_replay_requires_runtime_variables(store, api):
    s = _script(None, [{"id": "e", "action": "http", "url": "http://127.0.0.1:{var:port}/api/estado"}])
    a = run_observation(s, store, authorized=True, variables={"port": str(api)})
    with pytest.raises(ValueError, match="port"):
        run_replay(store, a["evidence_id"], authorized=True)
    assert run_replay(store, a["evidence_id"], authorized=True, variables={"port": str(api)})["reproducible"]


def test_case_integration_records_report_and_package(store, tmp_path):
    cases = CaseStore(store)
    case = cases.create("observación")
    t = samples.write(tmp_path, "app.py", samples.APP_V1)
    a = run_observation(_script(t, _app_steps()), store, authorized=True, case_id=case["case_id"])
    r = run_replay(store, a["evidence_id"], authorized=True, case_id=case["case_id"])
    t2 = samples.write(tmp_path, "app2.py", samples.APP_V2)
    b = run_observation(_script(t2, _app_steps()), store, authorized=True, case_id=case["case_id"])
    c = run_compare(store, a["evidence_id"], b["evidence_id"], case_id=case["case_id"])
    got = cases.get(case["case_id"])
    flows = [(x["kind"], x["payload"]["flow"], x["payload"]["status"]) for x in got["records"]]
    assert flows == [("observation", "observe", "done"), ("observation", "replay", "done"),
                     ("observation", "observe", "done"), ("comparison", "observe_compare", "done")]
    obs_rec = got["records"][0]["payload"]
    assert obs_rec["evidence_ids"] == [a["evidence_id"]]
    assert obs_rec["claims"][0]["status"] == "observed" and "código 0" in obs_rec["claims"][0]["text"]
    assert {"name": "eolfi.observe", "version": "1.0.0", "status": "ran"} in obs_rec["tools"]
    cmp_claims = got["records"][3]["payload"]["claims"]
    assert [x["status"] for x in cmp_claims] == ["derived", "hypothesis"]
    subjects = {x["subject"] for x in got["artifacts"]}
    assert {a["subject"], b["subject"], c["subject"]} <= subjects
    target = next(x for x in got["artifacts"] if x["subject"] == a["subject"])
    assert target["identity"] == "content" and target["version"] == "1"
    html = render_case_html(build_case_report(cases.get(case["case_id"])))
    assert "Observación (1 pasos" in html and "Repetición desde el guion: reproducible" in html
    assert "primer cambio en el paso arranque" in html
    out = tmp_path / "caso.json"
    cases.export(case["case_id"], out)
    other = EvidenceStore(tmp_path / "otra.db")
    try:
        assert CaseStore(other).import_case(out) is True
        again = CaseStore(other).get(case["case_id"])
        assert [x["payload"]["flow"] for x in again["records"]] == [x[1] for x in flows]
        assert again["records"][3]["payload"]["claims"][1]["status"] == "hypothesis"
    finally:
        other.close()
    assert r["reproducible"]


def test_cli_observe(tmp_path, capsys):
    from eolfi.cli import main

    t = samples.write(tmp_path, "app.py", samples.APP_V1)
    sp = tmp_path / "guion.json"
    sp.write_text(json.dumps({**_script("app.py", _app_steps())}), encoding="utf-8")   # target relativo al guion
    db = str(tmp_path / "c.db")
    assert main(["--db", db, "observe", "check", str(sp)]) == 0
    assert json.loads(capsys.readouterr().out)["steps"] == ["arranque"]
    assert main(["--db", db, "observe", "run", str(sp)]) == 2          # sin --autorizo no se ejecuta nada
    assert "autoriz" in capsys.readouterr().out
    assert main(["--db", db, "observe", "run", str(sp), "--autorizo"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["target"]["path"] == str(t.resolve())
    assert main(["--db", db, "observe", "replay", rep["evidence_id"], "--autorizo"]) == 0
    assert json.loads(capsys.readouterr().out)["reproducible"] is True
    assert main(["--db", db, "observe", "compare", rep["evidence_id"], rep["evidence_id"]]) == 0
    capsys.readouterr()
    bad = tmp_path / "malo.json"
    bad.write_text("{}", encoding="utf-8")
    assert main(["--db", db, "observe", "check", str(bad)]) == 1


# -- API del servidor (la que usan el panel y el agente de VS Code) ---------------------------------------
def test_observe_api_run_replay_compare_and_guards(tmp_path):
    from eolfi.server import make_server
    from tests.test_server import req

    W = {"X-Eolfi": "1"}
    httpd = make_server(str(tmp_path / "s.db"), "127.0.0.1", 0, tmp_path / "samples")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    try:
        t = samples.write(tmp_path, "app.py", samples.APP_V1)
        body = {"script": _script(t, _app_steps())}
        st, d, _ = req(port, "POST", "/api/observe/run", json.dumps(body), W)
        assert st == 403 and "authorized" in d["error"]
        st, case, _ = req(port, "POST", "/api/cases", json.dumps({"name": "obs"}), W)
        st, a, _ = req(port, "POST", "/api/observe/run", json.dumps({**body, "authorized": True,
                                                                    "case_id": case["case_id"]}), W)
        assert st == 200 and a["status"] == "done" and a["case_record"]
        st, got, _ = req(port, "GET", f"/api/observe/{a['evidence_id']}")
        assert st == 200 and got["session"]["steps"][0]["exit_code"] == 0
        st, r, _ = req(port, "POST", "/api/observe/replay", json.dumps({"evidence_id": a["evidence_id"],
                                                                       "authorized": True}), W)
        assert st == 200 and r["reproducible"] is True
        st, c, _ = req(port, "POST", "/api/observe/compare", json.dumps({"a": a["evidence_id"], "b": r["replay"],
                                                                        "case_id": case["case_id"]}), W)
        assert st == 200 and c["identical"] is True
        st, d, _ = req(port, "POST", "/api/observe/compare", json.dumps({"a": "0" * 64, "b": r["replay"]}), W)
        assert st == 404
        st, d, _ = req(port, "GET", "/api/observe/" + "0" * 64)
        assert st == 404
        st, kase, _ = req(port, "GET", f"/api/cases/{case['case_id']}")
        assert [x["payload"]["flow"] for x in kase["records"]] == ["observe", "observe_compare"]
        from eolfi.server import ApiError, EolfiApp as App  # modo remoto: nunca se ejecuta nada
        with pytest.raises(ApiError) as exc:
            App(str(tmp_path / "s.db")).observe_execute("run", {**body, "authorized": True}, remote=True)
        assert exc.value.status == 403 and "remoto" in str(exc.value)
    finally:
        httpd.shutdown()
        httpd.server_close()



# -- interfaz de escritorio (Windows UI Automation) ------------------------------------------------------
def test_desktop_step_validation():
    with pytest.raises(ScriptError, match="automation_id o name"):
        validate_script(_script(None, [{"action": "desktop", "argv": ["x"], "actions": [{"do": "invoke"}]}]))
    with pytest.raises(ScriptError, match="set_value necesita value"):
        validate_script(_script(None, [{"action": "desktop", "argv": ["x"],
                                        "actions": [{"do": "set_value", "automation_id": "a"}]}]))
    s = validate_script(_script(None, [{"action": "desktop", "argv": ["x"], "actions": [{"do": "read"}]}]))
    assert s["steps"][0]["close"] is True and s["steps"][0]["timeout"] == 60.0
    assert s["steps"][0]["screenshots"] is False
    visual = validate_script(_script(None, [{"action": "desktop", "argv": ["x"], "screenshots": True,
                                             "actions": [{"do": "read"}]}]))
    assert visual["steps"][0]["screenshots"] is True
    with pytest.raises(ScriptError, match="screenshots: booleano"):
        validate_script(_script(None, [{"action": "desktop", "argv": ["x"], "screenshots": "yes",
                                       "actions": [{"do": "read"}]}]))


@pytest.mark.skipif(sys.platform != "win32", reason="UI Automation solo en Windows")
def test_desktop_scenario_windows_uia(store, tmp_path):
    t = samples.write(tmp_path, "app.ps1", samples.WINFORMS)
    script = _script(t, [{"id": "ui", "action": "desktop", "timeout": 60, "cwd": "trabajo", "screenshots": True,
                          "argv": ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", "{target}"],
                          "actions": [{"id": "escribir", "do": "set_value", "automation_id": "entrada", "value": "hola"},
                                      {"id": "pulsar", "do": "invoke", "automation_id": "convertir"}]}],
                     environment={"passthrough": ["PATH", "PSModulePath"]}, scope={"files": ["trabajo"]})
    cid = CaseStore(store).create("captura UI sintética")["case_id"]
    rep = run_observation(script, store, authorized=True, case_id=cid)
    step = rep["steps"][0]
    assert step["status"] == "ok", json.dumps(step)[:3000]
    assert [a["id"] for a in step["actions"]] == ["_inicio", "escribir", "pulsar"]
    def elem(action, aid):
        return next(e for w in action["windows"] for e in w["elements"] if e.get("automation_id") == aid)
    ini, esc, pul = step["actions"]
    assert ini["windows"][0]["title"] == "Muestra Eolfi"
    assert elem(ini, "resultado")["name"] == "(vacio)"
    assert elem(esc, "entrada")["value"] == "hola"
    assert elem(pul, "resultado")["name"] == "HOLA"
    assert elem(pul, "convertir")["type"] == "Button"
    assert ini["windows_sha256"] != pul["windows_sha256"]
    assert "convertido:hola" in step["stdout"]["preview"] and "cerrado" in step["stdout"]["preview"]
    assert step["exit_code"] == 0 and step["killed_after_close"] is False
    created = [e["path"] for e in step["effects"]["files"] if e["change"] == "created"]
    assert created == ["{sandbox}/trabajo/ultimo.txt"]          # efecto de la acción «pulsar»
    assert rep["coverage"]["ui_desktop"]["status"] == "observed"
    assert rep["coverage"]["ui_desktop"]["screenshots"] == "captured"
    assert rep["coverage"]["visual_content"]["status"] == "not_redacted"
    for action in step["actions"]:
        shot = action["screenshot"]
        image = base64.b64decode(shot["data_base64"], validate=True)
        assert shot["status"] == "captured" and shot["mime_type"] == "image/jpeg"
        assert len(image) == shot["bytes"] <= 262144 and hashlib.sha256(image).hexdigest() == shot["sha256"]
        assert 1 <= shot["width"] <= 1280 and 1 <= shot["height"] <= 800
    report = build_case_report(CaseStore(store).get(cid))
    assert len(report["screenshots"]) == len(step["actions"])
    rendered = render_case_html(report)
    assert "data:image/jpeg;base64," in rendered and "Captura de ui / pulsar" in rendered
    assert rep["coverage"]["ui_mobile"]["status"] == "not_available"
    # Repetición: el resultado funcional (texto convertido y archivo) se repite; lo que varíe (p. ej. el árbol
    # inicial capturado antes de que la ventana termine de pintarse con el equipo cargado) queda MARCADO como no
    # reproducible, nunca oculto.
    r = run_replay(store, rep["evidence_id"], authorized=True)
    again = load_session(store, r["replay"])["session"]["steps"][0]
    assert elem(again["actions"][-1], "resultado")["name"] == "HOLA"
    ui = [d for d in r["non_reproducible"] if d["aspect"].split(".")[0] in ("_inicio", "escribir", "pulsar")]
    assert all(d["aspect"].endswith("captura visual") for d in ui), r["non_reproducible"]
    # Con PrintWindow la imagen es solo la ventana del objetivo: puede repetirse idéntica (antes, con
    # CopyFromScreen, siempre variaba). Lo exigible es que toda diferencia visual quede marcada, no que exista.
    assert {d["aspect"].split(".")[0] for d in ui} <= {"_inicio", "escribir", "pulsar"}
    assert all(d["reason"] for d in r["non_reproducible"])


def test_normalize_window_removes_volatile_parts():
    from eolfi.observe.session import normalize_window

    w = {"title": "Muestra", "class": "WindowsForms10.Window.8.app.0.141b42a_r6_ad1",
         "elements": [{"automation_id": "entrada"}, {"automation_id": "460978"}]}
    n = normalize_window(w)
    assert n["class"] == "WindowsForms10.Window" and n["class_normalized"] is True
    assert [e["automation_id"] for e in n["elements"]] == ["entrada", "#handle"]
    assert normalize_window({"class": "HwndWrapper[app.exe;;1a2b-3c]", "elements": []})["class"] == "HwndWrapper[app.exe]"
    assert normalize_window({"class": "Notepad", "elements": []})["class"] == "Notepad"


def test_compare_tolerances_are_declared_and_listed():
    base = {"steps": [{"id": "ui", "action": "browser", "status": "ok", "effects": {"files": []},
                       "actions": [{"id": "a", "status": "ok", "url_after": "u", "visible": {"text_sha256": "1"},
                                    "aria": {"sha256": "x"}, "requests": []}]}]}
    other = json.loads(json.dumps(base))
    other["steps"][0]["actions"][0]["visible"]["text_sha256"] = "2"
    strict = compare_sessions(base, other)
    assert not strict["identical"] and strict["first_change"]["aspect"] == "a.texto visible"
    tol = compare_sessions(base, other, ["*.texto visible"])
    assert tol["identical"] and tol["tolerated_total"] == 1 and tol["first_change"] is None
    other["steps"][0]["actions"][0]["url_after"] = "v"
    assert compare_sessions(base, other, ["*.texto visible"])["first_change"]["aspect"] == "a.url"


def test_child_sampler_ignores_orphans_of_a_reused_pid(monkeypatch):
    """CI Windows 3.10: el PID de un padre terminado se reasignó a nuestro proceso y csrss.exe/winlogon.exe
    (hijos huérfanos del anterior) parecían descendientes. Solo cuentan hijos creados después del padre."""
    starts = {100: 50.0, 200: 60.0, 300: 10.0, 400: 70.0}
    monkeypatch.setattr(probes, "process_table_method", lambda: "toolhelp32")
    monkeypatch.setattr(probes, "process_table", lambda: [
        (100, 1, "python.exe"), (200, 100, "hijo.exe"), (300, 100, "csrss.exe"), (400, 300, "winlogon.exe")])
    monkeypatch.setattr(probes, "process_start", lambda pid: starts.get(pid))
    s = probes.ChildSampler(100)
    s.sample()
    assert sorted(s.seen) == [200] and s.seen[200]["start"] == 60.0
    starts[200] = None                       # sin hora de creación verificable: tampoco se acepta
    s2 = probes.ChildSampler(100)
    s2.sample()
    assert s2.seen == {}


def test_survivor_check_requires_same_creation_time(monkeypatch):
    from eolfi.observe import session as ses

    monkeypatch.setattr(probes, "process_table", lambda: [(200, 100, "hijo.exe")])
    monkeypatch.setattr(probes, "process_table_method", lambda: "toolhelp32")
    monkeypatch.setattr(probes, "process_start", lambda pid: 99.0)
    assert ses._same_process_alive({"pid": 200, "name": "hijo.exe", "start": 99.0}) is True
    assert ses._same_process_alive({"pid": 200, "name": "hijo.exe", "start": 60.0}) is False   # PID reutilizado
    assert ses._same_process_alive({"pid": 200, "name": "hijo.exe", "start": None}) is False
    killed = []
    monkeypatch.setattr(ses.subprocess, "run", lambda cmd, **k: killed.append(cmd))
    ses._kill_survivors([{"pid": 200, "name": "hijo.exe", "start": 60.0}])
    assert killed == []


@pytest.mark.skipif(sys.platform != "win32", reason="UI Automation solo en Windows")
def test_desktop_screenshot_excludes_overlapping_windows(store, tmp_path):
    """La captura es de la ventana del objetivo (PrintWindow), no de la pantalla: otra ventana encima no aparece."""
    image_mod = pytest.importorskip("PIL.Image", reason="Pillow para leer los JPEG capturados")
    import io
    import subprocess
    import time

    occ = samples.write(tmp_path, "tapa.ps1", samples.OCCLUDER)
    cover = subprocess.Popen(["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", str(occ)],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        time.sleep(3)   # la ventana magenta ya está encima de la zona donde aparecerá el objetivo
        t = samples.write(tmp_path, "app.ps1", samples.WINFORMS_AT)
        script = _script(t, [{"id": "ui", "action": "desktop", "timeout": 60, "cwd": "trabajo", "screenshots": True,
                              "argv": ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", "{target}"],
                              "actions": [{"id": "pulsar", "do": "invoke", "automation_id": "convertir"}]}],
                         environment={"passthrough": ["PATH", "PSModulePath"]}, scope={"files": ["trabajo"]})
        rep = run_observation(script, store, authorized=True)
    finally:
        subprocess.run(["taskkill", "/PID", str(cover.pid), "/T", "/F"], capture_output=True)
    step = rep["steps"][0]
    assert step["status"] == "ok", json.dumps(step)[:3000]
    for action in step["actions"]:
        shot = action["screenshot"]
        assert shot["status"] == "captured" and shot["method"] == "PrintWindow"
        img = image_mod.open(io.BytesIO(base64.b64decode(shot["data_base64"]))).convert("RGB")
        pixels = list(img.getdata())
        magenta = sum(1 for r, g, b in pixels if r > 200 and g < 80 and b > 200)
        assert magenta / len(pixels) < 0.05, f"{magenta}/{len(pixels)} píxeles magenta: la captura incluye la ventana que tapa"
