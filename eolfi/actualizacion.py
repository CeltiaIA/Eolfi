"""«eolfi update --check»: qué versión hay instalada y si se ha publicado otra (C2, PLAN_DEFINITIVO.md).

Solo comprueba; nunca instala ni sustituye nada. La forma de actualizar depende de cómo se instaló (copia del
repositorio, pipx, entorno virtual o ejecutable) y se devuelve como instrucción para el operador.

- Sin ``red=True`` no se abre ninguna conexión: el resultado es la información local y ``NO VERIFICADO``.
- Con ``EOLAS_OFFLINE=1`` se rechaza siempre la consulta.
- Solo se consulta ``https://api.github.com`` (también tras redirecciones), sin credenciales ni cookies.
- El repositorio por defecto es ``CeltiaIA/Eolfi``; ``EOLFI_UPDATE_REPO`` o ``--repo`` lo cambian.
- Las publicaciones y etiquetas remotas son datos no confiables: solo se toman su nombre de versión y su URL.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from eolfi import __version__

SCHEMA = "eolfi.actualizacion/v1"
REPO_DEFECTO = "CeltiaIA/Eolfi"
API = "https://api.github.com/repos/{repo}"
HOSTS = ("api.github.com",)
LIMITE = 2 * 1024 * 1024
TIMEOUT = 30
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,38}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_VERSION = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?(?:[-.]?((?:a|b|rc|alpha|beta|pre|dev)\.?\d*))?$", re.I)
RAIZ = Path(__file__).resolve().parents[1]

Fetch = Callable[[str], bytes]


class ActualizacionError(ValueError):
    pass


# ── Versiones ─────────────────────────────────────────────────────────────────────────────────────────────────────

def parsear(texto: str) -> tuple[int, int, int, int, str] | None:
    """«v0.9.1», «0.10», «1.0.0rc2» → tupla ordenable; None si no es una versión reconocible.

    El cuarto elemento es 1 para una versión final y 0 para una previa, de modo que 1.0.0rc1 < 1.0.0.
    """
    m = _VERSION.match((texto or "").strip())
    if not m:
        return None
    previa = (m.group(4) or "").lower()
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), 0 if previa else 1, previa


def comparar(a: str, b: str) -> int | None:
    pa, pb = parsear(a), parsear(b)
    if pa is None or pb is None:
        return None
    return (pa > pb) - (pa < pb)


# ── Instalación local ─────────────────────────────────────────────────────────────────────────────────────────────

def _git(*args: str) -> str | None:
    try:
        proc = subprocess.run(["git", "-C", str(RAIZ), *args], capture_output=True, text=True, timeout=10,
                              check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def modo_instalacion(*, prefix: str | None = None, frozen: bool | None = None, raiz: Path | None = None) -> str:
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if frozen:
        return "ejecutable"
    raiz = RAIZ if raiz is None else raiz
    if (raiz / ".git").exists() and (raiz / "pyproject.toml").is_file():
        return "copia_repositorio"
    prefix = (prefix if prefix is not None else sys.prefix).replace("\\", "/").lower()
    if "/pipx/venvs/" in prefix + "/":
        return "pipx"
    if prefix != (sys.base_prefix.replace("\\", "/").lower()) and prefix:
        return "entorno_virtual"
    return "python_sistema"


def _version_paquete(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    v = data.get("version") if isinstance(data, dict) else None
    return v if isinstance(v, str) else None


def instalacion() -> dict[str, Any]:
    modo = modo_instalacion()
    info: dict[str, Any] = {"version": __version__, "modo": modo, "python": sys.version.split()[0],
                            "ejecutable": sys.executable}
    if modo == "copia_repositorio":
        info["git"] = {"commit": _git("rev-parse", "HEAD"), "rama": _git("rev-parse", "--abbrev-ref", "HEAD"),
                       "cambios_sin_confirmar": bool(_git("status", "--porcelain", "--untracked-files=no"))}
    componentes = {}
    for nombre, rel in (("puente", "eolfi/bridge/package.json"), ("extension_vscode", "eolfi/vscode-bridge/package.json")):
        v = _version_paquete(RAIZ / rel)
        if v:
            componentes[nombre] = v
    info["componentes"] = componentes
    info["nota_componentes"] = ("El puente y la extensión de VS Code tienen su propio número de versión; "
                                "la versión del producto es la del paquete Python.")
    return info


def instrucciones(modo: str, version: str | None = None) -> str:
    if modo == "copia_repositorio":
        return "git pull en la copia y después «python -m pip install -e .» si cambian las dependencias"
    if modo == "pipx":
        return "pipx upgrade eolfi (o pipx install --force con la ruta o URL de la publicación)"
    if modo == "ejecutable":
        return "descarga el ejecutable de la publicación y sustituye el actual tras comprobar su firma o hash"
    destino = f"=={version}" if version else ""
    return f"python -m pip install --upgrade \"eolfi{destino}\" desde la fuente de la publicación"


# ── Red ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _host_permitido(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "https" and (parts.hostname or "").lower() in HOSTS


class _SoloHostsPermitidos(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _host_permitido(newurl):
            raise ActualizacionError(f"redirección a un destino no permitido: {urllib.parse.urlsplit(newurl).hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class NoEncontrado(Exception):
    pass


def _fetch_red(url: str) -> bytes:
    if not _host_permitido(url):
        raise ActualizacionError(f"destino no permitido: {url}")
    opener = urllib.request.build_opener(_SoloHostsPermitidos())
    # Sin token ni cookies: la consulta es anónima aunque el equipo tenga credenciales de GitHub.
    req = urllib.request.Request(url, headers={"User-Agent": f"eolfi-update/{__version__}",
                                               "Accept": "application/vnd.github+json"})
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            data = resp.read(LIMITE + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise NoEncontrado(url) from exc
        raise
    if len(data) > LIMITE:
        raise ActualizacionError("respuesta demasiado grande")
    return data


def _json(fetch: Fetch, url: str) -> Any:
    return json.loads(fetch(url).decode("utf-8"))


def _texto(valor: Any, limite: int = 200) -> str | None:
    return valor[:limite] if isinstance(valor, str) else None


def _ultima_publicada(fetch: Fetch, repo: str) -> dict[str, Any] | None:
    base = API.format(repo=repo)
    try:
        rel = _json(fetch, base + "/releases/latest")
    except NoEncontrado:
        rel = None
    if isinstance(rel, dict) and parsear(str(rel.get("tag_name", ""))):
        return {"version": _texto(rel["tag_name"]), "origen": "publicacion", "url": _texto(rel.get("html_url"), 500),
                "fecha": _texto(rel.get("published_at"), 40)}
    try:
        tags = _json(fetch, base + "/tags?per_page=100")
    except NoEncontrado:
        return None
    candidatas = [t["name"] for t in tags if isinstance(t, dict) and isinstance(t.get("name"), str)
                  and parsear(t["name"])] if isinstance(tags, list) else []
    if not candidatas:
        return None
    mejor = max(candidatas, key=parsear)
    return {"version": mejor[:200], "origen": "etiqueta", "url": f"https://github.com/{repo}/releases/tag/"
            + urllib.parse.quote(mejor), "fecha": None}


def comprobar(*, red: bool = False, repo: str | None = None, fetch: Fetch | None = None) -> dict[str, Any]:
    repo = repo or os.environ.get("EOLFI_UPDATE_REPO") or REPO_DEFECTO
    if not _REPO.fullmatch(repo):
        raise ActualizacionError(f"repositorio no válido: {repo!r} (propietario/nombre)")
    local = instalacion()
    res: dict[str, Any] = {"schema": SCHEMA, "repo": repo, "instalada": local, "instala_nada": True}
    if os.environ.get("EOLAS_OFFLINE", "").strip() in ("1", "true", "yes"):
        return {**res, "estado": "NO VERIFICADO", "motivo": "EOLAS_OFFLINE=1: no se consulta la red"}
    if not red:
        return {**res, "estado": "NO VERIFICADO",
                "motivo": "sin --red no se consulta GitHub; solo se muestra la instalación local"}
    try:
        ultima = _ultima_publicada(fetch or _fetch_red, repo)
    except (OSError, ValueError, urllib.error.URLError, ActualizacionError, NoEncontrado) as exc:
        return {**res, "estado": "NO VERIFICADO", "motivo": f"consulta fallida: {str(exc)[:300]}"}
    if ultima is None:
        return {**res, "estado": "sin_publicaciones",
                "motivo": "el repositorio no tiene publicaciones ni etiquetas de versión"}
    res["publicada"] = ultima
    cmp = comparar(ultima["version"], __version__)
    if cmp is None:
        return {**res, "estado": "NO VERIFICADO", "motivo": "versión instalada o publicada no comparable"}
    if cmp > 0:
        return {**res, "estado": "nueva_version",
                "como_actualizar": instrucciones(local["modo"], ultima["version"].lstrip("vV"))}
    return {**res, "estado": "al_dia" if cmp == 0 else "instalada_mas_reciente"}
