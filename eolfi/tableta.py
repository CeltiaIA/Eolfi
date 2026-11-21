"""Superficie mínima del panel para la tableta satélite (Galaxy Tab 2, Android 4.1).

La tableta se vincula con el mismo código de un solo uso que VS Code (`POST /api/clients/token`), pero pidiendo
`"scope": "tableta"`. Su token solo abre las rutas de `PERMITIDAS`; cualquier otra devuelve 403 aunque el token sea
válido. Así, un token robado de la tableta no sirve para analizar archivos, crear proyectos ni decidir encargos.

Qué hace la tableta con ellas:
- `GET  /api/tableta/estado`        comprobar el vínculo y qué hay disponible (voz, chat);
- `POST /api/tableta/chat`          mandar un mensaje al chat de Eolas (trabajo «chat» normal del panel);
- `GET  /api/tableta/chat?id=…`     leer el resultado, solo de trabajos que abrió una tableta;
- `POST /api/tableta/chat/mensaje`  corregir o parar («para») un chat suyo que sigue en marcha;
- `GET  /api/tableta/trabajos`      visor: trabajos y encargos de VS Code, resumidos y en solo lectura;
- `POST /api/tableta/diagnostico`   la tableta informa de lo que midió en sí misma (TLS, WebView, micrófono);
- `POST /api/voz/transcribir`       WAV del micrófono de la tableta → texto (rutas ya existentes de voz);
- `POST /api/voz/hablar`            texto → WAV para el altavoz de la tableta.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

SCOPE = "tableta"

PERMITIDAS = frozenset({
    ("GET", "/api/tableta/estado"),
    ("GET", "/api/tableta/chat"),
    ("GET", "/api/tableta/trabajos"),
    ("POST", "/api/tableta/chat"),
    ("POST", "/api/tableta/chat/mensaje"),
    ("POST", "/api/tableta/diagnostico"),
    ("POST", "/api/voz/transcribir"),
    ("POST", "/api/voz/hablar"),
})

MAX_TEXTO = 2000          # un mensaje dictado o tecleado en la tableta
MAX_HISTORIAL = 12        # mensajes previos que la tableta puede mandar como contexto
MAX_DIAGNOSTICO = 32 * 1024
_ids_lock = threading.Lock()


def permitida(method: str, path: str) -> bool:
    return (("GET" if method == "HEAD" else method), path) in PERMITIDAS


def carpeta() -> Path:
    return Path(os.environ.get("EOLFI_TABLETA_DIR") or Path.home() / ".eolfi" / "tableta")


def _ids(app: Any) -> set[str]:
    """Trabajos abiertos por una tableta. 21/11/2026: se guardan en disco (antes solo en memoria: tras reiniciar el
    servidor la tableta ya no podía leer la respuesta de un trabajo que seguía en el historial)."""
    with _ids_lock:
        if not hasattr(app, "_tableta_jobs"):
            try:
                datos = json.loads((carpeta() / "trabajos.json").read_text(encoding="utf-8"))
                app._tableta_jobs = {i for i in datos.get("ids", []) if isinstance(i, str)
                                     and re.fullmatch(r"[0-9a-f]{16}", i)}
            except (OSError, ValueError, AttributeError):
                app._tableta_jobs = set()
        return app._tableta_jobs


def _anotar_id(app: Any, ident: str) -> None:
    ids = _ids(app)
    with _ids_lock:
        ids.add(ident)
        ultimos = sorted(ids)[-200:] if len(ids) > 200 else sorted(ids)
        try:
            carpeta().mkdir(parents=True, exist_ok=True)
            tmp = carpeta() / "trabajos.json.tmp"
            tmp.write_text(json.dumps({"ids": ultimos}), encoding="utf-8")
            os.replace(tmp, carpeta() / "trabajos.json")
        except OSError:
            pass   # sin disco escribible se sigue como antes: solo en memoria


def estado(app: Any) -> dict[str, Any]:
    from eolfi import __version__

    try:
        from eolfi import voz

        v = voz.estado()
        voz_ok = {"voz_a_texto": bool(v.get("voz_a_texto")), "texto_a_voz": bool(v.get("texto_a_voz")),
                  "motor": v.get("motor_activo"), "idioma": v.get("idioma")}
    except Exception as exc:  # noqa: BLE001 — la voz es opcional: se informa, no se cae
        voz_ok = {"voz_a_texto": False, "texto_a_voz": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
    return {"ok": True, "eolfi": __version__, "scope": SCOPE, "voz": voz_ok, "hora": int(time.time()),
            "rutas": sorted(p for _m, p in PERMITIDAS)}


def validar_mensajes(body: dict[str, Any]) -> list[dict[str, str]]:
    """`{"texto": "…", "historial"?: [{"role","content"}…]}` → mensajes del chat (el último, del usuario)."""
    texto = body.get("texto")
    if not isinstance(texto, str) or not texto.strip():
        raise ValueError("falta el texto")
    if len(texto) > MAX_TEXTO:
        raise ValueError(f"texto demasiado largo (máximo {MAX_TEXTO} caracteres)")
    hist = body.get("historial") or []
    if not isinstance(hist, list) or len(hist) > MAX_HISTORIAL:
        raise ValueError(f"historial: lista de hasta {MAX_HISTORIAL} mensajes")
    out = []
    for m in hist:
        if (not isinstance(m, dict) or m.get("role") not in ("user", "assistant")
                or not isinstance(m.get("content"), str) or not m["content"].strip()):
            raise ValueError("historial: cada mensaje necesita role user/assistant y texto")
        out.append({"role": m["role"], "content": m["content"][:MAX_TEXTO * 2]})
    out.append({"role": "user", "content": texto.strip() + NOTA_TABLETA})
    return out


# El smoke real (19/11) mostró que, sin contexto, Eolas no sabe que le hablan desde la tableta ni que su respuesta se
# leerá en voz alta. La nota va al final del mensaje y es visible en el trabajo del panel.
NOTA_TABLETA = ("\n\n(Mensaje enviado desde la tableta satélite de Eolfi, por voz o teclado; puede venir de un "
                "dictado imperfecto. Responde breve y en texto plano: se leerá en voz alta.)")


def chat_iniciar(app: Any, body: dict[str, Any], nivel: str) -> dict[str, Any]:
    msgs = validar_mensajes(body)
    job = app.start_job({"kind": "chat", "body": {"messages": msgs, "name": "Tableta"}}, nivel)
    _anotar_id(app, job["job_id"])
    return {"id": job["job_id"]}


def chat_mensaje(app: Any, body: dict[str, Any]) -> dict[str, Any]:
    """`{"id", "texto"}`: corrección para un chat de esta tableta que sigue en marcha; «para» lo cancela."""
    ident = str(body.get("id") or "")
    if not re.fullmatch(r"[0-9a-f]{16}", ident) or ident not in _ids(app):
        raise KeyError("trabajo no encontrado")
    texto = body.get("texto")
    if not isinstance(texto, str) or len(texto) > MAX_TEXTO:
        raise ValueError(f"texto de hasta {MAX_TEXTO} caracteres")
    return app.job_message(ident, {"texto": texto})


def chat_estado(app: Any, q: dict[str, str]) -> dict[str, Any]:
    ident = q.get("id", "")
    if not re.fullmatch(r"[0-9a-f]{16}", ident) or ident not in _ids(app):
        raise KeyError("trabajo no encontrado")
    st = app.job_status({"id": ident, "since": q.get("since", "0")})
    out = {k: st[k] for k in ("id", "status", "next", "elapsed", "error") if k in st}
    out["avisos"] = [str(e.get("msg", ""))[:200] for e in st.get("log", [])][-5:]
    res = st.get("result")
    if isinstance(res, dict):
        out["texto"] = str(res.get("text") or "")
        out["herramientas"] = [str(c.get("name") or c.get("tool") or "") for c in (res.get("tools") or [])
                               if isinstance(c, dict)][:20]
    return out


def trabajos(app: Any) -> dict[str, Any]:
    """Visor de solo lectura: etiquetas y estados, nunca cuerpos, rutas completas ni registros."""
    jobs = [{k: j.get(k) for k in ("id", "kind", "status", "label", "started", "finished") if j.get(k) is not None}
            for j in app.job_status({}).get("jobs", [])[:20]]
    try:
        enc = [{k: e.get(k) for k in ("id", "titulo", "estado", "creado", "actualizado") if e.get(k) is not None}
               for e in app.vscode_encargos().get("encargos", [])[:20]]
    except Exception:  # noqa: BLE001 — sin encargos legibles, el visor sigue mostrando los trabajos
        enc = []
    return {"trabajos": jobs, "encargos": enc}


_CLAVE_DIAG = re.compile(r"^[a-z][a-z0-9_.]{0,40}$")


def diagnostico(body: dict[str, Any], raw_len: int) -> dict[str, Any]:
    """Guarda lo que la tableta midió en sí misma. Solo claves simples y valores escalares o listas de texto."""
    if raw_len > MAX_DIAGNOSTICO:
        raise ValueError("diagnóstico demasiado grande")
    limpio: dict[str, Any] = {}
    for k, v in body.items():
        if not isinstance(k, str) or not _CLAVE_DIAG.match(k):
            raise ValueError(f"clave de diagnóstico inválida: {str(k)[:40]}")
        if isinstance(v, (bool, int, float)) or v is None:
            limpio[k] = v
        elif isinstance(v, str):
            limpio[k] = v[:1000]
        elif isinstance(v, list) and all(isinstance(x, str) for x in v):
            limpio[k] = [x[:200] for x in v[:100]]
        else:
            raise ValueError(f"valor de diagnóstico no admitido en {k}")
    d = carpeta()
    d.mkdir(parents=True, exist_ok=True)
    nombre = time.strftime("diagnostico-%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1000000:06d}.json"
    ruta = d / nombre
    ruta.write_text(json.dumps({"recibido": time.time(), "datos": limpio}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return {"guardado": nombre, "claves": len(limpio)}
