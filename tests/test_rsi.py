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


def test_dos_arranques_agotados_proponen_evaluar_el_plazo_sin_aplicarlo():
    for _ in range(2):
        rsi.observar("eolas-v2", "arranque", {"ok": False, "error": "Eolas no publicó health y el modelo gemma"})
    p, = rsi.proponer()
    assert (p["superficie"], p["actual"], p["propuesto"]) == ("eolas_v2.ready_timeout", 300, 600)
    assert eolas_v2.load_config()["ready_timeout"] == 300
    with pytest.raises(rsi.RSIError):
        rsi.validar(p["superficie"], 7201)


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
    assert vistos == [BASE, 2 * BASE] * rsi.MUESTRAS_MINIMAS          # pares alternados
    assert r["p_valor"] < 0.05 and r["ic95"][0] > 0
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
    for _ in range(2):   # el error de REA se muestra sin traza (código 1) y el RSI lo anota igual
        assert cli.main(["--db", str(tmp_path / "e.db"), "rea", "inventario", str(tmp_path / "x.exe")]) == 1
    assert vistos == [900, 900]
    obs = rsi.eventos("observacion")
    assert [(e["datos"]["fuente"], e["datos"]["operacion"], e["datos"]["sintomas"]) for e in obs] == [
        ("rea", "inventario", ["rea_tiempo_agotado"])] * 2
    assert cli.main(["rsi", "proponer"]) == 0
    pid = rsi.propuestas()[0]["id"]
    assert cli.main(["rsi", "aprobar", pid, "--por", "titular"]) == 2      # sin evaluar
    rsi.evaluar(pid, lambda: 1.0 if rsi.ajuste("rea.timeout") > 900 else 0.0)
    assert cli.main(["rsi", "aprobar", pid, "--por", "titular"]) == 0
    assert cli.main(["--db", str(tmp_path / "e.db"), "rea", "inventario", str(tmp_path / "x.exe")]) == 1
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


def test_leccion_desactivada_que_sigue_fallando_se_propone_reactivar():
    eolas_v2.record_lessons("gemma_q4", ["NameError: name 'x' is not defined"])
    eolas_v2.set_lesson_active("gemma_q4", "nombre", False)
    sup = "eolas_v2.leccion.gemma_q4.nombre"
    assert rsi._leer(sup) is False
    with pytest.raises(rsi.RSIError):
        rsi.validar(sup, "si")                                  # solo verdadero/falso
    with pytest.raises(rsi.RSIError):
        rsi.validar("eolas_v2.leccion.gemma_q4.inventada", True)
    for _ in range(2):                                          # el motor vuelve a fallar por la misma causa
        eolas_v2.record_lessons("gemma_q4", ["NameError: name 'y' is not defined"])
    obs = rsi.eventos("observacion")
    assert obs[-1]["datos"]["sintomas"] == ["leccion_inactiva"] and obs[-1]["datos"]["contexto"]["categoria"] == "nombre"
    prop = rsi.proponer()
    assert [(p["regla"], p["superficie"], p["actual"], p["propuesto"]) for p in prop] == [
        ("reactivar_leccion", sup, False, True)]
    rsi.evaluar(prop[0]["id"], lambda: 1.0 if rsi._leer(sup) else 0.0)
    assert rsi._leer(sup) is False                              # la evaluación restaura
    rsi.decidir(prop[0]["id"], "aprobar", por="titular")
    assert eolas_v2.active_lessons("gemma_q4")
    rsi.revertir(prop[0]["id"], por="titular")
    assert rsi._leer(sup) is False and not eolas_v2.active_lessons("gemma_q4")


