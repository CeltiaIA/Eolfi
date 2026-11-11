"""Muestra sintética propia del proyecto Eolfi: una API HTTP de notas mínima (solo biblioteca estándar).

Se usa en ejemplos/api-http/GUIA.md como objetivo «sin fuentes»: la guía solo mira su comportamiento por HTTP.
Escucha en 127.0.0.1; con --port 0 elige un puerto libre y lo imprime en la primera línea.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NOTAS = {"1": {"id": "1", "texto": "comprar pan"}}
VISITAS = {"n": 0}


class Api(BaseHTTPRequestHandler):
    server_version = "notas"
    sys_version = ""

    def log_message(self, *args):
        pass

    def _json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/salud":
            return self._json(200, {"estado": "ok", "version": "1.0"})
        if self.path.startswith("/api/notas/"):
            nota = NOTAS.get(self.path.rsplit("/", 1)[-1])
            return self._json(200, nota) if nota else self._json(404, {"error": "no existe"})
        if self.path == "/api/visitas":            # cambia en cada petición: estado que la etapa 1 no modela
            VISITAS["n"] += 1
            return self._json(200, {"visitas": VISITAS["n"]})
        return self._json(404, {"error": "ruta desconocida"})

    def do_POST(self):
        data = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path != "/api/validar":
            return self._json(404, {"error": "ruta desconocida"})
        try:
            texto = json.loads(data)["texto"]
        except (ValueError, KeyError, TypeError):
            return self._json(400, {"error": "falta texto"})
        return self._json(200, {"valido": bool(texto.strip()), "longitud": len(texto)})


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Api)
    print(f"escuchando en http://127.0.0.1:{srv.server_address[1]}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
