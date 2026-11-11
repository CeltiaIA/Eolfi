"""Reconstrucción independiente y trazable a partir de la especificación del caso (Fase 4).

Tres piezas separadas:

1. ``build_model``: **modelo de comportamiento** independiente de cualquier generador. Deriva componentes
   (interfaz de línea de comandos, API HTTP, interfaz de usuario, persistencia), sus interfaces y datos a partir
   de los requisitos y de las evidencias de observación, con cada decisión, sus alternativas y su motivo. No
   mira el código del original (no lo tiene) ni asume que detectar un framework baste.
2. ``generate``: generador de una **base ejecutable** para un lenguaje/plataforma (hoy: CLI en Python estándar
   y API HTTP observada en Python estándar) por etapas. Etapa 1 = reproducir los casos observados (tabla de
   comportamiento): cada caso queda marcado como
   *simulado* (no generaliza a entradas no observadas); lo que no se puede reproducir con la evidencia disponible
   (contenido de archivos solo conocido por hash, salidas truncadas, contradicciones) queda *pendiente*.
   Un manifiesto ``.eolfi/trazabilidad.json`` liga cada archivo y caso a su requisito y evidencia, y la
   regeneración nunca pisa un archivo modificado a mano (escribe ``<archivo>.nuevo`` y lo informa).
3. ``verify``: ejecuta la base generada con las entradas observadas y compara con lo esperado en la
   especificación (código de salida, stdout y stderr normalizados; en la API HTTP, estado, cuerpo y tipo de
   contenido de cada respuesta, y los archivos capturados). Comprueba además que la base compila, que no
   contiene líneas del objetivo original cuando este es accesible y que cada mejora aplicada cumple su razón.
   Guarda la evidencia y el registro del caso.

Mejoras (``improvements.py``): solo las que pide el operador, con razón de una categoría admitida, compatibles
con todos los requisitos observados y comprobables al ejecutar; las demás quedan registradas como rechazadas.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from eolfi.core.cases import case_run
from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Authority, Confidence, Evidence
from eolfi.reconstruct import improvements as _imp

MODEL_FORMAT = 1
PROVIDER = "eolfi.reconstruct"
VERSION = "1.0.0"
MANIFEST = ".eolfi/trazabilidad.json"
TARGETS = {"python-cli": "Línea de comandos en Python (solo biblioteca estándar)",
           "python-http": "API HTTP observada en Python (solo biblioteca estándar)"}
# Códigos propios de la base HTTP generada para lo que no reproduce (se marcan también con una cabecera).
HTTP_NOT_SPECIFIED = 501
HTTP_PENDING = 503
STATE_HEADER = "X-Eolfi-Estado"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _session_step(store: EvidenceStore, eid: str, step_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    ev = store.get_evidence(eid)
    session, params = json.loads(ev["result"]), json.loads(ev["params"])
    step = next(s for s in session["steps"] if s["id"] == step_id)
    sstep = next(s for s in params["script"]["steps"] if s["id"] == step_id)
    return step, sstep


# -- 1. modelo de comportamiento ---------------------------------------------------------------------------
def _file_effects(step: dict[str, Any], case: dict[str, Any], req_id: str, comp) -> None:
    """Escrituras del paso: solo se reproducen las capturadas íntegramente dentro del sandbox; el resto queda
    pendiente con su motivo. Compartido por la CLI y la API HTTP."""
    file_effects = [e for e in step.get("effects", {}).get("files", [])]
    if not file_effects:
        return
    d = comp("persistence", "persistence", "Persistencia en archivos")
    d["requirements"].append(req_id)
    d["data"] += [e["path"] for e in file_effects if e["path"] not in d["data"]]
    capture_requested = bool(step.get("file_capture_requested"))
    selected_paths = step.get("file_capture_paths", [])
    for effect in file_effects:
        path = effect["path"]
        if not path.startswith("{sandbox}/"):
            case["pending"].append(f"efecto externo no reconstruible: {path[:200]}")
            continue
        rel = path[len("{sandbox}/"):]
        if not rel or any(part in ("", ".", "..") for part in rel.split("/")):
            case["pending"].append(f"ruta de efecto no segura: {path[:200]}")
            continue
        if effect["change"] == "deleted":
            case["pending"].append(f"borrado de archivo requiere estado inicial no capturado: {path[:200]}")
            continue
        if not capture_requested or path not in selected_paths:
            case["pending"].append(f"contenido del archivo no capturado íntegramente: {path[:200]}")
            continue
        capture = effect.get("after", {}).get("content_capture", {})
        encoded = capture.get("data_base64")
        try:
            content = __import__("base64").b64decode(encoded, validate=True) if capture.get(
                "status") == "captured" and isinstance(encoded, str) else None
        except (ValueError, TypeError):
            content = None
        expected_hash = capture.get("sha256")
        if content is None or capture.get("sha256") != _sha(content) or capture.get("raw_sha256") != (
                effect.get("after") or {}).get("sha256"):
            case["pending"].append(f"contenido del archivo no capturado íntegramente: {path[:200]}")
            continue
        case["file_ops"].append({"action": "write", "path": rel, "data_base64": encoded,
                                 "sha256": expected_hash, "utf8": bool(capture.get("utf8"))})
        case["captured_paths"].append(path)
    if capture_requested and case["file_ops"]:
        case["pending"].append("transiciones de estado entre ejecuciones no modeladas; se aplica la "
                               "instantánea de archivos observada para esta entrada")


def _http_case(r: dict[str, Any], step: dict[str, Any], sstep: dict[str, Any]) -> dict[str, Any]:
    """Caso de la API HTTP: petición observada → respuesta observada. Solo lo que consta en la evidencia."""
    trace = (step.get("traces") or [{}])[0]
    req, resp = trace.get("request") or {}, trace.get("response")
    parts = urllib.parse.urlsplit(req.get("url") or "")
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    body = None
    if "body" in sstep:
        from eolfi.observe.script import content_bytes

        body = content_bytes(sstep["body"])
    ctype = next((v for k, v in (sstep.get("headers") or {}).items() if k.lower() == "content-type"), None)
    case: dict[str, Any] = {
        "requirement": r["id"], "method": (req.get("method") or sstep.get("method") or "GET").upper(),
        "path": path, "request_body_base64": __import__("base64").b64encode(body).decode() if body is not None else None,
        "request_body_sha256": _sha(body) if body is not None else None,
        "request_content_type": ctype if ctype and "{" not in ctype else None,
        "status": "simulado", "evidence_ids": r["evidence_ids"], "confidence": r["confidence"], "pending": [],
        "file_ops": [], "captured_paths": [], "response_status": None, "content_type": None,
        "response_body": "", "response_body_sha256": None}
    if "{var:" in path or "{sandbox}" in path:
        case["status"] = "pendiente"
        case["pending"].append("la ruta depende de variables de la observación")
    if r["status"] != "observed":
        case["status"] = "pendiente"
        case["pending"].append("requisito contradicho: la misma petición tuvo respuestas distintas (estado no "
                               "modelado)")
    if resp is None:
        case["status"] = "pendiente"
        case["pending"].append("sin respuesta observada: " + str(trace.get("blocked") or step.get("error") or
                                                                    "la petición falló")[:200])
        return case
    case["response_status"] = resp.get("status")
    ct = next((v for k, v in (resp.get("headers") or {}).items() if k.lower() == "content-type"), None)
    case["content_type"] = ct if ct and not str(ct).startswith("<redactado") else None
    rbody = resp.get("body") or {}
    preview = rbody.get("preview", "")
    if resp.get("body_truncated") or rbody.get("preview_truncated") or not rbody.get("utf8", True):
        case["status"] = "pendiente"
        case["pending"].append("cuerpo de la respuesta no disponible completo en la evidencia")
    elif "<dato personal:" in preview:
        case["status"] = "pendiente"
        case["pending"].append("cuerpo con datos personales ocultados en la evidencia: no se reproduce")
    elif "{var:" in preview:
        case["status"] = "pendiente"
        case["pending"].append("el cuerpo depende de variables de la observación ({var:…}) no reconstruidas")
    case["response_body"] = preview
    case["response_body_sha256"] = rbody.get("sha256_normalized")
    if resp.get("set_cookie_names"):
        case["pending"].append("cookies solo conocidas por nombre, sin valor: no se reproducen ("
                               + ", ".join(resp["set_cookie_names"])[:200] + ")")
    if trace.get("redirects"):
        case["pending"].append("redirecciones observadas no reproducidas")
    if r["unstable_aspects"]:
        case["pending"].append("aspectos no reproducibles: " + ", ".join(r["unstable_aspects"]))
    return case


def build_model(store: EvidenceStore, case_id: str) -> dict[str, Any]:
    from eolfi.spec import latest_spec

    spec = latest_spec(store, case_id)
    if spec is None:
        raise ValueError("el caso no tiene especificación: ejecuta antes eolfi spec build")
    components: dict[str, dict[str, Any]] = {}
    decisions: list[dict[str, Any]] = []

    def evidence_for(requirements: list[str]) -> list[str]:
        selected = set(requirements)
        return sorted({eid for req in spec["requirements"] if req["id"] in selected
                       for eid in req.get("evidence_ids", [])})

    def comp(cid: str, kind: str, title: str) -> dict[str, Any]:
        return components.setdefault(cid, {"id": cid, "kind": kind, "title": title, "requirements": [],
                                           "interfaces": [], "data": [], "cases": []})

    for r in spec["requirements"]:
        act = r["inputs"]["action"]
        if act == "run":
            c = comp("cli", "command_line", "Interfaz de línea de comandos")
            c["requirements"].append(r["id"])
            eid, step_id = r["source_steps"][0]
            step, sstep = _session_step(store, eid, step_id)
            args = list(sstep["argv"][1:])
            # Decisión: los argumentos que nombran al objetivo original no forman parte de la interfaz.
            if args and args[0] == "{target}":
                args = args[1:]
            stdin = None
            if "stdin" in sstep:
                from eolfi.observe.script import content_bytes

                stdin = content_bytes(sstep["stdin"]).decode("utf-8", "replace")
            case = {"requirement": r["id"], "args": args, "stdin": stdin, "status": "simulado",
                    "evidence_ids": r["evidence_ids"], "confidence": r["confidence"], "pending": [], "file_ops": [], "captured_paths": []}
            if r["status"] != "observed":
                case["status"] = "pendiente"
                case["pending"].append("requisito contradicho: no hay comportamiento único que reproducir")
            for name in ("stdout", "stderr"):
                out = step.get(name) or {}
                if out.get("preview_truncated") or not out.get("utf8", True):
                    case["status"] = "pendiente"
                    case["pending"].append(f"{name} no disponible completo en la evidencia")
                elif "<dato personal:" in out.get("preview", ""):
                    case["status"] = "pendiente"
                    case["pending"].append(f"{name} con datos personales ocultados en la evidencia: no se reproduce")
                case[name] = out.get("preview", "").replace(chr(13) + chr(10), chr(10))
                case[name + "_sha256"] = r["expected"].get(name)
            case["exit_code"] = r["expected"].get("código de salida", step.get("exit_code"))
            if r["unstable_aspects"]:
                case["pending"].append("aspectos no reproducibles: " + ", ".join(r["unstable_aspects"]))
            _file_effects(step, case, r["id"], comp)
            if r["persistence"] and any(p["kind"] == "registry" for p in r["persistence"]):
                case["pending"].append("efectos en el registro de Windows sin implementar")
            if case["pending"] and case["status"] == "simulado":
                case["status"] = "parcial"
            c["cases"].append(case)
        elif act == "http":
            c = comp("http_api", "http_api", "API HTTP observada")
            c["requirements"].append(r["id"])
            eid, step_id = r["source_steps"][0]
            step, sstep = _session_step(store, eid, step_id)
            case = _http_case(r, step, sstep)
            _file_effects(step, case, r["id"], comp)
            if case["pending"] and case["status"] == "simulado":
                case["status"] = "parcial"
            c["interfaces"].append({"method": case["method"], "path": case["path"],
                                    "url": r["inputs"].get("url")})
            c["cases"].append(case)
        elif act in ("browser", "desktop", "mobile"):
            c = comp("ui", "user_interface", "Interfaz de usuario observada")
            c["requirements"].append(r["id"])
            if r.get("state_machine"):
                c["interfaces"].append({"state_machine": r["state_machine"]})
    for component in components.values():
        component["requirements"] = sorted(set(component["requirements"]))
    if "cli" in components:
        c = components["cli"]
        c["interfaces"].append({"argv": sorted({json.dumps(x["args"]) for x in c["cases"]}),
                                "stdin": any(x["stdin"] is not None for x in c["cases"]),
                                "exit_codes": sorted({x["exit_code"] for x in c["cases"] if x["exit_code"] is not None})})
        decisions.append({
            "decision": "Etapa 1: tabla de comportamiento observado (entrada → salida) para la CLI",
            "reason": "es lo único demostrado por las evidencias; no hay fuentes del original",
            "requirements": sorted(c["requirements"]), "evidence_ids": evidence_for(c["requirements"]),
            "alternatives": ["inferir la lógica general (requiere más observaciones o una especificación revisada; "
                             "sin ellas sería una hipótesis)", "plantilla de framework detectado (no reproduce "
                             "el comportamiento)"],
            "consequence": "las entradas no observadas devuelven «comportamiento no especificado» (código 2)"})
        decisions.append({
            "decision": "Las rutas del sandbox de observación se sustituyen por el directorio de trabajo real",
            "reason": "la observación normalizó la ruta de trabajo como {sandbox}",
            "requirements": sorted(c["requirements"]), "evidence_ids": evidence_for(c["requirements"]),
            "alternatives": ["imprimir el marcador literal (rompería la equivalencia observable)"]})
    if "http_api" in components:
        c = components["http_api"]
        decisions.append({
            "decision": "Etapa 1: tabla de comportamiento observado (petición → respuesta) para la API HTTP",
            "reason": "solo las rutas, métodos, cuerpos de petición, códigos y cuerpos de respuesta observados "
                      "están demostrados por las evidencias",
            "requirements": sorted(c["requirements"]), "evidence_ids": evidence_for(c["requirements"]),
            "alternatives": ["inferir rutas o parámetros generales (sería una hipótesis sin más observaciones)",
                             "plantilla de framework detectado (no reproduce el comportamiento)"],
            "consequence": f"las peticiones no observadas responden {HTTP_NOT_SPECIFIED} «comportamiento no "
                           f"especificado» y los casos pendientes {HTTP_PENDING}, ambos con la cabecera "
                           f"{STATE_HEADER}"})
        decisions.append({
            "decision": "Las cabeceras de petición no forman parte de la coincidencia; el cuerpo, por su huella",
            "reason": "la evidencia guarda las cabeceras sensibles redactadas y el cuerpo de la petición por huella",
            "requirements": sorted(c["requirements"]), "evidence_ids": evidence_for(c["requirements"]),
            "alternatives": ["exigir cabeceras redactadas (no se pueden comprobar)"]})
    for kind in ("ui",):
        if kind in components:
            decisions.append({"decision": f"Componente «{components[kind]['title']}» documentado, sin generar",
                              "reason": "el generador de esta etapa solo cubre la CLI y la API HTTP",
                              "requirements": sorted(components[kind]["requirements"]),
                              "evidence_ids": evidence_for(components[kind]["requirements"]), "alternatives": [
                                  "generar un esqueleto sin comportamiento (se declararía como pendiente)"]})
    body = {"components": sorted(components.values(), key=lambda c: c["id"]), "decisions": decisions,
            "unknowns": spec["unknowns"], "hypotheses": spec["hypotheses"]}
    return {"model_format": MODEL_FORMAT, "case_id": case_id, "spec_version": spec["spec_version"],
            "spec_sha256": spec["content_sha256"],
            "content_sha256": _sha(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")), **body}


# -- 2. generador ----------------------------------------------------------------------------------------
_APP = '''"""{name}: reconstrucción independiente generada por Eolfi a partir de una especificación observada.

