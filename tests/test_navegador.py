"""Navegador propio de Eolfi (eolfi navegador): sin red, con npm y Playwright simulados."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from eolfi import acciones, navegador
from eolfi.generador import juez

ROOT = Path(__file__).resolve().parents[1]
EXE = "chrome-headless-shell.exe" if sys.platform == "win32" else "chrome-headless-shell"


@pytest.fixture
def aislado(tmp_path, monkeypatch):
    monkeypatch.setenv("EOLFI_NAVEGADOR_DIR", str(tmp_path / "nav"))
    monkeypatch.setenv("EOLFI_ACCIONES_FILE", str(tmp_path / "acciones.jsonl"))
    monkeypatch.delenv("EOLAS_OFFLINE", raising=False)
    return tmp_path / "nav"


def test_versiones_fijadas_iguales_que_las_pruebas_e2e():
    e2e = json.loads((ROOT / "tests" / "e2e" / "package.json").read_text(encoding="utf-8"))["devDependencies"]
    assert navegador.DEPENDENCIAS == {k: e2e[k] for k in navegador.DEPENDENCIAS}


def test_sin_instalar_y_manifiesto_que_apunta_fuera(aislado, tmp_path):
    assert navegador.estado()["instalado"] is False and navegador.ejecutable() is None
    aislado.mkdir()
    fuera = tmp_path / EXE
    fuera.write_bytes(b"x")
    (aislado / navegador.MANIFIESTO).write_text(json.dumps({"ejecutable": str(fuera)}), encoding="utf-8")
    assert navegador.ejecutable() is None                     # solo un ejecutable dentro de su carpeta
    assert navegador.estado()["instalado"] is False


def _falso_run(fallar_en=None):
    def run(cmd, cwd, env, plazo):
        cwd = Path(cwd)
        assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(cwd)
        if cmd[1] == "install" and "--ignore-scripts" in cmd:               # npm install
            if fallar_en == "npm":
                return subprocess.CompletedProcess(cmd, 1, "", "E404")
            deps = json.loads((cwd / "package.json").read_text(encoding="utf-8"))["dependencies"]
            for nombre, version in deps.items():
                d = cwd / "node_modules" / nombre
                d.mkdir(parents=True)
                (d / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
            (cwd / "node_modules" / "playwright-core" / "index.mjs").write_text("", encoding="utf-8")
            (cwd / "node_modules" / "axe-core" / "axe.min.js").write_text("", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        assert cmd[2:] == ["install", "--only-shell", "chromium"]          # playwright install
        if fallar_en == "navegador":
            return subprocess.CompletedProcess(cmd, 1, "", "sin red")
        d = cwd / "chromium_headless_shell-1248" / "chrome-headless-shell-x"
        d.mkdir(parents=True)
        (d / EXE).write_bytes(b"navegador")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return run


def test_instalar_deja_manifiesto_hash_y_registro(aislado, monkeypatch):
    monkeypatch.setattr(navegador.shutil, "which", lambda n: f"/bin/{n}")
    monkeypatch.setattr(navegador, "_run", _falso_run())
    r = navegador.instalar()
    assert r["ok"] and r["revision"] == "1248" and r["dependencias"] == navegador.DEPENDENCIAS
    assert r["sha256"] == navegador._sha256(Path(r["ejecutable"])) and r["bytes"] == 9
    est = navegador.estado(comprobar_hash=True)
    assert est["instalado"] is True and est["sha256_coincide"] is True
    Path(r["ejecutable"]).write_bytes(b"cambiado")
    assert navegador.estado(comprobar_hash=True)["sha256_coincide"] is False
    ev = acciones.eventos()[-1]
    assert ev["operacion"] == "navegador.instalar" and ev["ok"] and ev["resultado"]["revision"] == "1248"
    assert acciones.verificar()["ok"]


@pytest.mark.parametrize("paso", ["npm", "navegador"])
def test_un_fallo_se_registra_y_no_deja_manifiesto(aislado, monkeypatch, paso):
    monkeypatch.setattr(navegador.shutil, "which", lambda n: f"/bin/{n}")
    monkeypatch.setattr(navegador, "_run", _falso_run(fallar_en=paso))
    with pytest.raises(navegador.NavegadorError):
        navegador.instalar()
    assert not (aislado / navegador.MANIFIESTO).exists()
    assert acciones.eventos()[-1]["ok"] is False


def test_sin_red_no_descarga(aislado, monkeypatch):
    monkeypatch.setattr(navegador.shutil, "which", lambda n: f"/bin/{n}")
    monkeypatch.setenv("EOLAS_OFFLINE", "1")
    with pytest.raises(navegador.NavegadorError, match="EOLAS_OFFLINE"):
        navegador.instalar()


def test_el_juez_prefiere_lo_propio(aislado, monkeypatch, tmp_path):
    monkeypatch.setattr(navegador.shutil, "which", lambda n: f"/bin/{n}")
    monkeypatch.setattr(navegador, "_run", _falso_run())
    r = navegador.instalar()
    for k in ("EOLFI_PLAYWRIGHT", "EOLFI_AXE", "EOLFI_BROWSER_PATH", "EOLFI_BROWSER_CHANNEL"):
        monkeypatch.delenv(k, raising=False)
    assert juez._playwright() == str(aislado / "node_modules" / "playwright-core")
    assert juez._axe() == str(aislado / "node_modules" / "axe-core" / "axe.min.js")
    visto = {}

    def run(cmd, **kw):
        visto.clear()
        visto.update(kw["env"])
        return subprocess.CompletedProcess(cmd, 0, b'{"status": "ok", "checks": []}', b"")

    monkeypatch.setattr(juez.shutil, "which", lambda n: "/bin/node")
    monkeypatch.setattr(juez.subprocess, "run", run)
    juez.juzgar(tmp_path, juez.validar({"version": 1, "pasos": [{"comprobar": "x", "presente": "y"}]}))
    assert visto["EOLFI_BROWSER_PATH"] == r["ejecutable"]
    monkeypatch.setenv("EOLFI_BROWSER_CHANNEL", "chrome")                  # lo declarado manda
    juez.juzgar(tmp_path, juez.validar({"version": 1, "pasos": [{"comprobar": "x", "presente": "y"}]}))
    assert visto["EOLFI_BROWSER_CHANNEL"] == "chrome" and "EOLFI_BROWSER_PATH" not in visto
