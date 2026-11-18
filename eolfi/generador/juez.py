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
      {"comprobar": "sin errores de JavaScript", "sin_errores_js": true},
      {"comprobar": "accesible", "sin_problemas_accesibilidad": true}]}

``sin_problemas_accesibilidad`` (C4, 17/11/2026) pasa axe-core por la página en su estado de ese momento y falla si
hay problemas graves o críticos (WCAG 2.0/2.1 A y AA y buenas prácticas). axe se inyecta desde Playwright, sin
relajar la CSP de la aplicación; si axe-core no está disponible la comprobación falla (nunca se aprueba sin medir).

Destinos: ``static`` (se sirve la carpeta tal cual) y, desde C4 (17/11/2026), ``react``, ``vue`` y ``svelte``: se
sirve la compilación que deja ``npm run build`` en ``dist/`` (lo mismo que se publicaría). En otros destinos los
criterios se anotan como no ejecutados y la verificación NO queda en verde: un juez que no corre no aprueba nada.

Escritorio y móvil (B1, 18/11/2026): ``desktop`` (Electron) juzga ``renderer/``, ``tauri`` juzga ``src/`` y ``expo``
la versión web que deja ``npm run build:web`` (``expo export``) en ``dist/``, servidas en Chrome como un sitio. Límite:
no es la ventana de Electron, WebView2/WebKit ni la app nativa de Android/iOS; lo que dependa del puente nativo
(preload, comandos de Tauri, módulos nativos de Expo) no se juzga. Expo no se mide por defecto con axe en ``create``
(su compilación web real no está verificada en este equipo); con criterios del titular sí se juzga.

Consola (B1, 18/11/2026): en ``cli`` (el comando instalado en ``.venv``) y ``rust`` (``target/release``) los criterios
llevan ``"consola": true`` y sus pasos ejecutan el programa, sin shell, y comprueban la última ejecución::

    {"version": 1, "consola": true, "pasos": [
      {"ejecutar": ["tareas", "add", "comprar pan"]},
      {"comprobar": "añade sin error", "codigo": 0},
      {"ejecutar": ["--json", "tareas", "list"]},
      {"comprobar": "la lista la incluye", "contiene": "comprar pan"},
      {"comprobar": "sin trazas", "no_contiene": "Traceback"},
      {"comprobar": "id numérico", "patron": "\"id\":\\s*1"}]}

