"""Sesión de observación reproducible de un objetivo ejecutable, sin necesidad de su código fuente.

Ejecuta un guion validado (``eolfi.observe.script``) en un sandbox de carpeta temporal y registra, paso a paso:
entradas, salidas (stdout/stderr con hash y vista previa normalizada), código de salida/señal, duración, procesos
hijos muestreados, efectos en archivos y registro declarados, peticiones HTTP autorizadas y escenarios de
navegador con sus trazas enlazadas a la acción que las produjo. El resultado se guarda como evidencia
``controlled_repro`` y, con ``case_id``, como registro «observation» del caso.

ATENCIÓN: esto EJECUTA el objetivo con los permisos del usuario. El sandbox es una carpeta temporal con HOME/TEMP
redirigidos, NO un aislamiento de seguridad: úsalo solo con muestras autorizadas y en un entorno adecuado.
"""
from __future__ import annotations

import base64
import hashlib
import http.cookiejar
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Authority, Confidence, Evidence
from eolfi.observe import probes
from eolfi.observe.script import (LOOPBACK, ScriptError, content_bytes, expand, referenced_variables,
                                  script_sha256, validate_script)

PROVIDER = "eolfi.observe"
VERSION = "1.0.0"
OPERATION = "observation_session"
MAX_OUTPUT = 64 * 1024 * 1024
MAX_HTTP_BODY = 4 * 1024 * 1024
PREVIEW = 16 * 1024
ISOLATION = ("ninguna: subproceso con los permisos del usuario en una carpeta temporal (HOME/TEMP redirigidos por "
             "variables de entorno); no es un sandbox de seguridad")
_SECRET = re.compile(r"(authorization|cookie|token|secret|password|passwd|api[-_]?key|auth)", re.I)
_WIN_DEFAULT_ENV = ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "SYSTEMDRIVE", "PROCESSOR_ARCHITECTURE",
                    "NUMBER_OF_PROCESSORS")
