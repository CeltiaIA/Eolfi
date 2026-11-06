"""Comparación entre dos objetivos ya analizados (p. ej. v1 y v2 de un binario).

Trabaja sobre las evidencias registradas, no sobre los archivos: compara cada
operación que exista en ambos y explica qué cambió (importaciones, secciones,
mitigaciones, funciones, capacidades, pila web, dependencias…). El resultado
se guarda como evidencia `version_diff`.
"""
from __future__ import annotations

import json
from typing import Any

from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Authority, Confidence, Evidence
from eolfi.flows.triage_flow import environment_string

PROVIDER, VERSION = "eolfi.compare", "0.1.0"


def _latest(store: EvidenceStore, subject: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for ev in store.list_evidence(subject):
        out[ev["operation"]] = json.loads(ev["result"])
    return out


def _hashable(x: Any) -> Any:
    return x if isinstance(x, (str, int, float, bool, type(None))) else json.dumps(x, sort_keys=True, ensure_ascii=False)


def _set_diff(a, b, limit: int = 200) -> dict[str, Any] | None:
    # Listas con dicts o listas dentro (resultados raros) no deben lanzar TypeError.
    sa = {_hashable(x) for x in (a or [])} if not isinstance(a, dict) else set(a)
    sb = {_hashable(x) for x in (b or [])} if not isinstance(b, dict) else set(b)
    if sa == sb:
        return None
    return {"added": _sorted_any(sb - sa)[:limit], "removed": _sorted_any(sa - sb)[:limit],
            "added_count": len(sb - sa), "removed_count": len(sa - sb)}


def _sorted_any(xs) -> list:
    """sorted() que no falla con tipos mezclados (1 y "1", None…; M39)."""
    return sorted(xs, key=lambda x: (type(x).__name__, str(x)))


def _clip(v: Any, limit: int = 50) -> Any:
    """Antes y después de un cambio, sin copiar listas o textos enteros al resultado."""
    if isinstance(v, list) and len(v) > limit:
        return v[:limit] + [f"… {len(v) - limit} más"]
    if isinstance(v, str) and len(v) > 2000:
        return v[:2000] + "…"
    if isinstance(v, dict) and len(v) > limit:
        return {k: v[k] for k in list(v)[:limit]} | {"…": f"{len(v) - limit} claves más"}
    return v


def _dict_diff(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any] | None:
    keys = _sorted_any(set(a) | set(b))
    changed = {k: {"before": _clip(a.get(k)), "after": _clip(b.get(k))} for k in keys if a.get(k) != b.get(k)}
    return changed or None


def _sections(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> dict[str, Any] | None:
    ma = {str(s.get("name")): s for s in a or [] if isinstance(s, dict)}
    mb = {str(s.get("name")): s for s in b or [] if isinstance(s, dict)}
    out: dict[str, Any] = {}
    names = _set_diff(ma, mb)
    if names:
        out["names"] = names
    changes = []
    for n in sorted(set(ma) & set(mb)):
        sa, sb = ma[n], mb[n]
        size_a = sa.get("raw_size", sa.get("size", 0))
        size_b = sb.get("raw_size", sb.get("size", 0))
        d_ent = round((sb.get("entropy") or 0) - (sa.get("entropy") or 0), 3)
        if size_a != size_b or abs(d_ent) >= 0.3 or sa.get("flags") != sb.get("flags"):
            changes.append({"section": n, "size": [size_a, size_b], "entropy_delta": d_ent,
                            "flags": [sa.get("flags"), sb.get("flags")]})
    if changes:
        out["changed"] = changes[:60]
    return out or None


def _imports(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any] | None:
    da, db = a.get("dlls", {}), b.get("dlls", {})
    out: dict[str, Any] = {}
    dl = _set_diff(da, db)
    if dl:
        out["dlls"] = dl
    funcs = {}
    for dll in sorted(set(da) & set(db)):
        d = _set_diff(da[dll], db[dll], 100)
        if d:
            funcs[dll] = d
    if funcs:
        out["functions"] = funcs
    return out or None


def _functions(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any] | None:
    fa = {f.get("name"): f.get("size") for f in a.get("functions", []) if isinstance(f, dict)}
    fb = {f.get("name"): f.get("size") for f in b.get("functions", []) if isinstance(f, dict)}
    out: dict[str, Any] = {"count": [a.get("count"), b.get("count")]}
    names = _set_diff(fa, fb, 150)
    if names:
        out["names"] = names
    resized = [{"name": n, "size": [fa[n], fb[n]]} for n in sorted(set(fa) & set(fb)) if fa[n] != fb[n]]
    if resized:
        out["resized"] = sorted(resized, key=lambda x: -abs((x["size"][1] or 0) - (x["size"][0] or 0)))[:80]
    return out if len(out) > 1 or a.get("count") != b.get("count") else None


def _techs(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any] | None:
    return _set_diff([t.get("name") for t in a.get("technologies", []) if isinstance(t, dict)],
                     [t.get("name") for t in b.get("technologies", []) if isinstance(t, dict)])


SPECIAL = {
    "pe_sections": _sections, "elf_sections": _sections,
    "pe_imports": _imports,
    "pe_exports": lambda a, b: _set_diff(a.get("names"), b.get("names")),
    "elf_dynamic": lambda a, b: {k: v for k, v in {
        "needed": _set_diff(a.get("needed"), b.get("needed")),
        "imported_symbols": _set_diff(a.get("imported_symbols"), b.get("imported_symbols")),
        "exported_symbols": _set_diff(a.get("exported_symbols"), b.get("exported_symbols"))}.items() if v} or None,
    "ghidra_functions": _functions, "rizin_functions": _functions,
    "detect_capabilities": lambda a, b: {k: v for k, v in {
        "rules": _set_diff(a.get("rules"), b.get("rules")),
        "attack": _set_diff(a.get("attack"), b.get("attack"))}.items() if v} or None,
    "web_stack": _techs, "repo_stack": _techs,
    "strings_ascii": lambda a, b: {"count": [a.get("count"), b.get("count")],
                                   **({"sample": d} if (d := _set_diff(a.get("sample"), b.get("sample"), 60)) else {})}
    if a != b else None,
    "web_css": lambda a, b: {k: v for k, v in {
        "colors": _set_diff(a.get("colors"), b.get("colors")),
        "fonts": _set_diff(a.get("fonts"), b.get("fonts")),
        "breakpoints": _set_diff(a.get("breakpoints"), b.get("breakpoints")),
        "custom_properties": _set_diff(a.get("custom_properties", {}).get("sample"),
                                       b.get("custom_properties", {}).get("sample"))}.items() if v} or None,
    "repo_manifests": lambda a, b: _dict_diff(a.get("dependency_counts", {}), b.get("dependency_counts", {})),
}
SKIP = {"web_fetch", "web_assets", "web_structure", "web_blueprint", "repo_blueprint", "repo_git", "entropy"}


def compare(store: EvidenceStore, subject_a: str, subject_b: str) -> dict[str, Any]:
    a, b = _latest(store, subject_a), _latest(store, subject_b)
    if not a:
        raise ValueError(f"sin evidencias para {subject_a}")
    if not b:
        raise ValueError(f"sin evidencias para {subject_b}")
    changes: dict[str, Any] = {}
    for op in sorted(set(a) & set(b)):
        if op in SKIP or a[op] == b[op]:
            continue
        fn = SPECIAL.get(op)
        if fn:
            d = fn(a[op], b[op])
        elif isinstance(a[op], dict) and isinstance(b[op], dict):
            d = _dict_diff(a[op], b[op])
        else:
            d = {"before": a[op], "after": b[op]}
        if d:
            changes[op] = d
    result = {
        "a": subject_a, "b": subject_b,
        "only_in_a": sorted(set(a) - set(b)), "only_in_b": sorted(set(b) - set(a)),
        "unchanged": sorted(op for op in set(a) & set(b) if a[op] == b[op]),
        "changed": changes,
        "headline": _headline(changes),
    }
    ev = Evidence(
        subject=compare_subject(subject_a, subject_b), provider=PROVIDER, provider_version=VERSION,
        operation="version_diff", params={"a": subject_a, "b": subject_b}, result=result,
        authority=Authority.ANALYST_INFERENCE, confidence=Confidence.HIGH,
        limitations="Compara las evidencias más recientes de cada objetivo; si un proveedor no corrió en ambos, ese aspecto no se compara.",
        environment=environment_string(),
    )
    eid, _ = store.add_evidence(ev)
    return {"evidence_id": eid, "subject": ev.subject, **result}


def compare_subject(a: str, b: str) -> str:
    """Legible y sin colisiones: truncar a 24 caracteres juntaba «repo:https://github.com/…» distintos."""
    import hashlib

    short = lambda s: s.rstrip("/").rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:24] or s[:24]  # noqa: E731
    h = hashlib.sha256(f"{a}|{b}".encode("utf-8")).hexdigest()[:10]
    return f"compare:{short(a)}..{short(b)}#{h}"


def _headline(ch: dict[str, Any]) -> list[str]:
    out = []
    if "hash" in ch:
        s = ch["hash"].get("size")
        if s:
            out.append(f"Tamaño: {s['before']} → {s['after']} bytes")
    for k in ("pe_security", "elf_security", "macho_security"):
        if k in ch:
            out.append(f"Mitigaciones cambiadas: {', '.join(ch[k])}")
    if "pe_imports" in ch and "dlls" in ch["pe_imports"]:
        d = ch["pe_imports"]["dlls"]
        out.append(f"DLLs importadas: +{d['added_count']} −{d['removed_count']}")
    for k in ("ghidra_functions", "rizin_functions"):
        if k in ch and "names" in ch[k]:
            n = ch[k]["names"]
            out.append(f"Funciones ({k.split('_')[0]}): +{n['added_count']} −{n['removed_count']}")
    for k in ("web_stack", "repo_stack"):
        if k in ch:
            out.append(f"Tecnologías: +{ch[k]['added']} −{ch[k]['removed']}")
    if "packing_signals" in ch:
        out.append("Cambiaron las señales de empaquetado")
    return out
