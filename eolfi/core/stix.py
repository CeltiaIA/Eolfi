"""Exportación a STIX 2.1 (bundle JSON).

Modelo:
- identity: Eolfi (autor de todos los objetos).
- Por objetivo: un SCO (`file` con SHA-256 para binarios, `url` para webs y
  repos remotos, `directory` para carpetas locales) y un `grouping` que reúne
  todo lo dicho sobre él.
- Cada evidencia es un `note` que referencia al SCO; sus datos completos van
  en propiedades personalizadas `x_eolfi_*`.
- Cada incógnita es un `note` con `x_eolfi_status`.
- Técnicas ATT&CK detectadas por capa: `attack-pattern` con referencia MITRE.

Los identificadores son deterministas (UUIDv5), así que exportar dos veces la
misma base produce los mismos ids.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eolfi import __version__
from eolfi.core.evidence import EvidenceStore

NS = uuid.UUID("6f1c4a52-3b0e-4f63-9a4e-6c2e0e0f1a7b")
SCO_NS = uuid.UUID("00abedb4-aa42-466c-9c01-fed23315a9b7")   # namespace oficial STIX para SCO


def _id(kind: str, key: str, sco: bool = False) -> str:
    if sco:
        # STIX 2.1 §2.9: UUIDv5(namespace SCO, JSON canónico de las propiedades de id)
        canon = json.dumps(json.loads(key), sort_keys=True, separators=(",", ":"), ensure_ascii=False)             if key.startswith("{") else key
        return f"{kind}--{uuid.uuid5(SCO_NS, canon)}"
    return f"{kind}--{uuid.uuid5(NS, kind + ':' + key)}"


def _ts(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _label(names: dict[str, Any], subject: str) -> str:
    given = names.get(subject)
    return given[0] if isinstance(given, list) and given and isinstance(given[0], str) else subject


def _sco(subject: str, names: dict[str, list[str]]) -> dict[str, Any]:
    if re.fullmatch(r"[0-9a-f]{64}", subject):
        obj = {"type": "file", "spec_version": "2.1", "id": _id("file", json.dumps({"hashes": {"SHA-256": subject}}), True),
               "hashes": {"SHA-256": subject}}
        given = names.get(subject)
        if isinstance(given, list) and given and isinstance(given[0], str):
            obj["name"] = given[0]
        return obj
    kind, _, rest = subject.partition(":")
    if kind in ("url", "repo") and rest.startswith(("http://", "https://", "git@", "ssh://")):
        return {"type": "url", "spec_version": "2.1", "id": _id("url", json.dumps({"value": rest}), True), "value": rest}
    if kind in ("local", "repo"):
        return {"type": "directory", "spec_version": "2.1", "id": _id("directory", json.dumps({"path": rest}), True),
                "path": rest}
    return {"type": "x-eolfi-subject", "spec_version": "2.1", "id": _id("x-eolfi-subject", subject, True),
            "value": subject}


def build_stix(store: EvidenceStore, names: dict[str, list[str]] | None = None) -> dict[str, Any]:
    names = names or {}
    now = _ts(datetime.now(timezone.utc).timestamp())
    ident = {"type": "identity", "spec_version": "2.1", "id": _id("identity", "eolfi"),
             "created": "2026-01-01T00:00:00.000Z", "modified": "2026-01-01T00:00:00.000Z",
             "name": f"Eolfi {__version__}", "identity_class": "system"}
    objects: list[dict[str, Any]] = [ident]
    per_subject: dict[str, list[str]] = {}
    scos: dict[str, dict[str, Any]] = {}
    patterns: dict[str, dict[str, Any]] = {}

    by_id: dict[str, dict[str, Any]] = {}

    def sco_for(subject: str) -> dict[str, Any]:
        if subject not in scos:
            obj = _sco(subject, names)
            # url:X y repo:X con la misma URL dan el mismo id de SCO: un único objeto en el bundle.
            if obj["id"] not in by_id:
                by_id[obj["id"]] = obj
                objects.append(obj)
            scos[subject] = by_id[obj["id"]]
        return scos[subject]

    for ev in store.list_evidence():
        sco = sco_for(ev["subject"])
        result = json.loads(ev["result"])
        text = json.dumps(result, ensure_ascii=False, sort_keys=True)
        note = {
            "type": "note", "spec_version": "2.1", "id": _id("note", "ev:" + ev["evidence_id"]),
            "created": _ts(ev["created_at"]), "modified": _ts(ev["created_at"]),
            "created_by_ref": ident["id"],
            "abstract": f"{ev['operation']} ({ev['provider']} {ev['provider_version']})",
            "content": text if len(text) <= 4000 else text[:4000] + "…",
            "object_refs": [sco["id"]],
            "confidence": {"high": 85, "medium": 50, "low": 15}.get(ev["confidence"], 0),
            "x_eolfi_evidence_id": ev["evidence_id"],
            "x_eolfi_authority": ev["authority"],
            "x_eolfi_limitations": ev["limitations"],
            "x_eolfi_params": json.loads(ev["params"]),
        }
        objects.append(note)
        per_subject.setdefault(ev["subject"], []).append(note["id"])
        if ev["operation"] == "detect_capabilities":
            attack = result.get("attack", []) if isinstance(result, dict) else []
            for a in attack if isinstance(attack, list) else []:
                if not isinstance(a, str):
                    continue   # paquete importado con tipos inesperados: se ignora, no tumba la exportación
                m = re.search(r"\[(T\d{4}(?:\.\d{3})?)\]", a)
                if not m:
                    continue
                tid = m.group(1)
                if tid not in patterns:
                    patterns[tid] = {
                        "type": "attack-pattern", "spec_version": "2.1", "id": _id("attack-pattern", tid),
                        "created": now, "modified": now, "created_by_ref": ident["id"],
                        "name": a.split(" [")[0].split("::")[-1] or tid,
                        "external_references": [{"source_name": "mitre-attack", "external_id": tid,
                                                  "url": f"https://attack.mitre.org/techniques/{tid.replace('.', '/')}/"}],
                    }
                    objects.append(patterns[tid])
                per_subject[ev["subject"]].append(patterns[tid]["id"])

    for inc in store.list_incognitas():
        sco = sco_for(inc["subject"])
        note = {
            "type": "note", "spec_version": "2.1", "id": _id("note", "inc:" + inc["incognita_id"]),
            "created": _ts(inc["created_at"]), "modified": _ts(inc["created_at"]),
            "created_by_ref": ident["id"],
            "abstract": f"Incógnita ({inc['severity']}, {inc['status']})",
            "content": inc["question"], "object_refs": [sco["id"]],
            "x_eolfi_status": inc["status"], "x_eolfi_severity": inc["severity"],
            "x_eolfi_incognita_id": inc["incognita_id"],
        }
        objects.append(note)
        per_subject.setdefault(inc["subject"], []).append(note["id"])

    for subject, refs in per_subject.items():
        objects.append({
            "type": "grouping", "spec_version": "2.1", "id": _id("grouping", subject),
            "created": now, "modified": now, "created_by_ref": ident["id"],
            "name": f"Análisis Eolfi: {_label(names, subject)[:120]}",
            "context": "unspecified",
            "object_refs": [scos[subject]["id"], *dict.fromkeys(refs)],
        })
    # Id determinista: el mismo contenido produce el mismo bundle.
    digest = json.dumps(sorted(o["id"] for o in objects), separators=(",", ":"))
    return {"type": "bundle", "id": f"bundle--{uuid.uuid5(NS, 'bundle:' + digest)}", "objects": objects}


def export_stix(store: EvidenceStore, out: str | Path, names: dict[str, list[str]] | None = None) -> int:
    doc = build_stix(store, names)
    Path(out).write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return len(doc["objects"])
