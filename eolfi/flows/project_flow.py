"""Crear un proyecto a partir de fuentes con un PLAN razonado que el usuario aprueba antes de ejecutar nada.

1. ``propose_plan``: crea el caso, clasifica las fuentes e interpreta la descripción (directivas reconocidas y lo
   que no se pudo interpretar, ambos visibles) y propone pasos con qué hacen, qué usan, qué producen, cómo se
   verifican, riesgos y justificación. **No analiza ni ejecuta nada.**
2. ``approve_plan``: el usuario aprueba el plan, o lo edita (tecnología, opciones, instrucciones) — una edición
   crea una versión nueva ya aprobada; la decisión queda en el caso.
3. ``run_plan``: sigue el plan aprobado reutilizando los flujos existentes (triage/web/repo → especificación →
   create_project con verificación obligatoria). En modo ``auto`` ejecuta todos los pasos; en ``guided`` uno
   y se detiene para que el usuario continúe o añada instrucciones. Una instrucción que cambie lo planificado se
   propone como cambio de plan y exige aprobación. Sin verificación superada, el resultado nunca es verde.

Todo (planes, aprobaciones, decisiones, resultados de pasos) se guarda como registros «execution» del caso.
"""
from __future__ import annotations

import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from eolfi.core.cases import CaseStore
from eolfi.core.evidence import EvidenceStore

PLAN_FORMAT = 1
MODES = ("auto", "guided")
TARGETS = ("auto", "react", "vue", "svelte", "next", "static", "fastapi", "express", "django", "expo", "desktop",
           "tauri", "dotnet", "cli")
_TARGET_WORDS = [
    (r"\bnext(\.js)?\b", "next"), (r"\breact\b", "react"), (r"\bvue\b", "vue"), (r"\bsvelte\b", "svelte"),
    (r"\bfastapi\b", "fastapi"), (r"\bexpress\b", "express"), (r"\bdjango\b", "django"),
    (r"\b(m[oó]vil|android|ios|expo)\b", "expo"), (r"\btauri\b", "tauri"),
    (r"\b(\.net|dotnet|c#|avalonia)\b", "dotnet"), (r"\belectron\b", "desktop"),
    (r"\b(escritorio|desktop)\b", "desktop"), (r"\b(l[ií]nea de comandos|cli|terminal)\b", "cli"),
    (r"\b(est[aá]tic[oa]|html est[aá]tico)\b", "static"),
]
_OPTION_WORDS = [(r"\b(sqlite|base de datos|bbdd|persistencia)\b", "sqlite", "base de datos SQLite"),
                 (r"\b(login|inicio de sesi[oó]n|autenticaci[oó]n|usuarios)\b", "auth", "inicio de sesión")]


class PlanError(ValueError):
    pass


def interpret(description: str) -> dict[str, Any]:
    """Directivas reconocidas en la descripción (reglas explícitas, sin IA) y frases sin interpretar."""
    text = description.strip()
    low = text.lower()
    directives: list[dict[str, str]] = []
    target = "auto"
    for pat, tgt in _TARGET_WORDS:
        m = re.search(pat, low)
        if m:
            target = tgt
            directives.append({"text": m.group(0), "effect": f"tecnología destino: {tgt}"})
            break
    options = {"sqlite": False, "auth": False}
    for pat, key, label in _OPTION_WORDS:
        m = re.search(pat, low)
        if m:
            options[key] = True
            directives.append({"text": m.group(0), "effect": f"incluir {label}"})
    sentences = [s.strip() for s in re.split(r"(?<=[.;!?\n])\s*", text) if s.strip()]
    used = [d["text"] for d in directives]
    uninterpreted = [s for s in sentences if not any(u in s.lower() for u in used)]
    return {"target": target, "options": options, "directives": directives, "uninterpreted": uninterpreted}


def _classify(ref: str) -> str:
    from eolfi.flows.create_flow import classify

    return classify(ref)


_KIND_LABEL = {"web": "web", "repo": "repositorio", "binary": "archivo", "subject": "objetivo ya analizado"}


