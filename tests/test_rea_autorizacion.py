"""Autorización por caso para las herramientas de REA que ejecutan o abren algo vivo (13/11/2026)."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from eolfi import chat, rea_autorizacion as ra, rea_client

FAKE = [sys.executable, str(Path(__file__).parent / "fixtures" / "fake_rea_mcp.py")]


@pytest.fixture
def connect(tmp_path):
    db = tmp_path / "aut.db"

    def _connect():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn
    return _connect


def test_una_vez_se_consume_y_caso_vale_solo_en_su_caso(connect):
    a = ra.Authorizer(connect, "caso-1")
    args = {"pid": 42}
    rid = a.request("start_frida_session", args)
    assert a.request("start_frida_session", args) == rid                   # la misma petición no se duplica
    assert a.allowed("start_frida_session", args) is None                   # pedir no es autorizar
    ra.decide(connect, rid, "once")
    assert a.allowed("start_frida_session", {"pid": 7}) is None              # «una vez»: solo esos argumentos
    assert a.allowed("start_frida_session", args)
    assert a.allowed("start_frida_session", args) is None                    # y una sola vez
    rid2 = a.request("capture_process_scenario", {"x": 1})
    grant = ra.decide(connect, rid2, "case")["permiso"]
    assert a.allowed("capture_process_scenario", {"x": 2}) == grant          # «caso»: cualquier argumento en el caso
    assert ra.Authorizer(connect, "caso-2").allowed("capture_process_scenario", {"x": 1}) is None
    ra.revoke(connect, grant)
    assert a.allowed("capture_process_scenario", {"x": 2}) is None
    with pytest.raises(KeyError):
        ra.revoke(connect, grant)


def test_rechazar_sin_caso_y_peticiones_ya_decididas(connect):
    a = ra.Authorizer(connect, None)
    rid = a.request("gdb_console", {"c": "run"})
    with pytest.raises(ValueError, match="caso activo"):
        ra.decide(connect, rid, "case")                                      # sin caso activo: solo «una vez»
    assert ra.decide(connect, rid, "deny")["permiso"] is None
    assert a.allowed("gdb_console", {"c": "run"}) is None
    with pytest.raises(ValueError, match="ya se decidió"):
        ra.decide(connect, rid, "once")
    with pytest.raises(ValueError):
        ra.decide(connect, rid, "siempre")
    with pytest.raises(KeyError):
        ra.decide(connect, "aut_0000000000000000", "once")
    vista = ra.overview(connect, None)
    assert vista["pendientes"] == [] and vista["permisos"] == []


def test_rea_pide_permiso_ejecuta_solo_con_el_y_lo_registra(connect):
    client = rea_client.ReaClient(FAKE, timeout=20)
    try:
        tools = rea_client.ReaTools(client, authorizer=ra.Authorizer(connect, "caso-1"))
        text, ok = tools.call_tool("rea_usar", {"nombre": "start_frida_session", "argumentos": {"pid": 1}})
        pending = json.loads(text)
        assert not ok and pending["autorizacion_pendiente"].startswith("aut_")
        assert ra.overview(connect, "caso-1")["pendientes"][0]["tool"] == "start_frida_session"
        ra.decide(connect, pending["autorizacion_pendiente"], "once")
        text, ok = tools.call_tool("rea_usar", {"nombre": "start_frida_session", "argumentos": {"pid": 1}})
        assert ok and "hecho start_frida_session" in text
        log = ra.overview(connect, "caso-1")["ejecuciones"]
        assert log[0]["tool"] == "start_frida_session" and log[0]["ok"] == 1
        again, ok = tools.call_tool("rea_usar", {"nombre": "start_frida_session", "argumentos": {"pid": 1}})
        assert not ok and "autorizacion_pendiente" in again                   # «una vez» ya se usó
    finally:
        client.close()


def test_el_chat_muestra_la_peticion_y_el_modelo_no_puede_autorizarse(connect):
    assert chat._links('{"autorizacion_pendiente": "aut_1", "herramienta": "gdb_console"}') == {
        "autorizacion": "aut_1", "herramienta_pedida": "gdb_console"}
    names = set(chat.APP_TOOLS) | set(chat.CHAT_TOOLS) | set(rea_client.META_TOOLS)
    assert not any("autoriz" in n or "permiso" in n for n in names)          # ninguna herramienta para aprobar


def test_api_del_panel_decide_y_revoca(tmp_path):
    from eolfi import server

    app = server.EolfiApp(str(tmp_path / "s.db"))
    rid = ra.Authorizer(app._rea_db, None).request("start_frida_session", {"pid": 3})
    assert app.rea_authorizations({})["pendientes"][0]["id"] == rid
    with pytest.raises(server.ApiError) as e:
        app.rea_decide(rid, {"decision": "case"})
    assert e.value.status == 400
    grant = app.rea_decide(rid, {"decision": "once"})["permiso"]
    assert app.rea_revoke(grant)["revocado"]
    with pytest.raises(server.ApiError) as e:
        app.rea_revoke(grant)
    assert e.value.status == 404


class FakeBehavior:
    def __init__(self):
        self.calls = []

    def call(self, name, args, limit=None):
        self.calls.append(name)
        if name == "capture_process_scenario":
            return json.dumps({"evidence_id": f"ev_cap{self.calls.count(name)}", "normalized_result": {}}), True
        if name == "compare_process_captures":
            return json.dumps({"evidence_id": "ev_pc", "normalized_result": {"status": "equivalent"}}), True
        if name == "verify_reconstruction":
            claims = args["specification"]["claims"]
            assert {c["kind"] for c in claims} == {"behavioral"} and all(c["comparison_evidence_id"] == "ev_pc" for c in claims)
            return json.dumps({"normalized_result": {"status": "pass", "claims": {"items": [
                {"claim_id": c["claim_id"], "dimension": c["dimension"], "status": "pass"} for c in claims]}}}), True
        raise AssertionError(name)


def test_verificar_comportamiento_no_ejecuta_nada_sin_los_dos_permisos(connect):
    from eolfi import rea_compuestas as rc

    a = ra.Authorizer(connect, "caso-1")
    orig = {"ejecutable": "C:/m/app.exe", "argumentos": ["--version"]}
    rec = {"ejecutable": "python", "argumentos": ["app.py", "--version"]}
    rea = FakeBehavior()
    out = rc.verificar_comportamiento(rea, a, orig, rec)
    assert set(out["peticiones"]) == {"original", "reconstruccion"} and rea.calls == []      # nada ejecutado
    first = ra.overview(connect, "caso-1")["pendientes"]
    once = next(p["id"] for p in first if p["args"]["executable"] == "C:/m/app.exe")
    ra.decide(connect, once, "once")
    out = rc.verificar_comportamiento(rea, a, orig, rec)
    assert list(out["peticiones"]) == ["reconstruccion"] and rea.calls == []
    assert a.peek("capture_process_scenario", rc._scenario(orig))                           # el «una vez» sigue intacto
    other = next(p["id"] for p in ra.overview(connect, "caso-1")["pendientes"])
    ra.decide(connect, other, "case")
    out = rc.verificar_comportamiento(rea, a, orig, rec)
    assert out["verificacion"]["estado"] == "pass" and out["comparacion"] == "equivalent"
    assert rea.calls.count("capture_process_scenario") == 2 and "NO" not in out["aviso"]
    assert len(ra.overview(connect, "caso-1")["ejecuciones"]) == 2                          # las dos quedan registradas
    with pytest.raises(RuntimeError):
        rc.verificar_comportamiento(rea, None, orig, rec)                                   # sin autorizador, nunca
