"""Proveedores de modelo para el modo asistido (eolfi assist / create --ai).

- claude   SDK oficial de Anthropic (pip install eolfi[ai]); salida JSON estructurada.
- eolas    Motor local Eolas V1 (CeltIA), API compatible con Ollama en 127.0.0.1:11435.
- deepseek API oficial de DeepSeek (compatible OpenAI); clave en DEEPSEEK_API_KEY.
- gemini   API oficial de Gemini (endpoint compatible OpenAI); clave en GEMINI_API_KEY.
- openai   Cualquier servidor compatible OpenAI (--base-url, --model, clave en OPENAI_API_KEY).
- deepseek-web / gemini-web / meta-web
           Webs de chat a través del puente Electron de Eolfi (python -m eolfi bridge):
           tu sesión iniciada a mano y permiso en cada envío. Puede ir contra las
           condiciones de uso de esas webs: bajo tu cuenta y responsabilidad.

Las claves solo se leen de variables de entorno: nunca se guardan ni se registran.
La respuesta del modelo es DATO: se valida como JSON y las rutas se filtran
antes de escribir nada (ver eolfi.generador.assist).
"""
from __future__ import annotations

import json
import os
import re
import uuid
import urllib.error
from pathlib import Path
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


class LLMError(Exception):
    pass


@dataclass
class Reply:
    data: dict[str, Any]
    history_content: Any          # lo que se reenvía como turno "assistant" en una reparación
    usage: dict[str, int]
    model: str


PRESETS: dict[str, dict[str, Any]] = {
    "eolas": {"kind": "ollama", "base_url": os.environ.get("CELTIAIA_EOLAS_URL", "http://127.0.0.1:11435"),
              "model": os.environ.get("EOLAS_MODEL", "gemma-4-12b-it:latest"), "key_env": None,
              "context_bytes": 60_000},
    "deepseek": {"kind": "openai", "base_url": "https://api.deepseek.com", "model": "deepseek-chat",
                 "key_env": "DEEPSEEK_API_KEY", "json_mode": "json_object", "context_bytes": 200_000},
    "gemini": {"kind": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "model": os.environ.get("GEMINI_MODEL", "gemini-2.5-pro"), "key_env": "GEMINI_API_KEY",
               "json_mode": "json_schema", "context_bytes": 300_000},
    "openai": {"kind": "openai", "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
               "model": os.environ.get("OPENAI_MODEL", ""), "key_env": "OPENAI_API_KEY",
               "json_mode": "json_schema", "context_bytes": 200_000},
    "claude": {"kind": "claude", "context_bytes": 350_000},
    # Alias de compatibilidad: «gemma» usa el Gemma 12B servido por Eolas; no inicia un servidor paralelo.
    "gemma": {"kind": "ollama", "base_url": os.environ.get("CELTIAIA_EOLAS_URL", "http://127.0.0.1:11435"),
              "model": os.environ.get("EOLAS_MODEL", "gemma-4-12b-it:latest"), "context_bytes": 60_000},
    # Modelos de IA de VS Code (Language Model API, extensión eolfi/vscode-bridge). Modelo con
    # EOLFI_COPILOT_MODEL (familia, nombre o id; por defecto el primero que ofrezca VS Code) y herramientas de
    # VS Code con EOLFI_COPILOT_TOOLS (solo las que también permitas en el ajuste «eolfi.allowedTools»).
    "copilot-vscode": {"kind": "vscode", "model": os.environ.get("EOLFI_COPILOT_MODEL", ""), "context_bytes": 200_000},
    # Webs de chat vía el puente Electron (límite de 32 000 caracteres por mensaje).
    "deepseek-web": {"kind": "bridge", "site": "deepseek", "context_bytes": 14_000},
    "gemini-web": {"kind": "bridge", "site": "gemini", "context_bytes": 14_000},
    "meta-web": {"kind": "bridge", "site": "meta", "context_bytes": 14_000},
    # Adaptadores declarativos (grupo 3 de la Fase E): selectores sin calibrar hasta que pasan el autodiagnóstico.
    "chatgpt-web": {"kind": "bridge", "site": "chatgpt", "context_bytes": 14_000},
    "copilot-web": {"kind": "bridge", "site": "copilot", "context_bytes": 14_000},
    "lechat-web": {"kind": "bridge", "site": "lechat", "context_bytes": 14_000},
    # El primer chat web listo, prefiriendo los que tienen sesión iniciada.
    # Orden configurable con EOLFI_WEB_ORDER (por defecto meta,deepseek,gemini).
    "web": {"kind": "bridge", "site": "auto", "context_bytes": 14_000},
}


