"""La guía ejemplos/instalador/GUIA.md, ejecutada tal cual en una carpeta temporal (criterios de aceptación)."""
import json
import platform
from pathlib import Path

import pytest

import eolfi
from eolfi.cli import main

GUIA = Path(__file__).resolve().parent.parent / "ejemplos" / "instalador" / "GUIA.md"


def run(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr().out
    return code, (json.loads(out) if out.strip().startswith(("{", "[")) else out)


def test_guia_version(capsys, monkeypatch):
    assert "update --check" in GUIA.read_text(encoding="utf-8")
    monkeypatch.delenv("EOLAS_OFFLINE", raising=False)
    code, rep = run(capsys, "update", "--check")
    inst = rep["instalada"]
    assert code == 2 and rep["estado"] == "NO VERIFICADO" and "sin --red" in rep["motivo"]
    assert inst["version"] == eolfi.__version__ and rep["instala_nada"] is True
    assert inst["modo"] in ("copia_repositorio", "entorno_virtual", "pipx", "ejecutable", "python_sistema")


@pytest.mark.skipif(platform.system() not in ("Windows", "Linux"), reason="lanzador solo en Windows y Linux")
def test_guia_acceso_directo(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EOLFI_ACCIONES_FILE", str(tmp_path / "acciones.jsonl"))
    nombre = "Eolfi.lnk" if platform.system() == "Windows" else "eolfi.desktop"
    code, vista = run(capsys, "acceso-directo", "--carpeta", "lanzadores")
    assert code == 0 and vista["vista_previa"] is True and Path(vista["ruta"]).name == nombre
    assert vista["orden"][1:] == ["-m", "eolfi", "up", "--port", "8777"]
    assert not (tmp_path / "lanzadores").exists()
    code, hecho = run(capsys, "acceso-directo", "--carpeta", "lanzadores", "--aplicar")
    assert code == 0 and hecho["creado"] is True and hecho["comprobado"] is True
    assert (tmp_path / "lanzadores" / nombre).is_file()
    code, eventos = run(capsys, "acciones", "listar")
    assert [e["operacion"] for e in eventos] == ["instalador.acceso_directo"]
    code, fuera = run(capsys, "acceso-directo", "--carpeta", "lanzadores", "--quitar")
    assert code == 0 and fuera["quitado"] is True and not (tmp_path / "lanzadores" / nombre).exists()
    # Nunca sustituye un archivo ajeno con el mismo nombre.
    ajeno = tmp_path / "lanzadores" / nombre
    ajeno.write_bytes(b"no es de eolfi")
    code, _ = run(capsys, "acceso-directo", "--carpeta", "lanzadores", "--aplicar")
    assert code != 0 and ajeno.read_bytes() == b"no es de eolfi"
    code, _ = run(capsys, "acceso-directo", "--carpeta", "lanzadores", "--quitar")
    assert code != 0 and ajeno.read_bytes() == b"no es de eolfi"      # ni lo borra