def _steps(sources: list[dict[str, str]], interp: dict[str, Any], out: str) -> list[dict[str, Any]]:
    steps = []
    for i, s in enumerate(sources, 1):
        kind = s["kind"]
        remote = s["ref"].startswith(("http://", "https://", "git@", "ssh://"))
        how = {"web": ("descarga la página y sus recursos públicos" if remote else "lee el sitio local (HTML y "
                       "recursos)") + " y deduce la pila (sin ejecutar su código)",
               "repo": "clona superficialmente el repositorio y analiza su estructura y dependencias (no ejecuta "
                       "sus scripts)",
               "subject": "reutiliza el análisis ya guardado"}.get(
            kind, "triaje estático local: huella, formato, cabeceras y cadenas (no ejecuta el archivo)")
        steps.append({"id": f"analizar-{i}", "action": "analyze", "source": s["ref"],
                      "title": f"Analizar {_KIND_LABEL.get(kind, kind)}: "
                               + (s["ref"] if len(s["ref"]) <= 160 else "…" + s["ref"][-159:]),
                      "what": how, "uses": [s["ref"]], "produces": "evidencias e incógnitas en el caso",
                      "verification": "cada evidencia guarda proveedor, versión y entorno; los fallos quedan como "
                                      "resultado parcial",
                      "rationale": "sin evidencias de la fuente no hay especificación ni reconstrucción trazable",
                      "risks": (["el contenido remoto puede variar entre peticiones"] if kind == "web" and remote else
                                ["la carpeta puede cambiar: su contenido se registra con hash al analizarla"]
                                if kind in ("web", "repo") and not remote else
                                ["requiere red para clonar"] if kind == "repo" and s["ref"].startswith(("http", "git@"))
                                else [])})
    steps.append({"id": "especificar", "action": "specify", "title": "Construir la especificación sustentada",
                  "what": "agrupa el comportamiento observado y los hechos de las fuentes en requisitos con "
                          "evidencias y confianza; separa hipótesis e incógnitas",
                  "uses": [s["id"] for s in steps], "produces": "especificación versionada (registro del caso)",
                  "verification": "cada requisito enlaza evidencias existentes en el caso",
                  "rationale": "la reconstrucción debe salir de comportamiento y contratos documentados, no del código",
                  "risks": ["sin observación dinámica autorizada (eolfi observe) la especificación solo tendrá "
                            "hechos estáticos de las fuentes"]})
    opts = [k for k, v in interp["options"].items() if v]
    steps.append({"id": "generar", "action": "generate",
                  "title": f"Generar el proyecto ({interp['target']}{', ' + ', '.join(opts) if opts else ''})",
                  "what": "genera código propio con el generador de plantillas de Eolfi a partir del análisis; "
                          "no copia código de las fuentes",
                  "uses": ["especificar"], "produces": f"proyecto nuevo en {out}",
                  "verification": "instalación/restauración, compilación, pruebas y prueba de humo obligatorias "
                                  "(eolfi.generador.verify); sin verificación verde el resultado es parcial",
                  "rationale": "reutiliza create_project, el mismo flujo de la CLI y el panel",
                  "risks": ["la verificación necesita el toolchain del destino; si falta queda NO VERIFICADO",
                            "lo no observado ni especificado se genera como base y queda pendiente"]})
    return steps


def _records(cases: CaseStore, case_id: str) -> list[dict[str, Any]]:
    return [r for r in cases.get(case_id)["records"] if r["kind"] == "execution" and "project" in r["payload"]]


def _add(cases: CaseStore, case_id: str, entry: dict[str, Any]) -> str:
    return cases.add_record(case_id, "execution", {"project": entry})


def state(store: EvidenceStore, case_id: str) -> dict[str, Any]:
    """Plan vigente, aprobación, decisiones y resultados de pasos, a partir de los registros del caso."""
    cases = CaseStore(store)
    plans, decisions, results = [], [], {}
    for r in _records(cases, case_id):
        e = r["payload"]["project"]
        if e["type"] == "plan":
            plans.append(e | {"record_id": r["record_id"]})
        elif e["type"] == "step_result":
            results[e["step"]] = e | {"record_id": r["record_id"]}
        else:
            decisions.append(e | {"record_id": r["record_id"], "created_at": r["created_at"]})
    if not plans:
        raise PlanError("el caso no tiene un plan de proyecto")
    plan = plans[-1]
    approved = any(d["type"] == "approval" and d["plan_version"] == plan["version"] for d in decisions)
    decided = {d.get("proposal") for d in decisions if d["type"] == "change_decision"}
    pending_change = next((d for d in reversed(decisions) if d["type"] == "change_proposal"
                           and d["plan_version"] == plan["version"] and d["record_id"] not in decided), None)
    done = [s["id"] for s in plan["steps"] if s["id"] in results and results[s["id"]]["status"] in ("done", "partial")]
    failed = [s["id"] for s in plan["steps"] if s["id"] in results and results[s["id"]]["status"] == "error"]
    nxt = next((s["id"] for s in plan["steps"] if s["id"] not in done), None)
    if not approved:
        status = "awaiting_approval"
    elif pending_change:
        status = "change_proposed"
    elif failed:
        status = "failed"
    elif nxt is None:
        gen = results.get("generar", {})
        status = "done" if gen.get("verified") else "done_unverified"
    else:
        status = "ready" if not done else ("awaiting_continue" if plan["mode"] == "guided" else "ready")
    return {"case_id": case_id, "plan": plan, "plans": len(plans), "approved": approved, "status": status,
            "next_step": nxt, "results": results, "decisions": decisions, "pending_change": pending_change}


