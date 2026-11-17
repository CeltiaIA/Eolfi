"""La guía ejemplos/registro-acciones/GUIA.md, ejecutada tal cual en una carpeta temporal (criterios de aceptación)."""
import json
import platform
from pathlib import Path

import pytest

from eolfi.cli import main

GUIA = Path(__file__).resolve().parent.parent / "ejemplos" / "registro-acciones" / "GUIA.md"

pytestmark = pytest.mark.skipif(platform.system() not in ("Windows", "Linux"),
                                reason="el acceso directo de la guía existe en Windows y Linux")


@pytest.fixture
def guia(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registro = tmp_path / "registro" / "acciones.jsonl"
    monkeypatch.setenv("EOLFI_ACCIONES_FILE", str(registro))
    monkeypatch.delenv("EOLFI_ACCIONES", raising=False)
    return registro


def run(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr().out
    return code, (json.loads(out) if out.strip().startswith(("{", "[")) else out)


def test_guia_registro_acciones(guia, capsys):
    assert "acciones verificar --clave" in GUIA.read_text(encoding="utf-8")
    # 0. la vista previa no anota; --aplicar sí
    assert run(capsys, "acceso-directo", "--carpeta", "lanzadores")[1]["vista_previa"] is True
    assert not guia.exists()
    assert run(capsys, "acceso-directo", "--carpeta", "lanzadores", "--aplicar")[0] == 0
    # 1. listar y verificar
    code, eventos = run(capsys, "acciones", "listar")
    assert code == 0 and len(eventos) == 1
    ev = eventos[0]
    assert (ev["operacion"], ev["origen"], ev["ok"], ev["prev"]) == ("instalador.acceso_directo", "cli", True, "0" * 64)
    code, ver = run(capsys, "acciones", "verificar")
    assert code == 0 and ver["ok"] is True and ver["eventos"] == 1 and ver["ultimo"] == ev["sha256"]
    # 2. clave (sin sobrescribir), firma y verificación con firma
    assert run(capsys, "acciones", "clave", "--destino", "clave/firma.key")[0] == 0
    assert run(capsys, "acciones", "clave", "--destino", "clave/firma.key")[0] != 0
    capsys.readouterr()
    code, firma = run(capsys, "acciones", "firmar", "--clave", "clave/firma.key")
    assert code == 0 and firma["firmado_hasta"] == 1 and firma["evento"] == 2
    code, ver = run(capsys, "acciones", "verificar", "--clave", "clave/firma.key")
    f = ver["firmas"]
    assert code == 0 and f["ok"] is True and f["firmas"] == 1 and f["sin_firmar_al_final"] == 0
    # 3. lo posterior a la firma queda sin firmar
    assert run(capsys, "acceso-directo", "--carpeta", "lanzadores", "--quitar")[1]["quitado"] is True
    code, ver = run(capsys, "acciones", "verificar", "--clave", "clave/firma.key")
    assert code == 0 and ver["eventos"] == 3 and ver["firmas"]["sin_firmar_al_final"] == 1
    # 4. una manipulación se detecta
    lineas = guia.read_text(encoding="utf-8").splitlines(keepends=True)
    primero = json.loads(lineas[0])
    assert primero["resultado"]["creado"] is True
    primero["resultado"]["creado"] = False
    lineas[0] = json.dumps(primero, ensure_ascii=False) + "\n"
    guia.write_text("".join(lineas), encoding="utf-8")
    code, ver = run(capsys, "acciones", "verificar", "--clave", "clave/firma.key")
    assert code == 2 and ver["ok"] is False and ver["roto_en"] == 1 and ver["motivo"] == "cadena rota"
