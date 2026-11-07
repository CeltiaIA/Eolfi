"""Informe navegable (HTML autocontenido) de un caso de análisis.

Cada conclusión enlaza con las evidencias que la sustentan, las incógnitas relacionadas y sus límites.
El estado de cada conclusión se muestra tal como se registró (observada, derivada o hipótesis); el informe
no eleva nada. Las evidencias importadas se señalan: su autoridad la declaró el paquete, no esta máquina.
Sin scripts ni recursos externos; todo el texto procedente de objetivos se escapa.
"""
from __future__ import annotations

import html
import json
import time
from datetime import datetime, timezone
from typing import Any

from eolfi.core.cases import OBSERVED_AUTHORITIES, environment_identity

CLAIM_LABEL = {"observed": "Observada", "derived": "Derivada", "hypothesis": "Hipótesis"}
AUTHORITY_LABEL = {"distributed_artifact": "observada en el artefacto", "controlled_repro": "reproducción controlada",
                   "analyst_inference": "inferencia"}
IDENTITY_LABEL = {"content": "hash del contenido", "git_commit": "commit de git fijado",
                  "descriptor": "referencia (el contenido puede cambiar)", "derived": "subject derivado por Eolfi"}
STATUS_LABEL = {"done": "completado", "partial": "parcial", "error": "error", "cancelled": "cancelado"}
IMPORT_MARK = "[importada de "