def propose_plan(store: EvidenceStore, *, name: str, description: str, sources: list[str], mode: str = "auto",
                 out: str | None = None) -> dict[str, Any]:
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise PlanError("el nombre es obligatorio (máx. 120 caracteres)")
    if not isinstance(description, str) or len(description) > 8000:
        raise PlanError("descripción demasiado larga")
    if mode not in MODES:
        raise PlanError("modo debe ser auto o guided")
    if not isinstance(sources, list) or not sources or len(sources) > 50 or not all(
            isinstance(s, str) and s.strip() for s in sources):
        raise PlanError("añade al menos una fuente (archivo, web o repositorio)")
    srcs = []
    for ref in dict.fromkeys(s.strip() for s in sources):
        kind = _classify(ref)
        if kind == "subject":
            from eolfi.flows.create_flow import resolve_subject

            if not resolve_subject(store, ref):
                raise PlanError(f"'{ref}' no es una URL, una ruta existente ni un objetivo ya analizado")
        srcs.append({"ref": ref, "kind": kind})
    from eolfi.server import _folder_slug

    out = out or str(Path("generated") / _folder_slug(name))
    interp = interpret(description)
    cases = CaseStore(store)
    case = cases.create(name.strip(), description)
    plan = {"type": "plan", "format": PLAN_FORMAT, "version": 1, "plan_id": str(uuid.uuid4()), "mode": mode,
            "name": name.strip(), "description": description, "sources": srcs, "out": out,
            "target": interp["target"], "options": interp["options"], "instructions": [],
            "interpretation": {"directives": interp["directives"], "uninterpreted": interp["uninterpreted"]},
            "reasoning": _reasoning(srcs, interp),
            "steps": _steps(srcs, interp, out), "proposed_at": time.time()}
    _add(cases, case["case_id"], plan)
    return state(store, case["case_id"])


def _reasoning(srcs: list[dict[str, str]], interp: dict[str, Any]) -> list[str]:
    kinds = sorted({_KIND_LABEL.get(s["kind"], s["kind"]) for s in srcs})
    r = [f"Fuentes: {len(srcs)} ({', '.join(kinds)}). Se analizan primero para tener evidencias de cada una."]
    if interp["target"] == "auto":
        r.append("La descripción no fija la tecnología: se elegirá a partir de la pila detectada en las fuentes.")
    else:
        r.append(f"La descripción pide «{interp['directives'][0]['text']}» → destino {interp['target']}.")
    if interp["uninterpreted"]:
        r.append(f"{len(interp['uninterpreted'])} frase(s) no se traducen a una opción del generador: quedan como "
                 "instrucciones pendientes en el caso y no se aplican solas.")
    r.append("El código se genera con plantillas propias; nunca se copia código de las fuentes.")
    r.append("El resultado solo se da por bueno si la verificación (instalar, compilar, probar) pasa.")
    return r


def approve_plan(store: EvidenceStore, case_id: str, *, version: int, reviewer: str = "usuario",
                 edits: dict[str, Any] | None = None, note: str = "") -> dict[str, Any]:
    """Aprueba la versión indicada; con ``edits`` (target, options, mode, instructions) crea la versión siguiente."""
    st = state(store, case_id)
    plan = st["plan"]
    if version != plan["version"]:
        raise PlanError(f"la versión vigente del plan es la {plan['version']}")
    cases = CaseStore(store)
    if edits:
        plan = _revise(plan, edits)
        _add(cases, case_id, plan)
    _add(cases, case_id, {"type": "approval", "plan_version": plan["version"], "reviewer": str(reviewer)[:200],
                          "note": str(note)[:4000], "edited": bool(edits)})
    return state(store, case_id)


