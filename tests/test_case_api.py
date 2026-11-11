"""Fase 1: API de casos (mismo estado que la CLI y el agente) y trabajos enlazados con un caso."""
import json
import threading
import time

import pytest

from eolfi.server import make_server
from tests.elfgen import build_elf64
from tests.test_server import req

W = {"X-Eolfi": "1"}


@pytest.fixture
def srv(tmp_path):
    httpd = make_server(str(tmp_path / "s.db"), "127.0.0.1", 0, tmp_path / "samples")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1], tmp_path
    httpd.shutdown()
    httpd.server_close()


def _wait(port, job_id):
    for _ in range(200):
        _st, d, _ = req(port, "GET", f"/api/jobs?id={job_id}")
        if d["status"] not in ("queued", "running"):
            return d
        time.sleep(0.1)
    raise AssertionError("el trabajo no terminó")


def test_case_api_end_to_end(srv):
    port, tmp = srv
    st, case, _ = req(port, "POST", "/api/cases", json.dumps({"name": "API", "description": "d"}), W)
    assert st == 201
    cid = case["case_id"]
    f = tmp / "a.elf"
    f.write_bytes(build_elf64())

    # Un trabajo del panel con case_id queda registrado en el caso, y el trabajo lleva el case_id.
    st, job, _ = req(port, "POST", "/api/jobs", json.dumps({"kind": "triage", "body": {
        "path": str(f), "mode": "local", "case_id": cid}}), W)
    assert st == 202
    d = _wait(port, job["job_id"])
    assert d["status"] == "done" and d["result"]["case_record"]
    _st, jobs, _ = req(port, "GET", "/api/jobs")
    assert jobs["jobs"][0]["case_id"] == cid
    # Caso inexistente: se rechaza al crear el trabajo, antes de analizar nada.
    st, err, _ = req(port, "POST", "/api/jobs", json.dumps({"kind": "triage", "body": {
        "path": str(f), "case_id": "00000000-0000-4000-8000-000000000000"}}), W)
    assert st == 404 and "caso no encontrado" in err["error"]
    assert req(port, "POST", "/api/jobs", json.dumps({"kind": "triage", "body": {
        "path": str(f), "case_id": "../x"}}), W)[0] == 400

    st, lst, _ = req(port, "GET", "/api/cases")
    assert st == 200 and lst["cases"][0]["artifacts"] == 1 and lst["cases"][0]["last_record"]["status"] == "done"
    st, full, _ = req(port, "GET", f"/api/cases/{cid}")
    assert st == 200 and full["artifacts"][0]["identity"] == "content"
    assert isinstance(full["evidence"][0]["result"], dict)          # decodificado para el panel
    assert full["jobs"] and full["jobs"][0]["status"] == "done"

    sha = full["artifacts"][0]["subject"]
    ev = next(e["evidence_id"] for e in full["evidence"] if e["authority"] == "distributed_artifact")
    st, rec, _ = req(port, "POST", f"/api/cases/{cid}/records", json.dumps({"kind": "specification", "payload": {
        "claims": [{"text": "ELF", "status": "observed", "evidence_ids": [ev]},
                   {"text": "Quizá un servicio", "status": "hypothesis"}]}}), W)
    assert st == 200 and rec["record_id"]
    st, bad, _ = req(port, "POST", f"/api/cases/{cid}/records", json.dumps({"kind": "specification", "payload": {
        "claims": [{"text": "Sin pruebas", "status": "observed"}]}}), W)
    assert st == 400 and "observed" in bad["error"]
    st, link, _ = req(port, "POST", f"/api/cases/{cid}/artifacts", json.dumps({"subject": sha[:16]}), W)
    assert st == 200 and link["created"] is False
    assert req(port, "POST", f"/api/cases/{cid}/artifacts", json.dumps({"subject": "no-existe"}), W)[0] == 404

    st, html, hdrs = req(port, "GET", f"/api/cases/{cid}/report")
    assert st == 200 and b"Quiz\xc3\xa1 un servicio" in html and b"Hip\xc3\xb3tesis" in html
    assert hdrs["Content-Security-Policy"].startswith("default-src 'none'") and "script-src" not in hdrs["Content-Security-Policy"]
    assert "attachment" in req(port, "GET", f"/api/cases/{cid}/report?download=1")[2]["Content-Disposition"]

    st, pkg, hdrs = req(port, "GET", f"/api/cases/{cid}/export")
    assert st == 200 and pkg["case_package_version"] == 2 and "attachment" in hdrs["Content-Disposition"]
    st, imp, _ = req(port, "POST", "/api/cases/import", json.dumps({"package": pkg, "name": "c.json"}), W)
    assert st == 200 and imp == {"imported": False, "case_id": cid}   # idéntico: no se duplica
    pkg["case"]["name"] = "Otro"
    assert req(port, "POST", "/api/cases/import", json.dumps({"package": pkg}), W)[0] == 400
    assert req(port, "GET", "/api/cases/00000000-0000-4000-8000-000000000000")[0] == 404


def test_vscode_agent_activity_is_ephemeral_and_redacted(tmp_path):
    from eolfi.server import EolfiApp

    app = EolfiApp(str(tmp_path / "activity.db"), tmp_path / "samples")
    run_id = "a" * 32
    app.update_vscode_activity({"run_id": run_id, "phase": "start", "label": "@eolfi /auditar"})
    app.update_vscode_activity({"run_id": run_id, "phase": "progress", "message": "Paso 2 de 10: eolfi_read_file"})
    live = app.vscode_activity()["activity"][0]
    assert live["status"] == "running" and live["label"] == "@eolfi /auditar"
    assert live["log"][-1]["msg"] == "Paso 2 de 10: eolfi_read_file"
    app.update_vscode_activity({"run_id": run_id, "phase": "done", "message": "terminado"})
    assert app.vscode_activity()["activity"][0]["status"] == "done"
    assert "prompt" not in app.vscode_activity()["activity"][0]
    with pytest.raises(Exception, match="run_id o phase inválido"):
        app.update_vscode_activity({"run_id": "../escape", "phase": "start"})


def test_vscode_activity_api_requires_vscode_client(srv):
    port, _ = srv
    assert req(port, "GET", "/api/vscode/activity")[1] == {"activity": []}
    status, body, _ = req(port, "POST", "/api/vscode/activity", json.dumps({
        "run_id": "b" * 32, "phase": "start"}), {"X-Eolfi": "1"})
    assert status == 403 and "extensión vinculada" in body["error"]


def test_panel_serves_case_module(srv):
    port, _ = srv
    st, body, hdrs = req(port, "GET", "/cases.js")
    assert st == 200 and b"createCaseView" in body and hdrs["Content-Type"].startswith("text/javascript")
    st, index, _ = req(port, "GET", "/")
    assert b'id="panel-cases"' in index and b'id="case-view"' in index
