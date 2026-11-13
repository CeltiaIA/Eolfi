"""--reload no corta trabajos en marcha (12/11/2026).

Un cambio en app.js reiniciaba el servidor del panel y cortaba una batería de motores de una hora, dejando su
llama-server huérfano. Ahora solo el código Python reinicia (el panel se lee del disco en cada petición) y, si hay
trabajos en marcha o en cola, el vigilante espera a que terminen.
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from eolfi import server


def test_solo_el_codigo_python_obliga_a_reiniciar(tmp_path):
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "app.js").write_text("a", encoding="utf-8")
    (tmp_path / "web" / "index.html").write_text("a", encoding="utf-8")
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "mod.cpython-312.py").write_text("", encoding="utf-8")
    before = server._snapshot(tmp_path)
    assert list(before) == [str(tmp_path / "mod.py")]
    later = time.time() + 5
    os.utime(tmp_path / "web" / "app.js", (later, later))
    assert server._snapshot(tmp_path) == before                     # tocar el panel no reinicia
    os.utime(tmp_path / "mod.py", (later, later))
    assert server._snapshot(tmp_path) != before                     # tocar Python sí


def test_cuenta_trabajos_en_marcha_y_en_cola():
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = json.dumps({"jobs": [{"status": "running"}, {"status": "queued"}, {"status": "done"},
                                        {"status": "error"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert server._active_jobs(srv.server_address[1]) == 2
    finally:
        srv.shutdown()
    # 13/11/2026: «sin respuesta» NO es «cero trabajos» (una respuesta lenta durante la carga de un motor se tomó
    # como 0 y la recarga mató una ronda de horas): es None y el vigilante sigue esperando.
    assert server._active_jobs(9) is None


def test_el_vigilante_espera_a_que_terminen_los_trabajos(tmp_path, monkeypatch):
    """Con un cambio detectado y un trabajo activo, no termina el proceso hijo hasta que el trabajo acaba."""
    events = []
    snaps = iter([{"a": 1}] + [{"a": 2}] * 1000)                    # el primero es el inicial; luego hay cambio
    active = iter([1, 1, 1, 0] + [0] * 1000)                         # el trabajo termina a la cuarta consulta

    class Proc:
        def __init__(self):
            self.alive = True

        def poll(self):
            return None if self.alive else 0

        def terminate(self):
            events.append(("terminate", len(events)))
            self.alive = False
            raise KeyboardInterrupt                                  # corta el bucle externo de la prueba

        def wait(self, *_):
            return 0

    monkeypatch.setattr(server, "_snapshot", lambda root: next(snaps))
    monkeypatch.setattr(server, "_active_jobs", lambda port: events.append(("consulta", port)) or next(active))
    monkeypatch.setattr(server.subprocess, "Popen", lambda *a, **k: Proc())
    monkeypatch.setattr(server.time, "sleep", lambda s: None)
    try:
        server.serve_with_reload(["serve", "--port", "8799"])
    except KeyboardInterrupt:
        pass
    consultas = [e for e in events if e[0] == "consulta"]
    assert consultas and all(port == 8799 for _, port in consultas)
    # Solo se reinicia cuando ya no hay trabajos: dos lecturas SEGUIDAS de 0 (13/11/2026), 1+1+1+0+0 = 5 consultas.
    assert events[-1][0] == "terminate" and len(consultas) == 5
