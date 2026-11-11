"""Guion de una sesión de observación: validación y normalización.

Un guion es JSON y declara todo lo que la sesión hará y observará: objetivo, autorización, entorno, estado
inicial, alcance, pasos y limpieza. Se valida entero antes de ejecutar nada.

    {
      "eolfi_observation_script": 1,
      "name": "alta de usuario",
      "authorization": "muestra sintética propia; autoriza CeltiaIA",
      "target": {"path": "app.py", "version": "1.2", "provenance": "build local"},
      "environment": {"inherit": false, "vars": {"LANG": "C"}, "passthrough": ["PATH"], "redirect_home": true},
      "setup": {"files": {"datos/in.txt": {"text": "hola"}, "conf.ini": {"copy": "plantillas/conf.ini"}}},
      "scope": {"files": ["."], "registry": ["HKCU\\\\Software\\\\MiPrueba"], "children": true},
      "allow_hosts": ["127.0.0.1"],
      "steps": [
        {"id": "arranque", "action": "run", "argv": ["{python}", "{target}", "--init"], "timeout": 20},
        {"id": "entrada", "action": "write_file", "path": "datos/in.txt", "text": "adiós"},
        {"id": "api", "action": "http", "method": "GET", "url": "http://127.0.0.1:{var:port}/estado"},
        {"id": "ui", "action": "browser", "url": "http://127.0.0.1:{var:port}/",
         "actions": [{"id": "pulsar", "do": "click", "selector": "#ok"}]}
      ],
      "cleanup": {"remove_sandbox": true}
    }

Marcadores: ``{sandbox}`` (carpeta de trabajo de la sesión), ``{target}`` (ruta del objetivo), ``{python}``
(intérprete de Eolfi) y ``{var:NOMBRE}`` (variable de ejecución, p. ej. un puerto). Las rutas de archivos de los
pasos son relativas al sandbox y no pueden salir de él.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

SCRIPT_VERSION = 1
MAX_SCRIPT_BYTES = 1024 * 1024
MAX_STEPS = 200
MAX_BROWSER_ACTIONS = 100
STEP_ACTIONS = {"run", "write_file", "delete_file", "http", "browser", "desktop", "mobile"}
DESKTOP_DO = {"invoke", "set_value", "toggle", "select", "wait_for", "read"}
BROWSER_DO = {"goto", "click", "fill", "press", "check", "select", "wait_for", "reload"}
HTTP_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
LOOPBACK = {"127.0.0.1", "::1", "localhost", "[::1]"}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_VAR = re.compile(r"\{var:([A-Za-z_][A-Za-z0-9_]{0,63})\}")
_KEYS = {"eolfi_observation_script", "name", "description", "authorization", "target", "environment", "setup",
         "scope", "allow_hosts", "steps", "cleanup", "privacy", "isolation"}


class ScriptError(ValueError):
    pass


def _err(msg: str) -> None:
    raise ScriptError(msg)


def _text(value: Any, label: str, limit: int = 4000, *, required: bool = False) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        _err(f"{label}: texto {'obligatorio ' if required else ''}de hasta {limit} caracteres")
    return value


def _rel_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1000 or "\x00" in value:
        _err(f"{label}: ruta relativa obligatoria")
    p = PurePosixPath(value.replace("\\", "/"))
    if p.is_absolute() or re.match(r"^[A-Za-z]:", value) or ".." in p.parts or str(p) in ("", "."):
        _err(f"{label}: la ruta debe ser relativa al sandbox y sin «..»: {value!r}")
    return p.as_posix()


def _content(spec: Any, label: str, *, allow_copy: bool) -> dict[str, Any]:
    keys = {"text", "base64", "json"} | ({"copy"} if allow_copy else set())
    if not isinstance(spec, dict) or len(set(spec) & keys) != 1 or not set(spec) <= keys | {"sha256"}:
        _err(f"{label}: indica exactamente uno de {sorted(keys)}")
    if "text" in spec:
        _text(spec["text"], label, MAX_SCRIPT_BYTES)
    elif "base64" in spec:
        try:
            base64.b64decode(spec["base64"], validate=True)
        except (ValueError, TypeError):
            _err(f"{label}: base64 inválido")
    elif "json" in spec:
        try:
            json.dumps(spec["json"], allow_nan=False)
        except (TypeError, ValueError):
            _err(f"{label}: json no serializable")
    elif not isinstance(spec["copy"], str) or not spec["copy"]:
        _err(f"{label}: copy debe ser una ruta")
    if "sha256" in spec and not (isinstance(spec["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", spec["sha256"])):
        _err(f"{label}: sha256 inválido")
    return dict(spec)


def content_bytes(spec: dict[str, Any], base: Path | None = None) -> bytes:
    if "text" in spec:
        return spec["text"].encode("utf-8")
    if "base64" in spec:
        return base64.b64decode(spec["base64"])
    if "json" in spec:
        return json.dumps(spec["json"], ensure_ascii=False).encode("utf-8")
    src = Path(spec["copy"])
    if not src.is_absolute() and base is not None:
        src = base / src
    return src.read_bytes()


def _timeout(value: Any, label: str, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 600:
        _err(f"{label}: timeout entre 0 y 600 segundos")
    return float(value)


def _str_map(value: Any, label: str, limit: int = 200) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > limit or not all(
            isinstance(k, str) and k and len(k) <= 200 and isinstance(v, str) and len(v) <= 8000
            for k, v in value.items()):
        _err(f"{label}: objeto de textos")
    return dict(value)


def _step(raw: Any, i: int, seen: set[str]) -> dict[str, Any]:
    label = f"steps[{i}]"
    if not isinstance(raw, dict):
        _err(f"{label}: debe ser un objeto")
    action = raw.get("action")
    if action not in STEP_ACTIONS:
        _err(f"{label}.action debe ser uno de {sorted(STEP_ACTIONS)}")
    sid = raw.get("id", f"paso{i + 1}")
    if not isinstance(sid, str) or not _ID.fullmatch(sid) or sid in seen:
        _err(f"{label}.id inválido o repetido: {sid!r}")
    seen.add(sid)
    step: dict[str, Any] = {"id": sid, "action": action}
    if "description" in raw:
        step["description"] = _text(raw["description"], f"{label}.description")
    allowed = {"id", "action", "description"}
    if action == "run":
        allowed |= {"argv", "stdin", "timeout", "env", "cwd"}
        argv = raw.get("argv")
        if not isinstance(argv, list) or not argv or len(argv) > 500 or not all(
                isinstance(a, str) and len(a) <= 8000 for a in argv) or not argv[0]:
            _err(f"{label}.argv: lista no vacía de textos")
        step["argv"] = list(argv)
        if "stdin" in raw:
            step["stdin"] = _content(raw["stdin"], f"{label}.stdin", allow_copy=False)
        step["timeout"] = _timeout(raw.get("timeout"), label, 30.0)
        step["env"] = _str_map(raw.get("env"), f"{label}.env")
        if "cwd" in raw:
            step["cwd"] = _rel_path(raw["cwd"], f"{label}.cwd")
    elif action == "write_file":
        allowed |= {"path", "text", "base64", "json"}
        step["path"] = _rel_path(raw.get("path"), f"{label}.path")
        step["content"] = _content({k: raw[k] for k in ("text", "base64", "json") if k in raw},
                                   f"{label}", allow_copy=False)
    elif action == "delete_file":
        allowed |= {"path"}
        step["path"] = _rel_path(raw.get("path"), f"{label}.path")
    elif action == "http":
        allowed |= {"method", "url", "headers", "body", "timeout"}
        method = str(raw.get("method", "GET")).upper()
        if method not in HTTP_METHODS:
            _err(f"{label}.method no admitido")
        step["method"] = method
        step["url"] = _text(raw.get("url"), f"{label}.url", 8000, required=True)
        step["headers"] = _str_map(raw.get("headers"), f"{label}.headers", 100)
        if "body" in raw:
            step["body"] = _content(raw["body"], f"{label}.body", allow_copy=False)
        step["timeout"] = _timeout(raw.get("timeout"), label, 15.0)
    elif action == "browser":
        allowed |= {"url", "actions", "timeout", "viewport"}
        step["url"] = _text(raw.get("url"), f"{label}.url", 8000, required=True)
        step["timeout"] = _timeout(raw.get("timeout"), label, 60.0)
        acts = raw.get("actions", [])
        if not isinstance(acts, list) or len(acts) > MAX_BROWSER_ACTIONS:
            _err(f"{label}.actions: lista de hasta {MAX_BROWSER_ACTIONS} acciones")
        aseen: set[str] = set()
        step["actions"] = []
        for j, a in enumerate(acts):
            al = f"{label}.actions[{j}]"
            if not isinstance(a, dict) or a.get("do") not in BROWSER_DO or not set(a) <= {
                    "id", "do", "selector", "value", "url", "description"}:
                _err(f"{al}: «do» debe ser uno de {sorted(BROWSER_DO)}")
            aid = a.get("id", f"accion{j + 1}")
            if not isinstance(aid, str) or not _ID.fullmatch(aid) or aid in aseen:
                _err(f"{al}.id inválido o repetido")
            aseen.add(aid)
            act = {"id": aid, "do": a["do"]}
            for k in ("selector", "value", "url", "description"):
                if k in a:
                    act[k] = _text(a[k], f"{al}.{k}", 8000)
            if a["do"] in {"click", "fill", "press", "check", "select", "wait_for"} and not act.get("selector"):
                _err(f"{al}: «{a['do']}» necesita selector")
            if a["do"] in {"fill", "press", "select"} and "value" not in act:
                _err(f"{al}: «{a['do']}» necesita value")
            if a["do"] == "goto" and not act.get("url"):
                _err(f"{al}: goto necesita url")
            step["actions"].append(act)
        if "viewport" in raw:
            vp = raw["viewport"]
            if not isinstance(vp, dict) or set(vp) != {"width", "height"} or not all(
                    isinstance(vp[k], int) and 100 <= vp[k] <= 8000 for k in vp):
                _err(f"{label}.viewport: {{width, height}} enteros")
            step["viewport"] = dict(vp)
    elif action == "desktop":
        allowed |= {"argv", "timeout", "env", "cwd", "actions", "close", "screenshots"}
        argv = raw.get("argv")
        if not isinstance(argv, list) or not argv or len(argv) > 500 or not all(
                isinstance(a, str) and len(a) <= 8000 for a in argv) or not argv[0]:
            _err(f"{label}.argv: lista no vacía de textos")
        step["argv"] = list(argv)
        step["timeout"] = _timeout(raw.get("timeout"), label, 60.0)
        step["env"] = _str_map(raw.get("env"), f"{label}.env")
        if "cwd" in raw:
            step["cwd"] = _rel_path(raw["cwd"], f"{label}.cwd")
        if not isinstance(raw.get("close", True), bool):
            _err(f"{label}.close: booleano")
        step["close"] = raw.get("close", True)
        if not isinstance(raw.get("screenshots", False), bool):
            _err(f"{label}.screenshots: booleano")
        step["screenshots"] = raw.get("screenshots", False)
        acts = raw.get("actions", [])
        if not isinstance(acts, list) or len(acts) > MAX_BROWSER_ACTIONS:
            _err(f"{label}.actions: lista de hasta {MAX_BROWSER_ACTIONS} acciones")
        aseen: set[str] = set()
        step["actions"] = []
        for j, a in enumerate(acts):
            al = f"{label}.actions[{j}]"
            if not isinstance(a, dict) or a.get("do") not in DESKTOP_DO or not set(a) <= {
                    "id", "do", "automation_id", "name", "value", "description"}:
                _err(f"{al}: «do» debe ser uno de {sorted(DESKTOP_DO)}")
            aid = a.get("id", f"accion{j + 1}")
            if not isinstance(aid, str) or not _ID.fullmatch(aid) or aid in aseen:
                _err(f"{al}.id inválido o repetido")
            aseen.add(aid)
            act = {"id": aid, "do": a["do"]}
            for k in ("automation_id", "name", "value", "description"):
                if k in a:
                    act[k] = _text(a[k], f"{al}.{k}", 2000)
            if a["do"] != "read" and not (act.get("automation_id") or act.get("name")):
                _err(f"{al}: «{a['do']}» necesita automation_id o name")
            if a["do"] == "set_value" and "value" not in act:
                _err(f"{al}: set_value necesita value")
            step["actions"].append(act)
    elif action == "mobile":
        from eolfi.observe import mobile

        allowed |= mobile.validate_step(raw, step, label, _err, _text, _timeout, _ID, MAX_BROWSER_ACTIONS)
    extra = set(raw) - allowed
    if extra:
        _err(f"{label}: claves no admitidas para «{action}»: {sorted(extra)}")
    return step


def validate_script(raw: Any) -> dict[str, Any]:
    """Devuelve el guion normalizado (con valores por defecto explícitos) o lanza ScriptError."""
    if not isinstance(raw, dict):
        _err("el guion debe ser un objeto JSON")
    if raw.get("eolfi_observation_script") != SCRIPT_VERSION:
        _err(f"eolfi_observation_script debe ser {SCRIPT_VERSION}")
    extra = set(raw) - _KEYS
    if extra:
        _err(f"claves no admitidas: {sorted(extra)}")
    if len(json.dumps(raw, ensure_ascii=False).encode("utf-8")) > MAX_SCRIPT_BYTES:
        _err(f"guion mayor que {MAX_SCRIPT_BYTES} bytes")
    out: dict[str, Any] = {"eolfi_observation_script": SCRIPT_VERSION,
                           "name": _text(raw.get("name"), "name", 240, required=True),
                           "description": _text(raw.get("description"), "description"),
                           "authorization": _text(raw.get("authorization"), "authorization", 2000, required=True)}
    tgt = raw.get("target")
    if tgt is not None:
        if not isinstance(tgt, dict) or not set(tgt) <= {"path", "version", "provenance", "sha256"} \
                or not isinstance(tgt.get("path"), str) or not tgt["path"]:
            _err("target: {path, version?, provenance?, sha256?}")
        out["target"] = {"path": tgt["path"], "version": _text(tgt.get("version"), "target.version", 200),
                         "provenance": _text(tgt.get("provenance"), "target.provenance")}
        if "sha256" in tgt:
            if not (isinstance(tgt["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", tgt["sha256"])):
                _err("target.sha256 inválido")
            out["target"]["sha256"] = tgt["sha256"]
    env = raw.get("environment", {})
    if not isinstance(env, dict) or not set(env) <= {"inherit", "vars", "passthrough", "redirect_home"}:
        _err("environment: {inherit, vars, passthrough, redirect_home}")
    passthrough = env.get("passthrough", [])
    if not isinstance(passthrough, list) or not all(isinstance(x, str) and x for x in passthrough):
        _err("environment.passthrough: lista de nombres")
    for k in ("inherit", "redirect_home"):
        if k in env and not isinstance(env[k], bool):
            _err(f"environment.{k}: booleano")
    out["environment"] = {"inherit": env.get("inherit", False), "vars": _str_map(env.get("vars"), "environment.vars"),
                          "passthrough": list(passthrough), "redirect_home": env.get("redirect_home", True)}
    setup = raw.get("setup", {})
    if not isinstance(setup, dict) or not set(setup) <= {"files"}:
        _err("setup: {files}")
    files = setup.get("files", {})
    if not isinstance(files, dict) or len(files) > 1000:
        _err("setup.files: objeto ruta → contenido")
    out["setup"] = {"files": {_rel_path(k, f"setup.files[{k!r}]"): _content(v, f"setup.files[{k!r}]", allow_copy=True)
                              for k, v in files.items()}}
    scope = raw.get("scope", {})
    if not isinstance(scope, dict) or not set(scope) <= {"files", "registry", "children", "capture_contents"}:
        _err("scope: {files, registry, children, capture_contents}")
    sfiles = scope.get("files", ["."])
    if not isinstance(sfiles, list) or len(sfiles) > 50 or not all(isinstance(x, str) and x for x in sfiles):
        _err("scope.files: lista de carpetas")
    reg = scope.get("registry", [])
    if not isinstance(reg, list) or len(reg) > 50 or not all(isinstance(x, str) and x for x in reg):
        _err("scope.registry: lista de claves")
    from eolfi.observe.probes import parse_registry_key

    for k in reg:
        try:
            parse_registry_key(k)
        except ValueError as exc:
            _err(f"scope.registry: {exc}")
    if "children" in scope and not isinstance(scope["children"], bool):
        _err("scope.children: booleano")
    capture_contents = scope.get("capture_contents", [])
    if not isinstance(capture_contents, list) or len(capture_contents) > 50 or not all(
            isinstance(x, str) and x.startswith("{sandbox}/") and ".." not in x.split("/") for x in capture_contents):
        _err('scope.capture_contents: lista de hasta 50 rutas exactas con prefijo "{sandbox}/"')
    out["scope"] = {"files": list(sfiles), "registry": list(reg), "children": scope.get("children", True),
                    "capture_contents": list(dict.fromkeys(capture_contents))}
    hosts = raw.get("allow_hosts", [])
    if not isinstance(hosts, list) or len(hosts) > 50 or not all(
            isinstance(h, str) and re.fullmatch(r"[A-Za-z0-9.:\[\]-]{1,255}", h) for h in hosts):
        _err("allow_hosts: lista de nombres de host")
    out["allow_hosts"] = [h.lower() for h in hosts]
    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps or len(steps) > MAX_STEPS:
        _err(f"steps: lista de 1 a {MAX_STEPS} pasos")
    seen: set[str] = set()
    out["steps"] = [_step(s, i, seen) for i, s in enumerate(steps)]
    cleanup = raw.get("cleanup", {})
    if not isinstance(cleanup, dict) or not set(cleanup) <= {"remove_sandbox"} or not isinstance(
            cleanup.get("remove_sandbox", True), bool):
        _err("cleanup: {remove_sandbox: bool}")
    out["cleanup"] = {"remove_sandbox": cleanup.get("remove_sandbox", True)}
    iso = raw.get("isolation", {"mode": "none"})
    if not isinstance(iso, dict) or iso.get("mode", "none") not in ("none", "container") or not set(iso) <= {
            "mode", "image", "memory", "cpus", "pids"}:
        _err("isolation: {mode: none|container, image, memory, cpus, pids}")
    if iso.get("mode", "none") == "container":
        image = iso.get("image")
        if not isinstance(image, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._/:@-]{0,254}", image):
            _err("isolation.image: nombre de imagen local obligatorio (no se descarga nada)")
        memory = iso.get("memory", "512m")
        if not isinstance(memory, str) or not re.fullmatch(r"\d{1,6}[kmg]", memory):
            _err("isolation.memory: p. ej. 512m")
        cpus = iso.get("cpus", 1)
        if isinstance(cpus, bool) or not isinstance(cpus, (int, float)) or not 0.1 <= cpus <= 64:
            _err("isolation.cpus: entre 0.1 y 64")
        pids = iso.get("pids", 256)
        if isinstance(pids, bool) or not isinstance(pids, int) or not 8 <= pids <= 32768:
            _err("isolation.pids: entre 8 y 32768")
        if any(s["action"] == "desktop" for s in out["steps"]):
            _err("isolation container no admite pasos desktop (necesitan el escritorio del anfitrión)")
        if any(s["action"] == "mobile" for s in out["steps"]):
            _err("isolation container no admite pasos mobile (actúan sobre un dispositivo conectado al anfitrión)")
        out["isolation"] = {"mode": "container", "image": image, "memory": memory, "cpus": cpus, "pids": pids}
    else:
        out["isolation"] = {"mode": "none"}
    privacy = raw.get("privacy", {})
    if not isinstance(privacy, dict) or not set(privacy) <= {"redact_personal_data"} or not isinstance(
            privacy.get("redact_personal_data", True), bool):
        _err("privacy: {redact_personal_data: bool}")
    out["privacy"] = {"redact_personal_data": privacy.get("redact_personal_data", True)}
    if "{target}" in json.dumps(out["steps"]) and "target" not in out:
        _err("los pasos usan {target} pero el guion no declara target")
    return out


def script_sha256(script: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(script, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def referenced_variables(script: dict[str, Any]) -> set[str]:
    return set(_VAR.findall(json.dumps(script["steps"], ensure_ascii=False)))


def expand(text: str, values: dict[str, str], variables: dict[str, str]) -> str:
    def var(m: re.Match) -> str:
        name = m.group(1)
        if name not in variables:
            raise ScriptError(f"falta la variable de ejecución {name!r} (--var {name}=VALOR)")
        return variables[name]

    text = _VAR.sub(var, text)
    for k, v in values.items():
        text = text.replace("{" + k + "}", v)
    return text