def test_panel_muestra_y_decide_y_un_cliente_no_puede_aprobar(tmp_path):
    import http.client
    import threading

    from eolfi.server import make_server

    _cortes(2)
    httpd = make_server(str(tmp_path / "s.db"), "127.0.0.1", 0, tmp_path / "samples")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    def req(method, path, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        c.request(method, path, body="{}" if method == "POST" else None, headers={"X-Eolfi": "1", **(headers or {})})
        r = c.getresponse()
        data = json.loads(r.read())
        c.close()
        return r.status, data
    try:
        st, d = req("POST", "/api/rsi/proponer")
        pid = d["nuevas"][0]["id"]
        st, d = req("GET", "/api/rsi")
        assert st == 200 and d["registro"]["ok"] and d["propuestas"][0]["estado"] == "pendiente"
        assert req("POST", f"/api/rsi/propuestas/{pid}/aprobar")[0] == 400           # sin evaluar
        rsi.evaluar(pid, lambda: 1.0 if eolas_v2.load_config()["max_tokens"] > BASE else 0.0)
        assert req("POST", f"/api/rsi/propuestas/{pid}/aprobar", {"X-Eolfi-Client": "vscode"})[0] in (401, 403)
        st, d = req("POST", f"/api/rsi/propuestas/{pid}/aprobar")
        assert st == 200 and eolas_v2.load_config()["max_tokens"] == 2 * BASE
        assert [e for e in rsi.eventos("decision")][-1]["datos"]["por"] == "titular (panel)"
        assert req("POST", f"/api/rsi/propuestas/{pid}/revertir")[0] == 200
        assert eolas_v2.load_config()["max_tokens"] == BASE
        assert req("POST", "/api/rsi/propuestas/000000000000/rechazar")[0] == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_las_herramientas_rea_del_chat_se_observan(tmp_path):
    from eolfi import server
    from tests.test_rea_compuestas import FakeRea

    app = server.EolfiApp(str(tmp_path / "r.db"))
    app.roots = [tmp_path]

    class Tools:
        client = FakeRea(fail_on="inspect_model_artifact")

    tools = app._chat_rea_composites(Tools())
    with pytest.raises(RuntimeError):
        tools["eolfi_revisar_modelo"]({"ruta": str(tmp_path / "m-Q5_K_M.gguf")})
    Tools.client.fail_on = None
    tools["eolfi_revisar_modelo"]({"ruta": str(tmp_path / "m-Q5_K_M.gguf")})
    obs = [e["datos"] for e in rsi.eventos("observacion")]
    assert [(o["fuente"], o["operacion"], o["ok"]) for o in obs] == [
        ("chat", "revisar_modelo", False), ("chat", "revisar_modelo", True)]


def test_comparar_exige_significacion_y_no_aprueba_con_pocos_pares():
    assert rsi.comparar([0.5] * 5, [1.0] * 5)["aprobada"]                  # p = 1/32
    assert not rsi.comparar([0.5] * 4, [1.0] * 4)["aprobada"]              # p = 1/16: imposible con 4
    # Media mejor por 0,13 pero un par peor: el ejemplo real de 3 muestras del 16/11 no basta.
    r = rsi.comparar([7 / 9, 5 / 9, 1 / 4, 0.5, 0.5], [5 / 9, 1 / 4, 5 / 9, 1.0, 1.0])
    assert not r["aprobada"] and r["p_valor"] >= 0.05
    assert rsi.comparar([0.2] * 5, [0.22] * 5)["aprobada"] is False         # significativa pero < margen
    assert rsi.comparar([0.3, 0.4], [0.5, 0.6], semilla="x") == rsi.comparar([0.3, 0.4], [0.5, 0.6], semilla="x")
    with pytest.raises(rsi.RSIError):
        rsi.comparar([0.5], [0.5, 0.6])


def test_evaluar_pide_cinco_pares_y_pasa_la_semilla_al_banco():
    _cortes(2)
    pid = rsi.proponer()[0]["id"]
    with pytest.raises(rsi.RSIError):
        rsi.evaluar(pid, lambda: 1.0, muestras=4)
    semillas = []

    def banco(semilla):
        semillas.append(semilla)
        return 0.5
    r = rsi.evaluar(pid, banco)
    assert semillas == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4] and r["aprobada"] is False
    assert eolas_v2.load_config()["max_tokens"] == BASE


def test_evaluar_restaura_aunque_el_banco_falle():
    _cortes(2)
    pid = rsi.proponer()[0]["id"]

    def banco():
        if eolas_v2.load_config()["max_tokens"] > BASE:
            raise RuntimeError("caída del motor")
        return 0.5
    with pytest.raises(RuntimeError):
        rsi.evaluar(pid, banco)
    assert eolas_v2.load_config()["max_tokens"] == BASE
    assert rsi.propuestas()[0]["estado"] == "pendiente"


def test_aa_simulada_falsos_positivos_por_debajo_del_5_por_ciento():
    # Varianza medida en el banco «tareas» (desviación ≈ 0,3): la regla anterior aprobaba mucho por azar.
    r = rsi.calibrar_aa(desviacion=0.3, repeticiones=300, remuestreos=300)
    assert r["falsos_positivos"] <= 0.05
    assert r["falsos_positivos_regla_anterior"] > r["falsos_positivos"]


def test_prueba_aa_real_queda_en_el_registro():
    r = rsi.prueba_aa(lambda: 0.5)
    assert r["falso_positivo"] is False and len(r["a"]) == rsi.MUESTRAS_MINIMAS
    assert rsi.eventos("aa")[-1]["datos"]["falso_positivo"] is False
    assert rsi.verificar_registro()["ok"]
    with pytest.raises(rsi.RSIError):
        rsi.prueba_aa(lambda: 0.5, muestras=3)


def test_cli_aa_simulada(capsys):
    from eolfi import cli

    assert cli.main(["rsi", "aa", "--proveedor", "eolas-v2", "--simulada", "0.3"]) == 0
    assert "falsos_positivos" in capsys.readouterr().out
