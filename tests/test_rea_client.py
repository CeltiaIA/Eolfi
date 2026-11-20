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


def test_wsl_rea_command_pasa_binwalk_y_unblob_si_estan(monkeypatch):
    import subprocess

    from eolfi import rea_client

    home = "/home/u"
    base = f"{home}/.local/eolfi-rea"
    lines = {"ambos": f"{base}/node-v1-linux-x64|{home}|{base}/binwalk-3.1.0/bin/binwalk|{base}/unblob-26.6.4/eolfi-unblob",
             "ninguno": f"{base}/node-v1-linux-x64|{home}||",
             "ajeno": f"{base}/node-v1-linux-x64|{home}|/tmp/binwalk|/tmp/unblob"}
    monkeypatch.delenv("EOLFI_NO_REA", raising=False)
    monkeypatch.setattr(rea_client.shutil, "which", lambda name: "C:/Windows/wsl.exe")
    for case, line in lines.items():
        monkeypatch.setattr(rea_client.subprocess, "run",
                            lambda *a, _l=line, **k: subprocess.CompletedProcess(a, 0, stdout=_l + "\n", stderr=""))
        cmd = rea_client.wsl_rea_command()
        envs = [c for c in cmd if c.startswith("REA_") and "WAKARU" not in c]
        if case == "ambos":
            assert envs == [f"REA_BINWALK_COMMAND={base}/binwalk-3.1.0/bin/binwalk",
                            f"REA_UNBLOB_COMMAND={base}/unblob-26.6.4/eolfi-unblob"]
        else:  # sin instalar, o fuera de ~/.local/eolfi-rea: no se pasa
            assert envs == []
        assert cmd[-1] == "mcp"


def test_rea_env_pasa_wabt_si_esta_instalado(tmp_path, monkeypatch):
    import os

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("REA_WABT_BIN_DIRECTORY", raising=False)
    assert "REA_WABT_BIN_DIRECTORY" not in rea_client.rea_env()
    bin_ = tmp_path / ".eolfi" / "tools" / rea_client.WABT_DIR / "bin"
    bin_.mkdir(parents=True)
    exe = ".exe" if os.name == "nt" else ""
    (bin_ / f"wasm-validate{exe}").write_bytes(b"")
    assert "REA_WABT_BIN_DIRECTORY" not in rea_client.rea_env()  # falta wasm-objdump
    (bin_ / f"wasm-objdump{exe}").write_bytes(b"")
    assert "REA_WABT_BIN_DIRECTORY" not in rea_client.rea_env()  # falta wasm2wat
    (bin_ / f"wasm2wat{exe}").write_bytes(b"")
    assert rea_client.rea_env()["REA_WABT_BIN_DIRECTORY"] == str(bin_)
    monkeypatch.setenv("REA_WABT_BIN_DIRECTORY", "/otra")
    assert rea_client.rea_env()["REA_WABT_BIN_DIRECTORY"] == "/otra"  # la del usuario manda


def test_rea_env_no_hereda_credenciales_pero_si_ajustes_de_rea_y_del_sistema(monkeypatch):
    """Lista blanca (20/11): fuera credenciales con nombres imprevistos; dentro REA_* no secretos y lo del sistema."""
    for k, v in {"AWS_ACCESS_KEY_ID": "x", "GITHUB_PAT": "x", "OPENAI_API_KEY": "x", "MI_SERVICIO": "x",
                 "REA_API_TOKEN": "x", "REA_ANALYSIS_TIMEOUT_MS": "9000", "SYSTEMDRIVE": "C:",
                 "PATH": "/bin"}.items():
        monkeypatch.setenv(k, v)
    env = rea_client.rea_env()
    assert not {"AWS_ACCESS_KEY_ID", "GITHUB_PAT", "OPENAI_API_KEY", "MI_SERVICIO", "REA_API_TOKEN"} & set(env)
    assert env["REA_ANALYSIS_TIMEOUT_MS"] == "9000" and env["SYSTEMDRIVE"] == "C:" and "PATH" in env


