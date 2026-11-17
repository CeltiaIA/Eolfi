"""La guía ejemplos/crear-proyecto/GUIA.md, ejecutada tal cual con su fuente sintética (criterios de aceptación).

Usa la misma API HTTP que la guía (servidor en 127.0.0.1, puerto libre) y la CLI para la variante sin plan.
"""
import json
import shutil
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from eolfi.cli import main
from eolfi.server import make_server

EJEMPLO = Path(__file__).resolve().parent.parent / "ejemplos" / "crear-proyecto"
DESCRIPCION = "Quiero una web en HTML estático. Que tenga modo oscuro."

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="la verificación del proyecto estático usa node --test")


@pytest.fixture
def guia(tmp_path, monkeypatch):
    work = tmp_path / "crear-proyecto"
    shutil.copytree(EJEMPLO, work)
    monkeypatch.chdir(work)
    return work


@pytest.fixture
def api(guia):
    servers = []

    def arrancar():
        httpd = make_server("guia.db", "127.0.0.1", 0, "muestras")
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        port = httpd.server_address[1]

        def req(method, path, body=None):
            r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                       data=None if body is None else json.dumps(body).encode(),
                                       headers={"X-Eolfi": "1", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(r, timeout=60) as resp:
                    return resp.status, json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read())
        return req

    yield arrancar
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


def esperar(req, job_id, plazo=240):
    fin = time.time() + plazo
    while time.time() < fin:
        code, job = req("GET", f"/api/jobs?id={job_id}")
        assert code == 200
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.2)
    raise AssertionError(f"el trabajo {job_id} no terminó en {plazo} s")


def test_guia_con_plan_y_aprobacion(guia, api):
    assert "/api/projects/plan" in (guia / "GUIA.md").read_text(encoding="utf-8")
    req = api()
    # 1. plan: no ejecuta nada
    code, st = req("POST", "/api/projects/plan", {"name": "Recetario nuevo", "sources": ["fuente"], "out": "nuevo",
                                                  "description": DESCRIPCION})
    assert code == 201 and st["status"] == "awaiting_approval" and st["approved"] is False
    cid, plan = st["case_id"], st["plan"]
    assert [s["id"] for s in plan["steps"]] == ["analizar-1", "especificar", "generar"]
    for paso in plan["steps"]:
        assert paso["what"] and paso["verification"] and paso["rationale"] and "risks" in paso
    assert plan["target"] == "static"
    assert plan["interpretation"]["uninterpreted"] == ["Que tenga modo oscuro."]
    assert any("nunca se copia código" in r for r in plan["reasoning"])
    assert req("GET", "/api/evidence")[1]["total"] == 0 and not (guia / "nuevo").exists()
    # 2. sin aprobación no se ejecuta
    code, job = req("POST", "/api/jobs", {"kind": "project", "body": {"case_id": cid}})
    assert code == 202
    job = esperar(req, job["job_id"])
    assert job["status"] == "error" and job["code"] == 409 and "no está aprobado" in job["error"]
    assert not (guia / "nuevo").exists()
    # 3. aprobar la versión revisada
    code, err = req("POST", f"/api/projects/{cid}/approve", {"version": 2})
    assert code == 400 and "la versión vigente del plan es la 1" in err["error"]
    code, st = req("POST", f"/api/projects/{cid}/approve", {"version": 1, "note": "revisado"})
    assert code == 200 and st["approved"] is True and st["status"] == "ready"
    assert [(d["type"], d["note"]) for d in st["decisions"]] == [("approval", "revisado")]
    # 4. ejecutar el plan aprobado (modo auto)
    code, job = req("POST", "/api/jobs", {"kind": "project", "body": {"case_id": cid}})
    job = esperar(req, job["job_id"])
    assert job["status"] == "done", job.get("error")
    res = job["result"]
    assert res["status"] == "done"
    assert res["results"]["analizar-1"]["status"] == "done" and res["results"]["analizar-1"]["subject"]
    assert res["results"]["especificar"]["spec_version"] == 1
    gen = res["results"]["generar"]
    assert gen["status"] == "done" and gen["target"] == "static" and gen["files"] > 0
    # 5. la verificación: pasos y códigos de salida
    ver = gen["verification"]
    assert ver["ok"] is True
    assert [(p["step"], p["exit"]) for p in ver["steps"]] == [("sintaxis JS del sitio (js/main.js)", 0),
                                                              ("pruebas (node --test)", 0)]
    # 6. qué conserva de la fuente, sin copiarla
    spec = json.loads((guia / "nuevo" / "eolfi.spec.json").read_text(encoding="utf-8"))
    assert spec["pages"] == ["home"] and spec["features"] == ["localStorage"]
    assert spec["design"]["palette"]["background"] == "#fffaf0"
    assert spec["design"]["palette"]["primary"] == "#8b4513" and spec["design"]["font"] == "Georgia"
    assert spec["sections"] == ["Hero", "Features", "ContactForm"] and spec["sections_added"] == ["Features"]
    generado = "".join(p.read_text(encoding="utf-8") for p in (guia / "nuevo").rglob("*")
                       if p.is_file() and p.suffix in (".html", ".js", ".css"))
    fuente = [ln.strip() for ln in (guia / "fuente" / "app.js").read_text(encoding="utf-8").splitlines()
              if len(ln.strip()) > 20]
    assert fuente and not [ln for ln in fuente if ln in generado]
    # el estado sobrevive a reiniciar serve
    req2 = api()
    code, st = req2("GET", f"/api/projects/{cid}")
    assert code == 200 and st["status"] == "done" and st["results"]["generar"]["verified"] is True


def test_guia_create_desde_cli(guia, capsys):
    code = main(["--db", "guia.db", "create", "--from", "fuente", "--out", "nuevo-cli", "--name", "Recetario CLI"])
    rep = json.loads(capsys.readouterr().out)
    assert code == 0 and rep["target"] == "static"
    ver = rep["verification"]
    assert ver["ok"] is True and [s["exit"] for s in ver["steps"]] == [0, 0]
