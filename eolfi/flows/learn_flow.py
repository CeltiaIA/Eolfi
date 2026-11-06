"""Flujos de aprendizaje: páginas web y repositorios -> evidencias + resumen."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Callable

from eolfi.core.cases import case_run
from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Incognita, Status
from eolfi.flows.triage_flow import environment_string, record_findings

WEB = SimpleNamespace(name="eolfi.web", version="0.1.0")
REPO = SimpleNamespace(name="eolfi.repo", version="0.1.0")


def run_web(source: str, store: EvidenceStore, *, max_assets: int = 40, cross_origin: bool = False,
            ignore_robots: bool = False, save_dir: str | None = None,
            progress: Callable[[str], None] | None = None, case_id: str | None = None,
            provenance: str = "") -> dict[str, Any]:
    params = {"source": source, "max_assets": max_assets, "cross_origin": cross_origin,
              "ignore_robots": ignore_robots}
    with case_run(store, case_id, "web", params, provenance or f"fuente web indicada por el operador: {source}") as run:
        rep = _run_web(source, store, max_assets=max_assets, cross_origin=cross_origin,
                       ignore_robots=ignore_robots, save_dir=save_dir, progress=progress)
        _finish(run, rep)
        return rep


def _finish(run, rep: dict[str, Any]) -> None:
    """Asocia el objetivo al caso y registra el resultado del flujo (si hay caso)."""
    if run.active:
        run.associate(rep["subject"])
        run.finish(status="done", evidence_ids=rep["evidence_ids"], result={"summary": rep["summary"]})
        rep["case_record"] = run.record_id


def _run_web(source: str, store: EvidenceStore, *, max_assets: int, cross_origin: bool, ignore_robots: bool,
             save_dir: str | None, progress: Callable[[str], None] | None) -> dict[str, Any]:
    from eolfi.sites.fetch import Fetcher
    from eolfi.sites.webpage import analyze_web

    fetcher = Fetcher(respect_robots=not ignore_robots)
    subject, findings = analyze_web(source, fetcher=fetcher, max_assets=max_assets, cross_origin=cross_origin,
                                    save_dir=save_dir, progress=progress)
    ids = record_findings(store, subject, WEB, findings, environment_string())
    by = {f["operation"]: f["result"] for f in findings}
    for issue in by.get("web_accessibility", {}).get("issues", []):
        store.add_incognita(Incognita(subject=subject, question=f"Accesibilidad: {issue}", severity="low"))
    missing = by.get("web_headers", {}).get("missing_security", [])
    if missing:
        store.add_incognita(Incognita(subject=subject, severity="info",
                                      question=f"Cabeceras de seguridad ausentes: {', '.join(missing)}."))
    bp = by.get("web_blueprint", {})
    return {
        "subject": subject,
        "evidence_ids": ids,
        "summary": {
            "title": by.get("web_structure", {}).get("title"),
            "stack": bp.get("stack"),
            "suggested_scaffold": bp.get("suggested_scaffold"),
            "page_skeleton": bp.get("page_skeleton", [])[:12],
            "design_tokens": bp.get("design_tokens"),
            "component_candidates": bp.get("component_candidates", [])[:8],
            "learning_notes": bp.get("learning_notes"),
            "accessibility_issues": len(by.get("web_accessibility", {}).get("issues", [])),
            "saved_files": len(by.get("web_assets", {}).get("saved_files", [])),
        },
        "open_incognitas": len(store.list_incognitas(Status.OPEN, subject=subject)),
    }


def run_repo(source: str, store: EvidenceStore, *, workdir: str = "samples/repos",
             progress: Callable[[str], None] | None = None, case_id: str | None = None,
             provenance: str = "") -> dict[str, Any]:
    with case_run(store, case_id, "repo", {"source": source},
                  provenance or f"repositorio indicado por el operador: {source}") as run:
        rep = _run_repo(source, store, workdir=workdir, progress=progress)
        _finish(run, rep)
        return rep


def _run_repo(source: str, store: EvidenceStore, *, workdir: str,
              progress: Callable[[str], None] | None) -> dict[str, Any]:
    from eolfi.sites.repo import analyze_repo

    subject, findings = analyze_repo(source, workdir=workdir, progress=progress)
    ids = record_findings(store, subject, REPO, findings, environment_string())
    by = {f["operation"]: f["result"] for f in findings}
    for f in by.get("repo_hygiene", {}).get("possibly_sensitive_files", []):
        store.add_incognita(Incognita(subject=subject, severity="medium",
                                      question=f"Posible archivo sensible versionado: {f} (revisar sin publicarlo)."))
    if not by.get("repo_docs", {}).get("license"):
        store.add_incognita(Incognita(subject=subject, severity="info",
                                      question="Sin licencia detectada: no reutilices su código sin permiso."))
    bp = by.get("repo_blueprint", {})
    return {
        "subject": subject,
        "evidence_ids": ids,
        "summary": {
            "languages": [(l["language"], l["lines"]) for l in by.get("repo_languages", {}).get("code", [])[:6]],
            "stack": bp.get("stack"),
            "suggested_scaffold": bp.get("suggested_scaffold"),
            "package_manager": bp.get("package_manager"),
            "how_to_run": bp.get("how_to_run"),
            "layout": bp.get("layout"),
            "conventions": bp.get("conventions"),
            "license": by.get("repo_docs", {}).get("license"),
        },
        "open_incognitas": len(store.list_incognitas(Status.OPEN, subject=subject)),
    }


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)
