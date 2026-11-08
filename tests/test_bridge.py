"""Eolfi -> pasarela real del puente (Node) -> adaptador de chat simulado."""
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from eolfi.generador.assist import AssistError, assist
from eolfi.generador.llm import probe
from tests.test_assist import _project

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="requiere Node.js")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    procs = []

    def start(replies):
        bfile, rfile = tmp_path / "bridge.json", tmp_path / "replies.json"
        rfile.write_text(json.dumps(replies), encoding="utf-8")
        procs.append(subprocess.Popen(["node", "tests/fake_bridge.mjs", str(bfile), str(rfile)], cwd=ROOT))
        for _ in range(100):
            if bfile.exists():
                break
            time.sleep(0.05)
        monkeypatch.setenv("EOLFI_BRIDGE_FILE", str(bfile))
        return rfile
    yield start
    for p in procs:
        p.kill()


def test_web_provider_via_bridge(tmp_path, bridge):
    out = _project(tmp_path)
    page = (out / "index.html").read_text(encoding="utf-8")
    broken = page.replace("</main>", "<h1>dos</h1></main>")
    fixed = page.replace("</main>", '<section id="ofertas"><h2>Ofertas</h2></section></main>')
    rfile = bridge([
        {"summary": "Ofertas", "notes": [], "files": [{"path": "index.html", "content": broken}]},
        {"summary": "Ofertas corregidas", "notes": [], "files": [{"path": "index.html", "content": fixed}]},
    ])
    assert probe("meta-web") == {"available": True, "detail": "meta simulado"}
    r = assist(out, "Añade una sección de ofertas", provider="meta-web")
    assert r["ok"] and r["provider"] == "meta-web" and len(r["rounds"]) == 2
    assert 'id="ofertas"' in (out / "index.html").read_text(encoding="utf-8")
    seen = json.loads(Path(str(rfile) + ".seen.json").read_text(encoding="utf-8"))
    assert {s["site"] for s in seen} == {"meta"}
    assert seen[0]["conversation"] == seen[1]["conversation"]          # misma conversación en la web
    assert seen[0]["first"].startswith("Eres un ingeniero")              # primer turno: instrucciones completas
    assert seen[1]["length"] < seen[0]["length"]                         # reparación: solo el error
    assert all(s["length"] <= 31_000 for s in seen)


def test_bridge_not_running(tmp_path, monkeypatch):
    out = _project(tmp_path)
    monkeypatch.setenv("EOLFI_BRIDGE_FILE", str(tmp_path / "no-existe.json"))
    with pytest.raises(AssistError, match="eolfi bridge"):
        assist(out, "x", provider="gemini-web")
    assert probe("deepseek-web")["available"] is False


def test_panel_proxy_to_bridge(tmp_path, bridge):
    """El panel web habla con el puente a través del servidor de Eolfi (el token no llega al navegador)."""
    import threading

    from eolfi.server import make_server
    from tests.test_server import req

    bridge([{"summary": "hola", "notes": [], "files": []}])
    httpd = make_server(str(tmp_path / "s.db"), "127.0.0.1", 0, tmp_path / "samples")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    try:
        st, body, _ = req(port, "GET", "/api/bridge/status")
        assert st == 200 and body["running"] and body["providers"]["meta"]["ok"]
        assert "token" not in json.dumps(body)
        st, body, _ = req(port, "POST", "/api/bridge/chat", json.dumps({"provider": "meta", "prompt": "¿Qué tal?"}),
                          {"X-Eolfi": "1"})
        assert st == 200 and body["conversation"] == "panel-meta" and "hola" in body["text"]
        st, ev, _ = req(port, "GET", "/api/bridge/events?since=0")
        roles = [(e["role"], e["source"]) for e in ev["events"]]
        assert roles == [("user", "panel"), ("assistant", "panel")]
        st, img, hdrs = req(port, "GET", "/api/bridge/screen?provider=meta")
        assert st == 200 and hdrs["Content-Type"] == "image/jpeg" and img[:2] == b"\xff\xd8"
        assert req(port, "GET", "/api/bridge/screen?provider=evil")[0] == 400
        assert req(port, "POST", "/api/bridge/chat", json.dumps({"provider": "meta", "prompt": "x"}))[0] == 403
    finally:
        httpd.shutdown()


def test_panel_proxy_bridge_stopped(tmp_path, monkeypatch):
    import threading

    from eolfi.server import make_server
    from tests.test_server import req

    monkeypatch.setenv("EOLFI_BRIDGE_FILE", str(tmp_path / "nada.json"))
    httpd = make_server(str(tmp_path / "s.db"), "127.0.0.1", 0, tmp_path / "samples")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        st, body, _ = req(httpd.server_address[1], "GET", "/api/bridge/status")
        assert st == 200 and body["running"] is False and "eolfi bridge" in body["detail"]
        st, body, _ = req(httpd.server_address[1], "POST", "/api/bridge/chat",
                          json.dumps({"provider": "meta", "prompt": "x"}), {"X-Eolfi": "1"})
        assert st == 503
    finally:
        httpd.shutdown()


def test_choose_web_site_prefers_signed_in(monkeypatch):
    from eolfi.generador.llm import LLMError, choose_web_site
    st = {"gemini": {"ok": True, "signedIn": False}, "meta": {"ok": True, "signedIn": True},
          "deepseek": {"ok": False, "detail": "inicia sesión"}}
    assert choose_web_site(st) == "meta"                       # con sesión antes que invitado
    st["meta"]["busy"] = True
    assert choose_web_site(st) == "gemini"                     # ocupado -> el siguiente listo
    monkeypatch.setenv("EOLFI_WEB_ORDER", "deepseek,gemini")
    st["deepseek"] = {"ok": True, "signedIn": True}
    assert choose_web_site(st) == "deepseek"
    with pytest.raises(LLMError, match="Ningún chat web"):
        choose_web_site({s: {"ok": False, "detail": "x"} for s in ("gemini", "meta", "deepseek")})


def test_web_auto_provider_via_bridge(tmp_path, bridge):
    out = _project(tmp_path)
    page = (out / "index.html").read_text(encoding="utf-8").replace("</main>", '<section id="auto"><h2>Auto</h2></section></main>')
    rfile = bridge([{"summary": "auto", "notes": [], "files": [{"path": "index.html", "content": page}]}])
    r = assist(out, "x", provider="web")
    assert r["ok"] and r["model"].startswith("meta (web")           # el falso dice ok a los tres; Meta es el primer proveedor web
    seen = json.loads(Path(str(rfile) + ".seen.json").read_text(encoding="utf-8"))
    assert seen[0]["site"] == r["model"].split(" ")[0]