Etapa 1 — tabla de comportamiento observado. Cada caso procede de un requisito (ver .eolfi/trazabilidad.json).
Los casos «simulado» reproducen lo observado y NO generalizan; los «pendiente» no se pudieron reproducir con la
evidencia disponible. Cualquier otra entrada responde «comportamiento no especificado» (código 2).
No contiene código del programa original.
"""
import hashlib
import base64
import json
import os
import sys
from pathlib import Path

CASES = json.loads((Path(__file__).with_name("comportamiento.json")).read_text(encoding="utf-8"))
_MEJORAS = Path(__file__).with_name("mejoras.json")
MEJORAS = json.loads(_MEJORAS.read_text(encoding="utf-8")) if _MEJORAS.is_file() else {}


def _write(stream, text):
    if MEJORAS.get("utf8") and hasattr(stream, "buffer"):
        stream.flush()
        stream.buffer.write(text.encode("utf-8"))
        stream.buffer.flush()
    else:
        stream.write(text)


def _render(text):
    return text.replace("{sandbox}", os.getcwd()).replace(chr(13) + chr(10), chr(10))


def _apply_files(case):
    base = Path.cwd().resolve()
    for op in case.get("file_ops", []):
        rel = Path(op["path"])
        if rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
            raise ValueError("ruta de persistencia no segura")
        candidate = base / rel
        if any(parent.is_symlink() for parent in [candidate, *candidate.parents] if parent != base):
            raise ValueError("ruta de persistencia atraviesa un enlace")
        dst = candidate.resolve()
        if not dst.is_relative_to(base):
            raise ValueError("ruta de persistencia fuera del directorio de trabajo")
        data = base64.b64decode(op["data_base64"], validate=True)
        if hashlib.sha256(data).hexdigest() != op["sha256"]:
            raise ValueError("huella de archivo no válida")
        if op.get("utf8"):
            data = data.replace(b"{sandbox}", str(base).encode("utf-8"))
        if dst.exists():
            existing = dst.read_bytes()
            if op.get("utf8"):
                existing = existing.replace(str(base).encode("utf-8"), b"{sandbox}")
            if hashlib.sha256(existing).hexdigest() == op["sha256"]:
                continue
            raise ValueError("se conserva el archivo existente; no se sobrescribe")
        dst.parent.mkdir(parents=True, exist_ok=True)
        checked = dst.resolve()
        if not checked.is_relative_to(base) or dst.is_symlink():
            raise ValueError("ruta de persistencia atraviesa un enlace")
        checked.write_bytes(data)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    data = b"" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.buffer.read()
    text = data.decode("utf-8", "replace")
    for case in CASES:
        if case["args"] != argv or (case["stdin"] is not None and case["stdin"] != text):
            continue
        if case["status"] == "pendiente":
            sys.stderr.write("comportamiento pendiente de reconstruir: " + "; ".join(case["pending"]) + chr(10))
            return 3
        try:
            _apply_files(case)
        except Exception as exc:
            sys.stderr.write("persistencia pendiente: " + str(exc) + chr(10))
            return 3
        _write(sys.stdout, _render(case["stdout"]))
        _write(sys.stderr, _render(case["stderr"]))
        return case["exit_code"] if case["exit_code"] is not None else 0
    sys.stderr.write("comportamiento no especificado para estas entradas" + chr(10))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
'''

_APPLY_FILES = _APP[_APP.index("def _render(text):"):_APP.index("def main(argv=None):")]

_SERVER = '''"""{name}: API HTTP reconstruida por Eolfi a partir de una especificación observada.

