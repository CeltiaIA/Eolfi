"""Chat del panel: el motor Eolas V2 decide qué herramientas de Eolfi usar y Eolfi las ejecuta."""
import hashlib
import json

import pytest

from eolfi import chat


class FakeMCP:
    def __init__(self, db=None, roots=None, library=None):
        self.roots, self.calls = roots, []
        self.tools = {n: ({"name": n, "description": "d", "inputSchema": {"type": "object"}}, None)
                      for n in (*chat.CHAT_TOOLS, "herramienta_no_ofrecida")}

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


def test_una_ruta_gguf_escrita_en_el_mensaje_lleva_la_pista_del_auditor():
    # 20/11/2026: desde la tableta, «Audita el modelo … pesos.gguf» no llevaba pista y el modelo no auditaba.
    ruta = r"D:\Alejandria\corpus\modelos.gguf\objetos\sha256\32\32c5\pesos.gguf"
    msgs = chat.with_context([{"role": "user", "content": f"Audita el modelo Gemma 4 Q5 en {ruta}"}], [], None)
    text = msgs[-1]["content"]
    assert f"- Ruta de modelo en el mensaje: {ruta} (modelo GGUF: usa eolfi_modelos_auditar" in text
    assert chat.rutas_gguf(r"en \\srv\m\y.gguf, /home/a/b.GGUF y C:/m/x.gguf.") == [
        r"\\srv\m\y.gguf", "/home/a/b.GGUF", "C:/m/x.gguf"]
    assert chat.rutas_gguf(r"nada.gguf D:\a\b.ggufx D:\a\c.gguf.bak") == []
    assert chat.rutas_gguf(" ".join([f"C:/m/{i}.gguf" for i in range(9)] + ["C:/m/0.gguf"])) == [
        f"C:/m/{i}.gguf" for i in range(5)]
    # Si ya va como adjunto o como objetivo de análisis, no se repite.
    msgs = chat.with_context([{"role": "user", "content": f"mira {ruta}"}], [], {"kind": "archivo", "target": ruta})
    assert msgs[-1]["content"].count(ruta) == 2   # en el mensaje y en «Analiza también…», no una tercera vez
    # Un mensaje sin rutas .gguf queda igual.
    assert chat.with_context([{"role": "user", "content": "hola"}], [], None) == [{"role": "user", "content": "hola"}]


def test_chat_can_call_real_gguf_auditor_without_loading_model(tmp_path):
    from tests.test_modelos import fixture
    from eolfi.mcp_server import DATA_NOTE, EolfiMCP

    upload = fixture(tmp_path / "upload.bin")
    digest = hashlib.sha256(upload.read_bytes()).hexdigest()
    folder = tmp_path / digest
    folder.mkdir()
    path = upload.rename(folder / upload.name)
    mcp = EolfiMCP(db=str(tmp_path / "no-db.db"), roots=[str(tmp_path)])
    replies = iter([{"tool_calls": [_call("eolfi_modelos_auditar", {"ruta": str(path)})]},
                    {"content": "Auditoría estructural; no demuestra seguridad de pesos."}])
    sent = []
    result = chat.agent_turn([{"role": "user", "content": "Audita el GGUF adjunto"}], {"alias": "prueba"}, mcp,
                             lambda message: None,
                             request=lambda c, convo, tools: sent.append(list(convo)) or next(replies))
    assert result["tools"][0]["name"] == "eolfi_modelos_auditar" and result["tools"][0]["ok"]
    tool_text = next(m["content"] for m in sent[1] if m.get("role") == "tool")
    audit = json.loads(tool_text.removeprefix(DATA_NOTE))
    assert audit["sha256"] == digest
    assert audit["estado"] == "estructura_verificada"
    assert audit["procedencia"] == "NO VERIFICADO"
    assert not (tmp_path / "no-db.db").exists()


