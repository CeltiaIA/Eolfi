"""Configuración local llama.cpp y compatibilidad de Gemma con el proveedor Eolas."""
import json


def test_config_por_defecto_y_argumentos(tmp_path, monkeypatch):
    from eolfi import llamacpp

    monkeypatch.setenv("EOLFI_LLAMACPP_CONFIG", str(tmp_path / "llamacpp.json"))
    monkeypatch.setattr(llamacpp, "_find_server", lambda: "X:/llama-server.exe")
    monkeypatch.setattr(llamacpp, "_find_model", lambda: "X:/gemma-4-12b-it-Q5_K_M.gguf")
    cfg = llamacpp.load_config()
    assert (tmp_path / "llamacpp.json").is_file()
    assert cfg["port"] == 8090 and cfg["reasoning"] is True and cfg["show_reasoning"] is True
    a = llamacpp.server_args(cfg)
    assert a[0] == "X:/llama-server.exe" and a[a.index("-m") + 1].endswith("gemma-4-12b-it-Q5_K_M.gguf")
    assert a[a.index("--host") + 1] == "127.0.0.1"
    assert a[a.index("--reasoning-format") + 1] == "deepseek" and "--jinja" in a
    assert "--threads" not in a and "--threads-batch" not in a
    (tmp_path / "llamacpp.json").write_text(json.dumps({"temperature": 0.1, "reasoning": False, "max_tokens": 777, "threads": 4}), encoding="utf-8")
    cfg = llamacpp.load_config()
    a = llamacpp.server_args(cfg)
    assert a[a.index("--threads") + 1] == "4" and a[a.index("--threads-batch") + 1] == "4"
    assert llamacpp.request_options(cfg) == {"temperature": 0.1, "top_p": 0.95, "max_tokens": 777,
                                             "chat_template_kwargs": {"enable_thinking": False}}


def test_proveedor_gemma_usa_eolas_sin_arrancar_llama_cpp(monkeypatch):
    from eolfi import llamacpp
    from eolfi.generador import llm

    monkeypatch.setenv("CELTIAIA_EOLAS_URL", "http://127.0.0.1:11435")
    monkeypatch.setenv("EOLAS_MODEL", "gemma-4-12b-it:latest")
    monkeypatch.setattr(llamacpp, "start", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no debe arrancar llama.cpp")))
    sent = {}

    def fake_post(url, body, headers, timeout):
        sent.update(url=url, body=body)
        return {"message": {"content": '{"ok": true}'}, "prompt_eval_count": 5, "eval_count": 3}

    monkeypatch.setattr(llm, "_post", fake_post)
    p = llm.make_provider("gemma")
    r = p.complete("sistema", [{"role": "user", "content": "hola"}], {"type": "object"}, "high")
    assert r.data["ok"] is True and r.model == "gemma-4-12b-it:latest"
    assert r.usage == {"input_tokens": 5, "output_tokens": 3}
    assert sent["url"] == "http://127.0.0.1:11435/api/chat"
    assert sent["body"]["model"] == "gemma-4-12b-it:latest"
    assert sent["body"]["messages"] == [{"role": "system", "content": "sistema"},
                                         {"role": "user", "content": "hola"}]
    assert sent["body"]["format"] == {"type": "object"} and sent["body"]["think"] is False


def test_proveedor_eolas_v2_usa_perfil_activo_sin_cargar_modelo_doble(monkeypatch):
    from eolfi import eolas_v2
    from eolfi.generador import llm

    cfg = {"active_profile": "mistral", "system": "", "ctx": 32000, "temperature": 0.2, "top_p": 0.95,
           "max_tokens": 4096, "reasoning": False, "review_reasoning": False, "profiles": {}}
    c = {**cfg, "alias": "mistral-test", "model": "mistral.gguf", "url": "http://127.0.0.1:8090"}
    calls = []
    monkeypatch.setattr(eolas_v2, "load_config", lambda: cfg)
    monkeypatch.setattr(eolas_v2, "status", lambda: {"running_profile": "mistral"})
    monkeypatch.setattr(eolas_v2, "profile_config", lambda name, config: c)
    monkeypatch.setattr(eolas_v2, "start", lambda profile=None: calls.append(("start", profile)))
    monkeypatch.setattr(eolas_v2, "switch", lambda profile: calls.append(("switch", profile)))
    sent = {}

    def fake_post(url, body, headers, timeout):
        sent.update(url=url, body=body)
        return {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3}}

    monkeypatch.setattr(llm, "_post", fake_post)
    p = llm.make_provider("eolas-v2")
    reply = p.complete("sistema", [{"role": "user", "content": "hola"}], {"type": "object"}, "high")
    assert reply.data == {"ok": True, "summary": "", "notes": [], "files": []}
    assert reply.model == "mistral-test (Eolas V2 local)"
    assert reply.usage == {"input_tokens": 5, "output_tokens": 3}
    assert sent["url"] == "http://127.0.0.1:8090/v1/chat/completions"
    assert sent["body"]["model"] == "mistral-test"
    assert sent["body"]["max_tokens"] == 4096
    assert calls == [("start", "mistral")]