Etapa 1 — tabla de comportamiento observado (petición → respuesta). Cada caso procede de un requisito (ver
.eolfi/trazabilidad.json) y coincide por método, ruta con su consulta y huella del cuerpo de la petición; las
cabeceras de la petición no cuentan. Los casos «simulado» reproducen lo observado y NO generalizan; los
«pendiente» responden @PENDING@ y cualquier otra petición @NOT_SPECIFIED@ «comportamiento no especificado», ambos con
la cabecera @HEADER@. No contiene código del programa original.
"""
import argparse
import hashlib
import base64
import json
import os
import socketserver
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CASES = json.loads((Path(__file__).with_name("api.json")).read_text(encoding="utf-8"))
_MEJORAS = Path(__file__).with_name("mejoras.json")
MEJORAS = json.loads(_MEJORAS.read_text(encoding="utf-8")) if _MEJORAS.is_file() else {}


class Server(ThreadingHTTPServer):
    def server_bind(self):
        # Sin la resolución inversa (socket.getfqdn) de HTTPServer: en algunos equipos macOS tarda decenas de segundos.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


@APPLY_FILES@
class Handler(BaseHTTPRequestHandler):
    server_version = "eolfi-reconstruccion"
    sys_version = ""

    def log_message(self, fmt, *args):
        pass

    def _send(self, status, body, headers):
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        if MEJORAS.get("nosniff"):
            self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _handle(self):
        size = int(self.headers.get("Content-Length") or 0)
        if MEJORAS.get("max_body") and size > MEJORAS["max_body"]:
            self.close_connection = True
            return self._send(413, "cuerpo de la petición demasiado grande".encode("utf-8"),
                              {"@HEADER@": "limite", "Content-Type": "text/plain; charset=utf-8"})
        data = self.rfile.read(size) if size > 0 else b""
        digest = hashlib.sha256(data).hexdigest() if data else None
        for case in CASES:
            if case["method"] != self.command or case["path"] != self.path:
                continue
            if case["request_body_sha256"] != digest:
                continue
            if case["status"] == "pendiente":
                text = "comportamiento pendiente de reconstruir: " + "; ".join(case["pending"])
                return self._send(@PENDING@, text.encode("utf-8"), {"@HEADER@": "pendiente",
                                                         "Content-Type": "text/plain; charset=utf-8"})
            try:
                _apply_files(case)
            except Exception as exc:
                return self._send(@PENDING@, ("persistencia pendiente: " + str(exc)).encode("utf-8"),
                                  {"@HEADER@": "pendiente", "Content-Type": "text/plain; charset=utf-8"})
            headers = {"Content-Type": case["content_type"]} if case["content_type"] else {}
            return self._send(case["response_status"], _render(case["response_body"]).encode("utf-8"), headers)
        return self._send(@NOT_SPECIFIED@, "comportamiento no especificado para esta petición".encode("utf-8"),
                          {"@HEADER@": "no-especificado", "Content-Type": "text/plain; charset=utf-8"})

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _handle


def main(argv=None):
    parser = argparse.ArgumentParser(description="API HTTP reconstruida (solo comportamiento observado)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help="0 = puerto libre")
    args = parser.parse_args(argv)
    srv = Server((args.host, args.port), Handler)
    print(f"escuchando en http://{args.host}:{srv.server_address[1]}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''.replace("@APPLY_FILES@", _APPLY_FILES).replace("@PENDING@", str(HTTP_PENDING)).replace(
    "@NOT_SPECIFIED@", str(HTTP_NOT_SPECIFIED)).replace("@HEADER@", STATE_HEADER)

_HTTP_TESTS = '''"""Pruebas generadas desde la especificación: respuestas observadas de la API y escrituras capturadas."""
import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
CASES = json.loads((HERE / "api.json").read_text(encoding="utf-8"))
START_TIMEOUT = 60


def _start(cwd):
    """Arranca server.py con espera acotada; si no anuncia su dirección, falla mostrando su salida de error."""
    err = tempfile.TemporaryFile()
    p = subprocess.Popen([sys.executable, str(HERE / "server.py"), "--port", "0"], cwd=cwd,
                         stdout=subprocess.PIPE, stderr=err, text=True)
    p.eolfi_err = err
    lines = []
    reader = threading.Thread(target=lambda: lines.append(p.stdout.readline()), daemon=True)
    reader.start()
    reader.join(START_TIMEOUT)
    line = lines[0].strip() if lines else ""
    if not line.startswith("escuchando en "):
        p.kill()
        p.wait(timeout=10)
        reader.join(10)
        err.seek(0)
        detail = err.read().decode("utf-8", "replace")
        _stop(p)
        pytest.fail(f"server.py no arrancó en {START_TIMEOUT} s (salida: {line!r})\\n{detail}")
    return p, line.rsplit(" ", 1)[-1]


def _stop(p):
    if p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(timeout=10)
    p.stdout.close()
    p.eolfi_err.close()


def _request(base, method, path, body=None, ctype=None):
    req = urllib.request.Request(base + path, data=body, method=method,
                                 headers={"Content-Type": ctype} if ctype else {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        resp = opener.open(req, timeout=15)
    except urllib.error.HTTPError as exc:
        resp = exc
    with resp:
        return (resp.status if hasattr(resp, "status") else resp.code), resp.headers, resp.read()


@pytest.mark.parametrize("case", [c for c in CASES if c["status"] in ("simulado", "parcial")],
                         ids=lambda c: c["requirement"])
def test_respuestas_observadas(case, tmp_path):
    p, base = _start(tmp_path)
    try:
        body = base64.b64decode(case["request_body_base64"]) if case["request_body_base64"] is not None else None
        status, headers, data = _request(base, case["method"], case["path"], body, case["request_content_type"])
        assert status == case["response_status"]
        if case["method"] != "HEAD":
            assert data.decode("utf-8", "replace") == case["response_body"].replace("{sandbox}", str(tmp_path))
        if case["content_type"]:
            assert headers.get("Content-Type") == case["content_type"]
        for op in case.get("file_ops", []):
            path = tmp_path / op["path"]
            expected = base64.b64decode(op["data_base64"], validate=True)
            actual = path.read_bytes()
            if op.get("utf8"):
                actual = actual.replace(os.fsencode(tmp_path), b"{sandbox}")
            assert actual == expected
    finally:
        _stop(p)


def test_peticion_no_especificada(tmp_path):
    p, base = _start(tmp_path)
    try:
        status, headers, _ = _request(base, "GET", "/eolfi-ruta-no-observada")
        assert status == @NOT_SPECIFIED@ and headers.get("@HEADER@") == "no-especificado"
    finally:
        _stop(p)
'''.replace("@NOT_SPECIFIED@", str(HTTP_NOT_SPECIFIED)).replace("@HEADER@", STATE_HEADER)

_USAGE = {"python-cli": "    python app.py [argumentos] < entrada",
          "python-http": "    python server.py --port 8000\n\nLas peticiones no observadas responden "
                         f"{HTTP_NOT_SPECIFIED} y los casos pendientes {HTTP_PENDING} (cabecera `{STATE_HEADER}`)."}

_README = """# {name}

