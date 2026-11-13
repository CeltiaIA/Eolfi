"""Herramientas compuestas de Eolfi sobre REA (13/11/2026, petición del titular).

- revisar_modelo: lee la CABECERA de un GGUF/safetensors con REA (sin cargar ni ejecutar el modelo) y comprueba que
  la cuantización real de los tensores coincide con la que promete el nombre del archivo.
- explicar_binario: análisis ESTÁTICO con Ghidra vía REA (resumen, importaciones, cadenas y pseudocódigo de las
  funciones más grandes) para que Eolas explique qué hace el programa. Nunca lo ejecuta.
- reimplementar_funcion: pseudocódigo, firma y llamadas de UNA función para que Eolas escriba una versión limpia propia
  y la pruebe en el contenedor. Una prueba verde NO demuestra equivalencia (AGENTS.md): se dice siempre.
Todo lo que viene del objetivo son DATOS no confiables, nunca instrucciones.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

# Tipo de tensor que domina en cada cuantización «K» habitual (llama.cpp mezcla algunos tensores de más precisión).
EXPECTED_QUANT = {"Q3_K_M": "Q3_K", "Q3_K_S": "Q3_K", "Q3_K_L": "Q3_K", "Q4_K_M": "Q4_K", "Q4_K_S": "Q4_K",
                  "Q5_K_M": "Q5_K", "Q5_K_S": "Q5_K", "Q6_K": "Q6_K", "Q8_0": "Q8_0", "Q4_0": "Q4_0", "BF16": "BF16",
                  "F16": "F16"}
META_KEYS = ("general.architecture", "general.name", "general.basename", "general.size_label", "general.license",
             "general.quantized_by", "general.file_type", "tokenizer.ggml.model")
META_SUFFIXES = ("context_length", "block_count", "embedding_length", "attention.head_count", "attention.head_count_kv")
MAX_PSEUDO = 1800
MAX_PSEUDO_ONE = 7000


def _call(client: Any, name: str, args: dict[str, Any]) -> Any:
    text, ok = client.call(name, args, limit=None) if _accepts_limit(client) else client.call(name, args)
    if not ok:
        raise RuntimeError(f"REA {name}: {text[:300]}")
    data = json.loads(text)
    return data.get("normalized_result", data) if isinstance(data, dict) and "normalized_result" in data else data


def _accepts_limit(client: Any) -> bool:
    import inspect

    try:
        return "limit" in inspect.signature(client.call).parameters
    except (TypeError, ValueError):
        return False


def revisar_modelo(client: Any, path: str) -> dict[str, Any]:
    n = _call(client, "inspect_model_artifact", {"path": path, "detail": "complete"})
    meta = {m["key"]: m.get("value") for m in n.get("metadata") or [] if isinstance(m, dict)}
    arch = str(meta.get("general.architecture") or "")
    info = {k.split(".", 1)[1]: meta[k] for k in META_KEYS if k in meta}
    info.update({s: meta[f"{arch}.{s}"] for s in META_SUFFIXES if f"{arch}.{s}" in meta})
    by_type = (n.get("totals") or {}).get("by_type") or []
    params = {t["type"]: int(t.get("parameter_count") or 0) for t in by_type}
    dominant = max(params, key=params.get) if params else None
    claimed = next((q for q in sorted(EXPECTED_QUANT, key=len, reverse=True) if q.lower() in Path(path).name.lower()), None)
    checks = [{"comprobacion": "formato GGUF/safetensors legible", "ok": n.get("format") in ("gguf", "safetensors")}]
    if claimed:
        checks.append({"comprobacion": f"la cuantización real coincide con el nombre ({claimed})",
                       "ok": dominant == EXPECTED_QUANT[claimed], "dominante": dominant})
    total = int((n.get("totals") or {}).get("parameter_count") or 0)
    return {"archivo": path, "formato": n.get("format"), "version": n.get("version"), "modelo": info,
            "parametros": total, "parametros_legible": f"{total / 1e9:.2f} B" if total else None,
            "tensores": sum(int(t.get("tensors") or 0) for t in by_type),
            "tipos_de_tensor": {t["type"]: int(t.get("tensors") or 0) for t in by_type},
            "comprobaciones": checks, "aprobado": all(c["ok"] for c in checks),
            "limites": "Solo se leyó la cabecera: no verifica los pesos ni el comportamiento del modelo (el SHA-256 "
                       "completo lo verifica la descarga)."}


def _session(client: Any, path: str) -> dict[str, Any]:
    opened = _call(client, "open_binary", {"path": path})
    return opened.get("result", opened) if isinstance(opened, dict) else {}


def explicar_binario(client: Any, path: str, funciones: int = 5) -> dict[str, Any]:
    funciones = max(1, min(int(funciones or 5), 8))
    head = _session(client, path)
    try:
        overview = _call(client, "binary_overview", {})
        procs = _call(client, "list_procedures", {"detail": "complete"})
        procs = procs if isinstance(procs, list) else []
        imports = [p["value"] for p in procs if (p.get("procedure") or {}).get("external")]
        own = [p for p in procs if not (p.get("procedure") or {}).get("external") and not (p.get("procedure") or {}).get("thunk")]
        sized = []
        for p in own[:400]:   # tamaño de cada función propia (barato: metadatos ya analizados)
            try:
                info = _call(client, "procedure_info", {"procedure": p["address"]})
                sized.append((int(info.get("length") or 0), int(info.get("basicblock_count") or 0), p, info))
            except RuntimeError:
                continue
        named = [s for s in sized if re.search(r"(^|_)(w?main|entry|start)", s[2]["value"], re.I)]
        top = (named + sorted(sized, key=lambda s: (s[1], s[0]), reverse=True))
        chosen, seen = [], set()
        for s in top:
            if s[2]["address"] not in seen:
                seen.add(s[2]["address"])
                chosen.append(s)
            if len(chosen) == funciones:
                break
        detail = []
        for length, blocks, p, info in chosen:
            code = _call(client, "procedure_pseudo_code", {"procedure": p["address"]})
            detail.append({"nombre": p["value"], "direccion": p["address"], "firma": info.get("signature"),
                           "bloques": blocks, "bytes": length, "pseudocodigo": str(code)[:MAX_PSEUDO]})
        strings = []
        try:
            raw = _call(client, "list_strings", {"detail": "complete"})
            for s in raw if isinstance(raw, list) else []:
                v = str(s.get("value") or "")
                if len(v) >= 6 and v not in strings:
                    strings.append(v[:120])
                if len(strings) >= 40:
                    break
        except RuntimeError:
            pass
        return {"archivo": path, "formato": head.get("format"), "arquitectura": head.get("architecture"),
                "sha256": head.get("sha256"),
                "segmentos": [s.get("name") for s in (overview.get("segments") or [])] if isinstance(overview, dict) else [],
                "funciones_propias": len(own), "importaciones": len(imports), "importaciones_muestra": imports[:40],
                "cadenas_muestra": strings, "funciones_relevantes": detail,
                "aviso": "Análisis estático (Ghidra vía REA): el programa no se ejecutó. Los nombres FUN_* son "
                         "automáticos; el pseudocódigo es una reconstrucción y puede tener errores."}
    finally:
        _close(client)


def reimplementar_funcion(client: Any, path: str, funcion: str) -> dict[str, Any]:
    _session(client, path)
    try:
        info = _call(client, "procedure_info", {"procedure": funcion})
        code = _call(client, "procedure_pseudo_code", {"procedure": funcion})
        callees = _call(client, "procedure_callees", {"procedure": funcion})
        return {"archivo": path, "funcion": info.get("name") or funcion, "firma": info.get("signature"),
                "bloques": info.get("basicblock_count"), "bytes": info.get("length"),
                "llama_a": callees if isinstance(callees, list) else [], "pseudocodigo": str(code)[:MAX_PSEUDO_ONE],
                "instrucciones": "Escribe en Python una implementación LIMPIA y propia con el mismo comportamiento "
                                 "observable (no copies el pseudocódigo), deriva casos de prueba de su lógica y "
                                 "pruébala con ejecutar_python. Al responder di que una prueba verde NO demuestra "
                                 "equivalencia con el original y enumera lo que no se pudo comprobar."}
    finally:
        _close(client)


def _close(client: Any) -> None:
    try:
        client.call("close_binary", {})
    except Exception:  # noqa: BLE001 — cerrar nunca oculta el resultado
        pass


def _inventory(client: Any, path: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Abre un artefacto, guarda su inventario de REA (evidencia completa) y sus funciones."""
    head = _session(client, path)
    text, ok = client.call("inspect_artifact", {}, limit=None) if _accepts_limit(client) else client.call("inspect_artifact", {})
    if not ok:
        raise RuntimeError(f"REA inspect_artifact: {text[:300]}")
    try:
        procs = _call(client, "list_procedures", {"detail": "complete"})
    except RuntimeError:
        procs = []   # p. ej. un artefacto que no es ejecutable: se compara solo su inventario
    return head, json.loads(text), procs if isinstance(procs, list) else []


