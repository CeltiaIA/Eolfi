"""Tableta satélite (Galaxy Tab 2, Android 4.1): vínculo con alcance limitado y superficie mínima (19/11/2026)."""
import json
import sqlite3
import threading
import time

import pytest

from eolfi import tableta
from tests.test_server import req

X = {"X-Eolfi": "1"}


@pytest.fixture
def panel(tmp_path, monkeypatch):
    from eolfi.server import make_server

    monkeypatch.setenv("EOLFI_TABLETA_DIR", str(tmp_path / "tableta"))
    httpd = make_server(str(tmp_path / "e.db"), "127.0.0.1", 0, tmp_path / "samples")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd, httpd.server_address[1], tmp_path
    httpd.shutdown()
    httpd.server_close()


def _vincular(port, scope="tableta", name="Galaxy Tab 2"):
    code = req(port, "POST", "/api/clients/pair", "{}", X)[1]["code"]
    body = {"code": code, "name": name, **({"scope": scope} if scope else {})}
    st, out, _ = req(port, "POST", "/api/clients/token", json.dumps(body), X)
    assert st == 200, out
    return out


def _h(tok, extra=None):
    return {**X, "Authorization": "Bearer " + tok, "X-Eolfi-Client": "tableta", **(extra or {})}


def test_el_vinculo_de_tableta_lleva_su_alcance_y_el_panel_lo_muestra(panel):
    _httpd, port, _ = panel
    out = _vincular(port)
    assert out["scope"] == "tableta" and out["token"].startswith("ect_")
    clientes = req(port, "GET", "/api/clients")[1]["clients"]
    assert [c["scope"] for c in clientes] == ["tableta"]


def test_un_alcance_desconocido_se_rechaza_sin_gastar_el_codigo(panel):
    _httpd, port, _ = panel
    code = req(port, "POST", "/api/clients/pair", "{}", X)[1]["code"]
    st, out, _ = req(port, "POST", "/api/clients/token", json.dumps({"code": code, "scope": "todo"}), X)
    assert st == 400 and "scope" in out["error"]
    st, out, _ = req(port, "POST", "/api/clients/token", json.dumps({"code": code, "scope": "tableta"}), X)
    assert st == 200 and out["scope"] == "tableta"


def test_el_token_de_la_tableta_solo_abre_su_superficie(panel, monkeypatch):
    from eolfi import voz

    _httpd, port, _ = panel
    tok = _vincular(port)["token"]
    monkeypatch.setattr(voz, "estado", lambda: {"voz_a_texto": True, "texto_a_voz": False, "motor_activo": "whisper",
                                                "idioma": "es-ES"})
    st, out, _ = req(port, "GET", "/api/tableta/estado", headers=_h(tok))
    assert st == 200 and out["scope"] == "tableta" and out["voz"]["voz_a_texto"] is True
    # Fuera de su superficie: 403 aunque el token sea válido, y sin la cabecera X-Eolfi-Client también.
    for method, path, body in [("GET", "/api/subjects", None), ("GET", "/api/clients", None),
                               ("GET", "/api/jobs", None), ("GET", "/api/fs/list?path=C:/", None),
                               ("POST", "/api/jobs", json.dumps({"kind": "triage", "body": {"path": "C:/"}})),
                               ("POST", "/api/clients/pair", "{}"), ("DELETE", "/api/clients?id=x", None),
                               ("POST", "/api/voz/dictar", "{}"), ("POST", "/api/chat/motor", "{}")]:
        for headers in (_h(tok), {**X, "Authorization": "Bearer " + tok}):
            st, out, _ = req(port, method, path, body, headers)
            assert st == 403, (method, path, st, out)
    # Un token mal escrito no tiene alcance: 401.
    assert req(port, "GET", "/api/tableta/estado", headers=_h(tok + "x"))[0] == 401


def test_un_cliente_completo_sigue_como_antes(panel):
    _httpd, port, _ = panel
    tok = _vincular(port, scope=None, name="VS Code")["token"]
    st, out, _ = req(port, "GET", "/api/subjects", headers={**X, "Authorization": "Bearer " + tok,
                                                            "X-Eolfi-Client": "vscode"})
    assert st == 200, out


def test_una_base_antigua_sin_columna_de_alcance_se_migra_y_sus_tokens_siguen_validos(tmp_path):
    import hashlib

    from eolfi.server import EolfiApp

    db = tmp_path / "vieja.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE client_tokens (id TEXT PRIMARY KEY, token_sha256 TEXT UNIQUE, name TEXT, created REAL, "
                "last_used REAL)")
    con.execute("INSERT INTO client_tokens VALUES (?,?,?,?,?)",
                ("abc", hashlib.sha256(b"ect_viejo").hexdigest(), "VS Code", time.time(), None))
    con.commit()
    con.close()
    app = EolfiApp(str(db), tmp_path / "samples")
    assert app.client_scope("ect_viejo") is None and app.client_ok("ect_viejo") is True
    assert app.client_scope("ect_otro") is False


