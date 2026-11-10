"""Motor local Eolas: perfiles GGUF alternos y aprendizaje supervisado por feedback.

Los perfiles nunca comparten un proceso llama-server. El feedback solo se guarda con
consentimiento explícito; este módulo prepara datasets, pero no modifica pesos base.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

SCHEMA = "eolas-feedback/v1"
DATASET_SCHEMA = "eolas-training-dataset/v1"
DEFAULT_PROFILES: dict[str, dict[str, Any]] = {
    "gemma": {
        "alias": "gemma-4-12b-it-q5_k_m:latest",
        "model": r"D:\AI\Hydra\gguf\gemma-4-12b-it-Q5_K_M.gguf",
        "ctx": 32000,
        "gpu_layers": 8,
        "batch": 128,
        "ubatch": 64,
    },
    "mistral": {
        "alias": "mistral-7b-instruct-v0.3-q4_k_m:latest",
        "model": r"D:\AI\Hydra\gguf\Mistral-7B-Instruct-v0.3-Q4_K_M.gguf",
        "ctx": 32000,
        "gpu_layers": 8,
        "batch": 128,
        "ubatch": 64,
    },
    "moe": {
        "alias": "moe-local",
        "model": "",
        "ctx": 8192,
        "gpu_layers": 0,
        "batch": 128,
        "ubatch": 64,
    },
}
DEFAULT_CONFIG: dict[str, Any] = {
    "server": "",
    "port": 8090,
    "active_profile": "gemma",
    "profiles": DEFAULT_PROFILES,
    "ready_timeout": 300,
    "threads": 0,
    "temperature": 0.2,
    "top_p": 0.95,
    "max_tokens": 4096,
    "reasoning": True,
    "review_reasoning": False,
    "show_reasoning": True,
    "system": "",
    "extra_args": [],
    "feedback_enabled": False,
}
REDACT = re.compile(r"(?i)(api[_-]?key|token|password|secret)(\s*[:=]\s*)([^\s,;]+)")


def config_file() -> Path:
    return Path(os.environ.get("EOLFI_EOLAS_V2_CONFIG") or Path.home() / ".eolfi" / "eolas-v2.json")


def feedback_file() -> Path:
    return Path(os.environ.get("EOLFI_EOLAS_V2_FEEDBACK") or Path.home() / ".eolfi" / "eolas-v2" / "feedback.jsonl")


def runtime_file() -> Path:
    return config_file().with_suffix(".runtime.json")


def lock_file() -> Path:
    return config_file().with_suffix(".lock")


def _server_default() -> str:
    from eolfi.llamacpp import _find_server

    return _find_server()


def load_config(*, create: bool = True) -> dict[str, Any]:
    path = config_file()
    if path.is_file():
        try:
            user = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"Configuración Eolas inválida: {path}: {exc}") from exc
        if not isinstance(user, dict):
            raise ValueError(f"La configuración Eolas debe ser un objeto JSON: {path}")
    else:
        user = {}
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_json_atomic(path, DEFAULT_CONFIG)
    cfg = {**DEFAULT_CONFIG, **{k: v for k, v in user.items() if k in DEFAULT_CONFIG}}
    cfg["profiles"] = {name: {**DEFAULT_PROFILES[name], **dict((user.get("profiles") or {}).get(name) or {})}
                       for name in DEFAULT_PROFILES}
    cfg["server"] = str(cfg.get("server") or _server_default())
    cfg["port"] = int(cfg.get("port") or 8090)
    cfg["ready_timeout"] = max(1, int(cfg.get("ready_timeout") or 300))
    cfg["threads"] = max(0, int(cfg.get("threads") or 0))
    if cfg["active_profile"] not in DEFAULT_PROFILES:
        raise ValueError("active_profile debe ser 'gemma', 'mistral' o 'moe'")
    for name, env in (("gemma", "EOLFI_EOLAS_V2_GEMMA_GGUF"), ("mistral", "EOLFI_EOLAS_V2_MISTRAL_GGUF"),
                      ("moe", "EOLFI_EOLAS_V2_MOE_GGUF")):
        if os.environ.get(env):
            cfg["profiles"][name]["model"] = os.environ[env]
    return cfg


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def profile_config(name: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    if name not in DEFAULT_PROFILES:
        raise ValueError("perfil desconocido; usa 'gemma', 'mistral' o 'moe'")
    cfg = cfg or load_config()
    profile = cfg["profiles"][name]
    from eolfi import llamacpp

    result = {**cfg, **profile, "server": cfg["server"], "port": cfg["port"]}
    result.setdefault("alias", Path(str(result["model"])).stem)
    result["url"] = llamacpp.base_url(result)
    return result


def server_args(name: str, cfg: dict[str, Any] | None = None) -> list[str]:
    cfg = cfg or load_config()
    c = profile_config(name, cfg)
    if not c["server"] or not (Path(c["server"]).is_file() or shutil.which(c["server"])):
        raise FileNotFoundError("No encuentro llama-server.exe (PATH o campo server de la configuración Eolas)")
    if not Path(c["model"]).is_file():
        raise FileNotFoundError(f"No encuentro el GGUF del perfil {name}: {c['model']}")
    args = [c["server"], "-m", str(c["model"]), "--host", "127.0.0.1", "--port", str(c["port"]),
            "-c", str(c["ctx"]), "-ngl", str(c["gpu_layers"]), "-b", str(c["batch"]),
            "-ub", str(c["ubatch"]), "--alias", str(c["alias"]), "--jinja", "--reasoning-format", "deepseek"]
    if c["threads"] > 0:
        args += ["--threads", str(c["threads"]), "--threads-batch", str(c["threads"])]
    args.extend(str(x) for x in cfg.get("extra_args") or [])
    args.extend(str(x) for x in cfg["profiles"][name].get("extra_args") or [])
    return args


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) can be ambiguous on Windows around process exit/PID reuse.
        # Query the OS process handle so switch() doesn't wait on an already-dead server.
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        open_process.restype = wintypes.HANDLE
        handle = open_process(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            error = ctypes.get_last_error()
            return error == 5  # Access denied: conservatively treat as alive.
        try:
            exit_code = wintypes.DWORD()
            get_exit_code = kernel32.GetExitCodeProcess
            get_exit_code.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
            get_exit_code.restype = wintypes.BOOL
            if not get_exit_code(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == 259  # STILL_ACTIVE
        finally:
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = (wintypes.HANDLE,)
            close_handle.restype = wintypes.BOOL
            close_handle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


@contextmanager
def _exclusive_lock() -> Iterator[None]:
    path = lock_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            stale = not _pid_alive(int(record.get("pid", -1)))
        except (OSError, ValueError, TypeError):
            stale = False
        if not stale:
            raise RuntimeError("Eolas ya está cambiando de perfil; espera a que termine")
        path.unlink(missing_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, json.dumps({"pid": os.getpid()}).encode("utf-8"))
        yield
    finally:
        os.close(fd)
        path.unlink(missing_ok=True)


def _read_json(url: str, timeout: float = 2.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")) if response.status == 200 else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _healthy(c: dict[str, Any], expected_alias: str | None = None) -> bool:
    if _read_json(f"{c['url']}/health") is None:
        return False
    if not expected_alias:
        return True
    models = _read_json(f"{c['url']}/v1/models") or {}
    return any(str(row.get("id", "")) == expected_alias for row in models.get("data", []) if isinstance(row, dict))


def _legacy_eolas_models() -> list[str]:
    """Modelos anunciados por Eolas V1/CeltIA, que también puede ocupar la GPU."""
    tags = _read_json("http://127.0.0.1:11435/api/tags") or {}
    return [str(item.get("name") or item.get("model")) for item in tags.get("models", []) if isinstance(item, dict)]


def _runtime() -> dict[str, Any] | None:
    try:
        value = json.loads(runtime_file().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _stop_locked(*, wait: float = 30.0) -> bool:
    record = _runtime()
    if not record:
        return False
    pid = int(record.get("pid") or 0)
    port = int(record.get("port") or load_config(create=False)["port"])
    if pid and _pid_alive(pid):
        if os.name == "nt":
            result = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=wait)
            if result.returncode and _pid_alive(pid):
                raise RuntimeError(f"No pude detener el llama-server de Eolas (PID {pid})")
        else:
            os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + wait
        while _pid_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        if _pid_alive(pid):
            raise TimeoutError(f"El llama-server de Eolas (PID {pid}) no terminó")
    deadline = time.monotonic() + wait
    health_url = f"http://127.0.0.1:{port}/health"
    while _read_json(health_url, timeout=0.2) is not None and time.monotonic() < deadline:
        time.sleep(0.1)
    if _read_json(health_url, timeout=0.2) is not None:
        raise RuntimeError(f"El servidor sigue respondiendo en 127.0.0.1:{port}; no cambio de modelo")
    runtime_file().unlink(missing_ok=True)
    return True


def stop() -> dict[str, Any]:
    with _exclusive_lock():
        stopped = _stop_locked()
    return {"stopped": stopped, "runtime": str(runtime_file())}


def _start_locked(name: str, cfg: dict[str, Any] | None = None, *, popen: Callable[..., Any] = subprocess.Popen,
                  wait: float | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    c = profile_config(name, cfg)
    record = _runtime()
    if record and _pid_alive(int(record.get("pid") or 0)):
        if record.get("profile") == name and _healthy(c, str(c["alias"])):
            return {"running": True, "started": False, "profile": name, "url": c["url"], "pid": record["pid"]}
        raise RuntimeError(f"Eolas ya tiene activo el perfil {record.get('profile')}; cambia de perfil con switch")
    runtime_file().unlink(missing_ok=True)
    legacy_models = _legacy_eolas_models()
    if legacy_models:
        raise RuntimeError("Eolas V1/CeltIA sigue anunciando modelos en 127.0.0.1:11435 (" + ", ".join(legacy_models)
                           + "); detén su servicio antes de cargar Eolas V2 para no ocupar la GPU con ambos")
    if _healthy(c):
        raise RuntimeError(f"El puerto {c['port']} ya tiene un servidor que Eolas no inició; no lo detengo")
    log_path = config_file().with_suffix(".log")
    flags = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
             | getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0
    args = server_args(name, cfg)
    with log_path.open("ab") as log:
        common = {"stdout": log, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL,
                  "start_new_session": os.name != "nt"}
        breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0) if os.name == "nt" else 0
        try:
            proc = popen(args, creationflags=flags | breakaway, **common)
        except OSError:
            if not breakaway:
                raise
            proc = popen(args, creationflags=flags, **common)
    runtime = {"pid": proc.pid, "profile": name, "model": c["model"], "alias": c["alias"], "port": c["port"],
               "started_at": datetime.now(timezone.utc).isoformat()}
    timeout = float(wait if wait is not None else cfg["ready_timeout"])
    deadline = time.monotonic() + timeout
    try:
        _write_json_atomic(runtime_file(), runtime)
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"llama-server se cerró al iniciar Eolas (código {proc.returncode}; mira {log_path})")
            if _healthy(c, str(c["alias"])):
                return {"running": True, "started": True, "profile": name, "url": c["url"], "pid": proc.pid}
            time.sleep(0.5)
        raise TimeoutError(f"Eolas no publicó health y el modelo {c['alias']} en {timeout:g} s")
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=10)
        except Exception:
            pass
        runtime_file().unlink(missing_ok=True)
        raise


def start(profile: str | None = None, *, wait: float | None = None) -> dict[str, Any]:
    cfg = load_config()
    name = profile or str(cfg["active_profile"])
    with _exclusive_lock():
        return _start_locked(name, cfg, wait=wait)


def switch(profile: str, *, wait: float | None = None) -> dict[str, Any]:
    if profile not in DEFAULT_PROFILES:
        raise ValueError("perfil desconocido; usa 'gemma', 'mistral' o 'moe'")
    with _exclusive_lock():
        cfg = load_config()
        server_args(profile, cfg)
        config_path = config_file()
        stored = json.loads(config_path.read_text(encoding="utf-8-sig"))
        stopped = _stop_locked()
        started = _start_locked(profile, cfg, wait=wait)
        stored["active_profile"] = profile
        try:
            _write_json_atomic(config_path, stored)
        except OSError:
            if started["started"]:
                _stop_locked()
            raise
    return {**started, "stopped_previous": stopped}


@contextmanager
def inference_profile(name: str) -> Iterator[dict[str, Any]]:
    """Keep the selected model loaded until the caller finishes inference."""
    with _exclusive_lock():
        cfg = load_config()
        c = profile_config(name, cfg)
        record = _runtime()
        if record and record.get("profile") != name:
            server_args(name, cfg)
            _stop_locked()
        _start_locked(name, cfg)
        yield c


def status() -> dict[str, Any]:
    cfg = load_config(create=False)
    record = _runtime()
    live = bool(record and _pid_alive(int(record.get("pid") or 0)))
    selected = str(record.get("profile")) if live else str(cfg["active_profile"])
    c = profile_config(selected, cfg)
    healthy = _healthy(c, str(c["alias"])) if live else False
    return {"config": str(config_file()), "active_profile": cfg["active_profile"], "running_profile": selected if live else None,
            "model": c["model"], "alias": c["alias"], "url": c["url"], "pid": record.get("pid") if live else None,
            "running": bool(live and healthy), "model_verified": healthy,
            "feedback_enabled": bool(cfg["feedback_enabled"]), "feedback_file": str(feedback_file())}


def _clean_text(value: str, max_chars: int = 200_000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("El texto no puede estar vacío")
    if len(value) > max_chars:
        raise ValueError(f"El texto supera el límite de {max_chars} caracteres")
    return REDACT.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", value.strip())


def _clean_parameters(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "[MAX_DEPTH]"
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            name = str(key)
            cleaned[name] = "[REDACTED]" if re.search(r"(?i)(api[_-]?key|token|password|secret|credential)", name) else _clean_parameters(item, depth + 1)
        return cleaned
    if isinstance(value, list):
        return [_clean_parameters(item, depth + 1) for item in value[:1000]]
    if isinstance(value, str):
        return _clean_text(value, 20_000)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:2_000]


def record_feedback(*, profile: str, task: str, prompt: str, response: str, rating: int, consent: bool,
                    parameters: dict[str, Any] | None = None, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    if not consent:
        raise PermissionError("El feedback requiere consentimiento explícito")
    if profile not in DEFAULT_PROFILES:
        raise ValueError("perfil desconocido; usa 'gemma', 'mistral' o 'moe'")
    if not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 5:
        raise ValueError("rating debe ser un entero entre 1 y 5")
    cfg = cfg or load_config(create=False)
    if not cfg.get("feedback_enabled"):
        raise PermissionError("Activa primero el almacenamiento local con 'eolfi eolas-v2 feedback-consent on'")
    c = profile_config(profile, cfg)
    rec = {"schema": SCHEMA, "id": uuid.uuid4().hex, "created_at": datetime.now(timezone.utc).isoformat(),
           "task": _clean_text(task, 300), "prompt": _clean_text(prompt), "response": _clean_text(response),
           "rating": rating, "profile": profile, "model": Path(str(c["model"])).name,
           "base_model_sha256": c.get("sha256"), "parameters": _clean_parameters(parameters or {}), "consent": True}
    path = feedback_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return rec


def read_feedback(path: Path | None = None) -> list[dict[str, Any]]:
    source = path or feedback_file()
    if not source.exists():
        return []
    result: list[dict[str, Any]] = []
    for line_no, line in enumerate(source.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"JSONL inválido, línea {line_no}: {exc}") from exc
        if isinstance(item, dict) and item.get("schema") == SCHEMA and item.get("consent") is True:
            result.append(item)
    return result


def delete_feedback(record_id: str, path: Path | None = None) -> bool:
    source = path or feedback_file()
    rows = read_feedback(source)
    kept = [row for row in rows if row.get("id") != record_id]
    if len(kept) == len(rows):
        return False
    temp = source.with_name(source.name + f".{os.getpid()}.tmp")
    temp.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in kept), encoding="utf-8")
    os.replace(temp, source)
    return True


def export_feedback(out: Path) -> dict[str, Any]:
    rows = read_feedback()
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    target.write_text(content, encoding="utf-8")
    return {"path": str(target), "records": len(rows), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}


def import_feedback(source: Path) -> dict[str, Any]:
    cfg = load_config(create=False)
    if not cfg.get("feedback_enabled"):
        raise PermissionError("Activa el almacenamiento local antes de importar feedback con 'eolfi eolas-v2 feedback-consent on'")
    incoming = read_feedback(Path(source))
    current = read_feedback()
    known = {str(row["id"]) for row in current}
    added = 0
    path = feedback_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for row in incoming:
            if str(row.get("id", "")) in known:
                continue
            cleaned = {**row, "task": _clean_text(str(row.get("task", "")), 300),
                       "prompt": _clean_text(str(row.get("prompt", ""))),
                       "response": _clean_text(str(row.get("response", ""))),
                       "parameters": _clean_parameters(row.get("parameters") or {})}
            if cleaned.get("profile") not in DEFAULT_PROFILES or not isinstance(cleaned.get("rating"), int) or not 1 <= cleaned["rating"] <= 5:
                continue
            stream.write(json.dumps(cleaned, ensure_ascii=False, sort_keys=True) + "\n")
            known.add(str(cleaned["id"]))
            added += 1
    return {"imported": added, "skipped_or_duplicate": len(incoming) - added, "path": str(path)}


def _case_key(row: dict[str, Any]) -> str:
    normalized = " ".join(str(row.get("prompt", "")).casefold().split())
    return hashlib.sha256((str(row.get("task", "")).casefold() + "\0" + normalized).encode("utf-8")).hexdigest()


def _split(key: str) -> str:
    bucket = int(key[:8], 16) % 10
    return "train" if bucket < 8 else "validation" if bucket == 8 else "test"


def build_dataset(*, kind: str, out: Path, min_examples: int = 20, feedback: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if kind not in {"sft", "preference"}:
        raise ValueError("kind debe ser 'sft' o 'preference'")
    if min_examples < 1:
        raise ValueError("min_examples debe ser mayor que cero")
    rows = feedback if feedback is not None else read_feedback()
    cases: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("consent") is True and row.get("schema") == SCHEMA:
            cases.setdefault(_case_key(row), []).append(row)
    examples: list[dict[str, Any]] = []
    for key, group in cases.items():
        if kind == "sft":
            winners = sorted((r for r in group if int(r.get("rating", 0)) >= 4), key=lambda r: (-int(r["rating"]), str(r.get("id", ""))))
            if winners:
                row = winners[0]
                examples.append({"prompt": row["prompt"], "completion": row["response"], "source_id": row["id"], "split": _split(key)})
        else:
            winners = sorted((r for r in group if int(r.get("rating", 0)) >= 4), key=lambda r: (-int(r["rating"]), str(r.get("id", ""))))
            losers = sorted((r for r in group if int(r.get("rating", 0)) <= 2), key=lambda r: (int(r["rating"]), str(r.get("id", ""))))
            if winners and losers:
                examples.append({"prompt": winners[0]["prompt"], "chosen": winners[0]["response"], "rejected": losers[0]["response"],
                                 "chosen_id": winners[0]["id"], "rejected_id": losers[0]["id"], "split": _split(key)})
    if len(examples) < min_examples:
        raise ValueError(f"Dataset insuficiente: {len(examples)} ejemplos; mínimo {min_examples}")
    split_counts = {name: sum(1 for row in examples if row["split"] == name) for name in ("train", "validation", "test")}
    if not split_counts["train"] or not split_counts["validation"] or not split_counts["test"]:
        raise ValueError("Dataset insuficiente para separar train/validation/test por caso; añade más casos etiquetados")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_name(out.name + f".{os.getpid()}.tmp")
    temp.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in examples), encoding="utf-8")
    os.replace(temp, out)
    manifest = {"schema": DATASET_SCHEMA, "kind": kind, "examples": len(examples), "cases": len(cases),
                "split_counts": split_counts, "source": str(feedback_file()), "dataset_sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
                "training": "NO VERIFICADO: faltan comprobar checkpoint, runtime PEFT/QLoRA y VRAM"}
    _write_json_atomic(out.with_suffix(out.suffix + ".manifest.json"), manifest)
    return manifest


def recommend_profile(task: str, *, feedback: list[dict[str, Any]] | None = None, min_ratings: int = 3) -> dict[str, Any]:
    rows = feedback if feedback is not None else read_feedback()
    scores: dict[str, list[int]] = {name: [] for name in DEFAULT_PROFILES}
    normalized_task = " ".join(task.casefold().split())
    for row in rows:
        if row.get("consent") is True and " ".join(str(row.get("task", "")).casefold().split()) == normalized_task:
            if row.get("profile") in scores and isinstance(row.get("rating"), int):
                scores[row["profile"]].append(row["rating"])
    means = {name: (sum(values) / len(values) if values else None) for name, values in scores.items()}
    eligible = [name for name, values in scores.items() if len(values) >= min_ratings]
    chosen = max(eligible, key=lambda name: (means[name], len(scores[name]), name)) if eligible else "gemma"
    return {"profile": chosen, "task": task, "mean_rating": means, "rating_count": {n: len(v) for n, v in scores.items()},
            "calibrated": bool(eligible), "weights_updated": False}


def set_feedback_consent(enabled: bool) -> dict[str, Any]:
    cfg = load_config()
    path = config_file()
    stored = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    stored["feedback_enabled"] = bool(enabled)
    _write_json_atomic(path, stored or cfg)
    return {"feedback_enabled": bool(enabled), "config": str(path), "feedback_file": str(feedback_file())}


def training_readiness(base_checkpoint: Path, dataset: Path) -> dict[str, Any]:
    base = Path(base_checkpoint)
    is_hf_checkpoint = base.is_dir() and (base / "config.json").is_file() and any(
        (base / name).exists() for name in ("model.safetensors", "pytorch_model.bin", "model.safetensors.index.json", "pytorch_model.bin.index.json"))
    dataset_path = Path(dataset)
    dataset_ready = False
    dataset_error = "dataset etiquetado con manifest no encontrado"
    manifest_path = dataset_path.with_suffix(dataset_path.suffix + ".manifest.json")
    if dataset_path.is_file() and manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload = dataset_path.read_bytes()
            examples = [json.loads(line) for line in payload.decode("utf-8-sig").splitlines() if line.strip()]
            valid_kind = manifest.get("kind") in {"sft", "preference"}
            splits = {name: sum(row.get("split") == name for row in examples) for name in ("train", "validation", "test")}
            dataset_ready = (manifest.get("schema") == DATASET_SCHEMA and valid_kind
                             and manifest.get("dataset_sha256") == hashlib.sha256(payload).hexdigest()
                             and manifest.get("examples") == len(examples)
                             and all(splits.values())
                             and all(row.get("split") in splits for row in examples)
                             and (manifest["kind"] != "sft" or all(
                                 isinstance(row.get("prompt"), str) and row["prompt"].strip()
                                 and isinstance(row.get("completion"), str) and row["completion"].strip()
                                 for row in examples)))
            if not dataset_ready:
                dataset_error = "manifest, hash, esquema o contenido del dataset no coincide"
        except (OSError, ValueError, UnicodeError, AttributeError):
            dataset_error = "no se pudo validar manifest/contenido del dataset"
    modules = {name: __import__("importlib.util", fromlist=["find_spec"]).find_spec(name) is not None
               for name in ("torch", "transformers", "peft", "bitsandbytes")}
    blockers = []
    if not is_hf_checkpoint:
        blockers.append("checkpoint HF compatible no encontrado (GGUF no basta para PEFT estándar)")
    if not dataset_ready:
        blockers.append(dataset_error)
    elif manifest.get("kind") != "sft":
        blockers.append("el entrenamiento SFT solo acepta datasets kind=sft; DPO aún no está implementado")
    elif len(examples) < 20:
        blockers.append("dataset SFT demasiado pequeño: se requieren al menos 20 ejemplos")
    elif not any(json.loads(line).get("split") == "train" for line in dataset_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()):
        blockers.append("dataset sin ejemplos train")
    elif not any(json.loads(line).get("split") == "validation" for line in dataset_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()):
        blockers.append("dataset sin ejemplos validation")
    if not all(modules.values()):
        blockers.append("faltan dependencias opcionales: " + ", ".join(k for k, v in modules.items() if not v))
    return {"ready": not blockers, "status": "ready" if not blockers else "NO VERIFICADO", "checkpoint": str(base),
            "dataset": str(dataset_path), "modules": modules, "blockers": blockers,
            "note": "La VRAM se comprobará en el arranque del entrenamiento; aún no se ha entrenado ningún modelo."}


def _checkpoint_fingerprint(checkpoint: Path) -> tuple[str, int]:
    """Hash every regular checkpoint file by path and content for adapter provenance."""
    digest = hashlib.sha256()
    files = sorted(path for path in checkpoint.rglob("*") if path.is_file())
    if not files:
        raise ValueError("checkpoint vacío")
    for path in files:
        relative = path.relative_to(checkpoint).as_posix().encode("utf-8")
        content_hash = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                content_hash.update(chunk)
        digest.update(relative + b"\0" + content_hash.hexdigest().encode("ascii") + b"\n")
    return digest.hexdigest(), len(files)


def train_sft(base_checkpoint: Path, dataset: Path, output: Path, *, consent: bool = False,
              epochs: float = 1.0, max_seq_length: int = 1024) -> dict[str, Any]:
    """Train an isolated 4-bit QLoRA SFT adapter from local assets only."""
    if not consent:
        raise PermissionError("El entrenamiento requiere --consent: usará GPU y escribirá un adaptador nuevo")
    if epochs <= 0 or max_seq_length < 128:
        raise ValueError("epochs debe ser >0 y max_seq_length >=128")
    checkpoint, data, out = Path(base_checkpoint), Path(dataset), Path(output)
    if out.exists():
        raise FileExistsError(f"la ruta de salida ya existe y no se sobrescribirá: {out}")
    report = training_readiness(checkpoint, data)
    if not report["ready"]:
        raise RuntimeError("Prerrequisitos de entrenamiento no satisfechos: " + "; ".join(report["blockers"]))
    checkpoint_sha256, checkpoint_files = _checkpoint_fingerprint(checkpoint)
    # Stop only our own inference server and refuse to train alongside the legacy model.
    stop()
    if _legacy_eolas_models():
        raise RuntimeError("Eolas V1/CeltIA anuncia modelos; detén ese servidor antes de usar la GPU para entrenar")

    try:
        import torch
        from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig,
                                  DataCollatorForSeq2Seq, Trainer, TrainingArguments)
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    except ImportError as exc:
        raise RuntimeError(f"dependencia de entrenamiento ausente: {exc}") from exc
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA no disponible; no se inició el entrenamiento")
    free_bytes, total_bytes = torch.cuda.mem_get_info()
    if free_bytes < 5 * 1024**3:
        raise RuntimeError(f"VRAM libre insuficiente para iniciar QLoRA conservador: {free_bytes // 1024**2} MiB")

    rows = [json.loads(line) for line in data.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    tokenizer = AutoTokenizer.from_pretrained(str(checkpoint), local_files_only=True, use_fast=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    class EncodedSFT(torch.utils.data.Dataset):
        def __init__(self, selected):
            self.items = []
            for row in selected:
                prompt, completion = str(row["prompt"]), str(row["completion"])
                if getattr(tokenizer, "chat_template", None):
                    prompt_ids = tokenizer.apply_chat_template([{"role": "user", "content": prompt}],
                                                               tokenize=True, add_generation_prompt=True)
                    full_ids = tokenizer.apply_chat_template([{"role": "user", "content": prompt},
                                                              {"role": "assistant", "content": completion}],
                                                             tokenize=True, add_generation_prompt=False)
                else:
                    prefix = prompt.rstrip() + "\n"
                    prompt_ids = tokenizer(prefix, add_special_tokens=True, truncation=True,
                                           max_length=max_seq_length)["input_ids"]
                    full_ids = tokenizer(prefix + completion, add_special_tokens=True, truncation=True,
                                         max_length=max_seq_length)["input_ids"]
                if isinstance(prompt_ids, dict):
                    prompt_ids = prompt_ids["input_ids"]
                if isinstance(full_ids, dict):
                    full_ids = full_ids["input_ids"]
                if not full_ids or len(full_ids) > max_seq_length:
                    full_ids = list(full_ids[:max_seq_length])
                if list(full_ids[:len(prompt_ids)]) != list(prompt_ids):
                    raise ValueError("el tokenizer no conserva el prefijo prompt; dataset rechazado para evitar entrenar sobre prompt")
                labels = [-100] * len(prompt_ids) + list(full_ids[len(prompt_ids):])
                if not any(token != -100 for token in labels):
                    raise ValueError("ejemplo vacío tras tokenizar; dataset rechazado")
                self.items.append({"input_ids": list(full_ids), "attention_mask": [1] * len(full_ids), "labels": labels})
        def __len__(self): return len(self.items)
        def __getitem__(self, index): return self.items[index]

    train_rows = [row for row in rows if row["split"] == "train"]
    eval_rows = [row for row in rows if row["split"] == "validation"]
    train_set, eval_set = EncodedSFT(train_rows), EncodedSFT(eval_rows)
    quantization = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                      bnb_4bit_compute_dtype=torch.float16, bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(str(checkpoint), local_files_only=True,
             quantization_config=quantization, device_map="auto", torch_dtype=torch.float16)
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(model, LoraConfig(r=8, lora_alpha=16, lora_dropout=0.05,
                              target_modules="all-linear", bias="none", task_type="CAUSAL_LM"))
    out.mkdir(parents=True, exist_ok=False)
    try:
        import inspect
        args = dict(output_dir=str(out), num_train_epochs=epochs, per_device_train_batch_size=1,
                    per_device_eval_batch_size=1, gradient_accumulation_steps=4, learning_rate=2e-4,
                    logging_steps=10, save_strategy="epoch", fp16=True, gradient_checkpointing=True,
                    optim="paged_adamw_8bit", report_to="none", remove_unused_columns=False,
                    load_best_model_at_end=False, save_only_model=True)
        parameters = inspect.signature(TrainingArguments.__init__).parameters
        args["eval_strategy" if "eval_strategy" in parameters else "evaluation_strategy"] = "epoch"
        trainer = Trainer(model=model, args=TrainingArguments(**args), train_dataset=train_set,
                          eval_dataset=eval_set, data_collator=DataCollatorForSeq2Seq(tokenizer, pad_to_multiple_of=8))
        result = trainer.train()
        trainer.save_model(str(out))
        tokenizer.save_pretrained(out)
        _write_json_atomic(out / "eolas-v2-training.json", {
            "format": "peft-qlora-sft", "base_checkpoint": str(checkpoint.resolve()),
            "base_checkpoint_sha256": checkpoint_sha256, "base_checkpoint_files": checkpoint_files,
            "dataset": str(data.resolve()), "dataset_sha256": hashlib.sha256(data.read_bytes()).hexdigest(),
            "epochs": epochs, "max_seq_length": max_seq_length, "train_examples": len(train_set),
            "validation_examples": len(eval_set), "metrics": getattr(result, "metrics", {}),
            "status": "EXPERIMENTO: requiere evaluación independiente antes de uso"})
        return {"status": "adapter_saved_experiment_requires_evaluation", "output": str(out),
                "train_examples": len(train_set), "validation_examples": len(eval_set)}
    except Exception:
        # Preserve partial evidence for diagnosis; never silently delete training outputs.
        raise

