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


def _cutter_portable(local_app: Path) -> str | None:
    """Cutter portátil extraído por Eolfi en ``%LOCALAPPDATA%\\Eolfi-Cutter-*\\*\\cutter.exe`` (el más reciente)."""
    if not str(local_app) or not local_app.is_dir():
        return None
    candidatos = [p for p in local_app.glob("Eolfi-Cutter-*/*/cutter.exe") if p.is_file()]
    if not candidatos:
        return None
    return str(max(candidatos, key=lambda p: p.stat().st_mtime).resolve())


def _rizin_incluido(cutter_path: str | None) -> dict | None:
    """Rizin que trae el propio paquete de Cutter. En Windows sus DLL ``rz_*`` se cargan antes que las de otra
    instalación porque el cargador busca primero en la carpeta del ejecutable."""
    if not cutter_path:
        return None
    carpeta = Path(cutter_path).parent
    dlls = sorted(p.name for p in carpeta.glob("rz_core-*.dll"))
    rizin = carpeta / ("rizin.exe" if sys.platform == "win32" else "rizin")
    if not dlls and not rizin.is_file():
        return None
    return {"carpeta": str(carpeta), "rz_core": dlls[0] if dlls else None,
            "rizin": str(rizin) if rizin.is_file() else None,
            "nota": "Cutter usa este Rizin incluido; la instalación externa de Rizin no interviene en Cutter."}


def inventory(*, sigrok_probe: Callable[[], list[str] | None] | None = None) -> dict:
    """Devuelve presencia y alternativas; nunca ejecuta los binarios objetivo."""
    raiz = Path(__file__).resolve().parents[1]
    instalador_sigrok = raiz / "tools" / "instalar-sigrok-wsl.sh"
    program_files = Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
    local_app = Path(os.environ.get("LOCALAPPDATA") or "")
    npcap_path = _first_existing([Path(os.environ.get("WINDIR") or r"C:\Windows") / "System32" / "Npcap",
                                  program_files / "Npcap"])
    wireshark_path = shutil.which("dumpcap") or _first_existing([program_files / "Wireshark" / "dumpcap.exe"])
    cutter_env = os.environ.get("EOLFI_CUTTER")
    cutter_path = (str(Path(cutter_env).resolve()) if cutter_env and Path(cutter_env).is_file() else None) \
        or shutil.which("cutter") or _first_existing([
            program_files / "Cutter" / "Cutter.exe", program_files / "Rizin" / "Cutter.exe",
            local_app / "Programs" / "Cutter" / "Cutter.exe",
        ]) or _cutter_portable(local_app)
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
                   "variable_ruta": "EOLFI_CUTTER",
                   "rizin_incluido": _rizin_incluido(cutter_path),
                   "alternativa_rizin": str(Path(rizin_path).resolve()) if rizin_path else None,
                   "nota": "Rizin cubre análisis por CLI, pero no sustituye la interfaz de Cutter."},
        "pendientes": pendientes,
        "cambios": [],
    }
