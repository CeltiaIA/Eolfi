"""Equivalencia original ↔ reconstrucción con el MISMO guion de observación (Fase 5).

Para cada guion de observación del caso se repite la sesión cambiando solo el objetivo por el candidato, en el
mismo tipo de sandbox, entorno y entradas. Se comparan resultados estructurados —estado, código/señal, stdout,
stderr, procesos hijos, efectos en archivos y registro, respuestas y cookies HTTP, estados de interfaz— y no solo
stdout. Resultado por requisito: ``equivalent``, ``divergent`` o ``not_exercised`` (nunca se oculta lo no
probado detrás de un porcentaje), severidad por aspecto, tolerancias declaradas por el operador y apertura o
cierre automático de incógnitas de equivalencia.
"""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any

from eolfi.core.cases import case_run, file_identity
from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Authority, Confidence, Evidence, Incognita, Status

PROVIDER = "eolfi.equivalence"
VERSION = "1.0.0"
_HIGH = ("estado", "código de salida", "señal/estado", "stdout", "respuesta[*].estado", "respuesta[*].cuerpo",
         "petición[*].bloqueada", "*.estado", "*.url", "*.peticiones", "*.interfaz", "*.ventanas")
_MEDIUM = ("archivos", "registro", "cookies", "respuesta[*].cookies", "respuesta[*].redirecciones",
           "*.almacenamiento", "*.texto visible", "*.accesibilidad", "*.errores", "*.diálogos")


def severity(aspect: str) -> str:
    if any(fnmatch.fnmatchcase(aspect, p) for p in _HIGH):
        return "high"
    if any(fnmatch.fnmatchcase(aspect, p) for p in _MEDIUM):
        return "medium"
    return "low"     # stderr, procesos hijos, consola…


def _question(req: str, title: str, aspect: str) -> str:
    return f"Equivalencia: la reconstrucción diverge del original en {req} ({title}), aspecto «{aspect}»."


