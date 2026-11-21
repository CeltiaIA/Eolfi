"""Acceso directo al panel de Eolfi (C2 del plan).

``eolfi acceso-directo`` crea un lanzador que ejecuta ``eolfi up`` (Eolas, el puente de chats web y el panel, que se
abre en el navegador) con el mismo Python con el que está instalado Eolfi:

- Windows: un ``Eolfi.lnk`` en el escritorio o en el menú Inicio (se crea con el objeto COM ``WScript.Shell``).
- Linux: un ``eolfi.desktop`` en el escritorio o en ``~/.local/share/applications``.
- macOS: un ``Eolfi.command`` en el escritorio o en ``~/Applications``.

Por defecto solo muestra lo que haría; ``--aplicar`` lo crea y ``--quitar`` lo retira. Nunca sustituye ni borra un
archivo que no sea un lanzador de Eolfi. La carpeta de trabajo es la copia del repositorio si Eolfi se ejecuta desde
una, y ``~/.eolfi`` en los demás casos. Crear o quitar el acceso queda en el registro de acciones (B8).
"""
from __future__ import annotations

import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from eolfi.actualizacion import RAIZ, modo_instalacion

SCHEMA = "eolfi.acceso_directo/v1"
DONDE = ("escritorio", "menu")
MARCA = "eolfi up"             # lo que identifica un lanzador de Eolfi al sustituirlo o quitarlo
MAC_CABECERA = "#!/bin/sh\n# Lanzador del panel Eolfi (eolfi up)\n"


class AccesoDirectoError(ValueError):
    pass


def sistema_actual() -> str:
    return {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}.get(platform.system(), platform.system().lower())


def orden(port: int = 8777, python: str | None = None) -> list[str]:
    if not 1 <= int(port) <= 65535:
        raise AccesoDirectoError(f"puerto fuera de rango: {port}")
    if python is None and getattr(sys, "frozen", False):     # ejecutable: eolfi.exe es la propia CLI
        return [sys.executable, "up", "--port", str(int(port))]
    return [python or sys.executable, "-m", "eolfi", "up", "--port", str(int(port))]


def carpeta_trabajo() -> Path:
    return RAIZ if modo_instalacion() == "copia_repositorio" else Path.home() / ".eolfi"


def _powershell(script: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    # Los valores van por variables de entorno, nunca dentro del script: así una ruta con comillas no se interpreta.
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, timeout=60, env={**os.environ, **env})


def _carpeta_windows(nombre: str) -> Path:
    p = _powershell("[Environment]::GetFolderPath($env:EOLFI_CARPETA)", {"EOLFI_CARPETA": nombre})
    ruta = p.stdout.strip()
    if p.returncode or not ruta:
        raise AccesoDirectoError(f"no se pudo localizar la carpeta {nombre}: {p.stderr.strip()[:200]}")
    return Path(ruta)


def _carpeta_linux(donde: str) -> Path:
    if donde == "menu":
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        return Path(base) / "applications"
    try:
        p = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=10)
        if p.returncode == 0 and p.stdout.strip():
            return Path(p.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / "Desktop"


def destino(donde: str = "escritorio", *, carpeta: str | Path | None = None, sistema: str | None = None) -> Path:
    sistema = sistema or sistema_actual()
    if donde not in DONDE:
        raise AccesoDirectoError(f"ubicación desconocida: {donde} (usa {' o '.join(DONDE)})")
    if sistema == "windows":
        nombre = "Eolfi.lnk"
        base = Path(carpeta) if carpeta else _carpeta_windows("Desktop" if donde == "escritorio" else "Programs")
    elif sistema == "linux":
        nombre = "eolfi.desktop"
        base = Path(carpeta) if carpeta else _carpeta_linux(donde)
    elif sistema == "macos":
        nombre = "Eolfi.command"
        base = Path(carpeta) if carpeta else Path.home() / ("Desktop" if donde == "escritorio" else "Applications")
    else:
        raise AccesoDirectoError(f"acceso directo no soportado en {sistema}; usa «eolfi up» desde una terminal")
    return base / nombre


def _exec_desktop(args: list[str]) -> str:
    """Campo Exec de la especificación de .desktop: comillas dobles y escape de ", `, $ y \\ dentro de ellas."""
    partes = []
    for a in args:
        if a and all(c.isalnum() or c in "-_./:=+," for c in a):
            partes.append(a)
        else:
            esc = a.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
            partes.append(f'"{esc}"')
    return " ".join(partes).replace("%", "%%")


def contenido_desktop(args: list[str], trabajo: Path) -> str:
    if "\n" in str(trabajo) or any("\n" in a for a in args):
        raise AccesoDirectoError("ruta con salto de línea")
    return ("[Desktop Entry]\nType=Application\nName=Eolfi\n"
            "Comment=Panel de Eolfi: Eolas, puente de chats web y panel (eolfi up)\n"
            f"Exec={_exec_desktop(args)}\nPath={trabajo}\nTerminal=true\nCategories=Development;\n")


def _leer_lnk(ruta: Path) -> dict[str, str] | None:
    script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:EOLFI_LNK);"
              "$s.TargetPath; $s.Arguments; $s.WorkingDirectory")
    p = _powershell(script, {"EOLFI_LNK": str(ruta)})
    if p.returncode:
        return None
    lineas = (p.stdout.splitlines() + ["", "", ""])[:3]
    return {"objetivo": lineas[0].strip(), "argumentos": lineas[1].strip(), "carpeta": lineas[2].strip()}


