"""REA en el chat de Eolas V2: catálogo completo, escritura permitida y ejecución bloqueada (13/11/2026)."""
import sys
from pathlib import Path

import pytest

from eolfi import chat, rea_client

FAKE = [sys.executable, str(Path(__file__).parent / "fixtures" / "fake_rea_mcp.py")]


@pytest.fixture
def tools():
    client = rea_client.ReaClient(FAKE, timeout=20)
    checked = []

    def check(path):
        checked.append(path)
        if "prohibida" in path:
            raise ValueError("ruta fuera de las carpetas permitidas")

    t = rea_client.ReaTools(client, check_path=check)
    t.checked = checked
    yield t
    client.close()


def test_cliente_pagina_el_catalogo_y_ofrece_estaticas_por_ruta_y_meta(tools):
    assert set(tools.catalog) == {"inspect_byte_entropy", "inspect_artifact", "decompile_all", "start_frida_session",
                                  "list_unknowns"}                                  # dos páginas de tools/list
    assert set(tools.tools) == {"rea_inspect_byte_entropy", "rea_buscar", "rea_ayuda", "rea_usar"}
    text, ok = tools.call_tool("rea_inspect_byte_entropy", {"path": "C:/datos/x.bin"})
    assert ok and text.startswith("[REA]") and "DATOS no confiables" in text and "hecho inspect_byte_entropy" in text
    assert tools.checked == ["C:/datos/x.bin"]


def test_catalogo_vivo_escritura_permitida_y_ejecucion_bloqueada(tools):
    found, ok = tools.call_tool("rea_buscar", {"consulta": "descompila funciones"})
    assert ok and "decompile_all" in found and "escritura" in found
    text, ok = tools.call_tool("rea_usar", {"nombre": "decompile_all", "argumentos": {"output_directory": "C:/salida"}})
    assert ok and "hecho decompile_all" in text and tools.checked == ["C:/salida"]       # escribir: sí, con ruta válida
    text, ok = tools.call_tool("rea_usar", {"nombre": "decompile_all", "argumentos": {"output_directory": "C:/prohibida"}})
    assert not ok and "fuera de las carpetas" in text
    text, ok = tools.call_tool("rea_usar", {"nombre": "start_frida_session", "argumentos": {}})
    assert not ok and "Bloqueada" in text                                                 # ejecutar: nunca solo
    assert not tools.call_tool("rea_usar", {"nombre": "inventada", "argumentos": {}})[1]
    assert "esquema" in tools.call_tool("rea_ayuda", {"nombre": "decompile_all"})[0]


def test_eolas_usa_rea_desde_el_chat(tools):
    import json as _json

    class MCP:
        tools = {}

    box = chat.Toolbox(MCP(), {}, rea=tools)
    replies = iter([{"tool_calls": [{"id": "1", "function": {"name": "rea_usar", "arguments": _json.dumps(
        {"nombre": "decompile_all", "argumentos": {"output_directory": "C:/salida"}})}}]}, {"content": "Descompilado."}])
    sent = []
    out = chat.agent_turn([{"role": "user", "content": "descompila"}], {"alias": "g"}, box, lambda s: None,
                          request=lambda c, convo, t: sent.append(t) or next(replies))
    assert out["text"] == "Descompilado." and out["tools"][0]["ok"]
    assert {"rea_buscar", "rea_usar", "rea_inspect_byte_entropy"} <= {t["function"]["name"] for t in sent[0]}


def test_sin_rea_instalado_el_chat_sigue(monkeypatch):
    monkeypatch.setenv("EOLFI_NO_REA", "1")
    assert rea_client.rea_command() is None
    assert rea_client.blocked("capture_process_scenario") and rea_client.blocked("install_adb_package")
    assert not rea_client.blocked("decompile_all") and not rea_client.blocked("inspect_adb_client")
