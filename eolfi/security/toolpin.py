"""Fijar y comprobar las herramientas externas usadas por Eolfi (Fase 6).

``collect()`` registra, para cada proveedor externo y para los intérpretes (Python, Node.js), su ruta, versión y
SHA-256 del ejecutable. ``write_lock`` lo guarda en un archivo de bloqueo; ``check_lock`` compara el equipo actual
con ese archivo y lista lo que cambió (otra versión, otro binario, herramienta ausente o nueva). Así un resultado
puede repetirse con las mismas herramientas o explicar por qué no.
"""
from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

LOCK_FORMAT = 1
_MAX_HASH = 512 * 1024 * 1024


def file_fingerprint(path: str | Path) -> str:
    h = hashlib.sha256()
    read = 0
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
            read += len(chunk)
            if read > _MAX_HASH:
                return h.hexdigest() + "+truncado"
    return h.hexdigest()


def _node() -> dict[str, Any] | None:
    exe = shutil.which("node")
    if not exe:
        return None
    try:
        ver = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        ver = "unknown"
    return {"path": str(Path(exe).resolve()), "version": ver, "sha256": file_fingerprint(exe)}


def collect() -> dict[str, Any]:
    from eolfi.flows.triage_flow import ALL_PROVIDERS

    tools: dict[str, Any] = {"python": {"path": sys.executable, "version": platform.python_version(),
                                        "sha256": file_fingerprint(sys.executable)}}
    node = _node()
    if node:
        tools["node"] = node
    for p in ALL_PROVIDERS:
        ident = p.tool_identity() if hasattr(p, "tool_identity") else None
        if ident is None:
            continue
        version = p._tool_version() if hasattr(p, "_tool_version") else getattr(p, "version", "")
        tools[p.name] = {**ident, "version": version}
    from eolfi import __version__

    return {"lock_format": LOCK_FORMAT, "eolfi": __version__, "platform": f"{platform.system()} {platform.release()} "
            f"{platform.machine()}", "created_at": time.time(), "tools": dict(sorted(tools.items()))}


def write_lock(path: str | Path) -> dict[str, Any]:
    data = collect()
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def compare(locked: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    drift = []
    lt, ct = locked.get("tools", {}), current.get("tools", {})
    for name in sorted(set(lt) | set(ct)):
        a, b = lt.get(name), ct.get(name)
        if a is None:
            drift.append({"tool": name, "change": "nueva", "now": b.get("version")})
        elif b is None:
            drift.append({"tool": name, "change": "ausente", "locked": a.get("version")})
        else:
            for k in ("version", "sha256"):
                if a.get(k) != b.get(k):
                    drift.append({"tool": name, "change": k, "locked": a.get(k), "now": b.get(k)})
    if locked.get("eolfi") != current.get("eolfi"):
        drift.append({"tool": "eolfi", "change": "version", "locked": locked.get("eolfi"), "now": current.get("eolfi")})
    return {"matches": not drift, "drift": drift, "locked_platform": locked.get("platform"),
            "platform": current.get("platform")}


def check_lock(path: str | Path) -> dict[str, Any]:
    locked = json.loads(Path(path).read_text(encoding="utf-8"))
    if locked.get("lock_format") != LOCK_FORMAT:
        raise ValueError("formato de archivo de bloqueo desconocido")
    return compare(locked, collect())
