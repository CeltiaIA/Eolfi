"""Cliente generado desde el borrador OpenAPI de una captura (plan REA, punto 7)."""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
import threading
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
        self.send_header("Content-Type", "application/json")
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
        if self.path.startswith("/v1/items/42"):
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
