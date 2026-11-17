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
import time
from collections.abc import Callable
from pathlib import Path

from eolfi import telemetria

ROOT = Path(__file__).resolve().parents[1]
FUENTE = ROOT / "tools" / "rsi" / "fuente-tareas"
JUEZ = ROOT / "tools" / "rsi" / "juez-tareas.mjs"
CRITERIOS = ROOT / "tools" / "rsi" / "criterios-tareas.json"
ENCARGO = ("Implementa la lista de tareas: añadir una tarea con el formulario, marcarla como hecha al hacer clic, "
           "borrarla con un botón y mostrar en #resumen cuántas quedan pendientes. Guarda las tareas en localStorage.")
BANCOS_DIR = ROOT / "tools" / "rsi" / "bancos"
# Encargos del banco (PLAN_DEFINITIVO.md, B5). «tareas» conserva su juez propio; los demás viven en
# tools/rsi/bancos/<nombre>/ con fuente/, encargo.txt, criterios.json (los ve el proyecto: verify) y juez.json (el
# evaluador, que el proyecto no ve y comprueba MÁS casos que los criterios).
ENCARGOS = ("tareas", "contador", "filtro")
BANCOS = (*ENCARGOS, "todos")


def juzgar(proyecto: Path, *, timeout: float = 300) -> dict:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("el juez necesita Node.js")
    out = subprocess.run([node, str(JUEZ), str(proyecto)], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=timeout, cwd=JUEZ.parent, check=False)
    if out.returncode != 0:
        raise RuntimeError(f"el juez falló: {out.stderr.strip()[-400:]}")
    return json.loads(out.stdout)[proyecto.name]


def _ultima_linea(texto: str) -> str:
    """Última línea con contenido de la salida de errores: para saber por qué falló sin guardar todo."""
    lineas = [x.strip() for x in (texto or "").splitlines() if x.strip()]
    return lineas[-1][-300:] if lineas else ""


def _parcial(salida: str) -> bool:
    """¿``create --ai`` conservó un mejor intento parcial? (campo ``assist.parcial`` de su informe)."""
    try:
        return bool((json.loads(salida[salida.index("{"):]).get("assist") or {}).get("parcial"))
    except (ValueError, AttributeError):
        return False


def _mejor_intento(salida: str) -> dict:
    """Mejor resultado del juez de ``verify`` entre las rondas de un ``create --ai`` fallido (solo informativo)."""
    try:
        rondas = (json.loads(salida[salida.index("{"):]).get("assist") or {}).get("rounds") or []
    except (ValueError, AttributeError):
        return {}
    notas = [r["verification"]["judge"] for r in rondas
             if isinstance(r, dict) and isinstance((r.get("verification") or {}).get("judge"), dict)]
    notas = [n for n in notas if isinstance(n.get("passed"), int) and isinstance(n.get("total"), int)]
    if not notas:
        return {"rondas": len(rondas)}
    m = max(notas, key=lambda n: n["passed"])
    return {"rondas": len(rondas), "mejor_juez_verify": f'{m["passed"]}/{m["total"]}'}


def encargo(nombre: str) -> dict:
    """Archivos de un encargo: fuente, texto, criterios visibles y juez (None en «tareas», que usa JUEZ)."""
    if nombre == "tareas":
        return {"nombre": nombre, "fuente": FUENTE, "texto": ENCARGO, "criterios": CRITERIOS, "juez": None}
    if nombre not in ENCARGOS:
        raise ValueError(f"encargo desconocido: {nombre} (hay: {', '.join(ENCARGOS)})")
    d = BANCOS_DIR / nombre
    return {"nombre": nombre, "fuente": d / "fuente", "texto": (d / "encargo.txt").read_text(encoding="utf-8").strip(),
            "criterios": d / "criterios.json", "juez": d / "juez.json"}


