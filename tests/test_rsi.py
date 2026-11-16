"""Automejora recursiva (RSI) acotada: registro, superficies, propuestas, evaluación, decisión y reversión."""
import json

import pytest

from eolfi import eolas_v2, rsi

BASE = eolas_v2.DEFAULT_CONFIG["max_tokens"]


@pytest.fixture(autouse=True)
def aislado(tmp_path, monkeypatch):
    monkeypatch.setenv("EOLFI_RSI_DIR", str(tmp_path / "rsi"))
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(tmp_path / "eolas-v2.json"))
    monkeypatch.delenv("EOLFI_RSI", raising=False)
    monkeypatch.setattr(eolas_v2, "_server_default", lambda: "llama-server.exe")
    return tmp_path


def _cortes(n=2):
    for _ in range(n):
        rsi.observar("generador", "assist", {"ok": False, "error": "La respuesta de Eolas V2 se cortó por longitud"},
                     contexto={"proveedor": "eolas-v2"})


def test_observar_guarda_sintomas_y_caso_de_regresion_sin_contenido():
    ev = rsi.observar("generador", "assist", {"ok": False, "error": "JSON inválido en la respuesta: Unterminated string",
                                               "codigo": "secreto del objetivo"}, contexto={"proveedor": "eolas-v2"})
    assert ev["datos"]["sintomas"] == ["salida_cortada"] and ev["datos"]["ok"] is False
    assert "secreto" not in json.dumps(rsi.eventos()) and len(rsi.casos()) == 1
    rsi.observar("generador", "assist", {"ok": False, "error": "se cortó por longitud"}, contexto={"proveedor": "eolas-v2"})
    assert len(rsi.casos()) == 1          # misma huella: el banco no se duplica
    assert rsi.observar("rea", "explicar_binario", {"ok": True})["datos"]["sintomas"] == []


def test_registro_encadenado_detecta_manipulacion(aislado):
    _cortes(3)
    assert rsi.verificar_registro() == {"ok": True, "eventos": 3}
    path = aislado / "rsi" / "registro.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace('"ok":false', '"ok":true')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert rsi.verificar_registro() == {"ok": False, "roto_en": 2, "eventos": 1}


def test_propone_solo_con_repeticion_y_una_vez_por_regla():
    _cortes(1)
    assert rsi.proponer() == []
    _cortes(1)
    nuevas = rsi.proponer()
    assert [(p["regla"], p["superficie"], p["actual"], p["propuesto"]) for p in nuevas] == [
        ("salida_cortada_v2", "eolas_v2.max_tokens", BASE, 2 * BASE)]
    _cortes(2)
    assert rsi.proponer() == []           # ya hay una abierta


def test_superficies_cerradas_y_validadas():
    with pytest.raises(rsi.RSIError):
        rsi.validar("rea.autorizaciones", 1)
    with pytest.raises(rsi.RSIError):
        rsi.validar("eolas_v2.max_tokens", 10)
    with pytest.raises(rsi.RSIError):
        rsi.validar("eolas_v2.perfil.inexistente.ctx", 4096)
    assert rsi.validar("eolas_v2.perfil.gemma_q4.gpu_layers", 40) == 40


def test_evaluar_restaura_y_exige_mejora_y_muestras():
    _cortes(2)
    pid = rsi.proponer()[0]["id"]
    with pytest.raises(rsi.RSIError):
        rsi.evaluar(pid, lambda: 1.0, muestras=1)
    vistos = []

    def banco():
        tokens = eolas_v2.load_config()["max_tokens"]
        vistos.append(tokens)
        return 1.0 if tokens > BASE else 0.5
    r = rsi.evaluar(pid, banco)
    assert r["aprobada"] and r["media_base"] == 0.5 and r["media_candidata"] == 1.0
    assert vistos == [BASE] * 3 + [2 * BASE] * 3
    assert eolas_v2.load_config()["max_tokens"] == BASE          # restaurado
    assert rsi.propuestas()[0]["estado"] == "evaluada"


def test_evaluacion_sin_mejora_suspende_y_no_se_puede_aprobar():
    _cortes(2)
    pid = rsi.proponer()[0]["id"]
    assert rsi.evaluar(pid, lambda: 0.8)["aprobada"] is False
    with pytest.raises(rsi.RSIError):
        rsi.decidir(pid, "aprobar", por="titular")


def test_aprobar_aplica_y_revertir_restaura_con_registro():
    _cortes(2)
    pid = rsi.proponer()[0]["id"]
    with pytest.raises(rsi.RSIError):
        rsi.decidir(pid, "aprobar", por="titular")              # sin evaluar
    rsi.evaluar(pid, lambda: 1.0 if eolas_v2.load_config()["max_tokens"] > BASE else 0.0)
    with pytest.raises(rsi.RSIError):
        rsi.decidir(pid, "aprobar", por=" ")
    assert rsi.decidir(pid, "aprobar", por="titular")["nuevo"] == 2 * BASE
    assert eolas_v2.load_config()["max_tokens"] == 2 * BASE
    assert rsi.revertir(pid, por="titular")["restaurado"] == BASE
    assert eolas_v2.load_config()["max_tokens"] == BASE
    assert [e["tipo"] for e in rsi.eventos()][-4:] == ["evaluacion", "decision", "aplicacion", "reversion"]
    assert rsi.verificar_registro()["ok"]


