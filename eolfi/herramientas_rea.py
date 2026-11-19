"""Inventario E4 de solo lectura. No instala, inicia ni configura herramientas."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Callable


def _first_existing(paths: list[str | Path]) -> str | None:
    for raw in paths:
        path = Path(raw)
        if path.is_file() or path.is_dir():
            return str(path.resolve())
    return None


def _npcap_registry() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\npcap"):
            return True
    except OSError:
        return False


def _path_for_wsl(path: Path) -> str:
    """Representa una ruta Windows montada en WSL; en otros sistemas conserva su forma POSIX."""
    value = str(path.resolve())
    if len(value) >= 3 and value[1:3] in (":\\", ":/"):
        return f"/mnt/{value[0].lower()}/{value[3:].replace(chr(92), '/')}"
    return path.resolve().as_posix()


def inventory(*, sigrok_probe: Callable[[], list[str] | None] | None = None) -> dict:
    """Devuelve presencia y alternativas; nunca ejecuta los binarios objetivo."""
    raiz = Path(__file__).resolve().parents[1]
    instalador_sigrok = raiz / "tools" / "instalar-sigrok-wsl.sh"
    program_files = Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
    local_app = Path(os.environ.get("LOCALAPPDATA") or "")
    npcap_path = _first_existing([Path(os.environ.get("WINDIR") or r"C:\Windows") / "System32" / "Npcap",
                                  program_files / "Npcap"])
    wireshark_path = shutil.which("dumpcap") or _first_existing([program_files / "Wireshark" / "dumpcap.exe"])
    cutter_path = shutil.which("cutter") or _first_existing([
        program_files / "Cutter" / "Cutter.exe", program_files / "Rizin" / "Cutter.exe",
        local_app / "Programs" / "Cutter" / "Cutter.exe",
    ])
    rizin_path = shutil.which("rizin")
    if sigrok_probe is None:
        from eolfi.rea_client import wsl_rea_sigrok_command

        sigrok_probe = wsl_rea_sigrok_command
    try:
        sigrok_cmd = sigrok_probe()
    except (OSError, RuntimeError):
        sigrok_cmd = None
    npcap_disponible = bool(npcap_path or _npcap_registry())
    sigrok_disponible = bool(sigrok_cmd)
    cutter_disponible = bool(cutter_path)
    pendientes = []
    if not npcap_disponible:
        pendientes.append({"herramienta": "Npcap", "requiere": "administrador",
                           "motivo": "instala un controlador de captura de red"})
    if not sigrok_disponible:
        pendientes.append({"herramienta": "sigrok", "requiere": "WSL accesible y red para apt-get download",
                           "comando": f"bash {_path_for_wsl(instalador_sigrok)}"})
    if not cutter_disponible:
        pendientes.append({"herramienta": "Cutter", "requiere": "paquete revisado por el titular",
                           "motivo": "Rizin está disponible solo como alternativa de línea de comandos"
                           if rizin_path else "no se detectó Cutter ni Rizin"})
    return {
        "estado": "inventariado",
        "solo_lectura": True,
        "npcap": {"disponible": npcap_disponible, "ruta": npcap_path,
                  "dumpcap": str(Path(wireshark_path).resolve()) if wireshark_path else None,
                  "nota": "Instalar Npcap añade un controlador y requiere autorización explícita."},
        "sigrok": {"disponible": sigrok_disponible,
                   "entorno": "REA de WSL" if sigrok_cmd else None,
                   "instalador": str(instalador_sigrok) if instalador_sigrok.is_file() else None,
                   "nota": "No accesible desde este proceso; esto no demuestra que falte en WSL."
                   if not sigrok_cmd else "Accesible mediante el REA de WSL."},
        "cutter": {"disponible": cutter_disponible, "ruta": cutter_path,
                   "alternativa_rizin": str(Path(rizin_path).resolve()) if rizin_path else None,
                   "nota": "Rizin cubre análisis por CLI, pero no sustituye la interfaz de Cutter."},
        "pendientes": pendientes,
        "cambios": [],
    }
