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
from eolfi.acciones import registrada
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


def _tool_identity(tool, tool_sha=None, bundle_sha=None):
    """Identidad del ejecutable y de las bibliotecas de su carpeta; no demuestra procedencia."""
    digest = sha256(tool)
    if tool_sha and tool_sha != digest:
        raise ValueError("SHA-256 del cuantizador distinto del esperado")
    libraries = sorted({*tool.parent.glob("*.dll"), *tool.parent.glob("*.so*"), *tool.parent.glob("*.dylib")})
    if len(libraries) > 128:
        raise ValueError("Más de 128 bibliotecas junto al cuantizador: acota la instalación")
    if any(not p.is_file() for p in libraries):
        raise ValueError("Una biblioteca local no es un archivo legible")
    identity = {"archivo": str(tool), "sha256": digest, "version": "NO VERIFICADA",
                "bibliotecas_locales": [{"nombre": p.name, "archivo": str(p.resolve()), "sha256": sha256(p)}
                                         for p in libraries]}
    bundle = {"ejecutable": digest, "bibliotecas": [[p["nombre"], p["sha256"]]
                                                    for p in identity["bibliotecas_locales"]]}
    identity["bundle_sha256"] = hashlib.sha256(json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if bundle_sha and bundle_sha != identity["bundle_sha256"]:
        raise ValueError("SHA-256 del paquete del cuantizador distinto del esperado")
    return identity


def _child_env():
    # El hijo no restaura dependencias: no necesita URLs de pip/npm, proxies ni claves del cliente.
    env = {k: v for k, v in os.environ.items() if k.upper() in NATIVE_ENV}
    env.update(EOLAS_OFFLINE="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    return env


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
    tool_identity = _tool_identity(tool, tool_sha, bundle_sha)
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


@registrada("modelos.reconstruir", resultado=("estado", "salida", "sha256_salida", "respuesta", "aplicado", "adoptado", "perfil", "error"))
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
    env = _child_env()
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


# --- Smoke de inferencia de una reconstrucción (paso independiente de la conversión) ---

SMOKE_SCHEMA = "eolfi.modelos.smoke/v1"
SMOKE_PROMPT = "¿Cuánto es 17*3-8? Responde solo con el número."
SMOKE_EXPECTED = "43"
SMOKE_BUDGET = 16 * 1024 * 1024
PROFILE_SCHEMA = "eolfi.modelos.perfil/v1"


def _smoke_command(runner, model, prompt, tokens, threads):
    # Solo CPU: no reserva VRAM ni puertos, así que no compite por la GPU con un motor en marcha.
    # Ejecutor llama-cli: llama-completion (b11968) añade un sistema vacío con <|think|> aunque se pida
    # `-rea off`; aquí el pensamiento se apaga en la propia plantilla con enable_thinking=false.
    return [str(runner), "-m", str(model), "--device", "none", "-ngl", "0", "-t", str(threads),
            "-n", str(tokens), "-c", "2048", "--temp", "0", "--seed", "1", "--offline", "--simple-io",
            "--no-display-prompt", "--jinja", "-st", "-rea", "off",
            "--chat-template-kwargs", '{"enable_thinking":false}', "-p", prompt]


def _smoke_answer(text, prompt):
    """Respuesta del turno: entre el eco `> pregunta` de llama-cli y su línea de estadísticas.

    Sin esas marcas no se busca en la salida completa (la pancarta o la pregunta podrían contener el valor).
    Tampoco se usan pensamientos como respuesta, incluidos los truncados por el límite de tokens.
    """
    text = text.replace("\r\n", "\n")
    marker = "> " + prompt.replace("\r\n", "\n")
    if marker not in text:
        return ""
    text = text.rsplit(marker, 1)[1].split("\n[ Prompt:", 1)[0]
    if "<|channel>" in text:
        # Gemma cierra el canal de pensamiento con <channel|>; sin cierre, todo es pensamiento truncado.
        if "<channel|>" not in text:
            return ""
        text = text.rsplit("<channel|>", 1)[1]
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    return text.split("<think>", 1)[0].strip()


def prepare_smoke(folder, runner, *, bundle_sha=None, prompt=SMOKE_PROMPT, expected=SMOKE_EXPECTED,
                  tokens=64, threads=4, timeout=900):
    """Comprueba la carpeta de una reconstrucción terminada y prepara una pregunta; no ejecuta nada."""
    timeout = _timeout(timeout)
    folder, runner = Path(folder).expanduser().resolve(), Path(runner).expanduser().resolve()
    bundle_sha = _expected(bundle_sha, "del paquete")
    if type(threads) is not int or type(tokens) is not int or not 1 <= threads <= 64 or not 1 <= tokens <= 512:
        raise ValueError("Hilos o tokens fuera de rango (1–64 hilos; 1–512 tokens)")
    for label, text, limit in (("pregunta", prompt, 2000), ("respuesta esperada", expected, 200)):
        if not isinstance(text, str) or not text.strip() or len(text) > limit or "\0" in text:
            raise ValueError(f"La {label} debe ser texto no vacío de hasta {limit} caracteres")
    if not runner.is_file():
        raise ValueError("Se requiere un ejecutor local de llama.cpp")
    if os.name == "nt" and runner.suffix.lower() != ".exe":
        raise ValueError("En Windows se requiere un ejecutor .exe; no se ejecutan scripts de shell")
    recipe = json.loads((folder / "receta.json").read_text(encoding="utf-8"))
    model = folder / "modelo.gguf"
    conversion = recipe.get("conversion") or {}
    if (recipe.get("schema") != SCHEMA or recipe.get("estado") != "NO VERIFICADO" or conversion.get("exit") != 0
            or conversion.get("error") is not None or Path(recipe.get("salida", "")).resolve() != model
            or not model.is_file()):
        raise ValueError("La carpeta no contiene una reconstrucción terminada sin errores")
    before = _stamp(model)
    digest = sha256(model)
    if digest != (recipe.get("auditoria_salida") or {}).get("sha256"):
        raise ValueError("El modelo no coincide con el SHA-256 de salida de su receta")
    if before != _stamp(model):
        raise ValueError("El modelo cambió al preparar el smoke")
    return {"schema": SMOKE_SCHEMA, "estado": "preparado", "ejecutado": False,
            "fecha_utc": datetime.now(timezone.utc).isoformat(), "plataforma": sys.platform,
            "carpeta": str(folder), "modelo": str(model), "modelo_sha256": digest, "modelo_stamp": list(before),
            "entrada_sha256": recipe["entrada"]["sha256"], "cuantizacion": recipe["cuantizacion"],
            "herramienta": _tool_identity(runner, None, bundle_sha), "pregunta": prompt, "esperado": expected,
            "tokens": tokens, "hilos": threads, "timeout_segundos": timeout,
            "argv": _smoke_command(runner, model, prompt, tokens, threads),
            "verificacion": {"inferencia": "NO VERIFICADO", "banco": "NO VERIFICADO"},
            "limites": ["Una sola pregunta determinista en CPU: no mide calidad, velocidad en GPU ni equivalencia",
                        "No ejercita el servidor, las herramientas ni el planificador de Eolas (G6)",
                        "La identidad del ejecutor no verifica su procedencia ni su seguridad",
                        "Sin límite de RAM impuesto ni aislamiento de red del sistema",
                        "No se adopta el modelo ni se cambia la lista de confianza"]}


@registrada("modelos.probar", resultado=("estado", "salida", "sha256_salida", "respuesta", "aplicado", "adoptado", "perfil", "error"))
def execute_smoke(plan):
    """Ejecuta únicamente el plan en memoria que prepare_smoke acaba de verificar."""
    timeout = _timeout(plan["timeout_segundos"])
    folder, model = Path(plan["carpeta"]), Path(plan["modelo"])
    if (plan.get("schema") != SMOKE_SCHEMA or model != folder / "modelo.gguf"
            or plan["argv"] != _smoke_command(plan["herramienta"]["archivo"], model, plan["pregunta"],
                                              plan["tokens"], plan["hilos"])):
        raise ValueError("Plan o argumentos modificados")
    if list(_stamp(model)) != plan["modelo_stamp"]:
        raise ValueError("El modelo cambió después de preparar el smoke")
    for item in [plan["herramienta"], *plan["herramienta"]["bibliotecas_locales"]]:
        if sha256(item["archivo"]) != item["sha256"]:
            raise ValueError("El ejecutor o una biblioteca cambió después de preparar el smoke")
    name = "inferencia-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out_path, log_path, result_path = (folder / (name + ext) for ext in (".salida.txt", ".log", ".json"))
    step = {"exit": None, "error": None, "salida": str(out_path), "log": str(log_path)}
    plan.update(estado="en_ejecucion", ejecutado=True, resultado=str(result_path), ejecucion=step)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    started = time.monotonic()
    proc = None

    def save():
        temporary = result_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, result_path)

    def over_budget():
        return max(out_path.stat().st_size, log_path.stat().st_size) > SMOKE_BUDGET

    try:
        with out_path.open("xb") as out, log_path.open("xb") as log:
            proc = subprocess.Popen(plan["argv"], cwd=folder, env=_child_env(), stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=log, creationflags=flags,
                                    start_new_session=os.name != "nt")
            plan["pid_ejecutor"] = proc.pid
            save()
            while proc.poll() is None:
                if time.monotonic() - started > timeout:
                    raise TimeoutError("Tiempo de inferencia agotado")
                if over_budget():
                    raise RuntimeError("El ejecutor superó el presupuesto de salida o de registro")
                time.sleep(0.1)
            step["exit"] = proc.returncode
        if over_budget():
            raise RuntimeError("El ejecutor superó el presupuesto de salida o de registro")
        if step["exit"] != 0:
            raise RuntimeError(f"El ejecutor terminó con código {step['exit']}")
        answer = _smoke_answer(out_path.read_bytes().decode("utf-8", "replace"), plan["pregunta"])
        plan["respuesta"] = answer[:2000]
        if not re.search(r"(?<!\w)" + re.escape(plan["esperado"].strip()) + r"(?!\w)", answer):
            raise ValueError("La respuesta no contiene el valor esperado")
        plan["estado"] = "smoke_superado"
        plan["verificacion"]["inferencia"] = "smoke_superado: una pregunta determinista en CPU"
    except (OSError, ValueError, RuntimeError) as exc:
        step["error"] = str(exc)
        plan["estado"] = "fallido"
    except KeyboardInterrupt:
        plan["estado"] = "interrumpido"
        step["error"] = "Interrumpido por el usuario"
        raise
    finally:
        if proc is not None and proc.poll() is None:
            try:
                _terminate(proc)
            except (OSError, subprocess.TimeoutExpired) as exc:
                plan["estado"] = "fallido"
                step["error"] = f"NO VERIFICADO: no se pudo confirmar el cierre del ejecutor: {exc}"
        if proc is not None:
            step["exit"] = proc.returncode
        step["seconds"] = round(time.monotonic() - started, 3)
        if log_path.is_file():
            step["log_sha256"] = sha256(log_path)
            with log_path.open("rb") as stream:
                text = stream.read(SMOKE_BUDGET).decode("utf-8", "replace")
            if out_path.is_file():
                # llama-cli imprime versión y velocidad en stdout, no en el registro.
                with out_path.open("rb") as stream:
                    text += "\n" + stream.read(SMOKE_BUDGET).decode("utf-8", "replace")
            version = re.findall(r"build\s*:\s*([^\r\n]{1,200})", text)
            speed = re.findall(r"eval time\s*=[^\r\n]*?([\d.]+ tokens per second)|Generation:\s*([\d.]+ t/s)", text)
            speed = ["".join(s) for s in speed]
            if version:
                plan["herramienta"]["version_declarada_en_log"] = version[-1]
            if speed:
                step["velocidad_declarada_en_log"] = speed[-1]
        if plan["estado"] != "interrumpido":
            try:
                if list(_stamp(model)) != plan["modelo_stamp"] or sha256(model) != plan["modelo_sha256"]:
                    plan["estado"] = "fallido"
                    step["error"] = "El modelo cambió durante la inferencia"
            except OSError as exc:
                plan["estado"] = "fallido"
                step["error"] = f"No se pudo verificar el modelo al terminar: {exc}"
            except KeyboardInterrupt:
                plan["estado"] = "interrumpido"
                step["error"] = "Interrumpido al verificar el modelo después de inferencia"
                plan["verificacion"]["inferencia"] = "NO VERIFICADO"
                save()
                raise
        if plan["estado"] != "smoke_superado":
            plan["verificacion"]["inferencia"] = "NO VERIFICADO"
        save()
    return plan


def plan_profile(folder, profile, *, alias=None, ctx=32000, gpu_layers=8, batch=128, ubatch=64):
    """Valida una reconstrucción y propone un perfil Eolas sin modificar su configuración."""
    folder = Path(folder).expanduser().resolve()
    model, recipe_path = folder / "modelo.gguf", folder / "receta.json"
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", str(profile)):
        raise ValueError("El perfil debe usar minúsculas, números y guion bajo (2–64 caracteres)")
    values = {"ctx": ctx, "gpu_layers": gpu_layers, "batch": batch, "ubatch": ubatch}
    if any(type(value) is not int for value in values.values()):
        raise ValueError("Los límites del perfil deben ser enteros")
    if not 512 <= ctx <= 1_048_576 or not 0 <= gpu_layers <= 1024:
        raise ValueError("Contexto o capas GPU fuera de rango")
    if not 1 <= ubatch <= batch <= 4096:
        raise ValueError("Se requiere 1 <= ubatch <= batch <= 4096")
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    conversion = recipe.get("conversion") or {}
    if (recipe.get("schema") != SCHEMA or recipe.get("estado") != "NO VERIFICADO"
            or conversion.get("exit") != 0 or conversion.get("error") is not None
            or Path(recipe.get("salida", "")).resolve() != model or not model.is_file()):
        raise ValueError("La carpeta no contiene una reconstrucción terminada sin errores")
    before = _stamp(model)
    audit_result = audit(model)
    digest = audit_result.get("sha256")
    recorded_audit = recipe.get("auditoria_salida") or {}
    if audit_result.get("estado") == "fallido" or digest != recorded_audit.get("sha256"):
        raise ValueError("El modelo no coincide con el SHA-256 de salida de su receta")
    for key in ("arquitectura", "tensores", "tipo_archivo", "plantilla_sha256", "planificador",
                "declaraciones_tensores_sha256"):
        if audit_result.get(key) != recorded_audit.get(key):
            raise ValueError(f"El metadato {key} no coincide con la auditoría registrada")
    if before != _stamp(model):
        raise ValueError("El modelo cambió al planificar el perfil")
    architecture = audit_result.get("arquitectura")
    planner = audit_result.get("planificador") or {}
    prefix = str(architecture) + "."
    blocks, context = planner.get(prefix + "block_count"), planner.get(prefix + "context_length")
    sliding = planner.get(prefix + "attention.sliding_window")
    if type(blocks) is not int or blocks <= 0 or type(context) is not int or context <= 0:
        raise ValueError("El GGUF no declara capas y contexto válidos para el planificador")
    if ctx > context:
        raise ValueError(f"El contexto solicitado ({ctx}) supera el declarado por el GGUF ({context})")
    if gpu_layers > blocks:
        raise ValueError(f"Las capas GPU solicitadas ({gpu_layers}) superan las capas del modelo ({blocks})")
    if sliding is not None and (type(sliding) is not int or sliding <= 0 or sliding > context):
        raise ValueError("La ventana deslizante declarada no es válida")
    successful = []
    for evidence_path in sorted(folder.glob("inferencia-*.json"), reverse=True):
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        execution = evidence.get("ejecucion") or {}
        if (evidence.get("schema") == SMOKE_SCHEMA and evidence.get("estado") == "smoke_superado"
                and Path(evidence.get("modelo", "")).resolve() == model and evidence.get("modelo_sha256") == digest
                and execution.get("exit") == 0 and execution.get("error") is None
                and Path(evidence.get("resultado", "")).resolve() == evidence_path.resolve()
                and str((evidence.get("verificacion") or {}).get("inferencia", "")).startswith("smoke_superado")):
            successful.append((evidence_path, evidence))
    if not successful:
        raise ValueError("Falta un smoke superado para este mismo SHA-256")
    smoke_path, smoke = successful[0]
    proposed_alias = alias or f"{profile}:reconstruido"
    if not isinstance(proposed_alias, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", proposed_alias):
        raise ValueError("Alias de perfil inválido")
    unknown = list(audit_result.get("incognitas") or [])
    return {"schema": PROFILE_SCHEMA, "estado": "perfil_preparado_con_limites" if unknown else "perfil_preparado",
            "adoptado": False, "fecha_utc": datetime.now(timezone.utc).isoformat(),
            "perfil": profile, "modelo": str(model), "modelo_sha256": digest,
            "receta": str(recipe_path), "smoke": str(smoke_path),
            "arquitectura": architecture, "cuantizacion": recipe.get("cuantizacion"),
            "metadatos_planificador": planner,
            "plantilla": {"sha256": audit_result.get("plantilla_sha256"),
                           "bytes": audit_result.get("plantilla_bytes")},
            "propuesta": {"alias": proposed_alias, "model": str(model), "ctx": ctx,
                           "gpu_layers": gpu_layers, "batch": batch, "ubatch": ubatch,
                           "reasoning_format": "deepseek" if architecture in ("gemma", "gemma3", "gemma4") else None,
                           "chat_template_kwargs": {"enable_thinking": False}},
            "verificacion": {"conversion": "salida 0 y SHA-256 verificado",
                              "inferencia": smoke["verificacion"]["inferencia"],
                              "banco": "NO VERIFICADO"},
            "incognitas": unknown,
            "limites": ["La propuesta no modifica la configuración ni arranca el servidor",
                        "El smoke cubre una pregunta en CPU; no sustituye el banco ni el servidor Eolas",
                        "gpu_layers, batch y ubatch requieren validar memoria y rendimiento en el equipo",
                        "Los layouts de cuantización no cubiertos por el auditor siguen NO VERIFICADOS"]}


@registrada("eolas_v2.adoptar", campos=("plan_file", "expected_sha"), resultado=("estado", "salida", "sha256_salida", "respuesta", "aplicado", "adoptado", "perfil", "error"), si=lambda a: bool(a.get("apply")))
def adopt_profile(plan_file, expected_sha, *, apply=False):
    """Revalida un plan G6 y, solo con apply, añade un perfil nuevo sin activarlo."""
    expected_sha = _expected(expected_sha, "del modelo")
    path = Path(plan_file).expanduser().resolve()
    saved = json.loads(path.read_text(encoding="utf-8"))
    if saved.get("schema") != PROFILE_SCHEMA or saved.get("adoptado") is not False:
        raise ValueError("El archivo no es un plan de perfil sin adoptar")
    if saved.get("modelo_sha256") != expected_sha:
        raise ValueError("SHA-256 revisado distinto del plan")
    proposal = saved.get("propuesta") or {}
    model = Path(saved.get("modelo", "")).resolve()
    current = plan_profile(model.parent, saved.get("perfil"), alias=proposal.get("alias"),
                           ctx=proposal.get("ctx"), gpu_layers=proposal.get("gpu_layers"),
                           batch=proposal.get("batch"), ubatch=proposal.get("ubatch"))
    for key in ("modelo_sha256", "arquitectura", "cuantizacion", "metadatos_planificador", "plantilla", "propuesta"):
        if current.get(key) != saved.get(key):
            raise ValueError(f"El plan guardado ya no coincide: {key}")
    from eolfi import eolas_v2

    record = {"managed_by": eolas_v2.CUSTOM_PROFILE_MARKER, "alias": proposal["alias"],
              "model": str(model), "ctx": proposal["ctx"], "gpu_layers": proposal["gpu_layers"],
              "batch": proposal["batch"], "ubatch": proposal["ubatch"], "sha256": expected_sha,
              "reasoning": False,
              "reasoning_format": proposal.get("reasoning_format"),
              "chat_template_kwargs": proposal["chat_template_kwargs"],
              "source_recipe": current["receta"], "source_smoke": current["smoke"]}
    # Valida antes de anunciar siquiera la vista previa.
    eolas_v2._validate_custom_profile(current["perfil"], record)
    result = {"schema": "eolfi.modelos.adopcion/v1", "estado": "adopcion_preparada", "aplicado": False,
              "perfil": current["perfil"], "config": str(eolas_v2.config_file()), "registro": record,
              "active_profile": eolas_v2.load_config(create=False)["active_profile"],
              "limites": ["La vista previa no cambia la configuración ni arranca el motor",
                          "Aplicar añade un perfil nuevo, pero no lo selecciona como activo",
                          "Banco de la reconstrucción NO VERIFICADO"]}
    if apply:
        installed = eolas_v2.install_custom_profile(current["perfil"], record)
        result.update(estado="perfil_instalado_inactivo", aplicado=True, instalacion=installed)
    return result