def test_chat_desde_la_tableta_solo_ve_sus_trabajos(panel):
    httpd, port, _ = panel
    tok = _vincular(port)["token"]
    recibido = {}

    def chat_falso(body, nivel="usuario"):
        recibido.update(body=body, nivel=nivel)
        return {"text": "Hola desde Eolas", "tools": [{"name": "eolfi_objetivos"}]}

    httpd.app.chat = chat_falso
    st, out, _ = req(port, "POST", "/api/tableta/chat",
                     json.dumps({"texto": "  ¿qué tal?  ", "historial": [{"role": "user", "content": "hola"},
                                                                          {"role": "assistant", "content": "dime"}]}),
                     _h(tok))
    assert st == 202, out
    ident = out["id"]
    for _ in range(100):
        st, est, _ = req(port, "GET", f"/api/tableta/chat?id={ident}", headers=_h(tok))
        if est.get("status") in ("done", "error"):
            break
        time.sleep(0.05)
    assert est["status"] == "done" and est["texto"] == "Hola desde Eolas" and est["herramientas"] == ["eolfi_objetivos"]
    assert recibido["body"]["messages"][-1] == {"role": "user", "content": "¿qué tal?" + tableta.NOTA_TABLETA}
    assert recibido["body"]["messages"][0] == {"role": "user", "content": "hola"}   # el historial va sin nota
    assert len(recibido["body"]["messages"]) == 3
    # Un trabajo que no abrió la tableta no se puede leer desde ella.
    otro = req(port, "POST", "/api/jobs", json.dumps({"kind": "chat", "body": {"messages": [
        {"role": "user", "content": "x"}]}}), X)[1]["job_id"]
    assert req(port, "GET", f"/api/tableta/chat?id={otro}", headers=_h(tok))[0] == 404
    assert req(port, "GET", "/api/tableta/chat?id=../../x", headers=_h(tok))[0] == 404


@pytest.mark.parametrize("cuerpo", [{"texto": ""}, {"texto": "x" * 2001}, {"texto": "a", "historial": "no"},
                                    {"texto": "a", "historial": [{"role": "system", "content": "x"}]},
                                    {"texto": "a", "historial": [{"role": "user", "content": "x"}] * 13}])
def test_mensajes_invalidos_de_la_tableta(panel, cuerpo):
    _httpd, port, _ = panel
    tok = _vincular(port)["token"]
    assert req(port, "POST", "/api/tableta/chat", json.dumps(cuerpo), _h(tok))[0] == 400


def test_el_visor_resume_sin_cuerpos_ni_registros(panel):
    httpd, port, _ = panel
    tok = _vincular(port)["token"]
    httpd.app.jobs["a" * 16] = {"id": "a" * 16, "kind": "create", "status": "done", "label": "Tienda",
                                "started": 1.0, "log": [{"msg": "secreto"}], "body": {"source": "C:/privado"}}
    st, out, _ = req(port, "GET", "/api/tableta/trabajos", headers=_h(tok))
    assert st == 200
    assert out["trabajos"][0] == {"id": "a" * 16, "kind": "create", "status": "done", "label": "Tienda", "started": 1.0}
    assert "privado" not in json.dumps(out) and "secreto" not in json.dumps(out)


def test_diagnostico_guarda_solo_valores_simples(panel):
    _httpd, port, tmp = panel
    tok = _vincular(port)["token"]
    datos = {"android.sdk": 16, "tls.habilitados": ["TLSv1", "SSLv3"], "webview.ua": "Mozilla/5.0", "mic.pico": 812}
    st, out, _ = req(port, "POST", "/api/tableta/diagnostico", json.dumps(datos), _h(tok))
    assert st == 200 and out["claves"] == 4
    guardado = json.loads((tmp / "tableta" / out["guardado"]).read_text(encoding="utf-8"))
    assert guardado["datos"] == datos
    for malo in ({"anidado": {"x": 1}}, {"Clave Mala": 1}, {"lista": [1, 2]}):
        assert req(port, "POST", "/api/tableta/diagnostico", json.dumps(malo), _h(tok))[0] == 400


def test_la_voz_de_la_tableta_usa_las_rutas_existentes(panel, monkeypatch):
    from eolfi import voz

    _httpd, port, _ = panel
    tok = _vincular(port)["token"]
    monkeypatch.setattr(voz, "transcribir", lambda data, idioma=None: {"texto": f"{len(data)} bytes", "idioma": idioma})
    monkeypatch.setattr(voz, "hablar", lambda texto, idioma=None, voz=None: b"RIFF" + texto.encode())
    st, out, _ = req(port, "POST", "/api/voz/transcribir?idioma=es-ES", b"RIFFxxxx", _h(tok))
    assert st == 200 and out == {"texto": "8 bytes", "idioma": "es-ES"}
    st, out, _ = req(port, "POST", "/api/voz/hablar", json.dumps({"texto": "hola"}), _h(tok))
    assert st == 200 and out == b"RIFFhola"


def test_rutas_permitidas_estan_cerradas():
    assert tableta.permitida("HEAD", "/api/tableta/estado")
    assert not tableta.permitida("POST", "/api/tableta/estado")
    assert not tableta.permitida("GET", "/api/tableta/estado/")
    assert all(p.startswith(("/api/tableta/", "/api/voz/")) for _m, p in tableta.PERMITIDAS)


def test_app_android_sin_google_ni_samsung():
    """Requisito del titular (19/11): la tableta solo habla con lo nuestro por la red local. La app usa únicamente el
    framework AOSP, la JDK y org.json; nada de Play Services, Firebase, cuentas, TTS o reconocedor del sistema."""
    import re
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1] / "eolfi" / "tableta-android"
    fuentes = list((raiz / "src").rglob("*.java"))
    assert fuentes
    for f in fuentes:
        texto = f.read_text(encoding="utf-8")
        for imp in re.findall(r"^import\s+([\w.]+);", texto, re.M):
            assert imp.startswith(("android.", "java.", "javax.", "org.json.")), (f.name, imp)
        prohibido = re.search(r"com\.google|com\.samsung|com\.sec\.|gms|firebase|TextToSpeech|SpeechRecognizer|"
                              r"AccountManager", texto, re.I)
        assert not prohibido, (f.name, prohibido.group(0))
    construir = (raiz / "construir.py").read_text(encoding="utf-8")
    assert re.findall(r'uses-permission android:name="([\w.]+)"', construir) == [
        "android.permission.INTERNET", "android.permission.RECORD_AUDIO"]
    assert "uses-library" not in construir
