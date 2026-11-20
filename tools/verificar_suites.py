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
import tempfile
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


TIMEOUT = 3600


def kill_tree(p: subprocess.Popen) -> None:
    """Mata la suite y TODOS sus descendientes (15/11/2026).

    Con `shell=True` en Windows, `subprocess.run(timeout=...)` solo mataba el `cmd` intermedio: npm y node quedaban
    huérfanos con las tuberías abiertas y la guardia esperaba para siempre (5 h colgada con un e2e bloqueado)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, check=False)
    else:
        try:
            os.killpg(p.pid, 9)
        except OSError:
            pass
    try:
        p.kill()
    except OSError:
        pass


def missing_dependencies(cwd: Path) -> str | None:
    """Una suite de npm sin node_modules no puede ejecutarse: se dice claramente en vez de fallar a ciegas."""
    if (cwd / "package.json").is_file() and not (cwd / "node_modules").is_dir():
        return f"faltan dependencias en {cwd.relative_to(ROOT)}: ejecuta «npm ci» allí (no se instalan solas)"
    return None


def run(name: str, argv: list[str], cwd: Path, timeout: float = TIMEOUT) -> tuple[bool, str]:
    start = time.monotonic()
    if argv[0] == "npm" and (why := missing_dependencies(cwd)):
        return False, f"no se pudo ejecutar: {why}"
    try:
        p = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                             text=True, encoding="utf-8", errors="replace", env=clean_env(),
                             shell=os.name == "nt" and argv[0] == "npm", start_new_session=os.name != "nt")
    except OSError as exc:
        return False, f"no se pudo ejecutar: {exc}"
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(p)
        try:
            p.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            pass
        return False, f"no se pudo ejecutar: sin terminar tras {timeout:.0f} s; se detuvo la suite y sus procesos"
    tail = [ln for ln in (out + err).splitlines() if ln.strip()][-3:]
    info = f"{time.monotonic() - start:.0f} s · " + " | ".join(tail)[-300:]
    if p.returncode != 0:
        # 20/11/2026: un fallo intermitente de pytest solo dejó «AssertionEr...» y no se pudo saber qué aserción
        # falló. La salida completa de una suite que falla se guarda fuera del repositorio.
        if saved := save_failure_log(name, out, err):
            info += f" · salida completa: {saved}"
    return p.returncode == 0, info


def save_failure_log(name: str, out: str, err: str) -> str | None:
    slug = "".join(c if c.isalnum() else "-" for c in name).strip("-") or "suite"
    path = Path(tempfile.gettempdir()) / f"eolfi-guardia-{slug}-{time.strftime('%Y%m%d-%H%M%S')}.log"
    try:
        path.write_text(f"{out}\n--- stderr ---\n{err}", encoding="utf-8", errors="replace")
    except OSError:
        return None
    return str(path)


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
