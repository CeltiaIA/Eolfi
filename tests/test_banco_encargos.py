"""Encargos del banco del RSI (PLAN_DEFINITIVO.md, B5): cada juez aprueba una app de referencia correcta, suspende
la que no hace nada y caza el fallo que los criterios visibles no ven."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from eolfi import rsi_banco
from eolfi.generador import juez

con_navegador = pytest.mark.skipif(not shutil.which("node") or juez._playwright() is None,
                                   reason="requiere Node.js y playwright-core")
CABECERA = '<!doctype html><html lang="es"><meta charset="utf-8"><title>t</title><main><h1>App</h1>'
CONTADOR_HTML = (CABECERA + '<p id="valor">0</p><button id="menos">Restar</button><button id="mas">Sumar</button>'
                 '<button id="reiniciar">Reiniciar</button></main><script src="app.js"></script></html>')
CONTADOR_JS = """let n = Number(localStorage.getItem('n') || 0);
const pinta = () => { document.getElementById('valor').textContent = String(n); localStorage.setItem('n', String(n)); };
document.getElementById('mas').addEventListener('click', () => { n += 1; pinta(); });
document.getElementById('menos').addEventListener('click', () => { n = MENOS; pinta(); });
document.getElementById('reiniciar').addEventListener('click', () => { n = 0; pinta(); });
pinta();
"""
FILTRO_HTML = (CABECERA + '<label for="buscar">Buscar</label><input id="buscar" type="search"><ul id="lista">'
               + "".join(f"<li>{f}</li>" for f in ("Manzana", "Mandarina", "Pera", "Plátano", "Melón", "Sandía"))
               + '</ul><p id="cuenta">6 resultados</p></main><script src="app.js"></script></html>')
FILTRO_JS = """const norma = (s) => NORMA;
const items = [...document.querySelectorAll('#lista li')];
const filtra = () => { const q = norma(document.getElementById('buscar').value); let n = 0;
  for (const li of items) { const ve = norma(li.textContent).includes(q); li.hidden = !ve; if (ve) n += 1; }
  document.getElementById('cuenta').textContent = n + ' resultados'; };
document.getElementById('buscar').addEventListener('input', filtra);
filtra();
"""
SIN_ACENTOS = "s.toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g, '')"


def _app(d: Path, html: str, js: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(html, encoding="utf-8")
    (d / "app.js").write_text(js, encoding="utf-8")
    return d


def _nota(nombre: str, archivo: str, proyecto: Path) -> tuple[int, int, list[str]]:
    e = rsi_banco.encargo(nombre)
    j = juez.juzgar(proyecto, juez.validar(json.loads(Path(e[archivo]).read_text(encoding="utf-8"))))
    assert j["status"] == "ok", j
    return j["passed"], j["total"], [c["nombre"] for c in j["checks"] if not c["ok"]]


def test_cada_encargo_tiene_sus_archivos_y_el_juez_comprueba_mas_que_los_criterios():
    assert rsi_banco.ENCARGOS == ("tareas", "contador", "filtro") and rsi_banco.BANCOS[-1] == "todos"
    for nombre in ("contador", "filtro"):
        e = rsi_banco.encargo(nombre)
        assert (e["fuente"] / "index.html").is_file() and len(e["texto"]) > 80
        visibles, ocultos = (sum(1 for p in juez.validar(json.loads(Path(e[k]).read_text(encoding="utf-8")))["pasos"]
                                 if "comprobar" in p) for k in ("criterios", "juez"))
        assert ocultos > visibles >= 4
    with pytest.raises(ValueError):
        rsi_banco.encargo("inexistente")
    with pytest.raises(ValueError):
        rsi_banco.banco("inexistente", proveedor="eolas-v2")


@con_navegador
def test_contador_referencia_aprueba_y_el_juez_caza_los_negativos(tmp_path):
    bien = _app(tmp_path / "bien", CONTADOR_HTML, CONTADOR_JS.replace("MENOS", "Math.max(0, n - 1)"))
    assert _nota("contador", "criterios", bien)[:2] == (4, 4) and _nota("contador", "juez", bien)[:2] == (8, 8)
    negativo = _app(tmp_path / "negativo", CONTADOR_HTML, CONTADOR_JS.replace("MENOS", "n - 1"))
    assert _nota("contador", "criterios", negativo)[:2] == (4, 4)            # los criterios visibles no lo ven
    superadas, total, fallos = _nota("contador", "juez", negativo)
    assert superadas < total and "no baja de 0" in fallos
    vacio = _app(tmp_path / "vacio", CONTADOR_HTML, "")
    assert _nota("contador", "juez", vacio)[0] == 1                           # sin lógica, casi nada pasa


@con_navegador
def test_filtro_referencia_aprueba_y_el_juez_caza_los_acentos(tmp_path):
    bien = _app(tmp_path / "bien", FILTRO_HTML, FILTRO_JS.replace("NORMA", SIN_ACENTOS))
    assert _nota("filtro", "criterios", bien)[:2] == (5, 5) and _nota("filtro", "juez", bien)[:2] == (10, 10)
    con_acentos = _app(tmp_path / "acentos", FILTRO_HTML, FILTRO_JS.replace("NORMA", "s.toLowerCase()"))
    assert _nota("filtro", "criterios", con_acentos)[:2] == (5, 5)
    superadas, total, fallos = _nota("filtro", "juez", con_acentos)
    assert superadas < total and "no distingue acentos" in fallos
    vacio = _app(tmp_path / "vacio", FILTRO_HTML, "")
    assert _nota("filtro", "juez", vacio)[0] <= 4


def test_el_banco_todos_reparte_los_encargos_por_semilla(monkeypatch):
    vistos = []

    def run(cmd, **kw):
        vistos.append(cmd)
        return subprocess.CompletedProcess(cmd, 6, "", "AssistError: sin verde")
    monkeypatch.setattr(rsi_banco.subprocess, "run", run)
    notas = []
    banco = rsi_banco.banco("todos", proveedor="eolas-v2", registro=notas.append)
    assert [banco(i) for i in range(4)] == [0.0] * 4
    assert [n["banco"] for n in notas] == ["tareas", "contador", "filtro", "tareas"]
    for cmd, nombre in zip(vistos, ("tareas", "contador", "filtro")):
        e = rsi_banco.encargo(nombre)
        assert cmd[cmd.index("--from") + 1] == str(e["fuente"]) and cmd[cmd.index("--juez") + 1] == str(e["criterios"])
        assert cmd[cmd.index("--ai") + 1] == e["texto"] and "juez.json" not in " ".join(cmd)   # el evaluador no se entrega


def test_un_encargo_nuevo_se_puntua_con_su_juez_oculto(monkeypatch, tmp_path):
    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(rsi_banco.subprocess, "run", run)
    pedido = {}

    def juzgar(proyecto, criterios, **kw):
        pedido["comprobaciones"] = sum(1 for p in criterios["pasos"] if "comprobar" in p)
        return {"status": "ok", "passed": 6, "total": 8}
    monkeypatch.setattr(juez, "juzgar", juzgar)
    notas = []
    assert rsi_banco.banco("contador", proveedor="eolas-v2", registro=notas.append)(1) == 0.75
    assert pedido["comprobaciones"] == 8 and notas[0]["juez"] == "6/8" and notas[0]["banco"] == "contador"
    monkeypatch.setattr(juez, "juzgar", lambda *a, **k: {"status": "unavailable", "error": "sin navegador"})
    with pytest.raises(RuntimeError, match="no pudo ejecutarse"):
        rsi_banco.banco("contador", proveedor="eolas-v2")(1)