def _revise(plan: dict[str, Any], edits: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(edits, dict) or not set(edits) <= {"target", "options", "mode", "instructions"}:
        raise PlanError("edits admite target, options, mode e instructions")
    new = {k: v for k, v in plan.items() if k != "record_id"}
    changes = []
    if "target" in edits:
        if edits["target"] not in TARGETS:
            raise PlanError("tecnología no admitida")
        if edits["target"] != plan["target"]:
            changes.append(f"tecnología {plan['target']} → {edits['target']}")
        new["target"] = edits["target"]
    if "options" in edits:
        o = edits["options"]
        if not isinstance(o, dict) or not set(o) <= {"sqlite", "auth"} or not all(isinstance(v, bool) for v in o.values()):
            raise PlanError("options admite sqlite y auth (booleanos)")
        new["options"] = {**plan["options"], **o}
        if new["options"] != plan["options"]:
            changes.append(f"opciones {plan['options']} → {new['options']}")
    if "mode" in edits:
        if edits["mode"] not in MODES:
            raise PlanError("modo debe ser auto o guided")
        new["mode"] = edits["mode"]
    if "instructions" in edits:
        ins = edits["instructions"]
        if not isinstance(ins, list) or not all(isinstance(x, str) and len(x) <= 4000 for x in ins):
            raise PlanError("instructions debe ser una lista de textos")
        new["instructions"] = plan["instructions"] + [x.strip() for x in ins if x.strip()]
    new["version"] = plan["version"] + 1
    new["revised_from"] = plan["version"]
    new["changes"] = changes
    new["steps"] = _steps(plan["sources"], {"target": new["target"], "options": new["options"]}, plan["out"])
    new["proposed_at"] = time.time()
    return new


def add_instruction(store: EvidenceStore, case_id: str, text: str, *, reviewer: str = "usuario") -> dict[str, Any]:
    """Instrucción durante la ejecución guiada. Si cambia lo planificado, se propone un cambio de plan."""
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise PlanError("instrucción vacía o demasiado larga")
    st = state(store, case_id)
    plan = st["plan"]
    interp = interpret(text)
    edits: dict[str, Any] = {"instructions": [text]}
    if interp["target"] != "auto" and interp["target"] != plan["target"]:
        edits["target"] = interp["target"]
    opts = {k: True for k, v in interp["options"].items() if v and not plan["options"].get(k)}
    if opts:
        edits["options"] = opts
    cases = CaseStore(store)
    if set(edits) == {"instructions"}:
        _add(cases, case_id, {"type": "instruction", "plan_version": plan["version"], "text": text,
                              "reviewer": reviewer, "applies": "nota para el caso; no cambia los pasos"})
    else:
        _add(cases, case_id, {"type": "change_proposal", "plan_version": plan["version"], "text": text,
                              "reviewer": reviewer, "edits": edits,
                              "reason": "la instrucción cambia lo planificado: requiere aprobar el plan revisado"})
    return state(store, case_id)


def accept_change(store: EvidenceStore, case_id: str, *, accept: bool, reviewer: str = "usuario") -> dict[str, Any]:
    st = state(store, case_id)
    ch = st["pending_change"]
    if not ch:
        raise PlanError("no hay cambio de plan pendiente")
    cases = CaseStore(store)
    _add(cases, case_id, {"type": "change_decision", "plan_version": ch["plan_version"], "accepted": accept,
                          "reviewer": reviewer, "proposal": ch["record_id"]})
    if accept:
        return approve_plan(store, case_id, version=st["plan"]["version"], reviewer=reviewer, edits=ch["edits"],
                            note="cambio de plan aprobado")
    # Rechazado: la propuesta deja de bloquear (se re-aprueba la misma versión).
    _add(cases, case_id, {"type": "approval", "plan_version": st["plan"]["version"], "reviewer": reviewer,
                          "note": "cambio de plan rechazado; se sigue el plan vigente", "edited": False})
    return state(store, case_id)


def run_plan(store: EvidenceStore, case_id: str, *, workdir: str = "samples/repos",
             progress: Callable[[str], None] | None = None, force: bool = False) -> dict[str, Any]:
    """Ejecuta el plan aprobado: todos los pasos pendientes (auto) o el siguiente (guided)."""
    log = progress or (lambda _m: None)
    st = state(store, case_id)
    if not st["approved"]:
        raise PlanError("el plan no está aprobado: revísalo y apruébalo antes de ejecutar")
    if st["pending_change"]:
        raise PlanError("hay un cambio de plan pendiente de aprobar")
    plan = st["plan"]
    cases = CaseStore(store)
    for step in plan["steps"]:
        if step["id"] in st["results"] and st["results"][step["id"]]["status"] in ("done", "partial"):
            continue
        if step["id"] in st["results"] and st["results"][step["id"]]["status"] == "error" and not force:
            raise PlanError(f"el paso {step['id']} falló; corrige el plan o reintenta")
        log(f"paso {step['id']}: {step['title']}")
        entry = {"type": "step_result", "step": step["id"], "plan_version": plan["version"],
                 "started_at": time.time()}
        try:
            entry.update(_execute(store, case_id, plan, step, st, workdir, log))
        except Exception as exc:  # noqa: BLE001 — el fallo del paso queda en el caso
            entry.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:1500]}")
        except BaseException:      # cancelación del trabajo (JobCancelled) o interrupción: queda registrada
            _add(cases, case_id, entry | {"status": "cancelled", "error": "cancelado por el usuario",
                                          "finished_at": time.time()})
            raise
        entry["finished_at"] = time.time()
        _add(cases, case_id, entry)
        st = state(store, case_id)
        log(f"paso {step['id']}: {entry['status']}")
        if entry["status"] == "error" or plan["mode"] == "guided":
            break
    return state(store, case_id)