_HOME_VARS = {"HOME": ".home", "USERPROFILE": ".home", "APPDATA": ".home/AppData/Roaming",
              "LOCALAPPDATA": ".home/AppData/Local", "XDG_CONFIG_HOME": ".home/.config",
              "XDG_DATA_HOME": ".home/.local/share", "XDG_CACHE_HOME": ".home/.cache",
              "TEMP": ".tmp", "TMP": ".tmp", "TMPDIR": ".tmp"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _redact(name: str, value: str) -> str:
    if _SECRET.search(name):
        return f"<redactado sha256:{_sha(value.encode('utf-8', 'replace'))[:16]}>"
    return value[:2000]


class _Normalizer:
    """Sustituye rutas del sandbox y valores de variables de ejecución para comparar ejecuciones."""

    def __init__(self, root: Path, variables: dict[str, str], extra: tuple[str, ...] = ()):
        forms = {str(root), root.as_posix(), str(root.resolve()), root.resolve().as_posix(), *extra}
        if os.name == "nt":
            forms |= {f.lower() for f in forms}
        self.paths = sorted({f for f in forms if f}, key=len, reverse=True)
        self.vars = sorted(((v, k) for k, v in variables.items() if len(v) >= 4), key=lambda x: -len(x[0]))

    def text(self, s: str) -> str:
        s = s.replace("\r\n", "\n")
        for p in self.paths:
            s = s.replace(p, "{sandbox}")
            s = s.replace(p.replace("\\", "\\\\"), "{sandbox}")   # rutas escapadas en JSON
        for v, k in self.vars:
            s = s.replace(v, "{var:" + k + "}")
        return s

    def data(self, b: bytes) -> bytes:
        try:
            return self.text(b.decode("utf-8")).encode("utf-8")
        except UnicodeDecodeError:
            return b

    def path_data(self, b: bytes) -> bytes:
        """Normaliza rutas del sandbox para reconstrucción sin sustituir valores de entorno observados."""
        try:
            text = b.decode("utf-8").replace("\r\n", "\n")
        except UnicodeDecodeError:
            return b
        for path in self.paths:
            text = text.replace(path, "{sandbox}")
            text = text.replace(path.replace("\\", "\\\\"), "{sandbox}")
        return text.encode("utf-8")


def _output(data: bytes, norm: _Normalizer) -> dict[str, Any]:
    try:
        text, utf8 = data.decode("utf-8"), True
    except UnicodeDecodeError:
        text, utf8 = data.decode("utf-8", "replace"), False
    ntext = norm.text(text)
    out = {"size": len(data), "sha256": _sha(data), "utf8": utf8,
           "sha256_normalized": _sha(ntext.encode("utf-8")) if utf8 else _sha(data),
           "preview": ntext[:PREVIEW]}
    if len(ntext) > PREVIEW:
        out["preview_truncated"] = True
    return out


def _identity(path: Path) -> dict[str, Any]:
    from eolfi.providers.triage import sha256_file

    try:
        return {"path": str(path), "sha256": sha256_file(path), "size": path.stat().st_size}
    except OSError as exc:
        return {"path": str(path), "error": type(exc).__name__}


# -- entorno ----------------------------------------------------------------------------------------
def _build_env(spec: dict[str, Any], root: Path, values: dict[str, str], variables: dict[str, str]
               ) -> tuple[dict[str, str], dict[str, Any]]:
    env: dict[str, str] = dict(os.environ) if spec["inherit"] else {}
    names = list(spec["passthrough"]) + (list(_WIN_DEFAULT_ENV) if os.name == "nt" else [])
    passed = {}
    for k in names:
        if k in os.environ:
            env[k] = os.environ[k]
            passed[k] = "sha256:" + _sha(os.environ[k].encode("utf-8", "replace"))[:16]
        else:
            passed[k] = "ausente"
    redirected = []
    if spec["redirect_home"]:
        for k, rel in _HOME_VARS.items():
            p = root / rel
            p.mkdir(parents=True, exist_ok=True)
            env[k] = str(p)
            redirected.append(k)
    declared = {}
    for k, v in spec["vars"].items():
        env[k] = expand(v, values, variables)
        declared[k] = _redact(k, v)
    record = {"inherit": spec["inherit"], "passthrough": passed, "redirected": redirected, "declared": declared}
    if spec["inherit"]:
        record["inherited_names"] = sorted(set(os.environ) - set(declared) - set(redirected))[:500]
    return env, record


def _resolve_program(argv0: str, cwd: Path, env: dict[str, str]) -> str:
    if os.path.isabs(argv0):
        return argv0
    if "/" in argv0 or "\\" in argv0:
        return str((cwd / argv0).resolve())
    found = shutil.which(argv0, path=env.get("PATH") or os.environ.get("PATH"))
    return found or argv0


# -- pasos ----------------------------------------------------------------------------------------------
def _run_process(argv: list[str], cwd: Path, env: dict[str, str], stdin: bytes | None, timeout: float,
                 children: bool) -> dict[str, Any]:
    from eolfi.flows.diff_flow import _kill_tree

    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as inp:
        if stdin is not None:
            inp.write(stdin)
            inp.seek(0)
        t0 = time.monotonic()
        try:
            proc = subprocess.Popen(argv, cwd=str(cwd), env=env,
                                    stdin=inp if stdin is not None else subprocess.DEVNULL,
                                    stdout=out, stderr=err, start_new_session=os.name != "nt")
        except OSError as exc:
            return {"status": "error", "error": f"{type(exc).__name__}: {exc}", "duration_ms": 0}
        sampler = probes.ChildSampler(proc.pid).start() if children else None
        timed_out = over = False
        deadline = t0 + timeout
        while True:
            try:
                proc.wait(timeout=0.05)
                break
            except subprocess.TimeoutExpired:
                if os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size > MAX_OUTPUT:
                    over = True
                elif time.monotonic() >= deadline:
                    timed_out = True
                if over or timed_out:
                    _kill_tree(proc)
                    proc.wait()
                    break
        duration = round((time.monotonic() - t0) * 1000)
        child_info = sampler.stop() if sampler else None
        out.seek(0)
        err.seek(0)
        res: dict[str, Any] = {"status": "timeout" if timed_out else "output_limit" if over else "ok",
                               "exit_code": proc.returncode, "exit_status": probes.exit_status(proc.returncode),
                               "duration_ms": duration, "stdout": out.read(MAX_OUTPUT), "stderr": err.read(MAX_OUTPUT)}
    if child_info is not None:
        survivors = [p for p in child_info["processes"] if _same_process_alive(p)]
        child_info["survivors"] = survivors
        res["children"] = child_info
    return res


def _same_process_alive(p: dict[str, Any]) -> bool:
    """Sigue vivo EL MISMO proceso observado: PID, nombre y hora de creación (si se pudo leer) coinciden."""
    if (p["pid"], p["name"]) not in {(pid, name) for pid, _ppid, name in probes.process_table()}:
        return False
    if p.get("start") is not None:
        return probes.process_start(p["pid"]) == p["start"]
    return probes.process_table_method() == "ps"   # sin hora de creación solo se confía en ps (sin verificación)


def _kill_survivors(survivors: list[dict[str, Any]]) -> list[str]:
    """Termina procesos lanzados por el objetivo que siguen vivos (mismo PID, nombre y creación que al observarlos).
    Nunca mata el árbol de un PID: solo cada superviviente verificado."""
    done = []
    for p in survivors:
        if not _same_process_alive(p):
            continue
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/PID", str(p["pid"])], capture_output=True, timeout=10)
            else:
                os.kill(p["pid"], 9)
            done.append(f"{p['name']} ({p['pid']})")
        except (OSError, subprocess.SubprocessError):
            pass
    return done


def _host_allowed(url: str, allow: list[str]) -> str | None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return f"esquema no admitido: {parts.scheme or '(vacío)'}"
    host = (parts.hostname or "").lower()
    if host in LOOPBACK or host in allow:
        return None
    return f"host no autorizado por el guion (allow_hosts): {host}"


class _Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow: list[str], log: list[dict[str, Any]], norm: _Normalizer):
        self.allow, self.log, self.norm = allow, log, norm

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401, ANN001
        reason = _host_allowed(newurl, self.allow)
        self.log.append({"status": code, "location": self.norm.text(newurl), **({"blocked": reason} if reason else {})})
        if reason:
            raise urllib.error.URLError(f"redirección bloqueada: {reason}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _cookies(jar: http.cookiejar.CookieJar) -> list[dict[str, Any]]:
    return sorted(({"domain": c.domain, "path": c.path, "name": c.name,
                    "value_sha256": _sha((c.value or "").encode("utf-8", "replace"))[:16]} for c in jar),
                  key=lambda c: (c["domain"], c["path"], c["name"]))


def _http_step(step: dict[str, Any], values: dict[str, str], variables: dict[str, str], allow: list[str],
               jar: http.cookiejar.CookieJar, norm: _Normalizer) -> dict[str, Any]:
    url = expand(step["url"], values, variables)
    headers = {k: expand(v, values, variables) for k, v in step["headers"].items()}
    body = content_bytes(step["body"]) if "body" in step else None
    req_rec = {"method": step["method"], "url": norm.text(url),
               "headers": {k: _redact(k, v) for k, v in sorted(headers.items())}}
    if body is not None:
        req_rec["body"] = {"size": len(body), "sha256": _sha(body)}
    trace: dict[str, Any] = {"step_id": step["id"], "request": req_rec}
    reason = _host_allowed(url, allow)
    if reason:
        trace["blocked"] = reason
        return {"status": "error", "error": reason, "traces": [trace], "storage": {"cookies": _cookies(jar)}}
    redirects: list[dict[str, Any]] = []
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar),
                                         _Redirects(allow, redirects, norm))
    req = urllib.request.Request(url, data=body, method=step["method"], headers=headers)
    t0 = time.monotonic()
    status, error = "ok", None
    try:
        resp = opener.open(req, timeout=step["timeout"])
    except urllib.error.HTTPError as exc:   # 4xx/5xx también son respuestas observadas
        resp = exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        resp, status, error = None, "error", f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}"
    if resp is not None:
        with resp:
            data = resp.read(MAX_HTTP_BODY + 1)
            rheaders = {}
            set_cookies = []
            for k, v in resp.headers.items():
                if k.lower() == "set-cookie":
                    set_cookies.append(v.split("=", 1)[0].strip())
                elif k.lower() not in ("date",):
                    rheaders[k] = _redact(k, v)
            trace["response"] = {"status": resp.status if hasattr(resp, "status") else resp.code,
                                 "headers": dict(sorted(rheaders.items())), "set_cookie_names": sorted(set_cookies),
                                 "body": _output(data[:MAX_HTTP_BODY], norm),
                                 **({"body_truncated": True} if len(data) > MAX_HTTP_BODY else {})}
    trace["duration_ms"] = round((time.monotonic() - t0) * 1000)
    if redirects:
        trace["redirects"] = redirects
    out = {"status": status, "traces": [trace], "storage": {"cookies": _cookies(jar)},
           "duration_ms": trace["duration_ms"]}
    if error:
        out["error"] = error
    return out


