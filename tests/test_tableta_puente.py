"""Puente de la tableta hacia el Eolfi en vivo en 127.0.0.1 (20/11/2026).

Las pruebas levantan un Eolfi real en 127.0.0.1 (sin token de arranque, como el panel del titular) y el puente
delante, y comprueban que solo pasa la superficie de la tableta, siempre con nivel de usuario.
"""
import json
import ssl
import threading
import time

import pytest

from eolfi import server, tableta, tableta_puente
from tests.test_server import req

X = {"X-Eolfi": "1"}


def _arrancar(httpd):
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


@pytest.fixture
def vivo(tmp_path, monkeypatch):
    monkeypatch.setenv("EOLFI_TABLETA_DIR", str(tmp_path / "tableta"))
    eolfi = _arrancar(server.make_server(str(tmp_path / "e.db"), "127.0.0.1", 0, tmp_path / "samples"))
    puente = _arrancar(tableta_puente.make_puente("127.0.0.1", 0, "127.0.0.1", eolfi.server_address[1]))
    yield eolfi, eolfi.server_address[1], puente.server_address[1]
    for h in (puente, eolfi):
        h.shutdown()
        h.server_close()


def _codigo(port_eolfi):
    return req(port_eolfi, "POST", "/api/clients/pair", "{}", X)[1]["code"]


def _h(tok):
    return {**X, "Authorization": "Bearer " + tok, "X-Eolfi-Client": "tableta"}


def _vincular_por_puente(port_eolfi, port_puente, cuerpo=None):
    body = {"code": _codigo(port_eolfi), "name": "Galaxy Tab 2", **(cuerpo or {})}
    st, out, _ = req(port_puente, "POST", "/api/clients/token", json.dumps(body), X)
    assert st == 200, out
    return out


def test_el_puente_vincula_siempre_con_alcance_de_tableta(vivo):
    _eolfi, pe, pp = vivo
    # Aunque la petición no pida alcance (lo que daría un token completo de VS Code), el puente fuerza «tableta».
    out = _vincular_por_puente(pe, pp, {"scope": None})
    assert out["scope"] == "tableta" and out["token"].startswith("ect_")
    clientes = req(pe, "GET", "/api/clients")[1]["clients"]
    assert [c["scope"] for c in clientes] == ["tableta"]


def test_eolfi_no_vincula_un_cliente_completo_que_llegue_por_el_puente(vivo):
    _eolfi, pe, _pp = vivo
    # Defensa en profundidad: aunque algo se saltara el puente, Eolfi rechaza un canje sin alcance de tableta.
    cuerpo = json.dumps({"code": _codigo(pe), "name": "x"})
    st, out, _ = req(pe, "POST", "/api/clients/token", cuerpo, {**X, server.PUENTE_HEADER: "tableta"})
    assert st == 403 and "tabletas" in out["error"]


def test_chat_por_el_puente_llega_al_eolfi_en_vivo_como_usuario(vivo):
    eolfi, pe, pp = vivo
    tok = _vincular_por_puente(pe, pp)["token"]
    recibido = {}

    def chat_falso(body, nivel="titular"):
        recibido.update(nivel=nivel)
        return {"text": "Hola", "tools": [{"name": "eolfi_modelos_auditar"}]}

    eolfi.app.chat = chat_falso
    st, out, _ = req(pp, "POST", "/api/tableta/chat", json.dumps({"texto": "hola"}), _h(tok))
    assert st == 202, out
    for _ in range(100):
        st, est, _ = req(pp, "GET", f"/api/tableta/chat?id={out['id']}", headers=_h(tok))
        if est.get("status") in ("done", "error"):
            break
        time.sleep(0.05)
    assert est["status"] == "done" and est["herramientas"] == ["eolfi_modelos_auditar"]
    # La conexión llega a Eolfi desde 127.0.0.1, pero la tableta nunca es titular.
    assert recibido["nivel"] == "usuario"
    # Y el trabajo es del Eolfi en vivo: sale en su lista de trabajos («Seguimiento»).
    trabajos = req(pe, "GET", "/api/jobs")[1]["jobs"]
    assert out["id"] in [j["id"] for j in trabajos]


