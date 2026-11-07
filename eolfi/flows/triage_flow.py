"""Triaje en un solo paso: encadena proveedores y registra evidencias.

Formato/hash -> estructura PE/ELF -> cadenas -> herramientas externas (si
están) -> resumen, devolviendo un informe con evidencias y huecos
(incógnitas). Un proveedor que falla no tumba el triaje: su fallo se
registra como incógnita y el resto sigue.
"""
from __future__ import annotations

import os
import re
import sys
import platform
import traceback
from pathlib import Path
from typing import Any

from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Authority, Confidence, Evidence, Incognita, Status
from eolfi.providers.base import Provider
from eolfi.providers.binfmt import BinaryFormatProvider
from eolfi.providers.dex import AndroidJavaProvider
from eolfi.providers.external import CapaProvider, GhidraProvider, RizinProvider
from eolfi.providers.strings import StringsProvider
from eolfi.providers.triage import FileTriageProvider, sha256_file

# Proveedores locales (stdlib): rápidos, deterministas; son lo que ataca el fuzzer.
LOCAL_PROVIDERS: list[Provider] = [
    FileTriageProvider(),
    BinaryFormatProvider(),
    AndroidJavaProvider(),
    StringsProvider(),
]
# Triaje por defecto: locales + herramientas externas ligeras (segundos).
DEFAULT_PROVIDERS: list[Provider] = LOCAL_PROVIDERS + [CapaProvider(), RizinProvider()]
# Triaje profundo: añade Ghidra headless (minutos por binario).
DEEP_PROVIDERS: list[Provider] = DEFAULT_PROVIDERS + [GhidraProvider()]
ALL_PROVIDERS = DEEP_PROVIDERS


def environment_string() -> str:
    return f"{platform.system()} {platform.release()} py{platform.python_version()}"


def record_findings(
    store: EvidenceStore, subject: str, prov: Provider, findings: list[dict[str, Any]], env: str
) -> list[str]:
    ids = []
    ident = prov.tool_identity() if hasattr(prov, "tool_identity") else None
    if ident:   # herramienta externa: ruta y huella del ejecutable junto al entorno
        env = f"{env} | {prov.name} {ident['path']} sha256:{ident['sha256'][:16]}"
    for finding in findings:
        ev = Evidence(
            subject=subject,
            provider=prov.name,
            provider_version=getattr(prov, "version", "0.0.0"),
            operation=finding["operation"],
            params=finding.get("params", {}),
            result=finding["result"],
            authority=Authority(finding.get("authority", "analyst_inference")),
            confidence=Confidence(finding.get("confidence", "low")),
            limitations=finding.get("limitations", ""),
            environment=env,
        )
        eid, _ = store.add_evidence(ev)
        ids.append(eid)
    return ids


def _format_issues(op: str, res: Any) -> list[tuple[str, str]]:
    """Hallazgos de los formatos nuevos (Fase E) que merecen una incógnita: firma, ofuscación, iOS."""
    if not isinstance(res, dict):
        return []
    out: list[tuple[str, str]] = []
    if op == "pe_signature" and res.get("present"):
        if res.get("digest_matches") is False:
            out.append(("Windows: la firma Authenticode no coincide con el archivo (modificado después de firmarlo)",
                        "high"))
        if res.get("error"):
            out.append((f"Windows: firma Authenticode ilegible ({str(res['error'])[:120]})", "medium"))
    elif op == "dotnet_metadata" and res.get("obfuscation"):
        out.append((f".NET: posible ofuscación ({', '.join(res['obfuscation'][:4])})", "low"))
    elif op == "archive_inventory":
        for issue in (res.get("ios") or {}).get("findings", []) if isinstance(res.get("ios"), dict) else []:
            out.append((f"iOS: {issue}", "medium"))
    return out


def _close(store: EvidenceStore, subject: str, question: str) -> None:
    iid = Incognita(subject=subject, question=question).incognita_id
    store.resolve_incognita(iid)


