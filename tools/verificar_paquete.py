"""Comprueba que Eolfi funciona instalado como paquete, igual que lo instala pipx (C2 del plan).

Pasos, todos sin red:
1. Copia los archivos con seguimiento de Git (tal como están en la copia de trabajo) a una carpeta temporal, para no
   dejar ``build/`` ni tocar ``eolfi.egg-info`` en el repositorio.
2. Construye la rueda con ``pip wheel --no-deps --no-build-isolation --no-index`` (necesita setuptools instalado).
3. Crea un entorno virtual nuevo e instala la rueda con ``--no-index --no-deps``; pipx hace lo mismo en su entorno.
4. Comprueba que la versión de la rueda, la de ``eolfi --version`` y la de ``eolfi update --check`` son la del código,
   y que el modo detectado es ``entorno_virtual``.
5. Comprueba que el paquete instalado tiene todos los archivos de ``eolfi/`` que se usan al ejecutarlo (se excluyen
   solo las pruebas y utilidades de desarrollo de la extensión de VS Code).
6. Arranca ``eolfi serve`` desde el entorno, con un directorio personal temporal, y pide ``/api/health`` y ``/``.

Imprime un JSON con cada paso y su código de salida; sale con 0 solo si todo pasa.
Uso: python tools/verificar_paquete.py [--conservar]
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
# Lo que no forma parte del producto instalado: pruebas, fixtures y scripts de desarrollo de la extensión.
EXCLUIDOS = re.compile(r"^eolfi/(vscode-bridge/(test|e2e|fixtures|scripts)/|.*\.gitignore$|.*/__pycache__/)")
LIMITE_PIPX = "pipx no se ejecuta: se reproduce su instalación (entorno virtual propio, pip install de la rueda)."


def version_codigo() -> str:
    texto = (RAIZ / "eolfi" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', texto).group(1)


def paso(pasos: list, nombre: str, cmd: list[str], **kw) -> subprocess.CompletedProcess:
    t = time.monotonic()
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    pasos.append({"paso": nombre, "codigo": p.returncode, "segundos": round(time.monotonic() - t, 1),
                  **({"salida": (p.stdout + p.stderr)[-1500:]} if p.returncode else {})})
    return p


def comprobacion(pasos: list, nombre: str, ok: bool, **datos) -> bool:
    pasos.append({"paso": nombre, "codigo": 0 if ok else 1, **datos})
    return ok


def copiar_fuente(destino: Path) -> list[str]:
    """Copia los archivos con seguimiento (contenido de la copia de trabajo). Devuelve sus rutas relativas."""
    listado = subprocess.run(["git", "ls-files", "-z"], cwd=RAIZ, capture_output=True, check=True).stdout
    rutas = [r for r in listado.decode("utf-8").split("\0") if r]
    for rel in rutas:
        origen = RAIZ / rel
        if origen.is_file():
            (destino / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origen, destino / rel)
    return rutas


def entorno_aislado(tmp: Path) -> tuple[Path, dict[str, str]]:
    """Directorio personal propio, sin red y sin las variables de Eolfi del equipo: nada real interviene."""
    home = tmp / "home"
    home.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "EOLFI_DB", "EOLFI_HOME")}
    env.update(HOME=str(home), USERPROFILE=str(home), EOLFI_HOME=str(home / ".eolfi"), EOLAS_OFFLINE="1",
               EOLFI_ACCIONES_FILE=str(home / "acciones.jsonl"), PYTHONIOENCODING="utf-8")
    return home, env


def esperados(rutas: list[str], *, sin_py: bool = False) -> list[str]:
    return [r for r in rutas if r.startswith("eolfi/") and not EXCLUIDOS.match(r) and not (sin_py and r.endswith(".py"))]


def comprobar_version_y_modo(pasos: list, exe: list[str], home: Path, env: dict, version: str, modo: str) -> None:
    p = paso(pasos, "eolfi_version", [*exe, "--version"], cwd=home, env=env, timeout=120)
    comprobacion(pasos, "version_cli", p.stdout.strip() == f"eolfi {version}", salida=p.stdout.strip())
    # Sin red (EOLAS_OFFLINE=1) «update --check» sale con 2 y estado NO VERIFICADO: es lo esperado. Aquí solo
    # interesan la versión y el modo que informa; su código de salida queda anotado aparte.
    p = subprocess.run([*exe, "update", "--check"], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=home, env=env, timeout=120)
    pasos.append({"paso": "update_check", "codigo": 0 if p.returncode in (0, 2) else p.returncode,
                  "codigo_salida": p.returncode})
    try:
        inst = json.loads(p.stdout).get("instalada") or {}
        comprobacion(pasos, "version_y_modo", inst.get("version") == version and inst.get("modo") == modo,
                     version=inst.get("version"), modo=inst.get("modo"), esperado=modo)
    except ValueError:
        comprobacion(pasos, "version_y_modo", False, salida=(p.stdout + p.stderr)[-500:])


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(url: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=5) as r:  # noqa: S310 (solo 127.0.0.1)
        return r.status, r.read()


def comprobar_panel(pasos: list, exe: list[str], home: Path, env: dict, tmp: Path) -> None:
    port = _puerto_libre()
    srv = subprocess.Popen([*exe, "serve", "--port", str(port), "--samples", str(tmp / "samples")], cwd=home,
                           env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        salud = pagina = None
        fin = time.monotonic() + 90
        while time.monotonic() < fin and srv.poll() is None:
            try:
                salud = _get(f"http://127.0.0.1:{port}/api/health")
                pagina = _get(f"http://127.0.0.1:{port}/")
                break
            except OSError:
                time.sleep(0.5)
        comprobacion(pasos, "panel_health", bool(salud and salud[0] == 200))
        comprobacion(pasos, "panel_index", bool(pagina and pagina[0] == 200 and b"<html" in pagina[1].lower()),
                     bytes=len(pagina[1]) if pagina else 0)
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=15)
        except subprocess.TimeoutExpired:
            srv.kill()
        err = srv.stderr.read().decode("utf-8", "replace") if srv.stderr else ""
        if srv.stderr:
            srv.stderr.close()
        if pasos[-1]["codigo"] and err:
            pasos[-1]["stderr"] = err[-1500:]


# Prueba que juzga la rueda instalada: una página accesible, con CSP estricta, y los criterios de accesibilidad.
_JUEZ_INSTALADO = """
import json, pathlib, sys
from eolfi.generador import juez
from eolfi import navegador
app = pathlib.Path(sys.argv[1]); app.mkdir(parents=True, exist_ok=True)
(app / 'index.html').write_text('<!doctype html><html lang=\"es\"><meta charset=\"utf-8\">'
    '<meta http-equiv=\"Content-Security-Policy\" content=\"default-src \\'self\\'\">'
    '<title>Prueba</title><main><h1>Hola</h1><p id=\"x\">listo</p></main></html>', encoding='utf-8')
