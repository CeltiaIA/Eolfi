"""Configuración local llama.cpp y compatibilidad de Gemma con el proveedor Eolas."""
import contextlib
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


def test_proveedor_eolas_v2_usa_perfil_activo_sin_cargar_modelo_doble(monkeypatch):
    from contextlib import contextmanager

    from eolfi import eolas_v2
    from eolfi.generador import llm

    cfg = {"active_profile": "mistral", "system": "", "ctx": 32000, "temperature": 0.2, "top_p": 0.95,
           "max_tokens": 4096, "reasoning": False, "review_reasoning": False, "profiles": {}}
    c = {**cfg, "alias": "mistral-test", "model": "mistral.gguf", "url": "http://127.0.0.1:8090"}
    calls = []
    monkeypatch.setattr(eolas_v2, "load_config", lambda: cfg)
    monkeypatch.setattr(eolas_v2, "status", lambda: {"running_profile": "mistral"})
    monkeypatch.setattr(eolas_v2, "profile_config", lambda name, config: c)
    # El proveedor mantiene el perfil cargado durante la petición (inference_profile, con el cerrojo exclusivo):
    # un solo llama-server y nunca un segundo modelo en la GPU.
    @contextmanager
    def profile(name):
        calls.append(("perfil", name))
        yield c

    monkeypatch.setattr(eolas_v2, "inference_profile", profile)
    monkeypatch.setattr(eolas_v2, "start", lambda *a, **k: calls.append(("start", a)))
    monkeypatch.setattr(eolas_v2, "switch", lambda *a, **k: calls.append(("switch", a)))
    sent = {}

    def fake_post(url, body, headers, timeout):
        sent.update(url=url, body=body, headers=headers)
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
    assert calls == [("perfil", "mistral")]
    assert sent["headers"] == eolas_v2.auth_headers()              # Eolas V2 exige su clave de API
