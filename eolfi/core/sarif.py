"""Exportación de evidencias e incógnitas a SARIF 2.1.0.

- Un `run` por proveedor (tool.driver = proveedor + versión).
- Cada evidencia es un resultado `informational`; sus datos completos van
  en `properties` (autoridad, confianza, límites, resultado normalizado).
- Las incógnitas van en un run propio de Eolfi: abiertas como `fail` con
  nivel según su gravedad; resueltas como `pass`.
- Los artefactos se identifican por su sha-256. Si se conoce la ruta del
  archivo (parámetro `artifacts`), se añade como URI para que los visores
  (VS Code, GitHub) puedan enlazarlo.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from eolfi import __version__
from eolfi.core.evidence import EvidenceStore
from eolfi.providers.triage import sha256_file

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
_LEVEL = {"critical": "error", "high": "error", "medium": "warning", "low": "note", "info": "note"}
_MAX_MESSAGE = 400


def _artifact_map(paths: Iterable[str | Path]) -> dict[str, str]:
    out = {}
    for p in paths:
        p = Path(p)
        if p.is_file():
            out[sha256_file(p)] = p.resolve().as_uri()
    return out


def _summary(operation: str, result: Any) -> str:
    text = json.dumps(result, ensure_ascii=False, sort_keys=True)
    if len(text) > _MAX_MESSAGE:
        text = text[:_MAX_MESSAGE] + "…"
    return f"{operation}: {text}"


class _Run:
    def __init__(self, name: str, version: str):
        self.name, self.version = name, version
        self.rules: dict[str, dict[str, Any]] = {}
        self._rule_index: dict[str, int] = {}
        self.results: list[dict[str, Any]] = []
        self.artifacts: dict[str, int] = {}
        self.artifact_list: list[dict[str, Any]] = []

    def artifact(self, subject: str, uris: dict[str, str]) -> dict[str, Any]:
        if subject not in self.artifacts:
            entry: dict[str, Any] = {"location": {"uri": uris.get(subject, f"eolfi:subject/{subject}")}}
            if len(subject) == 64 and all(c in "0123456789abcdef" for c in subject):
                entry["hashes"] = {"sha-256": subject}
            self.artifacts[subject] = len(self.artifact_list)
            self.artifact_list.append(entry)
        idx = self.artifacts[subject]
        return {"physicalLocation": {"artifactLocation": {
            "uri": self.artifact_list[idx]["location"]["uri"], "index": idx}}}

    def rule(self, rule_id: str, description: str) -> int:
        if rule_id not in self.rules:
            self.rules[rule_id] = {"id": rule_id, "shortDescription": {"text": description}}
            self._rule_index[rule_id] = len(self._rule_index)
        return self._rule_index[rule_id]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": {"driver": {
                "name": self.name,
                "version": self.version,
                "informationUri": "https://sarifweb.azurewebsites.net/",
                "rules": list(self.rules.values()),
            }},
            "artifacts": self.artifact_list,
            "results": self.results,
            "columnKind": "unicodeCodePoints",
        }


def build_sarif(store: EvidenceStore, artifacts: Iterable[str | Path] = ()) -> dict[str, Any]:
    uris = _artifact_map(artifacts)
    runs: dict[tuple[str, str], _Run] = {}

    for ev in store.list_evidence():
        key = (ev["provider"], ev["provider_version"])
        run = runs.setdefault(key, _Run(*key))
        result = json.loads(ev["result"])
        idx = run.rule(ev["operation"], f"Evidencia '{ev['operation']}' de {ev['provider']}")
        run.results.append({
            "ruleId": ev["operation"],
            "ruleIndex": idx,
            "kind": "informational",
            "level": "none",
            "message": {"text": _summary(ev["operation"], result)},
            "locations": [run.artifact(ev["subject"], uris)],
            "partialFingerprints": {"eolfiEvidenceId/v1": ev["evidence_id"]},
            "properties": {
                "authority": ev["authority"],
                "confidence": ev["confidence"],
                "limitations": ev["limitations"],
                "environment": ev["environment"],
                "params": json.loads(ev["params"]),
                "result": result,
            },
        })

    inc_run = _Run("eolfi", __version__)
    for inc in store.list_incognitas():
        open_ = inc["status"] != "resolved"
        idx = inc_run.rule("incognita", "Pregunta abierta: no se concluye sin evidencia")
        inc_run.results.append({
            "ruleId": "incognita",
            "ruleIndex": idx,
            "kind": "fail" if open_ else "pass",
            "level": _LEVEL.get(inc["severity"] or "info", "note") if open_ else "none",
            "message": {"text": inc["question"]},
            "locations": [inc_run.artifact(inc["subject"], uris)],
            "partialFingerprints": {"eolfiIncognitaId/v1": inc["incognita_id"]},
            "properties": {
                "status": inc["status"],
                "severity": inc["severity"],
                "evidence_for": json.loads(inc["evidence_for"] or "[]"),
                "evidence_against": json.loads(inc["evidence_against"] or "[]"),
            },
        })

    all_runs = [r.to_dict() for r in runs.values()]
    if inc_run.results:
        all_runs.append(inc_run.to_dict())
    return {"$schema": SARIF_SCHEMA, "version": "2.1.0", "runs": all_runs}


def export_sarif(store: EvidenceStore, out_path: str | Path, artifacts: Iterable[str | Path] = ()) -> int:
    doc = build_sarif(store, artifacts)
    Path(out_path).write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return sum(len(r["results"]) for r in doc["runs"])