def test_gguf_context_uses_auditor_instead_of_native_decompiler():
    result = chat.with_context([{"role": "user", "content": "analiza"}],
                               [{"name": "Pesos.GGUF", "path": "/samples/hash.bin", "kind": "binario"}],
                               {"kind": "archivo", "target": "/models/local.gguf"})
    text = result[-1]["content"]
    assert text.count("eolfi_modelos_auditar") == 2
    assert "modo profundo" not in text
    assert "sin cargarlo" in text


def test_eolas_decide_las_herramientas_y_eolfi_las_ejecuta():
    mcp, steps, sent = FakeMCP(), [], []
    replies = iter([
        {"tool_calls": [_call("eolfi_triage", {"ruta": "C:/s/ab.bin"}), _call("ejecutar_python", {"codigo": "print(2)"}, "2"),
                        _call("herramienta_no_ofrecida", {}, "3")]},
        {"content": "Es un PE de Windows. Propuestas: 1) …"},
    ])
    out = chat.agent_turn([{"role": "user", "content": "analiza"}], {"alias": "gemma", "url": "u"}, mcp, steps.append,
                          request=lambda c, convo, tools: sent.append((list(convo), tools)) or next(replies),
                          run_python=lambda code: ("2", True))
    assert out["text"].startswith("Es un PE")
    offered = {t["function"]["name"] for t in sent[0][1]}
    assert offered == {*chat.CHAT_TOOLS, "ejecutar_python"}                 # nunca las que no son del chat
    assert [(c["name"], c["ok"]) for c in out["tools"]] == [("eolfi_triage", True), ("ejecutar_python", True),
                                                           ("herramienta_no_ofrecida", False)]
    assert mcp.calls == [("eolfi_triage", {"ruta": "C:/s/ab.bin"})]          # la no ofrecida no se ejecuta
    assert sent[0][0][0]["role"] == "system" and "DATOS" in sent[0][0][0]["content"]
    assert any("Consulto eolfi_triage" in s for s in steps)


def test_si_agota_las_rondas_pide_respuesta_final_sin_herramientas():
    sent = []

    def request(c, convo, tools):
        sent.append(tools)
        return ({"content": "Resumen."} if not tools or isinstance(tools, chat.Ninguna)
                else {"tool_calls": [_call("eolfi_biblioteca_buscar", {"consulta": "x"})]})

    out = chat.agent_turn([{"role": "user", "content": "x"}], {"alias": "g", "url": "u"}, FakeMCP(), lambda s: None,
                          request=request, max_rounds=2)
    # 21/11/2026: la vuelta final envía las mismas herramientas con tool_choice «none» (prefijo en caché).
    assert out["text"] == "Resumen." and isinstance(sent[-1], chat.Ninguna) and len(out["tools"]) == 2


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
    monkeypatch.setattr(app, "_chat_estado", lambda: {"vscode": {"activo": False}})
    monkeypatch.setattr(chat, "agent_turn", lambda msgs, c, mcp, progress, estado=None, **_dirigir:
                        seen.update(msgs=msgs, c=c, mcp=mcp, estado=estado) or
                        {"text": "Propuestas…", "tools": [{"name": "eolfi_triage", "args": "{}", "ok": True}]})
    out = app.chat({"messages": [{"role": "user", "content": "¿Qué genero?"}],
                    "attachments": [{"upload": "a" * 64, "name": "x.exe", "kind": "binario"}],
                    "analyze": {"kind": "url", "target": "https://example.com"}})
    assert out["text"] == "Propuestas…" and out["model"].startswith("gemma-q4") and used == ["gemma_q4"]
    assert seen["c"]["headers"] == {"Authorization": f"Bearer {eolas_v2.api_key()}"}       # Eolas V2 con su clave
    assert seen["c"]["endpoint"] == "http://127.0.0.1:8090/v1/chat/completions"
    con_nombre = app.samples / "adjuntos" / ("a" * 64) / "x.exe"           # con su nombre y extensión reales
    assert str(con_nombre) in seen["msgs"][-1]["content"] and con_nombre.read_bytes() == b"MZ"
    assert seen["mcp"].adjuntos == {"x.exe": str(con_nombre)}
    assert seen["estado"] == {"vscode": {"activo": False}}                 # el chat recibe el estado real

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
    assert "eolfi_inventada" not in box.tools and "herramienta_no_ofrecida" not in box.tools
    assert "eolfi_resolver" in box.tools
    assert {"eolfi_triage", "eolfi_proponer_proyecto", "eolfi_objetivos"} <= set(box.tools)
    replies = iter([{"tool_calls": [_call("eolfi_proponer_proyecto", {"nombre": "x", "descripcion": "y"}),
                                    _call("eolfi_triage", {"ruta": "a"}, "2"), _call("eolfi_objetivos", {}, "3")]},
                    {"content": "Te propongo un plan."}])
    out = chat.agent_turn([{"role": "user", "content": "crea"}], {"alias": "g"}, box, lambda s: None,
                          request=lambda c, convo, tools: next(replies))
    assert hechas == [{"nombre": "x", "descripcion": "y"}]
    assert out["tools"][0]["proyecto"] == "c-1" and out["tools"][0]["ok"]
    assert out["tools"][2]["ok"] is False                                # el error llega al modelo como dato
    assert out["tools"][2]["error"].startswith("Error") and "error" not in out["tools"][0]   # y queda en la traza
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