def _iso(t: Any) -> str:
    try:
        return datetime.fromtimestamp(float(t), timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (TypeError, ValueError, OverflowError, OSError):
        return "?"


def _loads(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def build_case_report(case: dict[str, Any]) -> dict[str, Any]:
    """Estructura del informe a partir de CaseStore.get(); no consulta ni modifica el almacén."""
    evidence = {e["evidence_id"]: e for e in case["evidence"]}
    incognitas = {i["incognita_id"]: i for i in case["incognitas"]}
    imported = {eid for eid, e in evidence.items() if IMPORT_MARK in str(e.get("limitations") or "")}
    conclusions: list[dict[str, Any]] = []
    limits: list[str] = []
    for rec in case["records"]:
        p = rec["payload"]
        rec_inc = [i for i in case["incognitas"] if i["subject"] in set(p.get("artifacts", []))
                   and i["status"] != "resolved"]
        for c in p.get("claims", []):
            ids = [x for x in c.get("evidence_ids", []) if x in evidence]
            conclusions.append({
                "text": c["text"], "status": c["status"], "record_id": rec["record_id"], "source": "registro",
                "evidence_ids": ids, "incognita_ids": [x for x in c.get("incognita_ids", []) if x in incognitas],
                "limits": [x for x in [c.get("limits", "")] if x] + _evidence_limits(ids, evidence),
                "imported": bool(set(ids) & imported),
                "observed_support": sum(1 for x in ids if evidence[x]["authority"] in OBSERVED_AUTHORITIES)})
        if "flow" in p and p.get("status") in ("done", "partial"):
            ids = [x for x in p.get("evidence_ids", []) if x in evidence]
            lim = [f"herramienta {t['name']}: {t['status']}" for t in p.get("tools", [])
                   if t.get("status") in ("skipped", "failed")] + list(p.get("errors", []))
            conclusions.append({
                "text": _flow_sentence(p), "status": "derived" if ids else "hypothesis", "record_id": rec["record_id"],
                "source": f"flujo {p['flow']}", "evidence_ids": ids,
                "incognita_ids": [i["incognita_id"] for i in rec_inc][:50],
                "limits": lim + _evidence_limits(ids, evidence), "imported": bool(set(ids) & imported),
                "observed_support": sum(1 for x in ids if evidence[x]["authority"] in OBSERVED_AUTHORITIES)})
        if p.get("status") in ("error", "cancelled", "partial"):
            limits.append(f"Registro {rec['record_id'][:8]} ({p.get('flow', rec['kind'])}): "
                          f"{STATUS_LABEL.get(p['status'], p['status'])}"
                          + (f" — {'; '.join(p.get('errors', [])[:3])}" if p.get("errors") else ""))
    for a in case["artifacts"]:
        if a["identity"] in ("descriptor", "derived"):
            limits.append(f"Artefacto {a['subject'][:60]}: identidad «{IDENTITY_LABEL[a['identity']]}», "
                          "no es un hash de contenido.")
        if a["size"] is None:
            limits.append(f"Artefacto {a['subject'][:60]}: tamaño desconocido.")
    open_inc = [i for i in case["incognitas"] if i["status"] != "resolved"]
    if open_inc:
        limits.append(f"{len(open_inc)} incógnitas abiertas: las conclusiones relacionadas no están cerradas.")
    if imported:
        limits.append(f"{len(imported)} evidencias importadas: su autoridad y confianza las declaró el paquete; "
                      "no se reverificaron en esta máquina.")
    hyp = sum(1 for c in conclusions if c["status"] == "hypothesis")
    if hyp:
        limits.append(f"{hyp} conclusiones son hipótesis: no deben citarse como hechos.")
    limits.append("La cobertura se limita a los artefactos, herramientas y entradas registrados; "
                  "lo no observado no se afirma.")
    statuses: dict[str, int] = {}
    for rec in case["records"]:
        st = rec["payload"].get("status", "registro")
        statuses[st] = statuses.get(st, 0) + 1
    return {"case": {k: case[k] for k in ("case_id", "name", "description", "created_at", "updated_at")},
            "artifacts": case["artifacts"], "records": case["records"], "evidence": case["evidence"],
            "incognitas": case["incognitas"], "imports": case.get("imports", []), "conclusions": conclusions,
            "limits": limits, "statuses": statuses, "open_incognitas": len(open_inc), "imported": sorted(imported),
            "generated_at": time.time(), "environment": environment_identity()}


def _evidence_limits(ids: list[str], evidence: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for x in ids:
        lim = str(evidence[x].get("limitations") or "").strip()
        if lim and lim not in out:
            out.append(lim[:400])
    return out[:8]


def _flow_sentence(p: dict[str, Any]) -> str:
    r = p.get("result") or {}
    flow = p["flow"]
    if flow == "triage":
        s = r.get("summary") or {}
        bits = [f"formato {s['format']}" if s.get("format") else "", f"máquina {s['machine']}" if s.get("machine") else ""]
        return f"Triaje: {', '.join(b for b in bits if b) or 'sin resumen'}; proveedores ejecutados: " \
               f"{', '.join(r.get('providers_run', [])) or 'ninguno'}."
    if flow in ("web", "repo"):
        s = r.get("summary") or {}
        stack = s.get("stack")
        label = (", ".join(stack) if isinstance(stack, list) and stack else stack if isinstance(stack, str) and stack
                 else s.get("stack_label") or "no determinada")
        return f"Análisis {flow}: pila {label}."
    if flow == "diff":
        return (f"Diferencial: {r.get('equivalent', 0)}/{r.get('comparable', 0)} entradas equivalentes "
                f"(umbral {r.get('threshold')}); {'supera' if r.get('passed') else 'no supera'} el umbral en el corpus probado.")
    if flow == "compare":
        return f"Comparación: cambian {len(r.get('changed', []))} aspectos ({', '.join(r.get('changed', [])[:6])})."
    if flow == "create":
        ver = r.get("verification") or {}
        return (f"Reconstrucción en {r.get('out')} ({r.get('target')}, {r.get('files')} archivos): verificación "
                f"{'superada' if ver.get('ok') else 'no superada o no ejecutada'}.")
    if flow == "observe":
        unfixed = ", ".join(r.get("unfixed_factors", [])[:6]) or "ninguno declarado"
        return (f"Observación ({r.get('steps', 0)} pasos, estado {r.get('status')}); factores no fijados: {unfixed}.")
    if flow == "replay":
        return (f"Repetición desde el guion: {'reproducible' if r.get('reproducible') else 'NO reproducible'} "
                f"({r.get('non_reproducible', 0)} aspectos difieren).")
    if flow == "observe_compare":
        fc = r.get("first_change") or {}
        return ("Comparación de observaciones: sin cambios observables." if r.get("identical") else
                f"Comparación de observaciones: primer cambio en el paso {fc.get('step')} ({fc.get('aspect')}); "
                f"{r.get('differences_total', 0)} diferencias.")
    return f"Flujo {flow}."


_CSS = """
:root{color-scheme:light dark;--bg:#fff;--fg:#1d1d1f;--muted:#5f6368;--line:#d0d4da;--ok:#0b6b2b;--warn:#8a5a00;--bad:#a1122a;--accent:#0b57d0}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--fg:#e8eaed;--muted:#a8adb4;--line:#3a3f45;--ok:#7bd88f;--warn:#f2c46d;--bad:#ff8a9b;--accent:#8ab4f8}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:1.5rem}
nav{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:.5rem 1.5rem;z-index:1}
nav a{margin-right:1rem}
a{color:var(--accent)}
code{font-size:.85em;word-break:break-all}
table{border-collapse:collapse;width:100%;margin:.5rem 0 1rem}
th,td{border:1px solid var(--line);padding:.35rem .5rem;text-align:left;vertical-align:top}
.badge{display:inline-block;border:1px solid currentColor;border-radius:.6rem;padding:0 .45rem;font-size:.8em;margin-right:.3rem}
.observed,.done,.resolved{color:var(--ok)}.derived,.partial,.investigating{color:var(--warn)}
.hypothesis,.error,.cancelled,.open{color:var(--bad)}
.muted{color:var(--muted)}
article{border:1px solid var(--line);border-radius:.4rem;padding:.6rem .9rem;margin:.6rem 0}
article:target{outline:3px solid var(--accent)}
pre{white-space:pre-wrap;word-break:break-word;max-height:18rem;overflow:auto;font-size:.85em}
details summary{cursor:pointer}
"""


def render_case_html(r: dict[str, Any]) -> str:
    from eolfi.security.privacy import redact_report

    r = redact_report(r)   # datos personales y secretos fuera del informe (identificadores y huellas intactos)
    e = html.escape

    def ev_link(x: str) -> str:
        return f'<a href="#ev-{e(x)}"><code>{e(x[:12])}</code></a>'

    def inc_link(x: str) -> str:
        return f'<a href="#inc-{e(x)}"><code>{e(x)}</code></a>'

    art_ids = {a["subject"]: f"art-{n}" for n, a in enumerate(r["artifacts"])}

    def art_link(s: str) -> str:
        return f'<a href="#{art_ids[s]}"><code>{e(s[:64])}</code></a>' if s in art_ids else f"<code>{e(s[:64])}</code>"

    c = r["case"]
    concl = []
    for n, x in enumerate(r["conclusions"]):
        evs = ", ".join(ev_link(i) for i in x["evidence_ids"]) or '<span class="muted">ninguna</span>'
        incs = ", ".join(inc_link(i) for i in x["incognita_ids"]) or '<span class="muted">ninguna</span>'
        lims = "".join(f"<li>{e(lim)}</li>" for lim in x["limits"]) or '<li class="muted">sin límites registrados</li>'
        concl.append(
            f'<article id="concl-{n}"><p><span class="badge {e(x["status"])}">{e(CLAIM_LABEL[x["status"]])}</span>'
            + ('<span class="badge partial">importada: no reverificada</span>' if x["imported"] else "")
            + f'{e(x["text"])}</p><p class="muted small">Origen: {e(x["source"])} · '
            f'<a href="#rec-{e(x["record_id"])}">registro {e(x["record_id"][:8])}</a> · evidencias observadas: '
            f'{x["observed_support"]}</p><p>Evidencias: {evs}</p><p>Incógnitas: {incs}</p>'
            f'<details><summary>Límites ({len(x["limits"])})</summary><ul>{lims}</ul></details></article>')
    arts = "".join(
        f'<tr id="{art_ids[a["subject"]]}"><td>{e(a["subject"][:80])}</td><td>{e(IDENTITY_LABEL.get(a["identity"], a["identity"]))}'
        f'<br><code>{e(a["content_sha256"] or "—")}</code></td><td>{"desconocido" if a["size"] is None else e(str(a["size"]))}</td>'
        f'<td>{e(a["format"])}</td><td>{e(a["version"] or "—")}</td><td>{e(a["platform"] or "—")}</td>'
        f'<td>{e(a["provenance"])}<br><span class="muted">{e(a["path"])}</span></td>'
        f'<td>{e(", ".join(t["name"] + " " + t.get("version", "") for t in a["tools"]) or "—")}</td>'
        f'<td>{e(" ".join(str(a["environment"].get(k, "")) for k in ("os", "os_release", "machine", "python", "eolfi")))}</td></tr>'
        for a in r["artifacts"])
    recs = []
    for rec in r["records"]:
        p = rec["payload"]
        st = p.get("status", "")
        tools = ", ".join(f'{t["name"]} {t.get("version", "")}'.strip() + (f' ({t["status"]})' if t.get("status") else "")
                          for t in p.get("tools", [])) or "—"
        env = p.get("environment") or {}
        errors = "".join(f"<li>{e(x)}</li>" for x in p.get("errors", []))
        dur = (f'{p["finished_at"] - p["started_at"]:.1f} s' if isinstance(p.get("finished_at"), (int, float))
               and isinstance(p.get("started_at"), (int, float)) else "—")
        body = {k: v for k, v in p.items() if k not in {"tools", "environment", "errors", "evidence_ids", "artifacts"}}
        recs.append(
            f'<article id="rec-{e(rec["record_id"])}"><p><strong>{e(rec["kind"])}</strong> '
            + (f'· flujo <strong>{e(p["flow"])}</strong> ' if p.get("flow") else "")
            + (f'<span class="badge {e(st)}">{e(STATUS_LABEL.get(st, st))}</span>' if st else "")
            + f'<span class="muted">{e(_iso(rec["created_at"]))} · duración {e(dur)}</span></p>'
            f'<p>Artefactos: {", ".join(art_link(s) for s in p.get("artifacts", [])) or "—"}</p>'
            f'<p>Herramientas: {e(tools)}</p><p class="muted">Entorno: {e(" ".join(str(v) for v in env.values()))}</p>'
            + (f'<p>Errores / resultados parciales:</p><ul>{errors}</ul>' if errors else "")
            + f'<p>Evidencias: {", ".join(ev_link(x) for x in p.get("evidence_ids", [])[:200]) or "—"}</p>'
            f'<details><summary>Datos del registro</summary><pre>{e(json.dumps(body, ensure_ascii=False, indent=2)[:20000])}</pre>'
            f'</details></article>')
    evs = "".join(
        f'<article id="ev-{e(x["evidence_id"])}"><p><code>{e(x["evidence_id"])}</code> '
        f'<span class="badge">{e(AUTHORITY_LABEL.get(x["authority"], x["authority"]))}</span>'
        f'<span class="badge">confianza {e(x["confidence"])}</span>'
        + ('<span class="badge partial">importada</span>' if x["evidence_id"] in set(r["imported"]) else "")
        + f'</p><p>{e(x["operation"])} · {e(x["provider"])} {e(x["provider_version"])} · objetivo {art_link(x["subject"])}'
        f' · {e(_iso(x["created_at"]))}</p><p class="muted">Límites: {e(str(x.get("limitations") or "—")[:600])}</p>'
        f'<p class="muted">Entorno: {e(str(x.get("environment") or "—"))}</p>'
        f'<details><summary>Resultado</summary><pre>{e(json.dumps(_loads(x["result"]), ensure_ascii=False, indent=2)[:4000])}</pre></details></article>'
        for x in r["evidence"])
    incs = "".join(
        f'<article id="inc-{e(i["incognita_id"])}"><p><span class="badge {e(i["status"])}">{e(i["status"])}</span>'
        f'<span class="badge">{e(str(i.get("severity") or "info"))}</span>{e(i["question"])}</p>'
        f'<p class="muted">Objetivo {art_link(i["subject"])} · a favor: '
        f'{", ".join(ev_link(x) for x in _loads(i.get("evidence_for") or "[]")) or "—"} · en contra: '
        f'{", ".join(ev_link(x) for x in _loads(i.get("evidence_against") or "[]")) or "—"}</p></article>'
        for i in r["incognitas"])
    imports = "".join(f'<li>Importado de {e(x["source_name"])} (paquete sha256 <code>{e(x["package_sha256"])}</code>) el '
                      f'{e(_iso(x["imported_at"]))}: autoridad declarada por el paquete.</li>' for x in r["imports"])
    statuses = " ".join(f'<span class="badge {e(k)}">{e(STATUS_LABEL.get(k, k))}: {v}</span>' for k, v in r["statuses"].items())
    limits = "".join(f"<li>{e(x)}</li>" for x in r["limits"])
    env = r["environment"]
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>Caso de Eolfi: {e(c["name"])}</title>
<style>{_CSS}</style>
</head>
<body>
<nav aria-label="Secciones"><a href="#resumen">Resumen</a><a href="#conclusiones">Conclusiones</a><a href="#limites">Límites</a><a href="#artefactos">Artefactos</a><a href="#registros">Registros</a><a href="#evidencias">Evidencias</a><a href="#incognitas">Incógnitas</a></nav>
<main>
<h1>Caso: {e(c["name"])}</h1>
<p class="muted">Caso <code>{e(c["case_id"])}</code> · creado {e(_iso(c["created_at"]))} · actualizado {e(_iso(c["updated_at"]))}
 · informe generado {e(_iso(r["generated_at"]))} con Eolfi {e(env.get("eolfi", "?"))} en {e(env.get("os", ""))} {e(env.get("machine", ""))}</p>
<p>{e(c["description"])}</p>
<section id="resumen"><h2>Resumen</h2>
<p>{len(r["artifacts"])} artefactos · {len(r["records"])} registros · {len(r["evidence"])} evidencias ·
{len(r["incognitas"])} incógnitas ({r["open_incognitas"]} abiertas) · {len(r["conclusions"])} conclusiones</p>
<p>Estado de los registros: {statuses or '<span class="muted">sin registros</span>'}</p>
{f"<ul>{imports}</ul>" if imports else ""}
<p class="muted">Las conclusiones conservan el estado con que se registraron. «Observada» exige evidencia del artefacto
o de una reproducción controlada; «Derivada», alguna evidencia; «Hipótesis» no es un hecho.</p></section>
<section id="conclusiones"><h2>Conclusiones ({len(r["conclusions"])})</h2>{"".join(concl) or '<p class="muted">Sin conclusiones registradas.</p>'}</section>
<section id="limites"><h2>Límites e incógnitas pendientes</h2><ul>{limits}</ul></section>
<section id="artefactos"><h2>Artefactos ({len(r["artifacts"])})</h2>
<table><thead><tr><th scope="col">Subject</th><th scope="col">Identidad</th><th scope="col">Tamaño</th><th scope="col">Formato</th>
<th scope="col">Versión</th><th scope="col">Plataforma</th><th scope="col">Procedencia</th><th scope="col">Herramientas</th><th scope="col">Entorno</th></tr></thead>
<tbody>{arts}</tbody></table></section>
<section id="registros"><h2>Registros ({len(r["records"])})</h2>{"".join(recs) or '<p class="muted">Sin registros.</p>'}</section>
<section id="evidencias"><h2>Evidencias ({len(r["evidence"])})</h2>{evs or '<p class="muted">Sin evidencias.</p>'}</section>
<section id="incognitas"><h2>Incógnitas ({len(r["incognitas"])})</h2>{incs or '<p class="muted">Sin incógnitas.</p>'}</section>
</main>
</body>
</html>
"""
