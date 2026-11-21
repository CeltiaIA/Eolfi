"""Puente de la tableta satélite hacia el Eolfi en vivo (20/11/2026).

El Eolfi del titular escucha solo en ``127.0.0.1:8777`` y no se abre a la red. La tableta (otro aparato) no puede
llegar a ese 127.0.0.1, así que este puente escucha en la red con TLS (el mismo certificado cuya huella fija la app)
y reenvía a ``http://127.0.0.1:8777`` **solo** lo que la tableta necesita:

- las rutas de ``tableta.PERMITIDAS`` (chat, trabajos, estado, diagnóstico y voz);
- ``POST /api/clients/token`` (canje del código de vinculación), forzando ``"scope": "tableta"``.

Todo lo demás se rechaza aquí, sin llegar a Eolfi. Fuera del canje exige un token ``ect_``. No reenvía cookies,
``Origin`` ni ``X-Eolfi-Client`` y añade ``X-Eolfi-Puente``, con la que Eolfi trata la petición como de usuario
(nunca titular, aunque llegue desde 127.0.0.1) y solo admite tokens de tableta. El destino siempre es una IP de
loopback literal: nunca ``localhost``.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import sys
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from eolfi import tableta

DESTINO = "127.0.0.1"
PUERTO_EOLFI = 8777
PUERTO_PUENTE = 18779
CANJE = ("POST", "/api/clients/token")
MAX_CUERPO = 4 * 1024 * 1024        # = MAX_JSON del servidor y MAX_BYTES de la voz (WAV de ~2 min)
MAX_CANJE = 4 * 1024
TIMEOUT = 180                        # la síntesis de voz larga puede tardar
CABECERAS_IDA = ("Authorization", "Content-Type", "X-Eolfi", "Accept-Language")
CABECERAS_VUELTA = ("Content-Type", "Content-Language", "Retry-After")
PUENTE_HEADER = "X-Eolfi-Puente"


class PuenteError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


def destino_valido(host: str) -> str:
    """Solo una IP de loopback literal (127.0.0.0/8 o ::1). «localhost» y nombres, no: dependen de la resolución."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError(f"destino no válido: {host!r} (usa una IP de loopback, p. ej. 127.0.0.1)") from None
    if not ip.is_loopback:
        raise ValueError(f"destino no válido: {host} no es loopback")
    return str(ip)


def admitida(method: str, path: str) -> bool:
    return (method, path) == CANJE or tableta.permitida(method, path)


def preparar(method: str, raw_path: str, headers: Any, body: bytes) -> tuple[str, dict[str, str], bytes]:
    """Valida una petición de la tableta y devuelve (ruta, cabeceras, cuerpo) para Eolfi. Lanza PuenteError."""
    url = urlparse(raw_path)
    if url.scheme or url.netloc or not url.path.startswith("/api/"):
        raise PuenteError(404, "ruta no disponible por el puente de la tableta")
    if not admitida(method, url.path):
        raise PuenteError(403, "por el puente solo pasan las rutas de la tableta")
    auth = (headers.get("Authorization") or "").strip()
    if (method, url.path) != CANJE and not auth.startswith("Bearer ect_"):
        raise PuenteError(401, "falta el token de la tableta: vincúlala con un código del panel")
    if (method, url.path) == CANJE:
        if len(body) > MAX_CANJE:
            raise PuenteError(413, "canje demasiado grande")
        try:
            obj = json.loads(body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, ValueError):
            raise PuenteError(400, "el canje debe ser JSON") from None
        if not isinstance(obj, dict):
            raise PuenteError(400, "el canje debe ser un objeto JSON")
        obj = {"code": str(obj.get("code", ""))[:16], "name": str(obj.get("name") or "Tableta")[:80],
               "scope": tableta.SCOPE}
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    out = {k: headers.get(k) for k in CABECERAS_IDA if headers.get(k)}
    if (method, url.path) == CANJE:
        out.pop("Authorization", None)
        out["Content-Type"] = "application/json; charset=utf-8"
    out[PUENTE_HEADER] = tableta.SCOPE
    path = url.path + (f"?{url.query}" if url.query else "")
    return path, out, body


