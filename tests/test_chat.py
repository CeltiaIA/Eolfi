"""Chat del panel: el motor Eolas V2 decide qué herramientas de Eolfi usar y Eolfi las ejecuta."""
import json

import pytest

from eolfi import chat


class FakeMCP:
    def __init__(self, db=None, roots=None, library=None):
        self.roots, self.calls = roots, []
        self.tools = {n: ({"name": n, "description": "d", "inputSchema": {"type": "object"}}, None)
                      for n in (*chat.CHAT_TOOLS, "eolfi_resolver")}

    def call_tool(self, name, args):
        self.calls.append((name, args))
        return {"content": [{"type": "text", "text": json.dumps({"summary": {"format": "pe"}})}], "isError": False}


def _call(name, args, i="1"):
    return {"id": i, "function": {"name": name, "arguments": json.dumps(args)}}


def test_mensajes_validos_y_ultimo_del_usuario():
    ok = chat.validate_messages([{"role": "user", "content": "hola"}, {"role": "assistant", "content": "hola"},
                                 {"role": "user", "content": "¿qué es?"}])
    assert ok[-1] == {"role": "user", "content": "¿qué es?"}
    for bad in ([], [{"role": "system", "content": "x"}], [{"role": "user", "content": "  "}],
                [{"role": "user", "content": "x" * (chat.MAX_MESSAGE_CHARS + 1)}],
                [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]):
        with pytest.raises(ValueError):
            chat.validate_messages(bad)


def test_contexto_dice_donde_estan_los_adjuntos_y_que_analizar():
    msgs = chat.with_context([{"role": "user", "content": "¿Qué genero?"}],
                             [{"name": "x.exe", "path": "C:/s/ab.bin", "kind": "binario"}],
                             {"kind": "url", "target": "https://example.com"})
    text = msgs[-1]["content"]
    assert text.startswith("¿Qué genero?") and "C:/s/ab.bin" in text and "binario" in text and "la web: https://example.com" in text
    assert chat.with_context([{"role": "user", "content": "x"}], [], None) == [{"role": "user", "content": "x"}]


def test_eolas_decide_las_herramientas_y_eolfi_las_ejecuta():
    mcp, steps, sent = FakeMCP(), [], []
    replies = iter([
        {"tool_calls": [_call("eolfi_triage", {"ruta": "C:/s/ab.bin"}), _call("ejecutar_python", {"codigo": "print(2)"}, "2"),
                        _call("eolfi_resolver", {}, "3")]},
        {"content": "Es un PE de Windows. Propuestas: 1) …"},
    ])
    out = chat.agent_turn([{"role": "user", "content": "analiza"}], {"alias": "gemma", "url": "u"}, mcp, steps.append,
                          request=lambda c, convo, tools: sent.append((list(convo), tools)) or next(replies),
                          run_python=lambda code: ("2", True))
    assert out["text"].startswith("Es un PE")
    offered = {t["function"]["name"] for t in sent[0][1]}
    assert offered == {*chat.CHAT_TOOLS, "ejecutar_python"}                 # nunca las que no son del chat
    assert [(c["name"], c["ok"]) for c in out["tools"]] == [("eolfi_triage", True), ("ejecutar_python", True),
                                                           ("eolfi_resolver", False)]
    assert mcp.calls == [("eolfi_triage", {"ruta": "C:/s/ab.bin"})]          # la no ofrecida no se ejecuta
    assert sent[0][0][0]["role"] == "system" and "DATOS" in sent[0][0][0]["content"]
    assert any("Eolas pide a Eolfi: eolfi_triage" in s for s in steps)


def test_si_agota_las_rondas_pide_respuesta_final_sin_herramientas():
    sent = []

    def request(c, convo, tools):
        sent.append(tools)
        return {"tool_calls": [_call("eolfi_biblioteca_buscar", {"consulta": "x"})]} if tools else {"content": "Resumen."}

    out = chat.agent_turn([{"role": "user", "content": "x"}], {"alias": "g", "url": "u"}, FakeMCP(), lambda s: None,
                          request=request, max_rounds=2)
    assert out["text"] == "Resumen." and sent[-1] == [] and len(out["tools"]) == 2


