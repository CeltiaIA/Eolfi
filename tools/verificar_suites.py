"""Guardia: ejecuta las cuatro suites de AGENTS.md y falla si alguna no está en verde (14/11/2026).

Decisión del titular: «poner un guard para que no puedan pasar cosas con fallos sin arreglar». Lo usa el gancho
`.githooks/pre-push` (actívalo con `git config core.hooksPath .githooks`) y se puede ejecutar a mano:

    python tools/verificar_suites.py            # las cuatro
    python tools/verificar_suites.py --sin-e2e  # sin navegador (solo para diagnosticar; el gancho no lo usa)

Una suite que no se puede ejecutar (falta node, falta el navegador, faltan dependencias) cuenta como FALLO, no como
aprobada: lo no verificado no pasa.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITES = (
    ("pytest", [sys.executable, "-m", "pytest", "-q"], ROOT),
    ("puente", ["node", "--test"], ROOT / "eolfi" / "bridge"),
    ("puente VS Code", ["node", "--test"], ROOT / "eolfi" / "vscode-bridge"),
    ("navegador (e2e)", ["npm", "test"], ROOT / "tests" / "e2e"),
)


def clean_env() -> dict[str, str]:
    """Entorno de las suites SIN las variables GIT_* (13/11/2026).

    Git ejecuta el gancho pre-push con GIT_DIR (y otras) apuntando a este repositorio. Las pruebas que crean
    repositorios temporales con «git init/commit/update-ref» las heredaban y escribieron en el repositorio de Eolfi:
    lo marcaron como bare y añadieron commits a las ramas que se estaban subiendo."""
    return {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}


def run(name: str, argv: list[str], cwd: Path) -> tuple[bool, str]:
    start = time.monotonic()
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           shell=os.name == "nt" and argv[0] == "npm", timeout=3600, env=clean_env())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"no se pudo ejecutar: {exc}"
    tail = [ln for ln in (p.stdout + p.stderr).splitlines() if ln.strip()][-3:]
    return p.returncode == 0, f"{time.monotonic() - start:.0f} s · " + " | ".join(tail)[-300:]


def main(argv: list[str]) -> int:
    # 13/11/2026: en una consola cp1252 el «ℹ» que imprime `node --test` tiraba la guardia con UnicodeEncodeError
    # antes de llegar al resultado. La salida se escribe en UTF-8 y lo que no quepa se sustituye.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    suites = [s for s in SUITES if not ("--sin-e2e" in argv and s[0].startswith("navegador"))]
    failed = []
    for name, cmd, cwd in suites:
        print(f"== {name} …", flush=True)
        ok, info = run(name, cmd, cwd)
        print(f"   {'VERDE' if ok else 'FALLA'} · {info}", flush=True)
        if not ok:
            failed.append(name)
    if failed:
        print(f"\nGUARDIA: no pasa. Suites con fallos o sin ejecutar: {', '.join(failed)}. Arréglalas antes de subir.")
        return 1
    print("\nGUARDIA: las suites están en verde.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