def test_el_chat_ofrece_todo_el_catalogo_mcp_actual(tmp_path):
    from eolfi.mcp_server import EolfiMCP

    mcp = EolfiMCP(db=str(tmp_path / "e.db"), roots=[str(tmp_path)])
    box = chat.Toolbox(mcp, {})
    assert set(box.tools) == set(mcp.tools) == set(chat.CHAT_TOOLS)
    assert box.call_tool("herramienta_no_ofrecida", {})["isError"] is True


@pytest.mark.parametrize("nombre", chat.CHAT_TOOLS)
def test_cada_herramienta_se_ofrece_se_ejecuta_y_devuelve_datos_al_motor(nombre):
    mcp, sent = FakeMCP(), []
    replies = iter([{"tool_calls": [_call(nombre, {"prueba": nombre})]}, {"content": "Resultado leído."}])
    out = chat.agent_turn([{"role": "user", "content": "analiza"}], {"alias": "g"}, mcp, lambda s: None,
                          request=lambda c, convo, tools: sent.append(list(convo)) or next(replies))
    assert mcp.calls == [(nombre, {"prueba": nombre})]
    assert out["tools"][0]["name"] == nombre and out["tools"][0]["ok"]
    assert out["tools"][0]["valid_args"] is True
    assert json.loads(sent[-1][-1]["content"])["summary"]["format"] == "pe"
    assert out["ejecucion"] == {"recuperaciones": 0, "llamadas": 1, "correctas": 1}


def test_promesa_sin_llamadas_se_recupera_ejecutando_y_leyendo_el_resultado():
    mcp, sent, steps = FakeMCP(), [], []
    replies = iter([{"content": "Iniciando la auditoría del modelo."},
                    {"tool_calls": [_call("eolfi_modelos_auditar", {"ruta": "D:/modelo.gguf"})]},
                    {"content": "He consultado el resultado de la auditoría."}])
    out = chat.agent_turn([{"role": "user", "content": "Audita D:/modelo.gguf"}], {"alias": "g"}, mcp, steps.append,
                          request=lambda c, convo, tools: sent.append((list(convo), tools)) or next(replies))
    assert mcp.calls == [("eolfi_modelos_auditar", {"ruta": "D:/modelo.gguf"})]
    assert all(t for _, t in sent) and sent[-1][0][-1]["role"] == "tool"
    assert out["ejecucion"] == {"recuperaciones": 1, "llamadas": 1, "correctas": 1}
    assert out["revision"]["inicial"] == ["accion_en_curso"] and out["revision"]["final"] == []