def bridge_status() -> dict[str, Any]:
    b = read_bridge()
    req = urllib.request.Request(b["url"] + "/v1/status", headers={"Authorization": f"Bearer {b['token']}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8")).get("providers", {})
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise LLMError("El puente no responde: arráncalo con  python -m eolfi bridge") from exc


def choose_web_site(status: dict[str, Any] | None = None) -> str:
    """Elige el chat web: primero los listos con sesión, luego los listos en modo invitado."""
    status = status if status is not None else bridge_status()
    order = [s.strip() for s in os.environ.get("EOLFI_WEB_ORDER", "meta,deepseek,gemini,lechat").split(",") if s.strip()]
    order += [s for s in ("gemini", "meta", "deepseek", "chatgpt", "lechat", "copilot") if s not in order]
    ready = [s for s in order if status.get(s, {}).get("ok") and not status.get(s, {}).get("busy")]
    signed = [s for s in ready if status[s].get("signedIn")]
    if signed or ready:
        return (signed or ready)[0]
    detail = "; ".join(f"{s}: {status.get(s, {}).get('detail', 'sin estado')}" for s in order)
    raise LLMError(f"Ningún chat web está listo ({detail})")

BRIDGE_LIMIT = 31_000


def bridge_file() -> Path:
    return Path(os.environ.get("EOLFI_BRIDGE_FILE") or Path.home() / ".eolfi" / "bridge.json")


def read_bridge() -> dict[str, Any]:
    f = bridge_file()
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LLMError("El puente de chats web no está arrancado: ejecuta  python -m eolfi bridge") from exc
    import urllib.parse

    # urlsplit, no startswith: «http://127.0.0.1:80@evil.com» empieza igual y va a evil.com (B19).
    try:
        u = urllib.parse.urlsplit(str(data.get("url", "")))
        port_ok = u.port is not None
    except ValueError:
        u, port_ok = None, False
    if (u is None or u.scheme != "http" or u.hostname != "127.0.0.1" or not port_ok or u.username or u.password
            or u.path not in ("", "/") or len(str(data.get("token", ""))) < 32):
        raise LLMError(f"{f} no tiene una configuración de puente válida")
    return data


