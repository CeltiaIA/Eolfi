"""Páginas renderizadas y rastreo limitado para «eolfi web --render» (C3, PLAN_DEFINITIVO.md).

Una SPA entrega un HTML casi vacío y construye la página con JavaScript: el análisis estático (``webpage.py``) no ve
su contenido ni sus rutas. Aquí se abre cada página en un Chrome/Edge sin interfaz (``render_driver.mjs``), se espera
a que la red se calme y se toman el HTML resultante, los enlaces y las rutas que la app cambia con ``pushState``.

Límites deliberados:
- Solo el mismo origen que la página inicial (más los hosts que el operador añada); el resto de peticiones del
  navegador se bloquean y se cuentan.
- Rastreo en anchura con tope de páginas (``max_paginas``) y de profundidad; robots.txt se respeta salvo
  ``--ignore-robots``. No rellena formularios ni pulsa botones: solo carga URLs.
- Necesita Node.js, playwright-core y un Chrome/Edge instalado; si falta algo, el resultado es ``unavailable``,
  no un análisis vacío. No descarga navegadores.
- Ejecutar el JavaScript de un sitio ajeno es ejecutar código no confiable en un navegador aislado sin perfil;
  el contenido de la página es dato, nunca instrucciones.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any

DRIVER = Path(__file__).with_name("render_driver.mjs")
_REPO_PLAYWRIGHT = Path(__file__).resolve().parents[2] / "tests" / "e2e" / "node_modules" / "playwright-core"
_NO_HTML = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".css", ".js", ".mjs", ".json", ".xml",
            ".pdf", ".zip", ".gz", ".mp4", ".mp3", ".wav", ".woff", ".woff2", ".ttf", ".wasm", ".map", ".txt")
MAX_PAGINAS = 50
MAX_PROFUNDIDAD = 5

Renderer = Callable[[list[str], list[str]], dict[str, Any]]


def _playwright() -> str | None:
    if os.environ.get("EOLFI_PLAYWRIGHT"):
        return os.environ["EOLFI_PLAYWRIGHT"]
    return str(_REPO_PLAYWRIGHT) if _REPO_PLAYWRIGHT.is_dir() else None


def render(urls: list[str], allow_hosts: list[str], *, timeout: float = 30.0, settle: float = 5.0,
           max_html: int = 2 * 1024 * 1024, max_requests: int = 400) -> dict[str, Any]:
    """Renderiza las URLs en un solo navegador. Devuelve la respuesta del controlador."""
    node = shutil.which("node")
    if node is None:
        return {"status": "unavailable", "error": "Node.js no está instalado: no se puede renderizar"}
    req = {"urls": urls, "allow_hosts": sorted({h.lower().strip("[]") for h in allow_hosts}),
           "timeout_ms": int(timeout * 1000), "settle_ms": int(settle * 1000), "max_html": max_html,
           "max_requests": max_requests}
    env = dict(os.environ)
    pw = _playwright()
    if pw:
        env["EOLFI_PLAYWRIGHT"] = pw
    with tempfile.TemporaryDirectory(prefix="eolfi-render-") as tmp:
        path = Path(tmp, "request.json")
        path.write_text(json.dumps(req), encoding="utf-8")
        try:
            proc = subprocess.run([node, str(DRIVER), str(path)], capture_output=True, env=env, check=False,
                                  timeout=(timeout + settle) * max(1, len(urls)) + 60)
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "error": "el renderizador no terminó a tiempo"}
    try:
        return json.loads(proc.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"status": "error", "error": "respuesta inválida del renderizador: "
                + proc.stderr.decode("utf-8", "replace")[-800:]}


def normalizar(url: str) -> str | None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    path = parts.path or "/"
    if path.lower().endswith(_NO_HTML):
        return None
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc.lower(), path, parts.query, ""))


def _origen(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    return f"{p.scheme}://{p.netloc.lower()}"


def rastrear(inicio: str, *, max_paginas: int = 10, max_profundidad: int = 2,
             robots: Callable[[str], bool] | None = None, renderer: Renderer | None = None,
             hosts_extra: list[str] | None = None, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Rastreo en anchura del mismo origen, renderizando cada nivel en un lote."""
    log = progress or (lambda _m: None)
    max_paginas = max(1, min(int(max_paginas), MAX_PAGINAS))
    max_profundidad = max(0, min(int(max_profundidad), MAX_PROFUNDIDAD))
    start = normalizar(inicio)
    if start is None:
        raise ValueError("--render necesita una URL http(s) de una página")
    origen = _origen(start)
    host = urllib.parse.urlsplit(start).hostname or ""
    allow = [host, *(hosts_extra or [])]
    renderer = renderer or (lambda urls, hosts: render(urls, hosts))
    robots = robots or (lambda _u: True)

    vistas: set[str] = {start}
    nivel = [(start, "inicio")]
    paginas: list[dict[str, Any]] = []
    excluidas = {"robots": 0, "otro_origen": 0, "tope": 0}
    navegador = None
    bloqueados: set[str] = set()
    for profundidad in range(max_profundidad + 1):
        lote = []
        for url, via in nivel:
            if not robots(url):
                excluidas["robots"] += 1
                paginas.append({"url": url, "profundidad": profundidad, "via": via, "estado": "excluida_robots"})
                continue
            if len([p for p in paginas if p.get("estado") != "excluida_robots"]) + len(lote) >= max_paginas:
                excluidas["tope"] += 1
                continue
            lote.append((url, via))
        if not lote:
            break
        log(f"renderizando {len(lote)} página(s) de profundidad {profundidad}…")
        res = renderer([u for u, _ in lote], allow)
        if res.get("status") != "ok":
            return {"estado": res.get("status", "error"), "error": res.get("error"), "paginas": paginas,
                    "limite": "Sin navegador no hay análisis renderizado: NO VERIFICADO"}
        navegador = res.get("browser")
        bloqueados.update(res.get("blocked_origins") or [])
        siguiente: list[tuple[str, str]] = []
        for (url, via), item in zip(lote, res.get("pages") or [], strict=False):
            pagina = {"url": url, "profundidad": profundidad, "via": via, "estado": item.get("status"),
                      "http": item.get("http"), "titulo": item.get("title"), "url_final": item.get("final_url"),
                      "texto_caracteres": item.get("text_chars"), "html_bytes": item.get("html_bytes"),
                      "recortado": item.get("truncated"), "errores_js": item.get("page_errors") or [],
                      "enlaces": 0, "rutas_spa": [], "html": item.get("html")}
            if item.get("status") != "ok":
                pagina["error"] = item.get("error")
                paginas.append(pagina)
                continue
            mismos = []
            for href in item.get("links") or []:
                n = normalizar(href)
                if n is None:
                    continue
                if _origen(n) != origen:
                    excluidas["otro_origen"] += 1
                    continue
                mismos.append(n)
            rutas = [n for n in (normalizar(r) for r in item.get("routes") or []) if n and _origen(n) == origen]
            pagina["enlaces"] = len(set(mismos))
            pagina["rutas_spa"] = sorted(set(rutas))[:50]
            paginas.append(pagina)
            for n, como in [*((m, "enlace") for m in mismos), *((r, "ruta_spa") for r in rutas)]:
                if n not in vistas:
                    vistas.add(n)
                    siguiente.append((n, como))
        nivel = siguiente
    renderizadas = [p for p in paginas if p.get("estado") == "ok"]
    return {"estado": "ok", "inicio": start, "navegador": navegador, "max_paginas": max_paginas,
            "max_profundidad": max_profundidad, "renderizadas": len(renderizadas), "paginas": paginas,
            "pendientes_sin_visitar": len(nivel) if nivel else 0, "excluidas": excluidas,
            "origenes_bloqueados": sorted(bloqueados),
            "limite": "Solo carga URLs del mismo origen; no rellena formularios ni pulsa botones. Rutas que solo "
                      "aparecen tras una interacción quedan fuera."}


def resumen_spa(estatico_texto: int | None, renderizada: dict[str, Any]) -> dict[str, Any]:
    """Compara el texto del HTML servido con el renderizado: mucho más texto renderizado indica una SPA."""
    rend = int(renderizada.get("texto_caracteres") or 0)
    est = int(estatico_texto or 0)
    return {"texto_estatico": est, "texto_renderizado": rend,
            "parece_spa": rend >= 200 and rend > 3 * max(est, 1),
            "nota": "Indicio por cantidad de texto, no una detección del framework"}
