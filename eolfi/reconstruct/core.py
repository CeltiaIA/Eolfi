"""Reconstrucción independiente y trazable a partir de la especificación del caso (Fase 4).

Tres piezas separadas:

1. ``build_model``: **modelo de comportamiento** independiente de cualquier generador. Deriva componentes
   (interfaz de línea de comandos, API HTTP, interfaz de usuario, persistencia), sus interfaces y datos a partir
   de los requisitos y de las evidencias de observación, con cada decisión, sus alternativas y su motivo. No
   mira el código del original (no lo tiene) ni asume que detectar un framework baste.
2. ``generate``: generador de una **base ejecutable** para un lenguaje/plataforma (hoy: CLI en Python estándar)
   por etapas. Etapa 1 = reproducir los casos observados (tabla de comportamiento): cada caso queda marcado como
   *simulado* (no generaliza a entradas no observadas); lo que no se puede reproducir con la evidencia disponible
   (contenido de archivos solo conocido por hash, salidas truncadas, contradicciones) queda *pendiente*.
   Un manifiesto ``.eolfi/trazabilidad.json`` liga cada archivo y caso a su requisito y evidencia, y la
   regeneración nunca pisa un archivo modificado a mano (escribe ``<archivo>.nuevo`` y lo informa).
3. ``verify``: ejecuta la base generada con las entradas observadas y compara con lo esperado en la
   especificación (código de salida, stdout y stderr normalizados). Guarda la evidencia y el registro del caso.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from eolfi.core.cases import case_run
from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Authority, Confidence, Evidence

MODEL_FORMAT = 1
PROVIDER = "eolfi.reconstruct"
VERSION = "1.0.0"
MANIFEST = ".eolfi/trazabilidad.json"
TARGETS = {"python-cli": "Línea de comandos en Python (solo biblioteca estándar)"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _session_step(store: EvidenceStore, eid: str, step_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    ev = store.get_evidence(eid)
    session, params = json.loads(ev["result"]), json.loads(ev["params"])
    step = next(s for s in session["steps"] if s["id"] == step_id)
    sstep = next(s for s in params["script"]["steps"] if s["id"] == step_id)
    return step, sstep


# -- 1. modelo de comportamiento ---------------------------------------------------------------------------
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
            file_effects = [e for e in step.get("effects", {}).get("files", [])]
            if file_effects:
                d = comp("persistence", "persistence", "Persistencia en archivos")
                d["requirements"].append(r["id"])
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
            if r["persistence"] and any(p["kind"] == "registry" for p in r["persistence"]):
                case["pending"].append("efectos en el registro de Windows sin implementar")
            if case["pending"] and case["status"] == "simulado":
                case["status"] = "parcial"
            c["cases"].append(case)
        elif act == "http":
            c = comp("http_api", "http_api", "API HTTP observada")
            c["requirements"].append(r["id"])
            c["interfaces"].append({"method": r["inputs"].get("method"), "url": r["inputs"].get("url")})
        elif act in ("browser", "desktop"):
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
    for kind in ("http_api", "ui"):
        if kind in components:
            decisions.append({"decision": f"Componente «{components[kind]['title']}» documentado, sin generar",
                              "reason": "el generador de esta etapa solo cubre la CLI",
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
import base64
from pathlib import Path

CASES = json.loads((Path(__file__).with_name("comportamiento.json")).read_text(encoding="utf-8"))


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
        sys.stdout.write(_render(case["stdout"]))
        sys.stderr.write(_render(case["stderr"]))
        return case["exit_code"] if case["exit_code"] is not None else 0
    sys.stderr.write("comportamiento no especificado para estas entradas" + chr(10))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
'''

_README = """# {name}

Reconstrucción independiente generada por Eolfi (objetivo `{target}`) desde la especificación v{spec_version}
del caso `{case_id}`. No contiene código del programa original.

## Estado por etapas

- Casos simulados completos (sin generalizar): {simulated}
- Casos parciales (reproducen solo los aspectos indicados): {partial}
- Casos pendientes: {pending}
- Componentes documentados sin generar: {not_generated}

## Uso

    python app.py [argumentos] < entrada

## Trazabilidad

