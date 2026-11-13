"""Servidor MCP falso con forma de REA para las pruebas (JSON por líneas en stdin/stdout)."""
import json
import sys

TOOLS = [
    {"name": "inspect_byte_entropy", "description": "Entropía de un archivo",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "inspect_artifact", "description": "Sobre la sesión abierta",
     "inputSchema": {"type": "object", "properties": {"detail": {"type": "string"}}}},
    {"name": "decompile_all", "description": "Descompila todas las funciones a un directorio",
     "inputSchema": {"type": "object", "properties": {"output_directory": {"type": "string"}}}},
    {"name": "start_frida_session", "description": "Inicia Frida", "inputSchema": {"type": "object"}},
    {"name": "list_unknowns", "description": "Incógnitas", "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object"}},
]
for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue
    method, params = msg["method"], msg.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "rea-falso"}}
    elif method == "tools/list":
        result = {"tools": TOOLS[:3], "nextCursor": "2"} if not params.get("cursor") else {"tools": TOOLS[3:]}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": f"hecho {params['name']} {json.dumps(params['arguments'])}"}],
                  "isError": False}
    else:
        result = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}) + "\n")
    sys.stdout.flush()