def test_trabajo_chat_usa_el_motor_eolas_v2_y_no_pisa_el_banco(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from eolfi import eolas_v2, mcp_server, server

    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(tmp_path / "eolas-v2.json"))
    monkeypatch.delenv("EOLFI_CHAT_URL", raising=False)
    app = server.EolfiApp(str(tmp_path / "c.db"))
    app.samples = tmp_path / "samples"
    app.samples.mkdir()
    (app.samples / ("a" * 64 + ".bin")).write_bytes(b"MZ")
    used = []

    @contextmanager
    def profile(name):
        used.append(name)
        yield {"alias": "gemma-q4", "url": "http://127.0.0.1:8090"}

    monkeypatch.setattr(eolas_v2, "load_config", lambda: {"active_profile": "gemma_q4"})
    monkeypatch.setattr(eolas_v2, "inference_profile", profile)
    monkeypatch.setattr(mcp_server, "EolfiMCP", FakeMCP)
    seen = {}
    monkeypatch.setattr(chat, "agent_turn", lambda msgs, c, mcp, progress: seen.update(msgs=msgs, c=c, mcp=mcp) or
                        {"text": "Propuestas…", "tools": [{"name": "eolfi_triage", "args": "{}", "ok": True}]})
    out = app.chat({"messages": [{"role": "user", "content": "¿Qué genero?"}],
                    "attachments": [{"upload": "a" * 64, "name": "x.exe", "kind": "binario"}],
                    "analyze": {"kind": "url", "target": "https://example.com"}})
    assert out["text"] == "Propuestas…" and out["model"].startswith("gemma-q4") and used == ["gemma_q4"]
    assert seen["c"]["headers"] == {"Authorization": f"Bearer {eolas_v2.api_key()}"}       # Eolas V2 con su clave
    assert seen["c"]["endpoint"] == "http://127.0.0.1:8090/v1/chat/completions"
    assert str(app.samples / ("a" * 64 + ".bin")) in seen["msgs"][-1]["content"]

    for bad in ({"messages": [{"role": "user", "content": "x"}], "analyze": {"kind": "inventado", "target": "y"}},
                {"messages": [{"role": "user", "content": "x"}], "attachments": [{"upload": "../../x"}]},
                {"messages": [{"role": "user", "content": "x"}], "attachments": [{"upload": "b" * 64}]}):
        with pytest.raises(server.ApiError):
            app.chat(bad)
    app.jobs["j"] = {"kind": "eolas-e2e", "status": "running"}          # el banco tiene la GPU
    with pytest.raises(server.ApiError, match="banco de motores"):
        app.chat({"messages": [{"role": "user", "content": "x"}]})
    assert app.chat_status()["busy"]


def test_motor_por_api_remota_configurable_y_seguro(monkeypatch):
    for var in ("EOLFI_CHAT_URL", "EOLFI_CHAT_MODEL", "EOLFI_CHAT_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert chat.remote_engine() is None                                      # por defecto: Eolas V2 local
    monkeypatch.setenv("EOLFI_CHAT_URL", "https://api.ejemplo.com/v1/")
    with pytest.raises(RuntimeError, match="EOLFI_CHAT_API_KEY"):
        chat.remote_engine()                                                 # sin clave no funciona
    monkeypatch.setenv("EOLFI_CHAT_MODEL", "modelo-x")
    monkeypatch.setenv("EOLFI_CHAT_API_KEY", "k-123")
    e = chat.remote_engine()
    assert e["endpoint"] == "https://api.ejemplo.com/v1/chat/completions" and e["headers"] == {"Authorization": "Bearer k-123"}
    monkeypatch.setenv("EOLFI_CHAT_URL", "http://api.ejemplo.com/v1")
    with pytest.raises(RuntimeError, match="https"):
        chat.remote_engine()                                                 # la clave nunca viaja por http


def test_peticion_del_chat_usa_el_destino_y_la_clave_del_motor(monkeypatch):
    import urllib.request

    sent = []

    class Opener:
        def open(self, req, timeout=0):
            sent.append(req)

            class R:
                def __enter__(self): return self
                def __exit__(self, *a): return False
                def read(self): return json.dumps({"choices": [{"message": {"content": "hola"}}]}).encode()
            return R()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *h: Opener())
    remote = {"kind": "api", "alias": "m", "endpoint": "https://api.x/v1/chat/completions", "headers": {"Authorization": "Bearer k"}}
    assert chat._request(remote, [{"role": "user", "content": "x"}], [])["content"] == "hola"
    body = json.loads(sent[0].data)
    assert sent[0].full_url == remote["endpoint"] and sent[0].get_header("Authorization") == "Bearer k"
    assert "chat_template_kwargs" not in body and "tools" not in body          # nada propio de llama-server en remoto