def test_un_token_de_tableta_directo_por_loopback_tampoco_es_titular(vivo):
    eolfi, pe, _pp = vivo
    code = _codigo(pe)
    tok = req(pe, "POST", "/api/clients/token", json.dumps({"code": code, "scope": "tableta"}), X)[1]["token"]
    recibido = {}
    eolfi.app.chat = lambda body, nivel="titular": recibido.update(nivel=nivel) or {"text": "ok", "tools": []}
    st, out, _ = req(pe, "POST", "/api/tableta/chat", json.dumps({"texto": "hola"}), _h(tok))
    assert st == 202, out
    for _ in range(100):
        if recibido:
            break
        time.sleep(0.05)
    assert recibido["nivel"] == "usuario"


def test_por_el_puente_solo_pasa_la_superficie_de_la_tableta(vivo):
    _eolfi, pe, pp = vivo
    tok = _vincular_por_puente(pe, pp)["token"]
    for method, path, body in [("GET", "/api/subjects", None), ("GET", "/api/clients", None),
                               ("GET", "/api/jobs", None), ("GET", "/", None), ("GET", "/app.js", None),
                               ("POST", "/api/clients/pair", "{}"), ("POST", "/api/local-chat/send", "{}"),
                               ("POST", "/api/voz/config", "{}"), ("POST", "/api/jobs", "{}"),
                               ("GET", "http://127.0.0.1:1/api/tableta/estado", None)]:
        st, _out, _ = req(pp, method, path, body, _h(tok))
        assert st in (403, 404), (method, path, st)
    for method in ("PUT", "DELETE", "OPTIONS"):
        assert req(pp, method, "/api/tableta/estado", None, _h(tok))[0] == 405
    import http.client

    c = http.client.HTTPConnection("127.0.0.1", pp, timeout=30)
    c.request("HEAD", "/api/tableta/estado", headers=_h(tok))
    assert c.getresponse().status == 405
    c.close()
    # Sin token de tableta no pasa nada salvo el canje.
    st, out, _ = req(pp, "GET", "/api/tableta/estado", headers=X)
    assert st == 401 and "token" in out["error"]


def test_un_token_completo_no_entra_por_el_puente(vivo):
    _eolfi, pe, pp = vivo
    completo = req(pe, "POST", "/api/clients/token", json.dumps({"code": _codigo(pe), "name": "VS Code"}), X)[1]
    assert "scope" not in completo
    st, out, _ = req(pp, "GET", "/api/tableta/estado", headers=_h(completo["token"]))
    assert st == 403 and "tableta" in out["error"]


def test_la_voz_pasa_por_el_puente(vivo, monkeypatch):
    from eolfi import voz

    _eolfi, pe, pp = vivo
    tok = _vincular_por_puente(pe, pp)["token"]
    monkeypatch.setattr(voz, "transcribir", lambda data, idioma=None: {"texto": f"{len(data)} bytes", "idioma": idioma})
    monkeypatch.setattr(voz, "hablar", lambda texto, idioma=None, voz=None: b"RIFF" + texto.encode())
    st, out, _ = req(pp, "POST", "/api/voz/transcribir?idioma=es-ES", b"RIFF" + b"\0" * 1000,
                     {**_h(tok), "Content-Type": "audio/wav"})
    assert st == 200 and out == {"texto": "1004 bytes", "idioma": "es-ES"}
    st, out, headers = req(pp, "POST", "/api/voz/hablar", json.dumps({"texto": "hola"}), _h(tok))
    assert st == 200 and out == b"RIFFhola" and headers["Content-Type"].startswith("audio/wav")


