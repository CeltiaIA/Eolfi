"""Modelo local con llama.cpp (por defecto Gemma 4) para todo Eolfi: configuración común, arranque y parada.

La configuración vive en ~/.eolfi/llamacpp.json (EOLFI_LLAMACPP_CONFIG) y la comparten el modo asistido de Eolfi
(proveedor «gemma») y la extensión de VS Code (@eolfi con el modelo local). Campos:

  server          llama-server.exe (vacío = el primero que se encuentre)
  model           .gguf (vacío = Gemma 4: E4B si existe, si no 12B)
  port            puerto en 127.0.0.1 (8090)
  ctx             contexto en tokens (32768: los lotes de la auditoría llegan a ~20 000)
  gpu_layers      capas en la GPU (99 = todas las que quepan)
  reasoning       razonamiento del modelo en el agente y el modo asistido (true)
  review_reasoning razonamiento en las revisiones de la auditoría archivo por archivo (false: más rápido)
  show_reasoning  mostrar el razonamiento en el chat (true)
  temperature, top_p, max_tokens
  system          instrucciones propias que se añaden a las de Eolfi (tono, idioma, estilo, reglas…)
  extra_args      argumentos extra para llama-server (lista)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

SERVER_CANDIDATES = [
    Path.home() / ".eolfi" / "tools" / "llama" / "llama-server.exe",
    Path(r"D:\HYDRA-BASE\llama\llama-server.exe"),
    Path(r"D:\HYDRA\runtime\llama-bin\llama-server.exe"),
    Path(r"D:\EOLAS-BASE\llama\llama-server.exe"),
]
GEMMA_CANDIDATES = [
    Path.home() / ".eolfi" / "models" / "gemma-4-E4B-it-Q4_K_M.gguf",
    Path(r"D:\LMStudio\models\lmstudio-community\gemma-4-E4B-it-GGUF\gemma-4-E4B-it-Q4_K_M.gguf"),
    Path(r"D:\AI\Hydra\gguf\gemma-4-12b-it-Q5_K_M.gguf"),
]

DEFAULTS: dict[str, Any] = {
    "server": "",
    "model": "",
    "alias": "gemma-4",
    "port": 8090,
    "ctx": 32768,
    "gpu_layers": 99,
    "reasoning": True,
    "review_reasoning": False,
    "show_reasoning": True,
    "temperature": 0.7,
    "top_p": 0.95,
    "max_tokens": 4096,
    "system": "",
    "extra_args": [],
}


def config_file() -> Path:
    return Path(os.environ.get("EOLFI_LLAMACPP_CONFIG") or Path.home() / ".eolfi" / "llamacpp.json")


def _find_server() -> str:
    for c in SERVER_CANDIDATES:
        if c.is_file():
            return str(c)
    return shutil.which("llama-server") or ""


def _find_model() -> str:
    for c in GEMMA_CANDIDATES:
        if c.is_file():
            return str(c)
    return ""


def load_config(create: bool = True) -> dict[str, Any]:
    """Configuración con los valores por defecto completados; la crea la primera vez (sin pisar la tuya)."""
    f = config_file()
    user: dict[str, Any] = {}
    if f.is_file():
        try:
            user = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            user = {}
    elif create:
        first = dict(DEFAULTS, server=_find_server(), model=_find_model())
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(first, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        user = first
    cfg = {**DEFAULTS, **{k: v for k, v in user.items() if k in DEFAULTS}}
    cfg["server"] = cfg["server"] or _find_server()
    cfg["model"] = cfg["model"] or _find_model()
    cfg["port"] = int(cfg["port"])
    return cfg


def base_url(cfg: dict[str, Any] | None = None) -> str:
    cfg = cfg or load_config()
    return f"http://127.0.0.1:{cfg['port']}"


def server_args(cfg: dict[str, Any]) -> list[str]:
    """Solo 127.0.0.1; plantillas jinja (herramientas) y razonamiento separado en reasoning_content."""
    return [cfg["server"], "-m", cfg["model"], "--host", "127.0.0.1", "--port", str(cfg["port"]), "-c", str(cfg["ctx"]),
            "-ngl", str(cfg["gpu_layers"]), "--alias", cfg["alias"], "--jinja", "--reasoning-format", "deepseek",
            *[str(a) for a in cfg.get("extra_args") or []]]


def healthy(cfg: dict[str, Any] | None = None, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url(cfg)}/health", timeout=timeout) as r:
            return r.status == 200
    except OSError:
        return False


def _pid_file() -> Path:
    return config_file().with_suffix(".pid")


def start(cfg: dict[str, Any] | None = None, wait: float = 300.0) -> dict[str, Any]:
    """Arranca llama-server si no está en marcha (queda en segundo plano; se para con stop())."""
    cfg = cfg or load_config()
    if healthy(cfg):
        return {"running": True, "url": base_url(cfg), "started": False}
    if not cfg["server"] or not Path(cfg["server"]).is_file():
        raise FileNotFoundError(f"No encuentro llama-server.exe: pon su ruta en «server» de {config_file()}")
    if not cfg["model"] or not Path(cfg["model"]).is_file():
        raise FileNotFoundError(f"No encuentro el modelo .gguf: pon su ruta en «model» de {config_file()}")
    log = config_file().with_suffix(".log")
    flags = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
             | getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0
    with open(log, "ab") as out:
        def launch(extra: int = 0):
            return subprocess.Popen(server_args(cfg), stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    creationflags=flags | extra, start_new_session=os.name != "nt")
        # DETACHED_PROCESS no saca el proceso del Job Object de quien lo lanza: si ese terminal (VS Code, un
        # agente, un sandbox) cierra su Job, mataría a llama-server sin dejar rastro en el registro. Se intenta
        # salir del Job; si este no lo permite (acceso denegado), se lanza como antes.
        breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0) if os.name == "nt" else 0
        try:
            p = launch(breakaway)
        except OSError:
            if not breakaway:
                raise
            p = launch()
    _pid_file().write_text(str(p.pid), encoding="utf-8")
    t0 = time.time()
    while time.time() - t0 < wait:
        if p.poll() is not None:
            raise RuntimeError(f"llama-server se cerró al arrancar (mira {log}; ¿el modelo no cabe? baja «gpu_layers» o «ctx»)")
        if healthy(cfg):
            return {"running": True, "url": base_url(cfg), "started": True, "pid": p.pid}
        time.sleep(1)
    raise TimeoutError(f"llama-server no estuvo listo en {int(wait)} s (mira {log})")


def stop() -> bool:
    """Para el llama-server que arrancó Eolfi (por su pid guardado)."""
    pf = _pid_file()
    if not pf.is_file():
        return False
    try:
        pid = int(pf.read_text(encoding="utf-8").strip())
    except ValueError:
        pf.unlink(missing_ok=True)
        return False
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=30)
        else:
            os.kill(pid, 15)
    finally:
        pf.unlink(missing_ok=True)
    return True


def status() -> dict[str, Any]:
    cfg = load_config()
    return {"config": str(config_file()), "url": base_url(cfg), "running": healthy(cfg), "server": cfg["server"],
            "model": cfg["model"], "reasoning": cfg["reasoning"], "show_reasoning": cfg["show_reasoning"],
            "temperature": cfg["temperature"], "max_tokens": cfg["max_tokens"]}


def request_options(cfg: dict[str, Any], *, reasoning: bool | None = None) -> dict[str, Any]:
    """Parámetros de cada petición (API de OpenAI de llama-server)."""
    think = cfg["reasoning"] if reasoning is None else reasoning
    return {"temperature": cfg["temperature"], "top_p": cfg["top_p"], "max_tokens": cfg["max_tokens"],
            "chat_template_kwargs": {"enable_thinking": bool(think)}}
