"""Telemetría local por fase (PLAN_DEFINITIVO.md, B4): cuánto tarda y qué rinde cada paso, para medir sin adivinar.

Una línea JSON por evento en ``~/.eolfi/telemetria/AAAA-MM.jsonl`` (``EOLFI_TELEMETRIA_DIR`` la cambia y
``EOLFI_TELEMETRIA=0`` la apaga). Solo números y nombres de proveedor, modelo y paso: nunca prompts, código, rutas
ni respuestas. No sale del equipo: nada de este módulo abre una conexión.

Eventos:
- ``ronda``: una ronda de ``assist`` (generación, verificación, tokens, tokens/s, juez, paso que falló).
- ``muestra``: una muestra de un banco del RSI (puntuación, minutos, semilla).
- ``carga``: desde el lanzamiento del servidor hasta que el perfil responde a la comprobación de salud.
"""
from __future__ import annotations

import json
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "eolfi-telemetria/v1"
_PERMITIDOS = (str, int, float, bool, type(None))
_MAX_TEXTO = 120


def activa() -> bool:
    return os.environ.get("EOLFI_TELEMETRIA", "1") != "0"


def carpeta() -> Path:
    return Path(os.environ.get("EOLFI_TELEMETRIA_DIR") or Path.home() / ".eolfi" / "telemetria")


def anotar(tipo: str, **datos: Any) -> dict[str, Any] | None:
    """Añade un evento. Solo valores planos (texto corto, números, booleanos); lo demás se descarta. Un fallo al
    escribir nunca rompe el trabajo que se está midiendo."""
    if not activa():
        return None
    limpio = {k: (v[:_MAX_TEXTO] if isinstance(v, str) else round(v, 3) if isinstance(v, float) else v)
              for k, v in datos.items() if isinstance(v, _PERMITIDOS)}
    ahora = datetime.now(timezone.utc)
    evento = {"schema": SCHEMA, "fecha": ahora.isoformat(timespec="seconds"), "tipo": tipo, **limpio}
    try:
        d = carpeta()
        d.mkdir(parents=True, exist_ok=True)
        with (d / f"{ahora:%Y-%m}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(evento, ensure_ascii=False) + "\n")
    except OSError:
        return None
    return evento


def eventos(tipo: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    d = carpeta()
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.jsonl")):
        for linea in f.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(linea)
            except ValueError:
                continue
            if isinstance(e, dict) and (tipo is None or e.get("tipo") == tipo):
                out.append(e)
    return out


def ronda(*, proveedor: str, modelo: str | None, destino: str, numero: int, generacion_s: float,
          verificacion_s: float, uso: dict[str, Any], tiempos: dict[str, Any], ok: bool, paso_fallido: str | None,
          juez: dict[str, Any] | None) -> None:
    """Evento de una ronda de ``assist``. Los tokens/s salen del motor si los da; si no, de salida / generación."""
    salida = int(uso.get("output_tokens", 0) or 0)
    tps = tiempos.get("predicted_per_second")
    if not isinstance(tps, (int, float)) and salida and generacion_s > 0:
        tps = salida / generacion_s
    semilla = os.environ.get("EOLFI_SEMILLA", "")
    anotar("ronda", proveedor=proveedor, modelo=modelo, destino=destino, ronda=numero,
           generacion_s=float(generacion_s), verificacion_s=float(verificacion_s),
           carga_declarada_s=tiempos.get("carga_declarada_s"),
           tokens_entrada=int(uso.get("input_tokens", 0) or 0), tokens_salida=salida,
           tokens_s=float(tps) if isinstance(tps, (int, float)) else None,
           lectura_tokens_s=float(tiempos["prompt_per_second"]) if isinstance(tiempos.get("prompt_per_second"), (int, float)) else None,
           ok=bool(ok), paso_fallido=paso_fallido,
           juez_superadas=(juez or {}).get("passed"), juez_total=(juez or {}).get("total"),
           semilla=int(semilla) if semilla.isdigit() else None)


def _mediana(valores: list[float]) -> float | None:
    v = [x for x in valores if isinstance(x, (int, float)) and not isinstance(x, bool)]
    return round(statistics.median(v), 2) if v else None


def resumen() -> dict[str, Any]:
    """Medianas por proveedor: lo que piden las métricas del plan (p50 por muestra, tokens/s, verificación)."""
    todos = eventos()
    rondas = [e for e in todos if e.get("tipo") == "ronda"]
    muestras = [e for e in todos if e.get("tipo") == "muestra"]
    cargas = [e for e in todos if e.get("tipo") == "carga"]
    por: dict[str, Any] = {}
    for prov in sorted({str(r.get("proveedor")) for r in rondas + cargas}):
        rs = [r for r in rondas if str(r.get("proveedor")) == prov]
        con_juez = [r for r in rs if isinstance(r.get("juez_total"), int) and r["juez_total"]]
        por[prov] = {
            "cargas": sum(c.get("proveedor") == prov for c in cargas),
            "carga_s_p50": _mediana([c.get("carga_s") for c in cargas if c.get("proveedor") == prov]),
            "carga_declarada_s_p50": _mediana([r.get("carga_declarada_s") for r in rs]),
            "rondas": len(rs), "rondas_en_verde": sum(1 for r in rs if r.get("ok")),
            "generacion_s_p50": _mediana([r.get("generacion_s") for r in rs]),
            "verificacion_s_p50": _mediana([r.get("verificacion_s") for r in rs]),
            "tokens_s_p50": _mediana([r.get("tokens_s") for r in rs]),
            "tokens_salida_p50": _mediana([r.get("tokens_salida") for r in rs]),
            "cortes_por_longitud": sum(1 for r in rs if r.get("paso_fallido") == "respuesta cortada por longitud"),
            "juez_media": round(statistics.fmean(r["juez_superadas"] / r["juez_total"] for r in con_juez), 3) if con_juez else None,
        }
    bancos: dict[str, Any] = {}
    for clave in sorted({(str(m.get("banco")), str(m.get("proveedor"))) for m in muestras}):
        ms = [m for m in muestras if (str(m.get("banco")), str(m.get("proveedor"))) == clave]
        notas = [m["puntuacion"] for m in ms if isinstance(m.get("puntuacion"), (int, float))]
        bancos[f"{clave[0]} · {clave[1]}"] = {
            "muestras": len(ms), "minutos_p50": _mediana([m.get("minutos") for m in ms]),
            "media": round(statistics.fmean(notas), 3) if notas else None,
            "desviacion": round(statistics.stdev(notas), 3) if len(notas) > 1 else None,
            "sin_entrega": sum(1 for m in ms if m.get("exit") not in (None, 0)),
        }
    return {"activa": activa(), "carpeta": str(carpeta()), "eventos": len(rondas) + len(muestras) + len(cargas),
            "por_proveedor": por, "bancos": bancos}