@pytest.mark.parametrize("primera", [{"content": ""}, {"content": "¿Quieres que lo audite?"}])
def test_orden_sin_llamada_recibe_una_sola_recuperacion_y_no_finge_ejecucion(primera):
    sent, mcp = [], FakeMCP()
    replies = iter([primera, {"content": "Necesito que me indiques la ruta del archivo."}])
    out = chat.agent_turn([{"role": "user", "content": "Audita el archivo"}], {"alias": "g"}, mcp, lambda s: None,
                          request=lambda c, convo, tools: sent.append(tools) or next(replies))
    assert len(sent) == 2 and all(sent) and not mcp.calls
    assert out["text"].startswith("(No he llegado a ejecutar ninguna herramienta")
    assert out["ejecucion"]["correctas"] == 0 and out["ejecucion"]["recuperaciones"] == 1


def test_la_recuperacion_de_una_orden_obliga_a_llamar_y_solo_esa_vuelta():
    """20/11/2026, tableta: con «auto» Gemma inventaba el resultado y en la recuperación se quedaba en bucle."""
    sent = []
    replies = iter([{"content": "Los proveedores son stdlib y capa."},
                    {"tool_calls": [_call("eolfi_doctor", {})]}, {"content": "Proveedores comprobados."}])
    out = chat.agent_turn([{"role": "user", "content": "Lista proveedores. Usa eolfi_doctor."}], {"alias": "g"},
                          FakeMCP(), lambda s: None, request=lambda c, convo, tools: sent.append(tools) or next(replies))
    assert [isinstance(t, chat.Obligatorias) for t in sent] == [False, True, False]
    assert sent[1] == sent[0] and out["ejecucion"] == {"recuperaciones": 1, "llamadas": 1, "correctas": 1}


def test_una_respuesta_solo_vacia_no_obliga_a_ejecutar():
    sent = []
    replies = iter([{"content": ""}, {"content": "Hola."}])
    chat.agent_turn([{"role": "user", "content": "hola"}], {"alias": "g"}, FakeMCP(), lambda s: None,
                    request=lambda c, convo, tools: sent.append(tools) or next(replies))
    assert len(sent) == 2 and not any(isinstance(t, chat.Obligatorias) for t in sent)


def test_el_motor_recibe_tool_choice_required_solo_con_obligatorias(monkeypatch):
    enviados = []

    class Resp:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self.data

    class Opener:
        def open(self, req, timeout=0):
            enviados.append(json.loads(req.data))
            return Resp(b'{"choices": [{"message": {"content": "ok"}}]}')

    monkeypatch.setattr(chat.urllib.request, "build_opener", lambda *a: Opener())
    herramientas = [{"type": "function", "function": {"name": "eolfi_doctor", "parameters": {"type": "object"}}}]
    motor = {"alias": "g", "endpoint": "http://127.0.0.1:1/v1/chat/completions", "kind": "eolas-v2"}
    chat._request(motor, [{"role": "user", "content": "x"}], herramientas)
    chat._request(motor, [{"role": "user", "content": "x"}], chat.Obligatorias(herramientas))
    chat._request(motor, [{"role": "user", "content": "x"}], [])
    assert [e.get("tool_choice") for e in enviados] == ["auto", "required", None]
    assert enviados[1]["tools"] == herramientas and "tools" not in enviados[2]


def test_pregunta_teorica_no_fuerza_herramientas():
    sent = []
    out = chat.agent_turn([{"role": "user", "content": "¿Para qué sirve una auditoría GGUF?"}], {"alias": "g"},
                          FakeMCP(), lambda s: None,
                          request=lambda c, convo, tools: sent.append(tools) or {"content": "Comprueba la estructura."})
    assert len(sent) == 1 and not out["tools"] and out["ejecucion"]["recuperaciones"] == 0


