"""Automejora recursiva (RSI) de Eolfi con REA, acotada y verificable (PLAN_REA.md, punto 12).

El ciclo: OBSERVAR resultados reales (generador, REA, juez funcional) → SÍNTOMAS → PROPONER un cambio en una
superficie declarada → EVALUAR la propuesta contra la línea base con un banco de pruebas repetido → el titular
APRUEBA (o rechaza) → se APLICA con copia previa y se puede REVERTIR.

Es recursivo en dos niveles, siempre con registro:
- el banco crece: cada fallo nuevo observado queda como caso de regresión (``casos.jsonl``);
- el propio mejorador se ajusta: una regla cuyas propuestas se rechazan sin ninguna adoptada pide más repeticiones
  antes de volver a proponer (umbral acotado), y lo deja escrito como evento ``meta``.

Límites que no se pueden mejorar a sí mismos (invariantes):
- solo se cambian las SUPERFICIES de este módulo, con su validación y rango; nada de código, autorizaciones de REA,
  rutas permitidas, AGENTS.md ni el juez o el banco que evalúan;
- ninguna propuesta se aplica sin evaluación aprobada y sin decisión del titular;
- todo queda en un registro encadenado por SHA-256 (``verificar_registro``), y ``EOLFI_RSI=0`` lo apaga.
"""
from __future__ import annotations

import hashlib
import inspect
import itertools
import json
import os
import random
import re
import statistics
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "eolfi-rsi/v1"
MARGEN_DEFECTO = 0.05
ALFA = 0.05
# Con la prueba exacta de signos el p mínimo es 1/2^n: con 4 pares o menos (≥ 0,0625) nunca se aprobaría nada.
MUESTRAS_MINIMAS = 5
REMUESTREOS = 10000
UMBRAL_INICIAL = 2
UMBRAL_MAXIMO = 10


class RSIError(ValueError):
    pass


def activo() -> bool:
    return os.environ.get("EOLFI_RSI", "1").strip() not in ("0", "false", "no")


def rsi_dir() -> Path:
    return Path(os.environ.get("EOLFI_RSI_DIR") or Path.home() / ".eolfi" / "rsi")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ── Registro encadenado ─────────────────────────────────────────────────────────────────────────────────────────

def _registro() -> Path:
    return rsi_dir() / "registro.jsonl"


def eventos(tipo: str | None = None) -> list[dict[str, Any]]:
    try:
        lines = _registro().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = [json.loads(line) for line in lines if line.strip()]
    return [e for e in out if tipo is None or e["tipo"] == tipo]


def _anotar(tipo: str, datos: dict[str, Any]) -> dict[str, Any]:
    previos = eventos()
    prev = previos[-1]["sha256"] if previos else "0" * 64
    evento = {"schema": SCHEMA, "seq": len(previos) + 1, "fecha": _now(), "tipo": tipo, "datos": datos, "prev": prev}
    evento["sha256"] = hashlib.sha256(_canon(evento).encode("utf-8")).hexdigest()
    _registro().parent.mkdir(parents=True, exist_ok=True)
    with _registro().open("a", encoding="utf-8") as fh:
        fh.write(_canon(evento) + "\n")
    return evento


def verificar_registro() -> dict[str, Any]:
    """Recalcula la cadena: cualquier evento editado, borrado o reordenado rompe la verificación."""
    prev = "0" * 64
    for i, e in enumerate(eventos(), 1):
        body = {k: v for k, v in e.items() if k != "sha256"}
        if e.get("seq") != i or e.get("prev") != prev or hashlib.sha256(_canon(body).encode("utf-8")).hexdigest() != e.get("sha256"):
            return {"ok": False, "roto_en": i, "eventos": i - 1}
        prev = e["sha256"]
    return {"ok": True, "eventos": len(eventos())}


# ── Superficies: lo único que el RSI puede cambiar ──────────────────────────────────────────────────────────────

def _ajustes_file() -> Path:
    return rsi_dir() / "ajustes.json"


AJUSTES_DEFECTO: dict[str, Any] = {"rea.timeout": 900}


