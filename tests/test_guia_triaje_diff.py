"""La guía ejemplos/triaje-y-diff/GUIA.md, ejecutada con sus muestras sintéticas (criterios de aceptación)."""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from eolfi.cli import main

EJEMPLO = Path(__file__).resolve().parent.parent / "ejemplos" / "triaje-y-diff"


@pytest.fixture
def guia(tmp_path, monkeypatch):
    work = tmp_path / "triaje-y-diff"
    shutil.copytree(EJEMPLO, work)
    monkeypatch.chdir(work)
    return work


def run(capsys, *args):
    code = main(["--db", "guia.db", *args])
    out = capsys.readouterr().out
    return code, (json.loads(out) if out.strip().startswith(("{", "[")) else out)


def test_muestra_wasm_es_la_documentada(guia):
    data = (guia / "muestra.wasm").read_bytes()
    assert len(data) == 42 and data[:8] == b"\0asm\x01\0\0\0" and b"respuesta" in data


def test_guia_triaje(guia, capsys):
    assert "triage muestra.wasm --local" in (guia / "GUIA.md").read_text(encoding="utf-8")
    code, tri = run(capsys, "triage", "muestra.wasm", "--local", "--summary")
    assert code == 0 and tri["summary"]["format"] == "wasm" and tri["providers_failed"] == []
    assert tri["subject"] == hashlib.sha256((guia / "muestra.wasm").read_bytes()).hexdigest()
    code, evs = run(capsys, "evidence", "--operation", "wasm_module")
    wasm = evs[0]["result"]
    assert [s["name"] for s in wasm["sections"]] == ["type", "function", "export", "code"]
    assert wasm["exports"] == [{"index": 0, "kind": "function", "name": "respuesta"}]
    assert "no se desensambla" in evs[0]["limitations"]
    code, _ = run(capsys, "report", tri["subject"], "--format", "md", "--fail-on", "high", "--out", "informe.md")
    informe = (guia / "informe.md").read_text(encoding="utf-8")
    assert code == 0 and "wasm_module" in informe and "<dato personal" not in informe


def test_guia_diff(guia, capsys):
    py = f'"{sys.executable}"'
    args = ("diff", "--autorizo", "--ref", f"{py} referencia.py", "--cand", f"{py} candidato.py", "corpus")
    assert run(capsys, "diff", "--ref", "x", "--cand", "y", "corpus")[0] == 2        # sin --autorizo no ejecuta
    code, rep = run(capsys, *args)
    assert code == 4 and rep["passed"] is False and rep["ratio"] == pytest.approx(0.6667, abs=1e-4)
    assert rep["mismatched_inputs"] == ["sin-salto.txt"] and rep["incognitas_opened"] == 1
    diff = rep["cases"][0]["stdout_diff"]
    assert "-lineas=1 palabras=3 caracteres=15" in diff and "+lineas=0 palabras=3 caracteres=15" in diff
    # corregir el candidato como indica la guía y repetir
    cand = guia / "candidato.py"
    cand.write_text(cand.read_text(encoding="utf-8").replace("texto.count(chr(10))", "len(texto.splitlines())"),
                    encoding="utf-8")
    code, rep = run(capsys, *args)
    assert code == 0 and rep["passed"] is True and rep["ratio"] == 1.0 and rep["incognitas_closed"] == 1
    p = subprocess.run([sys.executable, "candidato.py"], input="a\nb", capture_output=True, text=True)
    assert p.stdout.strip() == "lineas=2 palabras=2 caracteres=3"