def test_argumentos_invalidos_no_se_ejecutan_y_el_motor_puede_corregirlos():
    mcp, sent = FakeMCP(), []
    mala = _call("eolfi_evidencias", {})
    mala["function"]["arguments"] = {"no": "texto JSON"}
    replies = iter([{"tool_calls": [mala]}, {"tool_calls": [_call("eolfi_evidencias", {"limite": 1})]},
                    {"content": "Consulta completada."}])
    out = chat.agent_turn([{"role": "user", "content": "Lista las evidencias"}], {"alias": "g"}, mcp, lambda s: None,
                          request=lambda c, convo, tools: sent.append(list(convo)) or next(replies))
    assert mcp.calls == [("eolfi_evidencias", {"limite": 1})]
    assert out["tools"][0]["valid_args"] is False and out["tools"][0]["ok"] is False
    assert "no son un objeto JSON" in sent[1][-1]["content"]
    assert out["tools"][1]["ok"] is True


def test_error_de_herramienta_no_cuenta_como_paso_correcto():
    mcp = FakeMCP()
    mcp.call_tool = lambda name, args: {"isError": True, "content": [{"type": "text", "text": "Error: no existe"}]}
    replies = iter([{"tool_calls": [_call("eolfi_modelos_auditar", {"ruta": "no.gguf"})]},
                    {"content": "El archivo no existe."}])
    out = chat.agent_turn([{"role": "user", "content": "Audita no.gguf"}], {"alias": "g"}, mcp, lambda s: None,
                          request=lambda *a: next(replies))
    assert out["ejecucion"]["correctas"] == 0 and out["tools"][0]["error"] == "Error: no existe"


@pytest.mark.parametrize("argumentos", [None, False, 0, [], {}, ""])
def test_argumentos_vacios_de_tipo_incorrecto_no_ejecutan(argumentos):
    mcp = FakeMCP()
    llamada = _call("eolfi_doctor", {})
    llamada["function"]["arguments"] = argumentos
    replies = iter([{"tool_calls": [llamada]}, {"content": "Argumentos inválidos; no se ejecutó."}])
    out = chat.agent_turn([{"role": "user", "content": "Lista proveedores"}], {"alias": "g"}, mcp,
                          lambda s: None, request=lambda *a: next(replies))
    assert not mcp.calls
    assert out["tools"][0]["valid_args"] is False
    assert out["ejecucion"]["correctas"] == 0


@pytest.mark.parametrize("respuesta", [None, [], {"choices": "texto"}, {"choices": [None]},
                                        {"choices": [{"message": []}]}])
def test_respuesta_del_motor_malformada_da_error_explicito(monkeypatch, respuesta):
    import io

    class Opener:
        def open(self, *args, **kwargs):
            return io.BytesIO(json.dumps(respuesta).encode())

    monkeypatch.setattr(chat.urllib.request, "build_opener", lambda *a: Opener())
    with pytest.raises(RuntimeError, match="respuesta.*inválida"):
        chat._request({"alias": "g", "endpoint": "http://127.0.0.1:1/chat"}, [], [])


@pytest.mark.parametrize("llamadas", ["texto", [None], [{"function": []}],
                                      [{"function": {"name": 3}}],
                                      [_call("eolfi_doctor", {}), {"function": "rota"}]])
def test_llamadas_malformadas_no_ejecutan_ni_parcialmente(llamadas):
    mcp = FakeMCP()
    with pytest.raises(RuntimeError, match="llamadas.*inválida"):
        chat.agent_turn([{"role": "user", "content": "Lista proveedores"}], {"alias": "g"}, mcp,
                        lambda s: None, request=lambda *a: {"tool_calls": llamadas})
    assert mcp.calls == []


