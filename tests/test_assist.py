"""Modo IA con un cliente simulado (sin red ni credenciales)."""
import json
import shutil

import pytest

from eolfi.core.evidence import EvidenceStore
from eolfi.flows.create_flow import create_project
from eolfi.generador.assist import EDITABLE, AssistError, _allowed, assist
from eolfi.generador.llm import LLMError, Provider, Reply
from tests.fixtures import build_site

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="requiere Node.js")


class FakeClient(Provider):
    """Proveedor simulado (14/11/2026: antes imitaba el SDK de Claude, retirado): devuelve respuestas fijas, guarda
    las peticiones y puede simular un rechazo. Se pasa como provider=, así ninguna prueba toca un motor real."""

    name = "simulado"

    def __init__(self, replies, stop_reason="end_turn"):
        self.replies = list(replies)
        self.calls = []
        self.stop_reason = stop_reason
        self.model = "simulado"

    def complete(self, system, messages, schema, effort):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "schema": schema,
                           "effort": effort})
        if self.stop_reason == "refusal":
            raise LLMError("La IA rechazó la petición (categoría cyber)")
        data = self.replies.pop(0)
        return Reply(data, json.dumps(data), {"input_tokens": 1000, "output_tokens": 200}, self.model)


def _project(tmp_path):
    s = EvidenceStore(":memory:")
    site = build_site(tmp_path / "site")
    out = tmp_path / "nuevo"
    create_project([str(site)], s, out, name="Bicis", target="static", do_verify=False)
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
    r = assist(out, "Añade una sección de carrito", provider=client)
    assert r["ok"] and len(r["rounds"]) == 2
    assert set(r["rounds"][0]["rejected"]) == {"package.json", "../fuera.html"}
    assert r["rounds"][0]["failed_step"] == "pruebas (node --test)"
    candidate = r["rounds"][0]["failed_candidates"][0]
    assert candidate["path"] == "index.html"
    assert "Segundo h1" in candidate["content_redacted"]
    assert len(candidate["sha256"]) == 64
    assert r["rounds"][0]["failed_output"]
    assert "carrito" in (out / "index.html").read_text(encoding="utf-8")
    assert not (tmp_path / "fuera.html").exists()
    assert json.loads((out / "package.json").read_text(encoding="utf-8"))["name"]   # intacto
    # La reparación reenvía la respuesta anterior y el error.
    second = client.calls[1]["messages"]
    assert second[-2]["role"] == "assistant" and "<error>" in second[-1]["content"]
    assert r["provider"] == "simulado" and client.calls[0]["schema"]["type"] == "object"
    assert r["usage"] == {"input_tokens": 2000, "output_tokens": 400}


def test_assist_restores_when_never_green(tmp_path):
    out = _project(tmp_path)
    original = (out / "index.html").read_text(encoding="utf-8")
    bad = original.replace("</main>", "<h1>otro</h1></main>")
    client = FakeClient([{"summary": "x", "notes": [], "files": [
        {"path": "index.html", "content": bad}, {"path": "nueva.html", "content": "<p>x</p>"}]}] * 3)
    r = assist(out, "algo", provider=client)
    assert not r["ok"] and r["restored"] and len(r["rounds"]) == 3
    assert (out / "index.html").read_text(encoding="utf-8") == original
    assert not (out / "nueva.html").exists()


def test_assist_refusal(tmp_path):
    out = _project(tmp_path)
    client = FakeClient([{"summary": "", "notes": [], "files": []}], stop_reason="refusal")
    with pytest.raises(AssistError, match="rechazó"):
        assist(out, "algo", provider=client)


def test_assist_requires_eolfi_project(tmp_path):
    with pytest.raises(AssistError, match="eolfi.spec.json"):
        assist(tmp_path, "algo", provider=FakeClient([]))


# -- Proveedores HTTP (Eolas / compatibles OpenAI) con servidores locales falsos --
import http.server
import threading

from eolfi.generador.llm import make_provider, parse_json_text


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


def test_proveedores_retirados_dan_error_claro_sin_tocar_la_red(tmp_path):
    """14/11/2026, decisión del titular: retirados 10 proveedores; eolas-v2 es el de por defecto."""
    from eolfi.generador import llm

    out = _project(tmp_path)
    for name in ("claude", "openai", "gemini", "deepseek", "gemma", "nemo-moe", "copilot-vscode", "copilot-web",
                 "chatgpt-web", "lechat-web"):
        assert name not in llm.PRESETS
        with pytest.raises(AssistError, match="proveedor desconocido"):
            assist(out, "x", provider=name, base_url="http://127.0.0.1:9")
    assert llm.DEFAULT_PROVIDER == "eolas-v2" and llm.make_provider().name == "eolas-v2"
    assert set(llm.PRESETS) == {"eolas", "eolas-v2", "celtia-v2", "deepseek-web", "gemini-web", "meta-web", "web"}


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


# ------------------------------------------------------------------ autofix: que no queden errores
def _break(out):
    good = (out / "index.html").read_text(encoding="utf-8")
    (out / "index.html").write_text(good.replace("</main>", "<h1>Segundo h1</h1></main>"), encoding="utf-8",
                                    newline="\n")
    return good


