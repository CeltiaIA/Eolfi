"""Regla de salida para el servidor local de modelos.

La vista previa no cambia el sistema. En Windows, aplicar y retirar usan los
cmdlets NetSecurity con el ejecutable como variable de entorno.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Callable

SCHEMA = "eolfi.cortafuegos/v1"
PREFIJO = "Eolfi sin red"


class CortafuegosError(ValueError):
    pass


def _nombre(programa: Path) -> str:
    digest = hashlib.sha256(str(programa).casefold().encode("utf-8")).hexdigest()[:12]
    return f"{PREFIJO} {digest}"


def _powershell(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
        env={**os.environ, **env},
    )


def _programa(path: str | Path) -> Path:
    programa = Path(path).expanduser().resolve()
    if not programa.is_file():
        raise CortafuegosError(f"no existe el ejecutable del servidor: {programa}")
    if programa.suffix.lower() != ".exe":
        raise CortafuegosError("la regla Windows exige un ejecutable .exe")
    return programa


def estado(path: str | Path, *, sistema: str | None = None,
           run: Callable[[str, dict[str, str]], subprocess.CompletedProcess[str]] = _powershell) -> dict[str, Any]:
    programa = _programa(path)
    sistema = sistema or platform.system().lower()
    out: dict[str, Any] = {"schema": SCHEMA, "programa": str(programa), "regla": _nombre(programa),
                           "sistema": sistema, "estado": "NO VERIFICADO", "aplicado": False}
    if sistema != "windows":
        out["motivo"] = "El proveedor de reglas está implementado para Windows"
        return out
    script = (
        "$r=Get-NetFirewallRule -DisplayName $env:EOLFI_REGLA -ErrorAction SilentlyContinue;"
        "if(-not $r){'{\"existe\":false}';exit 0};"
        "$a=$r|Get-NetFirewallApplicationFilter;"
        "[pscustomobject]@{existe=$true;enabled=[string]$r.Enabled;direction=[string]$r.Direction;"
        "action=[string]$r.Action;program=[string]$a.Program}|ConvertTo-Json -Compress"
    )
    proc = run(script, {"EOLFI_REGLA": out["regla"]})
    if proc.returncode:
        out["motivo"] = (proc.stderr or proc.stdout or "no se pudo consultar NetSecurity").strip()[:300]
        return out
    try:
        data = json.loads(proc.stdout)
    except (TypeError, ValueError):
        out["motivo"] = "NetSecurity no devolvió JSON válido"
        return out
    if data.get("existe") is False:
        out.update(estado="ausente", verificada=True)
        return out
    coincide = (data.get("enabled") == "True" and data.get("direction") == "Outbound"
                and data.get("action") == "Block"
                and Path(str(data.get("program") or "")).resolve() == programa)
    out.update(estado="bloqueado" if coincide else "NO VERIFICADO", verificada=coincide, observado=data)
    if not coincide:
        out["motivo"] = "La regla existe, pero sus campos no coinciden con el bloqueo esperado"
    return out


def cambiar(path: str | Path, *, aplicar: bool, sistema: str | None = None,
            run: Callable[[str, dict[str, str]], subprocess.CompletedProcess[str]] = _powershell) -> dict[str, Any]:
    programa = _programa(path)
    sistema = sistema or platform.system().lower()
    if sistema != "windows":
        raise CortafuegosError("La gestión de reglas está implementada para Windows")
    nombre = _nombre(programa)
    if aplicar:
        script = (
            "$e=Get-NetFirewallRule -DisplayName $env:EOLFI_REGLA -ErrorAction SilentlyContinue;"
            "if($e){throw 'La regla ya existe'};"
            "New-NetFirewallRule -DisplayName $env:EOLFI_REGLA -Direction Outbound -Action Block "
            "-Enabled True -Profile Any -Program $env:EOLFI_PROGRAMA|Out-Null"
        )
    else:
        script = (
            "$r=Get-NetFirewallRule -DisplayName $env:EOLFI_REGLA -ErrorAction SilentlyContinue;"
            "if($r){$a=$r|Get-NetFirewallApplicationFilter;"
            "if([IO.Path]::GetFullPath([string]$a.Program) -ne [IO.Path]::GetFullPath($env:EOLFI_PROGRAMA))"
            "{throw 'La regla pertenece a otro ejecutable'};$r|Remove-NetFirewallRule}"
        )
    proc = run(script, {"EOLFI_REGLA": nombre, "EOLFI_PROGRAMA": str(programa)})
    if proc.returncode:
        raise CortafuegosError((proc.stderr or proc.stdout or "NetSecurity falló").strip()[:300])
    result = estado(programa, sistema=sistema, run=run)
    esperado = "bloqueado" if aplicar else "ausente"
    if result["estado"] != esperado:
        raise CortafuegosError(f"la comprobación posterior no confirmó el estado {esperado}")
    result["aplicado"] = aplicar
    from eolfi.acciones import anotar
    anotar("cortafuegos.bloquear" if aplicar else "cortafuegos.retirar",
           params={"programa": str(programa), "regla": nombre}, resultado={"estado": result["estado"]}, origen="cli")
    return result
