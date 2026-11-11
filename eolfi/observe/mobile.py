"""Paso de observación «mobile»: interfaz de una app Android conducida con adb y uiautomator.

El paso no instala nada ni concede permisos: la app debe estar ya instalada en un dispositivo o emulador que el
operador haya conectado y autorizado. Eolfi la lanza, ejecuta las acciones del guion (pulsar, escribir, teclas,
esperar, leer) y, tras cada una, registra la actividad en primer plano y el árbol de accesibilidad de la pantalla
(``uiautomator dump``). Opcionalmente guarda una captura PNG por acción (``screencap``).

``adb`` se busca en la variable de entorno ``EOLFI_ADB`` y, si no está, en el PATH. Sin adb o sin un único
dispositivo listo, el paso queda «unavailable» y la cobertura de interfaz móvil no se declara observada.
iOS no está implementado.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import time
import xml.etree.ElementTree as ET
from typing import Any, Callable

MAX_ELEMENTS = 300
MAX_DUMP_BYTES = 4 * 1024 * 1024
MAX_SCREENSHOT_BYTES = 1024 * 1024
MAX_SCREENSHOTS = 20
DUMP_PATH = "/sdcard/eolfi_ui.xml"
KEYS = {"BACK", "HOME", "ENTER", "TAB", "DEL", "MENU", "APP_SWITCH", "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT",
        "DPAD_RIGHT", "DPAD_CENTER", "ESCAPE", "SPACE"}
SELECTORS = ("resource_id", "text", "content_desc")
MOBILE_DO = {"tap", "input_text", "key", "wait_for", "read"}
_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")
_ACTIVITY = re.compile(r"^\.?[A-Za-z][A-Za-z0-9_$]*(\.[A-Za-z][A-Za-z0-9_$]*)*$")
_SERIAL = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_BOUNDS = re.compile(r"^\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]$")
_FOCUS = re.compile(r"mCurrentFocus=Window\{[^}]*?\s([A-Za-z0-9_.]+)/([A-Za-z0-9_.$]+)\}")
_FOCUSED_APP = re.compile(r"mFocusedApp=.*?\s([A-Za-z0-9_.]+)/([A-Za-z0-9_.$]+)")
_PROP = re.compile(r"^\[([^\]]+)\]: \[(.*)\]$")
PROPS = {"ro.product.manufacturer": "manufacturer", "ro.product.model": "model",
         "ro.build.version.release": "android_release", "ro.build.version.sdk": "sdk",
         "ro.product.cpu.abi": "abi", "ro.build.fingerprint": "build_fingerprint"}
LIMITS = ("árbol de accesibilidad de uiautomator (hasta 300 elementos con texto, descripción, identificador o "
          "acción) y actividad en primer plano tras cada acción; las posiciones no entran en la huella de la "
          "pantalla; vistas sin accesibilidad (p. ej. lienzos, juegos, WebView sin accesibilidad) no se ven; "
          "capturas PNG opcionales de hasta 1 MiB y 20 por paso, sin redacción visual; el estado del dispositivo "
          "no se restaura, salvo los datos de la app con clear_data")


class AdbError(RuntimeError):
    pass


def validate_step(raw: dict[str, Any], step: dict[str, Any], label: str, err: Callable[[str], None],
                  text: Callable[[Any, str, int], str], timeout: Callable[..., float], ident: re.Pattern,
                  max_actions: int) -> set[str]:
    """Valida y normaliza un paso mobile; devuelve las claves admitidas."""
    if raw.get("platform", "android") != "android":
        err(f"{label}.platform: solo «android» (iOS no está implementado)")
    step["platform"] = "android"
    pkg = raw.get("package")
    if not isinstance(pkg, str) or len(pkg) > 255 or not _PACKAGE.fullmatch(pkg):
        err(f"{label}.package: nombre de paquete Android (p. ej. org.ejemplo.app)")
    step["package"] = pkg
    if "activity" in raw:
        act = raw["activity"]
        if not isinstance(act, str) or len(act) > 255 or not _ACTIVITY.fullmatch(act):
            err(f"{label}.activity: nombre de actividad (p. ej. .Principal)")
        step["activity"] = act
    if "device" in raw:
        if not isinstance(raw["device"], str) or not _SERIAL.fullmatch(raw["device"]):
            err(f"{label}.device: número de serie de adb")
        step["device"] = raw["device"]
    step["timeout"] = timeout(raw.get("timeout"), label, 60.0)
    for flag, default in (("stop", True), ("screenshots", False), ("clear_data", False)):
        if not isinstance(raw.get(flag, default), bool):
            err(f"{label}.{flag}: booleano")
        step[flag] = raw.get(flag, default)
    acts = raw.get("actions", [])
    if not isinstance(acts, list) or len(acts) > max_actions:
        err(f"{label}.actions: lista de hasta {max_actions} acciones")
    seen: set[str] = set()
    step["actions"] = []
    for j, a in enumerate(acts):
        al = f"{label}.actions[{j}]"
        if not isinstance(a, dict) or a.get("do") not in MOBILE_DO or not set(a) <= {
                "id", "do", "value", "timeout", *SELECTORS}:
            err(f"{al}: «do» debe ser uno de {sorted(MOBILE_DO)}")
        aid = a.get("id", f"accion{j + 1}")
        if not isinstance(aid, str) or not ident.fullmatch(aid) or aid in seen or aid == "_inicio":
            err(f"{al}.id inválido o repetido")
        seen.add(aid)
        act: dict[str, Any] = {"id": aid, "do": a["do"]}
        for k in (*SELECTORS, "value"):
            if k in a:
                act[k] = text(a[k], f"{al}.{k}", 2000)
        if a["do"] in ("tap", "input_text", "wait_for") and not any(act.get(k) for k in SELECTORS):
            err(f"{al}: «{a['do']}» necesita resource_id, text o content_desc")
        if a["do"] == "input_text" and "value" not in act:
            err(f"{al}: input_text necesita value")
        if a["do"] == "key" and act.get("value") not in KEYS:
            err(f"{al}: key necesita value entre {sorted(KEYS)}")
        if "timeout" in a:
            act["timeout"] = timeout(a["timeout"], al, 10.0)
        step["actions"].append(act)
    return {"platform", "package", "activity", "device", "timeout", "stop", "screenshots", "clear_data", "actions"}



def adb_path() -> str | None:
    explicit = os.environ.get("EOLFI_ADB")
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    return shutil.which("adb")


def shell_quote_text(value: str) -> str:
    """Argumento de ``input text``: los espacios van como %s (convención de input) y el resto entre comillas."""
    return shlex.quote(value.replace(" ", "%s"))


class Adb:
    def __init__(self, path: str, serial: str | None, deadline: float):
        self.path, self.serial, self.deadline = path, serial, deadline
        self.calls = 0

    def _left(self, cap: float = 30.0) -> float:
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("se agotó el tiempo del paso")
        return min(left, cap)

    def run(self, *args: str, binary: bool = False, check: bool = True) -> Any:
        argv = [self.path, *(["-s", self.serial] if self.serial else []), *args]
        self.calls += 1
        try:
            p = subprocess.run(argv, capture_output=True, timeout=self._left(), stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"adb {args[0]} no terminó a tiempo") from exc
        if check and p.returncode != 0:
            raise AdbError(f"adb {' '.join(args)[:200]} → código {p.returncode}: "
                           f"{p.stderr.decode('utf-8', 'replace')[-400:]}")
        return p.stdout if binary else p.stdout.decode("utf-8", "replace")

    def shell(self, command: str, check: bool = True) -> str:
        return self.run("shell", command, check=check)


def select_device(path: str, wanted: str | None, deadline: float) -> tuple[str | None, str | None]:
    """(serie, error). Exige un único dispositivo listo, o el indicado."""
    out = Adb(path, None, deadline).run("devices")
    ready = [ln.split("\t")[0] for ln in out.splitlines()[1:] if ln.strip().endswith("\tdevice")]
    others = [ln.strip() for ln in out.splitlines()[1:] if ln.strip() and not ln.strip().endswith("\tdevice")]
    if wanted:
        if wanted in ready:
            return wanted, None
        return None, "el dispositivo indicado no está conectado y autorizado (adb devices)"
    if len(ready) == 1:
        return ready[0], None
    if not ready:
        why = f" ({len(others)} sin autorizar o desconectados)" if others else ""
        return None, "ningún dispositivo Android listo en adb devices" + why
    return None, f"{len(ready)} dispositivos conectados: indica cuál con «device»"


def device_identity(adb: Adb, serial: str) -> dict[str, Any]:
    props = {}
    for ln in adb.shell("getprop").splitlines():
        m = _PROP.match(ln.strip())
        if m and m.group(1) in PROPS:
            props[PROPS[m.group(1)]] = m.group(2)[:300]
    return {"serial_sha256": hashlib.sha256(serial.encode("utf-8")).hexdigest()[:16], **props}


def app_identity(adb: Adb, package: str) -> dict[str, Any]:
    paths = [ln.split(":", 1)[1].strip() for ln in adb.shell(f"pm path {shlex.quote(package)}", check=False)
             .splitlines() if ln.startswith("package:")]
    if not paths:
        return {"package": package, "installed": False}
    dump = adb.shell(f"dumpsys package {shlex.quote(package)}", check=False)
    vn = re.search(r"versionName=(\S+)", dump)
    vc = re.search(r"versionCode=(\d+)", dump)
    return {"package": package, "installed": True, "apk_paths": paths[:20],
            "version_name": vn.group(1) if vn else None, "version_code": int(vc.group(1)) if vc else None}


def parse_hierarchy(xml_text: str) -> dict[str, Any]:
    """Árbol de uiautomator → elementos significativos (acotados). Rechaza DTD/entidades."""
    if len(xml_text) > MAX_DUMP_BYTES:
        raise AdbError("volcado de interfaz demasiado grande")
    start = xml_text.find("<?xml")
    start = start if start >= 0 else xml_text.find("<hierarchy")
    end = xml_text.rfind("</hierarchy>")
    if start < 0 or end < 0:
        raise AdbError("volcado de interfaz no reconocido")
    body = xml_text[start:end + len("</hierarchy>")]
    if "<!DOCTYPE" in body or "<!ENTITY" in body:
        raise AdbError("volcado de interfaz con DTD: rechazado")
    root = ET.fromstring(body)
    elements: list[dict[str, Any]] = []
    total = 0
    packages: set[str] = set()
    for node in root.iter("node"):
        a = node.attrib
        if a.get("package"):
            packages.add(a["package"])
        clickable = a.get("clickable") == "true"
        meaningful = any(a.get(k) for k in ("text", "content-desc", "resource-id")) or clickable or \
            a.get("checkable") == "true"
        if not meaningful:
            continue
        total += 1
        if len(elements) >= MAX_ELEMENTS:
            continue
        el: dict[str, Any] = {"class": a.get("class", ""), "resource_id": a.get("resource-id", ""),
                              "text": a.get("text", ""), "content_desc": a.get("content-desc", "")}
        if a.get("password") == "true":
            el["text"] = None
            el["password"] = True
        for flag in ("clickable", "checkable", "checked", "enabled", "focused", "selected", "scrollable"):
            if a.get(flag) == "true":
                el[flag] = True
        if a.get("enabled") == "false":
            el["enabled"] = False
        m = _BOUNDS.match(a.get("bounds", ""))
        if m:
            el["bounds"] = [int(x) for x in m.groups()]
        elements.append(el)
    return {"elements": elements, "elements_total": total, "truncated": total > len(elements),
            "packages": sorted(packages)}


def screen_hash(screen: dict[str, Any]) -> str:
    """Huella de la pantalla sin posiciones ni foco (cambian con el dispositivo y el tiempo)."""
    core = [{k: v for k, v in e.items() if k not in ("bounds", "focused")} for e in screen.get("elements", [])]
    return hashlib.sha256(json.dumps([screen.get("activity"), core], sort_keys=True,
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def find(screen: dict[str, Any], act: dict[str, Any]) -> dict[str, Any] | None:
    for e in screen.get("elements", []):
        if all(e.get(k) == act[k] for k in SELECTORS if act.get(k)):
            return e
    return None


def png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    return None


class _Driver:
    def __init__(self, adb: Adb, step: dict[str, Any], norm: Any):
        self.adb, self.step, self.norm = adb, step, norm
        self.shots = 0

    def focus(self) -> tuple[str | None, str | None]:
        out = self.adb.shell("dumpsys window", check=False)
        m = _FOCUS.search(out) or _FOCUSED_APP.search(out)
        return (m.group(1), m.group(2)) if m else (None, None)

    def screen(self) -> dict[str, Any]:
        self.adb.shell(f"uiautomator dump {DUMP_PATH}", check=False)
        raw = self.adb.run("exec-out", f"cat {DUMP_PATH}", binary=True)
        self.adb.shell(f"rm -f {DUMP_PATH}", check=False)
        text = raw.decode("utf-8", "replace")
        if self.norm is not None:
            text = self.norm.text(text)
        screen = parse_hierarchy(text)
        pkg, activity = self.focus()
        screen["package"], screen["activity"] = pkg, activity
        return screen

    def screenshot(self) -> dict[str, Any]:
        if self.shots >= MAX_SCREENSHOTS:
            return {"status": "limit_reached"}
        data = self.adb.run("exec-out", "screencap -p", binary=True)
        size = png_size(data)
        if size is None:
            return {"status": "invalid_capture"}
        if len(data) > MAX_SCREENSHOT_BYTES:
            return {"status": "too_large", "bytes": len(data)}
        self.shots += 1
        return {"status": "captured", "mime_type": "image/png", "bytes": len(data), "width": size[0],
                "height": size[1], "sha256": hashlib.sha256(data).hexdigest(),
                "data_base64": base64.b64encode(data).decode("ascii")}

    def wait(self, act: dict[str, Any], seconds: float) -> tuple[dict[str, Any], dict[str, Any] | None]:
        limit = time.monotonic() + seconds
        while True:
            screen = self.screen()
            node = find(screen, act)
            if node is not None or time.monotonic() >= limit:
                return screen, node
            time.sleep(0.3)

    def wait_foreground(self, seconds: float) -> dict[str, Any]:
        limit = time.monotonic() + seconds
        while True:
            screen = self.screen()
            if screen.get("package") == self.step["package"] or time.monotonic() >= limit:
                return screen
            time.sleep(0.3)

    def record(self, aid: str, do: str, status: str, screen: dict[str, Any], **extra: Any) -> dict[str, Any]:
        rec = {"id": aid, "do": do, "status": status, "screen": screen, "screen_sha256": screen_hash(screen),
               **extra}
        if self.step.get("screenshots"):
            rec["screenshot"] = self.screenshot()
        return rec

    def act(self, a: dict[str, Any]) -> dict[str, Any]:
        target = {k: a[k] for k in SELECTORS if a.get(k)}
        extra: dict[str, Any] = {"target": target} if target else {}
        if a["do"] == "key":
            self.adb.shell(f"input keyevent KEYCODE_{a['value']}")
            time.sleep(0.3)
            return self.record(a["id"], "key", "ok", self.screen(), key=a["value"])
        if a["do"] == "read":
            return self.record(a["id"], "read", "ok", self.screen())
        screen, node = self.wait(a, a.get("timeout", 10.0) if a["do"] == "wait_for" else a.get("timeout", 5.0))
        if node is None:
            return self.record(a["id"], a["do"], "not_found", screen, **extra)
        if a["do"] == "wait_for":
            return self.record(a["id"], "wait_for", "ok", screen, **extra)
        b = node.get("bounds")
        if not b:
            return self.record(a["id"], a["do"], "error", screen, error="el elemento no tiene posición", **extra)
        x, y = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
        self.adb.shell(f"input tap {x} {y}")
        if a["do"] == "input_text":
            self.adb.shell(f"input text {shell_quote_text(a['value'])}")
            extra["value_sha256"] = hashlib.sha256(a["value"].encode("utf-8")).hexdigest()
        time.sleep(0.3)
        return self.record(a["id"], a["do"], "ok", self.screen(), **extra)


def run_mobile_step(step: dict[str, Any], norm: Any) -> dict[str, Any]:
    """Ejecuta un paso mobile y devuelve el registro del paso (sin id/action, que pone la sesión)."""
    t0 = time.monotonic()
    path = adb_path()
    if path is None:
        why = ("EOLFI_ADB no apunta a un archivo" if os.environ.get("EOLFI_ADB") else
               "adb no está en el PATH (Android SDK platform-tools)")
        return {"status": "unavailable", "error": f"interfaz móvil no disponible: {why}"}
    deadline = t0 + step["timeout"]
    rec: dict[str, Any] = {"platform": "android", "driver": {"name": "adb + uiautomator", "path": path},
                           "package": step["package"], "screenshots_requested": step.get("screenshots", False)}
    try:
        serial, why = select_device(path, step.get("device"), deadline)
        if serial is None:
            return {**rec, "status": "unavailable", "error": f"interfaz móvil no disponible: {why}"}
        adb = Adb(path, serial, deadline)
        rec["device"] = device_identity(adb, serial)
        app = app_identity(adb, step["package"])
        rec["app"] = app
        if not app["installed"]:
            return {**rec, "status": "error", "error": f"el paquete {step['package']} no está instalado en el "
                                                       "dispositivo (Eolfi no instala apps)",
                    "duration_ms": round((time.monotonic() - t0) * 1000)}
        pkg = shlex.quote(step["package"])
        if step.get("clear_data"):
            out = adb.shell(f"pm clear {pkg}", check=False)
            rec["cleared_data"] = "Success" in out
        if step.get("activity"):
            act = step["activity"]
            comp = f"{step['package']}/{act if not act.startswith('.') else step['package'] + act}"
            adb.shell(f"am start -W -n {shlex.quote(comp)}")
        else:
            adb.shell(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
        drv = _Driver(adb, step, norm)
        first = drv.wait_foreground(min(15.0, step["timeout"]))
        actions = [drv.record("_inicio", "launch", "ok" if first.get("package") == step["package"] else
                              "not_foreground", first)]
        for a in step["actions"]:
            actions.append(drv.act(a))
        if step.get("stop", True):
            adb.shell(f"am force-stop {pkg}", check=False)
            rec["stopped"] = True
        rec["actions"] = actions
        rec["adb_calls"] = adb.calls
        bad = [a for a in actions if a["status"] != "ok"]
        rec["status"] = "ok" if not bad else "partial"
        if bad:
            rec["error"] = "; ".join(f"{a['id']}: {a['status']}" for a in bad)[:1000]
        if step.get("screenshots") and any((a.get("screenshot") or {}).get("status") != "captured" for a in actions):
            rec["status"] = "partial"
            rec["error"] = (rec.get("error", "") + "; captura visual no completa").strip("; ")
    except TimeoutError as exc:
        rec.update(status="timeout", error=str(exc)[:1000])
    except (AdbError, ET.ParseError, OSError) as exc:
        rec.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:1000]}")
    rec["duration_ms"] = round((time.monotonic() - t0) * 1000)
    return rec


def coverage(steps: list[dict[str, Any]]) -> Any:
    mob = [s for s in steps if s["action"] == "mobile"]
    if not mob:
        return {"status": "not_requested", "ios": "no implementado"}
    if all(s["status"] == "unavailable" for s in mob):
        return {"status": "not_available", "reason": "; ".join(sorted({s["error"] for s in mob}))}
    requested = any(s.get("screenshots_requested") for s in mob)
    if all(s["status"] == "ok" for s in mob):
        return {"status": "observed", "method": "Android adb + uiautomator",
                "screenshots": "captured" if requested else "not_requested", "limits": LIMITS}
    return {"status": "partial", "screenshots": "partial" if requested else "not_requested",
            "reason": "; ".join(sorted({str(s.get("error", s["status"]))[:200] for s in mob if s["status"] != "ok"}))}
