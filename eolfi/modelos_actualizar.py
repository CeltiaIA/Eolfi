"""G5: actualizar modelos (PLAN_DEFINITIVO.md).

Dos pasos separados, ninguno adopta nada:

1. ``comprobar``: para cada modelo de un archivo de fuentes (``eolfi.modelos.fuentes/v1``) consulta la API pública de
   Hugging Face y compara el SHA-256 LFS del archivo publicado con el SHA-256 del modelo local. Solo lee metadatos.
2. ``descargar``: baja UN archivo de una revisión fijada (commit de 40 hex) a un archivo nuevo, comprueba tamaño y
   SHA-256 contra los valores revisados y lo pasa por la auditoría GGUF de G1. Deja un recibo ``descarga.json``.

Garantías y límites:
- Sin ``red=True`` no se abre ninguna conexión; con ``EOLAS_OFFLINE=1`` se rechaza siempre.
- Solo HTTPS a ``huggingface.co`` y sus CDN (``*.huggingface.co``, ``*.hf.co``), también en las redirecciones.
- No envía credenciales: los repositorios privados o con licencia aceptada por cuenta fallan como NO VERIFICADO.
- La descarga nunca sobrescribe; un archivo con hash distinto queda como ``.rechazado`` para revisarlo, no se usa.
- El hash publicado demuestra que se recibió lo publicado, no que el modelo sea seguro ni mejor. La comparación con
  el banco y la adopción (perfil, lista de confianza) siguen pendientes y quedan marcadas en ``verificacion``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eolfi.acciones import registrada

SCHEMA_FUENTES = "eolfi.modelos.fuentes/v1"
SCHEMA_COMPROBACION = "eolfi.modelos.actualizacion/v1"
SCHEMA_DESCARGA = "eolfi.modelos.descarga/v1"
API = "https://huggingface.co/api/models/{repo}/revision/{rev}?blobs=true"
RESOLVE = "https://huggingface.co/{repo}/resolve/{rev}/{archivo}"
HOSTS = ("huggingface.co", "hf.co")
LIMITE_API = 8 * 1024 * 1024
TIMEOUT = 60
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SHA = re.compile(r"[0-9a-f]{64}")

Fetch = Callable[[str], bytes]
Stream = Callable[[str], Iterator[bytes]]


class ActualizarError(ValueError):
    pass


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _host_permitido(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == h or host.endswith("." + h) for h in HOSTS)


def _exigir_red(red: bool) -> None:
    if os.environ.get("EOLAS_OFFLINE", "").strip() in ("1", "true", "yes"):
        raise ActualizarError("EOLAS_OFFLINE=1: G5 no abre conexiones en modo sin red")
    if not red:
        raise ActualizarError("comprobar o descargar modelos abre la red: indícalo con --red")


def _validar_archivo(nombre: str) -> str:
    if (not isinstance(nombre, str) or not nombre or nombre.startswith(("/", "\\")) or "\\" in nombre
            or any(p in ("", ".", "..") for p in nombre.split("/")) or not nombre.lower().endswith(".gguf")):
        raise ActualizarError(f"archivo de modelo no válido: {nombre!r} (ruta relativa del repositorio, .gguf)")
    return nombre


class _SoloHostsPermitidos(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _host_permitido(newurl):
            raise ActualizarError(f"redirección a un destino no permitido: {urllib.parse.urlsplit(newurl).hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _abrir(url: str):
    if not _host_permitido(url):
        raise ActualizarError(f"destino no permitido: {url}")
    opener = urllib.request.build_opener(_SoloHostsPermitidos())
    # Sin cabecera de autorización ni cookies: nunca se envían credenciales del usuario.
    req = urllib.request.Request(url, headers={"User-Agent": "eolfi-modelos/1", "Accept": "*/*"})
    return opener.open(req, timeout=TIMEOUT)


def _fetch_red(url: str) -> bytes:
    with _abrir(url) as resp:
        data = resp.read(LIMITE_API + 1)
    if len(data) > LIMITE_API:
        raise ActualizarError("respuesta de la API demasiado grande")
    return data


def _stream_red(url: str) -> Iterator[bytes]:
    with _abrir(url) as resp:
        while True:
            chunk = resp.read(4 * 1024 * 1024)
            if not chunk:
                return
            yield chunk


# ── Fuentes ───────────────────────────────────────────────────────────────────────────────────────────────────────

def leer_fuentes(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_FUENTES or not isinstance(data.get("modelos"), list):
        raise ActualizarError(f"archivo de fuentes inválido (se espera schema {SCHEMA_FUENTES} y una lista «modelos»)")
    vistos: set[str] = set()
    out = []
    for i, e in enumerate(data["modelos"], 1):
        if not isinstance(e, dict):
            raise ActualizarError(f"fuente {i}: debe ser un objeto")
        nombre = str(e.get("nombre") or "")
        if not nombre or nombre in vistos:
            raise ActualizarError(f"fuente {i}: «nombre» vacío o repetido")
        vistos.add(nombre)
        repo = str(e.get("repo") or "")
        if not _REPO.fullmatch(repo):
            raise ActualizarError(f"{nombre}: «repo» debe ser propietario/nombre de Hugging Face")
        sha = e.get("sha256")
        if sha is not None and (not isinstance(sha, str) or not _SHA.fullmatch(sha.lower())):
            raise ActualizarError(f"{nombre}: «sha256» local inválido")
        out.append({"nombre": nombre, "repo": repo, "archivo": _validar_archivo(e.get("archivo")),
                    "rama": str(e.get("rama") or "main"), "sha256": sha.lower() if sha else None,
                    "local": str(e["local"]) if e.get("local") else None})
    return out


def _sha_local(fuente: dict[str, Any]) -> tuple[str | None, str]:
    if fuente["sha256"]:
        return fuente["sha256"], "declarado"
    local = fuente.get("local")
    if local and Path(local).is_file():
        from eolfi.modelos import sha256

        return sha256(local), "calculado"
    return None, "desconocido"


# ── Comprobar ─────────────────────────────────────────────────────────────────────────────────────────────────────

def comprobar(fuentes: str | Path, *, nombre: str | None = None, red: bool = False,
              fetch: Fetch | None = None) -> dict[str, Any]:
    """Compara cada fuente con lo publicado. No escribe nada ni descarga pesos."""
    lista = leer_fuentes(fuentes)
    if nombre:
        lista = [f for f in lista if f["nombre"] == nombre]
        if not lista:
            raise ActualizarError(f"no hay ninguna fuente llamada {nombre!r}")
    _exigir_red(red)
    fetch = fetch or _fetch_red
    resultados = [_comprobar_una(f, fetch) for f in lista]
    estados = {r["estado"] for r in resultados}
    estado = ("NO VERIFICADO" if "NO VERIFICADO" in estados else
              "nueva_version" if "nueva_version" in estados else "al_dia")
    return {"schema": SCHEMA_COMPROBACION, "fecha": _ahora(), "estado": estado, "modelos": resultados,
            "limite": "Solo compara hashes publicados; no descarga, no audita ni adopta. Banco y adopción pendientes."}


def _comprobar_una(fuente: dict[str, Any], fetch: Fetch) -> dict[str, Any]:
    base = {"nombre": fuente["nombre"], "repo": fuente["repo"], "archivo": fuente["archivo"]}
    sha_local, origen = _sha_local(fuente)
    base.update(sha256_local=sha_local, sha256_local_origen=origen)
    url = API.format(repo=fuente["repo"], rev=urllib.parse.quote(fuente["rama"], safe=""))
    try:
        info = json.loads(fetch(url).decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError, ActualizarError) as exc:
        return {**base, "estado": "NO VERIFICADO", "error": f"{type(exc).__name__}: {exc}"[:300]}
    commit = str(info.get("sha") or "")
    sibling = next((s for s in info.get("siblings") or [] if isinstance(s, dict)
                    and s.get("rfilename") == fuente["archivo"]), None)
    if not _COMMIT.fullmatch(commit):
        return {**base, "estado": "NO VERIFICADO", "error": "la API no devolvió un commit válido"}
    if sibling is None:
        return {**base, "estado": "NO VERIFICADO", "revision": commit,
                "error": "el archivo ya no está publicado en ese repositorio"}
    lfs = sibling.get("lfs") or {}
    remoto = str(lfs.get("sha256") or "").lower()
    size = lfs.get("size") or sibling.get("size")
    if not _SHA.fullmatch(remoto):
        return {**base, "estado": "NO VERIFICADO", "revision": commit, "error": "sin SHA-256 LFS publicado"}
    out = {**base, "revision": commit, "sha256_publicado": remoto, "bytes": size,
           "ultima_modificacion": info.get("lastModified")}
    if sha_local is None:
        return {**out, "estado": "NO VERIFICADO", "error": "sin SHA-256 local con el que comparar"}
    if remoto == sha_local:
        return {**out, "estado": "al_dia"}
    return {**out, "estado": "nueva_version",
            "descarga": {"repo": fuente["repo"], "archivo": fuente["archivo"], "revision": commit,
                         "sha256": remoto, "bytes": size}}


# ── Descargar ─────────────────────────────────────────────────────────────────────────────────────────────────────

@registrada("modelos.descargar", campos=("repo", "archivo", "revision", "sha256", "destino"),
            resultado=("estado", "archivo_local", "sha256_obtenido", "bytes", "error"))
def descargar(repo: str, archivo: str, revision: str, sha256: str, destino: str | Path, *, red: bool = False,
              bytes_esperados: int | None = None, stream: Stream | None = None) -> dict[str, Any]:
    """Descarga un archivo fijado por commit y SHA-256 a una carpeta, sin sobrescribir, y lo audita (G1)."""
    if not _REPO.fullmatch(repo or ""):
        raise ActualizarError("repo debe ser propietario/nombre")
    archivo = _validar_archivo(archivo)
    if not _COMMIT.fullmatch(revision or ""):
        raise ActualizarError("revision debe ser el commit completo (40 hex) revisado con «comprobar»")
    sha256 = (sha256 or "").lower()
    if not _SHA.fullmatch(sha256):
        raise ActualizarError("sha256 debe ser el SHA-256 publicado y revisado (64 hex)")
    carpeta = Path(destino)
    final = carpeta / Path(archivo).name
    parcial = final.with_name(final.name + ".part")
    for p in (final, parcial, final.with_name(final.name + ".rechazado")):
        if p.exists():
            raise ActualizarError(f"ya existe {p}: G5 nunca sobrescribe")
    _exigir_red(red)
    carpeta.mkdir(parents=True, exist_ok=True)
    if bytes_esperados:
        libre = shutil.disk_usage(carpeta).free
        if libre < bytes_esperados + 64 * 1024 * 1024:
            raise ActualizarError(f"espacio insuficiente: hacen falta {bytes_esperados} bytes y quedan {libre}")
    url = RESOLVE.format(repo=repo, rev=revision, archivo=urllib.parse.quote(archivo))
    stream = stream or _stream_red
    h = hashlib.sha256()
    total = 0
    recibo: dict[str, Any] = {"schema": SCHEMA_DESCARGA, "inicio": _ahora(), "repo": repo, "archivo": archivo,
                              "revision": revision, "sha256_esperado": sha256, "bytes_esperados": bytes_esperados,
                              "url": url}
    try:
        with open(parcial, "xb") as fh:
            for chunk in stream(url):
                total += len(chunk)
                if bytes_esperados and total > bytes_esperados:
                    raise ActualizarError("se recibieron más bytes de los publicados")
                h.update(chunk)
                fh.write(chunk)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException as exc:
        estado = "interrumpido" if isinstance(exc, KeyboardInterrupt) else "fallido"
        recibo.update(fin=_ahora(), estado=estado, bytes=total, error=f"{type(exc).__name__}: {exc}"[:300],
                      archivo_parcial=str(parcial) if parcial.exists() else None)
        _escribir_recibo(carpeta, recibo)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return recibo
    obtenido = h.hexdigest()
    recibo.update(bytes=total, sha256_obtenido=obtenido, fin=_ahora())
    if obtenido != sha256 or (bytes_esperados and total != bytes_esperados):
        rechazado = final.with_name(final.name + ".rechazado")
        os.replace(parcial, rechazado)
        recibo.update(estado="fallido", archivo_rechazado=str(rechazado),
                      error="el SHA-256 o el tamaño no coinciden con lo publicado: no se usa")
        _escribir_recibo(carpeta, recibo)
        return recibo
    os.replace(parcial, final)
    from eolfi.modelos import audit

    auditoria = audit(final)
    recibo.update(archivo_local=str(final), auditoria={"estado": auditoria.get("estado"),
                                                        "errores": auditoria.get("errores"),
                                                        "incognitas": auditoria.get("incognitas")})
    recibo["estado"] = "descargado" if auditoria.get("estado") != "fallido" else "fallido"
    recibo["verificacion"] = {"hash": "coincide con lo publicado", "auditoria_g1": auditoria.get("estado"),
                              "banco": "NO VERIFICADO", "adopcion": "pendiente (G6: plan y adoptar)"}
    _escribir_recibo(carpeta, recibo)
    return recibo


def _escribir_recibo(carpeta: Path, recibo: dict[str, Any]) -> None:
    path = carpeta / "descarga.json"
    if path.exists():
        path = carpeta / f"descarga-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    path.write_text(json.dumps(recibo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    recibo["recibo"] = str(path)