`.eolfi/trazabilidad.json` liga cada archivo y caso con su requisito y sus evidencias. Si editas un archivo
generado, una regeneración no lo pisa: escribe `<archivo>.nuevo` para que compares.
"""


def _files(model: dict[str, Any], name: str, target: str) -> dict[str, tuple[bytes, list[str]]]:
    cli = next((c for c in model["components"] if c["id"] == "cli"), None)
    if cli is None:
        raise ValueError("la especificación no tiene comportamiento de línea de comandos que reconstruir")
    cases = [{k: c[k] for k in ("requirement", "args", "stdin", "stdout", "stderr", "exit_code", "status",
                                "pending", "file_ops")} for c in cli["cases"]]
    others = [c["title"] for c in model["components"] if c["id"] not in ("cli", "persistence")]
    readme = _README.format(name=name, target=target, spec_version=model["spec_version"], case_id=model["case_id"],
                            simulated=sum(c["status"] == "simulado" for c in cases),
                            partial=sum(c["status"] == "parcial" for c in cases),
                            pending=sum(c["status"] == "pendiente" for c in cases),
                            not_generated=", ".join(others) or "ninguno")
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
            "README.md": (readme.encode("utf-8"), [])}


def generate(model: dict[str, Any], out: str | Path, *, name: str = "reconstruccion",
             target: str = "python-cli") -> dict[str, Any]:
    """Escribe la base y el manifiesto; respeta los archivos modificados a mano desde la última generación."""
    if target not in TARGETS:
        raise ValueError(f"objetivo no admitido: {target} (disponibles: {', '.join(TARGETS)})")
    out = Path(out)
    manifest_path = out / MANIFEST
    old = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {"files": {}}
    written, kept = [], []
    files_rec = {}
    for rel, (data, reqs) in _files(model, name, target).items():
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
    cli = next(c for c in model["components"] if c["id"] == "cli")
    manifest = {"generator": f"{PROVIDER} {VERSION}", "target": target, "name": name, "case_id": model["case_id"],
                "spec_version": model["spec_version"], "spec_sha256": model["spec_sha256"],
                "model_sha256": model["content_sha256"], "generated_at": time.time(), "files": files_rec,
                "components": [{"id": c["id"], "kind": c["kind"], "requirements": c["requirements"],
                                "generated": c["id"] == "cli" or (c["id"] == "persistence" and any(
                                    case.get("file_ops") for case in cli["cases"])),
                                "partial": c["id"] == "persistence" and any(
                                    case.get("pending") for case in cli["cases"])} for c in model["components"]],
                "cases": [{"requirement": c["requirement"], "status": c["status"], "pending": c["pending"],
                           "captured_paths": c["captured_paths"], "evidence_ids": c["evidence_ids"]}
                          for c in cli["cases"]],
                "decisions": model["decisions"]}
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"out": str(out.resolve()), "written": written, "kept_manual": kept, "manifest": MANIFEST,
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



def verify(out: str | Path, *, timeout: float = 30.0) -> dict[str, Any]:
    out = Path(out).resolve()
    manifest = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    cases = json.loads((out / "comportamiento.json").read_text(encoding="utf-8"))
    results = []
    for case in cases:
        if case["status"] == "pendiente":
            results.append({"requirement": case["requirement"], "status": "pendiente", "pending": case["pending"]})
            continue
        with tempfile.TemporaryDirectory(prefix="eolfi-rec-") as tmp:
            p = subprocess.run([sys.executable, str(out / "app.py"), *case["args"]],
                               input=(case["stdin"] or "").encode("utf-8"), capture_output=True, cwd=tmp,
                               timeout=timeout)
            forms = {tmp, str(Path(tmp).resolve())}

            def norm(b: bytes) -> str:
                return normalize_paths(b.decode("utf-8", "replace"), forms)
            file_aspects = []
            for op in case.get("file_ops", []):
                path = Path(tmp) / op["path"]
                try:
                    data = path.read_bytes()
                except OSError:
                    file_aspects.append("archivos")
                    continue
                normalized = data
                if op.get("utf8"):
                    normalized = normalize_paths(data.decode("utf-8", "replace"), forms).encode("utf-8")
                if _sha(normalized) != op["sha256"]:
                    file_aspects.append("archivos")
        got = {"exit_code": p.returncode, "stdout": _sha(norm(p.stdout).encode("utf-8")),
               "stderr": _sha(norm(p.stderr).encode("utf-8"))}
        aspects = file_aspects
        if got["exit_code"] != case["exit_code"]:
            aspects.append("código de salida")
        for name in ("stdout", "stderr"):
            expected = _sha(case[name].encode("utf-8"))
            if got[name] != expected:
                aspects.append(name)
        aspects = sorted(set(aspects))
        status = "difiere" if aspects else "parcial" if case["status"] == "parcial" else "coincide"
        results.append({"requirement": case["requirement"], "status": status, "aspects": aspects,
                        **({"pending": case["pending"]} if status == "parcial" else {})})
    ok = sum(r["status"] == "coincide" for r in results)
    partial = sum(r["status"] == "parcial" for r in results)
    pend = sum(r["status"] == "pendiente" for r in results)
    return {"out": str(out), "spec_version": manifest["spec_version"], "cases": len(results), "match": ok,
            "partial": partial,
            "differ": len(results) - ok - partial - pend, "pending": pend, "results": results,
            "equivalent_on_observed": ok == len(results) - partial - pend and partial == 0 and ok > 0,
            "limits": "Solo cubre las entradas observadas; los casos pendientes y las entradas no observadas no "
                      "están reconstruidos. Coincidir aquí no demuestra equivalencia general."}


def reconstruct(store: EvidenceStore, case_id: str, out: str | Path, *, name: str = "reconstruccion",
                target: str = "python-cli") -> dict[str, Any]:
    """Modelo → generación → verificación, con evidencia y registro «reconstruction» en el caso."""
    with case_run(store, case_id, "reconstruct", {"out": str(out), "target": target, "name": name},
                  "reconstrucción desde la especificación del caso") as run:
        model = build_model(store, case_id)
        gen = generate(model, out, name=name, target=target)
        ver = verify(out)
        subject = f"proyecto:{Path(out).resolve()}"
        eid, _ = store.add_evidence(Evidence(
            subject=subject, provider=PROVIDER, provider_version=VERSION, operation="reconstruction_verification",
            params={"spec_version": model["spec_version"], "model_sha256": model["content_sha256"], "target": target},
            result={k: ver[k] for k in ("cases", "match", "differ", "pending", "results", "equivalent_on_observed")},
            authority=Authority.CONTROLLED_REPRO, confidence=Confidence.MEDIUM, limitations=ver["limits"]))
        run.artifact(subject, size=None, format="project", identity="derived", content_sha256="",
                     path=gen["out"], metadata={"manifest": MANIFEST})
        status = "done" if ver["differ"] == 0 and ver["partial"] == 0 and ver["pending"] == 0 and ver["match"] > 0 else "partial"
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
