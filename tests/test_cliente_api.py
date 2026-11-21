"""Cliente generado desde el borrador OpenAPI de una captura (plan REA, punto 7)."""
from __future__ import annotations

import ast
import io
import importlib.util
import json
import sys
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from eolfi import cliente_api, rea_compuestas as rc
from tests.test_rea_compuestas import FakeCapture, FakeFields


def _load(source: str, tmp_path: Path, name: str = "cliente_generado"):
    path = tmp_path / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


class _Handler(BaseHTTPRequestHandler):
    seen: list[dict] = []

    def _reply(self, code: int, body: object | None) -> None:
        data = b"" if body is None else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("CONTENT-TYPE", "application/json")  # las cabeceras HTTP no distinguen mayúsculas
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _record(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        _Handler.seen.append({"method": self.command, "path": self.path, "body": json.loads(raw) if raw else None,
                              "auth": self.headers.get("Authorization")})

    def do_GET(self):  # noqa: N802
        self._record()
        if self.path == "/grande":
            self._reply(200, {"datos": "x" * 200})
        elif self.path.startswith("/v1/items/42"):
            self._reply(200, {"id": 42, "ok": True})
        else:
            self._reply(404, {"error": "no"})

    def do_POST(self):  # noqa: N802
        self._record()
        self._reply(201, {"id": 1})

    def log_message(self, *args):
        pass


@pytest.fixture()
def server():
    _Handler.seen = []
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _borrador():
    return rc.api_desde_captura(FakeCapture(), r"C:\c.pcap", fields_client=FakeFields())["openapi"]


def test_solo_genera_las_operaciones_observadas():
    ops = {(o["metodo"], o["plantilla"]): o for o in cliente_api.operaciones(_borrador())}
    assert set(ops) == {("GET", "/v1/items/{id}"), ("POST", "/v1/items")}
    assert ops[("GET", "/v1/items/{id}")]["parametros_ruta"] == ["id"]
    assert ops[("GET", "/v1/items/{id}")]["codigos"] == ["200"] and not ops[("GET", "/v1/items/{id}")]["cuerpo"]
    post = ops[("POST", "/v1/items")]
    assert post["cuerpo"] and post["parametros_consulta"] == ["limit", "page"] and post["codigos"] == ["201"]


def test_nivel_basico_no_genera_cliente():
    basico = rc.api_desde_captura(FakeCapture(), r"C:\c.pcap")
    with pytest.raises(cliente_api.BorradorIncompleto):
        cliente_api.generar_cliente(basico.get("openapi") or {})
    with pytest.raises(cliente_api.BorradorIncompleto):
        cliente_api.generar_cliente({"paths": {"/x": {"parameters": []}}})


def test_el_cliente_generado_solo_usa_la_biblioteca_estandar():
    tree = ast.parse(cliente_api.generar_cliente(_borrador()))
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}


def test_el_cliente_generado_llama_a_la_api(server, tmp_path):
    mod = _load(cliente_api.generar_cliente(_borrador()), tmp_path)
    assert mod.SERVIDORES == ["http://api.x.test"]
    api = mod.Cliente(server, cabeceras={"Authorization": "Bearer prueba"})

    r = api.get_v1_items_por_id(42)
    assert (r.codigo, r.cuerpo, r.observado) == (200, {"id": 42, "ok": True}, True)

    r = api.post_v1_items(cuerpo={"name": "a"}, page=2)
    assert (r.codigo, r.cuerpo, r.observado) == (201, {"id": 1}, True)

    r = api.get_v1_items_por_id("no existe/..")
    assert r.codigo == 404 and r.observado is False and r.codigos_observados == ["200"]

    assert _Handler.seen[0] == {"method": "GET", "path": "/v1/items/42", "body": None, "auth": "Bearer prueba"}
    assert _Handler.seen[1]["method"] == "POST" and _Handler.seen[1]["path"] == "/v1/items?page=2"
    assert _Handler.seen[1]["body"] == {"name": "a"}
    assert _Handler.seen[2]["path"] == "/v1/items/no%20existe%2F.."      # el valor no puede salir de su segmento


@pytest.mark.parametrize("base", [
    "file:///etc/passwd", "data:text/plain,hola", "https:///sin-host", "no-es-url",
    "https://usuario:secreto@example.test", "https://example.test?token=x", "https://example.test/#fragmento",
    "https://example.test?", "https://example.test#", "https://example.test:puerto", "https://host con espacios.test",
])
def test_el_cliente_generado_rechaza_bases_que_no_son_http_con_host(tmp_path, base):
    mod = _load(cliente_api.generar_cliente(_borrador()), tmp_path, "cliente_base_segura")
    with pytest.raises(ValueError, match="HTTP o HTTPS"):
        mod.Cliente(base)