def _run_isolated(prov: Provider, path: Path, timeout: float = 180.0) -> list[dict[str, Any]]:
    """Proveedor local en un subproceso: un archivo hostil que agote memoria o tiempo no tumba el servidor."""
    import json as _json
    import subprocess as _sp

    from eolfi.providers.external import run_tree

    cls = type(prov)
    root = str(Path(__file__).resolve().parents[2])
    secret = re.compile(r"(API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|COOKIE|PRIVATE[_-]?KEY|AUTH)", re.I)
    env = {k: v for k, v in os.environ.items() if not secret.search(k)}   # el analizador no necesita secretos
    env.update(PYTHONPATH=root + os.pathsep + os.environ.get("PYTHONPATH", ""), PYTHONIOENCODING="utf-8")
    try:
        p = run_tree([sys.executable, "-m", "eolfi.providers.isolated", cls.__module__, cls.__qualname__, str(path)],
                     timeout, env=env)
    except _sp.TimeoutExpired:
        raise RuntimeError(f"tardó más de {int(timeout)} s (proceso aislado detenido)") from None
    if p.returncode != 0:
        tail = (p.stderr or "").strip().splitlines()[-1:] or [f"código {p.returncode}"]
        raise RuntimeError(f"el proceso aislado falló: {tail[0][:300]}")
    data = _json.loads(p.stdout)
    prov.version = data.get("version", getattr(prov, "version", "?"))
    return data["findings"]


def run_triage(
    target: str,
    store: EvidenceStore,
    providers: list[Provider] | None = None,
    *,
    isolate: bool = False,
    case_id: str | None = None,
    provenance: str = "",
) -> dict[str, Any]:
    """isolate=True: los proveedores locales (stdlib) corren en un subproceso con plazo y, en Linux/macOS,
    límite de memoria. Las herramientas externas ya son procesos aparte.

    case_id: registra el artefacto (hash, tamaño, formato, procedencia, herramientas) y un registro tipado
    «analysis» del resultado en ese caso; si el triaje falla, el registro queda con estado error."""
    from eolfi.core.cases import case_run

    path = Path(target)
    if not path.is_file():
        raise FileNotFoundError(target)
    names = [p.name for p in (providers if providers is not None else DEFAULT_PROVIDERS)]
    with case_run(store, case_id, "triage", {"target": str(path), "providers": names, "isolate": isolate},
                  provenance or f"archivo local declarado por el operador: {path}") as run:
        rep = _run_triage(path, store, providers, isolate=isolate)
        if run.active:
            run.associate(rep["subject"], path=str(path.resolve()))
            tools = [{"name": n, "version": "", "status": "skipped"} for n in rep["providers_skipped"]]
            tools += [{"name": n, "version": "", "status": "failed"} for n in rep["providers_failed"]]
            from eolfi.core.cases import tools_for

            tools = [t | {"status": "ran"} for t in tools_for(store, rep["subject"], rep["evidence_ids"])] + tools
            run.finish(status="partial" if rep["providers_failed"] else "done", evidence_ids=rep["evidence_ids"],
                       tools=tools, result={"summary": rep["summary"], "providers_run": rep["providers_run"],
                                            "providers_skipped": rep["providers_skipped"],
                                            "providers_failed": rep["providers_failed"]},
                       errors=[f"proveedor {n} falló: {rep['provider_errors'].get(n, '?')}" for n in rep["providers_failed"]])
            rep["case_record"] = run.record_id
        return rep


