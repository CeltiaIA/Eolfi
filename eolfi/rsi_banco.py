"""Bancos de evaluación del RSI (PLAN_REA.md, punto 12). Un banco es una función que devuelve una puntuación
entre 0 y 1 y puede recibir la semilla del par; ``rsi.evaluar`` la llama en pares alternados (actual y candidata).

Banco «tareas»: el mismo encargo de la competición V1/V2 del 16/11/2026. Eolfi crea un sitio estático desde
``tools/rsi/fuente-tareas``, la IA local implementa una lista de tareas (``create --ai``) y el juez funcional de
``tools/rsi/juez-tareas.mjs`` la prueba en Chrome. Puntuación: comprobaciones superadas / totales; si la creación o
su verificación fallan, 0. El proyecto se genera en una carpeta temporal que se borra al acabar.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUENTE = ROOT / "tools" / "rsi" / "fuente-tareas"
JUEZ = ROOT / "tools" / "rsi" / "juez-tareas.mjs"
ENCARGO = ("Implementa la lista de tareas: añadir una tarea con el formulario, marcarla como hecha al hacer clic, "
           "borrarla con un botón y mostrar en #resumen cuántas quedan pendientes. Guarda las tareas en localStorage.")
BANCOS = ("tareas",)


def juzgar(proyecto: Path, *, timeout: float = 300) -> dict:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("el juez necesita Node.js")
    out = subprocess.run([node, str(JUEZ), str(proyecto)], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=timeout, cwd=JUEZ.parent, check=False)
    if out.returncode != 0:
        raise RuntimeError(f"el juez falló: {out.stderr.strip()[-400:]}")
    return json.loads(out.stdout)[proyecto.name]


def banco_tareas(*, proveedor: str, modelo: str | None = None, entorno: dict[str, str] | None = None,
                 timeout: float = 3600, registro: Callable[[dict], None] | None = None) -> Callable[..., float]:
    def correr(semilla: int | None = None) -> float:
        # La semilla identifica el par de ``rsi.evaluar``; la generación aún no la usa (fase 1.2 de PLAN_VAS.md).
        work = Path(tempfile.mkdtemp(prefix="eolfi-rsi-tareas-"))
        try:
            proyecto = work / "tareas"
            cmd = [sys.executable, "-m", "eolfi", "create", "--from", str(FUENTE), "--out", str(proyecto),
                   "--target", "static", "--name", "tareas", "--ai", ENCARGO, "--provider", proveedor]
            if modelo:
                cmd += ["--model", modelo]
            run = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 timeout=timeout, cwd=ROOT, env={**os.environ, **(entorno or {})}, check=False)
            if run.returncode != 0:
                score, detalle = 0.0, {"exit": run.returncode}
            else:
                j = juzgar(proyecto)
                score, detalle = j["passed"] / max(1, j["total"]), {"juez": f'{j["passed"]}/{j["total"]}'}
            if registro:
                registro({"banco": "tareas", "proveedor": proveedor, "semilla": semilla, "puntuacion": score, **detalle})
            return score
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return correr