def test_meta_sube_el_umbral_de_una_regla_que_nunca_se_adopta():
    for _ in range(3):
        _cortes(rsi.umbral("salida_cortada_v2"))
        pid = rsi.proponer()[0]["id"]
        rsi.decidir(pid, "rechazar", por="titular")
    assert rsi.umbral("salida_cortada_v2") == 3
    assert rsi.eventos("meta")[-1]["datos"]["umbral"] == 3
    _cortes(2)
    assert rsi.proponer() == []                                   # ahora pide 3
    _cortes(1)
    assert rsi.proponer()[0]["regla"] == "salida_cortada_v2"


def test_rea_plazo_es_ajuste_propio(aislado):
    for _ in range(2):
        rsi.observar("rea", "explicar_binario", "RuntimeError: REA no respondió a tools/call en 900 s")
    p = rsi.proponer()[0]
    assert (p["superficie"], p["actual"], p["propuesto"]) == ("rea.timeout", 900, 1800)
    rsi.evaluar(p["id"], lambda: 1.0 if rsi.ajuste("rea.timeout") > 900 else 0.0)
    rsi.decidir(p["id"], "aprobar", por="titular")
    assert rsi.ajuste("rea.timeout") == 1800


def test_apagado_no_anota_nada(monkeypatch):
    monkeypatch.setenv("EOLFI_RSI", "0")
    assert rsi.observar("rea", "x", "REA no respondió a a en 1 s") is None
    assert rsi.proponer() == [] and rsi.eventos() == []


def test_cli_rea_anota_el_plazo_agotado_y_usa_el_ajuste(tmp_path, monkeypatch):
    from eolfi import cli, rea_client

    vistos = []

    class Lento:
        def __init__(self, command=None, *, timeout=300.0):
            vistos.append(timeout)

        def close(self):
            pass

    def inventario(client, ruta):
        raise RuntimeError("REA no respondió a tools/call en 900 s")

    monkeypatch.setattr(rea_client, "ReaClient", Lento)
    monkeypatch.setattr("eolfi.rea_compuestas.inventario_dependencias", inventario)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            cli.main(["--db", str(tmp_path / "e.db"), "rea", "inventario", str(tmp_path / "x.exe")])
    assert vistos == [900, 900]
    obs = rsi.eventos("observacion")
    assert [(e["datos"]["fuente"], e["datos"]["operacion"], e["datos"]["sintomas"]) for e in obs] == [
        ("rea", "inventario", ["rea_tiempo_agotado"])] * 2
    assert cli.main(["rsi", "proponer"]) == 0
    pid = rsi.propuestas()[0]["id"]
    assert cli.main(["rsi", "aprobar", pid, "--por", "titular"]) == 2      # sin evaluar
    rsi.evaluar(pid, lambda: 1.0 if rsi.ajuste("rea.timeout") > 900 else 0.0)
    assert cli.main(["rsi", "aprobar", pid, "--por", "titular"]) == 0
    with pytest.raises(RuntimeError):
        cli.main(["--db", str(tmp_path / "e.db"), "rea", "inventario", str(tmp_path / "x.exe")])
    assert vistos[-1] == 1800
    assert cli.main(["rsi", "verificar"]) == 0


def test_cli_create_ai_anota_la_salida_cortada(tmp_path, monkeypatch):
    from eolfi import cli
    from eolfi.generador.llm import LLMError

    def corta(*a, **k):
        raise LLMError("La respuesta de Eolas V2 se cortó por longitud; revisa ctx/max_tokens")

    monkeypatch.setattr("eolfi.flows.create_flow.create_project", corta)
    with pytest.raises(LLMError):
        cli.main(["--db", str(tmp_path / "e.db"), "create", "--from", str(tmp_path), "--out", str(tmp_path / "o"),
                  "--target", "static", "--ai", "algo", "--provider", "eolas-v2"])
    d = rsi.eventos("observacion")[-1]["datos"]
    assert (d["fuente"], d["sintomas"], d["contexto"]["proveedor"]) == ("generador", ["salida_cortada"], "eolas-v2")


def test_banco_tareas_puntua_con_el_juez_y_limpia(monkeypatch):
    import subprocess
    from pathlib import Path

    from eolfi import rsi_banco

    llamadas, carpetas = [], []

    def run(cmd, **kw):
        llamadas.append(cmd)
        if "create" in cmd:
            out = Path(cmd[cmd.index("--out") + 1])
            carpetas.append(out.parent)
            return subprocess.CompletedProcess(cmd, 0 if len(llamadas) == 1 else 6, "", "")
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"tareas": {"passed": 6, "total": 8}}), "")

    monkeypatch.setattr(rsi_banco.subprocess, "run", run)
    monkeypatch.setattr(rsi_banco.shutil, "which", lambda name: "node")
    notas = []
    banco = rsi_banco.banco_tareas(proveedor="eolas-v2", registro=notas.append)
    assert banco() == 0.75
    assert banco() == 0.0                      # create falla: 0 sin juez
    create = llamadas[0]
    assert create[create.index("--provider") + 1] == "eolas-v2" and "--ai" in create
    assert [n.get("juez") or n.get("exit") for n in notas] == ["6/8", 6]
    assert all(not c.exists() for c in carpetas)
    assert rsi_banco.FUENTE.joinpath("index.html").is_file() and rsi_banco.JUEZ.is_file()