(app / juez.ARCHIVO).write_text(json.dumps(juez.con_accesibilidad(None)), encoding='utf-8')
p = juez.paso(app, 'static')
print(json.dumps({'exit': p['exit'], 'step': p['step'], 'tail': p['tail'][-300:], 'playwright': juez._playwright(),
                  'axe': juez._axe(), 'navegador': str(navegador.ejecutable())}))
"""


def comprobar_navegador(pasos: list, py: Path, exe: list[str], env: dict, tmp: Path) -> None:
    """Con Eolfi instalado como paquete, el juez usa el navegador, Playwright y axe propios (eolfi navegador), no
    los de tests/e2e (que no van en la rueda). Sin navegador propio en este equipo: NO VERIFICADO, no aprobado."""
    sys.path.insert(0, str(RAIZ))
    from eolfi import navegador

    if navegador.ejecutable() is None or navegador.playwright_propio() is None:
        pasos.append({"paso": "navegador_propio", "codigo": 0, "estado": "NO VERIFICADO",
                      "motivo": "este equipo no tiene «eolfi navegador instalar»"})
        return
    env = {**env, "EOLFI_NAVEGADOR_DIR": str(navegador.carpeta())}
    for k in ("EOLFI_PLAYWRIGHT", "EOLFI_AXE", "EOLFI_BROWSER_PATH", "EOLFI_BROWSER_CHANNEL"):
        env.pop(k, None)
    paso(pasos, "navegador_estado", [*exe, "navegador", "estado", "--comprobar"], env=env, timeout=120)
    p = paso(pasos, "juez_instalado", [str(py), "-c", _JUEZ_INSTALADO, str(tmp / "app-juez")], cwd=tmp, env=env,
             timeout=300)
    try:
        r = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        comprobacion(pasos, "juez_con_lo_propio", False, salida=(p.stdout + p.stderr)[-500:])
        return
    propio = str(navegador.carpeta())
    comprobacion(pasos, "juez_con_lo_propio",
                 r["exit"] == 0 and all(str(r[k]).startswith(propio) for k in ("playwright", "axe", "navegador")),
                 **r)


def cerrar(out: dict, pasos: list, limites: str) -> dict:
    out["ok"] = bool(pasos) and all(p["codigo"] == 0 for p in pasos)
    out["estado"] = "verificado" if out["ok"] else "fallido"
    out["limites"] = limites
    return out


def sin_constructor() -> str | None:
    """Motivo por el que este Python no puede construir la rueda sin red, o None si puede.

    Sin aislamiento hace falta setuptools con ``bdist_wheel`` propio (70.1 o posterior) o el paquete ``wheel``."""
    try:
        import setuptools
    except ImportError:
        return "setuptools no está instalado en este Python"
    try:
        partes = tuple(int(x) for x in setuptools.__version__.split(".")[:2])
    except ValueError:
        partes = (0, 0)
    if partes >= (70, 1):
        return None
    try:
        import wheel  # noqa: F401
    except ImportError:
        return (f"setuptools {setuptools.__version__} no trae bdist_wheel y falta el paquete wheel: "
                "no se puede construir la rueda sin red")
    return None


def verificar(tmp: Path) -> dict:
    pasos: list[dict] = []
    version = version_codigo()
    out = {"schema": "eolfi.verificar_paquete/v1", "version_codigo": version, "carpeta": str(tmp), "pasos": pasos}
    motivo = sin_constructor()
    if motivo:
        out.update(ok=False, estado="NO VERIFICADO", motivo=motivo)
        return out

    fuente = tmp / "fuente"
    rutas = copiar_fuente(fuente)

    dist = tmp / "dist"
    p = paso(pasos, "rueda", [sys.executable, "-m", "pip", "wheel", str(fuente), "--no-deps", "--no-build-isolation",
                              "--no-index", "-q", "-w", str(dist)], cwd=tmp)
    ruedas = sorted(dist.glob("eolfi-*.whl"))
    if p.returncode or len(ruedas) != 1:
        return cerrar(out, pasos, LIMITE_PIPX)
    rueda = ruedas[0]
    comprobacion(pasos, "version_rueda", rueda.name.startswith(f"eolfi-{version}-"), rueda=rueda.name)

    venv = tmp / "venv"
    if paso(pasos, "entorno_virtual", [sys.executable, "-m", "venv", str(venv)]).returncode:
        return cerrar(out, pasos, LIMITE_PIPX)
    bin_dir = venv / ("Scripts" if os.name == "nt" else "bin")
    py = bin_dir / ("python.exe" if os.name == "nt" else "python")
    exe = [str(bin_dir / ("eolfi.exe" if os.name == "nt" else "eolfi"))]
    if paso(pasos, "instalar", [str(py), "-m", "pip", "install", "--no-index", "--no-deps", "-q", str(rueda)],
            cwd=tmp).returncode:
        return cerrar(out, pasos, LIMITE_PIPX)

    home, env = entorno_aislado(tmp)
    comprobar_version_y_modo(pasos, exe, home, env, version, "entorno_virtual")

    cod = ("import pathlib,eolfi;r=pathlib.Path(eolfi.__file__).parent;"
           "print('\\n'.join(sorted(p.relative_to(r.parent).as_posix() for p in r.rglob('*') if p.is_file())))")
    p = paso(pasos, "listar_instalado", [str(py), "-c", cod], cwd=home, env=env, timeout=120)
    instalados = set(p.stdout.split())
    faltan = [r for r in esperados(rutas) if r not in instalados]
    comprobacion(pasos, "archivos", not faltan, esperados=len(esperados(rutas)), faltan=faltan[:50])

    comprobar_panel(pasos, exe, home, env, tmp)
    comprobar_navegador(pasos, py, exe, env, tmp)
    return cerrar(out, pasos, LIMITE_PIPX)


def main(argv: list[str]) -> int:
    conservar = "--conservar" in argv
    tmp = Path(tempfile.mkdtemp(prefix="eolfi-paquete-"))
    try:
        out = verificar(tmp)
    finally:
        if not conservar:
            shutil.rmtree(tmp, ignore_errors=True)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
