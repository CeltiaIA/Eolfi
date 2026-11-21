"""Dónde van los proyectos que genera Eolfi: SIEMPRE fuera de su propio repositorio.

21/11/2026, titular: «los proyectos generados tienen que quedar siempre fuera; después, si son válidos, tendrán su
repo propio». Antes iban a ``generated/`` dentro de la carpeta de Eolfi (ignorada por git, pero mezclada con el
código). Ahora la carpeta por defecto es ``Eolfi-proyectos`` junto al repositorio (``D:\\Eolfi-proyectos``), o la de
``EOLFI_PROYECTOS``; y cualquier destino dentro del repositorio de Eolfi se rechaza.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def carpeta() -> Path:
    """Carpeta por defecto de los proyectos generados (no se crea aquí)."""
    env = os.environ.get("EOLFI_PROYECTOS", "").strip()
    return Path(env).expanduser().resolve() if env else (REPO.parent / "Eolfi-proyectos").resolve()


def dentro_del_repo(destino: str | Path) -> bool:
    try:
        Path(destino).resolve().relative_to(REPO)
    except ValueError:
        return False
    return True


def comprobar_fuera(destino: str | Path) -> None:
    """ValueError si el destino cae dentro del repositorio de Eolfi."""
    if dentro_del_repo(destino):
        raise ValueError(f"los proyectos generados van fuera del repositorio de Eolfi ({REPO}); usa por ejemplo "
                         f"{carpeta() / Path(destino).name} (si el proyecto es válido, tendrá su propio repositorio)")