def test_cuerpo_demasiado_grande(vivo, monkeypatch):
    _eolfi, pe, pp = vivo
    tok = _vincular_por_puente(pe, pp)["token"]
    monkeypatch.setattr(tableta_puente, "MAX_CUERPO", 10)
    st, out, _ = req(pp, "POST", "/api/tableta/chat", json.dumps({"texto": "hola hola hola"}), _h(tok))
    assert st == 413


def test_si_eolfi_no_responde_el_puente_da_502(tmp_path):
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    libre = s.getsockname()[1]
    s.close()
    puente = _arrancar(tableta_puente.make_puente("127.0.0.1", 0, "127.0.0.1", libre))
    try:
        st, out, _ = req(puente.server_address[1], "GET", "/api/tableta/estado",
                         headers={**X, "Authorization": "Bearer ect_x"})
        assert st == 502 and "Eolfi no responde" in out["error"]
    finally:
        puente.shutdown()
        puente.server_close()


@pytest.mark.parametrize("destino", ["localhost", "192.168.1.134", "0.0.0.0", "eolfi.lan", ""])
def test_el_destino_es_siempre_una_ip_de_loopback(destino):
    with pytest.raises(ValueError):
        tableta_puente.destino_valido(destino)
    assert tableta_puente.destino_valido("127.0.0.1") == "127.0.0.1"


def test_no_reenvia_cookies_ni_origen_ni_cliente():
    headers = {"Authorization": "Bearer ect_abc", "Cookie": "eolfi_token=secreto", "Origin": "https://malo",
               "X-Eolfi-Client": "vscode", "X-Eolfi": "1", "Content-Type": "application/json",
               "X-Eolfi-Puente": "otra-cosa"}
    path, out, _ = tableta_puente.preparar("GET", "/api/tableta/chat?id=0123456789abcdef", headers, b"")
    assert path == "/api/tableta/chat?id=0123456789abcdef"
    assert out == {"Authorization": "Bearer ect_abc", "Content-Type": "application/json", "X-Eolfi": "1",
                   server.PUENTE_HEADER: "tableta"}
    assert tableta_puente.PUENTE_HEADER == server.PUENTE_HEADER


def test_puente_con_tls_legado(tmp_path, vivo):
    pytest.importorskip("cryptography.x509")
    from tests.test_server_tls import _certificado

    _eolfi, pe, _pp = vivo
    cert, key = _certificado(tmp_path)
    puente = server.con_tls(tableta_puente.make_puente("127.0.0.1", 0, "127.0.0.1", pe), cert, key, legado=True)
    _arrancar(puente)
    try:
        import http.client

        ctx = ssl.create_default_context(cafile=str(cert))
        c = http.client.HTTPSConnection("127.0.0.1", puente.server_address[1], timeout=30, context=ctx)
        c.request("GET", "/api/tableta/estado", headers=X)
        r = c.getresponse()
        assert r.status == 401 and json.loads(r.read())["error"].startswith("falta el token")
        c.close()
    finally:
        puente.shutdown()
        puente.server_close()


def test_servir_arranca_en_una_consola_cp1252(tmp_path, monkeypatch):
    """20/11/2026: con la salida redirigida en Windows (cp1252) el puente caía al imprimir «→» al arrancar."""
    pytest.importorskip("cryptography.x509")
    import io
    import sys

    from tests.test_server_tls import _certificado

    cert, key = _certificado(tmp_path)
    crudo = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(crudo, encoding="cp1252", errors="strict"))

    def parar(self, *a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(server._Server, "serve_forever", parar)
    assert tableta_puente.servir("127.0.0.1", 0, cert, key, legado=True) == 0
    sys.stdout.flush()
    assert b"Puente de la tableta" in crudo.getvalue()


def test_rutas_del_puente():
    assert tableta_puente.admitida("POST", "/api/clients/token")
    assert not tableta_puente.admitida("GET", "/api/clients/token")
    assert all(tableta_puente.admitida(m, p) for m, p in tableta.PERMITIDAS)
