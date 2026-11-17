"""C2: acceso directo de «eolfi up», lanzador del ejecutable y Python base de verify."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from eolfi import _ejecutable, instalador
from eolfi.cli import main
from eolfi.generador import verify

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def anotados(monkeypatch):
    lista = []
    monkeypatch.setattr(instalador, "_anotar", lambda op, params, res: lista.append((op, params, res)))
    return lista


def test_orden_con_python_y_en_el_ejecutable(monkeypatch):
    assert instalador.orden(8800, python="py") == ["py", "-m", "eolfi", "up", "--port", "8800"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert instalador.orden(8777)[1:] == ["up", "--port", "8777"]
    with pytest.raises(instalador.AccesoDirectoError):
        instalador.orden(70000)


def test_exec_de_desktop_escapa_espacios_y_especiales():
    exec_ = instalador._exec_desktop(['/opt/mi python/bin/python', "-m", "eolfi", "up", 'a"$`\\b', "100%"])
    assert exec_ == '"/opt/mi python/bin/python" -m eolfi up "a\\"\\$\\`\\\\b" "100%%"'
    with pytest.raises(instalador.AccesoDirectoError):
        instalador.contenido_desktop(["x\ny"], Path("/tmp"))


def test_linux_crear_sustituir_y_quitar(tmp_path, anotados):
    r = instalador.crear("menu", carpeta=tmp_path, sistema="linux", python="/usr/bin/python3", port=8790)
    ruta = tmp_path / "eolfi.desktop"
    texto = ruta.read_text(encoding="utf-8")
    assert r["comprobado"] and "Exec=/usr/bin/python3 -m eolfi up --port 8790" in texto and "Terminal=true" in texto
    instalador.crear("menu", carpeta=tmp_path, sistema="linux", python="/usr/bin/python3")   # el suyo: se sustituye
    assert instalador.quitar("menu", carpeta=tmp_path, sistema="linux")["quitado"] and not ruta.exists()
    assert instalador.quitar("menu", carpeta=tmp_path, sistema="linux")["quitado"] is False
    assert [a[0] for a in anotados] == ["instalador.acceso_directo"] * 2 + ["instalador.acceso_directo.quitar"]


def test_no_sustituye_ni_borra_un_archivo_ajeno(tmp_path, anotados):
    ajeno = tmp_path / "eolfi.desktop"
    ajeno.write_text("[Desktop Entry]\nExec=otra-cosa\n", encoding="utf-8")
    with pytest.raises(instalador.AccesoDirectoError, match="no es un acceso directo de Eolfi"):
        instalador.crear("escritorio", carpeta=tmp_path, sistema="linux")
    with pytest.raises(instalador.AccesoDirectoError, match="no se borra"):
        instalador.quitar("escritorio", carpeta=tmp_path, sistema="linux")
    assert ajeno.read_text(encoding="utf-8") == "[Desktop Entry]\nExec=otra-cosa\n" and not anotados


def test_macos_y_ubicacion_desconocida_se_rechazan(tmp_path):
    with pytest.raises(instalador.AccesoDirectoError, match="no soportado"):
        instalador.destino(carpeta=tmp_path, sistema="macos")
    with pytest.raises(instalador.AccesoDirectoError, match="ubicación"):
        instalador.destino("barra", carpeta=tmp_path, sistema="linux")


def test_cli_sin_aplicar_es_vista_previa(tmp_path, capsys, anotados):
    assert main(["acceso-directo", "--carpeta", str(tmp_path), "--port", "8801"]) == 0
    salida = capsys.readouterr().out
    assert '"vista_previa": true' in salida and "8801" in salida
    assert not list(tmp_path.iterdir()) and not anotados


@pytest.mark.skipif(os.name != "nt", reason="acceso directo .lnk de Windows")
def test_windows_lnk_real(tmp_path, anotados):
    r = instalador.crear("escritorio", carpeta=tmp_path, port=8802)
    lnk = tmp_path / "Eolfi.lnk"
    assert lnk.is_file() and r["comprobado"] is True
    leido = instalador._leer_lnk(lnk)
    assert Path(leido["objetivo"]) == Path(sys.executable) and leido["argumentos"] == "-m eolfi up --port 8802"
    assert instalador._es_de_eolfi(lnk, "windows")
    assert instalador.quitar("escritorio", carpeta=tmp_path)["quitado"] and not lnk.exists()


def test_lanzador_del_ejecutable_acepta_menos_m(capsys):
    from eolfi import __version__

    assert _ejecutable.principal(["-m", "eolfi", "--version"]) == 0
    assert capsys.readouterr().out.strip() == f"eolfi {__version__}"
    assert _ejecutable.principal(["-m", "os"]) == 2


def test_lanzador_sin_menos_m_es_la_cli(capsys):
    assert _ejecutable.principal(["update", "--check"]) in (0, 1, 2)
    assert '"schema": "eolfi.actualizacion/v1"' in capsys.readouterr().out


def test_python_base_en_el_ejecutable_usa_el_del_sistema(monkeypatch):
    assert verify.python_base() == sys.executable
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(verify.shutil, "which", lambda n: "/usr/bin/python3" if n == "python3" else None)
    assert verify.python_base() == "/usr/bin/python3"


def test_la_rueda_declara_los_scripts_mjs():
    texto = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    assert '"generador/*.mjs"' in texto and '"sites/*.mjs"' in texto


def test_paquete_instalado_en_entorno_nuevo():
    """Construye la rueda sin red, la instala en un entorno virtual nuevo (como pipx) y arranca el panel."""
    pytest.importorskip("setuptools")
    p = subprocess.run([sys.executable, str(RAIZ / "tools" / "verificar_paquete.py")], capture_output=True,
                       text=True, encoding="utf-8", timeout=900)
    assert p.returncode == 0, p.stdout[-3000:] + p.stderr[-2000:]
    assert '"estado": "verificado"' in p.stdout