def parse_json_text(text: str) -> dict[str, Any]:
    """JSON tolerante a vallas ``` y texto alrededor (modelos sin modo estructurado)."""
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.S)
    if m:
        t = m.group(1)
    elif not t.startswith("{"):
        a, b = t.find("{"), t.rfind("}")
        if a < 0 or b <= a:
            raise LLMError("la respuesta no contiene un objeto JSON")
        t = t[a:b + 1]
    try:
        data = json.loads(t)
    except json.JSONDecodeError as exc:
        raise LLMError(f"JSON inválido en la respuesta: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMError("la respuesta JSON no es un objeto")
    data.setdefault("summary", "")
    data.setdefault("notes", [])
    data.setdefault("files", [])
    return data


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None   # una redirección no debe llevarse la clave (Authorization) a otro host


def check_key_url(url: str, has_key: bool) -> None:
    """Con clave, solo https (o http a este mismo equipo, p. ej. Eolas en 127.0.0.1)."""
    import urllib.parse

    u = urllib.parse.urlsplit(url)
    local = (u.hostname or "") in ("127.0.0.1", "localhost", "::1")
    if has_key and u.scheme != "https" and not local:
        raise LLMError(f"No se envía la clave por {u.scheme}:// a {u.hostname}: usa https://")


MAX_RESPONSE_BYTES = 32 * 1024 * 1024   # una respuesta mayor no es una respuesta de chat razonable (M25)
RETRIES = 3                             # reintentos ante 429, 5xx y cortes de red


def _post(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float,
          retries: int = RETRIES, sleep: Callable[[float], None] | None = None) -> dict[str, Any]:
    import time as _time

    check_key_url(url, "Authorization" in headers)
    data = json.dumps(body).encode("utf-8")
    opener = urllib.request.build_opener(_NoRedirect)
    wait = sleep or _time.sleep
    where = url.split("?")[0]
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json", **headers})
        try:
            with opener.open(req, timeout=timeout) as r:
                raw = r.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise LLMError(f"respuesta de {where} demasiado grande (más de {MAX_RESPONSE_BYTES // 2**20} MB)")
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read(4000).decode("utf-8", "replace")[:400]
            if (exc.code == 429 or exc.code >= 500) and attempt < retries:
                try:
                    pause = float(exc.headers.get("Retry-After") or 0)
                except (TypeError, ValueError):
                    pause = 0.0
                wait(min(max(pause, 2.0 * 2 ** attempt), 60.0))   # espera creciente, como mucho 1 min
                continue
            raise LLMError(f"HTTP {exc.code} de {where}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt < retries:
                wait(min(2.0 * 2 ** attempt, 60.0))
                continue
            raise LLMError(f"No se pudo conectar con {where}: {getattr(exc, 'reason', exc)}") from exc
        except json.JSONDecodeError as exc:
            raise LLMError("respuesta del servidor no es JSON") from exc
    raise LLMError(f"sin respuesta de {where}")


class Provider:
    name = "base"
    context_bytes = 200_000

    def complete(self, system: str, messages: list[dict[str, Any]], schema: dict[str, Any], effort: str) -> Reply:
        raise NotImplementedError


class ClaudeProvider(Provider):
    name = "claude"
    context_bytes = PRESETS["claude"]["context_bytes"]
    MODEL = "claude-opus-5-5"

    def __init__(self, client=None, model: str | None = None):
        self.client = client
        self.model = model or self.MODEL

    def complete(self, system, messages, schema, effort) -> Reply:
        if self.client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise LLMError("Falta el SDK de Anthropic: pip install 'eolfi[ai]' (o pip install anthropic)") from exc
            self.client = anthropic.Anthropic()
        try:
            import anthropic
            api_errors: tuple = (anthropic.APIStatusError, anthropic.APIConnectionError)
        except ImportError:          # cliente simulado en pruebas
            api_errors = ()
        try:
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=64000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",                       # si el modelo rechaza, el servidor reintenta con otro
                system=system,
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
                messages=messages,
            ) as stream:
                msg = stream.get_final_message()
        except api_errors as exc:  # type: ignore[misc]
            raise LLMError(f"Error de la API de Claude: {exc}") from exc
        if msg.stop_reason == "refusal":
            cat = getattr(getattr(msg, "stop_details", None), "category", None)
            raise LLMError(f"Claude rechazó la petición (categoría: {cat})")
        if msg.stop_reason == "max_tokens":
            raise LLMError("La respuesta se cortó por longitud: pide un cambio más acotado")
        text = next((b.text for b in msg.content if getattr(b, "type", "") == "text"), "")
        u = getattr(msg, "usage", None)
        return Reply(parse_json_text(text), msg.content,
                     {"input_tokens": getattr(u, "input_tokens", 0) or 0, "output_tokens": getattr(u, "output_tokens", 0) or 0},
                     self.model)


class OllamaProvider(Provider):
    """Eolas V1 / Ollama: POST /api/chat con `format` = esquema JSON."""
    name = "eolas"

    def __init__(self, base_url: str, model: str, context_bytes: int = 60_000, timeout: float = 900.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.context_bytes = context_bytes
        self.timeout = timeout

    def complete(self, system, messages, schema, effort) -> Reply:
        msgs = [{"role": "system", "content": system}] + [
            {"role": m["role"], "content": m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])}
            for m in messages]
        r = _post(f"{self.base_url}/api/chat", {
            "model": self.model, "messages": msgs, "stream": False, "format": schema, "think": False,
            "options": {"num_ctx": 32768, "num_predict": 12000, "temperature": 0.2},
        }, {}, self.timeout)
        text = (r.get("message") or {}).get("content", "")
        if not text:
            raise LLMError(f"Eolas no devolvió contenido ({r.get('error') or r.get('done_reason')})")
        return Reply(parse_json_text(text), text,
                     {"input_tokens": r.get("prompt_eval_count", 0) or 0, "output_tokens": r.get("eval_count", 0) or 0},
                     self.model)