def test_el_cliente_generado_admite_un_prefijo_de_ruta_en_la_base(tmp_path):
    mod = _load(cliente_api.generar_cliente(_borrador()), tmp_path, "cliente_base_con_prefijo")
    assert mod.Cliente("https://example.test/api/").base == "https://example.test/api"


@pytest.mark.parametrize("tiempo", [0, -1, True, "1", float("nan"), float("inf")])
def test_el_cliente_generado_exige_un_plazo_positivo_y_finito(tmp_path, tiempo):
    mod = _load(cliente_api.generar_cliente(_borrador()), tmp_path, "cliente_plazo_valido")
    with pytest.raises(ValueError, match="tiempo"):
        mod.Cliente("https://example.test", tiempo=tiempo)


@pytest.mark.parametrize("limite", [0, -1, True, 1.5])
def test_el_cliente_generado_exige_un_limite_de_respuesta_positivo(tmp_path, limite):
    mod = _load(cliente_api.generar_cliente(_borrador()), tmp_path, "cliente_limite_valido")
    with pytest.raises(ValueError, match="max_respuesta"):
        mod.Cliente("https://example.test", max_respuesta=limite)


def test_el_cliente_generado_acota_el_cuerpo_de_la_respuesta(server, tmp_path):
    mod = _load(cliente_api.generar_cliente(_borrador()), tmp_path, "cliente_respuesta_acotada")
    api = mod.Cliente(server, max_respuesta=32)
    with pytest.raises(ValueError, match="supera el límite de 32 bytes"):
        api._pedir("GET", "/grande", {}, None, [])


def test_el_cliente_generado_tolera_un_http_error_sin_cabeceras(tmp_path, monkeypatch):
    mod = _load(cliente_api.generar_cliente(_borrador()), tmp_path, "cliente_error_sin_cabeceras")
    error = urllib.error.HTTPError("https://example.test/x", 429, "límite", None, io.BytesIO(b"espera"))

    def fallar(*args, **kwargs):
        raise error

    api = mod.Cliente("https://example.test")
    monkeypatch.setattr(api._abridor, "open", fallar)
    respuesta = api._pedir("GET", "/x", {}, None, [])
    assert (respuesta.codigo, respuesta.cabeceras, respuesta.cuerpo) == (429, {}, "espera")


def test_el_cliente_generado_no_reenvia_credenciales_a_otro_origen(tmp_path):
    mod = _load(cliente_api.generar_cliente(_borrador()), tmp_path, "cliente_redirect_seguro")
    req = mod.urllib.request.Request("https://api.example/a", headers={
        "Authorization": "Bearer secreto", "Cookie": "sid=secreto", "X-Rastro": "ok"})
    nueva = mod._RedireccionSegura(permitir_externa=True).redirect_request(
        req, None, 302, "Found", {}, "https://otro.example/b")
    headers = {k.lower(): v for k, v in nueva.header_items()}
    assert "authorization" not in headers and "cookie" not in headers
    assert "x-rastro" not in headers


def test_el_cliente_generado_bloquea_redireccion_a_otro_host_por_defecto(tmp_path):
    mod = _load(cliente_api.generar_cliente(_borrador()), tmp_path, "cliente_redirect_bloqueado")
    req = mod.urllib.request.Request("https://api.example/a")
    with pytest.raises(mod.urllib.error.URLError, match="otro origen"):
        mod._RedireccionSegura().redirect_request(req, None, 302, "Found", {}, "https://interno.example/b")

    with pytest.raises(mod.urllib.error.URLError, match="otro origen"):
        mod._RedireccionSegura().redirect_request(req, None, 302, "Found", {}, "https://api.example:8443/b")


def test_el_cliente_generado_valida_la_opcion_de_redireccion(tmp_path):
    mod = _load(cliente_api.generar_cliente(_borrador()), tmp_path, "cliente_redirect_opcion")
    with pytest.raises(ValueError, match="redirecciones_externas"):
        mod.Cliente("https://example.test", redirecciones_externas=1)


