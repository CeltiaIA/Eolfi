"""B8: el puente Node y Python escriben una sola cadena de acciones que verifica eolfi/acciones.py."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from eolfi import acciones

MODULO = Path(__file__).resolve().parents[1] / "eolfi" / "bridge" / "acciones.mjs"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="sin Node: compatibilidad NO VERIFICADA")


def _node(path: Path, operacion: str, params: dict) -> dict:
    script = (f"import {{ anotar }} from {json.dumps(MODULO.as_uri())};\n"
              f"process.stdout.write(JSON.stringify(anotar({json.dumps(operacion)}, {{ params: {json.dumps(params)} }})));")
    proc = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True,
                          encoding="utf-8", timeout=60, env={**__import__("os").environ, "EOLFI_ACCIONES_FILE": str(path)})
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_cadena_mixta_python_y_node(tmp_path, monkeypatch):
    path = tmp_path / "acciones.jsonl"
    monkeypatch.setenv("EOLFI_ACCIONES_FILE", str(path))
    acciones.anotar("eolas_v2.arrancar", params={"perfil": "gemma"})
    raro = {"provider": "deepseek", "nota": "ñ «x»   \t \"q\" 😀", "prompt": acciones.huella("hola")}
    e2 = _node(path, "puente.chat", raro)
    acciones.anotar("eolas_v2.parar", params={"n": 3})
    _node(path, "puente.revocar", {"provider": "deepseek", "conversation": None})
    res = acciones.verificar()
    assert res == {"ok": True, "eventos": 4, "ultimo": acciones.eventos()[-1]["sha256"], "archivo": str(path)}
    assert e2["seq"] == 2 and e2["origen"] == "puente" and e2["params"]["nota"] == raro["nota"]
    # El hash que calcula Node coincide con el que recalcula Python.
    assert acciones._digest(acciones.eventos()[1]) == e2["sha256"]


def test_node_detecta_la_cabeza_escrita_por_python(tmp_path, monkeypatch):
    path = tmp_path / "acciones.jsonl"
    monkeypatch.setenv("EOLFI_ACCIONES_FILE", str(path))
    e1 = acciones.anotar("x", params={})
    e2 = _node(path, "puente.permiso", {"minutos": 30})
    assert e2["prev"] == e1["sha256"] and e2["seq"] == 2
    lineas = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lineas[0], lineas[1].replace('"minutos":30', '"minutos":300')]) + "\n",
                    encoding="utf-8")
    assert acciones.verificar()["roto_en"] == 2