class OpenAICompatProvider(Provider):
    """APIs oficiales compatibles con OpenAI (DeepSeek, Gemini, otras)."""

    def __init__(self, name: str, base_url: str, model: str, key_env: str | None, json_mode: str = "json_schema",
                 context_bytes: int = 200_000, timeout: float = 900.0):
        if not model:
            raise LLMError(f"Indica el modelo para '{name}' con --model")
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.key_env = key_env
        self.json_mode = json_mode
        self.context_bytes = context_bytes
        self.timeout = timeout

    def complete(self, system, messages, schema, effort) -> Reply:
        key = os.environ.get(self.key_env or "", "") if self.key_env else ""
        if self.key_env and not key:
            raise LLMError(f"Define la variable de entorno {self.key_env} con tu clave de {self.name}")
        if self.json_mode == "json_object":
            fmt: dict[str, Any] = {"type": "json_object"}
            system = system + "\n\nResponde SOLO con un objeto JSON con este esquema:\n" + json.dumps(schema)
        else:
            fmt = {"type": "json_schema", "json_schema": {"name": "eolfi_changes", "schema": schema, "strict": True}}
        msgs = [{"role": "system", "content": system}] + [
            {"role": m["role"], "content": m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])}
            for m in messages]
        r = _post(f"{self.base_url}/chat/completions", {
            "model": self.model, "messages": msgs, "response_format": fmt, "max_tokens": 32000,
        }, {"Authorization": f"Bearer {key}"} if key else {}, self.timeout)
        choice = (r.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            raise LLMError("La respuesta se cortó por longitud: pide un cambio más acotado")
        text = (choice.get("message") or {}).get("content") or ""
        u = r.get("usage") or {}
        return Reply(parse_json_text(text), text,
                     {"input_tokens": u.get("prompt_tokens", 0) or 0, "output_tokens": u.get("completion_tokens", 0) or 0},
                     self.model)


class LlamaCppProvider(OpenAICompatProvider):
    """Gemma 4 (u otro .gguf) con llama.cpp en 127.0.0.1: arranca llama-server si hace falta y usa la configuración
    común (temperatura, longitud, razonamiento, instrucciones propias). El razonamiento queda en last_reasoning."""

    def __init__(self, model: str | None = None):
        from eolfi import llamacpp

        self.cfg = llamacpp.load_config()
        super().__init__("gemma", llamacpp.base_url(self.cfg) + "/v1", model or self.cfg["alias"], None, "json_schema",
                         PRESETS["gemma"]["context_bytes"], timeout=1800.0)
        self.last_reasoning = ""

    def complete(self, system, messages, schema, effort) -> Reply:
        from eolfi import llamacpp

        llamacpp.start(self.cfg)
        if self.cfg.get("system"):
            system = f"{system}\n\nInstrucciones del usuario para este modelo:\n{self.cfg['system']}"
        msgs = [{"role": "system", "content": system}] + [
            {"role": m["role"], "content": m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])}
            for m in messages]
        opts = llamacpp.request_options(self.cfg)
        # El modo asistido devuelve archivos enteros: la mitad del contexto como mínimo para la respuesta.
        opts["max_tokens"] = max(int(opts["max_tokens"]), int(self.cfg["ctx"]) // 2)
        r = _post(f"{self.base_url}/chat/completions", {
            "model": self.model, "messages": msgs, **opts,
            "response_format": {"type": "json_schema", "json_schema": {"name": "eolfi_changes", "schema": schema, "strict": True}},
        }, {}, self.timeout)
        choice = (r.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            raise LLMError("La respuesta se cortó por longitud: sube «ctx» o «max_tokens» en " + str(llamacpp.config_file()))
        msg = choice.get("message") or {}
        self.last_reasoning = msg.get("reasoning_content") or ""
        text = msg.get("content") or ""
        u = r.get("usage") or {}
        return Reply(parse_json_text(text), text,
                     {"input_tokens": u.get("prompt_tokens", 0) or 0, "output_tokens": u.get("completion_tokens", 0) or 0},
                     f"{self.model} (llama.cpp local)")


class BridgeProvider(Provider):
    """DeepSeek / Gemini / Meta AI web a través del puente Electron local."""

    def __init__(self, name: str, site: str, context_bytes: int, timeout: float = 1900.0):
        self.name = name
        self.site = site
        self.model = f"{site} (web)"
        self.context_bytes = context_bytes
        self.timeout = timeout
        self.conversation = "eolfi-" + uuid.uuid4().hex[:16]
        self.turns = 0

    def complete(self, system, messages, schema, effort) -> Reply:
        bridge = read_bridge()
        if self.site == "auto":
            self.site = choose_web_site()
            self.model = f"{self.site} (web, automático)"
        last = messages[-1]["content"]
        last = last if isinstance(last, str) else json.dumps(last, ensure_ascii=False)
        rule = ("Formato de respuesta OBLIGATORIO: un único bloque de código ```json que contenga un objeto JSON "
                "válido y nada más (sin texto antes ni después). Dentro de las cadenas JSON escapa las comillas "
                "dobles como \\\" y los saltos de línea como \\n. El objeto cumple este esquema JSON:\n"
                + json.dumps(schema, ensure_ascii=False))
        if self.turns == 0:
            prompt = f"{system}\n\n{rule}\n\n{last}"
        else:   # la web conserva la conversación: basta con el nuevo mensaje
            prompt = f"{last}\n\nRecuerda: {rule}"
        if len(prompt) > BRIDGE_LIMIT:
            raise LLMError(f"La petición ({len(prompt)} caracteres) supera el límite de las webs de chat ({BRIDGE_LIMIT}); "
                           "pide un cambio más acotado o usa un proveedor por API")
        r = _post(bridge["url"] + "/v1/chat", {"provider": self.site, "prompt": prompt, "conversation": self.conversation},
                  {"Authorization": f"Bearer {bridge['token']}"}, self.timeout,
                  retries=0)   # nunca reintentar: cada envío al chat pide aprobación y no se debe duplicar
        self.turns += 1
        text = r.get("text") or ""
        if not text:
            raise LLMError(f"{self.name} no devolvió texto")
        try:
            data = parse_json_text(text)
        except LLMError as exc:
            dump = bridge_file().with_name(f"ultima-respuesta-{self.name}.txt")
            dump.write_text(text, encoding="utf-8")
            raise LLMError(f"{exc} (respuesta guardada en {dump})") from exc
        return Reply(data, text, {"input_tokens": 0, "output_tokens": 0}, self.model)


def make_provider(name: str = "claude", *, model: str | None = None, base_url: str | None = None,
                  client=None) -> Provider:
    name = (name or "claude").lower()
    if name not in PRESETS:
        raise LLMError(f"proveedor desconocido '{name}' (opciones: {', '.join(PRESETS)})")
    p = PRESETS[name]
    if p["kind"] == "claude":
        return ClaudeProvider(client, model)
    if p["kind"] == "ollama":
        return OllamaProvider(base_url or p["base_url"], model or p["model"], p["context_bytes"])
    if p["kind"] == "bridge":
        return BridgeProvider(name, p["site"], p["context_bytes"])
    if p["kind"] == "vscode":
        return VSCodeCopilotProvider(model or p["model"], p["context_bytes"])
    if p["kind"] == "llamacpp":
        return LlamaCppProvider(model)
    return OpenAICompatProvider(name, base_url or p["base_url"], model or p["model"], p["key_env"],
                                p.get("json_mode", "json_schema"), p["context_bytes"])


def vscode_bridge_file() -> Path:
    return Path(os.environ.get("EOLFI_VSCODE_BRIDGE_FILE") or Path.home() / ".eolfi" / "vscode-bridge.json")


def read_vscode_bridge() -> dict[str, Any]:
    import urllib.parse

    f = vscode_bridge_file()
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LLMError("El puente de VS Code no está activo: abre VS Code con la extensión de Eolfi "
                       "(python -m eolfi vscode) e inicia sesión en ella con «Eolfi: iniciar sesión»") from exc
    try:
        u = urllib.parse.urlsplit(str(data.get("url", "")))
        ok = u.scheme == "http" and u.hostname == "127.0.0.1" and u.port is not None and not u.username \
            and u.path in ("", "/") and len(str(data.get("token", ""))) >= 32
    except ValueError:
        ok = False
    if not ok:
        raise LLMError(f"{f} no tiene una configuración válida del puente de VS Code")
    return data


class VSCodeCopilotProvider(Provider):
    """Modelos de IA de VS Code por la Language Model API (con tu suscripción y tu permiso en VS Code)."""

    def __init__(self, model: str = "", context_bytes: int = 200_000, timeout: float = 900.0,
                 tools: list[str] | None = None):
        self.name = "copilot-vscode"
        self.model_pref = model
        self.model = model or "IA de VS Code"
        self.context_bytes = context_bytes
        self.timeout = timeout
        env_tools = [t.strip() for t in os.environ.get("EOLFI_COPILOT_TOOLS", "").split(",") if t.strip()]
        self.tools = tools if tools is not None else env_tools
        # Herramientas propias del puente para que el modelo mire el proyecto en VS Code: «read» (por defecto:
        # listar, leer, buscar y abrir), «write» (además escribir, con confirmación en VS Code por archivo),
        # «auto» (escribir sin preguntar cada vez, tras un único permiso en VS Code; si algo falla se deshace) u «off».
        mode = os.environ.get("EOLFI_COPILOT_WORKSPACE", "read").lower()
        self.workspace_tools = True if mode in ("write", "auto") else "read" if mode == "read" else None
        self.auto_approve = mode == "auto"
        self.journals: list[str] = []   # diarios de cambios de esta sesión (para deshacer)

    def complete(self, system, messages, schema, effort) -> Reply:
        bridge = read_vscode_bridge()
        rule = ("Formato de respuesta OBLIGATORIO: un único objeto JSON válido que cumpla este esquema, sin texto "
                "antes ni después:\n" + json.dumps(schema, ensure_ascii=False))
        msgs = [{"role": "system", "content": f"{system}\n\n{rule}"}]
        for m in messages:
            c = m["content"]
            msgs.append({"role": m["role"], "content": c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)})
        body: dict[str, Any] = {"messages": msgs}
        if self.model_pref:
            body["model"] = self.model_pref
        if self.tools:
            body["tools"] = self.tools
        if self.workspace_tools:
            body["workspace_tools"] = self.workspace_tools
        if self.auto_approve:
            body["auto_approve"] = True
        # Sin reintentos: una petición con herramientas podría repetir acciones en VS Code.
        r = _post(bridge["url"] + "/v1/chat", body, {"Authorization": f"Bearer {bridge['token']}"}, self.timeout,
                  retries=0)
        if r.get("journal") and r.get("written"):
            self.journals.append(r["journal"])
        text = r.get("text") or ""
        if not text.strip():
            raise LLMError("El modelo de VS Code no devolvió texto")
        model = r.get("model") or {}
        self.model = model.get("name") or model.get("id") or self.model
        return Reply(parse_json_text(text), text, {"input_tokens": 0, "output_tokens": 0}, self.model)


def _vscode_rollback(self) -> list[str]:
    """Deshace, del más reciente al más antiguo, lo que el modelo escribió en VS Code en esta sesión."""
    restored: list[str] = []
    if not self.journals:
        return restored
    b = read_vscode_bridge()
    for j in reversed(self.journals):
        try:
            r = _post(b["url"] + "/v1/workspace/undo", {"journal": j}, {"Authorization": f"Bearer {b['token']}"}, 120,
                      retries=0)
            restored += r.get("restored", [])
        except LLMError:
            continue
    self.journals.clear()
    return restored


VSCodeCopilotProvider.rollback = _vscode_rollback


def probe(name: str, base_url: str | None = None) -> dict[str, Any]:
    """Comprueba disponibilidad sin enviar el proyecto (para doctor / panel)."""
    p = PRESETS.get(name)
    if not p:
        return {"available": False, "detail": "desconocido"}
    if p["kind"] == "llamacpp":
        from eolfi import llamacpp

        cfg = llamacpp.load_config(create=False)
        if not cfg["server"] or not cfg["model"]:
            return {"available": False, "detail": f"falta llama-server o el modelo .gguf ({llamacpp.config_file()})"}
        return {"available": True, "detail": f"{Path(cfg['model']).name} · " + ("en marcha" if llamacpp.healthy(cfg) else "se arranca al usarlo")}
    if p["kind"] == "claude":
        try:
            import anthropic  # noqa: F401
            return {"available": True, "detail": "SDK instalado; credenciales vía ANTHROPIC_API_KEY o ant auth login"}
        except ImportError:
            return {"available": False, "detail": "pip install 'eolfi[ai]'"}
    if p["kind"] == "ollama":
        url = (base_url or p["base_url"]).rstrip("/") + "/api/tags"
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                models = [m.get("name") for m in json.loads(r.read().decode()).get("models", [])]
            return {"available": True, "detail": f"{len(models)} modelos", "models": models[:20]}
        except (urllib.error.URLError, OSError, ValueError):
            return {"available": False, "detail": f"Eolas no responde en {base_url or p['base_url']} (arráncalo con launch-eolas.ps1)"}
    if p["kind"] == "vscode":
        try:
            b = read_vscode_bridge()
            req = urllib.request.Request(b["url"] + "/v1/status", headers={"Authorization": f"Bearer {b['token']}"})
            with urllib.request.urlopen(req, timeout=10) as r:
                st = json.loads(r.read().decode())
            return {"available": bool(st.get("ok")),
                    "detail": f"VS Code {st.get('vscode')}: {st.get('models', 0)} modelos de IA"
                    if st.get("ok") else "VS Code activo pero sin modelos de IA (¿sesión iniciada en el asistente?)"}
        except (LLMError, urllib.error.URLError, OSError, ValueError) as exc:
            return {"available": False, "detail": str(exc) if isinstance(exc, LLMError) else "VS Code no responde"}
    if p["kind"] == "bridge" and p["site"] == "auto":
        try:
            site = choose_web_site()
            return {"available": True, "detail": f"usará {site}"}
        except LLMError as exc:
            return {"available": False, "detail": str(exc)}
    if p["kind"] == "bridge":
        try:
            bridge = read_bridge()
            req = urllib.request.Request(bridge["url"] + "/v1/status",
                                         headers={"Authorization": f"Bearer {bridge['token']}"})
            with urllib.request.urlopen(req, timeout=15) as r:
                st = json.loads(r.read().decode()).get("providers", {}).get(p["site"], {})
            return {"available": bool(st.get("ok")), "detail": st.get("detail", "sin estado")}
        except (LLMError, urllib.error.URLError, OSError, ValueError) as exc:
            return {"available": False, "detail": str(exc) if isinstance(exc, LLMError) else "el puente no responde"}
    key = p.get("key_env")
    return {"available": bool(os.environ.get(key or "")), "detail": f"clave en {key}" if key else "sin clave"}
