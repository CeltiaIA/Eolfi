"""Mejor intento puntuado por el juez (PLAN_DEFINITIVO.md, B6): el bucle repara desde la mejor versión y, si no llega
al verde, la conserva marcada como parcial."""
import json
import shutil
import subprocess

import pytest

from eolfi import rsi_banco, telemetria
from eolfi.generador import juez
from eolfi.generador.assist import assist
from tests.test_assist import FakeClient, _project
from tests.test_juez import CRITERIOS

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="requiere Node.js")


def _proyecto(tmp_path, monkeypatch, notas):
    """Proyecto estático con criterios; el juez devuelve, en orden, las notas dadas (k de 6)."""
    out = _project(tmp_path)
    f = tmp_path / "criterios.json"
    f.write_text(json.dumps(CRITERIOS), encoding="utf-8")
    juez.instalar(out, f)
    cola = iter(notas)

    def juzgar(*_a, **_k):
        n = next(cola)
        return {"status": "ok", "total": 6, "ejecutadas": 6, "seconds": 0, "passed": n,
                "checks": [{"nombre": f"falta-{n}", "ok": False}] if n < 6 else []}
    monkeypatch.setattr(juez, "juzgar", juzgar)
    return out


def _cambio(out, marca):
    html = (out / "index.html").read_text(encoding="utf-8").split("<!--v")[0]
    base = html if "</main>" in html else (out / "index.html").read_text(encoding="utf-8")
    return {"summary": marca, "notes": [], "files": [
        {"path": "index.html", "content": base.replace("</main>", f"<p>{marca}</p></main>")}]}


def test_sin_verde_se_conserva_el_mejor_intento_marcado_como_parcial(tmp_path, monkeypatch):
    out = _proyecto(tmp_path, monkeypatch, [2, 5, 3])
    original = (out / "index.html").read_text(encoding="utf-8")
    cliente = FakeClient([_cambio(out, "uno"), _cambio(out, "dos"), _cambio(out, "tres")])
    r = assist(out, "Implementa la lista", provider=cliente)
    assert (r["ok"], r["parcial"], r["restored"]) == (False, True, False)
    assert r["mejor_intento"] == {"ronda": 2, "juez": "5/6", "nota": 0.8333}
    # best_attempt describe la misma ronda que se conserva, y sus hashes son los del disco (B6 real, 20/11).
    assert r["best_attempt"]["round"] == 2 and r["rounds"][1].get("best_attempt") is True
    import hashlib
    assert r["best_attempt"]["files"] == [{"path": "index.html",
                                           "sha256": hashlib.sha256((out / "index.html").read_bytes()).hexdigest()}]
    final = (out / "index.html").read_text(encoding="utf-8")
    assert "<p>dos</p>" in final and "<p>tres</p>" not in final and final != original
    assert r["files_changed"] == ["index.html"]
    assert [x.get("nota") for x in r["rounds"]] == [0.3333, 0.8333, 0.5]
    assert r["rounds"][2]["volvio_a_ronda"] == 2 and "volvio_a_ronda" not in r["rounds"][1]


def test_una_ronda_que_empeora_no_se_queda_y_el_modelo_lo_sabe(tmp_path, monkeypatch):
    out = _proyecto(tmp_path, monkeypatch, [5, 3, 6])
    vistos = []

    class Cliente(FakeClient):
        def complete(self, system, messages, schema, effort):
            vistos.append((out / "index.html").read_text(encoding="utf-8"))
            return super().complete(system, messages, schema, effort)
    cliente = Cliente([_cambio(out, "uno"), _cambio(out, "dos"), _cambio(out, "tres")])
    r = assist(out, "Implementa la lista", provider=cliente)
    assert r["ok"] and not r["parcial"] and len(r["rounds"]) == 3
    assert "<p>uno</p>" in vistos[2] and "<p>dos</p>" not in vistos[2]      # antes de la ronda 3, la versión buena
    aviso = cliente.calls[2]["messages"][-1]["content"]
    assert "EMPEORÓ" in aviso and "ronda 1" in aviso and "superaba 5/6" in aviso and "falta-5" in aviso
    assert "EMPEORÓ" not in cliente.calls[1]["messages"][-1]["content"]


def test_si_deja_de_pasar_las_pruebas_tambien_se_vuelve_a_la_mejor(tmp_path, monkeypatch):
    out = _proyecto(tmp_path, monkeypatch, [4])
    html = (out / "index.html").read_text(encoding="utf-8")
    rompe = {"summary": "rompe", "notes": [], "files": [
        {"path": "index.html", "content": html.replace("</main>", "<h1>otro h1</h1></main>")},
        {"path": "nueva.html", "content": "<p>x</p>"}]}
    cliente = FakeClient([_cambio(out, "uno"), rompe, rompe])
    r = assist(out, "Implementa la lista", provider=cliente)
    assert r["parcial"] and r["mejor_intento"]["ronda"] == 1
    assert r["rounds"][1]["failed_step"] == "pruebas (node --test)" and r["rounds"][1]["volvio_a_ronda"] == 1
    assert "<p>uno</p>" in (out / "index.html").read_text(encoding="utf-8")
    assert not (out / "nueva.html").exists()                                  # lo creado después de la foto se va
    assert r["files_changed"] == ["index.html"]


def test_un_intento_que_no_supera_nada_no_se_conserva(tmp_path, monkeypatch):
    out = _proyecto(tmp_path, monkeypatch, [0, 0, 0])
    original = (out / "index.html").read_text(encoding="utf-8")
    r = assist(out, "algo", provider=FakeClient([_cambio(out, "a"), _cambio(out, "b"), _cambio(out, "c")]))
    assert (r["ok"], r["parcial"], r["restored"], r["files_changed"]) == (False, False, True, [])
    assert (out / "index.html").read_text(encoding="utf-8") == original


def test_sin_juez_todo_sigue_como_antes(tmp_path):
    out = _project(tmp_path)
    original = (out / "index.html").read_text(encoding="utf-8")
    malo = {"summary": "x", "notes": [], "files": [{"path": "index.html", "content": original.replace("</main>", "<h1>otro</h1></main>")}]}
    r = assist(out, "algo", provider=FakeClient([malo] * 3))
    assert (r["ok"], r["parcial"], r["restored"]) == (False, False, True) and "mejor_intento" not in r
    assert (out / "index.html").read_text(encoding="utf-8") == original


def test_el_banco_puntua_el_intento_parcial_en_vez_de_dar_cero(monkeypatch):
    informes = iter([{"assist": {"ok": False, "parcial": True, "rounds": []}},
                     {"assist": {"ok": False, "parcial": False, "rounds": []}}])

    def run(cmd, **kw):
        if "create" in cmd:
            from pathlib import Path
            Path(cmd[cmd.index("--out") + 1]).mkdir(parents=True)
            return subprocess.CompletedProcess(cmd, 6, "progreso\n" + json.dumps(next(informes)), "AssistError: sin verde")
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"tareas": {"passed": 6, "total": 9}}), "")
    monkeypatch.setattr(rsi_banco.subprocess, "run", run)
    monkeypatch.setattr(rsi_banco.shutil, "which", lambda name: "node")
    notas = []
    banco = rsi_banco.banco_tareas(proveedor="eolas-v2", registro=notas.append)
    assert round(banco(0), 3) == 0.667 and banco(1) == 0.0
    assert (notas[0]["parcial"], notas[0]["juez"], notas[0]["exit"]) == (True, "6/9", 6)
    assert "parcial" not in notas[1] and notas[1]["error"] == "AssistError: sin verde"
    assert [m["parcial"] for m in telemetria.eventos("muestra")] == [True, False]
