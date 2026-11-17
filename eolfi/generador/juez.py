"""Juez funcional dentro de la verificación (PLAN_DEFINITIVO.md, B1).

Si el proyecto trae ``eolfi.juez.json``, ``verify`` abre la aplicación en Chrome y ejecuta esos criterios: acciones
(escribir, hacer clic, recargar) y comprobaciones. El resultado entra en ``verification`` como un paso más, así que
un proyecto que compila pero no funciona deja de salir en verde y las rondas de reparación ven qué comprobación
falla. El modelo no puede escribir ni cambiar los criterios (``assist`` lo prohíbe).

Formato (versión 1)::

    {"version": 1, "pagina": "index.html", "pasos": [
      {"escribir": {"selector": "form input[type=text]", "texto": "comprar pan", "intro": true}},
      {"comprobar": "añade la tarea", "presente": "comprar pan"},
      {"comprobar": "el resumen cuenta 1", "selector": "#resumen", "patron": "\\\\b1\\\\b"},
      {"comprobar": "clic marca como hecha", "cambia_al_clic": "comprar pan"},
      {"clic": {"selector": "button", "en": "comprar pan"}},
      {"comprobar": "borrar quita la tarea", "ausente": "comprar pan"},
      {"recargar": true},
      {"comprobar": "sin errores de JavaScript", "sin_errores_js": true}]}

Hoy solo para el destino ``static`` (se sirve la carpeta tal cual). En otros destinos los criterios se anotan como
no ejecutados y la verificación NO queda en verde: un juez que no corre no aprueba nada.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

ARCHIVO = "eolfi.juez.json"
DRIVER = Path(__file__).with_name("juez_web.mjs")
DESTINOS = ("static",)
MAX_PASOS = 100
PLAZO = 180
_PAGINA = re.compile(r"[\w][\w./-]{0,120}\.html?")


class JuezError(ValueError):
    pass


def _texto(valor: Any, campo: str, maximo: int = 300) -> str:
    if not isinstance(valor, str) or not valor.strip() or len(valor) > maximo:
        raise JuezError(f"«{campo}» debe ser un texto de 1 a {maximo} caracteres")
    if any(ord(ch) < 32 for ch in valor):   # p. ej. "\b" mal escapado en el JSON, que llega como retroceso
        raise JuezError(f"«{campo}» contiene caracteres de control (¿una barra invertida sin duplicar en el JSON?)")
    return valor


def validar(data: Any) -> dict[str, Any]:
    """Devuelve los criterios normalizados o lanza JuezError. Nada del archivo se usa sin pasar por aquí."""
    if not isinstance(data, dict) or data.get("version") != 1:
        raise JuezError("criterios del juez: falta «version»: 1")
    pagina = data.get("pagina", "index.html")
    if not isinstance(pagina, str) or not _PAGINA.fullmatch(pagina) or ".." in pagina.split("/"):
        raise JuezError("«pagina» debe ser un archivo .html dentro del proyecto")
    pasos = data.get("pasos")
    if not isinstance(pasos, list) or not 1 <= len(pasos) <= MAX_PASOS:
        raise JuezError(f"«pasos» debe ser una lista de 1 a {MAX_PASOS} elementos")
    limpio: list[dict[str, Any]] = []
    for i, p in enumerate(pasos, 1):
        if not isinstance(p, dict):
            raise JuezError(f"paso {i}: debe ser un objeto")
        if "comprobar" in p:
            c: dict[str, Any] = {"comprobar": _texto(p["comprobar"], f"paso {i}: comprobar", 120)}
            tipos = [k for k in ("presente", "ausente", "patron", "cuenta", "cambia_al_clic", "sin_errores_js") if k in p]
            if len(tipos) != 1:
                raise JuezError(f"paso {i}: una comprobación lleva exactamente una de presente, ausente, patron, "
                                "cuenta, cambia_al_clic o sin_errores_js")
            t = tipos[0]
            if t in ("presente", "ausente", "cambia_al_clic"):
                c[t] = _texto(p[t], f"paso {i}: {t}")
            elif t == "patron":
                c["selector"] = _texto(p.get("selector"), f"paso {i}: selector")
                c["patron"] = _texto(p["patron"], f"paso {i}: patron", 200)
                try:
                    re.compile(c["patron"])
                except re.error as exc:
                    raise JuezError(f"paso {i}: patrón inválido ({exc})") from exc
            elif t == "cuenta":
                c["selector"] = _texto(p.get("selector"), f"paso {i}: selector")
                if not isinstance(p["cuenta"], int) or isinstance(p["cuenta"], bool) or not 0 <= p["cuenta"] <= 10000:
                    raise JuezError(f"paso {i}: «cuenta» debe ser un entero")
                c["cuenta"] = p["cuenta"]
            else:
                if p[t] is not True:
                    raise JuezError(f"paso {i}: «sin_errores_js» debe ser true")
                c[t] = True
            limpio.append(c)
        elif "escribir" in p and isinstance(p["escribir"], dict):
            e = p["escribir"]
            texto = e.get("texto")
            if not isinstance(texto, str) or len(texto) > 2000:
                raise JuezError(f"paso {i}: «texto» debe ser un texto")
            limpio.append({"escribir": {"selector": _texto(e.get("selector"), f"paso {i}: selector"), "texto": texto,
                                        "intro": bool(e.get("intro"))}})
        elif "clic" in p and isinstance(p["clic"], dict):
            k = p["clic"]
            if "texto" in k and "selector" not in k:
                limpio.append({"clic": {"texto": _texto(k["texto"], f"paso {i}: texto")}})
            else:
                clic = {"selector": _texto(k.get("selector"), f"paso {i}: selector")}
                if "en" in k:
                    clic["en"] = _texto(k["en"], f"paso {i}: en")
                limpio.append({"clic": clic})
        elif p.get("recargar") is True:
            limpio.append({"recargar": True})
        else:
            raise JuezError(f"paso {i}: acción desconocida (escribir, clic, recargar o comprobar)")
    if not any("comprobar" in p for p in limpio):
        raise JuezError("los criterios no tienen ninguna comprobación")
    return {"version": 1, "pagina": pagina, "pasos": limpio}


def cargar(proyecto: Path) -> dict[str, Any] | None:
    """Criterios del proyecto, o None si no trae. Un archivo inválido lanza JuezError (no se ignora)."""
    f = Path(proyecto) / ARCHIVO
    if not f.is_file():
        return None
    try:
        return validar(json.loads(f.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        if isinstance(exc, JuezError):
            raise
        raise JuezError(f"{ARCHIVO} no se puede leer: {exc}") from exc


def instalar(proyecto: Path, origen: str | Path) -> dict[str, Any]:
    """Copia unos criterios validados al proyecto (lo hace ``create --juez``, nunca el modelo)."""
    try:
        data = validar(json.loads(Path(origen).read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        if isinstance(exc, JuezError):
            raise
        raise JuezError(f"no se pueden leer los criterios de {origen}: {exc}") from exc
    (Path(proyecto) / ARCHIVO).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def _playwright() -> str | None:
    """Ruta de playwright-core: la declarada, o la de las pruebas del propio Eolfi si está instalada."""
    declarada = os.environ.get("EOLFI_PLAYWRIGHT")
    if declarada:
        return declarada
    local = Path(__file__).resolve().parents[2] / "tests" / "e2e" / "node_modules" / "playwright-core"
    return str(local) if (local / "index.mjs").is_file() else None


def juzgar(proyecto: str | Path, criterios: dict[str, Any], *, env: dict[str, str] | None = None,
           plazo: float = PLAZO) -> dict[str, Any]:
    """Ejecuta los criterios. Devuelve ``status`` ok (con passed/total/checks), unavailable o error."""
    total = sum(1 for p in criterios["pasos"] if "comprobar" in p)
    node = shutil.which("node")
    if node is None:
        return {"status": "unavailable", "total": total, "passed": 0, "error": "Node.js no está instalado"}
    run_env = dict(env or os.environ)
    pw = _playwright()
    if pw:
        run_env["EOLFI_PLAYWRIGHT"] = pw
    for k in ("EOLFI_BROWSER_CHANNEL", "EOLFI_BROWSER_PATH"):
        if os.environ.get(k):
            run_env[k] = os.environ[k]
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="eolfi-juez-") as tmp:
        req = Path(tmp, "peticion.json")
        req.write_text(json.dumps({"raiz": str(Path(proyecto).resolve()), "pagina": criterios["pagina"],
                                   "pasos": criterios["pasos"], "espera_ms": 5000, "asentar_ms": 200}),
                       encoding="utf-8")
        try:
            proc = subprocess.run([node, str(DRIVER), str(req)], capture_output=True, timeout=plazo, env=run_env,
                                  check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            return {"status": "error", "total": total, "passed": 0, "error": f"el juez no terminó en {plazo:.0f} s"}
    try:
        res = json.loads(proc.stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {"status": "error", "total": total, "passed": 0,
                "error": "respuesta inválida del juez: " + proc.stderr.decode("utf-8", "replace")[-400:]}
    res.setdefault("total", total)
    res.setdefault("passed", 0)
    res["total"] = total                       # el total lo fijan los criterios, no lo que llegó a ejecutarse
    res["seconds"] = round(time.monotonic() - t0, 1)
    return res


def paso(proyecto: str | Path, target: str, *, env: dict[str, str] | None = None) -> dict[str, Any] | None:
    """El paso «juez funcional» para ``verify``: None si el proyecto no trae criterios. Sale con 0 solo si TODAS
    las comprobaciones pasan; si el juez no puede correr, sale con 1 y dice por qué (nunca verde sin juez)."""
    try:
        criterios = cargar(Path(proyecto))
    except JuezError as exc:
        return {"step": "juez funcional", "exit": 1, "seconds": 0, "tail": f"criterios inválidos: {exc}",
                "judge": {"status": "error", "error": str(exc)}}
    if criterios is None:
        return None
    if os.environ.get("EOLFI_JUEZ") == "0":
        return {"step": "juez funcional (desactivado con EOLFI_JUEZ=0: NO VERIFICADO)", "exit": 0, "seconds": 0,
                "tail": "", "judge": {"status": "omitido"}}
    if target not in DESTINOS:
        j = {"status": "unavailable", "error": f"el juez funcional aún no cubre el destino «{target}»"}
    else:
        j = juzgar(proyecto, criterios, env=env)
    if j["status"] != "ok":
        return {"step": "juez funcional", "exit": 1, "seconds": j.get("seconds", 0),
                "tail": f"el juez no pudo ejecutarse: {j.get('error', j['status'])}", "judge": j}
    fallos = [c for c in j.get("checks", []) if not c.get("ok")]
    lineas = [f"Comprobaciones del juez funcional: {j['passed']} de {j['total']} superadas."]
    lineas += [f"- NO: {c['nombre']}" + (f" ({c['detalle']})" if c.get("detalle") else "") for c in fallos]
    if j.get("ejecutadas", j["total"]) < j["total"]:
        lineas.append(f"- {j['total'] - j['ejecutadas']} comprobaciones no llegaron a ejecutarse.")
    if j.get("accion_fallida"):
        lineas.append(f"- Acción que no se pudo hacer: {j['accion_fallida']}")
    if j.get("errores_js"):
        lineas.append("- Errores de JavaScript: " + " | ".join(j["errores_js"][:3]))
    return {"step": f"juez funcional ({j['passed']}/{j['total']})", "exit": 0 if j["passed"] == j["total"] else 1,
            "seconds": j.get("seconds", 0), "tail": "\n".join(lineas), "judge": j}