DRIVER = Path(__file__).with_name("browser_driver.mjs")


def _browser_step(step: dict[str, Any], values: dict[str, str], variables: dict[str, str], allow: list[str],
                  norm: _Normalizer, playwright: str | None) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        return {"status": "unavailable", "error": "Node.js no está instalado: no se puede conducir un navegador"}
    req = {"url": expand(step["url"], values, variables), "timeout_ms": int(step["timeout"] * 1000),
           "allow_hosts": sorted(LOOPBACK | set(allow)), "viewport": step.get("viewport"),
           "actions": [{**a, **({"url": expand(a["url"], values, variables)} if "url" in a else {}),
                        **({"value": expand(a["value"], values, variables)} if "value" in a else {})}
                       for a in step["actions"]]}
    env = dict(os.environ)
    if playwright:
        env["EOLFI_PLAYWRIGHT"] = playwright
    with tempfile.TemporaryDirectory(prefix="eolfi-obs-browser-") as tmp:
        rpath = Path(tmp, "request.json")
        rpath.write_text(json.dumps(req), encoding="utf-8")
        t0 = time.monotonic()
        try:
            proc = subprocess.run([node, str(DRIVER), str(rpath)], capture_output=True, timeout=step["timeout"] + 30,
                                  env=env)
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "error": "el controlador del navegador no terminó a tiempo"}
        duration = round((time.monotonic() - t0) * 1000)
    try:
        res = json.loads(proc.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"status": "error", "error": "respuesta inválida del controlador: "
                + proc.stderr.decode("utf-8", "replace")[-1000:], "duration_ms": duration}
    out: dict[str, Any] = {"status": res.get("status", "error"), "duration_ms": duration}
    for k in ("error", "browser"):
        if k in res:
            out[k] = res[k]
    actions = []
    for a in res.get("actions", []):
        a = json.loads(norm.text(json.dumps(a, ensure_ascii=False)))
        for r in a.get("requests", []):
            r["step_id"] = step["id"]
            r["action_id"] = a.get("id")
        actions.append(a)
    out["actions"] = actions
    out["traces"] = [r for a in actions for r in a.get("requests", [])]
    return out


UIA_DRIVER = Path(__file__).with_name("uia_driver.ps1")


_WINFORMS_CLASS = re.compile(r"^(WindowsForms10\.[A-Za-z0-9_]+)\..*$")
_HWND_CLASS = re.compile(r"^(HwndWrapper\[[^;\]]*)(;[^\]]*)?\]$")


def normalize_window(w: Any) -> Any:
    """Quita del árbol de UI lo que cambia en cada proceso sin cambiar la interfaz: el sufijo de dominio de
    aplicación de las clases WinForms/WPF y los AutomationId numéricos (handles de ventana de controles sin
    nombre). Se marca qué se normalizó."""
    if not isinstance(w, dict):
        return w
    out = dict(w)
    cls = str(out.get("class") or "")
    m = _WINFORMS_CLASS.match(cls) or _HWND_CLASS.match(cls)
    if m:
        out["class"] = m.group(1) + ("]" if cls.startswith("HwndWrapper") else "")
        out["class_normalized"] = True
    elems = []
    for e in out.get("elements") or []:
        if isinstance(e, dict) and str(e.get("automation_id") or "").isdigit():
            e = {**e, "automation_id": "#handle"}
        elems.append(e)
    out["elements"] = elems
    return out


def _desktop_step(step: dict[str, Any], argv: list[str], cwd: Path, env: dict[str, str],
                  norm: _Normalizer) -> dict[str, Any]:
    """Lanza la aplicación, la conduce con UI Automation y registra ventanas/árbol de accesibilidad por acción."""
    from eolfi.flows.diff_flow import _kill_tree

    if sys.platform != "win32":
        return {"status": "unavailable", "error": "la captura de interfaz de escritorio solo está implementada en "
                                                  "Windows (UI Automation)"}
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if shell is None:
        return {"status": "unavailable", "error": "PowerShell no disponible para UI Automation"}
    t0 = time.monotonic()
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err, \
            tempfile.TemporaryDirectory(prefix="eolfi-obs-uia-") as tmp:
        try:
            proc = subprocess.Popen(argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err)
        except OSError as exc:
            return {"status": "error", "error": f"{type(exc).__name__}: {exc}", "duration_ms": 0}
        rpath = Path(tmp, "request.json")
        rpath.write_text(json.dumps({"pid": proc.pid, "timeout_ms": int(step["timeout"] * 1000),
                                     "actions": step["actions"], "close": step["close"],
                                     "screenshots": step.get("screenshots", False)}), encoding="utf-8")
        res: dict[str, Any]
        try:
            drv = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass",
                                  "-File", str(UIA_DRIVER), str(rpath)], capture_output=True,
                                 timeout=step["timeout"] + 30)
            raw = drv.stdout.decode("utf-8", "replace").strip()
            res = json.loads(raw[raw.find("{"):]) if "{" in raw else {
                "status": "error", "error": "sin respuesta del controlador: "
                + drv.stderr.decode("utf-8", "replace")[-800:]}
        except subprocess.TimeoutExpired:
            res = {"status": "timeout", "error": "el controlador de UI Automation no terminó a tiempo"}
        except json.JSONDecodeError:
            res = {"status": "error", "error": "respuesta inválida del controlador de UI Automation"}
        killed = False
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            proc.wait()
            killed = True
        out.seek(0)
        err.seek(0)
        stdout, stderr = out.read(MAX_OUTPUT), err.read(MAX_OUTPUT)
    actions = [json.loads(norm.text(json.dumps(a, ensure_ascii=False))) for a in res.get("actions") or []]
    for a in actions:
        wins = a.get("windows") or []
        a["windows"] = [normalize_window(w) for w in (wins if isinstance(wins, list) else [wins])]
        a["windows_sha256"] = _sha(json.dumps(a["windows"], sort_keys=True, ensure_ascii=False).encode("utf-8"))
        shot = a.get("screenshot")
        if isinstance(shot, dict) and shot.get("status") == "captured":
            encoded = shot.pop("data_base64", "")
            try:
                data = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError):
                shot.clear()
                shot.update(status="invalid_capture")
            else:
                actual_sha = _sha(data)
                if len(data) != shot.get("bytes") or actual_sha != shot.get("sha256"):
                    shot.clear()
                    shot.update(status="integrity_error")
                else:
                    shot["data_base64"] = encoded
                    shot["sha256"] = actual_sha
        if step.get("screenshots") and (not isinstance(shot, dict) or shot.get("status") != "captured"):
            res["status"] = "partial"
            res["error"] = f"captura visual no completa: {shot.get('status') if isinstance(shot, dict) else 'sin resultado'}"
    rec: dict[str, Any] = {"status": res.get("status", "error"), "duration_ms": round((time.monotonic() - t0) * 1000),
                           "screenshots_requested": step.get("screenshots", False),
                           "driver": {"name": "Windows UI Automation (PowerShell)", "path": shell},
                           "actions": actions, "exit_code": proc.returncode,
                           "exit_status": probes.exit_status(proc.returncode), "killed_after_close": killed,
                           "stdout": _output(stdout, norm), "stderr": _output(stderr, norm)}
    if res.get("error"):
        rec["error"] = str(res["error"])[:1000]
    if killed and rec["status"] == "ok":
        rec["status"] = "partial"
        rec["error"] = "la aplicación no se cerró tras la última acción: se terminó"
    return rec