def _run_triage(path: Path, store: EvidenceStore, providers: list[Provider] | None, *, isolate: bool) -> dict[str, Any]:
    subject = sha256_file(path)
    env = environment_string()
    providers = providers if providers is not None else DEFAULT_PROVIDERS

    recorded: list[str] = []
    ran: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    errors: dict[str, str] = {}
    import copy

    for shared in providers:
        # Los proveedores son instancias globales con estado (self.version, rutas resueltas): con dos
        # triajes en paralelo, una evidencia podía quedar con la versión de otra ejecución (M21).
        prov = copy.copy(shared)
        if not prov.available():
            skipped.append(prov.name)
            store.add_incognita(
                Incognita(
                    subject=subject,
                    question=f"Proveedor '{prov.name}' no disponible; cobertura parcial.",
                    severity="info",
                )
            )
            continue
        # Si ahora está disponible, la incógnita de «no disponible» de ejecuciones anteriores se cierra (B15).
        _close(store, subject, f"Proveedor '{prov.name}' no disponible; cobertura parcial.")
        try:
            if isolate and type(shared) in {type(x) for x in LOCAL_PROVIDERS}:
                findings = _run_isolated(prov, path)
            else:
                from eolfi.providers.binfmt import parse_budget

                size = path.stat().st_size
                with parse_budget(max_bytes=64 * size + 256 * 1024 * 1024, seconds=120):
                    findings = prov.run(str(path))
        except Exception as exc:  # noqa: BLE001 — un proveedor no tumba el triaje
            failed.append(prov.name)
            errors[prov.name] = f"{type(exc).__name__}: {str(exc)[:300]}"
            # Pregunta estable (sin el texto del error, que cambia en cada ejecución: antes se duplicaba);
            # el detalle va en el registro.
            store.add_incognita(
                Incognita(
                    subject=subject,
                    question=f"Proveedor '{prov.name}' falló ({type(exc).__name__}): sus hallazgos faltan.",
                    severity="medium",
                )
            )
            print(f"eolfi: {prov.name} falló: {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
            if os.environ.get("EOLFI_DEBUG"):
                traceback.print_exc()
            continue
        ran.append(prov.name)
        for inc in store.list_incognitas(Status.OPEN, subject=subject):   # funcionó: se cierran sus fallos
            if inc["question"].startswith(f"Proveedor '{prov.name}' falló"):
                store.resolve_incognita(inc["incognita_id"])
        recorded.extend(record_findings(store, subject, prov, findings, env))
        for f in findings:
            res = f.get("result")
            man = res.get("manifest") if f["operation"] == "archive_inventory" and isinstance(res, dict) else (
                res if f["operation"] == "android_manifest" else None)
            for issue in (man or {}).get("security_findings", []) if isinstance(man, dict) else []:
                store.add_incognita(Incognita(subject=subject, question=f"Android: {issue}", severity="medium"))
            for issue, sev in _format_issues(f["operation"], res):
                store.add_incognita(Incognita(subject=subject, question=issue, severity=sev))

    return {
        "subject": subject,
        "target": str(path),
        "providers_run": ran,
        "providers_skipped": skipped,
        "providers_failed": failed,
        "provider_errors": errors,
        "evidence_ids": recorded,
        "summary": summarize(store, subject),
        "open_incognitas": len(store.list_incognitas(Status.OPEN, subject=subject)),
    }


def summarize(store: EvidenceStore, subject: str) -> dict[str, Any]:
    """Ficha breve del objetivo a partir de las evidencias ya registradas."""
    import json

    by_op: dict[str, Any] = {}
    for ev in store.list_evidence(subject):
        try:
            by_op[ev["operation"]] = json.loads(ev["result"])
        except (TypeError, ValueError):
            continue
    s: dict[str, Any] = {}
    try:
        _summary_fields(by_op, s)
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        # Una evidencia importada incompleta ya no tumba los triajes siguientes (M38).
        s["summary_error"] = f"evidencia con forma inesperada: {type(exc).__name__}: {exc}"
    return s


def _summary_fields(by_op: dict[str, Any], s: dict[str, Any]) -> None:
    if "detect_format" in by_op:
        s["format"] = by_op["detect_format"].get("format")
    if "macho_headers" in by_op and by_op["macho_headers"]["slices"]:
        s["machine"] = ", ".join(x["cpu"] for x in by_op["macho_headers"]["slices"])
        s["platform"] = by_op["macho_headers"]["slices"][0].get("platform")
    if "archive_inventory" in by_op:
        inv = by_op["archive_inventory"]
        s["package_kind"] = inv["kind"]
        s["frameworks"] = inv["frameworks"]
        man = inv.get("manifest") or {}
        if man.get("package"):
            s["android"] = {k: man.get(k) for k in ("package", "version_name", "min_sdk", "target_sdk", "launcher")}
            s["android"]["permissions"] = len(man.get("permissions", []))
            s["android"]["dangerous_permissions"] = man.get("dangerous_permissions")
    if "dex_structure" in by_op:
        s["dex_classes"] = by_op["dex_structure"]["counts"]["classes"]
    for kind in ("pe", "elf"):
        h = by_op.get(f"{kind}_headers")
        if h:
            s["machine"] = h.get("machine")
            s["entry_point"] = h.get("entry_point_rva", h.get("entry_point"))
        sec = by_op.get(f"{kind}_security")
        if sec:
            s["mitigations"] = sec
    if "pe_imports" in by_op:
        s["imported_dlls"] = sorted(by_op["pe_imports"]["dlls"])
    if "elf_dynamic" in by_op:
        s["needed_libs"] = by_op["elf_dynamic"]["needed"]
    if "packing_signals" in by_op:
        s["likely_packed"] = by_op["packing_signals"]["likely_packed"]
    if "detect_capabilities" in by_op:
        s["capabilities"] = by_op["detect_capabilities"].get("rules", [])[:20]
