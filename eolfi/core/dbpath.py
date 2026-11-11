"""Ruta por defecto de la base de evidencias (LIM-013, decisión del titular 2026-11-11).

Antes la base por defecto era ``eolfi.db`` en la carpeta actual: quedaba junto al código, con ``client_tokens``, y
podía acabar en una copia o un zip del proyecto. Ahora el orden es:

1. ``--db RUTA`` explícito.
2. La variable ``EOLFI_DB``.
3. ``eolfi.db`` en la carpeta de datos de Eolfi (``EOLFI_HOME`` o ``~/.eolfi``).

La primera vez, si en la carpeta actual hay una ``eolfi.db`` antigua y en la carpeta de datos no hay ninguna, se
**copia** con la API de copia de SQLite (incluye lo pendiente en el WAL y es coherente aunque otra conexión la tenga
abierta) y se avisa. La original no se borra ni se modifica. Si la copia falla, se sigue usando la antigua.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Callable

DB_NAME = "eolfi.db"
MIGRATED = "eolfi.db.migrado.json"


def data_home() -> Path:
    return Path(os.environ.get("EOLFI_HOME") or Path.home() / ".eolfi")


def _log(msg: str) -> None:
    print(f"Eolfi: {msg}", file=sys.stderr)


def _migrated(home: Path) -> list[str]:
    try:
        data = json.loads((home / MIGRATED).read_text(encoding="utf-8"))
        return [str(p) for p in data.get("from", [])]
    except (OSError, ValueError, AttributeError):
        return []


def _copy(src: Path, dst: Path) -> None:
    tmp = dst.with_name(dst.name + ".copiando")
    tmp.unlink(missing_ok=True)
    source = sqlite3.connect(str(src))
    try:
        target = sqlite3.connect(str(tmp))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    os.replace(tmp, dst)


def resolve_db(explicit: str | None, *, cwd: str | Path | None = None, log: Callable[[str], None] = _log) -> str:
    """Devuelve la ruta de la base de evidencias que se debe usar (ver el docstring del módulo)."""
    if explicit:
        return explicit
    env = os.environ.get("EOLFI_DB", "").strip()
    if env:
        return env
    home = data_home()
    target = home / DB_NAME
    legacy = Path(cwd or os.getcwd()) / DB_NAME
    try:
        same = legacy.is_file() and target.exists() and legacy.resolve() == target.resolve()
    except OSError:
        same = False
    if not legacy.is_file() or same:
        home.mkdir(parents=True, exist_ok=True)
        return str(target)
    legacy_key = str(legacy.resolve())
    if not target.exists():
        try:
            home.mkdir(parents=True, exist_ok=True)
            _copy(legacy, target)
            (home / MIGRATED).write_text(json.dumps({"from": [legacy_key]}, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
        except (OSError, sqlite3.Error) as exc:
            log(f"no se pudo copiar {legacy} a {target} ({type(exc).__name__}: {exc}); se sigue usando {legacy}")
            return str(legacy)
        log(f"la base de evidencias pasa a {target}. Se ha copiado {legacy}, que se conserva sin cambios y ya "
            f"no se usa por defecto (para usarla: --db \"{legacy}\").")
        return str(target)
    if legacy_key not in _migrated(home):
        log(f"en esta carpeta hay una {DB_NAME} que no se usa; la base por defecto es {target}. Para usar la de "
            f"aquí: --db \"{legacy}\".")
    return str(target)