Reconstrucción independiente generada por Eolfi (objetivo `{target}`) desde la especificación v{spec_version}
del caso `{case_id}`. No contiene código del programa original.

## Estado por etapas

- Casos simulados completos (sin generalizar): {simulated}
- Casos parciales (reproducen solo los aspectos indicados): {partial}
- Casos pendientes: {pending}
- Componentes documentados sin generar: {not_generated}

## Uso

{usage}

## Trazabilidad

`.eolfi/trazabilidad.json` liga cada archivo y caso con su requisito y sus evidencias. Si editas un archivo
generado, una regeneración no lo pisa: escribe `<archivo>.nuevo` para que compares.
"""


_PRIMARY = {"python-cli": "cli", "python-http": "http_api"}
_HTTP_CASE_KEYS = ("requirement", "method", "path", "request_body_base64", "request_body_sha256",
                   "request_content_type", "status", "pending", "file_ops", "response_status", "content_type",
                   "response_body", "response_body_sha256")


def resolve_target(model: dict[str, Any], target: str | None) -> str:
    """Objetivo explícito, o el que permite el modelo: la CLI si la hay; si no, la API HTTP observada."""
    if target is not None:
        if target not in TARGETS:
            raise ValueError(f"objetivo no admitido: {target} (disponibles: {', '.join(TARGETS)})")
        return target
    ids = {c["id"] for c in model["components"] if c.get("cases")}
    if "cli" in ids:
        return "python-cli"
    if "http_api" in ids:
        return "python-http"
    raise ValueError("la especificación no tiene comportamiento de línea de comandos ni de API HTTP que reconstruir")


def _primary(model: dict[str, Any], target: str) -> dict[str, Any]:
    comp = next((c for c in model["components"] if c["id"] == _PRIMARY[target]), None)
    if comp is None or not comp.get("cases"):
        what = "línea de comandos" if target == "python-cli" else "API HTTP"
        raise ValueError(f"la especificación no tiene comportamiento de {what} que reconstruir")
    return comp


def _readme(model: dict[str, Any], name: str, target: str, cases: list[dict[str, Any]]) -> bytes:
    others = [c["title"] for c in model["components"] if c["id"] not in (_PRIMARY[target], "persistence")]
    return _README.format(name=name, target=target, spec_version=model["spec_version"], case_id=model["case_id"],
                          simulated=sum(c["status"] == "simulado" for c in cases),
                          partial=sum(c["status"] == "parcial" for c in cases),
                          pending=sum(c["status"] == "pendiente" for c in cases),
                          not_generated=", ".join(others) or "ninguno", usage=_USAGE[target]).encode("utf-8")


def _improvement_file(items: list[dict[str, Any]]) -> dict[str, tuple[bytes, list[str]]]:
    cfg = _imp.config(items)
    if not cfg:
        return {}
    reqs = sorted({r for it in items if it["status"] == "applied" for r in it.get("requirements", [])})
    return {"mejoras.json": (json.dumps(cfg, ensure_ascii=False, indent=2).encode("utf-8"), reqs)}


def _files(model: dict[str, Any], name: str, target: str,
           items: list[dict[str, Any]] | None = None) -> dict[str, tuple[bytes, list[str]]]:
    primary = _primary(model, target)
    if target == "python-http":
        cases = [{k: c[k] for k in _HTTP_CASE_KEYS} for c in primary["cases"]]
        reqs = sorted({c["requirement"] for c in cases})
        return {"server.py": (_SERVER.replace("{name}", name).encode("utf-8"), reqs),
                "api.json": (json.dumps(cases, ensure_ascii=False, indent=2).encode("utf-8"), reqs),
                "tests/test_server.py": (_HTTP_TESTS.encode("utf-8"), reqs),
                "README.md": (_readme(model, name, target, cases), []), **_improvement_file(items or [])}
    cases = [{k: c[k] for k in ("requirement", "args", "stdin", "stdout", "stderr", "exit_code", "status",
                                "pending", "file_ops")} for c in primary["cases"]]
    readme = _readme(model, name, target, cases)
    tests = '''"""Pruebas generadas desde la especificación: salidas observadas y escrituras capturadas."""
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CASES = json.loads((HERE / "comportamiento.json").read_text(encoding="utf-8"))


def test_casos_observados(tmp_path):
    for case in [c for c in CASES if c["status"] in ("simulado", "parcial")]:
        cwd = tmp_path / case["requirement"]
        cwd.mkdir()
        p = subprocess.run([sys.executable, str(HERE / "app.py"), *case["args"]], input=(case["stdin"] or "").encode(),
                           capture_output=True, cwd=cwd)
        assert p.returncode == case["exit_code"], case["requirement"]
        expected_stdout = case["stdout"].replace("{sandbox}", str(cwd))
        expected_stderr = case["stderr"].replace("{sandbox}", str(cwd))
        assert p.stdout.decode("utf-8", "replace").replace(chr(13) + chr(10), chr(10)) == expected_stdout, case["requirement"]
        assert p.stderr.decode("utf-8", "replace").replace(chr(13) + chr(10), chr(10)) == expected_stderr, case["requirement"]
        for op in case.get("file_ops", []):
            path = cwd / op["path"]
            assert op["action"] == "write" and path.is_file(), case["requirement"]
            expected = base64.b64decode(op["data_base64"], validate=True)
            actual = path.read_bytes()
            if op.get("utf8"):
                actual = actual.replace(os.fsencode(cwd), b"{sandbox}")
            assert actual == expected, case["requirement"]


def test_entrada_no_especificada():
    p = subprocess.run([sys.executable, str(HERE / "app.py"), "--entrada-no-observada"], input=b"", capture_output=True)
    assert p.returncode == 2
'''
    reqs = sorted({c["requirement"] for c in cases})
    return {"app.py": (_APP.replace("{name}", name).encode("utf-8"), reqs),
            "comportamiento.json": (json.dumps(cases, ensure_ascii=False, indent=2).encode("utf-8"), reqs),
            "tests/test_app.py": (tests.encode("utf-8"), reqs),
            "README.md": (readme, []), **_improvement_file(items or [])}


def generate(model: dict[str, Any], out: str | Path, *, name: str = "reconstruccion",
             target: str | None = None, improvements: list[str] | None = None) -> dict[str, Any]:
    """Escribe la base y el manifiesto; respeta los archivos modificados a mano desde la última generación.
    Sin ``target`` elige la CLI si el modelo la tiene y, si no, la API HTTP observada. ``improvements``: mejoras
    pedidas por el operador (``id`` o ``id=valor``); solo se aplican las compatibles y comprobables."""
    target = resolve_target(model, target)
    items = _imp.plan(improvements, target, _primary(model, target)["cases"])
    out = Path(out)
    manifest_path = out / MANIFEST
    old = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {"files": {}}
    written, kept, removed = [], [], []
    files_rec = {}
    files = _files(model, name, target, items)
    # Una mejora retirada en esta generación: su archivo se borra solo si nadie lo cambió a mano.
    for rel, prev in old["files"].items():
        dst = out / rel
        if rel not in files and rel == "mejoras.json" and dst.is_file():
            if prev.get("sha256") == _sha(dst.read_bytes()):
                dst.unlink()
                removed.append(rel)
            else:
                kept.append(rel)
                files_rec[rel] = {**prev, "manual_changes": True}
    for rel, (data, reqs) in files.items():
        dst = out / rel
        new_sha = _sha(data)
        prev = old["files"].get(rel)
        if dst.exists() and (prev is None or _sha(dst.read_bytes()) != prev["sha256"]):
            if _sha(dst.read_bytes()) != new_sha:
                Path(str(dst) + ".nuevo").write_bytes(data)
                kept.append(rel)
                files_rec[rel] = {**(prev or {}), "requirements": reqs, "manual_changes": True,
                                  "proposed_sha256": new_sha}
                continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        written.append(rel)
        files_rec[rel] = {"sha256": new_sha, "requirements": reqs}
    cli = _primary(model, target)
    manifest = {"generator": f"{PROVIDER} {VERSION}", "target": target, "name": name, "case_id": model["case_id"],
                "spec_version": model["spec_version"], "spec_sha256": model["spec_sha256"],
                "model_sha256": model["content_sha256"], "generated_at": time.time(), "files": files_rec,
                "components": [{"id": c["id"], "kind": c["kind"], "requirements": c["requirements"],
                                "generated": c["id"] == cli["id"] or (c["id"] == "persistence" and any(
                                    case.get("file_ops") for case in cli["cases"])),
                                "partial": c["id"] == "persistence" and any(
                                    case.get("pending") for case in cli["cases"])} for c in model["components"]],
                "cases": [{"requirement": c["requirement"], "status": c["status"], "pending": c["pending"],
                           "captured_paths": c["captured_paths"], "evidence_ids": c["evidence_ids"],
                           **({"route": f"{c['method']} {c['path']}"} if target == "python-http" else {})}
                          for c in cli["cases"]],
                "decisions": model["decisions"], "improvements": items}
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"out": str(out.resolve()), "written": written, "kept_manual": kept, "removed": removed,
            "manifest": MANIFEST, "improvements": items,
            "simulated": sum(c["status"] == "simulado" for c in cli["cases"]),
            "partial": sum(c["status"] == "parcial" for c in cli["cases"]),
            "pending": sum(c["status"] == "pendiente" for c in cli["cases"])}


# -- 3. verificación frente a la especificación ---------------------------------------------------------------
def normalize_paths(text: str, forms: set[str]) -> str:
    """Sustituye la carpeta de trabajo por {sandbox}. La forma más larga primero: en macOS /var/… es un enlace a
    /private/var/…, y sustituir antes la corta dejaría «/private{sandbox}» (el orden de un set varía)."""
    t = text.replace(chr(13) + chr(10), chr(10))
    for form in sorted(forms, key=len, reverse=True):
        t = t.replace(form, "{sandbox}")
    return t



def _file_aspects(case: dict[str, Any], tmp: str, forms: set[str]) -> list[str]:
    aspects = []
    for op in case.get("file_ops", []):
        path = Path(tmp) / op["path"]
        try:
            data = path.read_bytes()
        except OSError:
            aspects.append("archivos")
            continue
        normalized = data
        if op.get("utf8"):
            normalized = normalize_paths(data.decode("utf-8", "replace"), forms).encode("utf-8")
        if _sha(normalized) != op["sha256"]:
            aspects.append("archivos")
    return aspects


def _cli_aspects(out: Path, case: dict[str, Any], timeout: float,
                 env: dict[str, str] | None = None) -> list[str]:
    import os

    with tempfile.TemporaryDirectory(prefix="eolfi-rec-") as tmp:
        p = subprocess.run([sys.executable, str(out / "app.py"), *case["args"]],
                           input=(case["stdin"] or "").encode("utf-8"), capture_output=True, cwd=tmp,
                           timeout=timeout, env={**os.environ, **env} if env else None)
        forms = {tmp, str(Path(tmp).resolve())}

        def norm(b: bytes) -> str:
            return normalize_paths(b.decode("utf-8", "replace"), forms)
        aspects = _file_aspects(case, tmp, forms)
    if p.returncode != case["exit_code"]:
        aspects.append("código de salida")
    for name, got in (("stdout", p.stdout), ("stderr", p.stderr)):
        if _sha(norm(got).encode("utf-8")) != _sha(case[name].encode("utf-8")):
            aspects.append(name)
    return aspects


def _http_aspects(out: Path, case: dict[str, Any], timeout: float) -> list[str]:
    """Arranca la API generada en una carpeta vacía (un servidor por caso: sin estado compartido), repite la
    petición observada y compara estado, cuerpo, tipo de contenido y archivos capturados."""
    import base64

    with tempfile.TemporaryDirectory(prefix="eolfi-rec-") as tmp:
        p = subprocess.Popen([sys.executable, str(out / "server.py"), "--port", "0"], cwd=tmp,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            line = p.stdout.readline().strip() if p.stdout else ""
            if not line.startswith("escuchando en "):
                return ["arranque"]
            body = (base64.b64decode(case["request_body_base64"]) if case["request_body_base64"] is not None
                    else None)
            req = urllib.request.Request(line.rsplit(" ", 1)[-1] + case["path"], data=body, method=case["method"],
                                         headers={"Content-Type": case["request_content_type"]}
                                         if case["request_content_type"] else {})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                resp = opener.open(req, timeout=timeout)
            except urllib.error.HTTPError as exc:
                resp = exc
            except (urllib.error.URLError, OSError) as exc:
                return [f"petición ({type(exc).__name__})"]
            with resp:
                status, headers, data = (resp.status if hasattr(resp, "status") else resp.code), resp.headers, \
                    resp.read()
            forms = {tmp, str(Path(tmp).resolve())}
            aspects = _file_aspects(case, tmp, forms)
        finally:
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=10)
            if p.stdout:
                p.stdout.close()
    if status != case["response_status"]:
        aspects.append("respuesta[*].estado")
    if case["method"] != "HEAD":
        got = normalize_paths(data.decode("utf-8", "replace"), forms)
        if _sha(got.encode("utf-8")) != _sha(case["response_body"].encode("utf-8")):
            aspects.append("respuesta[*].cuerpo")
    if case["content_type"] and headers.get("Content-Type") != case["content_type"]:
        aspects.append("respuesta[*].cabeceras")
    return aspects


def _start_server(out: Path, cwd: str) -> tuple[subprocess.Popen, str | None]:
    p = subprocess.Popen([sys.executable, str(out / "server.py"), "--port", "0"], cwd=cwd,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    line = p.stdout.readline().strip() if p.stdout else ""
    return p, (line.rsplit(" ", 1)[-1] if line.startswith("escuchando en ") else None)


def _stop_server(p: subprocess.Popen) -> None:
    p.terminate()
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait(timeout=10)
    if p.stdout:
        p.stdout.close()


def _check_improvement(out: Path, item: dict[str, Any], cases: list[dict[str, Any]],
                       timeout: float) -> dict[str, Any]:
    """Ejecuta la comprobación de una mejora aplicada sobre la base generada."""
    import http.client

    res: dict[str, Any] = {"id": item["id"], "category": item["category"], "check": item["check"]}
    if item["id"] == "compatibilidad-utf8":
        bad = []
        for c in cases:
            if c["requirement"] in item.get("requirements", []) and c["status"] != "pendiente":
                aspects = _cli_aspects(out, c, timeout, env={"PYTHONIOENCODING": "ascii"})
                if aspects:
                    bad.append(f"{c['requirement']}: {', '.join(sorted(set(aspects)))}")
        return res | {"verified": not bad, "detail": bad or [f"{len(item.get('requirements', []))} casos con "
                                                               "salida no ASCII coinciden con PYTHONIOENCODING=ascii"]}
    with tempfile.TemporaryDirectory(prefix="eolfi-mejora-") as tmp:
        p, base = _start_server(out, tmp)
        try:
            if base is None:
                return res | {"verified": False, "detail": ["el servidor no arrancó"]}
            parts = urllib.parse.urlsplit(base)
            conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=timeout)
            try:
                if item["id"] == "seguridad-nosniff":
                    paths = ["/eolfi-ruta-no-observada"] + [c["path"] for c in cases
                                                             if c["status"] != "pendiente" and c["method"] == "GET"][:1]
                    got = []
                    for path in paths:
                        conn.request("GET", path)
                        r = conn.getresponse()
                        r.read()
                        got.append((path, r.getheader("X-Content-Type-Options")))
                        conn.close()
                    ok = all(v == "nosniff" for _p, v in got)
                    return res | {"verified": ok, "detail": [f"{path}: {v}" for path, v in got]}
                limit = item["params"]["bytes"]
                conn.putrequest("POST", "/eolfi-limite")
                conn.putheader("Content-Length", str(limit + 1))
                conn.putheader("Content-Type", "application/octet-stream")
                conn.endheaders()
                r = conn.getresponse()
                r.read()
                return res | {"verified": r.status == 413, "detail": [f"Content-Length {limit + 1}: {r.status}"]}
            except (OSError, http.client.HTTPException) as exc:
                return res | {"verified": False, "detail": [f"{type(exc).__name__}: {exc}"[:300]]}
            finally:
                conn.close()
        finally:
            _stop_server(p)


def _build_check(out: Path) -> dict[str, Any]:
    """La base compila: py_compile de cada archivo Python generado (sin escribir cachés)."""
    errors, n = [], 0
    for f in sorted(out.rglob("*.py")):
        if ".eolfi" in f.parts:
            continue
        n += 1
        try:
            compile(f.read_bytes(), str(f), "exec")
        except (SyntaxError, ValueError) as exc:
            errors.append(f"{f.relative_to(out).as_posix()}: {exc}"[:300])
    return {"python_files": n, "errors": errors, "status": "ok" if n and not errors else "error"}


INDEPENDENCE_MIN_LINE = 20
INDEPENDENCE_MAX_BYTES = 16 * 1024 * 1024


def independence(out: Path, sources: list[str | Path]) -> dict[str, Any]:
    """Comprueba que el código generado (archivos .py y README) no contiene líneas del objetivo original.

    Los datos generados (tabla de comportamiento, api.json) contienen a propósito salidas OBSERVADAS y no se
    comparan. Si el objetivo no está accesible o no es texto, se declara sin comprobar."""
    code = {}
    for f in sorted(out.rglob("*")):
        if f.is_file() and ".eolfi" not in f.parts and f.suffix in (".py", ".md"):
            code[f.relative_to(out).as_posix()] = {ln.strip() for ln in f.read_text(
                encoding="utf-8", errors="replace").splitlines() if len(ln.strip()) >= INDEPENDENCE_MIN_LINE}
    checked, shared, skipped = [], [], []
    for src in sources:
        p = Path(src)
        try:
            if not p.is_file() or p.stat().st_size > INDEPENDENCE_MAX_BYTES:
                skipped.append(f"{p.name}: no accesible o demasiado grande")
                continue
            text = p.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            skipped.append(f"{p.name}: no es texto UTF-8 (binario): sin comparar línea a línea")
            continue
        checked.append({"name": p.name, "sha256": _sha(p.read_bytes())})
        lines = {ln.strip() for ln in text.splitlines() if len(ln.strip()) >= INDEPENDENCE_MIN_LINE}
        for rel, mine in code.items():
            shared += [f"{rel}: {ln[:120]}" for ln in sorted(mine & lines)]
    status = "copia" if shared else "independiente" if checked else "no_comprobado"
    return {"status": status, "checked": checked, "shared_lines": shared[:50], "skipped": skipped,
            "limits": "Compara líneas de al menos 20 caracteres entre el código generado y el objetivo cuando "
                      "es texto accesible; no detecta copias reescritas ni compara binarios."}


def verify(out: str | Path, *, timeout: float = 30.0, sources: list[str | Path] | None = None) -> dict[str, Any]:
    out = Path(out).resolve()
    manifest = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    http = manifest.get("target") == "python-http"
    cases = json.loads((out / ("api.json" if http else "comportamiento.json")).read_text(encoding="utf-8"))
    results = []
    for case in cases:
        if case["status"] == "pendiente":
            results.append({"requirement": case["requirement"], "status": "pendiente", "pending": case["pending"]})
            continue
        aspects = sorted(set(_http_aspects(out, case, timeout) if http else _cli_aspects(out, case, timeout)))
        status = "difiere" if aspects else "parcial" if case["status"] == "parcial" else "coincide"
        results.append({"requirement": case["requirement"], "status": status, "aspects": aspects,
                        **({"route": f"{case['method']} {case['path']}"} if http else {}),
                        **({"pending": case["pending"]} if status == "parcial" else {})})
    ok = sum(r["status"] == "coincide" for r in results)
    partial = sum(r["status"] == "parcial" for r in results)
    pend = sum(r["status"] == "pendiente" for r in results)
    applied = [it for it in manifest.get("improvements", []) if it["status"] == "applied"]
    checks = [_check_improvement(out, it, cases, timeout) for it in applied]
    return {"out": str(out), "spec_version": manifest["spec_version"], "cases": len(results), "match": ok,
            "build": _build_check(out), "independence": independence(out, sources or []),
            "improvements": checks, "improvements_rejected": [it for it in manifest.get("improvements", [])
                                                              if it["status"] != "applied"],
            "improvements_verified": all(c["verified"] for c in checks) if checks else None,
            "partial": partial,
            "differ": len(results) - ok - partial - pend, "pending": pend, "results": results,
            "equivalent_on_observed": ok == len(results) - partial - pend and partial == 0 and ok > 0,
            # «complete» (decisión del titular 2026-11-11): además, sin casos pendientes. equivalent_on_observed
            # se mantiene igual para no romper a quien ya lo lee.
            "complete": ok == len(results) and ok > 0,
            "limits": "Solo cubre las entradas observadas; los casos pendientes y las entradas no observadas no "
                      "están reconstruidos. Coincidir aquí no demuestra equivalencia general."
                      + (" En la API HTTP no se comparan las cabeceras de la petición, ni las cookies ni las "
                         "redirecciones, ni las transiciones de estado entre peticiones." if http else "")}


def target_sources(store: EvidenceStore, case_id: str) -> list[str]:
    """Rutas de los objetivos observados del caso (para la comprobación de independencia)."""
    from eolfi.spec import latest_spec

    spec = latest_spec(store, case_id)
    found: list[str] = []
    for eid in (spec or {}).get("sources", {}).get("sessions", []):
        ev = store.get_evidence(eid)
        try:
            params = json.loads(ev["params"]) if ev else {}
        except (TypeError, ValueError):
            continue
        tpath = ((params.get("script") or {}).get("target") or {}).get("path")
        if not tpath:
            continue
        p = Path(tpath)
        if not p.is_absolute() and params.get("base_dir"):
            p = Path(params["base_dir"]) / p
        if str(p) not in found:
            found.append(str(p))
    return found


def reconstruct(store: EvidenceStore, case_id: str, out: str | Path, *, name: str = "reconstruccion",
                target: str | None = None, improvements: list[str] | None = None) -> dict[str, Any]:
    """Modelo → generación → verificación, con evidencia y registro «reconstruction» en el caso."""
    with case_run(store, case_id, "reconstruct", {"out": str(out), "target": target, "name": name,
                                                  "improvements": list(improvements or [])},
                  "reconstrucción desde la especificación del caso") as run:
        model = build_model(store, case_id)
        target = resolve_target(model, target)
        gen = generate(model, out, name=name, target=target, improvements=improvements)
        ver = verify(out, sources=target_sources(store, case_id))
        subject = f"proyecto:{Path(out).resolve()}"
        eid, _ = store.add_evidence(Evidence(
            subject=subject, provider=PROVIDER, provider_version=VERSION, operation="reconstruction_verification",
            params={"spec_version": model["spec_version"], "model_sha256": model["content_sha256"], "target": target},
            result={k: ver[k] for k in ("cases", "match", "differ", "pending", "results", "equivalent_on_observed",
                                        "complete", "build", "independence", "improvements",
                                        "improvements_rejected", "improvements_verified")},
            authority=Authority.CONTROLLED_REPRO, confidence=Confidence.MEDIUM, limitations=ver["limits"]))
        run.artifact(subject, size=None, format="project", identity="derived", content_sha256="",
                     path=gen["out"], metadata={"manifest": MANIFEST})
        status = "done" if ver["differ"] == 0 and ver["partial"] == 0 and ver["pending"] == 0 and ver["match"] > 0 \
            and ver["build"]["status"] == "ok" and ver["independence"]["status"] != "copia" \
            and ver["improvements_verified"] is not False else "partial"
        run.finish(status=status, evidence_ids=[eid],
                   tools=[{"name": PROVIDER, "version": VERSION, "status": "ran"},
                          {"name": "python", "version": sys.version.split()[0], "status": "ran"}],
                   errors=[f"{r['requirement']}: difiere en {', '.join(r['aspects'])}" for r in ver["results"]
                           if r["status"] == "difiere"][:200],
                   result={"out": gen["out"], "spec_version": model["spec_version"], "simulated": gen["simulated"],
                           "partial": gen["partial"],
                           "pending": gen["pending"], "match": ver["match"], "differ": ver["differ"],
                           "kept_manual": gen["kept_manual"]})
        return {"model": model, "generation": gen, "verification": ver, "evidence_id": eid,
                "case_record": getattr(run, "record_id", None)}
