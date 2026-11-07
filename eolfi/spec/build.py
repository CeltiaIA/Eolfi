"""Especificación versionada a partir de las evidencias de un caso.

Fuentes:
- **dinámicas**: sesiones de observación (``eolfi observe``) y sus repeticiones;
- **estáticas**: hechos de identidad del artefacto (formato, plataforma, tamaño) derivados de sus evidencias.

Reglas:
- un requisito nace de comportamiento observado: mismas entradas → mismas salidas/efectos. Cada requisito enlaza
  las evidencias de las que sale y su confianza (``high`` si se observó igual en ≥2 ejecuciones, ``medium`` con una);
- si dos observaciones con las mismas entradas discrepan, el requisito queda ``contradicted`` y se abre una
  incógnita; los aspectos que una repetición marcó como no reproducibles quedan ``unstable`` y fuera de lo esperado;
- las conclusiones ``hypothesis`` del caso se listan aparte y nunca se convierten en requisitos ni en pruebas;
- pasos de navegador/escritorio producen una máquina de estados (estado = URL/ventana + huella de la interfaz,
  transición = acción).
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from eolfi.core.cases import CaseStore
from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Incognita
from eolfi.observe.compare import observables

SPEC_FORMAT = 1
REVIEW_DECISIONS = {"accepted", "rejected", "needs_info"}
_DYNAMIC_PROVIDER = "eolfi.observe"


def _h(obj: Any, n: int = 64) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:n]


def _inputs(step: dict[str, Any], target: str | None) -> dict[str, Any]:
    act = step["action"]
    base: dict[str, Any] = {"action": act, "target": target}
    if act in ("run", "desktop"):
        base["argv"] = step.get("argv", [])[1:]      # argv[0] es el intérprete/lanzador
        base["program"] = (step.get("argv") or [""])[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    if act == "run":
        base["stdin"] = step.get("stdin")
        base["env"] = step.get("env_overrides", {})
    elif act in ("write_file", "delete_file"):
        base["path"] = step.get("path")
        base["input"] = step.get("input")
    elif act == "http":
        req = (step.get("traces") or [{}])[0].get("request", {})
        base.update(method=req.get("method"), url=req.get("url"), body=req.get("body"))
    elif act == "browser":
        base["actions"] = [{k: a.get(k) for k in ("id", "do", "selector")} for a in step.get("actions", [])]
    if act == "desktop":
        base["actions"] = [{k: a.get(k) for k in ("id", "do", "target")} for a in step.get("actions", [])]
    return base


def _kind(step: dict[str, Any]) -> str:
    act = step["action"]
    failed = (act in ("run", "desktop") and step.get("exit_code") not in (0, None)) or (
        act == "http" and any(((t.get("response") or {}).get("status") or 0) >= 400 for t in step.get("traces", [])))
    if failed or step.get("status") not in ("ok",):
        return "error"
    return {"http": "interface", "write_file": "input", "delete_file": "input"}.get(act, "use_case")


def _states(step: dict[str, Any]) -> dict[str, Any] | None:
    if step["action"] not in ("browser", "desktop"):
        return None
    states: dict[str, dict[str, Any]] = {}
    transitions = []
    prev = None
    for a in step.get("actions", []):
        if step["action"] == "browser":
            label = a.get("url_after")
            fp = (a.get("visible") or {}).get("text_sha256")
        else:
            label = " | ".join(w.get("title") or "" for w in a.get("windows", []))
            fp = a.get("windows_sha256")
        sid = "S" + _h([label, fp], 10)
        states.setdefault(sid, {"id": sid, "label": label, "fingerprint": fp})
        if prev is not None or a.get("id") != "_inicio":
            transitions.append({"from": prev, "action": a.get("id"), "do": a.get("do"), "to": sid,
                                "status": a.get("status")})
        prev = sid
    return {"states": list(states.values()), "transitions": transitions}


def _persistence(step: dict[str, Any]) -> list[dict[str, Any]]:
    eff = step.get("effects", {})
    out = [{"kind": "file", "path": e["path"], "change": e["change"]} for e in eff.get("files", [])]
    out += [{"kind": "registry", "path": e["path"], "change": e["change"]} for e in eff.get("registry", [])]
    return out


def _sessions(store: EvidenceStore, case: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    sessions, unstable = [], {}
    for ev in case["evidence"]:
        if ev["provider"] != _DYNAMIC_PROVIDER:
            continue
        if ev["operation"] == "observation_session":
            sessions.append({"evidence_id": ev["evidence_id"], "subject": ev["subject"],
                             "session": json.loads(ev["result"])})
        elif ev["operation"] == "observation_replay":
            r = json.loads(ev["result"])
            for d in r.get("non_reproducible", []):
                for eid in (r.get("original"), r.get("replay")):
                    unstable.setdefault(f"{eid}:{d['step']}", set()).add(d["aspect"])
    # Las repeticiones están en otros subjects del mismo caso solo si se asociaron; se buscan también por enlace.
    known = {s["evidence_id"] for s in sessions}
    for ev in case["evidence"]:
        if ev["operation"] == "observation_replay":
            r = json.loads(ev["result"])
            rid = r.get("replay")
            if rid and rid not in known:
                got = store.get_evidence(rid)
                if got:
                    sessions.append({"evidence_id": rid, "subject": got["subject"], "session": json.loads(got["result"])})
                    known.add(rid)
    sessions.sort(key=lambda s: (s["session"].get("started_at") or 0, s["evidence_id"]))
    return sessions, unstable


def build_spec(store: EvidenceStore, case_id: str) -> dict[str, Any]:
    """Construye (sin guardar) la especificación del caso a partir de sus evidencias."""
    cases = CaseStore(store)
    case = cases.get(case_id)
    sessions, unstable = _sessions(store, case)
    groups: dict[str, dict[str, Any]] = {}
    for s in sessions:
        target = (s["session"].get("target") or {}).get("sha256")
        for step in s["session"].get("steps", []):
            inp = _inputs(step, target)
            key = _h(inp)
            g = groups.setdefault(key, {"inputs": inp, "observations": [], "step": step})
            obs = dict(observables(step))
            skip = unstable.get(f"{s['evidence_id']}:{step['id']}", set())
            g["observations"].append({"evidence_id": s["evidence_id"], "step_id": step["id"], "values": obs,
                                      "unstable": sorted(skip), "kind": _kind(step), "states": _states(step),
                                      "persistence": _persistence(step), "duration_ms": step.get("duration_ms")})
    requirements = []
    contradictions = []
    for key, g in groups.items():
        obs = g["observations"]
        unstable_aspects = sorted({a for o in obs for a in o["unstable"]})
        aspects = list(obs[0]["values"].keys())
        expected, differing = {}, []
        for a in aspects:
            if a in unstable_aspects:
                continue
            vals = [o["values"].get(a) for o in obs]
            if all(json.dumps(v, sort_keys=True) == json.dumps(vals[0], sort_keys=True) for v in vals):
                expected[a] = vals[0]
            else:
                differing.append({"aspect": a, "values": [{"evidence_id": o["evidence_id"], "value": o["values"].get(a)}
                                                          for o in obs]})
        rid = "REQ-" + key[:10]
        status = "contradicted" if differing else "observed"
        durations = [o["duration_ms"] for o in obs if isinstance(o["duration_ms"], int)]
        req = {
            "id": rid, "kind": obs[0]["kind"], "title": f"{g['inputs']['action']} «{obs[0]['step_id']}»",
            "status": status, "confidence": "low" if differing else "high" if len(obs) >= 2 else "medium",
            "inputs": g["inputs"], "expected": expected, "unstable_aspects": unstable_aspects,
            "persistence": obs[0]["persistence"], "evidence_ids": sorted({o["evidence_id"] for o in obs}),
            "observations": len(obs),
            "non_functional": {"duration_ms_max": max(durations)} if durations else {},
        }
        if obs[0]["states"]:
            req["state_machine"] = obs[0]["states"]
        if differing:
            req["contradictions"] = differing
            contradictions.append({"requirement": rid, "aspects": [d["aspect"] for d in differing]})
        requirements.append(req)
    requirements.sort(key=lambda r: (r["inputs"]["target"] or "", r["title"], r["id"]))
    artifacts = [{"subject": a["subject"], "identity": a["identity"], "format": a["format"], "size": a["size"],
                  "platform": a["platform"], "version": a["version"], "status": "derived",
                  "evidence_ids": [e["evidence_id"] for e in case["evidence"] if e["subject"] == a["subject"]
                                   and e["provider"] != _DYNAMIC_PROVIDER][:50]}
                 for a in case["artifacts"] if a["identity"] == "content"]
    hypotheses = [{"text": c["text"], "record_id": r["record_id"], "evidence_ids": c.get("evidence_ids", [])}
                  for r in case["records"] for c in (r["payload"].get("claims") or []) if c["status"] == "hypothesis"]
    gaps = []
    for s in sessions:
        for k, v in (s["session"].get("coverage") or {}).items():
            if isinstance(v, dict) and v.get("status") in ("not_available", "partial"):
                gaps.append(f"{k}: {v['status']} ({v.get('reason', '')[:200]})")
    unknowns = {"open_incognitas": [{"incognita_id": i["incognita_id"], "question": i["question"],
                                     "severity": i["severity"]} for i in case["incognitas"] if i["status"] != "resolved"],
                "coverage_gaps": sorted(set(gaps)),
                "unfixed_factors": sorted({f["factor"] for s in sessions for f in s["session"].get("unfixed_factors", [])})}
    body = {"requirements": requirements, "artifacts": artifacts, "contradictions": contradictions,
            "hypotheses": hypotheses, "unknowns": unknowns}
    return {"spec_format": SPEC_FORMAT, "case_id": case_id, "generated_at": time.time(),
            "sources": {"sessions": [s["evidence_id"] for s in sessions]}, "content_sha256": _h(body), **body}


def _spec_records(cases: CaseStore, case_id: str) -> list[dict[str, Any]]:
    return [r for r in cases.get(case_id)["records"] if r["kind"] == "specification" and "spec" in r["payload"]]


def _reviews(cases: CaseStore, case_id: str) -> list[dict[str, Any]]:
    return [r["payload"]["review"] | {"record_id": r["record_id"], "created_at": r["created_at"]}
            for r in cases.get(case_id)["records"] if r["kind"] == "specification" and "review" in r["payload"]]


def latest_spec(store: EvidenceStore, case_id: str, version: int | None = None) -> dict[str, Any] | None:
    recs = _spec_records(CaseStore(store), case_id)
    if not recs:
        return None
    if version is None:
        rec = recs[-1]
    else:
        rec = next((r for r in recs if r["payload"]["spec_version"] == version), None)
        if rec is None:
            raise ValueError(f"no existe la versión {version} de la especificación")
    return rec["payload"]["spec"] | {"spec_version": rec["payload"]["spec_version"], "record_id": rec["record_id"]}


def _apply_reviews(spec: dict[str, Any], reviews: list[dict[str, Any]]) -> None:
    """La última revisión de cada requisito se conserva si lo revisado (huella de lo esperado) no ha cambiado."""
    last: dict[str, dict[str, Any]] = {}
    for rv in reviews:
        last[rv["requirement"]] = rv
    for req in spec["requirements"]:
        rv = last.get(req["id"])
        fp = _h([req["expected"], req["status"]], 16)
        if rv is None:
            req["review"] = {"state": "pending"}
        elif rv["fingerprint"] == fp:
            req["review"] = {"state": rv["decision"], "reviewer": rv["reviewer"], "note": rv["note"],
                             "record_id": rv["record_id"]}
        else:
            req["review"] = {"state": "pending", "note": f"cambió desde la revisión {rv['record_id'][:8]} "
                             f"({rv['decision']}): revisar de nuevo"}


def store_spec(store: EvidenceStore, case_id: str) -> dict[str, Any]:
    """Construye y guarda una versión nueva (si el contenido cambió) como registro «specification» del caso."""
    cases = CaseStore(store)
    spec = build_spec(store, case_id)
    _apply_reviews(spec, _reviews(cases, case_id))
    prev = latest_spec(store, case_id)
    if prev and prev["content_sha256"] == spec["content_sha256"] and \
            [r["review"] for r in prev["requirements"]] == [r["review"] for r in spec["requirements"]]:
        return prev | {"unchanged": True}
    version = (prev["spec_version"] + 1) if prev else 1
    ev_ids = sorted({e for r in spec["requirements"] for e in r["evidence_ids"]})
    claims = []
    for r in spec["requirements"][:5000]:
        claims.append({"text": f"{r['id']} {r['title']}: {len(r['expected'])} aspectos esperados"
                               + (f"; contradicción en {', '.join(c['aspect'] for c in r['contradictions'])}"
                                  if r.get("contradictions") else ""),
                       "status": "observed" if r["status"] == "observed" else "derived",
                       "evidence_ids": r["evidence_ids"],
                       "limits": "comportamiento con estas entradas; otras entradas no están especificadas"})
    for h in spec["hypotheses"][:1000]:
        claims.append({"text": h["text"][:4000], "status": "hypothesis", "evidence_ids": []})
    payload = {"spec": spec, "spec_version": version, "parent": prev["record_id"] if prev else None,
               "evidence_ids": ev_ids, "claims": claims}
    rid = cases.add_record(case_id, "specification", payload)
    subjects = {a["subject"] for a in cases.get(case_id)["artifacts"]}
    for c in spec["contradictions"]:
        req = next(r for r in spec["requirements"] if r["id"] == c["requirement"])
        subj = req["inputs"]["target"] if req["inputs"]["target"] in subjects else None
        subj = subj or next((store.get_evidence(e)["subject"] for e in req["evidence_ids"]), None)
        if subj:
            store.add_incognita(Incognita(subject=subj, severity="medium", evidence_for=req["evidence_ids"],
                                          question=f"Especificación: {c['requirement']} ({req['title']}) da resultados "
                                                   f"distintos con las mismas entradas en {', '.join(c['aspects'])}; "
                                                   f"¿no determinismo, estado externo o entrada no fijada?"))
    return spec | {"spec_version": version, "record_id": rid}


def review_requirement(store: EvidenceStore, case_id: str, requirement_id: str, decision: str, *,
                       reviewer: str, note: str = "") -> dict[str, Any]:
    """Revisión humana trazable: queda como registro del caso ligado a la huella de lo revisado."""
    if decision not in REVIEW_DECISIONS:
        raise ValueError(f"decisión debe ser una de {sorted(REVIEW_DECISIONS)}")
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 200:
        raise ValueError("reviewer obligatorio")
    spec = latest_spec(store, case_id)
    if spec is None:
        raise ValueError("el caso no tiene especificación: ejecuta eolfi spec build")
    req = next((r for r in spec["requirements"] if r["id"] == requirement_id), None)
    if req is None:
        raise ValueError(f"requisito no encontrado: {requirement_id}")
    rv = {"requirement": requirement_id, "decision": decision, "reviewer": reviewer.strip(), "note": note[:4000],
          "spec_version": spec["spec_version"], "fingerprint": _h([req["expected"], req["status"]], 16)}
    rid = CaseStore(store).add_record(case_id, "specification", {"review": rv})
    return rv | {"record_id": rid}


def diff_specs(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    ra = {r["id"]: r for r in a["requirements"]}
    rb = {r["id"]: r for r in b["requirements"]}
    changed = []
    for rid in sorted(set(ra) & set(rb)):
        fields = [k for k in ("status", "confidence", "expected", "unstable_aspects", "persistence", "state_machine",
                              "review") if ra[rid].get(k) != rb[rid].get(k)]
        if fields:
            changed.append({"id": rid, "fields": fields})
    return {"from": a.get("spec_version"), "to": b.get("spec_version"),
            "added": sorted(set(rb) - set(ra)), "removed": sorted(set(ra) - set(rb)), "changed": changed,
            "contradictions_from": len(a["contradictions"]), "contradictions_to": len(b["contradictions"])}


def spec_tests(spec: dict[str, Any]) -> dict[str, Any]:
    """Casos de prueba derivados SOLO de requisitos observados (sin contradicciones ni hipótesis).

    Cada caso fija las entradas observadas y los aspectos esperados estables; los aspectos inestables se omiten."""
    tests, skipped = [], []
    for r in spec["requirements"]:
        if r["status"] != "observed" or r.get("review", {}).get("state") == "rejected":
            skipped.append({"requirement": r["id"], "reason": r.get("review", {}).get("state") == "rejected"
                            and "rechazado en revisión" or "requisito contradicho"})
            continue
        tests.append({"id": "T-" + r["id"][4:], "requirement": r["id"], "origin": "observed",
                      "confidence": r["confidence"], "inputs": r["inputs"], "expect": r["expected"],
                      "ignore": r["unstable_aspects"], "evidence_ids": r["evidence_ids"]})
    return {"spec_version": spec.get("spec_version"), "content_sha256": spec.get("content_sha256"),
            "tests": tests, "skipped": skipped,
            "limits": "Solo cubre las entradas observadas; no hay pruebas para hipótesis ni para entradas no ensayadas."}
