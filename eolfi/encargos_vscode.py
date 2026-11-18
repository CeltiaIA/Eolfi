"""Encargos del chat de Eolfi a @eolfi en VS Code, con cola de aprobación (18/11/2026).

El chat del panel puede encargar una aplicación nueva para la carpeta abierta en VS Code. Un encargo:

1. Se propone con el flujo VERIFICADO de Eolfi (plan de proyecto: analizar fuentes y ``create`` con verificación,
   juez funcional y accesibilidad). El modelo no escribe archivos a ciegas.
2. Queda en esta cola como «pendiente» con sus operaciones de riesgo: escribir la carpeta destino, ejecutar comandos
   de compilación y pruebas, instalar dependencias y usar la red. Nada se ejecuta todavía.
3. El titular lo aprueba o lo rechaza en el panel o en VS Code (la extensión muestra el aviso). Solo entonces se
   aprueba el plan y empieza el trabajo; el progreso se ve en los dos lados.

Cada alta y cada decisión quedan en el registro de acciones (``eolfi.acciones``). La cola vive en
``~/.eolfi/encargos-vscode.json`` (o ``EOLFI_ENCARGOS_VSCODE``); el estado del trabajo sale del caso del proyecto.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from eolfi.acciones import registrada

MAX_ENCARGOS = 200
ORIGENES = ("panel", "vscode")
_lock = threading.Lock()


def archivo() -> Path:
    env = os.environ.get("EOLFI_ENCARGOS_VSCODE")
    return Path(env) if env else Path.home() / ".eolfi" / "encargos-vscode.json"


def riesgos(carpeta: str, fuentes: list[str]) -> list[str]:
    """Operaciones de riesgo que el titular aprueba de una vez con el encargo (las dice el aviso en ambos lados)."""
    out = [f"escribir archivos nuevos en {carpeta} (debe estar vacía o no existir; nunca se sobrescribe)",
           "ejecutar los comandos de compilación, pruebas y prueba de humo del proyecto generado",
           "instalar sus dependencias (npm, pip, dotnet…) y usar la red para descargarlas"]
    if any(f.startswith(("http://", "https://", "git@", "ssh://")) for f in fuentes):
        out.append("descargar las fuentes indicadas (webs o repositorios)")
    return out


def _leer() -> list[dict[str, Any]]:
    try:
        data = json.loads(archivo().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []


def _guardar(items: list[dict[str, Any]]) -> None:
    path = archivo()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items[-MAX_ENCARGOS:], ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


@registrada("vscode.encargo_crear", campos=("nombre", "carpeta", "case_id"), huellas=("descripcion",),
            resultado=("id", "estado"))
def crear(*, nombre: str, descripcion: str, carpeta: str, fuentes: list[str], case_id: str,
          plan_version: int) -> dict[str, Any]:
    """Alta de un encargo pendiente de aprobación (el plan ya está propuesto, sin aprobar)."""
    entry = {"id": secrets.token_hex(16), "nombre": nombre, "descripcion": descripcion[:2000], "carpeta": carpeta,
             "fuentes": list(fuentes), "case_id": case_id, "plan_version": int(plan_version),
             "riesgos": riesgos(carpeta, list(fuentes)), "estado": "pendiente", "creado": time.time()}
    with _lock:
        items = _leer()
        items.append(entry)
        _guardar(items)
    return entry


def listar(estado: str | None = None) -> list[dict[str, Any]]:
    with _lock:
        items = _leer()
    return [e for e in reversed(items) if estado is None or e.get("estado") == estado]


def obtener(encargo_id: str) -> dict[str, Any]:
    for e in listar():
        if e.get("id") == encargo_id:
            return e
    raise KeyError(f"encargo no encontrado: {encargo_id}")


@registrada("vscode.encargo_decidir", campos=("encargo_id", "aprobar", "origen"), resultado=("id", "estado"))
def decidir(encargo_id: str, *, aprobar: bool, origen: str) -> dict[str, Any]:
    """Aprueba o rechaza un encargo PENDIENTE. Solo una vez: un encargo decidido no cambia de estado por aquí."""
    if origen not in ORIGENES:
        raise ValueError(f"origen no válido: {origen}")
    with _lock:
        items = _leer()
        entry = next((e for e in items if e.get("id") == encargo_id), None)
        if entry is None:
            raise KeyError(f"encargo no encontrado: {encargo_id}")
        if entry.get("estado") != "pendiente":
            raise ValueError(f"el encargo ya está {entry.get('estado')}")
        entry.update(estado="aprobado" if aprobar else "rechazado", decidido=time.time(), origen=origen)
        _guardar(items)
    return entry


def anotar(encargo_id: str, **campos: Any) -> dict[str, Any]:
    """Guarda datos del trabajo (job_id, error al arrancar…) sin cambiar la decisión."""
    with _lock:
        items = _leer()
        entry = next((e for e in items if e.get("id") == encargo_id), None)
        if entry is None:
            raise KeyError(f"encargo no encontrado: {encargo_id}")
        entry.update({k: v for k, v in campos.items() if k not in ("id", "estado", "origen", "decidido")})
        _guardar(items)
    return entry
