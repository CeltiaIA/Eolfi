"""Descarga prudente de recursos web.

- Solo http/https; tamaño máximo por recurso y total; tiempo límite.
- Respeta robots.txt (salvo que el usuario lo desactive explícitamente).
- Anti-SSRF: si la página analizada es pública, ningún recurso ni
  redirección puede apuntar a direcciones privadas, loopback o link-local.
  Una página hostil no puede usar Eolfi para sondear tu red local.
- Pausa entre peticiones para no cargar el servidor ajeno.
- Nunca ejecuta lo descargado: solo se lee como texto/bytes.
"""
from __future__ import annotations

import http.client
import ipaddress
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field

from eolfi import __version__

USER_AGENT = f"Eolfi/{__version__} (analisis educativo; +https://github.com/)"
MAX_REDIRECTS = 5


class FetchError(Exception):
    pass


@dataclass
class Response:
    url: str
    final_url: str
    status: int | None
    headers: dict[str, str]
    body: bytes
    elapsed: float
    error: str | None = None
    redirects: list[str] = field(default_factory=list)

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    def text(self) -> str:
        import re as _re

        ct = self.headers.get("content-type", "")
        enc = "utf-8"
        if "charset=" in ct:
            enc = ct.split("charset=", 1)[1].split(";")[0].strip().strip('"') or "utf-8"
        else:
            # Sin charset en la cabecera: el <meta charset> de la página (B21).
            m = _re.search(rb"""<meta[^>]+charset=["']?([\w-]{2,30})""", self.body[:4096], _re.I)
            if m:
                enc = m.group(1).decode("ascii")
        try:
            return self.body.decode(enc, "replace")
        except LookupError:
            return self.body.decode("utf-8", "replace")