def test_herramientas_de_la_aplicacion_y_enlaces_para_la_pagina():
    hechas = []
    box = chat.Toolbox(FakeMCP(), {"eolfi_proponer_proyecto": lambda a: hechas.append(a) or
                                   {"case_id": "c-1", "aviso": "no se ejecuta"},
                                   "eolfi_objetivos": lambda a: 1 / 0, "eolfi_inventada": lambda a: None})
    assert "eolfi_inventada" not in box.tools and "eolfi_resolver" not in box.tools
    assert {"eolfi_triage", "eolfi_proponer_proyecto", "eolfi_objetivos"} <= set(box.tools)
    replies = iter([{"tool_calls": [_call("eolfi_proponer_proyecto", {"nombre": "x", "descripcion": "y"}),
                                    _call("eolfi_triage", {"ruta": "a"}, "2"), _call("eolfi_objetivos", {}, "3")]},
                    {"content": "Te propongo un plan."}])
    out = chat.agent_turn([{"role": "user", "content": "crea"}], {"alias": "g"}, box, lambda s: None,
                          request=lambda c, convo, tools: next(replies))
    assert hechas == [{"nombre": "x", "descripcion": "y"}]
    assert out["tools"][0]["proyecto"] == "c-1" and out["tools"][0]["ok"]
    assert out["tools"][2]["ok"] is False                                # el error llega al modelo como dato
    assert chat._links('[nota] {"subject": "ab", "x": 1}') == {"objetivo": "ab"} and chat._links("nada") == {}


def test_proponer_proyecto_desde_el_chat_no_lo_ejecuta(tmp_path, monkeypatch):
    from eolfi import server

    app = server.EolfiApp(str(tmp_path / "p.db"))
    pedidos = []
    monkeypatch.setattr(app, "project_plan", lambda body: pedidos.append(body) or
                        {"case_id": "c-9", "status": "proposed", "plan": {"version": 1}})
    monkeypatch.setattr(app, "project_run", lambda body: pytest.fail("el chat nunca ejecuta un plan"))
    out = app._chat_propose_project({"nombre": "Web", "descripcion": "Una web", "fuentes": ["https://x"], "modo": "guiado"})
    assert out["case_id"] == "c-9" and "NO se ejecuta" in out["aviso"]
    assert pedidos == [{"name": "Web", "description": "Una web", "sources": ["https://x"], "mode": "guided"}]
    with pytest.raises(ValueError):
        app._chat_propose_project({"nombre": "W", "descripcion": "d", "fuentes": "no-lista"})


