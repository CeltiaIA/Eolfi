"""Fase 6: ejecución aislada en contenedor (Docker local con una imagen ya presente; nunca se descarga nada)."""
import json
import os

import pytest

from eolfi.core.evidence import EvidenceStore
from eolfi.observe import ScriptError, run_observation, validate_script
from eolfi.observe.session import container_runtime, load_script
from eolfi.security.levels import session_plan
from tests import observe_samples as samples
from tests.test_observe import _script

IMAGE = os.environ.get("EOLFI_TEST_IMAGE", "python:3.12-slim")
RT = container_runtime(IMAGE)
needs_docker = pytest.mark.skipif(not RT["ok"], reason=f"contenedor no disponible: {RT.get('reason')}")

PROBE = r'''
import os, socket, sys
data = sys.stdin.read()
os.makedirs("estado", exist_ok=True)
open("estado/salida.txt", "w").write(data.upper())
print("cwd=" + os.getcwd())
print("uid=" + str(os.getuid()))
print("home_secreto=" + str("EOLFI_OBS_SECRETO_PRUEBA" in os.environ))
try:
    socket.create_connection(("1.1.1.1", 53), timeout=2)
    print("red=si")
except OSError:
    print("red=no")
try:
    open("/etc/eolfi", "w")
    print("raiz=escribible")
except OSError:
    print("raiz=solo-lectura")
'''


def _iso(**kw):
    return {"mode": "container", "image": IMAGE, **kw}


def test_isolation_validation():
    base = _script(None, [{"action": "delete_file", "path": "x"}])
    with pytest.raises(ScriptError, match="imagen"):
        validate_script({**base, "isolation": {"mode": "container"}})
    with pytest.raises(ScriptError, match="memory"):
        validate_script({**base, "isolation": _iso(memory="mucha")})
    with pytest.raises(ScriptError, match="desktop"):
        validate_script({**base, "isolation": _iso(), "steps": [{"action": "desktop", "argv": ["x"]}]})
    assert validate_script(base)["isolation"] == {"mode": "none"}
    assert validate_script({**base, "isolation": _iso()})["isolation"] == {
        "mode": "container", "image": IMAGE, "memory": "512m", "cpus": 1, "pids": 256}


def test_missing_image_is_unavailable_not_isolated(tmp_path):
    store = EvidenceStore(tmp_path / "e.db")
    try:
        t = samples.write(tmp_path, "p.py", "print(1)")
        rep = run_observation(_script(t, [{"id": "r", "action": "run", "argv": ["{python}", "{target}"]}],
                                      isolation={"mode": "container", "image": "eolfi-no-existe:0"}),
                              store, authorized=True)
        assert rep["steps"][0]["status"] == "unavailable" and rep["status"] == "partial"
        assert rep["isolation_mode"] == "none" and rep["data_handling"]["level"] == "observed"
    finally:
        store.close()


@needs_docker
def test_container_run_is_isolated_and_observed(tmp_path, monkeypatch):
    monkeypatch.setenv("EOLFI_OBS_SECRETO_PRUEBA", "no-debe-verse")
    store = EvidenceStore(tmp_path / "e.db")
    try:
        t = samples.write(tmp_path, "sonda.py", PROBE)
        script = _script(t, [{"id": "sonda", "action": "run", "argv": ["{python}", "{target}"],
                              "stdin": {"text": "hola"}, "timeout": 120}], isolation=_iso(memory="256m", pids=64))
        sc, bdir = load_script(script)
        plan = session_plan(sc, bdir, db_path=store.path)
        assert plan["level"] == "isolated" and plan["container"]["image_id"].startswith("sha256:")
        rep = run_observation(script, store, authorized=True)
        step = rep["steps"][0]
        assert step["status"] == "ok", json.dumps(step)[:2000]
        out = step["stdout"]["preview"]
        assert "cwd={sandbox}" in out and "uid=65534" in out
        assert "red=no" in out and "raiz=solo-lectura" in out and "home_secreto=False" in out
        assert step["exit_code"] == 0 and step["isolation"] == "container"
        created = {e["path"] for e in step["effects"]["files"] if e["change"] == "created"}
        assert "{sandbox}/estado/salida.txt" in created
        assert rep["isolation_mode"] == "container" and rep["container"]["image_id"] == RT["image_id"]
        assert rep["data_handling"]["level"] == "isolated"
        assert rep["coverage"]["children"]["status"] == "not_available"
        assert any(f["factor"] == "imagen del contenedor" for f in rep["unfixed_factors"])
        assert "no-debe-verse" not in json.dumps(rep)
    finally:
        store.close()


@needs_docker
def test_container_timeout_removes_container(tmp_path):
    import subprocess

    store = EvidenceStore(tmp_path / "e.db")
    try:
        t = samples.write(tmp_path, "lento.py", "import time; time.sleep(60)")
        rep = run_observation(_script(t, [{"id": "l", "action": "run", "argv": ["{python}", "{target}"],
                                           "timeout": 8}], isolation=_iso()), store, authorized=True)
        assert rep["steps"][0]["status"] == "timeout"
        ps = subprocess.run(["docker", "ps", "-q", "--filter", "name=eolfi-obs-"], capture_output=True, text=True)
        assert ps.stdout.strip() == ""
    finally:
        store.close()
