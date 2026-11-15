"""La salida del CLI redirigida a archivo es UTF-8 válido (15/11/2026).

En Windows, con stdout redirigido, Python escribía con la página local (cp1252) y `json.load(open(...,
encoding="utf-8"))` fallaba en las tildes. Se ejecuta el CLI en un subproceso real, con stdout a un archivo y sin
PYTHONIOENCODING ni PYTHONUTF8, para reproducir el caso.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOMBRE = "Análisis de la canción ñandú — «pingüino»"


def _run(tmp_path, out_name, *args):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    env["EOLFI_HOME"] = str(tmp_path / "home")
    out = tmp_path / out_name
    with open(out, "wb") as fh:
        r = subprocess.run([sys.executable, "-m", "eolfi", "--db", str(tmp_path / "e.db"), *args], cwd=ROOT,
                           env=env, stdout=fh, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=120)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    return out.read_bytes().decode("utf-8")   # falla con UnicodeDecodeError si no es UTF-8


def test_json_redirigido_es_utf8(tmp_path):
    text = _run(tmp_path, "case.json", "case", "create", NOMBRE)
    assert text.endswith("\n")
    case = json.loads(text)
    assert case["name"] == NOMBRE
    with open(tmp_path / "case.json", encoding="utf-8") as fh:
        assert json.load(fh)["name"] == NOMBRE


def test_informe_html_redirigido_es_utf8(tmp_path):
    cid = json.loads(_run(tmp_path, "case.json", "case", "create", NOMBRE))["case_id"]
    html = _run(tmp_path, "rep.html", "case", "report", cid)
    assert "ñandú" in html and "pingüino" in html
