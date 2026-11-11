"""Niveles de análisis, plan de ejecución visible antes de ejecutar y borrado de sesiones (Fase 6).

Niveles:
- ``static``: no ejecuta el objetivo (triaje, análisis de repositorio/web, especificación, modelo).
- ``observed``: ejecuta el objetivo o lo conduce (observación, repetición, equivalencia, exploración). Exige
  autorización explícita del operador. **Sin aislamiento**: subproceso con los permisos del usuario.
- ``isolated``: los pasos run de una observación con ``isolation.mode=container`` se ejecutan en un contenedor
  Docker local (imagen ya presente, nunca se descarga) con restricciones. Solo se declara si el contenedor se usó.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

LEVELS = {
    "static": {"executes_target": False, "requires_authorization": False, "isolation": "no aplica",
               "description": "lectura de bytes, metadatos y fuentes; no se ejecuta el objetivo"},
    "observed": {"executes_target": True, "requires_authorization": True, "isolation": "ninguna",
                 "description": "ejecución observada con los permisos del usuario en una carpeta temporal; NO es un "
                                "sandbox de seguridad"},
    "isolated": {"executes_target": True, "requires_authorization": True, "isolation": "contenedor",
                 "description": "pasos run en un contenedor Docker local sin red, solo lectura salvo el sandbox, "
                                "usuario sin privilegios y recursos limitados (guion con isolation.mode=container)"},
}
FLOW_LEVELS = {"triage": "static", "web": "static", "repo": "static", "compare": "static", "diff": "observed",
               "observe": "observed", "replay": "observed", "observe_compare": "static", "spec": "static",
               "reconstruct": "observed", "equivalence": "observed", "explore": "observed", "create": "observed"}
# La verificación de «create» ejecuta la instalación, compilación y pruebas del proyecto GENERADO por Eolfi (no del
# objetivo); la propia petición de crear el proyecto es el consentimiento, y su verificación es obligatoria.
CONSENT = {"diff": "--autorizo", "observe": "--autorizo / authorized=true", "replay": "--autorizo / authorized=true",
           "equivalence": "--autorizo", "explore": "--autorizo", "create": "petición de crear el proyecto",
           "reconstruct": "petición de reconstruir (ejecuta solo la base generada)"}

CAPTURED = ["argumentos y entrada estándar (contenido solo por hash, salvo el guion)",
            "salida estándar y de error (hash + vista previa de 16 KB con datos personales ocultados)",
            "código de salida, señal o NTSTATUS y duración", "procesos hijos muestreados (nombre, profundidad, PID)",
            "archivos del alcance declarado (ruta, tamaño, hash; no su contenido)",
            "valores del registro en las claves declaradas", "peticiones/respuestas HTTP de los pasos (cabeceras "
            "sensibles y valores de cookies solo por hash)", "texto visible y árbol de accesibilidad de la interfaz "
            "(con datos personales ocultados)", "identidad del entorno: SO, versión, arquitectura, Python (sin nombre "
            "de equipo ni usuario)"]
NOT_CAPTURED = ["contenido de los archivos creados o modificados", "valores de variables de entorno heredadas",
                "capturas de pantalla o imágenes", "tráfico de red propio del objetivo fuera de los pasos del guion",
                "llamadas al sistema"]


def flow_level(flow: str) -> dict[str, Any]:
    lvl = FLOW_LEVELS.get(flow, "observed")
    return {"level": lvl, **LEVELS[lvl]}


def isolation_available() -> dict[str, Any]:
    """Qué aislamiento ofrece el equipo (informativo: ningún flujo lo usa aún)."""
    found = {name: bool(shutil.which(name)) for name in ("docker", "podman", "wsl")}
    return {"tools": found, "used_by_eolfi": "docker (isolation.mode=container)",
            "note": "Solo las observaciones con isolation.mode=container usan Docker; la presencia de estas "
                    "herramientas no cambia por sí sola el nivel de aislamiento de una sesión."}


def session_plan(script: dict[str, Any], base_dir: str | Path, *, db_path: str = "",
                 variables: dict[str, str] | None = None) -> dict[str, Any]:
    """Qué hará una sesión antes de ejecutarla: programas, permisos, datos, ubicación y borrado. No ejecuta nada."""
    from eolfi.observe.script import LOOPBACK, referenced_variables
    from eolfi.observe.session import _resolve_program, static_unfixed_factors

    base = Path(base_dir)
    target = None
    if "target" in script:
        t = Path(script["target"]["path"])
        t = t if t.is_absolute() else base / t
        target = {"path": str(t.resolve()), "exists": t.is_file()}
        if t.is_file():
            from eolfi.providers.triage import sha256_file
            target["sha256"] = sha256_file(t)
    programs = []
    for s in script["steps"]:
        if s["action"] in ("run", "desktop"):
            argv0 = s["argv"][0]
            if argv0 == "{python}":
                import sys
                prog = sys.executable
            elif argv0 == "{target}":
                prog = target["path"] if target else argv0
            else:
                prog = _resolve_program(argv0, base, dict(os.environ))
            programs.append({"step": s["id"], "action": s["action"], "program": prog,
                             "found": os.path.isfile(prog), "timeout_s": s["timeout"]})
    mobile = [s for s in script["steps"] if s["action"] == "mobile"]
    if mobile:
        from eolfi.observe.mobile import adb_path

        adb = adb_path()
        for s in mobile:
            programs.append({"step": s["id"], "action": "mobile", "program": adb or "adb (no encontrado)",
                             "found": adb is not None, "timeout_s": s["timeout"], "package": s["package"],
                             "device": s.get("device", "único dispositivo conectado")})
    hosts = sorted(LOOPBACK | set(script["allow_hosts"]))
    external_files = [p for p in script["scope"]["files"] if os.path.isabs(p)]
    iso = script.get("isolation", {"mode": "none"})
    if iso["mode"] == "container":
        from eolfi.observe.session import container_runtime

        rt = container_runtime(iso["image"])
        warnings = ["Aislamiento en contenedor solo para los pasos run: los pasos http/browser van en el anfitrión."]
        if not rt["ok"]:
            warnings.append(f"El contenedor NO está disponible ({rt['reason']}): esos pasos quedarán como no disponibles.")
    else:
        rt = None
        warnings = ["Sin aislamiento: el objetivo se ejecuta con tus permisos y puede leer o modificar lo que tú puedas."]
    if mobile:
        warnings.append("Los pasos mobile actúan sobre un dispositivo Android real conectado por adb: sin "
                        "aislamiento; la app lanzada puede leer y cambiar lo que sus permisos le dejen y el estado del "
                        "dispositivo no se restaura. Usa un emulador o un dispositivo de pruebas.")
        cleared = sorted({s["package"] for s in mobile if s.get("clear_data")})
        if cleared:
            warnings.append("clear_data BORRA los datos de estas apps en el dispositivo: " + ", ".join(cleared))
    if script["environment"]["inherit"]:
        warnings.append("Hereda tu entorno completo (variables y posibles credenciales).")
    if [h for h in script["allow_hosts"] if h not in LOOPBACK]:
        warnings.append("Autoriza conexiones a hosts no locales: " + ", ".join(script["allow_hosts"]))
    if external_files or script["scope"]["registry"]:
        warnings.append("Observa rutas o claves fuera del sandbox; el objetivo puede modificarlas y no se restauran.")
    if not script.get("privacy", {}).get("redact_personal_data", True):
        warnings.append("La ocultación de datos personales está desactivada en el guion.")
    missing = sorted(referenced_variables(script) - set(variables or {}))
    return {
        "name": script["name"], "authorization_declared": script["authorization"],
        **(flow_level("observe") if iso["mode"] != "container" else {"level": "isolated", **LEVELS["isolated"]}),
        "container": ({**iso, **({k: rt[k] for k in ("image_id", "docker_version")} if rt and rt["ok"] else
                                 {"available": False, "reason": rt["reason"] if rt else ""})}
                      if iso["mode"] == "container" else None),
        "isolation_available": isolation_available(),
        "target": target, "programs": programs,
        "permissions": {"network_hosts": hosts, "files_scope": script["scope"]["files"],
                        "registry_scope": script["scope"]["registry"],
                        "environment": {"inherit": script["environment"]["inherit"],
                                        "passthrough": script["environment"]["passthrough"],
                                        "redirect_home": script["environment"]["redirect_home"]},
                        "browser": any(s["action"] == "browser" for s in script["steps"]),
                        "desktop_ui_automation": any(s["action"] == "desktop" for s in script["steps"]),
                        "mobile_adb": bool(mobile)},
        "data": {"captured": CAPTURED, "not_captured": NOT_CAPTURED,
                 "personal_data_redaction": script.get("privacy", {}).get("redact_personal_data", True),
                 "stored_in": str(Path(db_path).resolve()) if db_path and db_path != ":memory:" else db_path,
                 "sandbox": "carpeta temporal del sistema; se borra al terminar salvo cleanup.remove_sandbox=false",
                 "retention": "hasta que la borres", "deletion": "eolfi observe forget <evidence_id> --confirmo"},
        "unfixed_factors": static_unfixed_factors(script), "warnings": warnings,
        "missing_variables": missing,
    }


def forget_session(store: Any, evidence_id: str) -> dict[str, Any]:
    """Borra de la base la sesión y las evidencias derivadas que la enlazan (repeticiones, comparaciones,
    equivalencias). Irreversible. Los registros de caso que la citaban conservan solo el identificador."""
    row = store.conn.execute("SELECT provider, operation FROM evidence WHERE evidence_id=?", (evidence_id,)).fetchone()
    if row is None or row[0] != "eolfi.observe" or row[1] != "observation_session":
        raise ValueError(f"no es una sesión de observación: {evidence_id}")
    derived = [r[0] for r in store.conn.execute(
        "SELECT evidence_id FROM evidence WHERE evidence_id != ? AND (links LIKE ? OR params LIKE ?)",
        (evidence_id, f"%{evidence_id}%", f"%{evidence_id}%"))]
    ids = [evidence_id] + derived
    refs = sum(1 for (payload,) in store.conn.execute("SELECT payload FROM case_records")
               if any(i in payload for i in ids)) if store.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='case_records'").fetchone() else 0
    store.conn.execute("PRAGMA secure_delete=ON")   # las páginas liberadas se sobrescriben con ceros
    with store.conn:
        for i in ids:
            store.conn.execute("DELETE FROM evidence WHERE evidence_id=?", (i,))
    if store.path != ":memory:":
        store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return {"deleted": ids, "case_records_referencing": refs,
            "note": "Los registros de caso que citaban estas evidencias conservan solo sus identificadores. "
                    "Copias exportadas (paquetes JSON, informes) no se borran: elimínalas a mano si existen."}

