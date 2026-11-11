"""La guía ejemplos/web-y-repo/GUIA.md, ejecutada con sus muestras sintéticas (criterios de aceptación)."""
import json
import shutil
from pathlib import Path

import pytest

from eolfi.cli import main

EJEMPLO = Path(__file__).resolve().parent.parent / "ejemplos" / "web-y-repo"


@pytest.fixture
def guia(tmp_path, monkeypatch):
    work = tmp_path / "web-y-repo"
    shutil.copytree(EJEMPLO, work, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
    monkeypatch.chdir(work)
    return work


def run(capsys, *args):
    code = main(["--db", "guia.db", *args])
    out = capsys.readouterr().out
    return code, (json.loads(out) if out.strip().startswith(("{", "[")) else out)


def _ev(capsys, operation):
    code, evs = run(capsys, "evidence", "--operation", operation)
    assert code == 0 and len(evs) == 1, operation
    return evs[0]["result"]


def test_guia_web(guia, capsys):
    code, web = run(capsys, "web", "sitio")
    s = web["summary"]
    assert code == 0 and s["stack"] == [] and s["stack_label"] == "HTML estático sin framework detectado"
    assert {"header", "nav", "main", "form#nueva"} <= set(s["page_skeleton"])
    tokens = s["design_tokens"]
    assert tokens["colors"] == ["#fdfcf8", "#222"] and tokens["fonts"] == ["system-ui"]
    assert tokens["custom_properties_sample"] == ["--fondo", "--tinta"]
    js = _ev(capsys, "web_js")
    assert js["api_endpoints"] == ["/api/notas"] and js["features"] == {"fetch": 1, "localStorage": 2}
    assert _ev(capsys, "web_accessibility")["issues"] == []


def test_guia_repo(guia, capsys):
    code, rep = run(capsys, "repo", "repo")
    assert code == 0 and rep["summary"]["languages"][0][0] == "Python"
    langs = _ev(capsys, "repo_languages")
    assert [c["language"] for c in langs["code"]] == ["Python"] and {"Markdown", "TOML"} <= set(langs["other"])
    py = _ev(capsys, "repo_manifests")["manifests"]["pyproject.toml"]
    assert py["name"] == "notas" and py["requires_python"] == ">=3.10" and py["scripts"] == {"notas": "notas.cli:main"}
    assert _ev(capsys, "repo_quality")["tests"]["files"] == 1
    assert any("pip install -e ." in h for h in rep["summary"]["how_to_run"])
    code, inc = run(capsys, "incognitas")
    assert any(i["question"].startswith("Sin licencia detectada") for i in inc)


@pytest.mark.skipif(shutil.which("node") is None, reason="la verificación del proyecto estático usa node --test")
def test_guia_create(guia, capsys):
    code, rep = run(capsys, "create", "--from", "sitio", "--out", "nuevo", "--name", "Notas nuevo")
    assert code == 0 and rep["target"] == "static" and rep["verification"]["ok"] is True
    spec = json.loads((guia / "nuevo" / "eolfi.spec.json").read_text(encoding="utf-8"))
    assert spec["pages"] == ["home", "acerca"]
    assert spec["design"]["palette"]["background"] == "#fdfcf8" and spec["design"]["palette"]["text"] == "#222"
    assert spec["design"]["font"] == "system-ui"
    assert spec["api"]["observed_endpoints"] == ["/api/notas"] and spec["features"] == ["fetch", "localStorage"]
    # Lo que la guía advierte: Hero y Features se añaden por defecto; ContactForm sale del formulario observado.
    assert spec["sections"] == ["Hero", "Features", "ContactForm"]
    generado = "".join(p.read_text(encoding="utf-8") for p in (guia / "nuevo").rglob("*") if p.suffix in
                       (".html", ".js", ".css"))
    assert "localStorage.getItem('notas')" not in generado     # nada copiado de la fuente
