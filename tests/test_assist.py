"""Modo IA con un cliente simulado (sin red ni credenciales)."""
import json
import shutil
from types import SimpleNamespace

import pytest

from eolfi.core.evidence import EvidenceStore
from eolfi.flows.create_flow import create_project
from eolfi.generador.assist import EDITABLE, AssistError, _allowed, assist
from tests.fixtures import build_site

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="requiere Node.js")


class FakeStream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


class FakeClient:
    """Imita client.beta.messages.stream(...) y guarda las peticiones."""

    def __init__(self, replies, stop_reason="end_turn"):
        self.replies = list(replies)
        self.calls = []
        self.stop_reason = stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kw):
        self.calls.append(kw)
        data = self.replies.pop(0)
        msg = SimpleNamespace(
            stop_reason=self.stop_reason, stop_details=SimpleNamespace(category="cyber"),
            content=[SimpleNamespace(type="text", text=json.dumps(data))],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200))
        return FakeStream(msg)


def _project(tmp_path):
    s = EvidenceStore(":memory:")
    site = build_site(tmp_path / "site")
    out = tmp_path / "nuevo"
    create_project([str(site)], s, out, name="Bicis", target="static")
    return out


def test_allowed_paths():
    assert _allowed("react", "src/components/Cart.tsx")
    for bad in ("package.json", "src/../package.json", "/etc/passwd", "C:/x.ts", "vite.config.ts",
                ".github/workflows/ci.yml", "node_modules/x/index.js", "src/x.exe", "eolfi.spec.json"):
        assert not _allowed("react", bad), bad
    assert _allowed("static", "catalogo.html") and not _allowed("static", "scripts/serve.mjs")
    assert set(EDITABLE) == {"static", "react", "vue", "svelte", "next", "fastapi", "express", "django", "expo", "desktop", "tauri", "cli", "dotnet"}
    assert _allowed("expo", "src/components/Section.tsx") and not _allowed("expo", "app.json")


def test_assist_repairs_then_passes(tmp_path):
    out = _project(tmp_path)
    good = (out / "index.html").read_text(encoding="utf-8")
    broken = good.replace("</main>", "<h1>Segundo h1</h1></main>")          # rompe la prueba de h1 único
    fixed = good.replace("</main>", '<section id="carrito"><h2>Carrito</h2></section></main>')
    client = FakeClient([
        {"summary": "Añade carrito", "notes": [], "files": [
            {"path": "index.html", "content": broken},
            {"path": "package.json", "content": "{}"},                       # prohibido
            {"path": "../fuera.html", "content": "x"}]},                       # fuera del proyecto
        {"summary": "Carrito corregido", "notes": ["un solo h1"], "files": [
            {"path": "./index.html", "content": fixed}]},
    ])
    r = assist(out, "Añade una sección de carrito", client=client)
    assert r["ok"] and len(r["rounds"]) == 2
    assert set(r["rounds"][0]["rejected"]) == {"package.json", "../fuera.html"}
    assert r["rounds"][0]["failed_step"] == "pruebas (node --test)"
    assert "carrito" in (out / "index.html").read_text(encoding="utf-8")
    assert not (tmp_path / "fuera.html").exists()
    assert json.loads((out / "package.json").read_text(encoding="utf-8"))["name"]   # intacto
    # La reparación reenvía la respuesta anterior y el error.
    second = client.calls[1]["messages"]
    assert second[-2]["role"] == "assistant" and "<error>" in second[-1]["content"]
    assert client.calls[0]["model"] == "claude-opus-5-5" and r["provider"] == "claude"
    assert client.calls[0]["output_config"]["format"]["type"] == "json_schema"
    assert client.calls[0]["fallbacks"] == "default"
    assert r["usage"] == {"input_tokens": 2000, "output_tokens": 400}


def test_assist_restores_when_never_green(tmp_path):
    out = _project(tmp_path)
    original = (out / "index.html").read_text(encoding="utf-8")
    bad = original.replace("</main>", "<h1>otro</h1></main>")
    client = FakeClient([{"summary": "x", "notes": [], "files": [
        {"path": "index.html", "content": bad}, {"path": "nueva.html", "content": "<p>x</p>"}]}] * 3)
    r = assist(out, "algo", client=client)
    assert not r["ok"] and r["restored"] and len(r["rounds"]) == 3
    assert (out / "index.html").read_text(encoding="utf-8") == original
    assert not (out / "nueva.html").exists()


def test_assist_refusal(tmp_path):
    out = _project(tmp_path)
    client = FakeClient([{"summary": "", "notes": [], "files": []}], stop_reason="refusal")
    with pytest.raises(AssistError, match="rechazó"):
        assist(out, "algo", client=client)