def _ui_desktop_coverage(steps: list[dict[str, Any]]) -> Any:
    desk = [s for s in steps if s["action"] == "desktop"]
    if not desk:
        return "not_requested"
    if all(s["status"] == "ok" for s in desk):
        requested = any(s.get("screenshots_requested") for s in desk)
        return {"status": "observed", "method": "Windows UI Automation",
                "screenshots": "captured" if requested else "not_requested",
                "limits": "árbol de accesibilidad acotado (300 elementos por ventana) de las ventanas del proceso "
                          "lanzado; capturas opcionales limitadas a 20 imágenes JPEG de 256 KiB por paso; "
                          "contenido visual sin redacción automática; controles sin UI Automation no se ven"}
    requested = any(s.get("screenshots_requested") for s in desk)
    return {"status": "partial", "screenshots": "partial" if requested else "not_requested",
            "reason": "; ".join(sorted({str(s.get("error", s["status"]))[:200]
                                         for s in desk if s["status"] != "ok"}))}


CONTAINER_SANDBOX = "/sandbox"
ISOLATION_CONTAINER = ("contenedor: los pasos run se ejecutan en {image} sin red, con sistema de archivos de solo "
                       "lectura salvo el sandbox montado, usuario sin privilegios (65534), sin capacidades, sin "
                       "credenciales del anfitrión y con límites de memoria {memory}, CPU {cpus} y {pids} procesos. "
                       "Comparte el núcleo de la VM de Docker: no equivale a una VM dedicada. Los pasos http y "
                       "browser se ejecutan en el anfitrión.")