def test_wsl_rea_ghidra_command_anade_ghidra_y_java_o_none(monkeypatch):
    import subprocess

    base = ["wsl.exe", "-e", "env", "REA_WAKARU_COMMAND=/h/w", "/h/node", "/h/rea.mjs", "mcp"]
    jdk = "/home/u/.local/eolfi-rea/jdk21/usr/lib/jvm/java-21-openjdk-amd64"
    scripts = []

    def run(argv, **kw):
        scripts.append(argv[4])   # bash -c SCRIPT rea-ghidra RUTA: la ruta va aparte, nunca dentro del script
        assert argv[5] == "rea-ghidra" and argv[6].startswith("/mnt/d/tools/ghidra") and "/mnt/" not in argv[4]
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

    monkeypatch.setattr(rea_client, "wsl_rea_command", lambda: list(base))
    monkeypatch.setattr(rea_client.subprocess, "run", run)
    out = jdk + "\n"
    cmd = rea_client.wsl_rea_ghidra_command(r"D:\tools\ghidra_12.1.4_PUBLIC")
    assert cmd[:6] == ["wsl.exe", "-e", "env", "GHIDRA_INSTALL_DIR=/mnt/d/tools/ghidra_12.1.4_PUBLIC",
                       f"JAVA_HOME={jdk}", f"PATH={jdk}/bin:/usr/bin:/bin"]
    assert cmd[6] == f"REA_GHIDRA_STARTUP_TIMEOUT_MS={rea_client.GHIDRA_STARTUP_MS}"
    assert cmd[7] == f"GHIDRA_MAXMEM={rea_client.GHIDRA_MAX_HEAP}"
    assert cmd[8] == f"REA_MCP_MAX_RESPONSE_BYTES={rea_client.GHIDRA_MAX_RESPONSE_BYTES}"
    assert cmd[9:] == base[3:] and "linux_x86_64/decompile" in scripts[-1]
    out = ""   # falta Java o Ghidra en WSL
    assert rea_client.wsl_rea_ghidra_command(r"D:\tools\ghidra") is None
    out = "/tmp/otro-java\n"
    assert rea_client.wsl_rea_ghidra_command(r"D:\tools\ghidra") is None
    monkeypatch.delenv("GHIDRA_INSTALL_DIR", raising=False)
    assert rea_client.wsl_rea_ghidra_command() is None
    monkeypatch.setattr(rea_client, "wsl_rea_command", lambda: None)
    assert rea_client.wsl_rea_ghidra_command(r"D:\tools\ghidra") is None


def test_wsl_swift_demangle_una_salida_por_nombre_o_none(monkeypatch):
    import subprocess

    seen = {}

    def run(argv, **kw):
        seen["input"], seen["script"] = kw["input"], argv[-1]
        lines = kw["input"].splitlines()
        return subprocess.CompletedProcess(argv, code, stdout="".join(f"D:{n}\n" for n in lines[:keep]), stderr="")

    monkeypatch.delenv("EOLFI_NO_REA", raising=False)
    monkeypatch.setattr(rea_client.shutil, "which", lambda name: "wsl.exe")
    monkeypatch.setattr(rea_client.subprocess, "run", run)
    code, keep = 0, 9
    assert rea_client.wsl_swift_demangle(["$sA", "$sB\nC"]) == ["D:$sA", "D:$sB C"]
    assert seen["input"] == "$sA\n$sB C\n" and rea_client.WSL_SWIFT_DEMANGLE in seen["script"]
    keep = 1   # falta una salida: no se emparejan mal
    assert rea_client.wsl_swift_demangle(["$sA", "$sB"]) is None
    code, keep = 1, 9   # no instalado
    assert rea_client.wsl_swift_demangle(["$sA"]) is None
    assert rea_client.wsl_swift_demangle([]) == []
    monkeypatch.setenv("EOLFI_NO_REA", "1")
    assert rea_client.wsl_swift_demangle(["$sA"]) is None
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


def test_wsl_rea_sigrok_command_anade_sigrok_o_none(monkeypatch):
    import subprocess

    base = ["wsl.exe", "-e", "env", "REA_WAKARU_COMMAND=/h/w", "/h/node", "/h/rea.mjs", "mcp"]
    launcher = "/home/u/.local/eolfi-rea/" + rea_client.WSL_SIGROK
    out = launcher + "\n"
    scripts = []

    def run(argv, **kw):
        scripts.append(argv[-1])
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

    monkeypatch.setattr(rea_client, "wsl_rea_command", lambda: list(base))
    monkeypatch.setattr(rea_client.subprocess, "run", run)
    cmd = rea_client.wsl_rea_sigrok_command()
    assert cmd == [*base[:3], f"REA_SIGROK_COMMAND={launcher}", *base[3:]]
    assert "/usr/bin/prlimit" in scripts[-1]
    out = ""   # falta el lanzador o prlimit
    assert rea_client.wsl_rea_sigrok_command() is None
    out = "/tmp/otro\n"
    assert rea_client.wsl_rea_sigrok_command() is None
    monkeypatch.setattr(rea_client, "wsl_rea_command", lambda: None)
    assert rea_client.wsl_rea_sigrok_command() is None
