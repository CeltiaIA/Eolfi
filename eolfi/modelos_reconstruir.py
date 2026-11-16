"""Cuantización local explícita con receta y originales conservados.

No descarga herramientas, no adopta perfiles y no ejecuta inferencia.
"""
from __future__ import annotations

import json
import hashlib
import math
import os
import re
import shutil
import signal
import sys
import struct
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from eolfi.modelos import audit, sha256

TYPES = {"Q4_0": 2, "Q3_K_M": 12, "Q4_K_M": 15, "Q5_K_M": 17, "Q6_K": 18, "Q8_0": 7}
SCHEMA = "eolfi.modelos.reconstruccion/v1"
MARGIN = 64 * 1024 * 1024
NATIVE_ENV = {"PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "TMPDIR",
              "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
              "PROGRAMFILES(X86)", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "OS",
              "LANG", "LC_ALL", "LC_CTYPE"}


def _stamp(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ino


def _expected(value, label):
    if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", value)):
        raise ValueError(f"SHA-256 {label} inválido")
    return value.lower() if value is not None else None


def _command(tool, source, output, quant, threads, buffer_mib):
    return [str(tool), "--max-buffer-size", str(buffer_mib), str(source), str(output), quant, str(threads)]


def _timeout(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 86400:
        raise ValueError("Timeout fuera de rango (0–86400 s)")
    return float(value)


def prepare(source, destination, tool, quant, *, source_sha=None, tool_sha=None, bundle_sha=None,
            threads=4, buffer_mib=256, timeout=1800):
    started = time.monotonic()
    timeout = _timeout(timeout)
    source, destination, tool = (Path(p).expanduser().resolve() for p in (source, destination, tool))
    source_sha, tool_sha = _expected(source_sha, "de entrada"), _expected(tool_sha, "del cuantizador")
    bundle_sha = _expected(bundle_sha, "del paquete")
    if quant not in TYPES:
        raise ValueError("Tipo de cuantización no admitido")
    if type(threads) is not int or type(buffer_mib) is not int or not 1 <= threads <= 64 or not 16 <= buffer_mib <= 4096:
        raise ValueError("Hilos o memoria fuera de rango (1–64 hilos; 16–4096 MiB)")
    if destination.exists():
        raise FileExistsError("La salida debe ser una carpeta nueva; no sobrescribo recetas ni modelos")
    if source == tool or not source.is_file() or not tool.is_file():
        raise ValueError("Se requieren un GGUF de entrada y un cuantizador local distintos")
    if os.name == "nt" and tool.suffix.lower() != ".exe":
        raise ValueError("En Windows se requiere un cuantizador .exe; no se ejecutan scripts de shell")
    # Un lote dividido requiere tratar todas sus identidades y salidas; no afirmar cobertura monolítica.
    if re.search(r"-\d{5}-of-\d{5}\.gguf$", source.name, re.I):
        raise ValueError("Reconstrucción de entradas divididas NO VERIFICADA")
    before = _stamp(source)
    input_audit = audit(source)
    if input_audit["estado"] != "estructura_verificada":
        raise ValueError("La estructura de entrada no está verificada; revisa modelos auditar")
    if input_audit.get("division", {}).get("split.count", 1) > 1 or input_audit.get("division", {}).get("split.no", 0) != 0:
        raise ValueError("Reconstrucción de entradas divididas NO VERIFICADA, aunque se haya cambiado su nombre")
    if not input_audit.get("tipos_tensores") or not set(input_audit["tipos_tensores"]) <= {"0", "1", "30"}:
        raise ValueError("Solo se admite entrada F32/F16/BF16; no se requantizan pesos ya cuantizados")
    if not isinstance(input_audit.get("arquitectura"), str) or not input_audit["arquitectura"]:
        raise ValueError("La entrada necesita declarar su arquitectura")
    layers = input_audit["planificador"].get(input_audit["arquitectura"] + ".block_count")
    if layers is not None and (type(layers) is not int or layers <= 0):
        raise ValueError("El número de capas declarado no es válido para cuantizar")
    if source_sha and source_sha != input_audit["sha256"]:
        raise ValueError("SHA-256 de entrada distinto del esperado")
    digest = sha256(tool)
    if tool_sha and tool_sha != digest:
        raise ValueError("SHA-256 del cuantizador distinto del esperado")
    libraries = sorted({*tool.parent.glob("*.dll"), *tool.parent.glob("*.so*"), *tool.parent.glob("*.dylib")})
    if len(libraries) > 128:
        raise ValueError("Más de 128 bibliotecas junto al cuantizador: acota la instalación")
    if any(not p.is_file() for p in libraries):
        raise ValueError("Una biblioteca local no es un archivo legible")
    tool_identity = {"archivo": str(tool), "sha256": digest, "version": "NO VERIFICADA",
                     "bibliotecas_locales": [{"nombre": p.name, "archivo": str(p.resolve()), "sha256": sha256(p)}
                                              for p in libraries]}
    bundle = {"ejecutable": digest, "bibliotecas": [[p["nombre"], p["sha256"]]
                                                    for p in tool_identity["bibliotecas_locales"]]}
    tool_identity["bundle_sha256"] = hashlib.sha256(json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if bundle_sha and bundle_sha != tool_identity["bundle_sha256"]:
        raise ValueError("SHA-256 del paquete del cuantizador distinto del esperado")
    if before != _stamp(source):
        raise ValueError("La entrada cambió al preparar la receta")
    return {"schema": SCHEMA, "estado": "preparado", "ejecutado": False,
            "fecha_utc": datetime.now(timezone.utc).isoformat(), "plataforma": sys.platform,
            "version_sistema": list(sys.getwindowsversion()[:3]) if hasattr(sys, "getwindowsversion") else list(os.uname()),
            "bits_python": struct.calcsize("P") * 8,
            "entrada": input_audit, "herramienta": tool_identity, "cuantizacion": quant,
            "entrada_stamp": list(before),
            "hilos": threads, "memoria_mib": buffer_mib,
            "timeout_segundos": timeout,
            "preparacion_segundos": round(time.monotonic() - started, 3),
            "carpeta_salida": str(destination), "salida": str(destination / "modelo.gguf"),
            "argv": _command(tool, source, destination / "modelo.gguf", quant, threads, buffer_mib),
            "verificacion": {"inferencia": "NO VERIFICADO", "banco": "NO VERIFICADO"},
            "limites": ["La identidad de la herramienta no verifica su procedencia ni su seguridad",
                        "Bibliotecas del sistema y módulos cargados dinámicamente no inventariados",
                        "No se adopta el modelo ni se cambia la lista de confianza",
                        "Sin aislamiento de red del sistema; los indicadores offline no equivalen a cortafuegos"]}


def _save(folder, result):
    temporary = folder / "receta.json.tmp"
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, folder / "receta.json")


def _terminate(proc):
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                           timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=10)


def execute(recipe, *, timeout=None):
    """Ejecuta únicamente la receta en memoria que prepare acaba de verificar."""
    timeout = _timeout(recipe.get("timeout_segundos", 1800) if timeout is None else timeout)
    recipe["timeout_segundos"] = timeout
    folder, source, output = Path(recipe["carpeta_salida"]), Path(recipe["entrada"]["archivo"]), Path(recipe["salida"])
    if (recipe.get("schema") != SCHEMA or output != folder / "modelo.gguf"
            or recipe["argv"] != _command(recipe["herramienta"]["archivo"], source, output,
                                          recipe["cuantizacion"], recipe["hilos"], recipe["memoria_mib"])):
        raise ValueError("Receta o argumentos modificados")
    if list(_stamp(source)) != recipe["entrada_stamp"]:
        raise ValueError("La entrada cambió después de preparar la receta")
    for item in [recipe["herramienta"], *recipe["herramienta"]["bibliotecas_locales"]]:
        if sha256(item["archivo"]) != item["sha256"]:
            raise ValueError("El cuantizador o una biblioteca cambió después de preparar la receta")
    parent = next(p for p in [folder.parent, *folder.parents] if p.is_dir())
    if shutil.disk_usage(parent).free < recipe["entrada"]["bytes"] + MARGIN:
        raise OSError("Espacio insuficiente: se reserva conservadoramente el tamaño de entrada más 64 MiB")
    folder.mkdir(parents=True, exist_ok=False)
    recipe.update(estado="en_ejecucion", ejecutado=True)
    _save(folder, recipe)
    started = time.monotonic()
    before = _stamp(source)
    # El cuantizador no restaura dependencias: no necesita URLs de pip/npm, proxies ni claves del cliente.
    env = {k: v for k, v in os.environ.items() if k.upper() in NATIVE_ENV}
    env.update(EOLAS_OFFLINE="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    step = {"exit": None, "error": None, "log": str(folder / "cuantizador.log")}
    proc = None
    cancelled = False
    try:
        with (folder / "cuantizador.log").open("wb") as log:
            proc = subprocess.Popen(recipe["argv"], cwd=folder, env=env, stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
                                    start_new_session=os.name != "nt")
            recipe["pid_cuantizador"] = proc.pid
            _save(folder, recipe)
            while proc.poll() is None:
                if time.monotonic() - started > timeout:
                    raise TimeoutError("Tiempo de cuantización agotado")
                if (folder / "cuantizador.log").stat().st_size > 16 * 1024 * 1024 or (output.exists() and output.stat().st_size > recipe["entrada"]["bytes"] + MARGIN):
                    raise RuntimeError("El cuantizador superó el presupuesto de salida o de registro")
                time.sleep(0.1)
            step["exit"] = proc.returncode
        if (folder / "cuantizador.log").stat().st_size > 16 * 1024 * 1024 or (output.exists() and output.stat().st_size > recipe["entrada"]["bytes"] + MARGIN):
            raise RuntimeError("El cuantizador superó el presupuesto de salida o de registro")
        if step["exit"] != 0:
            raise RuntimeError(f"El cuantizador terminó con código {step['exit']}")
        output_audit = audit(output)
        recipe["auditoria_salida"] = output_audit
        if output_audit["estado"] == "fallido":
            raise ValueError("La salida no supera la auditoría GGUF")
        if (output_audit.get("tensores") != recipe["entrada"]["tensores"]
                or output_audit.get("arquitectura") != recipe["entrada"]["arquitectura"]
                or output_audit.get("plantilla_sha256") != recipe["entrada"]["plantilla_sha256"]
                or output_audit.get("planificador") != recipe["entrada"]["planificador"]
                or output_audit.get("declaraciones_tensores_sha256") != recipe["entrada"]["declaraciones_tensores_sha256"]
                or output_audit.get("tipo_archivo") != TYPES[recipe["cuantizacion"]]):
            raise ValueError("Arquitectura, tensores, plantilla o cuantización de salida no coinciden con la receta")
        recipe["estado"] = "NO VERIFICADO"  # conversión terminada; inferencia y banco son un paso independiente
    except (OSError, ValueError, RuntimeError) as exc:
        step["error"] = str(exc)
        recipe["estado"] = "fallido"
    except KeyboardInterrupt:
        cancelled = True
        recipe["estado"] = "interrumpido"
        step["error"] = "Interrumpido por el usuario"
        raise
    finally:
        if proc is not None and proc.poll() is None:
            try:
                _terminate(proc)
            except (OSError, subprocess.TimeoutExpired) as exc:
                recipe["estado"] = "fallido"
                step["error"] = f"NO VERIFICADO: no se pudo confirmar el cierre del cuantizador: {exc}"
        if proc is not None:
            step["exit"] = proc.returncode
        step["seconds"] = round(time.monotonic() - started, 3)
        recipe["conversion"] = step
        log_path = folder / "cuantizador.log"
        if log_path.is_file():
            step["log_sha256"] = sha256(log_path)
            with log_path.open("rb") as stream:
                prefix = stream.read(1024 * 1024).decode("utf-8", "replace")
            version = re.search(r"^version:\s*([^\r\n]{1,200})", prefix, re.M)
            if version:
                recipe["herramienta"]["version_declarada_en_log"] = version.group(1)
        if proc is not None and not cancelled:
            try:
                recipe["sha256_entrada_despues"] = sha256(source)
                if before != _stamp(source) or recipe["sha256_entrada_despues"] != recipe["entrada"]["sha256"]:
                    recipe["estado"] = "fallido"
                    step["error"] = "La entrada cambió durante la cuantización"
            except OSError as exc:
                recipe["estado"] = "fallido"
                step["error"] = f"No se pudo verificar la entrada al terminar: {exc}"
            except KeyboardInterrupt:
                recipe["estado"] = "interrumpido"
                step["error"] = "Interrumpido al verificar la entrada original"
                recipe["verificacion"]["entrada_despues"] = "NO VERIFICADO: comprobación interrumpida"
                recipe["ejecucion_segundos"] = round(time.monotonic() - started, 3)
                _save(folder, recipe)
                raise
        else:
            recipe["verificacion"]["entrada_despues"] = "NO VERIFICADO: proceso no iniciado o interrumpido"
        recipe["ejecucion_segundos"] = round(time.monotonic() - started, 3)
        _save(folder, recipe)
    return recipe
