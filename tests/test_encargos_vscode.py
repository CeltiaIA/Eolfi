"""Encargos del chat de Eolfi a @eolfi en VS Code con cola de aprobación (18/11/2026)."""
import json
import secrets
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from eolfi import acciones, chat, chat_honestidad as hon, encargos_vscode as enc
from tests.fixtures import build_site
from tests.test_server import req

X = {"X-Eolfi": "1"}


def test_la_cola_solo_decide_una_vez_y_queda_en_el_registro():
    e = enc.crear(nombre="Tienda", descripcion="una tienda", carpeta="D:/x/tienda", fuentes=["https://ejemplo.com"],
                  case_id="c1", plan_version=1)
    assert e["estado"] == "pendiente" and len(e["id"]) == 32
    assert any("instalar" in r for r in e["riesgos"]) and any("descargar las fuentes" in r for r in e["riesgos"])
    assert [x["id"] for x in enc.listar("pendiente")] == [e["id"]]
    d = enc.decidir(e["id"], aprobar=False, origen="vscode")
    assert d["estado"] == "rechazado" and d["origen"] == "vscode"
    with pytest.raises(ValueError, match="ya está rechazado"):
        enc.decidir(e["id"], aprobar=True, origen="panel")
    with pytest.raises(ValueError):
        enc.decidir(e["id"], aprobar=True, origen="otro")
    ops = [(ev["operacion"], ev["ok"]) for ev in acciones.eventos()]
    assert ("vscode.encargo_crear", True) in ops and ("vscode.encargo_decidir", True) in ops
    crear = next(ev for ev in acciones.eventos() if ev["operacion"] == "vscode.encargo_crear")
    assert "una tienda" not in json.dumps(crear)          # la descripción solo como huella
    assert acciones.verificar()["ok"] is True


def test_el_chat_ofrece_la_herramienta_y_avisa_de_que_queda_pendiente():
    assert "eolfi_vscode_encargo" in chat.APP_TOOLS and "eolfi_vscode_encargo_estado" in chat.APP_TOOLS
    assert "eolfi_vscode_encargo" in chat.SYSTEM_PROMPT
    activo = hon.contexto({"vscode": {"activo": True, "carpetas": ["D:/p"]}})
    assert "eolfi_vscode_encargo" in activo
    llamada = [{"name": "eolfi_vscode_encargo", "ok": True}]
    hallazgos = hon.revisar("He creado la aplicación en tu carpeta.", llamada, {"eolfi_vscode_encargo"})
    assert [h["codigo"] for h in hallazgos] == ["encargo_como_hecho"]
    con_estado = llamada + [{"name": "eolfi_vscode_encargo_estado", "ok": True}]
    assert hon.revisar("He creado la aplicación.", con_estado, {"eolfi_vscode_encargo"}) == []
    assert chat._links(json.dumps({"encargo_id": "a" * 32, "case_id": "c"})) == {"encargo": "a" * 32}


def test_sin_puente_el_encargo_lo_dice_y_no_crea_nada(tmp_path, monkeypatch):
    from eolfi import server

    app = server.EolfiApp(str(tmp_path / "e.db"), tmp_path / "s")
    monkeypatch.setattr(app, "_chat_estado", lambda: {"vscode": {"activo": False}})
    monkeypatch.setattr(app, "project_plan", lambda body: pytest.fail("sin puente no se propone nada"))
    with pytest.raises(ValueError, match="puente de VS Code no responde"):
        app._chat_vscode_encargo({"nombre": "App", "descripcion": "algo"})
    assert enc.listar() == []


