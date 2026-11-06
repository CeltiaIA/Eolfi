"""Comparación de sesiones de observación y repetición desde el guion.

La comparación separa tres cosas:
- **hechos**: diferencias observables paso a paso (salidas, códigos, efectos, trazas), con el primer cambio
  observable en el orden del guion;
- **contexto**: qué difiere entre las dos ejecuciones (objetivo, intérprete, SO, entorno, variables, navegador);
- **atribución**: siempre «hypothesis»; que el contexto difiera no demuestra que esa diferencia cause el cambio.
"""
from __future__ import annotations

import difflib
import json
import os
from pathlib import Path
from typing import Any

from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Authority, Confidence, Evidence
from eolfi.observe import session as obs

COMPARE_OPERATION = "observation_comparison"
REPLAY_OPERATION = "observation_replay"


def _short(v: Any, limit: int = 300) -> Any:
    raw = json.dumps(v, ensure_ascii=False, sort_keys=True)
    return v if len(raw) <= limit else raw[:limit] + "…"


def _out(o: dict[str, Any] | None) -> str | None:
    return None if not o else o.get("sha256_normalized") or o.get("sha256")


def _file_effects(effects: list[dict[str, Any]]) -> list[list[Any]]:
    out = []
    for e in effects:
        after = e.get("after") or {}
        sha = after.get("sha256_normalized") or after.get("sha256") if isinstance(after, dict) else after
        out.append([e["path"], e["change"], sha])
    return out


def _children(step: dict[str, Any]) -> list[list[Any]]:
    procs = (step.get("children") or {}).get("processes", [])
    names = [[p["depth"], p["name"].lower() if os.name == "nt" else p["name"]] for p in procs]
    return sorted(names)


def observables(step: dict[str, Any]) -> list[tuple[str, Any]]:
    """Aspectos comparables de un paso, en orden estable. Excluye PID, tiempos y rutas del sandbox."""
    obs_: list[tuple[str, Any]] = [("estado", step.get("status"))]
    act = step["action"]
    if act == "run":
        obs_ += [("código de salida", step.get("exit_code")), ("señal/estado", step.get("exit_status")),
                 ("stdout", _out(step.get("stdout"))), ("stderr", _out(step.get("stderr")))]
        if "children" in step:
            obs_.append(("procesos hijos", _children(step)))
    elif act == "http":
        for i, t in enumerate(step.get("traces", [])):
            r = t.get("response") or {}
            obs_ += [(f"respuesta[{i}].estado", r.get("status")), (f"respuesta[{i}].cuerpo", _out(r.get("body"))),
                     (f"respuesta[{i}].cookies", r.get("set_cookie_names")),
                     (f"respuesta[{i}].redirecciones", t.get("redirects")), (f"petición[{i}].bloqueada", t.get("blocked"))]
        obs_.append(("cookies", [[c["domain"], c["path"], c["name"]] for c in step.get("storage", {}).get("cookies", [])]))
    elif act == "browser":
        for a in step.get("actions", []):
            p = a.get("id", "?")
            st = a.get("storage") or {}
            reqs = sorted([[r.get("method"), r.get("url"), r.get("status"), r.get("failure"), r.get("blocked")]
                           for r in a.get("requests", [])], key=lambda x: json.dumps(x))
            obs_ += [(f"{p}.estado", a.get("status")), (f"{p}.url", a.get("url_after")),
                     (f"{p}.texto visible", (a.get("visible") or {}).get("text_sha256")),
                     (f"{p}.accesibilidad", (a.get("aria") or {}).get("sha256")),
                     (f"{p}.peticiones", reqs),
                     (f"{p}.almacenamiento", {"local": st.get("localStorage"), "session": st.get("sessionStorage"),
                                              "cookies": [[c.get("domain"), c.get("name")] for c in st.get("cookies", [])]}),
                     (f"{p}.consola", a.get("console")), (f"{p}.errores", a.get("page_errors")),
                     (f"{p}.diálogos", a.get("dialogs"))]
    elif act == "desktop":
        obs_ += [("código de salida", step.get("exit_code")), ("stdout", _out(step.get("stdout"))),
                 ("stderr", _out(step.get("stderr")))]
        for a in step.get("actions", []):
            p = a.get("id", "?")
            obs_ += [(f"{p}.estado", a.get("status")),
                     (f"{p}.ventanas", [w.get("title") for w in a.get("windows", [])]),
                     (f"{p}.interfaz", a.get("windows_sha256"))]
    effects = step.get("effects", {})
    obs_.append(("archivos", _file_effects(effects.get("files", []))))
    if "registry" in effects:
        obs_.append(("registro", [[e["path"], e["change"], e.get("after")] for e in effects["registry"]]))
    return obs_


