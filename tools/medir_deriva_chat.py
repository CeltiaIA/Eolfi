"""Mide cuánto divaga o alucina el chat de Eolfi con el motor REAL (17/11/2026).

Repite N veces cada prompt de tests/chat_deriva_casos.json (sacados de una conversación real con gemma-4-12b) y
cuenta, con eolfi.chat_honestidad, los defectos de la respuesta ANTES de la ronda de corrección (lo que el modelo
dice por sí mismo) y DESPUÉS (lo que ve el usuario). También mide la variación: cuántos conjuntos de defectos
distintos aparecen para el mismo prompt.

    python tools/medir_deriva_chat.py --repeticiones 5 --salida deriva.json
    python tools/medir_deriva_chat.py --vscode activo        # simula el puente activo en el contexto

Carga el motor Eolas V2 activo (GPU) o usa EOLFI_CHAT_URL/MODEL/API_KEY si están definidas. Las herramientas son
las del servidor MCP de Eolfi, con una base de datos temporal y sin carpetas permitidas (no lee tus archivos).
El detector es de patrones: un 0 aquí no prueba que el modelo no invente otras cosas.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from eolfi import chat, eolas_v2  # noqa: E402
from eolfi.mcp_server import EolfiMCP  # noqa: E402


def medir(engine: dict, prompts: list[dict], repeticiones: int, estado: dict, db: str) -> dict:
    filas = []
    for p in prompts:
        corridas = []
        for i in range(repeticiones):
            t0 = time.time()
            mcp = chat.Toolbox(EolfiMCP(db=db, roots=[tempfile.gettempdir()]), {})
            try:
                out = chat.agent_turn([{"role": "user", "content": p["texto"]}], engine, mcp, lambda s: None,
                                      estado=estado)
                corridas.append({"inicial": out["revision"]["inicial"], "final": out["revision"]["final"],
                                 "herramientas": [t["name"] for t in out["tools"]], "segundos": round(time.time() - t0, 1),
                                 "texto": out["text"][:600]})
            except RuntimeError as exc:
                corridas.append({"error": str(exc)[:300]})
            print(f"{p['id']} #{i + 1}: {corridas[-1].get('inicial', corridas[-1].get('error'))}", flush=True)
        validas = [c for c in corridas if "error" not in c]
        cuenta = collections.Counter(code for c in validas for code in c["inicial"])
        filas.append({
            "id": p["id"], "corridas": corridas, "validas": len(validas),
            "con_defecto_inicial": sum(1 for c in validas if c["inicial"]),
            "con_defecto_final": sum(1 for c in validas if c["final"]),
            "defectos": dict(cuenta),
            "variantes": len({tuple(sorted(c["inicial"])) for c in validas}),
        })
    total = sum(f["validas"] for f in filas)
    return {"motor": engine.get("label"), "repeticiones": repeticiones, "estado": estado, "prompts": filas,
            "resumen": {"respuestas": total,
                        "con_defecto_inicial": sum(f["con_defecto_inicial"] for f in filas),
                        "con_defecto_final": sum(f["con_defecto_final"] for f in filas)}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repeticiones", type=int, default=3)
    ap.add_argument("--vscode", choices=("activo", "inactivo"), default="inactivo")
    ap.add_argument("--salida", type=Path)
    a = ap.parse_args()
    casos = json.loads((RAIZ / "tests" / "chat_deriva_casos.json").read_text(encoding="utf-8"))
    estado = {"vscode": {"activo": a.vscode == "activo", "carpetas": []}}
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "deriva.db")
        remote = chat.remote_engine()
        if remote:
            informe = medir(remote, casos["prompts"], a.repeticiones, estado, db)
        else:
            with eolas_v2.inference_profile(str(eolas_v2.load_config()["active_profile"])) as c:
                informe = medir(chat.local_engine(c), casos["prompts"], a.repeticiones, estado, db)
    r = informe["resumen"]
    print(f"\n{informe['motor']}: {r['con_defecto_inicial']}/{r['respuestas']} respuestas con defecto antes de corregir, "
          f"{r['con_defecto_final']}/{r['respuestas']} después.")
    for f in informe["prompts"]:
        print(f"  {f['id']}: {f['con_defecto_inicial']}/{f['validas']} → {f['con_defecto_final']}/{f['validas']}, "
              f"{f['variantes']} variantes, {f['defectos']}")
    if a.salida:
        a.salida.write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
