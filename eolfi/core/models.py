"""Modelo de evidencias de Eolfi.

La idea central: un agente que hace ingeniería inversa no debe *afirmar
con seguridad algo que no ha comprobado*. Cada hallazgo es una Evidence
inmutable con procedencia, confianza y límites; cada duda es una
Incognita (pregunta abierta) con estado.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class Authority(str, Enum):
    """De dónde sale la certeza de una evidencia."""
    DISTRIBUTED_ARTIFACT = "distributed_artifact"   # leído del propio binario
    CONTROLLED_REPRO = "controlled_repro"           # reproducido en entorno controlado
    ANALYST_INFERENCE = "analyst_inference"         # inferencia del analista/agente


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Status(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class Evidence:
    """Un hallazgo verificable. evidence_id = sha256 de su proyección semántica."""
    subject: str          # sha256 del artefacto analizado
    provider: str         # herramienta que lo produjo
    provider_version: str
    operation: str        # qué se hizo (p. ej. "detect_format")
    params: dict[str, Any]
    result: Any           # resultado normalizado
    authority: Authority
    confidence: Confidence
    limitations: str = ""
    environment: str = ""
    links: list[str] = field(default_factory=list)  # evidence_ids relacionados
    created_at: float = field(default_factory=time.time)

    @property
    def evidence_id(self) -> str:
        projection = {
            "provider": self.provider,
            "subject": self.subject,
            "operation": self.operation,
            "params": self.params,
            "result": self.result,
        }
        return hashlib.sha256(_canonical(projection).encode("utf-8")).hexdigest()

    def to_row(self) -> dict[str, Any]:
        d = asdict(self)
        d["authority"] = self.authority.value
        d["confidence"] = self.confidence.value
        d["evidence_id"] = self.evidence_id
        d["params"] = _canonical(self.params)
        d["result"] = _canonical(self.result)
        d["links"] = _canonical(self.links)
        return d


@dataclass
class Incognita:
    """Pregunta abierta. No se tapa con suposiciones: se registra y se resuelve."""
    subject: str
    question: str
    status: Status = Status.OPEN
    evidence_for: list[str] = field(default_factory=list)
    evidence_against: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    severity: str = "info"   # info | low | medium | high | critical
    created_at: float = field(default_factory=time.time)

    @property
    def incognita_id(self) -> str:
        key = {"subject": self.subject, "question": self.question}
        return hashlib.sha256(_canonical(key).encode("utf-8")).hexdigest()[:16]

    def to_row(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["incognita_id"] = self.incognita_id
        d["evidence_for"] = _canonical(self.evidence_for)
        d["evidence_against"] = _canonical(self.evidence_against)
        d["depends_on"] = _canonical(self.depends_on)
        return d