def container_runtime(image: str) -> dict[str, Any]:
    """Docker disponible y la imagen presente localmente (nunca se descarga desde aquí)."""
    exe = shutil.which("docker")
    if not exe:
        return {"ok": False, "reason": "Docker no está instalado"}
    try:
        p = subprocess.run([exe, "image", "inspect", image, "--format", "{{.Id}}"], capture_output=True, text=True,
                           timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "reason": f"Docker no responde: {type(exc).__name__}"}
    if p.returncode != 0:
        return {"ok": False, "reason": f"la imagen {image} no está en local (descárgala tú con docker pull) o el "
                                       f"servicio de Docker está parado"}
    ver = subprocess.run([exe, "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True,
                         timeout=60).stdout.strip()
    return {"ok": True, "docker": exe, "image": image, "image_id": p.stdout.strip(), "docker_version": ver}


def _run_container(rt: dict[str, Any], iso: dict[str, Any], root: Path, argv: list[str], workdir: str,
                   env: dict[str, str], stdin: bytes | None, timeout: float) -> dict[str, Any]:
    name = "eolfi-obs-" + uuid.uuid4().hex[:16]
    cmd = [rt["docker"], "run", "--rm", "-i", "--name", name, "--pull", "never", "--network", "none", "--read-only",
           "--tmpfs", "/tmp:rw,size=64m", "--memory", iso["memory"], "--cpus", str(iso["cpus"]),
           "--pids-limit", str(iso["pids"]), "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
           "--user", "65534:65534", "-v", f"{root.resolve()}:{CONTAINER_SANDBOX}", "-w", workdir]
    for k, v in sorted(env.items()):
        cmd += ["-e", f"{k}={v}"]
    cmd += [iso["image"], *argv]
    host_env = {k: v for k, v in os.environ.items() if k.upper() in (
        "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "USERPROFILE", "APPDATA",
        "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "HOME", "DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_CONTEXT")}
    r = _run_process(cmd, root, host_env, stdin, timeout, False)
    if r.get("status") != "ok":   # plazo/salida agotados: el cliente murió, el contenedor puede seguir vivo
        subprocess.run([rt["docker"], "rm", "-f", name], capture_output=True, timeout=60)
    if r.get("exit_code") == 125:
        r = {**r, "status": "error", "error": "Docker no pudo crear el contenedor: "
             + r.get("stderr", b"").decode("utf-8", "replace")[-500:]}
    return r


# -- sesión ------------------------------------------------------------------------------------------
def static_unfixed_factors(script: dict[str, Any]) -> list[dict[str, str]]:
    """Factores externos que el guion no puede fijar, conocidos antes de ejecutar."""
    f = [{"factor": "reloj", "detail": "Eolfi no virtualiza la fecha/hora: salidas que dependan del reloj variarán"},
         {"factor": "planificación y PID", "detail": "orden de planificación, PID y tiempos dependen del SO"}]
    env = script["environment"]
    if env["inherit"]:
        f.append({"factor": "entorno heredado", "detail": "el entorno del operador se hereda y no queda fijado"})
    if env["redirect_home"]:
        f.append({"factor": "rutas conocidas del SO", "detail": "HOME/APPDATA/TEMP se redirigen solo por variables "
                  "de entorno; un programa que consulte la API del SO usa las rutas reales"})
    else:
        f.append({"factor": "carpetas del usuario", "detail": "HOME/APPDATA reales: su estado no se fija"})
    external = [s for s in script["scope"]["files"] if os.path.isabs(s)]
    if external or script["scope"]["registry"]:
        f.append({"factor": "estado externo", "detail": "rutas/claves fuera del sandbox no se restauran entre "
                  "ejecuciones: " + ", ".join(external + script["scope"]["registry"])[:1000]})
    if [h for h in script["allow_hosts"] if h not in LOOPBACK]:
        f.append({"factor": "red externa", "detail": "hosts no locales autorizados: "
                  + ", ".join(script["allow_hosts"])[:1000]})
    if any(s["action"] == "browser" for s in script["steps"]):
        f.append({"factor": "navegador", "detail": "motor y versión del navegador (se registran); atribución de "
                  "peticiones por ventana temporal de cada acción"})
    if script.get("isolation", {}).get("mode") == "container":
        f.append({"factor": "imagen del contenedor", "detail": f"{script['isolation']['image']}: su identificador se "
                  "registra en cada sesión; otra versión de la imagen puede cambiar el resultado"})
    names = sorted(referenced_variables(script))
    if names:
        f.append({"factor": "variables de ejecución", "detail": "se indican al ejecutar: " + ", ".join(names)})
    return f


def _coverage(script: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any]:
    actions = {s["action"] for s in script["steps"]}
    reg = script["scope"]["registry"]
    browser = [s for s in steps if s["action"] == "browser"]
    return {
        "process_io": "observed" if "run" in actions else "not_requested",
        "exit_status_signals": ("observed" if "run" in actions else "not_requested"),
        "files": {"status": "observed", "scope": script["scope"]["files"],
                  "limits": "instantánea antes/después de cada paso: un cambio revertido dentro del mismo paso no "
                            "se ve; sin enlaces simbólicos; tope de archivos y de bytes por hash"},
        "registry": ("not_requested" if not reg else "observed" if probes.registry_available()
                     else {"status": "not_available", "reason": "el registro solo existe en Windows"}),
        "children": ({"status": "not_available", "reason": "los procesos dentro del contenedor no se muestrean desde "
                                                          "el anfitrión"} if script.get("isolation", {}).get("mode") == "container"
                     else "not_requested" if not script["scope"]["children"] or "run" not in actions else
                     {"status": "sampled", "method": probes.process_table_method(),
                      "limits": "muestreo periódico: procesos de vida más corta que el intervalo pueden no verse; "
                                "los PID no son reproducibles"}),
        "system_calls": {"status": "not_available",
                         "reason": "Eolfi no traza llamadas al sistema; usa un trazador (strace/ETW/dtrace) o REA "
                                   "(instrument_with_frida, capture_process_scenario) con autorización"},
        "network": ("not_requested" if not actions & {"http", "browser"} else
                    {"status": "observed", "limits": "solo el tráfico de los pasos http/browser del guion; el "
                     "tráfico propio del objetivo no se captura"}),
        "ui_web": ("not_requested" if not browser else
                   "observed" if all(s["status"] == "ok" for s in browser) else
                   {"status": "partial", "reason": "; ".join(sorted({str(s.get('error', s['status']))[:200]
                                                                     for s in browser if s["status"] != "ok"}))}),
        "ui_desktop": _ui_desktop_coverage(steps),
        "ui_mobile": {"status": "not_available",
                      "reason": "Eolfi no automatiza interfaces móviles; ver REA capture_adb_screen / "
                                "capture_native_ui_scenario con un dispositivo autorizado"},
    }


def _file_roots(script: dict[str, Any], root: Path) -> list[tuple[str, Path]]:
    roots = []
    for s in script["scope"]["files"]:
        if os.path.isabs(s):
            roots.append((Path(s).as_posix(), Path(s)))
        else:
            rel = s.replace("\\", "/").strip("/")
            if ".." in rel.split("/"):
                raise ScriptError(f"scope.files fuera del sandbox: {s}")
            roots.append(("{sandbox}" + ("" if rel in ("", ".") else "/" + rel), root / rel))
    return roots


def _effects(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    return probes.diff_mapping(before, after)


def _subject(script: dict[str, Any], target: dict[str, Any] | None) -> str:
    if target and target.get("sha256"):
        return target["sha256"]
    return "cmd:observe:" + script_sha256(script)


def load_script(source: str | Path | dict[str, Any]) -> tuple[dict[str, Any], Path]:
    if isinstance(source, dict):
        return validate_script(source), Path.cwd()
    p = Path(source)
    if p.stat().st_size > 1024 * 1024:
        raise ScriptError("guion mayor que 1 MB")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScriptError(f"guion no es JSON UTF-8 válido: {exc}") from None
    return validate_script(raw), p.resolve().parent


def execute(script: dict[str, Any], base_dir: Path, *, variables: dict[str, str] | None = None,
            keep_sandbox: bool = False, playwright: str | None = None,
            on_step: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Ejecuta el guion (ya validado) y devuelve el registro de la sesión. No escribe en la base."""
    variables = dict(variables or {})
    missing = referenced_variables(script) - set(variables)
    if missing:
        raise ScriptError("faltan variables de ejecución: " + ", ".join(sorted(missing)))
    from eolfi.core.cases import environment_identity

    session_id = str(uuid.uuid4())
    target = None
    if "target" in script:
        tpath = Path(script["target"]["path"])
        tpath = tpath if tpath.is_absolute() else (base_dir / tpath)
        if not tpath.is_file():
            raise ScriptError(f"no existe el objetivo: {tpath}")
        target = {**_identity(tpath.resolve()), "version": script["target"]["version"],
                  "provenance": script["target"]["provenance"]}
        if script["target"].get("sha256") and script["target"]["sha256"] != target["sha256"]:
            raise ScriptError("el SHA-256 del objetivo no coincide con el declarado en el guion")
    iso = script.get("isolation", {"mode": "none"})
    rt = container_runtime(iso["image"]) if iso["mode"] == "container" else None
    root = Path(tempfile.mkdtemp(prefix="eolfi-obs-"))
    norm = _Normalizer(root, variables, (CONTAINER_SANDBOX,) if rt else ())
    values = {"sandbox": str(root), "python": sys.executable, **({"target": target["path"]} if target else {})}
    cvalues = None
    if rt and rt["ok"]:
        cvalues = {"sandbox": CONTAINER_SANDBOX, "python": "python"}
        if target:   # el objetivo entra en el contenedor como copia dentro del sandbox (solo lectura no aplica)
            tdir = root / ".eolfi-objetivo"
            tdir.mkdir()
            shutil.copy2(target["path"], tdir / Path(target["path"]).name)
            cvalues["target"] = f"{CONTAINER_SANDBOX}/.eolfi-objetivo/{Path(target['path']).name}"
    started = time.time()
    t0 = time.monotonic()
    steps_out: list[dict[str, Any]] = []
    programs: dict[str, dict[str, Any]] = {}
    survivors: list[dict[str, Any]] = []
    setup_rec: dict[str, Any] = {}
    capture_remaining = probes.MAX_CAPTURE_SESSION_BYTES
    file_capture_statuses: list[str] = []
    try:
        for rel, spec in script["setup"]["files"].items():
            data = content_bytes(spec, base_dir)
            if spec.get("sha256") and spec["sha256"] != _sha(data):
                raise ScriptError(f"setup.files[{rel!r}]: el SHA-256 no coincide con el declarado")
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            setup_rec[rel] = {"size": len(data), "sha256": _sha(data), **({"copied_from": spec["copy"]}
                                                                          if "copy" in spec else {})}
        env, env_rec = _build_env(script["environment"], root, values, variables)
        roots = _file_roots(script, root)
        reg_keys = script["scope"]["registry"]
        fsnap = probes.snapshot_files(roots, norm.data)
        rsnap = probes.snapshot_registry(reg_keys) if reg_keys else None
        initial = {"files": fsnap["files"], "files_truncated": fsnap["truncated"],
                   **({"registry": rsnap["values"], "registry_missing": rsnap["missing"]} if rsnap else {})}
        jar = http.cookiejar.CookieJar()
        for step in script["steps"]:
            rec: dict[str, Any] = {"id": step["id"], "action": step["action"],
                                   "started_ms": round((time.monotonic() - t0) * 1000)}
            try:
                if step["action"] == "run" and rt is not None:
                    stdin = content_bytes(step["stdin"]) if "stdin" in step else None
                    if not rt["ok"]:
                        rec.update(status="unavailable", error=rt["reason"])
                    else:
                        argv = [expand(a, cvalues, variables) for a in step["argv"]]
                        cenv = {"HOME": f"{CONTAINER_SANDBOX}/.home", "TMPDIR": f"{CONTAINER_SANDBOX}/.tmp",
                                **{k: expand(v, cvalues, variables) for k, v in script["environment"]["vars"].items()},
                                **{k: expand(v, cvalues, variables) for k, v in step["env"].items()}}
                        workdir = CONTAINER_SANDBOX + ("/" + step["cwd"] if "cwd" in step else "")
                        (root / ".home").mkdir(exist_ok=True)
                        (root / ".tmp").mkdir(exist_ok=True)
                        if "cwd" in step:
                            (root / step["cwd"]).mkdir(parents=True, exist_ok=True)
                        r = _run_container(rt, iso, root, argv, workdir, cenv, stdin, step["timeout"])
                        rec.update(argv=[norm.text(a) for a in argv], isolation="container",
                                   env_overrides={k: _redact(k, v) for k, v in step["env"].items()},
                                   stdin={"size": len(stdin), "sha256": _sha(stdin)} if stdin is not None else None,
                                   status=r["status"], duration_ms=r["duration_ms"])
                        if "error" in r:
                            rec["error"] = r["error"]
                        else:
                            rec.update(exit_code=r["exit_code"], exit_status=probes.exit_status(r["exit_code"]),
                                       stdout=_output(r["stdout"], norm), stderr=_output(r["stderr"], norm))
                elif step["action"] == "run":
                    cwd = root / step["cwd"] if "cwd" in step else root
                    cwd.mkdir(parents=True, exist_ok=True)
                    argv = [expand(a, values, variables) for a in step["argv"]]
                    senv = {**env, **{k: expand(v, values, variables) for k, v in step["env"].items()}}
                    argv[0] = _resolve_program(argv[0], cwd, senv)
                    if os.path.isfile(argv[0]) and argv[0] not in programs:
                        programs[argv[0]] = _identity(Path(argv[0]))
                    stdin = content_bytes(step["stdin"]) if "stdin" in step else None
                    r = _run_process(argv, cwd, senv, stdin, step["timeout"], script["scope"]["children"])
                    rec.update(argv=[norm.text(a) for a in argv], env_overrides={k: _redact(k, v) for k, v in
                                                                                 step["env"].items()},
                               stdin={"size": len(stdin), "sha256": _sha(stdin)} if stdin is not None else None,
                               status=r["status"], duration_ms=r["duration_ms"])
                    if "error" in r:
                        rec["error"] = r["error"]
                    else:
                        rec.update(exit_code=r["exit_code"], exit_status=r["exit_status"],
                                   stdout=_output(r["stdout"], norm), stderr=_output(r["stderr"], norm))
                    if "children" in r:
                        rec["children"] = r["children"]
                        survivors += r["children"]["survivors"]
                elif step["action"] == "write_file":
                    dst = root / step["path"]
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    data = content_bytes(step["content"])
                    dst.write_bytes(data)
                    rec.update(status="ok", path=step["path"], input={"size": len(data), "sha256": _sha(data)})
                elif step["action"] == "delete_file":
                    dst = root / step["path"]
                    existed = dst.is_file()
                    if existed:
                        dst.unlink()
                    rec.update(status="ok" if existed else "error", path=step["path"],
                               **({} if existed else {"error": "el archivo no existía"}))
                elif step["action"] == "http":
                    rec.update(_http_step(step, values, variables, script["allow_hosts"], jar, norm))
                elif step["action"] == "desktop":
                    cwd = root / step["cwd"] if "cwd" in step else root
                    cwd.mkdir(parents=True, exist_ok=True)
                    argv = [expand(a, values, variables) for a in step["argv"]]
                    senv = {**env, **{k: expand(v, values, variables) for k, v in step["env"].items()}}
                    argv[0] = _resolve_program(argv[0], cwd, senv)
                    if os.path.isfile(argv[0]) and argv[0] not in programs:
                        programs[argv[0]] = _identity(Path(argv[0]))
                    rec["argv"] = [norm.text(a) for a in argv]
                    rec.update(_desktop_step(step, argv, cwd, senv, norm))
                elif step["action"] == "browser":
                    rec.update(_browser_step(step, values, variables, script["allow_hosts"], norm, playwright))
            except ScriptError:
                raise
            except Exception as exc:  # noqa: BLE001 — se registra el fallo del paso y la sesión sigue
                rec.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:1000]}")
            after = probes.snapshot_files(roots, norm.data)
            file_effects = _effects(fsnap["files"], after["files"])
            selected_paths = script["scope"].get("capture_contents", [])
            changed_paths = [e["path"] for e in file_effects
                             if e["change"] in ("created", "modified") and e["path"] in selected_paths]
            if selected_paths:
                rec["file_capture_requested"] = True
                rec["file_capture_paths"] = selected_paths
            if changed_paths:
                contents, capture_remaining = probes.capture_file_contents(roots, changed_paths, capture_remaining)
                for effect in file_effects:
                    capture = contents.get(effect["path"])
                    if capture:
                        if capture.get("status") == "captured":
                            raw = base64.b64decode(capture["data_base64"], validate=True)
                            normalized = norm.path_data(raw)
                            try:
                                raw.decode("utf-8")
                                is_utf8 = True
                            except UnicodeDecodeError:
                                is_utf8 = False
                            capture.update(raw_sha256=capture["sha256"], sha256=_sha(normalized),
                                           data_base64=base64.b64encode(normalized).decode("ascii"), utf8=is_utf8)
                        effect.setdefault("after", {})["content_capture"] = capture
                        file_capture_statuses.append(capture.get("status", "unknown"))
                        if capture.get("status") != "captured" and rec.get("status") == "ok":
                            rec["status"] = "partial"
                            rec["error"] = f"contenido de archivo solicitado no capturado: {capture.get('status')}"
            rec["effects"] = {"files": file_effects}
            fsnap = after
            if rsnap is not None:
                rafter = probes.snapshot_registry(reg_keys)
                rec["effects"]["registry"] = _effects(rsnap["values"], rafter["values"])
                rsnap = rafter
            steps_out.append(rec)
            if on_step:
                on_step(rec)
        final = {"files": fsnap["files"], "files_truncated": fsnap["truncated"],
                 **({"registry": rsnap["values"]} if rsnap else {})}
    finally:
        killed = _kill_survivors(survivors) if survivors else []
        cleanup: dict[str, Any] = {"killed_survivors": killed,
                                   "registry": "no se restaura" if script["scope"]["registry"] else "no aplica",
                                   "external_files": "no se restauran" if any(os.path.isabs(s) for s in
                                                                              script["scope"]["files"]) else "no aplica"}
        if keep_sandbox or not script["cleanup"]["remove_sandbox"]:
            cleanup["sandbox"] = "conservado"
            cleanup["kept_at"] = str(root)
        else:
            errors: list[str] = []
            if sys.version_info >= (3, 12):
                shutil.rmtree(root, onexc=lambda _f, p, e: errors.append(f"{Path(p).name}: {type(e).__name__}"))
            else:
                shutil.rmtree(root, onerror=lambda _f, p, e: errors.append(f"{Path(p).name}: {e[0].__name__}"))
            cleanup["sandbox"] = "eliminado" if not root.exists() else "eliminado parcialmente"
            if errors:
                cleanup["errors"] = errors[:20]
    # Datos personales y secretos en el texto guardado (los hashes ya se calcularon sobre los bytes reales).
    from eolfi.security.privacy import LIMITS as _PRIVACY_LIMITS
    from eolfi.security.privacy import redact_tree

    redacted: dict[str, int] = {}
    privacy_on = script.get("privacy", {}).get("redact_personal_data", True)
    if privacy_on:
        steps_out = redact_tree(steps_out, {"preview", "text_preview", "text", "message"}, redacted)
    env_id = environment_identity()
    env_id.update(process_table=probes.process_table_method(),
                  registry="disponible" if probes.registry_available() else "no disponible")
    return {
        "session_id": session_id, "name": script["name"], "script_sha256": script_sha256(script),
        "authorization": script["authorization"],
        "isolation": (ISOLATION_CONTAINER.format(**iso) if rt and rt["ok"] else ISOLATION),
        "isolation_mode": "container" if rt and rt["ok"] else "none",
        **({"container": {k: rt[k] for k in ("image", "image_id", "docker_version")}} if rt and rt["ok"] else {}),
        "target": target, "programs": sorted(programs.values(), key=lambda p: p["path"]),
        "platform": env_id, "environment": env_rec, "variables": {k: _redact(k, v) for k, v in variables.items()},
        "setup": setup_rec, "initial_state": initial, "steps": steps_out, "final_state": final,
        "started_at": started, "duration_ms": round((time.monotonic() - t0) * 1000), "cleanup": cleanup,
        "coverage": {**_coverage(script, steps_out), "personal_data": (
            {"status": "redacted", "redacted": redacted, "limits": _PRIVACY_LIMITS} if privacy_on else
            {"status": "not_redacted", "reason": "desactivado en el guion (privacy.redact_personal_data=false)"}),
            "visual_content": ({"status": "not_redacted", "reason": "la captura de ventana no admite redacción visual; "
                               "revisar el contenido del objetivo antes de habilitar screenshots"}
                               if any(s.get("action") == "desktop" and s.get("screenshots") for s in script["steps"])
                               else {"status": "not_requested"}),
            "file_contents": ({"status": ("captured" if file_capture_statuses and
                                            all(s == "captured" for s in file_capture_statuses) else
                                            "partial" if file_capture_statuses else
                                            "not_observed" if not script["scope"].get("capture_contents") else "no_changes"),
                               "not_redacted": True, "paths": script["scope"].get("capture_contents", []),
                               "limits": f"captura optativa; máximo {probes.MAX_CAPTURE_FILE_BYTES} bytes por archivo y "
                                         f"{probes.MAX_CAPTURE_SESSION_BYTES} bytes por sesión"}
                              if script["scope"].get("capture_contents") else {"status": "not_requested"})},
        "unfixed_factors": static_unfixed_factors(script),
        "status": "done" if all(s["status"] == "ok" for s in steps_out) else "partial",
    }


def _claims(session: dict[str, Any], eid: str) -> list[dict[str, Any]]:
    claims = []
    for s in session["steps"][:200]:
        if s["action"] == "run" and "exit_code" in s:
            st = s["exit_status"]
            how = (f"código {st['code']}" if st["kind"] == "exit" else
                   f"señal {st.get('signal_name')}" if st["kind"] == "signal" else st.get("name", str(st)))
            text = (f"Paso {s['id']}: el proceso terminó con {how}; stdout {s['stdout']['size']} B "
                    f"(sha256 {s['stdout']['sha256'][:12]}), {len(s['effects']['files'])} cambios de archivo")
        elif s["action"] == "http" and s.get("traces") and "response" in s["traces"][0]:
            text = f"Paso {s['id']}: {s['traces'][0]['request']['method']} respondió {s['traces'][0]['response']['status']}"
        elif s["action"] == "desktop" and s["status"] == "ok":
            text = f"Paso {s['id']}: {len(s.get('actions', []))} instantáneas de interfaz (UI Automation)"
        elif s["action"] == "browser" and s["status"] == "ok":
            text = f"Paso {s['id']}: {len(s.get('actions', []))} acciones de navegador con {len(s.get('traces', []))} peticiones"
        else:
            continue
        claims.append({"text": text, "status": "observed", "evidence_ids": [eid],
                       "limits": "observado en una sola ejecución; el alcance está en coverage"})
    return claims


def store_session(store: EvidenceStore, session: dict[str, Any], script: dict[str, Any], *,
                  replay_of: str | None = None, base_dir: Path | None = None,
                  operation: str = OPERATION) -> tuple[str, str]:
    subject = _subject(script, session["target"])
    params = {"session_id": session["session_id"], "script": script, "script_sha256": session["script_sha256"],
              "variables": session["variables"], **({"replay_of": replay_of} if replay_of else {}),
              **({"base_dir": str(base_dir)} if base_dir else {})}
    ev = Evidence(subject=subject, provider=PROVIDER, provider_version=VERSION, operation=operation, params=params,
                  result=session, authority=Authority.CONTROLLED_REPRO, confidence=Confidence.MEDIUM,
                  limitations="Una ejecución observada con el alcance declarado en coverage; no prueba el "
                              "comportamiento con otras entradas ni entornos. " + ISOLATION,
                  environment=f"{session['platform']['os']} {session['platform']['os_release']} "
                              f"{session['platform']['machine']}")
    eid, _ = store.add_evidence(ev)
    return eid, subject


def run_observation(source: str | Path | dict[str, Any], store: EvidenceStore, *, authorized: bool,
                    variables: dict[str, str] | None = None, case_id: str | None = None,
                    keep_sandbox: bool = False, playwright: str | None = None, provenance: str = "",
                    base_dir: str | Path | None = None, _replay_of: str | None = None) -> dict[str, Any]:
    """Valida, ejecuta y guarda una sesión. ``authorized`` debe ser True: el operador confirma que puede
    ejecutar el objetivo (además del campo ``authorization`` del guion)."""
    if not authorized:
        raise PermissionError("la observación EJECUTA el objetivo: confirma la autorización (--autorizo)")
    from eolfi.core.cases import case_run, file_identity

    script, bdir = load_script(source)
    if base_dir is not None:
        bdir = Path(base_dir)
    params = {"script": str(source) if not isinstance(source, dict) else "(objeto)", "name": script["name"],
              "variables": sorted((variables or {}).keys()), **({"replay_of": _replay_of} if _replay_of else {})}
    with case_run(store, case_id, "observe", params, provenance or script["authorization"]) as run:
        session = execute(script, bdir, variables=variables, keep_sandbox=keep_sandbox, playwright=playwright)
        from eolfi.security.levels import flow_level

        from eolfi.security.levels import LEVELS

        session["data_handling"] = {
            **(flow_level("observe") if session.get("isolation_mode") != "container"
               else {"level": "isolated", **LEVELS["isolated"], "isolation": "contenedor (pasos run)"}),
            "stored_in": str(Path(store.path).resolve()) if store.path != ":memory:" else ":memory:",
            "retention": "hasta que la borres", "deletion": "eolfi observe forget <evidence_id> --confirmo"}
        eid, subject = store_session(store, session, script, replay_of=_replay_of, base_dir=bdir)
        rep = {"evidence_id": eid, "subject": subject, **session}
        if run.active:
            if session["target"]:
                sha, info = file_identity(session["target"]["path"])
                info.update(version=session["target"]["version"], metadata={"role": "objetivo observado"})
                run.artifact(sha, provenance=session["target"]["provenance"] or script["authorization"], **info)
            else:
                run.artifact(subject, size=None, format="observation-script", identity="derived", content_sha256="",
                             metadata={"note": "sesión sin objetivo declarado: subject = huella del guion"})
            tools = [{"name": PROVIDER, "version": VERSION, "status": "ran"},
                     {"name": "python", "version": session["platform"]["python"], "status": "ran"}]
            for s in session["steps"]:
                b = s.get("browser")
                if isinstance(b, dict) and b.get("name"):
                    t = {"name": str(b["name"]), "version": str(b.get("version", "")), "status": "ran"}
                    if t not in tools:
                        tools.append(t)
            errors = [f"{s['id']}: {s.get('error') or s['status']}" for s in session["steps"] if s["status"] != "ok"]
            run.finish(status=session["status"], evidence_ids=[eid], tools=tools, errors=errors[:200],
                       claims=_claims(session, eid),
                       result={"session_id": session["session_id"], "steps": len(session["steps"]),
                               "status": session["status"], "coverage": session["coverage"],
                               "unfixed_factors": [f["factor"] for f in session["unfixed_factors"]]})
            rep["case_record"] = run.record_id
        return rep


def load_session(store: EvidenceStore, evidence_id: str) -> dict[str, Any]:
    ev = store.get_evidence(evidence_id)
    if ev is None or ev["provider"] != PROVIDER or ev["operation"] not in (OPERATION,):
        raise ValueError(f"no es una sesión de observación: {evidence_id}")
    return {"evidence_id": evidence_id, "subject": ev["subject"], "params": json.loads(ev["params"]),
            "session": json.loads(ev["result"])}


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")
