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


def _cap(data, code=0, elapsed=80, truncated=False):
    return {"normalized_result": {"frames": [{"sequence": 0, "at_ms": elapsed // 2, "data": data}],
                                  "exit": {"code": code, "signal": 0, "reason": "exited"},
                                  "settlement": {"elapsed_ms": elapsed}, "truncated": truncated}}


def test_escenario_normaliza_los_tiempos():
    from eolfi import rea_compuestas as rc

    sc = rc._scenario({"ejecutable": "/usr/bin/whoami"})
    assert sc["normalization"] == {"time_bucket_ms": rc.BEHAVIOR_TIME_BUCKET_MS}


def test_comprobacion_propia_ignora_tiempos_y_ve_diferencias():
    from eolfi import rea_compuestas as rc

    # Caso real (14/11/2026): misma salida y código, distinto tiempo de cierre → REA «changed», Eolfi «igual».
    same = rc._own_check(_cap("mejil\r\n", elapsed=93), _cap("mejil\r\n", elapsed=79))
    assert (same["salida"], same["terminal"]) == ("igual", "igual")
    other = rc._own_check(_cap("mejil\r\n"), _cap("otro-usuario\r\n", code=1))
    assert (other["salida"], other["terminal"]) == ("distinto", "distinto")
    unknown = rc._own_check(_cap("mejil\r\n"), _cap("mejil\r\n", truncated=True))
    assert unknown["terminal"] == "desconocido" and unknown["salida"] == "igual"
    assert rc._own_check({}, _cap("x"))["salida"] == "desconocido"


def test_escenario_wsl_traduce_rutas_y_responde_al_cursor_de_conpty():
    from eolfi import rea_compuestas as rc

    win = rc._scenario({"ejecutable": r"C:\Windows\System32\whoami.exe", "argumentos": [r"D:\x\y.txt"],
                        "carpeta": r"D:\x"}, wsl=True)
    assert win["executable"] == "/mnt/c/Windows/System32/whoami.exe"
    assert win["arguments"] == [r"D:\x\y.txt"]                      # un .exe recibe rutas de Windows
    assert win["working_directory"] == "/mnt/d/x" and win["events"] == [rc.CURSOR_REPLY]
    lin = rc._scenario({"ejecutable": "/usr/bin/python3", "argumentos": [r"D:\rec\app.py", "--v"]}, wsl=True)
    assert lin["arguments"] == ["/mnt/d/rec/app.py", "--v"] and "events" not in lin
    assert rc._scenario({"ejecutable": r"C:\a.exe"})["executable"] == r"C:\a.exe"   # sin WSL, tal cual


def test_comprobacion_propia_quita_secuencias_de_control():
    from eolfi import rea_compuestas as rc

    conpty = ("\x1b[6n\x1b[?9001h\x1b[m\x1b]0;C:\\Windows\\System32\\whoami.exe\x07\x1b[?25h\x1b[?9001l"
              "celtia\\mejil\r\n")
    out = rc._own_check(_cap(conpty), _cap("celtia\\mejil\r\n"))
    assert out["terminal"] == "igual" and out["original"]["terminal"] == "celtia\\mejil\r\n"


def test_servidor_no_arranca_rea_de_wsl_si_falta_el_permiso(connect, monkeypatch):
    from eolfi import rea_client, server

    started = []
    monkeypatch.setattr(server.os, "name", "nt")
    monkeypatch.setattr(rea_client, "wsl_rea_command", lambda: ["wsl.exe", "x"])
    class Closable(FakeBehavior):
        def close(self):
            pass

    monkeypatch.setattr(rea_client, "ReaClient", lambda *a, **k: started.append(a) or Closable())

    class Rea:
        client = None
        authorizer = ra.Authorizer(connect, "caso-w")

    app = server.EolfiApp.__new__(server.EolfiApp)
    app._progress = lambda msg: None
    orig, rec = {"ejecutable": r"C:\Windows\System32\whoami.exe"}, {"ejecutable": "/usr/bin/python3", "argumentos": [r"D:\r\w.py"]}
    out = server.EolfiApp._verify_behavior(app, Rea, orig, rec)
    assert out["autorizacion_pendiente"] and started == []
    pend = ra.overview(connect, "caso-w")["pendientes"]
    assert {p["args"]["executable"] for p in pend} == {"/mnt/c/Windows/System32/whoami.exe", "/usr/bin/python3"}
    for p in pend:
        ra.decide(connect, p["id"], "once")
    out = server.EolfiApp._verify_behavior(app, Rea, orig, rec)
    assert out["comparacion"] == "equivalent" and len(started) == 1


class FakeLedger(FakeBehavior):
    """REA simulado que además exporta el paquete y construye el libro."""

    def __init__(self):
        super().__init__()
        self.ledger_args = None
        self.coverage_args = None

    def call(self, name, args, limit=None):
        if name == "capture_process_scenario":
            text, ok = super().call(name, args, limit)
            data = json.loads(text)
            data["normalized_result"] = {"manifest": {"executable_sha256": "a" * 64, "normalization_sha256": "b" * 64}}
            data["environment"] = {"id": "linux-x64"}
            return json.dumps(data), ok
        if name == "evaluate_reconstruction_coverage":
            self.calls.append(name)
            self.coverage_args = args
            return json.dumps({"normalized_result": {
                "boundary_id": args["boundary_id"], "status": "partial",
                "summary": {"required_surfaces": 1, "required_claims": 2, "reasons": 1},
                "reasons": [{"code": "package-proof-missing", "subject_id": "authority-independence", "detail": "x"}],
                "recommended_probes": [{"operation": "verify_reconstruction_package",
                                        "subject_id": "authority-independence", "rationale": "x"}],
                "evidence_ids": []}}), True
        if name == "verify_reconstruction":
            text, ok = super().call(name, args, limit)
            data = json.loads(text)
            data["evidence_id"] = "ev_" + "v" * 8
            return json.dumps(data), ok
        if name == "export_evidence_bundle":
            self.calls.append(name)
            Path(args["path"]).write_text(json.dumps({"records": [1, 2]}), encoding="utf-8")
            return json.dumps({"normalized_result": {"result": {"records": 2}}}), True
        if name == "build_reconstruction_obligation_ledger":
            self.calls.append(name)
            self.ledger_args = args
            ob = args["reviewed_obligations"][0]["obligation_id"]
            return json.dumps({"normalized_result": {"status": "unknown", "coverage": {"status": "complete"},
                                                     "ledger_id": "rol_x", "closure_digest": "d", "limitations": [],
                                                     "obligations": [{"obligation_id": ob, "status": "implemented",
                                                                      "diagnostics": [{"code": "verifier-unavailable",
                                                                                       "detail": "x"}]},
                                                                     {"obligation_id": "obl_otra", "status": "unknown"}]}}), True
        return super().call(name, args, limit)


def test_libro_de_obligaciones_ata_la_obligacion_al_modulo(connect, tmp_path):
    import hashlib

    from eolfi import rea_compuestas as rc

    mod = tmp_path / "rec.py"
    mod.write_text("print('x')\n", encoding="utf-8")
    a = ra.Authorizer(connect, "caso-l")
    orig = {"ejecutable": "/usr/bin/whoami"}
    rec = {"ejecutable": "python3", "argumentos": [str(mod)], "modulo": str(mod)}
    rea = FakeLedger()
    rc.verificar_comportamiento(rea, a, orig, rec)
    for p in ra.overview(connect, "caso-l")["pendientes"]:
        ra.decide(connect, p["id"], "once")
    out = rc.verificar_comportamiento(rea, a, orig, rec)
    libro = out["libro_obligaciones"]
    assert libro["estado"] == "unknown" and libro["obligacion"]["estado"] == "implemented"
    assert libro["obligacion"]["propietario_sha256"] == hashlib.sha256(mod.read_bytes()).hexdigest()
    assert libro["generadas_por_rea"]["total"] == 1 and "no fabrica" in libro["aviso"]
    binding = rea.ledger_args["manifest"]["bindings"][0]
    assert binding["original_cases"][0]["evidence_id"] == "ev_cap1"
    assert binding["fixtures"][0]["evidence_ids"] == ["ev_cap2"]
    assert binding["verifier"]["result_evidence_id"] == "ev_vvvvvvvv" and binding["verifier"]["status"] == "pass"
    assert rea.ledger_args["evidence_bundle"] == {"records": [1, 2]}
    assert rea.calls.count("export_evidence_bundle") == 1                    # un solo paquete para libro y cobertura
    # Cobertura: un contrato por dimensión, con su resumen canónico, y lo no demostrado como «unknown».
    cob = out["cobertura"]
    assert cob["estado"] == "partial" and cob["razones"] and cob["siguientes_pruebas"]
    cov = rea.coverage_args["coverage"]
    for contract in cov["verifier_contracts"]:
        base = {k: v for k, v in contract.items() if k != "contract_sha256"}
        assert contract["contract_sha256"] == hashlib.sha256(
            json.dumps(base, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert [r["covered_dimensions"] for r in cov["verifier_results"]] == [["terminal"], ["exit"]]
    assert all(r["status"] == "pass" and "ev_cap1" in r["evidence_ids"] for r in cov["verifier_results"])
    own = cov["owners"][0]["ownership"]
    assert own["owner_sha256"] == hashlib.sha256(mod.read_bytes()).hexdigest()
    assert own["authority_route"] == "unknown" and own["package_state"] == "unknown"
    assert cov["artifacts"][0]["artifact_sha256"] == "a" * 64
    # Sin «modulo» no se intenta el libro y se dice por qué.
    rec2 = dict(rec, argumentos=["otro"])
    rec2.pop("modulo")
    rc.verificar_comportamiento(rea, a, orig, rec2)
    for p in ra.overview(connect, "caso-l")["pendientes"]:
        ra.decide(connect, p["id"], "once")
    assert "no generado" in rc.verificar_comportamiento(rea, a, orig, rec2)["libro_obligaciones"]
