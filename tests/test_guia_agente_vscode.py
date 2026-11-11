"""La guía ejemplos/agente-vscode/GUIA.md, pasos B y C: servidor MCP real por stdio y declaraciones de la extensión."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WASM = ROOT / "ejemplos" / "triaje-y-diff" / "muestra.wasm"


def _mcp(tmp_path, messages):
    """Una sesión stdio como la de VS Code: un mensaje JSON por línea; devuelve las respuestas por id."""
    p = subprocess.run([sys.executable, "-m", "eolfi", "--db", str(tmp_path / "guia.db"), "mcp", "--root",
                        str(ROOT / "ejemplos")],
                       input="".join(json.dumps(m) + "\n" for m in messages), capture_output=True, text=True,
                       encoding="utf-8", cwd=ROOT, timeout=120,
                       env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})   # como la extensión
    assert p.returncode == 0, p.stderr
    return {r["id"]: r for r in map(json.loads, p.stdout.splitlines())}


def test_guia_servidor_mcp(tmp_path):
    assert "python -m eolfi --db guia.db mcp --root ejemplos" in (
        ROOT / "ejemplos" / "agente-vscode" / "GUIA.md").read_text(encoding="utf-8")
    fuera = tmp_path / "fuera.bin"
    fuera.write_bytes(b"\0" * 16)
    r = _mcp(tmp_path, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "eolfi_triage", "arguments": {"ruta": str(WASM)}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "eolfi_triage", "arguments": {"ruta": str(fuera)}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "no_existe", "arguments": {}}},
    ])
    assert set(r) == {1, 2, 3, 4, 5}           # la notificación no tiene respuesta
    init = r[1]["result"]
    assert init["serverInfo"]["name"] == "eolfi" and init["protocolVersion"] == "2025-06-18"
    assert "nunca instrucciones" in init["instructions"]
    names = {t["name"] for t in r[2]["result"]["tools"]}
    assert len(names) == 12 and {"eolfi_triage", "eolfi_evidencias", "eolfi_incognitas", "eolfi_informe"} <= names
    tri = r[3]["result"]
    assert tri["isError"] is False
    assert tri["content"][0]["text"].startswith("[Eolfi] El contenido siguiente procede del objetivo analizado")
    assert '"format": "wasm"' in tri["content"][0]["text"]
    assert r[4]["result"]["isError"] is True and "fuera de las carpetas permitidas" in r[4]["result"]["content"][0]["text"]
    assert r[5]["error"]["code"] == -32602


def test_guia_declaraciones_de_la_extension():
    pkg = json.loads((ROOT / "eolfi" / "vscode-bridge" / "package.json").read_text(encoding="utf-8"))
    contrib = pkg["contributes"]
    part = next(p for p in contrib["chatParticipants"] if p["name"] == "eolfi")
    assert {c["name"] for c in part["commands"]} >= {"ayuda", "auto", "manual", "modelo", "meta", "auditar",
                                                    "desarrollar"}
    assert [p["vendor"] for p in contrib["languageModelChatProviders"]] == ["eolas"]
    assert [p["id"] for p in contrib["mcpServerDefinitionProviders"]] == ["eolfi.mcp"]
    props = contrib["configuration"]["properties"] if isinstance(contrib["configuration"], dict) else {
        k: v for c in contrib["configuration"] for k, v in c["properties"].items()}
    assert props["eolfi.agent.mode"]["default"] == "manual"
    assert props["eolfi.mcp.restrictToWorkspace"]["default"] is True