``contiene``, ``no_contiene`` y ``patron`` miran la salida estándar; ``codigo``, el código de salida. Cada juicio corre
en una carpeta temporal nueva que hace de carpeta de datos (``*_DATA_DIR`` del proyecto) y de HOME/APPDATA: no toca
los datos del titular y los pasos de un mismo juicio comparten estado. Cada ejecución tiene 30 s.
"""
from __future__ import annotations

import contextlib
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
# Carpeta que se sirve en cada destino: el proyecto tal cual o la compilación de Vite.
DESTINOS = {"static": ".", "react": "dist", "vue": "dist", "svelte": "dist",
            "desktop": "renderer", "tauri": "src", "expo": "dist"}
# Cómo se obtiene esa carpeta cuando falta (las de desktop y tauri son la propia fuente).
_COMPILAR = {"react": "npm run build", "vue": "npm run build", "svelte": "npm run build", "expo": "npm run build:web"}
# Destinos con servidor propio (C4, 17/11/2026): se arranca la app en un puerto local (127.0.0.1), se espera a que
# responda, se juzga por URL y se para el árbol de procesos. Usa lo que verify ya instaló (.venv, node_modules,
# compilación de Next); no instala nada.
SERVIDORES = ("next", "express", "fastapi", "django", "go")   # go: el ejecutable bin/app de la verificación (B1)
CONSOLA = ("cli", "rust")
CUBIERTOS = (*DESTINOS, *SERVIDORES, *CONSOLA)
# Destinos en los que ``create`` instala por defecto los criterios de accesibilidad (decisión del titular, C4):
# los que se juzgan en Chrome, salvo Expo.
POR_DEFECTO = tuple(t for t in (*DESTINOS, *SERVIDORES) if t != "expo")
PLAZO_CONSOLA = 30
_DATOS = re.compile(r"[\"']([A-Z][A-Z0-9_]{0,60}_DATA_DIR)[\"']")
ARRANQUE = 90
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
    if "consola" in data:
        if data["consola"] is not True:
            raise JuezError("«consola» debe ser true")
        return _validar_consola(data)
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
            tipos = [k for k in ("presente", "ausente", "patron", "cuenta", "cambia_al_clic", "sin_errores_js",
                                 "sin_problemas_accesibilidad") if k in p]
            if len(tipos) != 1:
                raise JuezError(f"paso {i}: una comprobación lleva exactamente una de presente, ausente, patron, "
                                "cuenta, cambia_al_clic, sin_errores_js o sin_problemas_accesibilidad")
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
                    raise JuezError(f"paso {i}: «{t}» debe ser true")
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


def _validar_consola(data: dict[str, Any]) -> dict[str, Any]:
    pasos = data.get("pasos")
    if not isinstance(pasos, list) or not 1 <= len(pasos) <= MAX_PASOS:
        raise JuezError(f"«pasos» debe ser una lista de 1 a {MAX_PASOS} elementos")
    limpio: list[dict[str, Any]] = []
    ejecutado = False
    for i, p in enumerate(pasos, 1):
        if not isinstance(p, dict):
            raise JuezError(f"paso {i}: debe ser un objeto")
        if "ejecutar" in p:
            args = p["ejecutar"]
            if not isinstance(args, list) or len(args) > 20:
                raise JuezError(f"paso {i}: «ejecutar» debe ser una lista de hasta 20 argumentos")
            e: dict[str, Any] = {"ejecutar": [_texto(a, f"paso {i}: argumento") for a in args]}
            if "entrada" in p:
                if not isinstance(p["entrada"], str) or len(p["entrada"]) > 2000:
                    raise JuezError(f"paso {i}: «entrada» debe ser un texto de hasta 2000 caracteres")
                e["entrada"] = p["entrada"]
            limpio.append(e)
            ejecutado = True
        elif "comprobar" in p:
            if not ejecutado:
                raise JuezError(f"paso {i}: una comprobación necesita un «ejecutar» antes")
            c: dict[str, Any] = {"comprobar": _texto(p["comprobar"], f"paso {i}: comprobar", 120)}
            tipos = [k for k in ("codigo", "contiene", "no_contiene", "patron") if k in p]
            if len(tipos) != 1:
                raise JuezError(f"paso {i}: una comprobación de consola lleva exactamente una de codigo, contiene, "
                                "no_contiene o patron")
            t = tipos[0]
            if t == "codigo":
                if not isinstance(p[t], int) or isinstance(p[t], bool) or not 0 <= p[t] <= 255:
                    raise JuezError(f"paso {i}: «codigo» debe ser un entero de 0 a 255")
                c[t] = p[t]
            else:
                c[t] = _texto(p[t], f"paso {i}: {t}", 200 if t == "patron" else 300)
                if t == "patron":
                    try:
                        re.compile(c[t])
                    except re.error as exc:
                        raise JuezError(f"paso {i}: patrón inválido ({exc})") from exc
            limpio.append(c)
        else:
            raise JuezError(f"paso {i}: acción de consola desconocida (ejecutar o comprobar)")
    if not any("comprobar" in p for p in limpio):
        raise JuezError("los criterios no tienen ninguna comprobación")
    return {"version": 1, "consola": True, "pasos": limpio}


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


# ``create --accesibilidad`` (C4): axe en el estado inicial y tras cambiar al tema oscuro de la plantilla. Si la app
# no tiene el botón de tema, el juez anota la acción fallida y la segunda medida se hace en el tema que haya.
PASOS_ACCESIBILIDAD = [
    {"comprobar": "sin problemas graves de accesibilidad", "sin_problemas_accesibilidad": True},
    {"clic": {"selector": "[data-theme-toggle]"}},
    {"comprobar": "sin problemas graves de accesibilidad tras cambiar el tema", "sin_problemas_accesibilidad": True},
]


def con_accesibilidad(data: dict[str, Any] | None) -> dict[str, Any]:
    """Los criterios de accesibilidad solos, o añadidos al final de otros (tras recargar la página)."""
    if data is not None and data.get("consola"):
        raise JuezError("la accesibilidad (axe) no se aplica a criterios de consola")
    if data is None:
        return validar({"version": 1, "pasos": [
            {"comprobar": "sin errores de JavaScript", "sin_errores_js": True}, *PASOS_ACCESIBILIDAD]})
    return validar({**data, "pasos": [*data["pasos"], {"recargar": True}, *PASOS_ACCESIBILIDAD]})


def _escribir(proyecto: Path, data: dict[str, Any]) -> None:
    (Path(proyecto) / ARCHIVO).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def instalar_accesibilidad(proyecto: Path) -> dict[str, Any]:
    data = con_accesibilidad(None)
    _escribir(proyecto, data)
    return data


def instalar(proyecto: Path, origen: str | Path, *, accesibilidad: bool = False) -> dict[str, Any]:
    """Copia unos criterios validados al proyecto (lo hace ``create --juez``, nunca el modelo)."""
    try:
        data = validar(json.loads(Path(origen).read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        if isinstance(exc, JuezError):
            raise
        raise JuezError(f"no se pueden leer los criterios de {origen}: {exc}") from exc
    if accesibilidad:
        data = con_accesibilidad(data)
    _escribir(proyecto, data)
    return data


def _playwright() -> str | None:
    """Ruta de playwright-core: la declarada, la del navegador propio («eolfi navegador instalar») o la de las
    pruebas del propio Eolfi si está instalada."""
    declarada = os.environ.get("EOLFI_PLAYWRIGHT")
    if declarada:
        return declarada
    from eolfi import navegador

    propio = navegador.playwright_propio()
    if propio:
        return str(propio)
    local = Path(__file__).resolve().parents[2] / "tests" / "e2e" / "node_modules" / "playwright-core"
    return str(local) if (local / "index.mjs").is_file() else None


def _axe() -> str | None:
    """axe.min.js: el declarado (EOLFI_AXE) o el de las pruebas del propio Eolfi, con la versión fijada allí."""
    declarado = os.environ.get("EOLFI_AXE")
    if declarado:
        return declarado if Path(declarado).is_file() else None
    from eolfi import navegador

    propio = navegador.axe_propio()
    if propio:
        return str(propio)
    local = Path(__file__).resolve().parents[2] / "tests" / "e2e" / "node_modules" / "axe-core" / "axe.min.js"
    return str(local) if local.is_file() else None


def _venv_python(proyecto: Path) -> Path:
    return proyecto / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def arranque(proyecto: Path, target: str, puerto: int) -> tuple[list[str], dict[str, str]]:
    """Orden y variables para servir la app en 127.0.0.1:puerto. JuezError si falta lo que instala verify."""
    p = str(puerto)
    if target in ("fastapi", "django"):
        py = _venv_python(proyecto)
        if not py.is_file():
            raise JuezError("no está el entorno virtual .venv (lo crea la verificación)")
        if target == "fastapi":
            return [str(py), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", p], {}
        return [str(py), "manage.py", "runserver", f"127.0.0.1:{p}", "--noreload"], {}
    if target == "go":
        exe = proyecto / "bin" / ("app.exe" if os.name == "nt" else "app")
        if not exe.is_file():
            raise JuezError("no está bin/app (lo compila la verificación con go build)")
        return [str(exe)], {"PORT": p, "HOST": "127.0.0.1"}
    node = shutil.which("node")
    if node is None:
        raise JuezError("Node.js no está instalado")
    if target == "express":
        return [node, "src/server.js"], {"PORT": p, "HOST": "127.0.0.1"}
    if target == "next":
        binario = proyecto / "node_modules" / "next" / "dist" / "bin" / "next"
        if not binario.is_file():
            raise JuezError("no está node_modules/next (lo instala la verificación)")
        if not (proyecto / ".next").is_dir():
            raise JuezError("no está la compilación .next (npm run build)")
        return [node, str(binario), "start", "-p", p, "-H", "127.0.0.1"], {"PORT": p}
    raise JuezError(f"destino sin servidor conocido: {target}")


def _puerto_libre() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _resumen_salida(salida: Path) -> str:
    """Las líneas de error primero y luego el final: una traza larga (rutas largas del runner de la CI) dejaba el
    mensaje del error fuera de los últimos 400 caracteres."""
    texto = salida.read_text(encoding="utf-8", errors="replace")
    errores = [ln.strip() for ln in texto.splitlines()
               if re.search(r"\b\w*(Error|Exception)\b|^Traceback", ln.strip()) and not ln.strip().startswith("at ")]
    cabeza = " | ".join(dict.fromkeys(errores))[:300]
    return (cabeza + "\n" if cabeza else "") + texto[-400:]


@contextlib.contextmanager
def servido(proyecto: Path, target: str, *, env: dict[str, str] | None = None, plazo: float | None = None):
    """Arranca la app y devuelve su URL base; al salir, mata el árbol de procesos. JuezError si no responde."""
    import urllib.error
    import urllib.request

    from eolfi.generador.verify import _kill_tree

    plazo = plazo or ARRANQUE
    puerto = _puerto_libre()
    cmd, extra = arranque(proyecto, target, puerto)
    url = f"http://127.0.0.1:{puerto}/"
    salida = Path(tempfile.mkstemp(prefix="eolfi-servidor-", suffix=".log")[1])
    with salida.open("wb") as log:
        proc = subprocess.Popen(cmd, cwd=proyecto, env={**(env or os.environ), **extra}, stdout=log, stderr=log,
                                stdin=subprocess.DEVNULL, start_new_session=os.name != "nt",
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        fin = time.monotonic() + plazo
        while True:
            if proc.poll() is not None:
                raise JuezError(f"el servidor terminó con salida {proc.returncode} antes de responder: "
                                + _resumen_salida(salida))
            try:
                with urllib.request.urlopen(url, timeout=3):
                    break
            except urllib.error.HTTPError as exc:
                if exc.code < 500:
                    break                      # responde (p. ej. 404 en «/»): los criterios dirán si basta
            except (urllib.error.URLError, OSError):
                pass
            if time.monotonic() > fin:
                raise JuezError(f"el servidor no respondió en {plazo:.0f} s: " + _resumen_salida(salida))
            time.sleep(0.5)
        yield url
    finally:
        _kill_tree(proc)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        with contextlib.suppress(OSError):
            salida.unlink()


def juzgar(proyecto: str | Path, criterios: dict[str, Any], *, env: dict[str, str] | None = None,
           plazo: float = PLAZO, url: str | None = None) -> dict[str, Any]:
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
    if not (run_env.get("EOLFI_BROWSER_CHANNEL") or run_env.get("EOLFI_BROWSER_PATH")):
        # El navegador propio de Eolfi («eolfi navegador instalar») antes que el Chrome del equipo.
        from eolfi import navegador

        propio = navegador.ejecutable()
        if propio:
            run_env["EOLFI_BROWSER_PATH"] = str(propio)
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="eolfi-juez-") as tmp:
        req = Path(tmp, "peticion.json")
        req.write_text(json.dumps({"raiz": str(Path(proyecto).resolve()), "pagina": criterios["pagina"],
                                   "pasos": criterios["pasos"], "espera_ms": 5000, "asentar_ms": 200,
                                   "axe": _axe(), "url": url}),
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


def ejecutable(proyecto: Path, target: str) -> Path:
    """El programa que juzga un destino de consola: el comando instalado en .venv o el binario de cargo."""
    from eolfi import compat_toml as tomllib

    exe = ".exe" if os.name == "nt" else ""
    try:
        if target == "cli":
            scripts = tomllib.loads((proyecto / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
            return proyecto / ".venv" / ("Scripts" if os.name == "nt" else "bin") / (next(iter(scripts)) + exe)
        nombre = tomllib.loads((proyecto / "Cargo.toml").read_text(encoding="utf-8"))["package"]["name"]
        return proyecto / "target" / "release" / (nombre + exe)
    except (OSError, ValueError, KeyError, StopIteration, TypeError) as exc:
        raise JuezError(f"no se sabe qué programa ejecutar ({exc})") from exc


def _variables_datos(proyecto: Path) -> list[str]:
    nombres: set[str] = set()
    for f in [*proyecto.glob("src/*.rs"), *proyecto.glob("src/*/*.py")][:60]:
        with contextlib.suppress(OSError, UnicodeDecodeError):
            nombres.update(_DATOS.findall(f.read_text(encoding="utf-8")))
    return sorted(nombres)


def _decodificar(data: bytes) -> str:
    """UTF-8 y, si no lo es, la codificación del sistema (un programa que escribe en cp1252 en Windows)."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        import locale

        return data.decode(locale.getpreferredencoding(False) or "latin-1", "replace")