def check_equivalence(store: EvidenceStore, case_id: str, candidate: str | Path, *, authorized: bool,
                      tolerances: list[str] | None = None, variables: dict[str, str] | None = None) -> dict[str, Any]:
    """Ejecuta los guiones del caso contra ``candidate`` y los compara con las sesiones originales."""
    if not authorized:
        raise PermissionError("la comprobación EJECUTA el candidato: confirma la autorización (--autorizo)")
    from eolfi.observe import compare_sessions, run_observation
    from eolfi.spec import latest_spec

    tolerances = list(tolerances or [])
    cand = Path(candidate).resolve()
    if not cand.is_file():
        raise ValueError(f"no existe el candidato: {cand}")
    spec = latest_spec(store, case_id)
    if spec is None:
        raise ValueError("el caso no tiene especificación: ejecuta antes eolfi spec build")
    with case_run(store, case_id, "equivalence", {"candidate": str(cand), "tolerances": tolerances},
                  "candidato de reconstrucción indicado por el operador") as run:
        originals: dict[str, dict[str, Any]] = {}
        for eid in spec["sources"]["sessions"]:
            ev = store.get_evidence(eid)
            params = json.loads(ev["params"])
            if "replay_of" in params or params["script_sha256"] in originals:
                continue                      # una sesión original por guion
            originals[params["script_sha256"]] = {"evidence_id": eid, "params": params,
                                                  "session": json.loads(ev["result"]), "subject": ev["subject"]}
        runs, step_status = [], {}
        for o in originals.values():
            script = json.loads(json.dumps(o["params"]["script"]))
            if "target" not in script:
                continue
            script["target"] = {**{k: v for k, v in script["target"].items() if k != "sha256"}, "path": str(cand),
                                "provenance": "reconstrucción candidata"}
            new = run_observation(script, store, authorized=True, variables=variables,
                                  base_dir=o["params"].get("base_dir"))
            cmp = compare_sessions(o["session"], new)
            diffs = []
            for d in cmp["differences"]:
                tolerated = any(fnmatch.fnmatchcase(d["aspect"], t) for t in tolerances)
                diffs.append({**d, "severity": severity(d["aspect"]), "tolerated": tolerated})
            for s in o["session"]["steps"]:
                bad = [d for d in diffs if d["step"] == s["id"] and not d["tolerated"]]
                step_status[(o["evidence_id"], s["id"])] = bad
            runs.append({"original": o["evidence_id"], "candidate_session": new["evidence_id"],
                         "differences": diffs, "context_differences": cmp["context_differences"]})
        requirements = []
        for r in spec["requirements"]:
            exercised = [tuple(x) for x in r.get("source_steps", []) if tuple(x) in step_status]
            if not exercised:
                requirements.append({"id": r["id"], "title": r["title"], "result": "not_exercised"})
                continue
            bad = [d for x in exercised for d in step_status[x]]
            requirements.append({"id": r["id"], "title": r["title"],
                                 "result": "divergent" if bad else "equivalent",
                                 "aspects": sorted({d["aspect"] for d in bad}),
                                 "severity": max((d["severity"] for d in bad), key=["low", "medium", "high"].index,
                                                 default=None)})
        counts = {k: sum(r["result"] == k for r in requirements) for k in ("equivalent", "divergent", "not_exercised")}
        total = len(requirements)
        result = {"candidate": str(cand), "spec_version": spec["spec_version"], "requirements": requirements,
                  "counts": counts, "total_requirements": total,
                  "coverage": {"exercised": total - counts["not_exercised"], "total": total,
                               "not_exercised": [r["id"] for r in requirements if r["result"] == "not_exercised"]},
                  "unobserved_zones": spec["unknowns"]["coverage_gaps"],
                  "equivalent": counts["divergent"] == 0 and counts["not_exercised"] == 0 and total > 0,
                  "tolerances": tolerances, "runs": runs,
                  "limits": "Equivalencia solo sobre los guiones observados y sus entradas; zonas no observadas "
                            "y requisitos no ejercitados quedan fuera y se listan."}
        # Incógnitas de equivalencia: se abren con cada divergencia y se cierran cuando vuelve a coincidir.
        subject_orig = next(iter(originals.values()))["subject"] if originals else None
        opened = closed = 0
        if subject_orig:
            open_ids = {i["incognita_id"] for i in store.list_incognitas(Status.OPEN, subject=subject_orig)}
            for r in requirements:
                if r["result"] == "divergent":
                    for a in r["aspects"]:
                        store.add_incognita(Incognita(subject=subject_orig, severity=r["severity"],
                                                      question=_question(r["id"], r["title"], a)))
                        opened += 1
                elif r["result"] == "equivalent":
                    for i in store.list_incognitas(Status.OPEN, subject=subject_orig):
                        if i["incognita_id"] in open_ids and i["question"].startswith(
                                f"Equivalencia: la reconstrucción diverge del original en {r['id']} "):
                            closed += store.resolve_incognita(i["incognita_id"])
        result.update(incognitas_opened=opened, incognitas_closed=closed)
        sha, info = file_identity(cand)
        eid, _ = store.add_evidence(Evidence(
            subject=sha, provider=PROVIDER, provider_version=VERSION, operation="equivalence_check",
            params={"case_id": case_id, "spec_version": spec["spec_version"], "tolerances": tolerances,
                    "originals": sorted(o["evidence_id"] for o in originals.values())},
            result={k: v for k, v in result.items() if k != "runs"} | {"runs": [
                {k: x[k] for k in ("original", "candidate_session")} | {"differences": x["differences"][:200]}
                for x in runs]},
            authority=Authority.CONTROLLED_REPRO, confidence=Confidence.MEDIUM, limitations=result["limits"],
            links=[x["candidate_session"] for x in runs]))
        if run.active:
            info["metadata"] = {"role": "reconstrucción candidata"}
            run.artifact(sha, **info)
            for o in originals.values():
                run.associate(o["subject"])
            claims = [{"text": f"{counts['equivalent']} requisitos equivalentes, {counts['divergent']} divergentes y "
                               f"{counts['not_exercised']} sin ejercitar de {total}",
                       "status": "observed", "evidence_ids": [eid],
                       "limits": result["limits"]}]
            run.finish(status="done" if result["equivalent"] else "partial", evidence_ids=[eid], claims=claims,
                       tools=[{"name": PROVIDER, "version": VERSION, "status": "ran"}],
                       errors=[f"{r['id']}: {', '.join(r['aspects'])} ({r['severity']})" for r in requirements
                               if r["result"] == "divergent"][:200],
                       result={"counts": counts, "equivalent": result["equivalent"],
                               "not_exercised": result["coverage"]["not_exercised"][:200]})
            result["case_record"] = run.record_id
        result["evidence_id"] = eid
        return result
