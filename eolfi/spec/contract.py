"""Contrato de implementación: la especificación en una forma que otra persona puede implementar sin el original.

El contrato sale SOLO de la especificación guardada (requisitos, ejemplos literales observados, incógnitas e
hipótesis); no lee el objetivo ni sus fuentes. Cada afirmación lleva su grado:

- ``seguro``: comportamiento observado igual en ≥2 ejecuciones y sin aspectos inestables;
- ``inferido``: una sola observación, aspectos inestables, hipótesis o identidad derivada del artefacto;
- ``desconocido``: contradicciones, incógnitas abiertas, huecos de cobertura, contenidos solo conocidos por huella
  y cualquier entrada no observada.
"""
from __future__ import annotations

import json
from typing import Any

from eolfi.spec.build import certainty

CONTRACT_FORMAT = 1
LEVELS = ("seguro", "inferido", "desconocido")


def build_contract(spec: dict[str, Any]) -> dict[str, Any]:
    """Contrato estructurado (JSON) a partir de una especificación guardada."""
    reqs = []
    for r in spec["requirements"]:
        ex = r.get("examples") or {}
        level = r.get("certainty") or certainty(r)
        unknown = list(ex.get("omitted", []))
        if r.get("contradictions"):
            unknown += [f"contradicción en «{c['aspect']}»: valores distintos con las mismas entradas"
                        for c in r["contradictions"]]
        if r.get("unstable_aspects"):
            unknown += [f"aspecto no reproducible: {a}" for a in r["unstable_aspects"]]
        if not ex:
            unknown.append("especificación anterior sin ejemplos literales: vuelve a ejecutar eolfi spec build")
        reqs.append({"id": r["id"], "title": r["title"], "kind": r["kind"], "certainty": level,
                     "observations": r["observations"], "evidence_ids": r["evidence_ids"],
                     "review": (r.get("review") or {}).get("state", "pending"),
                     "given": {k: v for k, v in ex.items() if k in ("argv", "stdin", "request", "path")},
                     "then": {k: v for k, v in ex.items() if k in ("exit_code", "stdout", "stderr", "response",
                                                                   "files")},
                     "unknown": unknown})
    by_step = {(eid, sid): r["id"] for r in spec["requirements"] for eid, sid in r.get("source_steps", [])}
    sequences = []
    for q in spec.get("sequences", []):
        eid = (q.get("evidence_ids") or [""])[0]
        lvl = "desconocido" if q["status"] != "observed" else "seguro" if q["observations"] >= 2 else "inferido"
        sequences.append({"id": q["id"], "certainty": lvl, "observations": q["observations"],
                          "steps": [{"step": t["step"], "requirement": by_step.get((eid, t["step"]))}
                                    for t in q["machine"]["transitions"]],
                          **({"first_divergence": q["first_divergence"]} if q.get("first_divergence") else {})})
    summary = spec.get("certainty") or {lvl: [x["id"] for x in reqs if x["certainty"] == lvl] for lvl in LEVELS}
    return {"contract_format": CONTRACT_FORMAT, "case_id": spec.get("case_id"),
            "spec_version": spec.get("spec_version"), "spec_sha256": spec.get("content_sha256"),
            "requirements": reqs, "sequences": sequences,
            "sequence_note": "Los pasos de un mismo guion se observaron en este orden y en el mismo directorio de "
                             "trabajo: el estado de archivos de un paso es el punto de partida del siguiente.",
            "summary": {lvl: list(summary.get(lvl, [])) for lvl in LEVELS},
            "hypotheses": [h["text"] for h in spec.get("hypotheses", [])],
            "open_incognitas": [i["question"] for i in spec.get("unknowns", {}).get("open_incognitas", [])],
            "coverage_gaps": list(spec.get("unknowns", {}).get("coverage_gaps", [])),
            "limits": "Solo describe las entradas observadas. Cualquier otra entrada es comportamiento no "
                      "especificado (desconocido). No contiene código del original."}


def _block(value: Any) -> str:
    if value is None:
        return "_(no guardado: desconocido)_"
    if isinstance(value, str):
        return "\n```text\n" + value + ("" if value.endswith("\n") or not value else "\n") + "```"
    return "`" + json.dumps(value, ensure_ascii=False) + "`"


def contract_markdown(contract: dict[str, Any]) -> str:
    """Contrato legible (Markdown) para implementar sin consultar el original."""
    lines = [f"# Contrato de implementación — caso `{contract['case_id']}`", "",
             f"Especificación v{contract['spec_version']} (huella `{(contract['spec_sha256'] or '')[:16]}`).",
             "", contract["limits"], "", "## Grado de cada afirmación", ""]
    for lvl in LEVELS:
        items = contract["summary"][lvl]
        lines.append(f"- **{lvl}** ({len(items)}): " + ("; ".join(items) if items else "ninguno"))
    lines.append("")
    if contract["sequences"]:
        lines += ["## Orden observado", "", contract["sequence_note"], ""]
        for q in contract["sequences"]:
            lines.append(f"- {q['id']} (**{q['certainty']}**, {q['observations']} observaciones): "
                         + " → ".join(f"{x['step']} ({x['requirement'] or '?'})" for x in q["steps"])
                         + (f"; primera divergencia en «{q['first_divergence']['step']}»"
                            if q.get("first_divergence") else ""))
        lines.append("")
    for r in contract["requirements"]:
        lines += [f"## {r['id']} — {r['title']}", "",
                  f"- Grado: **{r['certainty']}** ({r['observations']} observaciones, revisión: {r['review']})",
                  f"- Tipo: {r['kind']}", f"- Evidencias: {', '.join(e[:12] for e in r['evidence_ids'])}", "",
                  "**Dado**", ""]
        for k, v in r["given"].items():
            lines.append(f"- {k}: {_block(v)}")
        lines += ["", "**Entonces**", ""]
        for k, v in r["then"].items():
            if k == "files":
                for f in v:
                    lines.append(f"- archivo `{f['path']}` ({f['change']})"
                                 + (f": {_block(f.get('content'))}" if f["change"] != "deleted" else ""))
            else:
                lines.append(f"- {k}: {_block(v)}")
        if r["unknown"]:
            lines += ["", "**Desconocido**", ""] + [f"- {u}" for u in r["unknown"]]
        lines.append("")
    if contract["hypotheses"]:
        lines += ["## Hipótesis (inferidas, sin pruebas)", ""] + [f"- {h}" for h in contract["hypotheses"]] + [""]
    if contract["open_incognitas"] or contract["coverage_gaps"]:
        lines += ["## Desconocido en general", ""] + [f"- {q}" for q in contract["open_incognitas"]] + [
            f"- cobertura: {g}" for g in contract["coverage_gaps"]] + [""]
    return "\n".join(lines)