def make_handler(destino: str, puerto: int, log: Any = None):
    destino = destino_valido(destino)

    class Handler(BaseHTTPRequestHandler):
        server_version = "EolfiPuenteTableta"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # noqa: A003 - firma de BaseHTTPRequestHandler
            if log is not None:
                print(f"[{time.strftime('%H:%M:%S')}] {self.address_string()} {fmt % args}", file=log, flush=True)

        def _error(self, status: int, msg: str) -> None:
            data = json.dumps({"error": msg}, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
            self.close_connection = True

        def _leer(self) -> bytes:
            if self.headers.get("Transfer-Encoding"):
                raise PuenteError(411, "envía el cuerpo con Content-Length")
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise PuenteError(400, "Content-Length no válido") from None
            if n < 0 or n > MAX_CUERPO:
                raise PuenteError(413, f"cuerpo demasiado grande (máximo {MAX_CUERPO // (1024 * 1024)} MB)")
            return self.rfile.read(n) if n else b""

        def _reenviar(self, method: str) -> None:
            try:
                url = urlparse(self.path)
                if not admitida(method, url.path):   # se rechaza sin reenviar; un cuerpo pequeño se descarta
                    try:                             # (en Windows, cerrar sin leerlo provoca un reset TCP)
                        n = int(self.headers.get("Content-Length") or 0)
                    except ValueError:
                        n = 0
                    if 0 < n <= 64 * 1024:
                        self.rfile.read(n)
                    raise PuenteError(403, "por el puente solo pasan las rutas de la tableta")
                body = self._leer()
                path, headers, body = preparar(method, self.path, self.headers, body)
            except PuenteError as exc:
                return self._error(exc.status, str(exc))
            headers["Host"] = f"{destino}:{puerto}" if ":" not in destino else f"[{destino}]:{puerto}"
            conn = http.client.HTTPConnection(destino, puerto, timeout=TIMEOUT)
            try:
                conn.request(method, path, body=body if method == "POST" else None, headers=headers)
                resp = conn.getresponse()
                data = resp.read()
            except OSError as exc:
                return self._error(502, f"Eolfi no responde en {destino}:{puerto} ({exc.__class__.__name__}): "
                                        "¿está abierto el panel?")
            finally:
                conn.close()
            self.send_response(resp.status)
            for k in CABECERAS_VUELTA:
                if resp.getheader(k):
                    self.send_header(k, resp.getheader(k))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
            self.close_connection = True

        def do_GET(self):  # noqa: N802
            self._reenviar("GET")

        def do_POST(self):  # noqa: N802
            self._reenviar("POST")

        def _no(self):
            self._error(405, "método no admitido por el puente de la tableta")

        do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _no  # noqa: N815

    return Handler


def make_puente(host: str, port: int, destino: str = DESTINO, puerto: int = PUERTO_EOLFI, log: Any = None):
    from eolfi.server import _Server

    return _Server((host, port), make_handler(destino, puerto, log))


def servir(host: str, port: int, cert: str | Path, key: str | Path | None, destino: str = DESTINO,
           puerto: int = PUERTO_EOLFI, legado: bool = False) -> int:
    from eolfi.server import _salidas_tolerantes, con_tls

    _salidas_tolerantes()   # la consola de Windows (cp1252) no puede escribir «→» (caía al arrancar); el aviso va en ASCII
    try:
        destino = destino_valido(destino)
    except ValueError as exc:
        print(f"eolfi: {exc}", file=sys.stderr)
        return 2
    try:
        httpd = make_puente(host, port, destino, puerto, log=sys.stdout)
    except OSError as exc:
        print(f"eolfi: no se pudo escuchar en {host}:{port} ({exc.strerror or exc})", file=sys.stderr)
        return 2
    try:
        con_tls(httpd, cert, key, legado=legado)
    except (OSError, ValueError) as exc:
        print(f"eolfi: no se pudo cargar el certificado ({exc})", file=sys.stderr)
        httpd.server_close()
        return 2
    print(f"Puente de la tableta: https://{host}:{port} -> http://{destino}:{puerto} "
          f"(solo rutas de la tableta{', TLS legado' if legado else ''}). Ctrl+C para parar.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