def test_traza_conserva_estado_y_verificacion_del_encargo():
    mcp = FakeMCP()
    mcp.tools["eolfi_vscode_encargo_estado"] = ({"name": "eolfi_vscode_encargo_estado", "description": "d",
                                               "inputSchema": {"type": "object"}}, None)
    mcp.call_tool = lambda *a: {"content": [{"type": "text", "text": json.dumps({
        "id": "e1", "estado": "pendiente_aprobacion", "proyecto": {"verificado": False}})}]}
    replies = iter([{"tool_calls": [_call("eolfi_vscode_encargo_estado", {"encargo_id": "e1"})]},
                    {"content": "El encargo sigue pendiente."}])
    out = chat.agent_turn([{"role": "user", "content": "Consulta el encargo"}], {"alias": "g"}, mcp,
                          lambda s: None, request=lambda *a: next(replies))
    assert out["tools"][0]["encargo"] == "e1"
    assert out["tools"][0]["estado_encargo"] == "pendiente_aprobacion"
    assert out["tools"][0]["proyecto_verificado"] is False


# 21/11/2026: dirigir el hilo mientras trabaja, cortar con Parar y plan interno con razonamiento.
def test_un_mensaje_nuevo_durante_el_trabajo_entra_en_la_conversacion_con_prioridad():
    buzon, vistos, progreso = [["mejor busca y"]], [], []

    def request(c, convo, tools):
        vistos.append([m["content"] for m in convo if m["role"] == "user"])
        return ({"tool_calls": [_call("eolfi_biblioteca_buscar", {"consulta": "x"})]} if len(vistos) == 1
                else {"content": "Hecho con y."})

    out = chat.agent_turn([{"role": "user", "content": "busca x"}], {"alias": "g", "url": "u"}, FakeMCP(),
                          progreso.append, request=request, steer=lambda: buzon.pop() if buzon else [])
    assert out["text"] == "Hecho con y." and out["correcciones"] == ["mejor busca y"]
    assert any("tiene prioridad" in u and "mejor busca y" in u for u in vistos[0])
    assert any(p.startswith("Recibido:") for p in progreso)


def test_si_la_correccion_llega_cuando_iba_a_contestar_hace_otra_vuelta():
    buzon = [[], ["no, en castellano"]]
    respuestas = iter([{"content": "Answer."}, {"content": "Respuesta."}])
    out = chat.agent_turn([{"role": "user", "content": "hola"}], {"alias": "g", "url": "u"}, FakeMCP(),
                          lambda s: None, request=lambda c, convo, tools: next(respuestas),
                          steer=lambda: buzon.pop(0) if buzon else [])
    assert out["text"] == "Respuesta." and out["correcciones"] == ["no, en castellano"]


def test_parar_corta_una_llamada_larga_al_motor_en_el_acto():
    import threading, time
    liberar = threading.Event()

    def request(c, convo, tools):
        liberar.wait(10)
        return {"content": "tarde"}

    def vigilar():
        raise RuntimeError("cancelado por el usuario")

    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="cancelado"):
        chat.agent_turn([{"role": "user", "content": "hola"}], {"alias": "g", "url": "u"}, FakeMCP(),
                        lambda s: None, request=request, vigilar=vigilar)
    liberar.set()
    assert time.monotonic() - t0 < 3


def test_vigilado_devuelve_el_resultado_y_propaga_errores():
    assert chat.vigilado(lambda: 7, None) == 7
    assert chat.vigilado(lambda: 8, lambda: None) == 8
    with pytest.raises(ValueError):
        chat.vigilado(lambda: (_ for _ in ()).throw(ValueError("x")), lambda: None)