def _execute(store: EvidenceStore, case_id: str, plan: dict[str, Any], step: dict[str, Any], st: dict[str, Any],
             workdir: str, log: Callable[[str], None]) -> dict[str, Any]:
    if step["action"] == "analyze":
        src = next(s for s in plan["sources"] if s["ref"] == step["source"])
        if src["kind"] == "subject":
            from eolfi.flows.create_flow import resolve_subject

            subject = resolve_subject(store, src["ref"])
            CaseStore(store).associate(case_id, subject, provenance="objetivo ya analizado")
            return {"status": "done", "subject": subject}
        if src["kind"] == "web":
            from eolfi.flows.learn_flow import run_web
            rep = run_web(src["ref"], store, progress=log, case_id=case_id)
        elif src["kind"] == "repo":
            from eolfi.flows.learn_flow import run_repo
            rep = run_repo(src["ref"], store, workdir=workdir, progress=log, case_id=case_id)
        else:
            from eolfi.flows.triage_flow import LOCAL_PROVIDERS, run_triage
            rep = run_triage(src["ref"], store, LOCAL_PROVIDERS, case_id=case_id)
        return {"status": "done" if rep.get("case_record") else "partial", "subject": rep["subject"],
                "case_record": rep.get("case_record")}
    if step["action"] == "specify":
        from eolfi.spec import store_spec

        spec = store_spec(store, case_id)
        return {"status": "done", "spec_version": spec["spec_version"], "requirements": len(spec["requirements"]),
                "contradictions": len(spec["contradictions"]), "artifacts": len(spec["artifacts"]),
                "open_incognitas": len(spec["unknowns"]["open_incognitas"])}
    if step["action"] == "generate":
        from eolfi.flows.create_flow import create_project

        subjects = [r["subject"] for k, r in st["results"].items() if k.startswith("analizar-") and r.get("subject")]
        if not subjects:
            raise PlanError("no hay fuentes analizadas")
        rep = create_project(subjects, store, plan["out"], name=plan["name"], target=plan["target"], do_verify=True,
                             workdir=workdir, db="sqlite" if plan["options"].get("sqlite") else "memory",
                             auth=bool(plan["options"].get("auth")), progress=log, case_id=case_id,
                             provenance="plan aprobado de crear proyecto")
        ver = rep.get("verification") or {}
        verified = bool(ver.get("ok"))
        return {"status": "done" if verified else "partial", "verified": verified, "out": rep.get("out"),
                "target": rep.get("target"), "files": rep.get("files"),
                "verification": {"ok": verified, **({"error": ver["error"]} if ver.get("error") else {}),
                                 "steps": [{k: s.get(k) for k in ("step", "exit", "seconds")}
                                           for s in (ver.get("steps") or [])][:50]},
                **({} if verified else {"note": "NO VERIFICADO o verificación fallida: no es un producto listo"})}
    raise PlanError(f"acción desconocida: {step['action']}")
