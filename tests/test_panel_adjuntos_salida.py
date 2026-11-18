"""Panel (18/11/2026): límite de adjuntos del chat según quién pide y servidor que sigue respondiendo cuando ya no hay
quien lea su salida («no carga ni responde» en el panel de 8777)."""
import http.client
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from eolfi import chat, server
from eolfi.server import EolfiApp, make_server

ROOT = Path(__file__).resolve().parents[1]


def _msg(n: int) -> dict:
    return {"messages": [{"role": "user", "content": "genera el proyecto"}],
            "attachments": [{"upload": "no-es-una-huella", "name": f"a{i}.png"} for i in range(n)]}


@pytest.mark.parametrize("nivel, n, error", [
    ("usuario", 6, "hasta 5 archivos"), ("usuario", 5, "adjunto inválido"),
    ("premium", 11, "hasta 10 archivos"), ("premium", 10, "adjunto inválido"),
    ("titular", 40, "adjunto inválido"),          # el titular no tiene límite fijo: pasa al siguiente control
    ("inventado", 6, "hasta 5 archivos"),         # un nivel desconocido cuenta como usuario normal
])
def test_limite_de_adjuntos_por_nivel(tmp_path, nivel, n, error):
    app = EolfiApp(str(tmp_path / "c.db"), tmp_path / "samples")
    with pytest.raises(server.ApiError, match=error):
        app.chat(_msg(n), nivel=nivel)
    with pytest.raises(server.ApiError, match="hasta 5 archivos"):
        app.chat(_msg(6))                         # sin nivel (llamadas internas): el más restrictivo
    assert chat.limite_adjuntos("titular") is None and chat.LIMITES_ADJUNTOS["premium"] == 10


@pytest.fixture
def srv(tmp_path):
    httpd = make_server(str(tmp_path / "s.db"), "127.0.0.1", 0, tmp_path / "samples")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def _req(httpd, method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=20)
    c.request(method, path, json.dumps(body) if body is not None else None, {"Content-Type": "application/json", "X-Eolfi": "1"})
    r = c.getresponse()
    return r.status, json.loads(r.read() or b"null")


def test_el_servidor_pone_el_nivel_por_la_conexion(srv, monkeypatch):
    monkeypatch.setattr(srv.app, "chat_status", lambda _q=None: {"available": True})
    assert _req(srv, "GET", "/api/chat/estado")[1]["max_adjuntos"] is None          # desde este equipo: titular
    # El trabajo de chat lanzado desde este equipo no aplica el límite de 5 (falla después, por los adjuntos falsos);
    # lo que diga el cuerpo de la petición no cambia el nivel.
    st, job = _req(srv, "POST", "/api/jobs", {"kind": "chat", "body": {**_msg(6), "nivel": "usuario"}})
    assert st == 202
    for _ in range(100):
        st, out = _req(srv, "GET", f"/api/jobs?id={job['job_id']}")
        if out.get("status") not in ("queued", "running"):
            break
        time.sleep(0.05)
    assert out["status"] == "error" and "adjunto inválido" in out["error"]
    monkeypatch.setattr(server, "_LOOPBACK", set())                                   # como si viniera de otro equipo
    assert _req(srv, "GET", "/api/chat/estado")[1]["max_adjuntos"] == 5


def test_salida_tolerante_descarta_lo_que_no_se_puede_escribir():
    class Rota:
        def write(self, _t):
            raise OSError(22, "Invalid argument")

        def flush(self):
            raise OSError(22, "Invalid argument")

        encoding = "utf-8"

    s = server._SalidaTolerante(Rota())
    assert s.write("hola\n") == 5 and s.flush() is None and s.encoding == "utf-8"
    assert server._SalidaTolerante(None).write("x") == 1


def test_servidor_sin_quien_lea_su_salida_sigue_respondiendo(tmp_path):
    """Reproduce el panel de 8777: se lanza con stdout/stderr a tuberías y luego se cierran (el que lo lanzó ya no
    existe). Antes, cada petición moría al escribir su línea de registro y el navegador recibía una respuesta vacía."""
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "EOLFI_HOME": str(home / ".eolfi"),
           "EOLFI_BRIDGE_FILE": str(home / ".eolfi" / "bridge.json"),
           "EOLFI_VSCODE_BRIDGE_FILE": str(home / ".eolfi" / "vscode-bridge.json"), "PYTHONIOENCODING": "utf-8"}
    p = subprocess.Popen([sys.executable, "-m", "eolfi", "--db", str(tmp_path / "h.db"), "serve", "--port", "0",
                          "--samples", str(tmp_path / "s")], cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        line = ""
        for _ in range(20):
            line = p.stdout.readline()
            if "sirviendo en" in line or not line:
                break
        port = int(re.search(r":(\d+)", line.split("sirviendo en", 1)[1]).group(1))
        p.stdout.close()
        p.stderr.close()                          # nadie lee ya: escribir en ellas falla
        for path in ("/", "/api/health", "/app.js"):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
            c.request("GET", path)
            r = c.getresponse()
            assert r.status == 200 and r.read(), path
        assert p.poll() is None
    finally:
        p.kill()
        p.wait(10)
