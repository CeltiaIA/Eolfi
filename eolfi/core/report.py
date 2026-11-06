"""Informes de un objetivo en HTML (autocontenido) o Markdown, con umbral para CI (Fase E).

    python -m eolfi report <objetivo> --format html --out informe.html
    python -m eolfi report <objetivo> --format md --fail-on high     # código 1 si hay incógnitas ≥ high

El HTML no lleva scripts ni recursos externos (se puede abrir sin conexión y adjuntar) y todo el texto
procedente del objetivo se escapa: los binarios y las webs analizadas son hostiles.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Any

from eolfi import __version__
from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Status

SEVERITY = ("info", "low", "medium", "high", "critical")


def _rank(sev: Any) -> int:
    return SEVERITY.index(sev) if sev in SEVERITY else 0


def _findings(by_op: dict[str, Any]) -> list[str]:
    """Hallazgos de seguridad repartidos por las evidencias (manifiesto Android, ZIP, mitigaciones…)."""
    out: list[str] = []
    for op in ("android_manifest", "archive_inventory"):
        r = by_op.get(op)
        man = r.get("manifest") if op == "archive_inventory" and isinstance(r, dict) else r
        if isinstance(man, dict):
            out += [str(f) for f in man.get("security_findings", []) if isinstance(f, str)]
        if op == "archive_inventory" and isinstance(r, dict):
            out += [str(f) for f in (r.get("zip_anomalies") or {}).get("findings", []) if isinstance(f, str)]
    sig = by_op.get("pe_signature")
    if isinstance(sig, dict) and sig.get("present"):
        signer = (sig.get("signer") or {}).get("subject")
        out.append(f"Firma Authenticode de {signer or 'firmante desconocido'}: "
                   + ("el resumen coincide con el archivo" if sig.get("digest_matches") else
                      "EL RESUMEN NO COINCIDE (archivo modificado después de firmarlo)" if sig.get("digest_matches") is False
                      else "resumen no comprobado"))
    elif isinstance(sig, dict):
        out.append("Sin firma Authenticode incrustada")
    inv = by_op.get("archive_inventory")
    if isinstance(inv, dict):
        ios = inv.get("ios")
        if isinstance(ios, dict):
            out += [str(f) for f in ios.get("findings", []) if isinstance(f, str)]
        apk = inv.get("signature")
        if isinstance(apk, dict) and apk.get("schemes"):
            out.append(f"Firma APK: esquemas {', '.join(apk['schemes'])}; certificado(s) "
                       + ", ".join(x[:16] + "…" for x in apk.get("certificate_sha256", [])[:3]))
    net = by_op.get("dotnet_metadata")
    if isinstance(net, dict) and net.get("obfuscation"):
        out.append(f".NET con posible ofuscación: {', '.join(map(str, net['obfuscation'][:4]))}")
    for op in ("pe_security", "elf_security"):
        sec = by_op.get(op)
        if isinstance(sec, dict):
            missing = [k for k in ("aslr", "dep_nx", "pie", "nx", "relro", "canary") if sec.get(k) is False]
            if missing:
                out.append(f"Mitigaciones ausentes ({op.split('_')[0].upper()}): {', '.join(missing)}")
    return list(dict.fromkeys(out))


def build_report(store: EvidenceStore, subject: str, names: list[str] | None = None) -> dict[str, Any]:
    from eolfi.flows.triage_flow import summarize

    evs = store.list_evidence(subject)
    if not evs:
        raise ValueError(f"sin evidencias para {subject}")
    by_op: dict[str, Any] = {}
    for e in evs:
        try:
            by_op[e["operation"]] = json.loads(e["result"])
        except (TypeError, ValueError):
            continue
    incs = store.list_incognitas(subject=subject)
    open_incs = sorted((i for i in incs if i["status"] != Status.RESOLVED.value),
                       key=lambda i: -_rank(i.get("severity")))
    return {
        "subject": subject,
        "names": names or [],
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "eolfi": __version__,
        "summary": summarize(store, subject),
        "findings": _findings(by_op),
        "open_incognitas": [{"severity": i.get("severity") or "info", "question": i["question"]} for i in open_incs],
        "resolved_incognitas": sum(1 for i in incs if i["status"] == Status.RESOLVED.value),
        "evidence": [{"operation": e["operation"], "provider": f"{e['provider']} {e['provider_version']}",
                      "confidence": e["confidence"], "authority": e["authority"],
                      "limitations": e.get("limitations") or ""} for e in evs],
    }


def fails(report: dict[str, Any], level: str | None) -> bool:
    """¿Hay incógnitas abiertas de gravedad ≥ level? (para --fail-on en CI)."""
    if not level:
        return False
    return any(_rank(i["severity"]) >= _rank(level) for i in report["open_incognitas"])


def _value(v: Any) -> str:
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)[:400]
    return str(v)


def render_markdown(r: dict[str, Any]) -> str:
    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    title = r["names"][0] if r["names"] else r["subject"]
    lines = [f"# Informe de Eolfi: {esc(title)}", "", f"- Objetivo: `{r['subject']}`",
             f"- Generado: {r['generated']} con Eolfi {r['eolfi']}", "", "## Resumen", ""]
    lines += [f"- **{esc(k)}**: {esc(_value(v))}" for k, v in r["summary"].items()] or ["- (sin resumen)"]
    lines += ["", "## Hallazgos de seguridad", ""]
    lines += [f"- {esc(f)}" for f in r["findings"]] or ["- Ninguno detectado."]
    lines += ["", f"## Incógnitas abiertas ({len(r['open_incognitas'])}; resueltas: {r['resolved_incognitas']})", ""]
    lines += [f"- **{i['severity']}** · {esc(i['question'])}" for i in r["open_incognitas"]] or ["- Ninguna."]
    lines += ["", f"## Evidencias ({len(r['evidence'])})", "", "| Operación | Proveedor | Confianza | Autoridad |",
              "|---|---|---|---|"]
    lines += [f"| {esc(e['operation'])} | {esc(e['provider'])} | {e['confidence']} | {e['authority']} |" for e in r["evidence"]]
    return "\n".join(lines) + "\n"


_CSS = """
body{font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;margin:2rem auto;max-width:60rem;padding:0 1rem;color:#1d232b;background:#fff}
h1{font-size:1.5rem}h2{font-size:1.15rem;margin-top:2rem;border-bottom:1px solid #d8dde3;padding-bottom:.25rem}
code{background:#f1f3f6;padding:0 .3rem;border-radius:4px;overflow-wrap:anywhere}
table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{text-align:left;padding:.35rem .5rem;border-bottom:1px solid #e3e7ec;vertical-align:top}
.sev{display:inline-block;min-width:4.5rem;font-weight:600}.critical,.high{color:#a4161a}.medium{color:#8a5a00}.low,.info{color:#3d4a57}
dl{display:grid;grid-template-columns:max-content 1fr;gap:.25rem 1rem}dt{font-weight:600}dd{margin:0;overflow-wrap:anywhere}
@media (prefers-color-scheme:dark){body{background:#12141a;color:#e8eaf0}code{background:#1e222b}th,td{border-color:#2a2f3a}
.critical,.high{color:#ff8a8a}.medium{color:#f2c46d}.low,.info{color:#a8b3c2}}
"""


def render_html(r: dict[str, Any]) -> str:
    e = html.escape
    title = r["names"][0] if r["names"] else r["subject"]
    summary = "".join(f"<dt>{e(str(k))}</dt><dd>{e(_value(v))}</dd>" for k, v in r["summary"].items())
    findings = "".join(f"<li>{e(f)}</li>" for f in r["findings"]) or "<li>Ninguno detectado.</li>"
    incs = "".join(f'<li><span class="sev {e(i["severity"])}">{e(i["severity"])}</span> {e(i["question"])}</li>'
                   for i in r["open_incognitas"]) or "<li>Ninguna.</li>"
    rows = "".join(f"<tr><td>{e(x['operation'])}</td><td>{e(x['provider'])}</td><td>{e(x['confidence'])}</td>"
                   f"<td>{e(x['authority'])}</td><td>{e(x['limitations'][:300])}</td></tr>" for x in r["evidence"])
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>Informe de Eolfi: {e(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<main>
<h1>Informe de Eolfi: {e(title)}</h1>
<p>Objetivo <code>{e(r["subject"])}</code> · generado {e(r["generated"])} con Eolfi {e(r["eolfi"])}</p>
<h2>Resumen</h2>
<dl>{summary or "<dt>—</dt><dd>sin resumen</dd>"}</dl>
<h2>Hallazgos de seguridad</h2>
<ul>{findings}</ul>
<h2>Incógnitas abiertas ({len(r["open_incognitas"])}; resueltas: {r["resolved_incognitas"]})</h2>
<ul>{incs}</ul>
<h2>Evidencias ({len(r["evidence"])})</h2>
<table>
<thead><tr><th scope="col">Operación</th><th scope="col">Proveedor</th><th scope="col">Confianza</th><th scope="col">Autoridad</th><th scope="col">Límites</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</main>
</body>
</html>
"""