def test_assist_requires_eolfi_project(tmp_path):
    with pytest.raises(AssistError, match="eolfi.spec.json"):
        assist(tmp_path, "algo", client=FakeClient([]))


# -- Proveedores HTTP (Eolas / compatibles OpenAI) con servidores locales falsos --
import http.server
import threading

from eolfi.generador.llm import LLMError, make_provider, parse_json_text


def _fake_server(handler_fn):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            status, out = handler_fn(self.path, body, dict(self.headers))
            data = json.dumps(out).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_parse_json_text_tolerant():
    assert parse_json_text('```json\n{"summary": "a", "files": []}\n```')["summary"] == "a"
    assert parse_json_text('Aquí va: {"files": [], "summary": "b"} fin')["summary"] == "b"
    with pytest.raises(LLMError):
        parse_json_text("sin json")


def test_eolas_provider_end_to_end(tmp_path):
    out = _project(tmp_path)
    page = (out / "index.html").read_text(encoding="utf-8").replace(
        "</main>", '<section id="rutas"><h2>Rutas</h2></section></main>')
    seen = {}

    def handler(path, body, headers):
        seen.update(path=path, model=body["model"], fmt=body["format"], roles=[m["role"] for m in body["messages"]])
        content = json.dumps({"summary": "Rutas añadidas", "notes": [], "files": [{"path": "index.html", "content": page}]})
        return 200, {"message": {"role": "assistant", "content": content}, "prompt_eval_count": 50, "eval_count": 9}
    srv, url = _fake_server(handler)
    try:
        r = assist(out, "Añade rutas", provider="eolas", base_url=url)
    finally:
        srv.shutdown()
    assert r["ok"] and r["provider"] == "eolas" and r["model"] == "gemma-4-12b-it:latest"
    assert seen["path"] == "/api/chat" and seen["fmt"]["required"] == ["summary", "files", "notes"]
    assert seen["roles"] == ["system", "user"] and r["usage"] == {"input_tokens": 50, "output_tokens": 9}
    assert 'id="rutas"' in (out / "index.html").read_text(encoding="utf-8")


def test_openai_compat_needs_key_and_sends_bearer(tmp_path, monkeypatch):
    out = _project(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(AssistError, match="DEEPSEEK_API_KEY"):
        assist(out, "x", provider="deepseek", base_url="http://127.0.0.1:9")
    got = {}

    def handler(path, body, headers):
        got.update(path=path, auth=headers.get("Authorization"), fmt=body["response_format"])
        return 200, {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(
            {"summary": "nada", "notes": [], "files": []})}}], "usage": {"prompt_tokens": 7, "completion_tokens": 3}}
    srv, url = _fake_server(handler)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "clave-de-prueba")
    try:
        r = assist(out, "x", provider="deepseek", base_url=url)
    finally:
        srv.shutdown()
    assert r["ok"] and got["path"] == "/chat/completions" and got["auth"] == "Bearer clave-de-prueba"
    assert got["fmt"] == {"type": "json_object"}          # DeepSeek: modo JSON


def test_provider_http_error_restores(tmp_path):
    out = _project(tmp_path)
    before = (out / "index.html").read_text(encoding="utf-8")
    srv, url = _fake_server(lambda p, b, h: (500, {"error": "modelo no cargado"}))
    try:
        with pytest.raises(AssistError, match="HTTP 500"):
            assist(out, "x", provider="eolas", base_url=url)
    finally:
        srv.shutdown()
    assert (out / "index.html").read_text(encoding="utf-8") == before
    with pytest.raises(LLMError, match="desconocido"):
        make_provider("inventado-web")


def test_ai_may_only_add_new_migrations(tmp_path):
    from eolfi.generador.assist import _apply
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "0001_init.sql").write_text("CREATE TABLE res_a (id INTEGER);", encoding="utf-8")
    files = [{"path": "migrations/0002_add_price.sql", "content": "ALTER TABLE res_a ADD COLUMN price REAL;"},
             {"path": "migrations/0001_init.sql", "content": "DROP TABLE res_a;"},
             {"path": "migrations/sin_numero.sql", "content": "SELECT 1;"}]
    written, rejected = _apply(tmp_path.resolve(), "fastapi", files, {})
    assert written == ["migrations/0002_add_price.sql"]
    assert rejected == ["migrations/0001_init.sql", "migrations/sin_numero.sql"]
    assert "res_a (id" in (tmp_path / "migrations" / "0001_init.sql").read_text(encoding="utf-8")
    assert not _allowed("react", "migrations/0002_x.sql")
