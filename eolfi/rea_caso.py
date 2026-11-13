"""Lo que REA analiza dentro de un caso queda en ese caso de Eolfi (plan REA, punto 6; 13/11/2026).

Cada herramienta compuesta (revisar modelo, explicar binario, reimplementar función, comparar versiones, inventario,
verificar comportamiento) ejecutada con un caso activo, desde el chat o desde `eolfi rea --caso`, registra:
- el objetivo como ARTEFACTO del caso (por su SHA-256 si REA lo dio; si no, por su ruta local);
- el resultado como EVIDENCIA de proveedor «rea» (autoridad: leído del artefacto, o reproducción controlada si se
  ejecutó), con sus límites;
- lo que REA no pudo establecer como INCÓGNITAS del caso (verificaciones «unknown», cuantización que no coincide,
  comprobaciones que no se pudieron hacer). Una incógnita no se tapa con suposiciones: se registra y se resuelve.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from eolfi.core.cases import CaseStore
from eolfi.core.models import Authority, Confidence, Evidence, Incognita

MAX_RESULT_CHARS = 60_000
_SHA = re.compile(r"^[0-9a-f]{64}$")


def rea_version() -> str:
    pkg = Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "rea-agents" / "package.json"
    try:
        return str(json.loads(pkg.read_text(encoding="utf-8")).get("version") or "desconocida")
    except (OSError, ValueError):
        return "desconocida"


def _targets(operation: str, result: dict[str, Any], params: dict[str, Any]) -> list[tuple[str, str]]:
    """(subject, ruta) de cada objetivo: SHA-256 si REA lo dio, si no la ruta local o la orden."""
    def subject(path: str, sha: Any = None) -> str:
        return sha if isinstance(sha, str) and _SHA.fullmatch(sha) else f"local:{Path(path).resolve()}"

    if operation == "comparar_versiones":
        return [(subject(result["original"]["ruta"], result["original"].get("sha256")), result["original"]["ruta"]),
                (subject(result["nueva"]["ruta"], result["nueva"].get("sha256")), result["nueva"]["ruta"])]
    if operation == "verificar_comportamiento":
        out = []
        for side in ("original", "reconstruccion"):
            sc = (result.get("escenario") or {}).get(side) or {}
            cmd = " ".join([sc.get("executable", ""), *sc.get("arguments", [])]).strip()
            out.append((f"cmd:{cmd}", sc.get("executable", "")))
        return out
    path = str(result.get("archivo") or params.get("ruta") or "")
    return [(subject(path, result.get("sha256")), path)]


def _incognitas(operation: str, result: dict[str, Any]) -> list[tuple[str, str]]:
    """(pregunta, gravedad) de lo que REA no pudo establecer."""
    found: list[tuple[str, str]] = []
    for check in result.get("comprobaciones") or []:
        if not check.get("ok"):
            found.append((f"Revisar modelo: falló «{check.get('comprobacion')}» (dominante: {check.get('dominante')}). "
                          "¿El archivo es lo que dice su nombre?", "medium"))
    verification = result.get("verificacion") or {}
    for claim in verification.get("afirmaciones") or []:
        if claim.get("status") == "unknown":
            found.append((f"REA no tiene evidencia suficiente para la afirmación «{claim.get('claim_id')}» "
                          f"({operation}): falta comprobarla por otra vía.", "low"))
    for what, why in (result.get("no_aplica") or {}).items():
        found.append((f"Inventario: no se pudo leer «{what}» ({str(why)[:120]}).", "info"))
    return found


def _compact(value: Any) -> Any:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= MAX_RESULT_CHARS:
        return json.loads(text)
    return {"recortado": True, "caracteres": len(text), "inicio": text[:MAX_RESULT_CHARS]}


def registrar(store: Any, case_id: str, operation: str, params: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Registra en el caso el resultado de una herramienta compuesta de REA. `store` es un EvidenceStore."""
    cases = CaseStore(store)
    version = rea_version()
    targets = _targets(operation, result, params)
    for subject, path in targets:
        p = Path(path) if path else None
        size = p.stat().st_size if p is not None and p.is_file() else None
        cases.add_artifact(case_id, subject, size=size, format=str(result.get("formato") or "desconocido"),
                           provenance=f"REA · {operation} desde Eolfi", path=str(path or ""),
                           tools=[{"name": "rea-agents", "version": version}])
    executed = operation == "verificar_comportamiento"
    ev = Evidence(subject=targets[0][0], provider="rea", provider_version=version, operation=operation,
                  params=_compact(params), result=_compact(result),
                  authority=Authority.CONTROLLED_REPRO if executed else Authority.DISTRIBUTED_ARTIFACT,
                  confidence=Confidence.MEDIUM, limitations=str(result.get("aviso") or result.get("limites") or ""),
                  environment=f"REA {version} vía Eolfi")
    evidence_id, _new = store.add_evidence(ev)
    incognitas = []
    for question, severity in _incognitas(operation, result):
        incognitas.append(store.add_incognita(Incognita(subject=targets[0][0], question=question, severity=severity,
                                                        evidence_for=[evidence_id])))
    store.conn.commit()
    return {"caso": case_id, "artefactos": [s for s, _p in targets], "evidencia": evidence_id, "incognitas": incognitas}
