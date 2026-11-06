"""Eolfi → VS Code: acciones sobre el editor a través de la extensión puente (eolfi/vscode-bridge).

    from eolfi.vscode_tools import vscode_action
    vscode_action("open", path="D:/Eolfi/README.md", line=10)
    vscode_action("find", text="def triage")
    vscode_action("write", path="notas.md", content="…", reason="resumen del análisis")   # VS Code pide confirmación

Acciones: workspace, list, read, find, open, write, command; y tool (herramientas de VS Code permitidas en el
ajuste «eolfi.allowedTools»). Los límites (solo dentro del workspace, confirmación para escribir y abrir otras
carpetas, comandos en lista blanca) los aplica la extensión, en VS Code.
"""
from __future__ import annotations

from typing import Any

from eolfi.generador.llm import LLMError, _post, read_vscode_bridge

ACTIONS = ("workspace", "list", "read", "find", "open", "write", "command")


def vscode_action(action: str, timeout: float = 300.0, **params: Any) -> dict[str, Any]:
    if action not in ACTIONS and action != "tool":
        raise LLMError(f"acción de VS Code desconocida: {action} (opciones: {', '.join(ACTIONS)}, tool)")
    b = read_vscode_bridge()
    path = "/v1/tool" if action == "tool" else f"/v1/workspace/{action}"
    # Sin reintentos: write y command no deben repetirse.
    return _post(b["url"] + path, params, {"Authorization": f"Bearer {b['token']}"}, timeout, retries=0)
