r"""Corpus compartido con Alejandría (biblioteca local de código y textos).

Eolfi no copia nada por su cuenta: usa los scripts de la propia biblioteca, que ya
validan la sintaxis, deduplican por contenido (SHA-256 normalizado), excluyen
secretos y registran cada acción en manifests/auditoria.jsonl. Las fuentes y
exclusiones son las de <biblioteca>/config/fuentes.json, las mismas que usa el
mantenimiento horario: así el índice del corpus queda siempre completo.

    python -m eolfi corpus [--library D:\Alejandria] [--dry-run]
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def library_config(library: Path) -> dict:
    cfg = library / "config" / "fuentes.json"
    if not cfg.is_file():
        raise FileNotFoundError(f"No existe {cfg}: crea la lista de fuentes del corpus compartido")
    data = json.loads(cfg.read_text(encoding="utf-8-sig"))
    sources = [s for s in data.get("fuentes", []) if Path(s).is_dir()]
    if not sources:
        raise ValueError(f"{cfg} no tiene fuentes existentes")
    return {"fuentes": sources, "excluir_carpetas": data.get("excluir_carpetas") or []}


def run_corpus(library: str, *, dry_run: bool = False) -> int:
    lib = Path(library)
    organizer = lib / "scripts" / "Organizar-Corpus.ps1"
    audit = lib / "scripts" / "Audit-Alejandria.ps1"
    if not organizer.is_file():
        raise FileNotFoundError(f"No es una biblioteca Alejandría (falta {organizer})")
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        raise FileNotFoundError("PowerShell no está instalado (necesario para los scripts de la biblioteca)")
    cfg = library_config(lib)
    eolfi_root = str(Path(__file__).resolve().parent.parent)
    if not any(Path(s).resolve() == Path(eolfi_root) for s in cfg["fuentes"]):
        print(f"Aviso: {eolfi_root} no figura en config/fuentes.json; no se guardará el código de Eolfi.",
              file=sys.stderr)

    # Ningún dato externo se mete en el texto del comando: PowerShell también cierra cadenas con las
    # comillas tipográficas (‘ ’ ‚ ‛), así que escapar «'» no basta. Los datos viajan como JSON en una
    # variable de entorno y el comando es SIEMPRE el mismo texto fijo (PLAN_MEJORAS M40).
    payload = {
        "organizer": str(organizer), "audit": str(audit) if audit.is_file() else "", "root": str(lib),
        "sources": cfg["fuentes"], "excluded": cfg["excluir_carpetas"], "dryRun": bool(dry_run),
    }
    command = (
        "$a = $env:EOLFI_CORPUS_ARGS | ConvertFrom-Json; "
        "$p = @{ Source = [string[]]$a.sources; Root = [string]$a.root }; "
        "if ($a.excluded) { $p.ExcludedDirs = [string[]]$a.excluded }; "
        "if ($a.dryRun) { $p.DryRun = $true }; "
        "& ([string]$a.organizer) @p; "
        "if (-not $a.dryRun -and $a.audit) { foreach ($s in $a.sources) { & ([string]$a.audit) -Root ([string]$a.root) -Source ([string]$s) } }"
    )
    env = dict(os.environ, EOLFI_CORPUS_ARGS=json.dumps(payload, ensure_ascii=False))
    print(f"Corpus compartido en {lib}: fuentes {', '.join(cfg['fuentes'])}" + (" (prueba en seco)" if dry_run else ""))
    return subprocess.call([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
                           env=env)
