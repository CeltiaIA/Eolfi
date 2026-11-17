"""Telemetría local por fase (PLAN_DEFINITIVO.md, B4)."""
import json
import shutil
import subprocess

import pytest

from eolfi import cli, rsi_banco, telemetria
from eolfi.generador import llm
from eolfi.generador.assist import assist
from tests.test_assist import FakeClient, _project


def test_solo_se_guardan_valores_planos_y_cortos():
    e = telemetria.anotar("ronda", proveedor="eolas-v2", generacion_s=1.23456, ok=True, texto="x" * 500,
                          prompt=["no", "entra"], objeto={"tampoco": 1})
    assert e["generacion_s"] == 1.235 and len(e["texto"]) == 120 and "prompt" not in e and "objeto" not in e
    assert telemetria.eventos("ronda") == [e] and telemetria.eventos("muestra") == []
    assert [f.name[-6:] for f in telemetria.carpeta().iterdir()] == [".jsonl"]


def test_apagada_no_escribe_nada(monkeypatch):
    monkeypatch.setenv("EOLFI_TELEMETRIA", "0")
    assert telemetria.anotar("ronda", ok=True) is None
    assert not telemetria.carpeta().exists() and telemetria.resumen()["eventos"] == 0


def test_una_carpeta_que_no_se_puede_escribir_no_rompe_el_trabajo(monkeypatch, tmp_path):
    bloqueo = tmp_path / "es-un-archivo"
    bloqueo.write_text("x", encoding="utf-8")
    monkeypatch.setenv("EOLFI_TELEMETRIA_DIR", str(bloqueo))
    assert telemetria.anotar("ronda", ok=True) is None


def test_assist_anota_cada_ronda_sin_contenido(tmp_path, monkeypatch):
    if not shutil.which("node"):
        pytest.skip("requiere Node.js")
    monkeypatch.setenv("EOLFI_SEMILLA", "5")
    out = _project(tmp_path)
    html = (out / "index.html").read_text(encoding="utf-8")
    roto = {"summary": "SECRETO-DEL-RESUMEN", "notes": [], "files": [
        {"path": "index.html", "content": html.replace("</main>", "<h1>SECRETO-DEL-CODIGO</h1></main>")}]}
    bien = {"summary": "ok", "notes": [], "files": [{"path": "index.html", "content": html.replace("</main>", "<p>x</p></main>")}]}
    cliente = FakeClient([roto, bien])
    cliente.last_server_timings = {"predicted_per_second": 9.5, "prompt_per_second": 700.0}
    assert assist(out, "ENCARGO-SECRETO", provider=cliente)["ok"]
    r1, r2 = telemetria.eventos("ronda")
    assert (r1["ronda"], r1["ok"], r1["paso_fallido"], r1["tokens_s"], r1["semilla"]) == (1, False, "pruebas (node --test)", 9.5, 5)
    assert (r2["ronda"], r2["ok"], r2["paso_fallido"], r2["tokens_salida"], r2["proveedor"]) == (2, True, None, 200, "simulado")
    crudo = "".join(f.read_text(encoding="utf-8") for f in telemetria.carpeta().iterdir())
    assert "SECRETO" not in crudo and str(tmp_path) not in crudo and str(tmp_path).replace("\\", "\\\\") not in crudo


def test_un_corte_por_longitud_tambien_se_anota(tmp_path):
    if not shutil.which("node"):
        pytest.skip("requiere Node.js")

    class SeCorta(FakeClient):
        def complete(self, system, messages, schema, effort):
            raise llm.RespuestaCortada("se cortó por longitud")
    assert not assist(_project(tmp_path), "algo", provider=SeCorta([]))["ok"]
    assert [r["paso_fallido"] for r in telemetria.eventos("ronda")] == ["respuesta cortada por longitud"] * 3
    assert telemetria.resumen()["por_proveedor"]["simulado"]["cortes_por_longitud"] == 3


def test_el_banco_anota_cada_muestra_y_el_resumen_da_medianas(monkeypatch, capsys):
    codigos = iter([0, 6, 0])

    def run(cmd, **kw):
        if "create" in cmd:
            return subprocess.CompletedProcess(cmd, next(codigos), "", "")
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"tareas": {"passed": 9, "total": 9}}), "")
    monkeypatch.setattr(rsi_banco.subprocess, "run", run)
    monkeypatch.setattr(rsi_banco.shutil, "which", lambda name: "node")
    banco = rsi_banco.banco_tareas(proveedor="eolas-v2")
    assert [banco(i) for i in range(3)] == [1.0, 0.0, 1.0]
    ms = telemetria.eventos("muestra")
    assert [(m["semilla"], m["puntuacion"], m["exit"]) for m in ms] == [(0, 1.0, 0), (1, 0.0, 6), (2, 1.0, 0)]
    telemetria.anotar("ronda", proveedor="eolas-v2", generacion_s=100.0, verificacion_s=4.0, tokens_s=10.0, ok=True,
                      juez_superadas=9, juez_total=10)
    telemetria.anotar("ronda", proveedor="eolas-v2", generacion_s=300.0, verificacion_s=6.0, tokens_s=8.0, ok=False,
                      juez_superadas=5, juez_total=10)
    r = telemetria.resumen()
    b = r["bancos"]["tareas · eolas-v2"]
    assert (b["muestras"], b["media"], b["sin_entrega"]) == (3, 0.667, 1) and b["desviacion"] == 0.577
    p = r["por_proveedor"]["eolas-v2"]
    assert (p["rondas"], p["rondas_en_verde"], p["generacion_s_p50"], p["tokens_s_p50"], p["juez_media"]) == (2, 1, 200.0, 9.0, 0.7)
    assert cli.main(["telemetria"]) == 0 and "por_proveedor" in capsys.readouterr().out
    assert cli.main(["telemetria", "ruta"]) == 0
