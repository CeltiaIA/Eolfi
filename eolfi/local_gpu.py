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


class GpuBusy(RuntimeError):
    """Otro modelo local ocupa la GPU y no se puede liberar sin interrumpir trabajo."""


def _get_json(url: str, timeout: float = 2.0) -> Any:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
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
    slots = _get_json(f"http://127.0.0.1:{port}/slots") if port else None
    slots = [s for s in slots if isinstance(s, dict)] if isinstance(slots, list) else []
    busy = any(s.get("is_processing") for s in slots)
    # id_task cambia con cada petición: así se ve también la actividad corta entre dos miradas del vigilante.
    tasks = tuple(s.get("id_task") for s in slots)
    return {"pid": pid, "profile": record.get("profile"), "port": port, "busy": busy, "tasks": tasks}


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


def start_watchdog(pid: int, port: int, idle_minutes: float = IDLE_MINUTES) -> int | None:
    """Lanza en segundo plano el vigilante que para Eolas V2 tras ``idle_minutes`` sin uso."""
    if idle_minutes <= 0:
        return None
    flags = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
             | getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0
    proc = subprocess.Popen([sys.executable, "-m", "eolfi.local_gpu", "watch", "--pid", str(pid), "--port", str(port),
                             "--idle", str(idle_minutes)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=flags, start_new_session=os.name != "nt")
    return proc.pid


def watch(pid: int, port: int, idle_minutes: float, *, poll: float = POLL_SECONDS,
          clock=time.monotonic, sleep=time.sleep) -> str:
    """Bucle del vigilante. Termina cuando el servidor muere o cuando lo para por inactividad."""
    from eolfi import eolas_v2

    last = clock()
    seen = None
    while True:
        holder = eolas_v2_holder()
        if holder is None or holder["pid"] != pid:
            return "servidor terminado"
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
    sub.add_parser("status")
    args = ap.parse_args(argv)
    if args.cmd == "watch":
        watch(args.pid, args.port, args.idle)
    else:
        print(json.dumps({"eolas_loaded": eolas_loaded(), "eolas_v2": eolas_v2_holder()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
