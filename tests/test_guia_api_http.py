"""La guía ejemplos/api-http/GUIA.md, ejecutada con su muestra sintética (criterios de aceptación por paso)."""
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from eolfi.cli import main

EJEMPLO = Path(__file__).resolve().parent.parent / "ejemplos" / "api-http"


@pytest.fixture
def guia(tmp_path, monkeypatch):
    work = tmp_path / "api-http"
    shutil.copytree(EJEMPLO, work)
    monkeypatch.chdir(work)
    return work


@pytest.fixture
def servidor(guia):
    p = subprocess.Popen([sys.executable, str(guia / "servidor.py"), "--port", "0"], stdout=subprocess.PIPE, text=True)
    line = p.stdout.readline().strip()
    assert line.startswith("escuchando en "), line
    yield line.rsplit(":", 1)[-1]
    p.terminate()
    p.wait(timeout=10)
    p.stdout.close()


def run(capsys, *args):
    code = main(["--db", "guia.db", *args])
    out = capsys.readouterr().out
    return code, (json.loads(out) if out.strip().startswith(("{", "[")) else out)


def _get(base, path, method="GET", data=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        r = opener.open(urllib.request.Request(base + path, method=method, data=data), timeout=10)
    except urllib.error.HTTPError as exc:
        r = exc
    with r:
        return r.code, r.headers.get("X-Eolfi-Estado")


def test_guia_api_http(guia, servidor, capsys):
    texto = (guia / "GUIA.md").read_text(encoding="utf-8")
    assert "eolfi " in texto and "--target python-http" in texto
    port = f"port={servidor}"
    code, case = run(capsys, "case", "create", "Notas")
    cid = case["case_id"]
    # 1. plan
    code, plan = run(capsys, "observe", "plan", "guion.json", "--var", port)
    assert code == 0 and plan["level"] == "observed" and plan["warnings"]
    # 2. observar
    code, obs = run(capsys, "observe", "run", "guion.json", "--autorizo", "--case", cid, "--var", port)
    assert code == 0 and obs["status"] == "done"
    assert [s["traces"][0]["response"]["status"] for s in obs["steps"]] == [200, 200, 404, 200, 400, 200, 200]
    assert servidor not in json.dumps(obs["steps"][0]["traces"][0]["request"]["url"])
    # 3. especificar
    code, spec = run(capsys, "spec", "build", "--case", cid)
    reqs = spec["requirements"]
    assert len(reqs) == 6 and sum(r["kind"] == "error" for r in reqs) == 2
    assert [(r["status"], r["confidence"]) for r in reqs if r["status"] != "observed"] == [("contradicted", "low")]
    # 4. reconstruir (sin CLI observada → python-http)
    code, rec = run(capsys, "reconstruct", "--case", cid, "--out", "reconstruccion")
    g, v = rec["generation"], rec["verification"]
    assert code == 4 and g["simulated"] == 5 and g["pending"] == 1 and g["partial"] == 0
    assert v["match"] == 5 and v["differ"] == 0 and v["pending"] == 1
    assert v["equivalent_on_observed"] is True and v["complete"] is False      # lo pendiente no se oculta
    manifest = json.loads((guia / "reconstruccion" / ".eolfi" / "trazabilidad.json").read_text(encoding="utf-8"))
    assert manifest["target"] == "python-http" and all(c["evidence_ids"] and c["route"] for c in manifest["cases"])
    assert "comprar pan" not in (guia / "reconstruccion" / "server.py").read_text(encoding="utf-8")
    # 5. usar y probar la API generada
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "reconstruccion/tests"],
                       capture_output=True, text=True, timeout=180)
    assert p.returncode == 0, p.stdout + p.stderr
    gen = subprocess.Popen([sys.executable, "reconstruccion/server.py", "--port", "0"], stdout=subprocess.PIPE,
                           text=True)
    try:
        base = gen.stdout.readline().strip().rsplit(" ", 1)[-1]
        assert _get(base, "/api/salud") == (200, None)
        assert _get(base, "/api/notas/2") == (501, "no-especificado")
        assert _get(base, "/api/salud", "DELETE") == (501, "no-especificado")
        assert _get(base, "/api/visitas") == (503, "pendiente")
    finally:
        gen.terminate()
        gen.wait(timeout=10)
        gen.stdout.close()
    # 6. informe
    assert run(capsys, "case", "report", cid, "--out", "informe.html")[0] == 0
    assert "Notas" in (guia / "informe.html").read_text(encoding="utf-8")