def test_el_motor_elegido_en_eolfi_es_el_de_eolas_v2(tmp_path, monkeypatch):
    import json as _json

    from eolfi import eolas_v2, server

    cfg_path = tmp_path / "eolas.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(cfg_path))
    cfg = eolas_v2.load_config()
    for name in ("gemma_q4", "qwen14_q4"):
        cfg["profiles"][name]["model"] = str(tmp_path / f"{name}.gguf")
        (tmp_path / f"{name}.gguf").touch()
    cfg["profiles"]["mistral"]["model"] = str(tmp_path / "no-existe.gguf")
    cfg_path.write_text(_json.dumps(cfg), encoding="utf-8")
    app = server.EolfiApp(str(tmp_path / "m.db"))
    monkeypatch.setattr(eolas_v2, "_start_locked", lambda *a, **k: pytest.fail("elegir motor no arranca nada"))
    st = app.chat_set_profile({"profile": "qwen14_q4"})
    assert st["profile"] == "qwen14_q4" and eolas_v2.load_config()["active_profile"] == "qwen14_q4"
    assert {"gemma_q4", "qwen14_q4"} <= {p["name"] for p in st["profiles"]} and "nemo_moe" not in {p["name"] for p in st["profiles"]}
    for bad in ("inventado", "nemo_moe", "mistral"):                       # mistral: sin GGUF en esta prueba
        with pytest.raises(server.ApiError):
            app.chat_set_profile({"profile": bad})


def test_esquemas_sin_tipos_en_lista_para_la_plantilla_de_gemma():
    """14/11/2026: «NotImplemented: map: filter-mapping not implemented» (HTTP 500) de la plantilla de Gemma 4 con
    esquemas de REA que dan el tipo como lista."""
    rea_like = {"type": "object", "properties": {
        "columns": {"type": "array", "items": {"type": ["null", "boolean", "object", "array", "number", "string"], "items": {}}},
        "limit": {"type": ["integer", "null"], "description": "Máximo"},
        "path": {"type": "string"}}, "required": ["path"]}
    safe = chat.template_safe(rea_like)
    assert safe["properties"]["columns"]["items"]["type"] == "string"
    assert "cualquier valor JSON" in safe["properties"]["columns"]["items"]["description"]
    assert safe["properties"]["limit"] == {"type": "integer", "description": "Máximo"}
    assert safe["required"] == ["path"] and rea_like["properties"]["limit"]["type"] == ["integer", "null"]   # sin mutar

    def walk(x):
        if isinstance(x, dict):
            assert not isinstance(x.get("type"), list)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    class MCP:
        tools = {"rea_x": ({"name": "rea_x", "description": "d", "inputSchema": rea_like}, None)}

    sent = []
    chat.agent_turn([{"role": "user", "content": "hola"}], {"alias": "g"}, MCP(), lambda s: None,
                    request=lambda c, convo, tools: sent.append(tools) or {"content": "hola"})
    walk(sent[0])                                                     # nada llega al modelo con tipos en lista


def test_la_pregunta_no_desaparece_si_falla_el_envio():
    js = (__import__("pathlib").Path(__file__).parents[1] / "eolfi" / "web" / "eolas-chat.js").read_text(encoding="utf-8")
    assert "chat.messages.pop()" not in js and "user.failed = true" in js
    assert "!m.local && !m.failed" in js                               # lo no enviado no va al modelo


def test_ids_de_llamada_validos_para_la_plantilla_de_mistral():
    """13/11/2026: Mistral Small 3.2 rechaza (HTTP 400) IDs que no sean 9 caracteres alfanuméricos."""
    import re

    from eolfi.chat import safe_tool_calls

    seen = set()
    for turn in range(6):
        calls = safe_tool_calls([{"id": "call_" + "x" * 30, "function": {"name": "a"}}, {"function": {"name": "b"}}], turn)
        for tc in calls:
            assert re.fullmatch(r"[A-Za-z0-9]{9}", tc["id"]) and tc["id"] not in seen
            seen.add(tc["id"])
        assert calls[0]["function"] == {"name": "a"}


def test_el_chat_sabe_que_lo_que_ejecuta_se_pide_con_permiso():
    """14/11/2026: gemma dijo que capture_web_screenshot «no existe» sin buscarla: rea_usar decía «herramienta
    permitida» y el modelo entendía que las de ejecución le estaban vetadas. Se piden con rea_usar y Eolfi pide permiso."""
    from eolfi import chat, rea_client

    assert "rea_buscar" in chat.SYSTEM_PROMPT and "pide autorización" in chat.SYSTEM_PROMPT
    usar = rea_client.META_TOOLS["rea_usar"]["description"]
    assert "permitida" not in usar and "autorización" in usar