def test_redireccion_externa_solo_conserva_cabeceras_inocuas(tmp_path):
    mod = _load(cliente_api.generar_cliente(_borrador()), tmp_path, "cliente_redirect_headers")
    req = mod.urllib.request.Request("https://api.example/a", headers={
        "Accept": "application/json", "X-API-Key": "secreto", "X-Auth-Token": "otro"})
    nueva = mod._RedireccionSegura(permitir_externa=True).redirect_request(
        req, None, 302, "Found", {}, "https://otro.example/b")
    headers = {k.lower(): v for k, v in nueva.header_items()}
    assert headers == {"accept": "application/json"}


def test_nombres_y_textos_de_la_captura_no_rompen_el_codigo(tmp_path):
    spec = {"openapi": "3.0.3", "info": {"title": 'x"""\\ y'}, "servers": [{"url": 'http://a"""b'}],
            "paths": {"/a/{id}/b/{id}": {"get": {"responses": {"200": {}, "x\"\"\"": {}}}},
                      "/class/9lives-\"x\"": {"delete": {"parameters": [{"name": "self", "in": "query"},
                                                                         {"name": "id", "in": "query"}],
                                                          "responses": {}}},
                      "/": {"get": {"responses": {"204": {}}}}}}
    mod = _load(cliente_api.generar_cliente(spec), tmp_path, "cliente_raro")
    names = {n for n in dir(mod.Cliente) if not n.startswith("_")}
    assert {"get_a_por_id_b_por_id", "delete_class_9lives_x", "get_raiz"} <= names
    assert mod.Cliente._ruta("/a/{id}/b/{id_2}", id=1, id_2=2) == "/a/1/b/2"
    import inspect

    assert list(inspect.signature(mod.Cliente.delete_class_9lives_x).parameters) == ["self", "id", "self_q"]


def test_parametros_normalizados_no_colisionan(tmp_path):
    spec = {"paths": {"/x/{self}/{cuerpo}": {"post": {
        "parameters": [{"in": "query", "name": name} for name in ("a-b", "a_b", "self", "cuerpo")],
        "requestBody": {}, "responses": {"200": {}},
    }}}}
    mod = _load(cliente_api.generar_cliente(spec), tmp_path, "cliente_colisiones")
    import inspect

    params = list(inspect.signature(mod.Cliente.post_x_por_self_por_cuerpo).parameters)
    assert params == ["self", "self_ruta", "cuerpo_ruta", "cuerpo", "a_b", "a_b_2", "cuerpo_q", "self_q"]
    api = mod.Cliente("https://example.test")
    api._pedir = lambda metodo, ruta, consulta, cuerpo, observados: (metodo, ruta, consulta, cuerpo)
    assert api.post_x_por_self_por_cuerpo("a/b", "c d", cuerpo={"ok": True}, a_b=1, a_b_2=2) == (
        "POST", "/x/a%2Fb/c%20d", {"a-b": 1, "a_b": 2, "cuerpo": None, "self": None}, {"ok": True})


def test_parametros_de_ruta_con_sufijos_ya_observados(tmp_path):
    spec = {"paths": {"/x/{id}/{id_2}/{id}": {"get": {"responses": {"200": {}}}}}}
    mod = _load(cliente_api.generar_cliente(spec), tmp_path, "cliente_sufijos")
    api = mod.Cliente("https://example.test")
    api._pedir = lambda metodo, ruta, consulta, cuerpo, observados: ruta
    assert api.get_x_por_id_por_id_2_por_id("a", "b", "c") == "/x/a/b/c"


def test_escribir_cliente_no_sobrescribe_y_rechaza_el_nivel_basico(tmp_path):
    completo = rc.api_desde_captura(FakeCapture(), r"C:\c.pcap", fields_client=FakeFields())
    destino = tmp_path / "cliente.py"
    out = cliente_api.escribir_cliente(completo, str(destino))
    assert out["archivo"] == str(destino) and len(out["sha256"]) == 64
    assert out["operaciones"] == ["POST /v1/items → post_v1_items", "GET /v1/items/{id} → get_v1_items_por_id"]
    original = destino.read_bytes()
    with pytest.raises(FileExistsError):
        cliente_api.escribir_cliente(completo, str(destino))
    assert destino.read_bytes() == original
    with pytest.raises(ValueError, match=r"\.py"):
        cliente_api.escribir_cliente(completo, str(tmp_path / "cliente.txt"))
    basico = rc.api_desde_captura(FakeCapture(), r"C:\c.pcap")
    with pytest.raises(cliente_api.BorradorIncompleto):
        cliente_api.escribir_cliente(basico, str(tmp_path / "otro.py"))
    assert not (tmp_path / "otro.py").exists()