def _rel(ruta: Path, base: Path) -> str:
    try:
        return ruta.relative_to(base).as_posix()
    except ValueError:
        return str(ruta)


def juzgar_consola(proyecto: str | Path, target: str, criterios: dict[str, Any], *,
                   env: dict[str, str] | None = None) -> dict[str, Any]:
    proyecto = Path(proyecto)
    total = sum(1 for p in criterios["pasos"] if "comprobar" in p)
    try:
        exe = ejecutable(proyecto, target)
    except JuezError as exc:
        return {"status": "error", "total": total, "passed": 0, "error": str(exc)}
    if not exe.is_file():
        return {"status": "error", "total": total, "passed": 0,
                "error": f"no está {_rel(exe, proyecto)}: falta compilar o instalar el comando"}
    t0 = time.monotonic()
    checks: list[dict[str, Any]] = []
    res: dict[str, Any] = {"status": "ok", "total": total, "ejecutable": _rel(exe, proyecto)}
    with tempfile.TemporaryDirectory(prefix="eolfi-juez-consola-") as tmp:
        run_env = dict(env or os.environ)
        for k in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
            run_env[k] = tmp
        for k in _variables_datos(proyecto):
            run_env[k] = str(Path(tmp) / "datos")
        ultimo: dict[str, Any] | None = None
        for p in criterios["pasos"]:
            if "ejecutar" in p:
                orden = " ".join(p["ejecutar"]) or "(sin argumentos)"
                try:
                    proc = subprocess.run([str(exe), *p["ejecutar"]], input=p.get("entrada", "").encode("utf-8"),
                                          capture_output=True, timeout=PLAZO_CONSOLA, env=run_env, cwd=tmp,
                                          check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    ultimo = {"orden": orden, "codigo": proc.returncode,
                              "salida": _decodificar(proc.stdout), "error": _decodificar(proc.stderr)}
                except (subprocess.TimeoutExpired, OSError) as exc:
                    motivo = (f"no terminó en {PLAZO_CONSOLA} s" if isinstance(exc, subprocess.TimeoutExpired)
                              else f"no se pudo ejecutar ({exc})")
                    res.setdefault("accion_fallida", f"«{orden}» {motivo}")
                    ultimo = {"orden": orden, "codigo": None, "salida": "", "error": motivo}
                continue
            assert ultimo is not None   # la validación exige un «ejecutar» antes
            salida = ultimo["salida"]
            if "codigo" in p:
                ok = ultimo["codigo"] == p["codigo"]
                detalle = f"«{ultimo['orden']}» salió con {ultimo['codigo']}" + (
                    f": {ultimo['error'].strip()[-200:]}" if ultimo["error"].strip() else "")
            elif "contiene" in p:
                ok, detalle = p["contiene"] in salida, f"la salida de «{ultimo['orden']}» no lo contiene"
            elif "no_contiene" in p:
                ok, detalle = p["no_contiene"] not in salida, f"la salida de «{ultimo['orden']}» lo contiene"
            else:
                ok, detalle = bool(re.search(p["patron"], salida)), f"la salida de «{ultimo['orden']}» no encaja"
            c = {"nombre": p["comprobar"], "ok": ok}
            if not ok:
                c["detalle"] = detalle if "codigo" in p else f"{detalle}; empieza por: {salida.strip()[:160]!r}"
            checks.append(c)
    res.update({"checks": checks, "passed": sum(1 for c in checks if c["ok"]), "ejecutadas": len(checks),
                "seconds": round(time.monotonic() - t0, 2)})
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
    raiz = Path(proyecto) / DESTINOS[target] if target in DESTINOS else None
    if criterios.get("consola") or target in CONSOLA:
        if not criterios.get("consola"):
            j = {"status": "error", "error": f"«{target}» es un destino de consola: los criterios llevan "
                                             "«consola»: true y pasos ejecutar/comprobar"}
        elif target not in CONSOLA:
            j = {"status": "error", "error": f"criterios de consola en un destino que no lo es («{target}»)"}
        else:
            j = juzgar_consola(proyecto, target, criterios, env=env)
    elif target in SERVIDORES:
        try:
            with servido(Path(proyecto), target, env=env) as url:
                j = juzgar(proyecto, criterios, env=env, url=url)
        except JuezError as exc:
            j = {"status": "error", "error": str(exc)}
    elif raiz is None:
        j = {"status": "unavailable", "error": f"el juez funcional aún no cubre el destino «{target}»"}
    elif not (raiz / criterios["pagina"]).is_file():
        como = f"falta la compilación ({_COMPILAR[target]})" if target in _COMPILAR else "falta la interfaz"
        j = {"status": "error", "error": f"no está {DESTINOS[target]}/{criterios['pagina']}: {como}"}
    else:
        j = juzgar(raiz, criterios, env=env)
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