def comparar_versiones(client: Any, original: str, nueva: str) -> dict[str, Any]:
    """Qué cambió entre dos versiones (o entre un original y su reconstrucción), con el veredicto verificable de REA.

    REA compara los inventarios completos (`compare_artifacts`) y `verify_reconstruction` evalúa la afirmación
    «mismo artefacto». Eolfi añade las importaciones y funciones con nombre añadidas o quitadas. Es una comparación
    ESTRUCTURAL: el comportamiento al ejecutarse no se compara (requiere autorización, plan punto 2)."""
    try:
        head_a, inv_a, procs_a = _inventory(client, original)
        head_b, inv_b, procs_b = _inventory(client, nueva)
        cmp_text, ok = client.call("compare_artifacts", {"left": inv_a, "right": inv_b}, limit=None) \
            if _accepts_limit(client) else client.call("compare_artifacts", {"left": inv_a, "right": inv_b})
        if not ok:
            raise RuntimeError(f"REA compare_artifacts: {cmp_text[:300]}")
        cmp = json.loads(cmp_text)
        result = cmp.get("normalized_result") or {}
        spec = {"name": f"Eolfi · {Path(original).name} frente a {Path(nueva).name}",
                "claims": [{"kind": "structural-artifact", "claim_id": "mismo-artefacto",
                            "title": "La versión nueva conserva el artefacto original", "comparison_evidence_id":
                                cmp.get("evidence_id"), "dimension": "overall"}]}
        verdict = _call(client, "verify_reconstruction", {"specification": spec})
    finally:
        _close(client)

    def names(procs: list[dict[str, Any]], external: bool) -> set[str]:
        return {str(p.get("value")) for p in procs
                if bool((p.get("procedure") or {}).get("external")) == external
                and (external or not re.match(r"^(FUN|thunk_FUN|LAB|SUB)_", str(p.get("value"))))}

    imp_a, imp_b = names(procs_a, True), names(procs_b, True)
    fn_a, fn_b = names(procs_a, False), names(procs_b, False)
    claims = (verdict.get("claims") or {}).get("items") or [] if isinstance(verdict, dict) else []
    return {"original": {"ruta": original, "sha256": head_a.get("sha256"), "formato": head_a.get("format"),
                         "funciones": len(procs_a), "importaciones": len(imp_a)},
            "nueva": {"ruta": nueva, "sha256": head_b.get("sha256"), "formato": head_b.get("format"),
                      "funciones": len(procs_b), "importaciones": len(imp_b)},
            "identicos": head_a.get("sha256") == head_b.get("sha256") and bool(head_a.get("sha256")),
            "rea_estado": result.get("status"), "rea_resumen": result.get("summary"),
            "rea_cambios": [{"ruta": c.get("logical_path"), "tipo": c.get("classification"),
                             "dimensiones": c.get("dimensions")} for c in (result.get("changes") or [])[:20]],
            "verificacion": {"estado": verdict.get("status") if isinstance(verdict, dict) else None,
                             "afirmaciones": [{k: c.get(k) for k in ("claim_id", "status", "observed_status")}
                                              for c in claims],
                             "limites": sorted({l for c in claims for l in c.get("limitations") or []})[:8]},
            "importaciones_anadidas": sorted(imp_b - imp_a)[:50], "importaciones_quitadas": sorted(imp_a - imp_b)[:50],
            "funciones_con_nombre_anadidas": sorted(fn_b - fn_a)[:50],
            "funciones_con_nombre_quitadas": sorted(fn_a - fn_b)[:50],
            "aviso": "Comparación estructural y estática (no se ejecutó nada). Las funciones sin nombre (FUN_*) no se "
                     "emparejan entre versiones; «unknown» en REA significa sin evidencia suficiente, no igualdad."}