def test_autofix_green_project_does_not_call_the_ai(tmp_path):
    from eolfi.generador.assist import autofix

    out = _project(tmp_path)
    client = FakeClient([])                      # cualquier llamada fallaría (lista vacía)
    r = autofix(out, provider=client)
    assert r["ok"] and not r["needed"] and not client.calls and r["provider"] is None
    assert r["initial"]["ok"] and r["final"] == r["initial"] and r["files_changed"] == []


def test_autofix_repairs_failing_project(tmp_path):
    from eolfi.generador.assist import autofix

    out = _project(tmp_path)
    good = _break(out)
    client = FakeClient([{"summary": "Un solo h1", "notes": ["se quita el h1 duplicado"],
                          "files": [{"path": "index.html", "content": good}]}])
    r = autofix(out, provider=client)
    assert r["ok"] and r["needed"] and r["files_changed"] == ["index.html"] and len(r["rounds"]) == 1
    assert not r["initial"]["ok"] and r["final"]["ok"]
    prompt = client.calls[0]["messages"][0]["content"]
    assert '<error step="pruebas (node --test)">' in prompt and "Corrige los errores" in prompt
    assert (out / "index.html").read_text(encoding="utf-8") == good


def test_autofix_restores_when_never_green(tmp_path):
    from eolfi.generador.assist import autofix

    out = _project(tmp_path)
    _break(out)
    broken = (out / "index.html").read_text(encoding="utf-8")
    worse = broken.replace("</main>", "<h1>Tercero</h1></main>")
    client = FakeClient([{"summary": "x", "notes": [], "files": [{"path": "index.html", "content": worse}]}] * 3)
    r = autofix(out, provider=client)
    assert not r["ok"] and r["restored"] and len(r["rounds"]) == 3 and r["files_changed"] == []
    assert (out / "index.html").read_text(encoding="utf-8") == broken


def test_autofix_does_not_ask_ai_for_setup_failures(tmp_path, monkeypatch):
    from eolfi.generador import verify as verify_mod
    from eolfi.generador.assist import autofix

    out = _project(tmp_path)
    monkeypatch.setattr(verify_mod, "verify", lambda *a, **k: {"ok": False, "steps": [
        {"step": "instalar dependencias (npm install)", "exit": 1, "seconds": 1, "tail": "ENOTFOUND"}]})
    client = FakeClient([])
    r = autofix(out, provider=client)
    assert not r["ok"] and r["needed"] and not client.calls and "No corregible" in r["summary"]


def _create_broken(tmp_path, monkeypatch, provider):
    from eolfi.generador import generators

    original = generators.generate

    def generate_then_break(spec, out, **kw):
        files = original(spec, out, **kw)
        _break(out)
        return files

    monkeypatch.setattr(generators, "generate", generate_then_break)
    s = EvidenceStore(":memory:")
    site = build_site(tmp_path / "site")
    out = tmp_path / "nuevo"
    rep = create_project([str(site)], s, out, name="Bicis", target="static", do_verify=True, autofix=True,
                         ai_provider=provider)
    return s, out, rep


def test_create_runs_autofix_when_verification_fails(tmp_path, monkeypatch):
    from eolfi.generador import generators

    good_holder = {}
    original = generators.generate

    def capture(spec, out, **kw):                # la versión buena, para que la IA simulada la devuelva
        files = original(spec, out, **kw)
        good_holder["html"] = (out / "index.html").read_text(encoding="utf-8")
        return files

    monkeypatch.setattr(generators, "generate", capture)

    class Fixer(FakeClient):
        def complete(self, system, messages, schema, effort):
            self.replies = [{"summary": "corregido", "notes": [],
                             "files": [{"path": "index.html", "content": good_holder["html"]}]}]
            return super().complete(system, messages, schema, effort)

    s, out, rep = _create_broken(tmp_path, monkeypatch, Fixer([]))
    assert rep["autofix"]["ok"] and rep["autofix"]["needed"]
    assert rep["verification"]["ok"] and rep["verification"]["autofixed"]
    assert s.list_incognitas(subject=f"proyecto:{out.resolve()}") == []   # corregido: sin incógnita abierta


def test_create_keeps_failure_when_autofix_unavailable(tmp_path, monkeypatch):
    class Down(FakeClient):
        def complete(self, system, messages, schema, effort):
            raise LLMError("motor no disponible")

    s, out, rep = _create_broken(tmp_path, monkeypatch, Down([]))
    assert not rep["verification"]["ok"] and not rep["autofix"]["ok"]
    assert "no disponible" in rep["autofix"]["summary"]
    assert "Segundo h1" in (out / "index.html").read_text(encoding="utf-8")   # nada a medias


def test_cli_autofix_on_green_project(tmp_path):
    from eolfi import cli

    out = _project(tmp_path)
    db = str(tmp_path / "e.db")
    assert cli.main(["--db", db, "autofix", str(out)]) == 0
    assert cli._parser().parse_args(["create", "--from", "x", "--out", "y"]).autofix is True
    assert cli._parser().parse_args(["create", "--from", "x", "--out", "y", "--sin-autofix"]).autofix is False


def test_server_autofix_job(tmp_path):
    from eolfi.server import ApiError, EolfiApp

    out = _project(tmp_path)
    app = EolfiApp(str(tmp_path / "e.db"), tmp_path / "s")
    assert "autofix" in app.JOB_KINDS
    with pytest.raises(ApiError, match="project"):
        app.autofix({})
    r = app.autofix({"project": str(out)})          # en verde: no llega a crear el proveedor
    assert r["ok"] and not r["needed"]