def test_plan_interno_solo_en_preguntas_abiertas_y_va_al_final_del_ultimo_mensaje():
    vistos, pedidos = [], []

    def plan(m):
        pedidos.append(m)
        return "Comparar ventajas y costes."

    def request(c, convo, tools):
        vistos.append(convo[-1]["content"])
        return {"content": "Depende de..."}

    out = chat.agent_turn([{"role": "user", "content": "¿Por qué conviene usar caché en el motor?"}],
                          {"alias": "g", "url": "u"}, FakeMCP(), lambda s: None, request=request, plan=plan)
    assert out["plan"] == "Comparar ventajas y costes." and "[Mi plan interno" in vistos[0]
    pedidos.clear()
    chat.agent_turn([{"role": "user", "content": "lista los proyectos"}], {"alias": "g", "url": "u"}, FakeMCP(),
                    lambda s: None, request=lambda c, convo, tools: (
                        {"content": "Lista."} if any(m["role"] == "tool" for m in convo)
                        else {"tool_calls": [_call("eolfi_biblioteca_buscar", {"consulta": "x"})]}), plan=plan)
    assert pedidos == []


def test_un_plan_que_falla_no_impide_contestar():
    def plan(m):
        raise RuntimeError("motor ocupado")
    out = chat.agent_turn([{"role": "user", "content": "¿Cómo funciona la caché del motor y por qué importa?"}],
                          {"alias": "g", "url": "u"}, FakeMCP(), lambda s: None,
                          request=lambda c, convo, tools: {"content": "Así."}, plan=plan)
    assert out["text"] == "Así." and "plan" not in out


def test_planificar_pide_razonamiento_sin_herramientas():
    visto = {}

    def request(c, mensajes, tools, timeout, **kw):
        visto.update(tools=tools, **kw)
        return {"content": "", "reasoning_content": "Primero miro X."}

    assert chat.planificar({"kind": "eolas-v2"}, [{"role": "user", "content": "¿por qué?"}], request=request) == \
        "Primero miro X."
    assert visto["tools"] == [] and visto["pensar"] is True


def test_request_traduce_ninguna_a_tool_choice_none(monkeypatch):
    enviado = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}).encode()

    class Opener:
        def open(self, req, timeout=None):
            enviado.update(json.loads(req.data))
            return Resp()

    monkeypatch.setattr(chat.urllib.request, "build_opener", lambda *a: Opener())
    tools = [{"type": "function", "function": {"name": "a", "parameters": {"type": "object"}}}]
    chat._request({"alias": "g", "endpoint": "http://127.0.0.1:1/v1/chat/completions", "kind": "eolas-v2"}, [],
                  chat.Ninguna(tools))
    assert enviado["tool_choice"] == "none" and enviado["tools"] and \
        enviado["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.parametrize("respuesta, esperado", [
    ({"content": "Empiezo a contestar", "reasoning_content": "Pienso X.", "_fin": "length"}, "Pienso X."),
    ({"content": "Respuesta a medias", "_fin": "length"}, ""),
    ({"content": "Plan: mirar X.", "_fin": "stop"}, "Plan: mirar X."),
])
def test_planificar_prefiere_el_razonamiento_y_descarta_respuestas_cortadas(respuesta, esperado):
    assert chat.planificar({"kind": "eolas-v2"}, [{"role": "user", "content": "x"}],
                           request=lambda *a, **k: respuesta) == esperado


def test_una_respuesta_cortada_por_el_tope_se_termina():
    """21/11/2026, titular: respuestas «cortas y cortadas». Si el motor se queda sin tokens, una vuelta más sin
    herramientas para que termine; el hilo no se queda con la petición de continuar."""
    vistos = []

    def request(c, messages, tools, *a, **k):
        vistos.append((len(messages), isinstance(tools, chat.Ninguna)))
        if len(vistos) == 1:
            return {"content": "El caso ilfy analiza el modelo Dory y tiene dos informes: el de", "_fin": "length"}
        return {"content": "funcionalidades y el de mejoras.", "_fin": "stop"}

    out = chat.agent_turn([{"role": "user", "content": "hola"}], {"alias": "x"}, type("M", (), {"tools": {}})(),
                          lambda m: None, request=request)
    assert out["text"] == "El caso ilfy analiza el modelo Dory y tiene dos informes: el de funcionalidades y el de mejoras."
    assert vistos[1][1] is True and vistos[1][0] == vistos[0][0] + 2