def _detail(aspect: str, sa: dict[str, Any], sb: dict[str, Any]) -> list[str] | None:
    if aspect in ("stdout", "stderr"):
        pa, pb = (sa.get(aspect) or {}).get("preview", ""), (sb.get(aspect) or {}).get("preview", "")
        return list(difflib.unified_diff(pa.splitlines(), pb.splitlines(), "a", "b", lineterm="", n=1))[:20]
    if aspect.endswith("texto visible"):
        aid = aspect.split(".", 1)[0]
        va = next((a for a in sa.get("actions", []) if a.get("id") == aid), {})
        vb = next((a for a in sb.get("actions", []) if a.get("id") == aid), {})
        return list(difflib.unified_diff((va.get("visible") or {}).get("text_preview", "").splitlines(),
                                         (vb.get("visible") or {}).get("text_preview", "").splitlines(),
                                         "a", "b", lineterm="", n=1))[:20]
    return None


def _context(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    diffs = []

    def add(factor: str, va: Any, vb: Any) -> None:
        if va != vb:
            diffs.append({"factor": factor, "a": _short(va), "b": _short(vb)})

    ta, tb = a.get("target") or {}, b.get("target") or {}
    add("objetivo (sha256)", ta.get("sha256"), tb.get("sha256"))
    add("objetivo (versión declarada)", ta.get("version"), tb.get("version"))
    add("guion (sha256)", a.get("script_sha256"), b.get("script_sha256"))
    pa = {Path(p["path"]).name: p.get("sha256") for p in a.get("programs", [])}
    pb = {Path(p["path"]).name: p.get("sha256") for p in b.get("programs", [])}
    add("programas ejecutados", pa, pb)
    for k in sorted(set(a.get("platform", {})) | set(b.get("platform", {}))):
        add(f"plataforma.{k}", a.get("platform", {}).get(k), b.get("platform", {}).get(k))
    ea, eb = a.get("environment", {}), b.get("environment", {})
    for k in ("inherit", "passthrough", "declared", "redirected"):
        add(f"entorno.{k}", ea.get(k), eb.get(k))
    add("variables de ejecución", a.get("variables"), b.get("variables"))
    add("estado inicial (archivos)", a.get("initial_state", {}).get("files"), b.get("initial_state", {}).get("files"))
    add("estado inicial (registro)", a.get("initial_state", {}).get("registry"),
        b.get("initial_state", {}).get("registry"))
    ba = [s.get("browser") for s in a.get("steps", []) if s.get("browser")]
    bb = [s.get("browser") for s in b.get("steps", []) if s.get("browser")]
    add("navegador", ba, bb)
    return diffs


def compare_sessions(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Compara dos registros de sesión (``result`` de la evidencia)."""
    steps_b = {s["id"]: s for s in b.get("steps", [])}
    ids_a = [s["id"] for s in a.get("steps", [])]
    differences: list[dict[str, Any]] = []
    for sa in a.get("steps", []):
        sb = steps_b.get(sa["id"])
        if sb is None:
            differences.append({"step": sa["id"], "aspect": "paso ausente en b", "a": sa["action"], "b": None})
            continue
        ob = dict(observables(sb))
        for aspect, va in observables(sa):
            vb = ob.pop(aspect, None)
            if va != vb:
                d = {"step": sa["id"], "action": sa["action"], "aspect": aspect, "a": _short(va), "b": _short(vb)}
                det = _detail(aspect, sa, sb)
                if det:
                    d["detail"] = det
                differences.append(d)
        for aspect, vb in ob.items():
            if vb not in (None, [], {}):
                differences.append({"step": sa["id"], "action": sa["action"], "aspect": aspect, "a": None,
                                    "b": _short(vb)})
    for sid in steps_b:
        if sid not in ids_a:
            differences.append({"step": sid, "aspect": "paso ausente en a", "a": None, "b": steps_b[sid]["action"]})
    context = _context(a, b)
    first = differences[0] if differences else None
    return {
        "identical": not differences,
        "steps_compared": len([s for s in ids_a if s in steps_b]),
        "first_change": first,
        "differences": differences[:500],
        "differences_total": len(differences),
        "context_differences": context,
        "attribution": {
            "status": "hypothesis",
            "candidates": [c["factor"] for c in context],
            "note": ("Factores de contexto que difieren entre las ejecuciones. Que difieran no demuestra que causen "
                     "el cambio observado; confírmalo variando un factor cada vez." if context else
                     "No difiere ningún factor de contexto registrado: el cambio puede deberse a factores no fijados "
                     "(reloj, planificación, red, estado externo) o a no determinismo del objetivo."),
        } if differences else {"status": "hypothesis", "candidates": [], "note": "sin cambios observables"},
        "limits": "Solo se comparan los aspectos observados en ambas sesiones con el alcance de su coverage.",
    }


def _store_derived(store: EvidenceStore, a: dict[str, Any], b: dict[str, Any], operation: str,
                   result: dict[str, Any]) -> tuple[str, str]:
    subject = a["subject"] if a["subject"] == b["subject"] else \
        f"compare:observe:{a['evidence_id'][:16]}..{b['evidence_id'][:16]}"
    ev = Evidence(subject=subject, provider=obs.PROVIDER, provider_version=obs.VERSION, operation=operation,
                  params={"a": a["evidence_id"], "b": b["evidence_id"]}, result=result,
                  authority=Authority.CONTROLLED_REPRO, confidence=Confidence.MEDIUM,
                  limitations=result.get("limits", ""), links=[a["evidence_id"], b["evidence_id"]])
    eid, _ = store.add_evidence(ev)
    return eid, subject


def _case_link(run: Any, store: EvidenceStore, subject: str, sessions: list[dict[str, Any]]) -> None:
    for s in sessions:
        run.associate(s["subject"], path=((s["session"].get("target") or {}).get("path") or ""))
    if subject not in [s["subject"] for s in sessions]:
        run.artifact(subject, size=None, format="observation-comparison", identity="derived", content_sha256="",
                     metadata={"sessions": [s["evidence_id"] for s in sessions]})


def run_compare(store: EvidenceStore, a_id: str, b_id: str, *, case_id: str | None = None) -> dict[str, Any]:
    from eolfi.core.cases import case_run

    with case_run(store, case_id, "observe_compare", {"a": a_id, "b": b_id}, "sesiones de observación") as run:
        a, b = obs.load_session(store, a_id), obs.load_session(store, b_id)
        result = compare_sessions(a["session"], b["session"])
        eid, subject = _store_derived(store, a, b, COMPARE_OPERATION, result)
        rep = {"evidence_id": eid, "subject": subject, "a": a_id, "b": b_id, **result}
        if run.active:
            _case_link(run, store, subject, [a, b])
            claims = []
            if result["first_change"]:
                fc = result["first_change"]
                claims.append({"text": f"Primer cambio observable: paso {fc['step']}, {fc['aspect']}",
                               "status": "derived", "evidence_ids": [eid, a_id, b_id]})
                if result["attribution"]["candidates"]:
                    claims.append({"text": "Posibles causas (sin confirmar): "
                                   + ", ".join(result["attribution"]["candidates"])[:3000],
                                   "status": "hypothesis", "evidence_ids": [eid]})
            run.finish(status="done", evidence_ids=[eid, a_id, b_id], claims=claims,
                       tools=[{"name": obs.PROVIDER, "version": obs.VERSION, "status": "ran"}],
                       result={k: result[k] for k in ("identical", "steps_compared", "first_change",
                                                      "differences_total")})
            rep["case_record"] = run.record_id
        return rep


def run_replay(store: EvidenceStore, evidence_id: str, *, authorized: bool, variables: dict[str, str] | None = None,
               case_id: str | None = None, playwright: str | None = None) -> dict[str, Any]:
    """Repite una sesión guardada desde su guion y marca lo que no se pudo reproducir."""
    if not authorized:
        raise PermissionError("repetir la sesión EJECUTA el objetivo: confirma la autorización (--autorizo)")
    from eolfi.core.cases import case_run
    from eolfi.providers.triage import sha256_file

    orig = obs.load_session(store, evidence_id)
    script, osess = orig["params"]["script"], orig["session"]
    base_dir = Path(orig["params"].get("base_dir") or Path.cwd())
    with case_run(store, case_id, "replay", {"replay_of": evidence_id}, "repetición desde el guion") as run:
        prechecks: list[dict[str, Any]] = []
        target = osess.get("target")
        if target:
            p = Path(target["path"])
            now = sha256_file(p) if p.is_file() else None
            if now != target.get("sha256"):
                prechecks.append({"factor": "objetivo", "detail": f"el objetivo cambió o falta: {p}"})
        for rel, rec in (osess.get("setup") or {}).items():
            src = rec.get("copied_from")
            if src:
                sp = Path(src) if Path(src).is_absolute() else base_dir / src
                if not sp.is_file() or sha256_file(sp) != rec["sha256"]:
                    prechecks.append({"factor": "estado inicial", "detail": f"setup.files[{rel}] cambió: {src}"})
        missing = sorted(obs.referenced_variables(script) - set(variables or {}))
        if missing:
            raise ValueError("faltan variables de ejecución para repetir: " + ", ".join(missing))
        new = obs.run_observation(script, store, authorized=True, variables=variables, playwright=playwright,
                                  base_dir=base_dir, _replay_of=evidence_id)
        nsess = {"evidence_id": new["evidence_id"], "subject": new["subject"], "session": new}
        cmp = compare_sessions(osess, new)
        non_repro = [{"step": d["step"], "aspect": d["aspect"],
                      "reason": "difiere entre dos ejecuciones del mismo guion"} for d in cmp["differences"]]
        result = {"original": evidence_id, "replay": new["evidence_id"],
                  "reproducible": cmp["identical"] and not prechecks,
                  "prechecks": prechecks, "non_reproducible": non_repro[:500],
                  "unfixed_factors": osess.get("unfixed_factors", []),
                  "context_differences": cmp["context_differences"], "first_change": cmp["first_change"],
                  "limits": ("Una repetición coincidente no prueba determinismo: los factores no fijados pueden "
                             "variar en otra ejecución.")}
        eid, subject = _store_derived(store, orig, nsess, REPLAY_OPERATION, result)
        rep = {"evidence_id": eid, "subject": subject, **result}
        if run.active:
            _case_link(run, store, subject, [orig, nsess])
            run.finish(status="done" if new["status"] == "done" else "partial",
                       evidence_ids=[eid, evidence_id, new["evidence_id"]],
                       tools=[{"name": obs.PROVIDER, "version": obs.VERSION, "status": "ran"}],
                       errors=[f"{d['step']}: {d['aspect']}" for d in non_repro][:200],
                       result={k: result[k] for k in ("reproducible", "prechecks", "first_change")}
                       | {"non_reproducible": len(non_repro)})
            rep["case_record"] = run.record_id
        return rep