def test_no_sobrescribe_una_carpeta_con_contenido(tmp_path, monkeypatch):
    from eolfi import server

    app = server.EolfiApp(str(tmp_path / "e.db"), tmp_path / "s")
    ocupada = tmp_path / "ocupada"
    ocupada.mkdir()
    (ocupada / "a.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(app, "_chat_estado", lambda: {"vscode": {"activo": True, "carpetas": [str(tmp_path)]}})
    monkeypatch.setattr(app, "project_plan", lambda body: pytest.fail("no debe proponerse"))
    with pytest.raises(ValueError, match="no está vacía"):
        app._chat_vscode_encargo({"nombre": "App", "descripcion": "algo", "carpeta": str(ocupada)})
    with pytest.raises(ValueError, match="absoluta"):
        app._chat_vscode_encargo({"nombre": "App", "descripcion": "algo", "carpeta": "relativa/app"})


class _VSCodeSimulado:
    """El puente de la extensión: responde al workspace y recibe los encargos (como haría extension.js)."""

    def __init__(self, carpeta):
        self.token = secrets.token_hex(32)
        self.encargos = []
        self.recibido = threading.Event()
        sim = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if self.headers.get("Authorization") != f"Bearer {sim.token}":
                    return self._send(401, {"error": "token"})
                if self.path == "/v1/workspace/workspace":
                    return self._send(200, {"folders": [str(carpeta)]})
                if self.path == "/v1/encargo":
                    sim.encargos.append(body)
                    sim.recibido.set()
                    return self._send(202, {"recibido": body.get("id")})
                return self._send(404, {"error": "ruta"})

            def _send(self, status, obj):
                data = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    from eolfi.server import make_server

    proyecto = tmp_path / "vscode-carpeta"
    proyecto.mkdir()
    vs = _VSCodeSimulado(proyecto)
    puente = tmp_path / "vscode-bridge.json"
    puente.write_text(json.dumps({"url": vs.url, "token": vs.token, "pid": 1}), encoding="utf-8")
    monkeypatch.setenv("EOLFI_VSCODE_BRIDGE_FILE", str(puente))
    httpd = make_server(str(tmp_path / "e.db"), "127.0.0.1", 0, tmp_path / "samples")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd, vs, proyecto
    httpd.shutdown()
    httpd.server_close()
    vs.httpd.shutdown()


def _vincular_vscode(port):
    code = req(port, "POST", "/api/clients/pair", "{}", X)[1]["code"]
    tok = req(port, "POST", "/api/clients/token", json.dumps({"code": code, "name": "VS Code simulado"}),
              {**X, "X-Eolfi-Client": "vscode"})[1]["token"]
    return {**X, "X-Eolfi-Client": "vscode", "Authorization": f"Bearer {tok}"}


def test_el_rechazo_desde_el_panel_no_ejecuta_nada(entorno, tmp_path, monkeypatch):
    httpd, vs, proyecto = entorno
    port = httpd.server_address[1]
    app = httpd.app
    monkeypatch.setattr(app, "start_job", lambda body: pytest.fail("un encargo rechazado no arranca trabajos"))
    site = build_site(tmp_path / "site")
    out = app._chat_vscode_encargo({"nombre": "Rechazada", "descripcion": "web", "fuentes": [str(site)]})
    assert vs.recibido.wait(5) and vs.encargos[0]["id"] == out["encargo_id"]
    st, body, _ = req(port, "POST", f"/api/vscode/encargos/{out['encargo_id']}/rechazar", "{}", X)
    assert st == 200 and body["estado"] == "rechazado" and body["origen"] == "panel"
    assert req(port, "POST", f"/api/vscode/encargos/{out['encargo_id']}/aprobar", "{}", X)[0] == 409
    assert not (proyecto / "rechazada").exists()


@pytest.mark.skipif(not shutil.which("node"), reason="requiere Node.js (verificación del proyecto estático)")
def test_encargo_del_chat_aprobado_en_vscode_genera_un_proyecto_verificado(entorno, tmp_path):
    """Integración: chat → encargo pendiente → aviso al VS Code simulado → aprobación DESDE VS Code (cliente vinculado)
    → plan aprobado y create con verificación → el proyecto aparece verificado en la carpeta abierta en VS Code."""
    httpd, vs, proyecto = entorno
    port = httpd.server_address[1]
    app = httpd.app
    site = build_site(tmp_path / "site")
    out = app._chat_vscode_encargo({"nombre": "Mi Web", "descripcion": "una web estática",
                                    "fuentes": [str(site)]})
    assert out["estado"] == "pendiente_aprobacion" and out["aviso_vscode"] == "mostrado en VS Code"
    assert out["carpeta"].startswith(str(proyecto))
    assert vs.recibido.wait(5) and vs.encargos[0]["riesgos"] == out["riesgos"]
    destino = proyecto / "mi-web"
    assert not destino.exists()                                       # nada se ejecuta antes de aprobar
    assert req(port, "GET", "/api/vscode/encargos")[1]["encargos"][0]["estado"] == "pendiente"

    auth = _vincular_vscode(port)
    st, body, _ = req(port, "POST", f"/api/vscode/encargos/{out['encargo_id']}/aprobar", "{}", auth)
    assert st == 200 and body["origen"] == "vscode" and body.get("job_id"), body
    final = None
    for _ in range(600):
        final = req(port, "GET", "/api/vscode/encargos", None, auth)[1]["encargos"][0]
        if final["estado"] in ("hecho", "fallido"):
            break
        time.sleep(0.5)
    assert final["estado"] == "hecho", final
    assert final["proyecto"]["verificado"] is True
    assert (destino / "index.html").is_file()
    estado_chat = app._chat_vscode_encargo_estado({"encargo_id": out["encargo_id"]})
    assert estado_chat["estado"] == "hecho"
    ops = [ev["operacion"] for ev in acciones.eventos()]
    assert "vscode.encargo_crear" in ops and "vscode.encargo_decidir" in ops and "generador.create" in ops