def ajuste(nombre: str) -> Any:
    """Ajuste propio del RSI (p. ej. el plazo de REA en la CLI), con su valor por defecto."""
    return _read_json(_ajustes_file(), {}).get(nombre, AJUSTES_DEFECTO[nombre])


def _rango(lo: int, hi: int) -> Callable[[Any], int]:
    def check(v: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise RSIError(f"valor fuera de rango [{lo}, {hi}]: {v!r}")
        return v
    return check


_LECCION = re.compile(r"eolas_v2\.leccion\.(\w+)\.(\w+)")


def _leer(superficie: str) -> Any:
    from eolfi import eolas_v2

    if superficie == "rea.timeout":
        return ajuste("rea.timeout")
    if superficie == "eolas_v2.max_tokens":
        return eolas_v2.load_config()["max_tokens"]
    m = re.fullmatch(r"eolas_v2\.perfil\.(\w+)\.(ctx|gpu_layers)", superficie)
    if m:
        return eolas_v2.load_config()["profiles"][m[1]][m[2]]
    m = _LECCION.fullmatch(superficie)
    if m:
        return bool(eolas_v2._read_lessons().get(m[1], {}).get(m[2], {}).get("activa", False))
    raise RSIError(f"superficie no permitida: {superficie}")


def _escribir(superficie: str, valor: Any) -> None:
    from eolfi import eolas_v2

    valor = validar(superficie, valor)
    if superficie == "rea.timeout":
        data = _read_json(_ajustes_file(), {})
        data["rea.timeout"] = valor
        _write_json(_ajustes_file(), data)
        return
    m = _LECCION.fullmatch(superficie)
    if m:
        try:
            eolas_v2.set_lesson_active(m[1], m[2], valor)
        except ValueError as exc:
            raise RSIError(str(exc)) from exc
        return
    path = eolas_v2.config_file()
    user = _read_json(path, {})
    if superficie == "eolas_v2.max_tokens":
        user["max_tokens"] = valor
    else:
        _, _, perfil, campo = superficie.split(".")
        user.setdefault("profiles", {}).setdefault(perfil, {})[campo] = valor
    _write_json(path, user)


def validar(superficie: str, valor: Any) -> Any:
    from eolfi import eolas_v2

    if superficie == "rea.timeout":
        return _rango(60, 7200)(valor)
    if superficie == "eolas_v2.max_tokens":
        return _rango(1024, 32768)(valor)
    m = re.fullmatch(r"eolas_v2\.perfil\.(\w+)\.(ctx|gpu_layers)", superficie)
    if m and m[1] in eolas_v2.DEFAULT_PROFILES:
        return _rango(2048, 131072)(valor) if m[2] == "ctx" else _rango(0, 999)(valor)
    m = _LECCION.fullmatch(superficie)
    if m and m[2] in eolas_v2.LESSON_CATEGORIES:
        if not isinstance(valor, bool):
            raise RSIError(f"una lección se activa o desactiva (true/false): {valor!r}")
        return valor
    raise RSIError(f"superficie no permitida: {superficie}")


# ── Observar y síntomas ─────────────────────────────────────────────────────────────────────────────────────────

SINTOMAS: dict[str, str] = {
    "salida_cortada": r"se cort[óo] por longitud|Unterminated string|JSON inv[áa]lido en la respuesta",
    "rea_tiempo_agotado": r"REA no respondi[óo] a .* en \d+(\.\d+)? s",
    "js_sintaxis": r"sintaxis JS del sitio",
    "plazo_local": r"no termin[óo] en \d+ s",
    "leccion_inactiva": r"lecci[óo]n inactiva",
}


def sintomas(texto: str) -> list[str]:
    return [name for name, pattern in SINTOMAS.items() if re.search(pattern, texto or "", re.IGNORECASE)]


def observar(fuente: str, operacion: str, resultado: Any, *, contexto: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Anota un resultado real. Guarda solo síntomas, recuentos y huellas: nunca el código ni el contenido analizado
    (lo que devuelve REA es del objetivo y no se reutiliza). Un fallo nuevo pasa al banco como caso de regresión."""
    if not activo():
        return None
    texto = resultado if isinstance(resultado, str) else _canon(resultado)
    found = sintomas(texto)
    ok = bool(resultado.get("ok", not found)) if isinstance(resultado, dict) else not found
    huella = hashlib.sha256(f"{fuente}|{operacion}|{','.join(found)}".encode()).hexdigest()[:16]
    datos = {"fuente": fuente, "operacion": operacion, "ok": ok, "sintomas": found, "huella": huella,
             "contexto": {k: v for k, v in (contexto or {}).items() if isinstance(v, (str, int, float, bool))}}
    evento = _anotar("observacion", datos)
    if found and huella not in {c["huella"] for c in casos()}:
        with (rsi_dir() / "casos.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(_canon({"huella": huella, "fuente": fuente, "operacion": operacion, "sintomas": found,
                             "desde": evento["fecha"], "contexto": datos["contexto"]}) + "\n")
    return evento


def casos() -> list[dict[str, Any]]:
    try:
        return [json.loads(line) for line in (rsi_dir() / "casos.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return []


# ── Reglas: síntoma → propuesta ─────────────────────────────────────────────────────────────────────────────────

def _doblar(superficie: str, tope: int) -> Callable[[dict[str, Any]], tuple[str, Any] | None]:
    def propose(ctx: dict[str, Any]) -> tuple[str, Any] | None:
        actual = _leer(superficie)
        nuevo = min(int(actual) * 2, tope)
        return (superficie, nuevo) if nuevo > actual else None
    return propose


def _reactivar_leccion(ctx: dict[str, Any]) -> tuple[str, Any] | None:
    perfil, categoria = ctx.get("perfil"), ctx.get("categoria")
    if not perfil or not categoria:
        return None
    superficie = f"eolas_v2.leccion.{perfil}.{categoria}"
    return None if _leer(superficie) else (superficie, True)


REGLAS: dict[str, dict[str, Any]] = {
    "salida_cortada_v2": {"sintoma": "salida_cortada", "fuente": "eolas-v2", "motivo":
                          "Las respuestas de Eolas V2 se cortan por longitud: más tokens de salida.",
                          "proponer": _doblar("eolas_v2.max_tokens", 32768)},
    "rea_plazo": {"sintoma": "rea_tiempo_agotado", "fuente": "rea", "motivo":
                  "REA agota el plazo de la CLI: más tiempo por petición.",
                  "proponer": _doblar("rea.timeout", 7200)},
    # La lección la desactivó el titular y el motor sigue fallando por esa misma causa: volver a activarla.
    "reactivar_leccion": {"sintoma": "leccion_inactiva", "fuente": "eolas-v2", "motivo":
                          "Eolas V2 repite fallos de una categoría cuya lección está desactivada: reactivarla.",
                          "proponer": _reactivar_leccion},
}


def _meta() -> dict[str, Any]:
    return _read_json(rsi_dir() / "meta.json", {})


def umbral(regla: str) -> int:
    return int(_meta().get(regla, {}).get("umbral", UMBRAL_INICIAL))


def propuestas(estado: str | None = None) -> list[dict[str, Any]]:
    """Estado actual de cada propuesta, reconstruido del registro."""
    by_id: dict[str, dict[str, Any]] = {}
    for e in eventos():
        d = e["datos"]
        if e["tipo"] == "propuesta":
            by_id[d["id"]] = {**d, "estado": "pendiente", "fecha": e["fecha"]}
        elif e["tipo"] in ("evaluacion", "decision", "aplicacion", "reversion") and d.get("id") in by_id:
            p = by_id[d["id"]]
            if e["tipo"] == "evaluacion":
                p["evaluacion"] = d
                p["estado"] = "evaluada" if d["aprobada"] else "suspendida"
            elif e["tipo"] == "decision":
                p["estado"] = "rechazada" if d["decision"] == "rechazar" else "aprobada"
            elif e["tipo"] == "aplicacion":
                p["estado"], p["anterior"] = "aplicada", d["anterior"]
            else:
                p["estado"] = "revertida"
    out = list(by_id.values())
    return [p for p in out if estado is None or p["estado"] == estado]


def proponer() -> list[dict[str, Any]]:
    """Recorre las observaciones y propone un cambio por regla cuando su síntoma se repite lo bastante."""
    if not activo():
        return []
    abiertas = {(p["regla"]) for p in propuestas() if p["estado"] in ("pendiente", "evaluada", "aprobada")}
    obs = eventos("observacion")
    nuevas = []
    for nombre, regla in REGLAS.items():
        if nombre in abiertas:
            continue
        hechos = [e for e in obs if regla["sintoma"] in e["datos"]["sintomas"]
                  and regla["fuente"] in (e["datos"]["fuente"], e["datos"]["contexto"].get("proveedor"))]
        ultima = max((p["fecha"] for p in propuestas() if p["regla"] == nombre), default="")
        hechos = [e for e in hechos if e["fecha"] > ultima]
        if len(hechos) < umbral(nombre):
            continue
        cambio = regla["proponer"](hechos[-1]["datos"]["contexto"])
        if not cambio:
            continue
        superficie, valor = cambio
        pid = hashlib.sha256(f"{nombre}|{superficie}|{valor}|{len(eventos())}".encode()).hexdigest()[:12]
        datos = {"id": pid, "regla": nombre, "superficie": superficie, "actual": _leer(superficie), "propuesto": valor,
                 "motivo": regla["motivo"], "observaciones": [e["seq"] for e in hechos]}
        _anotar("propuesta", datos)
        nuevas.append(datos)
    return nuevas


def _propuesta(pid: str) -> dict[str, Any]:
    for p in propuestas():
        if p["id"] == pid:
            return p
    raise RSIError(f"propuesta desconocida: {pid}")


# ── Evaluar, decidir, aplicar, revertir ─────────────────────────────────────────────────────────────────────────

Banco = Callable[..., float]
"""Un banco devuelve una puntuación entre 0 y 1. Puede aceptar un argumento, la semilla del par (0, 1, 2…), que
recibe igual la línea base y la candidata del mismo par."""


def _p_signos(difs: Sequence[float], rng: random.Random) -> float:
    """Valor p unilateral de la prueba de permutación de signos sobre diferencias pareadas (H0: la candidata no
    mejora). Exacta hasta 16 pares; con más, Monte Carlo con 20 000 permutaciones."""
    obs = sum(difs)
    absd = [abs(d) for d in difs]
    if len(difs) <= 16:
        total = cuenta = 0
        for signos in itertools.product((1, -1), repeat=len(difs)):
            total += 1
            cuenta += sum(s * a for s, a in zip(signos, absd)) >= obs - 1e-12
        return cuenta / total
    n = 20000
    cuenta = sum(sum(a if rng.random() < 0.5 else -a for a in absd) >= obs - 1e-12 for _ in range(n))
    return (cuenta + 1) / (n + 1)


def _ic_bootstrap(difs: Sequence[float], rng: random.Random, remuestreos: int) -> tuple[float, float]:
    """Intervalo al 95 % (percentiles) de la mejora media por bootstrap de los pares."""
    if remuestreos <= 0:
        m = statistics.fmean(difs)
        return m, m
    k = len(difs)
    medias = sorted(sum(rng.choices(difs, k=k)) / k for _ in range(remuestreos))
    return medias[int(0.025 * (remuestreos - 1))], medias[int(0.975 * (remuestreos - 1))]


def comparar(base: Sequence[float], cand: Sequence[float], *, margen: float = MARGEN_DEFECTO, alfa: float = ALFA,
             semilla: str = "rsi", remuestreos: int = REMUESTREOS) -> dict[str, Any]:
    """Decisión estadística sobre pares (base[i], cand[i]). Se aprueba solo si las tres se cumplen: p < ``alfa``
    (prueba exacta de signos), límite inferior del intervalo al 95 % > 0 y mejora media ≥ ``margen``. Determinista
    para la misma ``semilla``."""
    if len(base) != len(cand) or not base:
        raise RSIError("hacen falta pares de muestras")
    rng = random.Random(semilla)
    difs = [c - b for b, c in zip(base, cand)]
    mejora = statistics.fmean(difs)
    p = _p_signos(difs, rng)
    lo, hi = _ic_bootstrap(difs, rng, remuestreos)
    return {"pares": len(difs), "mejora_media": round(mejora, 4), "ic95": [round(lo, 4), round(hi, 4)],
            "p_valor": round(p, 4), "alfa": alfa, "margen": margen,
            "aprobada": p < alfa and lo > 0 and mejora >= margen}


def _llamar(banco: Banco, semilla: int) -> float:
    try:
        con_semilla = len(inspect.signature(banco).parameters) >= 1
    except (TypeError, ValueError):
        con_semilla = False
    s = float(banco(semilla) if con_semilla else banco())
    if not 0.0 <= s <= 1.0:
        raise RSIError(f"el banco debe puntuar entre 0 y 1: {s}")
    return s


def evaluar(pid: str, banco: Banco, *, muestras: int = MUESTRAS_MINIMAS, margen: float = MARGEN_DEFECTO,
            alfa: float = ALFA) -> dict[str, Any]:
    """Línea base y candidata con el MISMO banco, en ``muestras`` pares ALTERNADOS (base, candidata) con la misma
    semilla en cada par, para que la deriva (temperatura de la GPU, cachés) afecte igual a las dos. La candidata se
    aplica solo durante sus muestras y el valor anterior se restaura siempre. Decide ``comparar``."""
    p = _propuesta(pid)
    if p["estado"] != "pendiente":
        raise RSIError(f"la propuesta {pid} está {p['estado']}")
    if muestras < MUESTRAS_MINIMAS:
        raise RSIError(f"hacen falta al menos {MUESTRAS_MINIMAS} muestras (con menos, la prueba nunca aprueba)")
    anterior = _leer(p["superficie"])
    base: list[float] = []
    cand: list[float] = []
    try:
        for i in range(muestras):
            base.append(_llamar(banco, i))
            _escribir(p["superficie"], p["propuesto"])
            try:
                cand.append(_llamar(banco, i))
            finally:
                _escribir(p["superficie"], anterior)
    finally:
        if _leer(p["superficie"]) != anterior:
            _escribir(p["superficie"], anterior)
    est = comparar(base, cand, margen=margen, alfa=alfa, semilla=f"rsi:{pid}")
    datos = {"id": pid, "base": base, "candidata": cand, "media_base": round(statistics.fmean(base), 4),
             "media_candidata": round(statistics.fmean(cand), 4), **est}
    _anotar("evaluacion", datos)
    return datos


def prueba_aa(banco: Banco, *, muestras: int = MUESTRAS_MINIMAS, margen: float = MARGEN_DEFECTO,
              alfa: float = ALFA) -> dict[str, Any]:
    """Prueba A/A del evaluador con el banco real: los dos lados con la MISMA configuración. Si ``comparar``
    aprueba, es un falso positivo y queda en el registro. No cambia ninguna superficie."""
    if muestras < MUESTRAS_MINIMAS:
        raise RSIError(f"hacen falta al menos {MUESTRAS_MINIMAS} muestras")
    a, b = [], []
    for i in range(muestras):
        a.append(_llamar(banco, i))
        b.append(_llamar(banco, i))
    est = comparar(a, b, margen=margen, alfa=alfa, semilla="rsi:aa")
    datos = {"a": a, "b": b, **est, "falso_positivo": est["aprobada"]}
    _anotar("aa", datos)
    return datos


def calibrar_aa(*, desviacion: float, media: float = 0.5, muestras: int = MUESTRAS_MINIMAS,
                repeticiones: int = 400, margen: float = MARGEN_DEFECTO, alfa: float = ALFA,
                semilla: int = 1, remuestreos: int = 1000) -> dict[str, Any]:
    """A/A simulada: puntuaciones normales recortadas a [0, 1], sin diferencia real entre lados. Devuelve la tasa
    de falsos positivos de ``comparar`` y, para comparar, la de la regla anterior (media + margen y peor muestra)."""
    rng = random.Random(semilla)

    def muestra() -> float:
        return min(1.0, max(0.0, rng.gauss(media, desviacion)))
    fp = fp_antes = 0
    for r in range(repeticiones):
        a = [muestra() for _ in range(muestras)]
        b = [muestra() for _ in range(muestras)]
        fp += comparar(a, b, margen=margen, alfa=alfa, semilla=f"aa:{r}", remuestreos=remuestreos)["aprobada"]
        fp_antes += statistics.fmean(b) >= statistics.fmean(a) + margen and min(b) >= min(a)
    return {"repeticiones": repeticiones, "muestras": muestras, "desviacion": desviacion,
            "falsos_positivos": fp / repeticiones, "falsos_positivos_regla_anterior": fp_antes / repeticiones}


def decidir(pid: str, decision: str, *, por: str) -> dict[str, Any]:
    """El titular aprueba (y se aplica) o rechaza. Solo se aprueba lo que pasó la evaluación."""
    if decision not in ("aprobar", "rechazar"):
        raise RSIError("decisión: aprobar o rechazar")
    if not por.strip():
        raise RSIError("falta quién decide")
    p = _propuesta(pid)
    if decision == "aprobar" and p["estado"] != "evaluada":
        raise RSIError(f"solo se aprueba una propuesta evaluada con éxito (está {p['estado']})")
    if p["estado"] in ("aplicada", "revertida", "rechazada"):
        raise RSIError(f"la propuesta {pid} ya está {p['estado']}")
    _anotar("decision", {"id": pid, "decision": decision, "por": por})
    if decision == "rechazar":
        _ajustar_meta(p["regla"], adoptada=False)
        return {"id": pid, "estado": "rechazada"}
    anterior = _leer(p["superficie"])
    _escribir(p["superficie"], p["propuesto"])
    _anotar("aplicacion", {"id": pid, "superficie": p["superficie"], "anterior": anterior, "nuevo": p["propuesto"]})
    _ajustar_meta(p["regla"], adoptada=True)
    return {"id": pid, "estado": "aplicada", "superficie": p["superficie"], "anterior": anterior, "nuevo": p["propuesto"]}


def revertir(pid: str, *, por: str) -> dict[str, Any]:
    p = _propuesta(pid)
    if p["estado"] != "aplicada":
        raise RSIError(f"solo se revierte una propuesta aplicada (está {p['estado']})")
    _escribir(p["superficie"], p["anterior"])
    _anotar("reversion", {"id": pid, "superficie": p["superficie"], "restaurado": p["anterior"], "por": por})
    _ajustar_meta(p["regla"], adoptada=False)
    return {"id": pid, "estado": "revertida", "superficie": p["superficie"], "restaurado": p["anterior"]}


def _ajustar_meta(regla: str, *, adoptada: bool) -> None:
    """Segundo nivel: la regla aprende de sus resultados. Tres rechazos o reversiones sin ninguna adopción suben su
    umbral en uno (hasta UMBRAL_MAXIMO); una adopción lo devuelve al inicial."""
    meta = _meta()
    m = meta.setdefault(regla, {"umbral": UMBRAL_INICIAL, "adoptadas": 0, "rechazadas": 0})
    antes = m["umbral"]
    if adoptada:
        m["adoptadas"] += 1
        m["umbral"] = UMBRAL_INICIAL
    else:
        m["rechazadas"] += 1
        if m["adoptadas"] == 0 and m["rechazadas"] % 3 == 0:
            m["umbral"] = min(m["umbral"] + 1, UMBRAL_MAXIMO)
    _write_json(rsi_dir() / "meta.json", meta)
    if m["umbral"] != antes:
        _anotar("meta", {"regla": regla, "umbral_antes": antes, "umbral": m["umbral"],
                         "adoptadas": m["adoptadas"], "rechazadas": m["rechazadas"]})


def estado() -> dict[str, Any]:
    obs = eventos("observacion")
    return {"activo": activo(), "carpeta": str(rsi_dir()), "registro": verificar_registro(),
            "observaciones": len(obs), "con_sintomas": sum(1 for e in obs if e["datos"]["sintomas"]),
            "casos_de_regresion": len(casos()), "propuestas": propuestas(),
            "reglas": {n: {"sintoma": r["sintoma"], "umbral": umbral(n)} for n, r in REGLAS.items()}}
