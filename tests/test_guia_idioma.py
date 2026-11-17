"""La guía ejemplos/idioma/GUIA.md: CLI y API en inglés solo cuando se pide (el panel lo prueba el e2e)."""
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from eolfi.server import make_server

ROOT = Path(__file__).resolve().parent.parent
GUIA = ROOT / "ejemplos" / "idioma" / "GUIA.md"


def ayuda(*args, env=None):
    entorno = {k: v for k, v in os.environ.items() if k != "EOLFI_IDIOMA"}
    entorno.update(PYTHONIOENCODING="utf-8", **(env or {}))
    r = subprocess.run([sys.executable, "-m", "eolfi", *args], cwd=ROOT, env=entorno, capture_output=True,
                       text=True, encoding="utf-8", timeout=60, check=False)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_guia_cli():
    assert "--idioma en" in GUIA.read_text(encoding="utf-8")
    es = ayuda("acciones", "--help")
    en = ayuda("--idioma", "en", "acciones", "--help")
    por_entorno = ayuda("acciones", "--help", env={"EOLFI_IDIOMA": "en"})
    assert "Recalcula la cadena SHA-256 del registro" in es
    assert "Recomputes the log's SHA-256 chain" in en and "Recomputes the log's SHA-256 chain" in por_entorno
    for orden in ("verificar", "clave", "firmar", "anclar", "listar"):   # los nombres de las órdenes no cambian
        assert orden in en


@pytest.fixture
def api(tmp_path):
    httpd = make_server(str(tmp_path / "e.db"), "127.0.0.1", 0, tmp_path / "s")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def error(port, query="", headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/jobs?id=no-existe{query}", headers=headers or {})
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=10)
    return exc.value.code, exc.value.headers.get("Content-Language"), json.loads(exc.value.read())


def test_guia_api(api):
    assert error(api) == (404, "es", {"error": "trabajo no encontrado"})
    ingles = (404, "en", {"error": "job not found"})
    assert error(api, "&lang=en") == ingles
    assert error(api, headers={"Accept-Language": "en-GB,en;q=0.9"}) == ingles
    assert error(api, headers={"Cookie": "eolfi_idioma=en"}) == ingles