def _puntuar(e: dict, proyecto: Path) -> dict:
    """Nota del evaluador: {"passed", "total"}. El juez declarativo se ejecuta con el mismo motor que el de verify."""
    if e["juez"] is None:
        return juzgar(proyecto)
    from eolfi.generador import juez as _juez

    j = _juez.juzgar(proyecto, _juez.validar(json.loads(Path(e["juez"]).read_text(encoding="utf-8"))))
    if j.get("status") != "ok":
        raise RuntimeError(f"el juez no pudo ejecutarse: {j.get('error', j.get('status'))}")
    return {"passed": j["passed"], "total": j["total"]}


def banco(nombre: str, **kw) -> Callable[..., float]:
    """Banco por nombre. «todos» reparte los encargos por semilla (par 0 → tareas, par 1 → contador…), de modo que
    la línea base y la candidata de un mismo par hacen el mismo encargo."""
    if nombre == "todos":
        partes = [banco_tareas(encargo_nombre=n, **kw) for n in ENCARGOS]
        return lambda semilla=0: partes[int(semilla or 0) % len(partes)](semilla)
    if nombre not in ENCARGOS:
        raise ValueError(f"banco desconocido: {nombre} (hay: {', '.join(BANCOS)})")
    return banco_tareas(encargo_nombre=nombre, **kw)


def banco_tareas(*, proveedor: str, modelo: str | None = None, entorno: dict[str, str] | None = None,
                 timeout: float = 3600, registro: Callable[[dict], None] | None = None,
                 juez_en_verify: bool = True, encargo_nombre: str = "tareas") -> Callable[..., float]:
    """``juez_en_verify``: el proyecto lleva los criterios del juez funcional, así que ``verify`` prueba la app en
    Chrome y las rondas de reparación ven qué falla (B1). La puntuación la sigue dando el juez externo, que el
    proyecto no ve. La semilla del par llega a la generación por ``EOLFI_SEMILLA`` (B2)."""
    e = encargo(encargo_nombre)

    def correr(semilla: int | None = None) -> float:
        work = Path(tempfile.mkdtemp(prefix=f"eolfi-rsi-{e['nombre']}-"))
        t0 = time.monotonic()
        try:
            proyecto = work / e["nombre"]
            cmd = [sys.executable, "-m", "eolfi", "create", "--from", str(e["fuente"]), "--out", str(proyecto),
                   "--target", "static", "--name", e["nombre"], "--ai", e["texto"], "--provider", proveedor]
            if modelo:
                cmd += ["--model", modelo]
            if juez_en_verify:
                cmd += ["--juez", str(e["criterios"])]
            fijo = {} if semilla is None else {"EOLFI_SEMILLA": str(int(semilla))}
            run = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 timeout=timeout, cwd=ROOT, env={**os.environ, **fijo, **(entorno or {})}, check=False)
            if run.returncode != 0 and _parcial(run.stdout) and proyecto.is_dir():
                # Sin verde, pero se conservó el mejor intento (B6): lo puntúa el evaluador como a cualquier otro.
                # No es una entrega en verde (queda anotado), pero da una nota graduada en vez de un cero.
                j = _puntuar(e, proyecto)
                score = j["passed"] / max(1, j["total"])
                detalle = {"exit": run.returncode, "parcial": True, "juez": f'{j["passed"]}/{j["total"]}',
                           **_mejor_intento(run.stdout)}
            elif run.returncode != 0:
                # Sin verde y sin nada que conservar (el proyecto se restaura): 0.
                score, detalle = 0.0, {"exit": run.returncode, **_mejor_intento(run.stdout),
                                       "error": _ultima_linea(run.stderr)}
            else:
                j = _puntuar(e, proyecto)
                score, detalle = j["passed"] / max(1, j["total"]), {"juez": f'{j["passed"]}/{j["total"]}'}
            telemetria.anotar("muestra", banco=e["nombre"], proveedor=proveedor, modelo=modelo, semilla=semilla,
                              puntuacion=float(score), minutos=(time.monotonic() - t0) / 60,
                              exit=run.returncode, juez_en_verify=juez_en_verify,
                              parcial=bool(detalle.get("parcial")))
            if registro:
                registro({"banco": e["nombre"], "proveedor": proveedor, "semilla": semilla, "puntuacion": score, **detalle})
            return score
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return correr
