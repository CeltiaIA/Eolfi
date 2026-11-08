"""Modelo local llama.cpp (Gemma 4): configuración común y proveedor «gemma»."""
import json


def test_config_por_defecto_y_argumentos(tmp_path, monkeypatch):
    from eolfi import llamacpp

    monkeypatch.setenv("EOLFI_LLAMACPP_CONFIG", str(tmp_path / "llamacpp.json"))
    monkeypatch.setattr(llamacpp, "_find_server", lambda: "X:/llama-server.exe")
    monkeypatch.setattr(llamacpp, "_find_model", lambda: "X:/gemma-4-E4B-it-Q4_K_M.gguf")
    cfg = llamacpp.load_config()
    assert (tmp_path / "llamacpp.json").is_file()
    assert cfg["port"] == 8090 and cfg["reasoning"] is True and cfg["show_reasoning"] is True
    a = llamacpp.server_args(cfg)
    assert a[0] == "X:/llama-server.exe" and a[a.index("-m") + 1].endswith("gemma-4-E4B-it-Q4_K_M.gguf")
    assert a[a.index("--host") + 1] == "127.0.0.1"
    assert a[a.index("--reasoning-format") + 1] == "deepseek" and "--jinja" in a
    assert "--threads" not in a and "--threads-batch" not in a
    (tmp_path / "llamacpp.json").write_text(json.dumps({"temperature": 0.1, "reasoning": False, "max_tokens": 777, "threads": 4}), encoding="utf-8")
    cfg = llamacpp.load_config()
    a = llamacpp.server_args(cfg)
    assert a[a.index("--threads") + 1] == "4" and a[a.index("--threads-batch") + 1] == "4"
    assert llamacpp.request_options(cfg) == {"temperature": 0.1, "top_p": 0.95, "max_tokens": 777,
                                             "chat_template_kwargs": {"enable_thinking": False}}


def test_proveedor_gemma(tmp_path, monkeypatch):
    from eolfi import llamacpp
    from eolfi.generador import llm

    monkeypatch.setenv("EOLFI_LLAMACPP_CONFIG", str(tmp_path / "llamacpp.json"))
    (tmp_path / "llamacpp.json").write_text(json.dumps({"server": "X:/s.exe", "model": "X:/g.gguf", "system": "Sé breve.",
                                                        "ctx": 8192, "max_tokens": 1000}), encoding="utf-8")
    monkeypatch.setattr(llamacpp, "start", lambda cfg=None, wait=0: {"running": True})
    sent = {}

    def fake_post(url, body, headers, timeout):
        sent.update(url=url, body=body)
        return {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok": true}', "reasoning_content": "pienso…"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3}}

    monkeypatch.setattr(llm, "_post", fake_post)
    p = llm.make_provider("gemma")
    r = p.complete("sistema", [{"role": "user", "content": "hola"}], {"type": "object"}, "high")
    assert r.data["ok"] is True and "llama.cpp local" in r.model
    assert p.last_reasoning == "pienso…"
    assert sent["url"] == "http://127.0.0.1:8090/v1/chat/completions"
    assert "Sé breve." in sent["body"]["messages"][0]["content"]
    assert sent["body"]["chat_template_kwargs"] == {"enable_thinking": True}
    assert sent["body"]["max_tokens"] == 4096                         # la mitad del contexto como mínimo
    assert sent["body"]["response_format"]["type"] == "json_schema"