def ip_is_private(addr: str) -> bool:
    """No global = privada, loopback, link-local, CGNAT (100.64/10), reservada, multicast…"""
    ip = ipaddress.ip_address(addr.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not ip.is_global or ip.is_multicast


def _explicit_local(host: str) -> bool:
    """El usuario apunta a su equipo o a su red a propósito: localhost o una IP privada escrita tal cual."""
    h = (host or "").strip("[]").lower()
    if h in ("localhost",) or h.endswith(".localhost"):
        return True
    try:
        return ip_is_private(str(ipaddress.ip_address(h)))
    except ValueError:
        return False


def host_is_private(host: str) -> bool:
    """True si el host resuelve a alguna IP no pública (o no resuelve: ante la duda, privado)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return True
    return any(ip_is_private(info[4][0]) for info in infos)


def _pinned_socket(host: str, port: int, timeout, allow_private: bool) -> socket.socket:
    """Resuelve UNA vez, valida esa IP y conecta exactamente a ella. Así un DNS que responde
    «pública» al comprobar y «127.0.0.1» al conectar (DNS rebinding) no burla el anti-SSRF."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise OSError(f"no se pudo resolver {host}: {exc}") from exc
    last: Exception | None = None
    for family, stype, proto, _canon, addr in infos:
        if not allow_private and ip_is_private(addr[0]):
            raise OSError(f"bloqueado: {host} resolvió a {addr[0]} (dirección no pública, anti-SSRF)")
        sock = socket.socket(family, stype, proto)
        try:
            if timeout is not None and timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            sock.connect(addr)
            peer = sock.getpeername()[0]
            if not allow_private and ip_is_private(peer):
                raise OSError(f"bloqueado: conexión a {peer} (anti-SSRF)")
            return sock
        except OSError as exc:
            sock.close()
            last = exc
            if "anti-SSRF" in str(exc):
                raise
    raise last or OSError(f"sin direcciones para {host}")


def _pinned_handlers(fetcher: "Fetcher", context):
    class PinnedHTTP(http.client.HTTPConnection):
        def connect(self):
            self.sock = _pinned_socket(self.host, self.port, self.timeout, bool(fetcher.allow_private))
            fetcher._watch(self.sock)

    class PinnedHTTPS(http.client.HTTPSConnection):
        def connect(self):
            sock = _pinned_socket(self.host, self.port, self.timeout, bool(fetcher.allow_private))
            fetcher._watch(sock)
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)

    class HTTPH(urllib.request.HTTPHandler):
        def http_open(self, req):
            return self.do_open(PinnedHTTP, req)

    class HTTPSH(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(PinnedHTTPS, req, context=context)

    return HTTPH(), HTTPSH(context=context)


def _ssl_context():
    """Verificación TLS con el almacén del sistema (truststore) si está instalado."""
    import ssl

    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        return ssl.create_default_context()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None     # gestionamos las redirecciones a mano para validarlas


class Fetcher:
    def __init__(self, *, max_bytes: int = 5 * 1024 * 1024, max_total: int = 60 * 1024 * 1024,
                 timeout: float = 20.0, delay: float = 0.25, respect_robots: bool = True):
        self.max_bytes = max_bytes
        self.max_total = max_total
        self.timeout = timeout
        self.delay = delay
        self.respect_robots = respect_robots
        self.total = 0
        self.allow_private: bool | None = None   # se fija con la primera URL
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        # Conexión a IP fijada y validada (anti DNS rebinding). Sin proxy: con proxy la IP final
        # no se podría validar, y un proxy del sistema podría alcanzar la red interna.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect,
                                                   *_pinned_handlers(self, _ssl_context()))
        self._last = 0.0
        self.requests = 0

    def _check_url(self, url: str) -> urllib.parse.SplitResult:
        u = urllib.parse.urlsplit(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise FetchError(f"URL no soportada: {url[:120]}")
        private = host_is_private(u.hostname)
        explicit = _explicit_local(u.hostname)
        if self.allow_private is None:
            # Analizar tu propio localhost o una IP privada escrita a mano está bien; un dominio cuyo DNS devuelve
            # alguna IP privada, no (sería la puerta de un ataque SSRF por DNS mixto).
            self.allow_private = bool(private and explicit)
            if self.allow_private:
                self._private_host = u.hostname.lower()
        if private and not (self.allow_private and u.hostname.lower() == getattr(self, "_private_host", None)):
            raise FetchError(f"bloqueado: {u.hostname} es una dirección privada (anti-SSRF)")
        return u

    def robots_allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        u = urllib.parse.urlsplit(url)
        origin = f"{u.scheme}://{u.netloc}"
        if origin not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self._raw_get(origin + "/robots.txt", limit=512 * 1024)
                if r.status and 200 <= r.status < 300:
                    rp.parse(r.text().splitlines())
                elif r.status is None or r.status in (401, 403) or r.status >= 500:
                    # RFC 9309: inaccesible (red caída, 5xx) = no rastrear; antes un corte de red «permitía todo» (B21).
                    rp.disallow_all = True
                else:
                    rp.allow_all = True   # 404 y similares: no hay robots.txt
            except FetchError:
                rp.disallow_all = True
            self._robots[origin] = rp
        rp = self._robots[origin]
        return rp.can_fetch(USER_AGENT, url) if rp else True

    def get(self, url: str) -> Response:
        if not self.robots_allowed(url):
            raise FetchError(f"robots.txt no permite {url[:120]} (usa --ignore-robots solo si tienes permiso)")
        return self._raw_get(url, limit=self.max_bytes)

    def _watch(self, sock) -> None:
        """Plazo TOTAL también en la conexión y en las cabeceras (PLAN_MEJORAS A17): el timeout del socket
        es por operación, y un servidor que envía la cabecera byte a byte lo esquivaba. Un temporizador
        cierra el socket al vencer el plazo de la petición en curso."""
        import threading

        deadline = getattr(self, "_deadline", None)
        if deadline is None:
            return

        def kill():
            try:
                sock.shutdown(2)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

        timer = threading.Timer(max(0.0, deadline - time.time()), kill)
        timer.daemon = True
        timer.start()
        self._timers.append(timer)

    def _raw_get(self, url: str, limit: int) -> Response:
        self._timers: list = []
        try:
            return self._raw_get_inner(url, limit)
        except OSError as exc:
            # El vigilante del plazo cerró el socket a mitad de lectura: es un plazo agotado, no un
            # error de red cualquiera.
            if self._deadline is not None and time.time() >= self._deadline - 0.05:
                raise FetchError(f"descarga demasiado lenta: {url[:120]}") from exc
            raise
        finally:
            for t in self._timers:
                t.cancel()
            self._deadline = None

    def _raw_get_inner(self, url: str, limit: int) -> Response:
        start = time.time()
        self._deadline = start + self.timeout * 3
        redirects: list[str] = []
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            self._check_url(current)
            wait = self.delay - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            self.requests += 1
            req = urllib.request.Request(current, headers={
                "User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Encoding": "identity"})
            try:
                resp = self._opener.open(req, timeout=self.timeout)
                status = resp.status
            except urllib.error.HTTPError as exc:
                resp, status = exc, exc.code
            except (urllib.error.URLError, OSError, ValueError) as exc:
                return Response(url, current, None, {}, b"", time.time() - start,
                                error=f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}", redirects=redirects)
            headers = {k.lower(): v for k, v in resp.headers.items()}
            cookies = resp.headers.get_all("set-cookie") or []
            if len(cookies) > 1:
                # Una por línea: un salto de línea no puede ir dentro de una cabecera, así que separa sin
                # ambigüedad (con « | » los atributos de una cookie se atribuían a otra; M32).
                headers["set-cookie"] = "\n".join(cookies)
            if status in (301, 302, 303, 307, 308) and "location" in headers:
                resp.close()
                nxt = urllib.parse.urljoin(current, headers["location"])
                if current.startswith("https://") and nxt.startswith("http://"):
                    raise FetchError(f"redirección de https a http rechazada: {nxt[:120]}")
                if not url.endswith("/robots.txt") and not self.robots_allowed(nxt):
                    raise FetchError(f"robots.txt no permite el destino de la redirección {nxt[:120]}")
                current = nxt
                redirects.append(current)
                continue
            # Lectura por bloques con plazo TOTAL (un servidor que envía a cuentagotas no retiene
            # la petición indefinidamente: el timeout del socket es por operación).
            deadline = start + self.timeout * 3
            chunks, got = [], 0
            try:
                while got <= limit:
                    if time.time() > deadline:
                        raise FetchError(f"descarga demasiado lenta: {current[:120]}")
                    # read1: devuelve lo que haya llegado (read(n) esperaría a juntar n bytes y el
                    # plazo total no se comprobaría hasta el final).
                    n = min(65536, limit + 1 - got)
                    piece = resp.read1(n) if hasattr(resp, "read1") else resp.read(n)
                    if not piece:
                        break
                    chunks.append(piece)
                    got += len(piece)
            finally:
                resp.close()
            body = b"".join(chunks)
            truncated = len(body) > limit
            body = body[:limit]
            self.total += len(body)
            if self.total > self.max_total:
                raise FetchError("límite total de descarga alcanzado")
            r = Response(url, current, status, headers, body, time.time() - start, redirects=redirects)
            if truncated:
                r.error = f"truncado a {limit} bytes"
            return r
        raise FetchError(f"demasiadas redirecciones desde {url[:120]}")
