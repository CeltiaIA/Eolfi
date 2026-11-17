"""B2: ¿la misma petición con semilla da el MISMO texto? Medición reproducible por motor (18/11/2026).

Envía N veces la misma petición de generación con ``EOLFI_SEMILLA`` (semilla + temperatura 0, y en llama-server
sin caché de prompt) y cuenta cuántas salidas distintas aparecen. Con ``--frio`` descarga el modelo de Eolas V1
entre peticiones (``keep_alive: 0``), para comparar en frío y en caliente: así se encontró en V2 que la caché de
prompt cambiaba el texto.

    python tools/medir_determinismo.py --motor eolas --repeticiones 7 --frio --salida b2-eolas-v1.json
    python tools/medir_determinismo.py --motor eolas-v2 --repeticiones 7

No arranca motores: el motor tiene que estar ya en marcha. Un resultado de N/N idénticas con un prompt no prueba
que todo el banco sea determinista; mide este motor, este modelo y este prompt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

SISTEMA = "Eres un generador de código. Responde solo con JSON válido según el esquema."
PROMPT = ("Escribe en Python una función `resumen(numeros)` que devuelva un diccionario con la media, la mediana y la "
          "desviación típica de una lista de números, sin bibliotecas externas, y explica en tres frases cómo "
          "trata la lista vacía.")
ESQUEMA = {"type": "object", "properties": {"codigo": {"type": "string"}, "explicacion": {"type": "string"}},
           "required": ["codigo", "explicacion"], "additionalProperties": False}


def medir(completar: Callable[[], str], repeticiones: int,
          enfriar: Callable[[], Any] | None = None) -> dict[str, Any]:
    """Llama `completar` N veces (enfriando antes de las impares si hay `enfriar`) y agrupa los textos por huella."""
    corridas = []
    for i in range(repeticiones):
        estado = "caliente"
        if enfriar is not None and i % 2 == 0:
            enfriar()
            estado = "frío"
        t0 = time.monotonic()
        texto = completar()
        corridas.append({"n": i + 1, "estado": estado, "segundos": round(time.monotonic() - t0, 1),
                         "sha256": hashlib.sha256(texto.encode("utf-8")).hexdigest(), "caracteres": len(texto),
                         "inicio": texto[:120]})
        print(f"#{i + 1} {estado}: {corridas[-1]['sha256'][:12]} ({corridas[-1]['segundos']} s)", flush=True)
    huellas: dict[str, int] = {}
    for c in corridas:
        huellas[c["sha256"]] = huellas.get(c["sha256"], 0) + 1
    mayoritaria = max(huellas.values()) if huellas else 0
    return {"repeticiones": repeticiones, "distintas": len(huellas), "identicas": mayoritaria,
            "determinista": len(huellas) == 1 and repeticiones > 0, "corridas": corridas}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--motor", default="eolas", help="proveedor de eolfi.generador.llm (eolas, eolas-v2…)")
    ap.add_argument("--modelo")
    ap.add_argument("--repeticiones", type=int, default=7)
    ap.add_argument("--semilla", type=int, default=0)
    ap.add_argument("--frio", action="store_true", help="Eolas V1: descarga el modelo antes de las peticiones impares")
    ap.add_argument("--salida", type=Path)
    a = ap.parse_args()
    os.environ["EOLFI_SEMILLA"] = str(a.semilla)

    from eolfi.generador import llm

    proveedor = llm.make_provider(a.motor, model=a.modelo)
    mensajes = [{"role": "user", "content": PROMPT}]
    enfriar = None
    if a.frio:
        if a.motor != "eolas":
            ap.error("--frio solo está implementado para Eolas V1 (keep_alive: 0)")
        from eolfi.local_gpu import release_eolas

        enfriar = lambda: release_eolas(proveedor.base_url)  # noqa: E731
    informe = medir(lambda: proveedor.complete(SISTEMA, mensajes, ESQUEMA, "low").history_content,
                    a.repeticiones, enfriar)
    informe.update({"motor": a.motor, "modelo": getattr(proveedor, "model", None), "semilla": a.semilla,
                    "frio": a.frio, "fecha": time.strftime("%Y-%m-%d %H:%M")})
    print(f"\n{a.motor} ({informe['modelo']}): {informe['identicas']}/{a.repeticiones} idénticas, "
          f"{informe['distintas']} salida(s) distinta(s)")
    if a.salida:
        a.salida.write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if informe["determinista"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
