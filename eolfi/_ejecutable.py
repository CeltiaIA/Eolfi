"""Punto de entrada del ejecutable de Eolfi (PyInstaller; lo usa ``tools/construir_ejecutable.py``).

Eolfi se relanza a sí mismo con ``[sys.executable, "-m", "eolfi", ...]`` (``up``, el reinicio del panel, el banco) y
con otros módulos (``-m eolfi.providers.isolated``, ``-m eolfi.local_gpu``). En el ejecutable ``sys.executable`` es
``eolfi.exe``: por eso este lanzador acepta ``-m MÓDULO ARGUMENTOS`` como el intérprete y ejecuta ese módulo. Sin
``-m`` es la CLI normal.
"""
from __future__ import annotations

import runpy
import sys


def principal(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) >= 2 and argv[0] == "-m":
        modulo = argv[1]
        if not modulo.startswith("eolfi"):
            print(f"eolfi: el ejecutable solo lanza módulos de Eolfi, no «{modulo}»", file=sys.stderr)
            return 2
        sys.argv = [sys.argv[0], *argv[2:]]
        try:
            runpy.run_module(modulo, run_name="__main__", alter_sys=True)
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        return 0
    from eolfi.cli import main

    return main(argv)


if __name__ == "__main__":
    raise SystemExit(principal())
