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


@pytest.mark.parametrize("salida,con_kuna", [("/n/node|/home/u|kuna", True), ("/n/node|/home/u|", False),
                                              ("/n/node|/home/u", False)])
def test_el_rea_de_wsl_recibe_kuna_si_esta_instalado(monkeypatch, salida, con_kuna):
    """15/11/2026: instalar-rea-wsl.sh deja ~/.local/eolfi-rea/kuna; Eolfi se lo pasa a REA como REA_KUNA_COMMAND."""
    import subprocess

    monkeypatch.delenv("EOLFI_NO_REA", raising=False)
    monkeypatch.setattr(rea_client.shutil, "which", lambda name: "wsl.exe")
    monkeypatch.setattr(rea_client.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=salida + "\n", stderr=""))
    cmd = rea_client.wsl_rea_command()
    assert cmd[:4] == ["wsl.exe", "-e", "env", "REA_WAKARU_COMMAND=/home/u/.local/eolfi-rea/wakaru/wakaru"]
    assert cmd[-3:] == ["/n/node/bin/node", "/home/u/.local/eolfi-rea/npm/node_modules/rea-agents/scripts/rea.mjs", "mcp"]
    assert rea_client.wsl_has_kuna(cmd) is con_kuna
    assert ("REA_KUNA_COMMAND=/home/u/.local/eolfi-rea/kuna" in cmd) is con_kuna


def test_cli_motor_kuna_sin_kuna_lo_explica(monkeypatch, tmp_path, capsys):
    from eolfi import cli

    monkeypatch.setattr(rea_client, "wsl_rea_command", lambda: ["wsl.exe", "-e", "env", "REA_WAKARU_COMMAND=w", "n", "r", "mcp"])
    code = cli.main(["--db", str(tmp_path / "e.db"), "rea", "explicar", str(tmp_path / "x.elf"), "--motor", "kuna"])
    assert code == 2 and "instalar-rea-wsl.sh" in capsys.readouterr().err


def test_cli_error_de_rea_sin_traza(monkeypatch, tmp_path, capsys):
    from eolfi import cli, rea_compuestas

    class Rea:
        def __init__(self, *a, **k):
            pass

        def close(self):
            pass

    def falla(*a, **k):
        raise RuntimeError('REA open_binary: {"error":{"category":"unsupported_provider"}}')

    monkeypatch.setattr(rea_client, "wsl_rea_command", lambda: ["wsl.exe", "-e", "env", "REA_KUNA_COMMAND=k", "mcp"])
    monkeypatch.setattr(rea_client, "ReaClient", Rea)
    monkeypatch.setattr(rea_compuestas, "explicar_binario", falla)
    monkeypatch.delenv("EOLFI_DEBUG", raising=False)
    code = cli.main(["--db", str(tmp_path / "e.db"), "rea", "explicar", str(tmp_path / "x.exe"), "--motor", "kuna"])
    err = capsys.readouterr().err
    assert code == 1 and "Traceback" not in err and "para PE usa --motor ghidra" in err