def _try(client: Any, name: str, args: dict[str, Any]) -> tuple[Any, str | None]:
    try:
        return _call(client, name, args), None
    except (RuntimeError, ValueError) as exc:
        return None, str(exc)[:200]


def inventario_dependencias(client: Any, path: str) -> dict[str, Any]:
    """Librerías, versiones, firmas y certificados de un binario (plan REA, punto 4). Estático: no lo ejecuta.

    PE: DLL importadas (y diferidas) con sus funciones e imphash, certificados y tipos de recurso. Go: versión del
    compilador, módulo principal y dependencias declaradas. Rust: dependencias si el binario es «auditable». Lo que
    no aplica al formato se indica en «no_aplica», no se inventa."""
    with open(path, "rb") as fh:
        magic = fh.read(4)
    fmt = ("pe" if magic[:2] == b"MZ" else "elf" if magic == b"\x7fELF"
           else "macho" if magic in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe") else "otro")
    out: dict[str, Any] = {"archivo": path, "formato": fmt, "no_aplica": {}}
    if fmt == "pe":
        imp, err = _try(client, "inspect_pe_imports", {"path": path})
        if imp:
            out["sha256"] = (imp.get("artifact") or {}).get("sha256")
            out["arquitectura"] = imp.get("architecture")
            out["imphash"] = imp.get("imphash")

            def dlls(rows: Any) -> list[dict[str, Any]]:
                return [{"libreria": d.get("name"), "funciones": len(d.get("functions") or []),
                         "muestra": [f.get("name") or f"ordinal {f.get('ordinal')}" for f in (d.get("functions") or [])[:8]]}
                        for d in rows or []]
            out["librerias"] = dlls(imp.get("imports"))
            out["librerias_diferidas"] = dlls(imp.get("delay_imports"))
        else:
            out["no_aplica"]["importaciones"] = err
        certs, err = _try(client, "inspect_pe_certificates", {"path": path})
        if certs is not None:
            out["firma"] = {"certificados": len(certs.get("entries") or []),
                            "aviso": "No se verifica la cadena ni la firma Authenticode; sin tabla no prueba que no "
                                     "esté firmado por catálogo."}
        else:
            out["no_aplica"]["certificados"] = err
        res, err = _try(client, "inspect_pe_resources", {"path": path})
        if res is not None:
            kinds = Counter(str((r.get("type") or {}).get("name") or (r.get("type") or {}).get("id") or r.get("type"))
                            for r in res.get("resources") or [] if isinstance(r, dict))
            out["recursos"] = dict(kinds) or {"total": len(res.get("resources") or [])}
        else:
            out["no_aplica"]["recursos"] = err
    else:
        exp, err = _try(client, "inspect_native_exports", {"path": path})
        out["exportaciones"] = (len(exp.get("exports") or []) if isinstance(exp, dict) else None) if exp else None
        if err:
            out["no_aplica"]["exportaciones"] = err
    go, err = _try(client, "inspect_go_binary", {"path": path})
    info = (go or {}).get("build_info") if isinstance(go, dict) else None
    if info:
        lines = [ln.split("\t") for ln in str(info.get("module_text") or "").splitlines()]
        deps = [{"modulo": p[1], "version": p[2] if len(p) > 2 else None}
                for p in lines if p[0] == "dep" and len(p) > 1][:200]
        out["go"] = {"version": info.get("go_version"),
                     "modulo": next((p[1] for p in lines if p[0] == "path" and len(p) > 1), None),
                     # Vacío no significa «sin dependencias»: la información de compilación no las declara.
                     "dependencias": deps or "no declaradas en la información de compilación del binario"}
    rust, err = _try(client, "inspect_rust_binary", {"path": path})
    meta = (rust or {}).get("auditable_metadata") if isinstance(rust, dict) else None
    if meta:
        pkgs = meta.get("packages") if isinstance(meta, dict) else None
        out["rust"] = {"dependencias": [{"crate": p.get("name"), "version": p.get("version")}
                                        for p in pkgs or [] if isinstance(p, dict)][:200]}
    elif isinstance(rust, dict) and rust.get("rustc_commit"):
        out["rust"] = {"rustc_commit": rust.get("rustc_commit"), "dependencias": "no incrustadas (no es «auditable»)"}
    out["aviso"] = ("Inventario estático de REA: lo declarado en el archivo, no autentica nombres ni versiones y no "
                    "dice qué se carga al ejecutarse.")
    return out


BEHAVIOR_DIMENSIONS = ("overall", "terminal", "exit")


def _scenario(spec: dict[str, Any]) -> dict[str, Any]:
    exe = str(spec.get("ejecutable") or spec.get("executable") or "").strip()
    if not exe:
        raise ValueError("cada escenario necesita «ejecutable»")
    args = spec.get("argumentos") or spec.get("arguments") or []
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise ValueError("«argumentos» debe ser una lista de textos")
    out: dict[str, Any] = {"executable": exe, "arguments": args}
    cwd = spec.get("carpeta") or spec.get("working_directory")
    if cwd:
        out["working_directory"] = str(cwd)
    return out


def verificar_comportamiento(client: Any, authorizer: Any, original: dict[str, Any],
                             reconstruccion: dict[str, Any]) -> dict[str, Any]:
    """Cobertura de COMPORTAMIENTO (plan REA, punto 1): ejecuta el original y la reconstrucción con el mismo escenario,
    compara las capturas y verifica afirmaciones de comportamiento (salida, código de salida y global).

    EJECUTA PROGRAMAS: cada captura necesita un permiso del titular (autorización por caso, punto 2). Sin él, solo se
    crean las peticiones y no se ejecuta nada. Aprobar cubre solo lo declarado, no la equivalencia global."""
    if authorizer is None:
        raise RuntimeError("verificar el comportamiento ejecuta programas: necesita la autorización por caso")
    scenarios = {"original": _scenario(original), "reconstruccion": _scenario(reconstruccion)}
    # Primero se comprueba SIN consumir: si falta el permiso de un lado, no se gasta el «una vez» del otro.
    pending = {side: authorizer.request("capture_process_scenario", args)
               for side, args in scenarios.items() if not authorizer.peek("capture_process_scenario", args)}
    grants = {}
    if not pending:
        grants = {side: authorizer.allowed("capture_process_scenario", args) for side, args in scenarios.items()}
        # Mismo comando en los dos lados con un solo «una vez»: el segundo no tiene permiso y no se ejecuta nada.
        pending = {side: authorizer.request("capture_process_scenario", scenarios[side])
                   for side, g in grants.items() if not g}
    if pending:
        return {"autorizacion_pendiente": next(iter(pending.values())), "herramienta": "capture_process_scenario",
                "peticiones": pending,
                "mensaje": "Para comparar el comportamiento hay que EJECUTAR el original y la reconstrucción. He pedido "
                           "autorización al usuario; explícale qué se va a ejecutar y espera a que la apruebe."}
    captures = {}
    for side, args in scenarios.items():
        text, ok = client.call("capture_process_scenario", args, limit=None) if _accepts_limit(client) \
            else client.call("capture_process_scenario", args)
        authorizer.log("capture_process_scenario", args, grants[side], ok)
        if not ok:
            raise RuntimeError(f"REA capture_process_scenario ({side}): {text[:300]}")
        captures[side] = json.loads(text)
    cmp_text, ok = client.call("compare_process_captures", {"left": captures["original"], "right": captures["reconstruccion"]},
                               limit=None) if _accepts_limit(client) else \
        client.call("compare_process_captures", {"left": captures["original"], "right": captures["reconstruccion"]})
    if not ok:
        raise RuntimeError(f"REA compare_process_captures: {cmp_text[:300]}")
    cmp = json.loads(cmp_text)
    spec = {"name": "Eolfi · comportamiento de la reconstrucción",
            "claims": [{"kind": "behavioral", "claim_id": f"comportamiento-{d}", "title": f"Mismo comportamiento ({d})",
                        "comparison_evidence_id": cmp.get("evidence_id"), "dimension": d} for d in BEHAVIOR_DIMENSIONS]}
    verdict = _call(client, "verify_reconstruction", {"specification": spec})
    claims = (verdict.get("claims") or {}).get("items") or [] if isinstance(verdict, dict) else []
    return {"escenario": scenarios, "comparacion": (cmp.get("normalized_result") or {}).get("status"),
            "verificacion": {"estado": verdict.get("status") if isinstance(verdict, dict) else None,
                             "afirmaciones": [{k: c.get(k) for k in ("claim_id", "dimension", "status", "observed_status")}
                                              for c in claims],
                             "limites": sorted({l for c in claims for l in c.get("limitations") or []})[:8]},
            "permisos_usados": grants,
            "aviso": "Cubre solo este escenario y estas dimensiones; una coincidencia no demuestra equivalencia funcional "
                     "completa y «unknown» significa sin evidencia suficiente."}


def analizar_app_js(client: Any, path: str) -> dict[str, Any]:
    """Aplicación JavaScript, Electron o web (carpeta o .asar) analizada por REA SIN ejecutarla (plan REA, punto 5):
    estadísticas, superficie de Electron (ventanas, precargas, IPC, procesos, módulos nativos) y cobertura del grafo
    semántico por familia. Las relaciones son candidatas estáticas: no prueban ejecución."""
    n = _call(client, "analyze_javascript_application", {"input_path": path, "detail": "summary"})
    summary = n.get("summary") or {}
    electron = summary.get("electron") or {}
    ipc = electron.get("ipc") or {}
    semantic = ((summary.get("coverage") or {}).get("semantic") or {})
    families = [{"familia": f.get("family"), "estado": f.get("status"), "relaciones": f.get("retained_relations"),
                 "incognitas": f.get("unknown_count")} for f in semantic.get("families") or []]
    unknown_total = next((int(m.group(1)) for u in n.get("unknowns") or []
                          if (m := re.match(r"(\d+) semantic graph unknowns", str(u)))), None)
    stats = summary.get("statistics") or {}
    return {"archivo": path, "formato": summary.get("format"), "sha256": summary.get("root_artifact_sha256"),
            "evidencia_rea": n.get("parent_evidence_id"),
            "estadisticas": {"archivos_relevantes": stats.get("relevant_files"),
                             "javascript_analizados": stats.get("parsed_javascript_files"),
                             "fallos_de_lectura": stats.get("parse_failures"), "hallazgos": stats.get("findings"),
                             "asar_anidados": stats.get("nested_asar_containers")},
            "electron": {"ventanas": electron.get("browser_windows"), "precargas": electron.get("preload_entrypoints"),
                         "apis_expuestas": electron.get("exposed_api_members"),
                         "canales_ipc": ipc.get("literal_channels"), "manejadores_ipc": ipc.get("main_handlers"),
                         "procesos_utilidad": electron.get("utility_processes"),
                         "modulos_nativos": electron.get("native_addon_bindings")},
            "cobertura": {"aplicacion": ((summary.get("coverage") or {}).get("application") or {}).get("status"),
                          "semantica": semantic.get("status"), "familias": families},
            "incognitas_semanticas": unknown_total,
            "siguiente_paso": "Para rastrear una función o un dato concreto: rea_usar con trace_javascript_semantics "
                              "sobre esta evidencia. Recuperar fuentes legibles de un paquete minificado "
                              "(recover_javascript_sources) solo está disponible en Linux x64 con Wakaru.",
            "aviso": "Análisis estático de REA: el código no se ejecutó; las relaciones son candidatas y «unknown» "
                     "significa sin evidencia, no ausencia."}


def recuperar_fuentes_js(client: Any, path: str, destino: str, *, run: Any = None) -> dict[str, Any]:
    """Reconstruye módulos legibles de un script o paquete JavaScript con Wakaru, vía el REA de WSL2 (plan REA,
    punto 5). No ejecuta el código de la aplicación. La salida se crea dentro de Ubuntu (REA exige propiedad y
    permisos que un disco de Windows montado no ofrece) y se copia a `destino` en Windows.
    Las fuentes recuperadas de programas de terceros NO van a Alejandría (derechos de autor)."""
    import secrets
    import subprocess

    from eolfi.rea_client import wsl_path

    run = run or subprocess.run
    run_id = "eolfi-" + secrets.token_hex(6)
    base = "$HOME/.local/eolfi-rea/salidas"
    home = run(["wsl.exe", "-e", "bash", "-c", f"mkdir -p {base} && chmod 700 {base} && echo $HOME"],
               capture_output=True, text=True, timeout=60).stdout.strip().splitlines()[-1]
    linux_out = f"{home}/.local/eolfi-rea/salidas/{run_id}"
    n = _call(client, "recover_javascript_sources", {"path": wsl_path(path), "output_directory": linux_out})
    dest = Path(destino)
    if dest.exists() and any(dest.iterdir()):
        raise ValueError(f"el destino ya existe y no está vacío: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    copied = run(["wsl.exe", "-e", "cp", "-r", linux_out, wsl_path(dest)], capture_output=True, text=True, timeout=300)
    if copied.returncode != 0:
        raise RuntimeError(f"no se pudo copiar el resultado a Windows: {copied.stderr[-300:]}")
    run(["wsl.exe", "-e", "rm", "-rf", linux_out], capture_output=True, text=True, timeout=60)
    modules = [{"modulo": m.get("reported_filename"), "estado": m.get("reported_status"),
                "sha256": (m.get("artifact") or {}).get("sha256")} for m in n.get("modules") or []]
    src = n.get("source") or {}
    return {"archivo": path, "sha256": src.get("sha256"), "formato": n.get("reported_format"),
            "estado": n.get("status"), "motor": f"wakaru {(n.get('engine') or {}).get('version')}",
            "modulos": modules, "fallidos": n.get("failed"), "avisos": (n.get("warnings") or [])[:10],
            "destino": str(dest), "equivalencia": n.get("runtime_equivalence"),
            "aviso": "Recuperación estática (no se ejecutó la aplicación): los nombres originales y la equivalencia en "
                     "ejecución quedan desconocidos. Si el programa es de terceros, estas fuentes no van a Alejandría."}


_ID_SEGMENT = re.compile(r"^(\d+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{16,})$", re.I)


def _template(path: str) -> str:
    """/api/v1/productos/42 → /api/v1/productos/{id} (segmentos numéricos, UUID o hex largos)."""
    parts = [("{id}" if _ID_SEGMENT.match(p) else p) for p in path.split("/")]
    return "/".join(parts) or "/"


def _json_schema(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        return {"type": "array", "items": _json_schema(value[0]) if value else {}}
    if isinstance(value, dict):
        return {"type": "object", "properties": {k: _json_schema(v) for k, v in list(value.items())[:50]}}
    return {}


def api_desde_captura(client: Any, path: str, fields_client: Any = None) -> dict[str, Any]:
    """De una captura de red (pcap/pcapng) a un borrador de API (plan REA, punto 7). No ejecuta nada ni captura.

    Nivel básico (REA de Windows, `inspect_pcap_capture`): servidores, rutas con plantillas, parámetros de consulta,
    protocolos y hosts cifrados (SNI de TLS). Nivel completo (REA de WSL con tshark, `inspect_packet_capture`):
    métodos, códigos de respuesta, tipos de contenido y esquemas JSON → borrador OpenAPI 3. El tráfico cifrado solo
    deja ver el host."""
    import urllib.parse

    n = _call(client, "inspect_pcap_capture", {"path": path, "detail": "complete"})
    servers, endpoints = set(), {}
    for uri in n.get("http_request_uris") or []:
        u = urllib.parse.urlsplit(str(uri))
        if u.scheme and u.netloc:
            servers.add(f"{u.scheme}://{u.netloc}")
        ep = endpoints.setdefault(_template(u.path or "/"), {"ejemplos": [], "parametros": set()})
        if len(ep["ejemplos"]) < 5:
            ep["ejemplos"].append(str(uri))
        ep["parametros"].update(urllib.parse.parse_qs(u.query, keep_blank_values=True))
    out: dict[str, Any] = {
        "archivo": path, "sha256": ((n.get("target") or {}).get("sha256") if isinstance(n.get("target"), dict) else None),
        "formato": n.get("file_type"), "paquetes": n.get("packet_count"),
        "protocolos": [p.get("protocol") for p in n.get("protocol_distribution") or []][:20],
        "hosts_cifrados_tls": n.get("tls_sni_values") or [], "servidores": sorted(servers),
        "endpoints": {k: {"ejemplos": v["ejemplos"], "parametros_consulta": sorted(v["parametros"])}
                      for k, v in sorted(endpoints.items())},
        "nivel": "basico"}
    if fields_client is None:
        out["aviso"] = ("Nivel básico: rutas y parámetros observados. Los métodos, códigos y cuerpos necesitan el "
                        "análisis de campos de REA, que solo funciona en Linux (tshark en WSL2). Aún no es una "
                        "especificación OpenAPI completa.")
        return out
    # http.request_in (número de trama de la petición) en vez de http.response_for.uri: este último no existe en
    # tshark 4.6.4 de Ubuntu (14/11/2026). REA devuelve el cuerpo (http.file_data) en hexadecimal.
    fields = ["http.request.method", "http.request.uri", "http.response.code", "http.request_in",
              "http.content_type", "http.file_data"]
    rows = _call(fields_client, "inspect_packet_capture", {"path": path, "fields": fields, "display_filter": "http",
                                                           "match_limit": None})
    frames = (rows.get("packets") or rows.get("matches") or rows.get("frames") or []) if isinstance(rows, dict) else rows or []
    ops: dict[tuple[str, str], dict[str, Any]] = {}
    pending: dict[str, tuple[str, str]] = {}

    def field(fr: dict[str, Any], name: str) -> str | None:
        v = (fr.get("fields") or fr).get(name)
        return (v[0] if isinstance(v, list) and v else v) if v not in (None, "", []) else None

    def body_json(fr: dict[str, Any]) -> Any:
        raw = field(fr, "http.file_data")
        if not raw:
            return None
        text = raw
        if re.fullmatch(r"(?:[0-9a-fA-F]{2})+", raw):
            try:
                text = bytes.fromhex(raw).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                return None
        try:
            return json.loads(text)
        except ValueError:
            return None

    for fr in frames:
        method, uri = field(fr, "http.request.method"), field(fr, "http.request.uri")
        if method and uri:
            key = (_template(urllib.parse.urlsplit(uri).path or "/"), method.lower())
            op = ops.setdefault(key, {"respuestas": {}, "peticion": None})
            body = body_json(fr)
            if body is not None and op["peticion"] is None:
                op["peticion"] = _json_schema(body)
            pending[str(field(fr, "frame.number") or uri)] = key
            continue
        code = field(fr, "http.response.code")
        key = pending.get(str(field(fr, "http.request_in") or ""))
        if code and key:
            body = body_json(fr)
            schema = _json_schema(body) if body is not None else None
            ops[key]["respuestas"][code] = {"tipo": field(fr, "http.content_type"), "esquema": schema}
    paths: dict[str, Any] = {}
    for (tpl, method), op in sorted(ops.items()):
        params = [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}] if "{id}" in tpl else []
        params += [{"name": q, "in": "query", "schema": {"type": "string"}}
                   for q in (out["endpoints"].get(tpl) or {}).get("parametros_consulta", [])]
        entry: dict[str, Any] = {"summary": f"{method.upper()} {tpl} (observado)",
                                 "responses": {code: {"description": "observada en la captura",
                                                      **({"content": {(r["tipo"] or "application/json").split(";")[0]: {"schema": r["esquema"]}}}
                                                         if r["esquema"] else {})} for code, r in op["respuestas"].items()}
                                 or {"default": {"description": "sin respuesta observada"}}}
        if params:
            entry["parameters"] = params
        if op["peticion"]:
            entry["requestBody"] = {"content": {"application/json": {"schema": op["peticion"]}}}
        paths.setdefault(tpl, {})[method] = entry
    out.update(nivel="completo", openapi={
        "openapi": "3.0.3",
        "info": {"title": "API inferida de una captura (borrador de Eolfi)", "version": "desconocida",
                 "description": "Solo lo observado en la captura: no incluye operaciones no usadas ni garantiza tipos."},
        "servers": [{"url": s} for s in sorted(servers)], "paths": paths})
    out["aviso"] = ("Borrador inferido solo de lo observado: faltan las operaciones que no aparecen y los tipos se "
                    "deducen de ejemplos. Revisa credenciales o datos personales antes de compartirlo.")
    return out