def _es_de_eolfi(ruta: Path, sistema: str) -> bool:
    if ruta.is_symlink():
        return False
    if sistema == "windows":
        info = _leer_lnk(ruta)
        # «python -m eolfi up …» o, en el ejecutable, «eolfi.exe up …»: en los dos casos aparece «eolfi up».
        return bool(info and MARCA in f"{Path(info['objetivo']).stem} {info['argumentos']}")
    try:
        texto = ruta.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if sistema == "macos":
        return texto.startswith(MAC_CABECERA)
    return "[Desktop Entry]" in texto and MARCA in texto


def _argumentos_windows(args: list[str]) -> str:
    return subprocess.list2cmdline(args[1:])


def plan(donde: str = "escritorio", *, port: int = 8777, carpeta: str | Path | None = None,
         sistema: str | None = None, python: str | None = None) -> dict[str, Any]:
    sistema = sistema or sistema_actual()
    ruta = destino(donde, carpeta=carpeta, sistema=sistema)
    args = orden(port, python)
    trabajo = carpeta_trabajo()
    out: dict[str, Any] = {"schema": SCHEMA, "sistema": sistema, "donde": donde, "ruta": str(ruta),
                           "orden": args, "carpeta_trabajo": str(trabajo), "modo_instalacion": modo_instalacion(),
                           "existe": ruta.exists()}
    if sistema == "windows":
        out["lnk"] = {"objetivo": args[0], "argumentos": _argumentos_windows(args), "carpeta": str(trabajo)}
    elif sistema == "macos":
        out["contenido"] = MAC_CABECERA + f"cd {shlex.quote(str(trabajo))} || exit 1\nexec {shlex.join(args)}\n"
    else:
        out["contenido"] = contenido_desktop(args, trabajo)
    return out


def _anotar(operacion: str, params: dict[str, Any], resultado: dict[str, Any]) -> None:
    from eolfi.acciones import anotar

    anotar(operacion, params=params, resultado=resultado, origen="cli")


def crear(donde: str = "escritorio", *, port: int = 8777, carpeta: str | Path | None = None,
          sistema: str | None = None, python: str | None = None) -> dict[str, Any]:
    p = plan(donde, port=port, carpeta=carpeta, sistema=sistema, python=python)
    ruta, sistema = Path(p["ruta"]), p["sistema"]
    if (ruta.exists() or ruta.is_symlink()) and not _es_de_eolfi(ruta, sistema):
        raise AccesoDirectoError(f"{ruta} ya existe y no es un acceso directo de Eolfi: no se sustituye")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    Path(p["carpeta_trabajo"]).mkdir(parents=True, exist_ok=True)
    if sistema == "windows":
        lnk = p["lnk"]
        script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:EOLFI_LNK);"
                  "$s.TargetPath=$env:EOLFI_OBJETIVO; $s.Arguments=$env:EOLFI_ARGS;"
                  "$s.WorkingDirectory=$env:EOLFI_TRABAJO; $s.Description='Panel de Eolfi (eolfi up)'; $s.Save()")
        r = _powershell(script, {"EOLFI_LNK": str(ruta), "EOLFI_OBJETIVO": lnk["objetivo"],
                                 "EOLFI_ARGS": lnk["argumentos"], "EOLFI_TRABAJO": lnk["carpeta"]})
        if r.returncode:
            raise AccesoDirectoError(f"no se pudo crear {ruta}: {r.stderr.strip()[:300]}")
        leido = _leer_lnk(ruta)
        comprobado = bool(leido and Path(leido["objetivo"]) == Path(lnk["objetivo"])
                          and leido["argumentos"] == lnk["argumentos"])
    else:
        ruta.write_text(p["contenido"], encoding="utf-8", newline="\n")
        ruta.chmod(0o755)
        comprobado = ruta.read_text(encoding="utf-8") == p["contenido"]
    p.update(creado=True, comprobado=comprobado)
    _anotar("instalador.acceso_directo", {"donde": donde, "ruta": str(ruta), "port": int(port)},
            {"creado": True, "comprobado": comprobado})
    return p


def quitar(donde: str = "escritorio", *, carpeta: str | Path | None = None, sistema: str | None = None) -> dict[str, Any]:
    sistema = sistema or sistema_actual()
    ruta = destino(donde, carpeta=carpeta, sistema=sistema)
    out: dict[str, Any] = {"schema": SCHEMA, "sistema": sistema, "donde": donde, "ruta": str(ruta), "quitado": False}
    if not ruta.exists():
        out["nota"] = "no había acceso directo"
        return out
    if not _es_de_eolfi(ruta, sistema):
        raise AccesoDirectoError(f"{ruta} no es un acceso directo de Eolfi: no se borra")
    ruta.unlink()
    out["quitado"] = True
    _anotar("instalador.acceso_directo.quitar", {"donde": donde, "ruta": str(ruta)}, {"quitado": True})
    return out
