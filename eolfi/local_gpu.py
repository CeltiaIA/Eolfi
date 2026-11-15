"""Un solo modelo local en la GPU a la vez.

Eolfi puede usar dos servidores de modelos locales: **Eolas** (CeltIA, API tipo Ollama en 127.0.0.1:11435, que carga
el modelo al recibir una petición y lo descarga solo tras un rato sin uso) y **Eolas V2** (`eolfi eolas-v2`,
llama-server propio con perfiles Gemma/Mistral). Con 8 GB de VRAM no caben los dos: el 11 y el 12 de noviembre de
2026 un Mistral-Nemo de Eolas V2 olvidado junto al Gemma de Eolas dio «bad allocation» y dejó el agente casi
parado. Esta guardia:

- antes de arrancar Eolas V2, mira qué tiene *cargado* Eolas (``/api/ps``, no el catálogo de ``/api/tags``) y se
  niega, salvo que se pida liberarlo (``keep_alive: 0``);
- antes de pedir algo a Eolas, si Eolas V2 tiene un modelo cargado y está ocioso, lo para; si está generando, se
  niega con un mensaje claro;
- vigila Eolas V2 y lo para tras ``IDLE_MINUTES`` sin peticiones, para que no quede olvidado.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any

EOLAS_URL = os.environ.get("CELTIAIA_EOLAS_URL", "http://127.0.0.1:11435").rstrip("/")
IDLE_MINUTES = float(os.environ.get("EOLFI_LOCAL_IDLE_MINUTES", "15"))
POLL_SECONDS = 30.0


def eolas_v1_parked() -> bool:
    """Eolas V1 (CeltIA, 11435) parado hasta que se repare (15/11/2026, decisión del titular): Eolfi no lo arranca
    ni lo usa como proveedor. ``EOLFI_EOLAS_V1=1`` lo vuelve a habilitar cuando esté reparado."""
    return os.environ.get("EOLFI_EOLAS_V1", "").strip() != "1"


class GpuBusy(RuntimeError):
    """Otro modelo local ocupa la GPU y no se puede liberar sin interrumpir trabajo."""


def _get_json(url: str, timeout: float = 2.0, headers: dict[str, str] | None = None) -> Any:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")) if r.status == 200 else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def eolas_loaded(url: str = EOLAS_URL) -> list[str]:
    """Modelos que Eolas tiene cargados en memoria ahora mismo (vacío si no responde o no hay ninguno)."""
    data = _get_json(f"{url}/api/ps") or {}
    return [str(m.get("name") or m.get("model")) for m in data.get("models", []) if isinstance(m, dict)]


def release_eolas(url: str = EOLAS_URL) -> list[str]:
    """Pide a Eolas que descargue sus modelos (``keep_alive: 0``, como Ollama). Devuelve los que descargó."""
    released = []
    for name in eolas_loaded(url):
        body = json.dumps({"model": name, "keep_alive": 0}).encode("utf-8")
        req = urllib.request.Request(f"{url}/api/generate", data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30):
                released.append(name)
        except (urllib.error.URLError, OSError):
            pass
    deadline = time.monotonic() + 15
    while eolas_loaded(url) and time.monotonic() < deadline:
        time.sleep(0.5)
    return released


def eolas_v2_holder() -> dict[str, Any] | None:
    """El llama-server de Eolas V2 si está vivo: {pid, profile, port, busy}."""
    from eolfi import eolas_v2

    try:
        record = json.loads(eolas_v2.runtime_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pid = int(record.get("pid") or 0)
    if not eolas_v2._pid_alive(pid):
        return None
    port = int(record.get("port") or 0)
    # /slots exige la clave de Eolas V2 (--api-key-file): sin ella responde 401 y el vigilante no veía ninguna
    # petición (P0-2, auditoría del 15/11/2026).
    try:
        headers = eolas_v2.auth_headers()
    except OSError:
        headers = {}
    slots = _get_json(f"http://127.0.0.1:{port}/slots", headers=headers) if port else None
    slots_ok = isinstance(slots, list)
    slots = [s for s in slots if isinstance(s, dict)] if slots_ok else []
    busy = any(s.get("is_processing") for s in slots)
    # id_task cambia con cada petición: así se ve también la actividad corta entre dos miradas del vigilante.
    tasks = tuple(s.get("id_task") for s in slots)
    return {"pid": pid, "profile": record.get("profile"), "port": port, "busy": busy, "tasks": tasks,
            "slots_ok": slots_ok, "watchdog_pid": int(record.get("idle_watchdog_pid") or 0) or None,
            "watchdog_token": record.get("idle_watchdog_token") or None}


def check_before_eolas_v2(*, release: bool = False, url: str = EOLAS_URL) -> dict[str, Any]:
    """Antes de cargar Eolas V2: la GPU no puede tener ya el modelo de Eolas."""
    loaded = eolas_loaded(url)
    if not loaded:
        return {"eolas_loaded": [], "released": []}
    if not release:
        raise GpuBusy(f"Eolas tiene cargado {', '.join(loaded)} en la GPU; no cargo Eolas V2 a la vez (8 GB no dan "
                      "para dos modelos). Espera a que Eolas lo descargue solo o repite con --liberar-eolas")
    released = release_eolas(url)
    still = eolas_loaded(url)
    if still:
        raise GpuBusy(f"Pedí a Eolas que descargara {', '.join(loaded)}, pero sigue cargado: {', '.join(still)}")
    return {"eolas_loaded": loaded, "released": released}


def free_for_eolas() -> dict[str, Any]:
    """Antes de una petición a Eolas: Eolas V2 no puede tener un modelo cargado. Si está ocioso, se para."""
    holder = eolas_v2_holder()
    if holder is None:
        return {"stopped_eolas_v2": None}
    if holder["busy"]:
        raise GpuBusy(f"Eolas V2 está generando con el perfil {holder['profile']} (PID {holder['pid']}); no pido a "
                      "Eolas que cargue otro modelo encima. Espera a que termine o páralo con «eolfi eolas-v2 stop»")
    from eolfi import eolas_v2

    eolas_v2.stop()
    return {"stopped_eolas_v2": holder}


def start_watchdog(pid: int, port: int, idle_minutes: float = IDLE_MINUTES, *,
                   popen=subprocess.Popen, token: str | None = None) -> int | None:
    """Lanza en segundo plano el vigilante que para Eolas V2 tras ``idle_minutes`` sin uso.

    ``token`` identifica al vigilante en el runtime de Eolas V2 (el PID no sirve: en Windows el python.exe de un venv
    es un lanzador con otro PID). Un vigilante cuyo token ya no figura en el runtime se retira."""
    if idle_minutes <= 0:
        return None
    flags = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
             | getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0
    # Igual que el llama-server: fuera del Job Object de quien lo lanza. Sin esto, al cerrar la sesión o la tarea
    # que arrancó Eolas V2 moría el vigilante y el servidor (que sí sale del job) quedaba huérfano (P0-3).
    breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0) if os.name == "nt" else 0
    args = [sys.executable, "-m", "eolfi.local_gpu", "watch", "--pid", str(pid), "--port", str(port),
            "--idle", str(idle_minutes)] + (["--token", token] if token else [])
    common = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
              "start_new_session": os.name != "nt"}
    try:
        proc = popen(args, creationflags=flags | breakaway, **common)
    except OSError:
        if not breakaway:      # el job no permite salir: se lanza dentro y el rearme lo repondrá si muere
            raise
        proc = popen(args, creationflags=flags, **common)
    return proc.pid


def ensure_watchdog(*, idle_minutes: float = IDLE_MINUTES, popen=None) -> int | None:
    """Rearma el vigilante si Eolas V2 está vivo y el suyo ya no existe. Devuelve el PID del vigilante activo."""
    from eolfi import eolas_v2

    record = eolas_v2._runtime()
    if not record or idle_minutes <= 0:
        return None
    pid, port = int(record.get("pid") or 0), int(record.get("port") or 0)
    if not (pid and port and eolas_v2._pid_alive(pid)):
        return None
    current = int(record.get("idle_watchdog_pid") or 0)
    if current and eolas_v2._pid_alive(current):
        return current
    import secrets

    token = secrets.token_hex(8)
    # Primero el runtime con el token nuevo: si quedara un vigilante antiguo vivo, verá otro token y se retirará.
    eolas_v2._write_json_atomic(eolas_v2.runtime_file(), {**record, "idle_watchdog_token": token,
                                                          "idle_watchdog_pid": None})
    new = start_watchdog(pid, port, idle_minutes, popen=popen or subprocess.Popen, token=token)
    eolas_v2._write_json_atomic(eolas_v2.runtime_file(), {**record, "idle_watchdog_token": token,
                                                          "idle_watchdog_pid": new})
    return new


def watch(pid: int, port: int, idle_minutes: float, *, poll: float = POLL_SECONDS,
          clock=time.monotonic, sleep=time.sleep, token: str | None = None) -> str:
    """Bucle del vigilante. Termina cuando el servidor muere o cuando lo para por inactividad."""
    from eolfi import eolas_v2

    last = clock()
    seen = None
    while True:
        holder = eolas_v2_holder()
        if holder is None or holder["pid"] != pid:
            return "servidor terminado"
        if token and holder["watchdog_token"] not in (None, token):
            return "otro vigilante activo"       # un rearme no deja dos vigilantes sobre el mismo servidor
        if holder["busy"] or (seen is not None and holder["tasks"] != seen):
            last = clock()
        elif clock() - last >= idle_minutes * 60:
            eolas_v2.stop()
            return f"parado tras {idle_minutes:g} min sin uso"
        seen = holder["tasks"]
        sleep(poll)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eolfi.local_gpu")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("watch")
    w.add_argument("--pid", type=int, required=True)
    w.add_argument("--port", type=int, required=True)
    w.add_argument("--idle", type=float, default=IDLE_MINUTES)
    w.add_argument("--token")
    sub.add_parser("status")
    args = ap.parse_args(argv)
    if args.cmd == "watch":
        watch(args.pid, args.port, args.idle, token=args.token)
    else:
        if not sys.stdout.isatty() and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")   # redirigido en Windows: UTF-8, no cp1252 (15/11/2026)
        print(json.dumps({"eolas_loaded": eolas_loaded(), "eolas_v2": eolas_v2_holder()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
