"""Navegador propio de Eolfi (17/11/2026, pedido del titular).

El juez funcional de ``verify`` (B1) y la comprobación de accesibilidad (C4) necesitan un navegador, Playwright y
axe-core. Con ``eolfi navegador instalar`` Eolfi deja de depender del Chrome del equipo y de las pruebas e2e del
repositorio; todo queda dentro de ``~/.eolfi/navegador`` y no toca el sistema:

1. ``npm install`` de ``playwright-core`` y ``axe-core`` en las versiones fijadas aquí (las mismas que
   ``tests/e2e/package.json``), sin scripts de instalación; npm comprueba el sha512 del registro y lo deja en
   ``package-lock.json``.
2. ``playwright install --only-shell chromium``: Chrome Headless Shell de la revisión que corresponde a ese
   ``playwright-core``, descargado de ``cdn.playwright.dev`` (fuente oficial de Playwright).

Solo con la orden explícita del titular; nunca con ``EOLAS_OFFLINE=1``. Límite: Playwright no publica un SHA-256
del navegador; se anota el del ejecutable instalado (detecta cambios posteriores), no se compara con uno oficial.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFIESTO = "navegador.json"
# Las mismas que tests/e2e/package.json (una prueba lo comprueba).
DEPENDENCIAS = {"playwright-core": "1.64.1", "axe-core": "4.14.0"}


class NavegadorError(RuntimeError):
    pass


def carpeta() -> Path:
    base = os.environ.get("EOLFI_NAVEGADOR_DIR")
    if base:
        return Path(base)
    return Path(os.environ.get("EOLFI_HOME") or Path.home() / ".eolfi") / "navegador"


def playwright_propio() -> Path | None:
    p = carpeta() / "node_modules" / "playwright-core"
    return p if (p / "index.mjs").is_file() else None


def axe_propio() -> Path | None:
    p = carpeta() / "node_modules" / "axe-core" / "axe.min.js"
    return p if p.is_file() else None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for bloque in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _buscar(raiz: Path) -> Path | None:
    nombre = "chrome-headless-shell.exe" if sys.platform == "win32" else "chrome-headless-shell"
    hallados = sorted(raiz.glob(f"chromium_headless_shell-*/*/{nombre}"))
    return hallados[-1] if hallados else None


def _manifiesto() -> dict[str, Any] | None:
    try:
        info = json.loads((carpeta() / MANIFIESTO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return info if isinstance(info, dict) else None


def ejecutable() -> Path | None:
    """El ejecutable del navegador propio, si está instalado y dentro de su carpeta."""
    info = _manifiesto()
    try:
        exe = Path(info["ejecutable"]) if info else None
    except (KeyError, TypeError):
        return None
    return exe if exe and exe.is_file() and carpeta() in exe.parents else None


def estado(*, comprobar_hash: bool = False) -> dict[str, Any]:
    raiz, info = carpeta(), _manifiesto()
    if info is None:
        return {"instalado": False, "carpeta": str(raiz),
                "nota": "Sin navegador propio: el juez usa el Chrome del equipo y el Playwright de las pruebas "
                        "e2e si los hay. Instálalo con «eolfi navegador instalar» (unos 100 MB)."}
    exe = ejecutable()
    completo = exe is not None and playwright_propio() is not None and axe_propio() is not None
    out = {"instalado": completo, "carpeta": str(raiz), **{k: info.get(k) for k in (
        "ejecutable", "revision", "dependencias", "sha256", "bytes", "fecha")}}
    if not completo:
        out["nota"] = "Instalación incompleta (falta el navegador, playwright-core o axe-core): repite «eolfi " \
                      "navegador instalar»."
    elif comprobar_hash:
        out["sha256_coincide"] = _sha256(exe) == info.get("sha256")
    return out


def _run(cmd: list[str], cwd: Path, env: dict[str, str], plazo: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=plazo, check=False,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def instalar(*, plazo: float = 900) -> dict[str, Any]:
    """Instala playwright-core, axe-core y el navegador en ``carpeta()`` y escribe el manifiesto."""
    from eolfi import acciones

    node, npm = shutil.which("node"), shutil.which("npm")
    if node is None or npm is None:
        raise NavegadorError("Node.js/npm no están instalados")
    if os.environ.get("EOLAS_OFFLINE") == "1":
        raise NavegadorError("EOLAS_OFFLINE=1: no se descarga nada")
    raiz = carpeta()
    raiz.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(raiz)}

    def fallo(paso: str, proc: subprocess.CompletedProcess[str]) -> NavegadorError:
        error = (proc.stderr or proc.stdout or "")[-600:]
        acciones.anotar("navegador.instalar", params={"carpeta": str(raiz), "paso": paso}, ok=False,
                        error=error[-300:])
        return NavegadorError(f"{paso} falló (salida {proc.returncode}): {error}")

    (raiz / "package.json").write_text(json.dumps({
        "name": "eolfi-navegador", "private": True,
        "description": "Navegador y Playwright propios de Eolfi para el juez funcional (eolfi navegador)",
        "dependencies": DEPENDENCIAS}, indent=2) + "\n", encoding="utf-8")
    proc = _run([npm, "install", "--no-audit", "--no-fund", "--ignore-scripts"], raiz, env, plazo)
    if proc.returncode != 0 or playwright_propio() is None or axe_propio() is None:
        raise fallo("npm install de playwright-core y axe-core", proc)
    pw = playwright_propio()
    proc = _run([node, str(pw / "cli.js"), "install", "--only-shell", "chromium"], raiz, env, plazo)
    exe = _buscar(raiz)
    if proc.returncode != 0 or exe is None:
        raise fallo("descarga del navegador", proc)
    instaladas = {}
    for nombre in DEPENDENCIAS:
        try:
            instaladas[nombre] = json.loads((raiz / "node_modules" / nombre / "package.json")
                                            .read_text(encoding="utf-8"))["version"]
        except (OSError, ValueError, KeyError):
            instaladas[nombre] = None
    if instaladas != DEPENDENCIAS:
        raise NavegadorError(f"versiones instaladas distintas de las fijadas: {instaladas}")
    info = {"ejecutable": str(exe), "revision": exe.parent.parent.name.split("-")[-1],
            "dependencias": instaladas, "sha256": _sha256(exe), "bytes": exe.stat().st_size,
            "fecha": datetime.now(timezone.utc).isoformat(),
            "origen": "registro de npm (sha512 en package-lock.json) y cdn.playwright.dev",
            "nota": "SHA-256 del ejecutable instalado; Playwright no publica uno oficial para comparar."}
    (raiz / MANIFIESTO).write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    acciones.anotar("navegador.instalar", params={"carpeta": str(raiz)},
                    resultado={k: info[k] for k in ("revision", "dependencias", "sha256", "bytes")})
    return {"ok": True, **info}
