"""Verifica que un proyecto generado funciona: instala, fija versiones, compila y prueba.

- npm: `npm install` resuelve las versiones más recientes ("latest") y después
  se fijan en package.json como ^x.y.z con la versión realmente instalada.
- Python: crea un entorno virtual propio (.venv) dentro del proyecto; nunca
  instala nada en el Python global.
Cada paso registra código de salida, duración y el final de su salida.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable


# Variables que necesitan npm, pip, node y Python para funcionar (sistema, rutas, proxy y certificados).
# Todo lo demás (ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, tokens…) NO llega a las pruebas del proyecto,
# que pueden incluir código escrito por una IA a partir de datos no confiables.
_ENV_KEEP = {
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR", "HOME",
    "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "COMMONPROGRAMFILES", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "OS",
    "LANG", "LC_ALL", "LC_CTYPE", "TERM", "USER", "USERNAME", "LOGNAME", "SHELL",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE",
    "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_CERT",
    "NPM_CONFIG_REGISTRY", "NPM_CONFIG_CAFILE", "NVM_HOME", "NVM_SYMLINK", "PYTHONIOENCODING",
}


def safe_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() in _ENV_KEEP}
    env.update(CI="true", NEXT_TELEMETRY_DISABLED="1", EXPO_NO_TELEMETRY="1", npm_config_fund="false",
               npm_config_audit="false", npm_config_update_notifier="false", PIP_DISABLE_PIP_VERSION_CHECK="1")
    return env


def sandbox_env(home: Path) -> dict[str, str]:
    """Entorno para verificar código escrito por una IA (PLAN_MEJORAS A10): la carpeta personal es una
    carpeta temporal vacía, así que las pruebas no pueden leer ~/.ssh, ~/.eolfi (token del puente), las
    credenciales de npm/pip/git ni nada de tu perfil. Solo se comparten las CACHÉS de paquetes (npm, pip,
    NuGet, Cargo, Electron) para no descargar todo en cada ronda."""
    real_home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA") or real_home / ".cache")
    env = safe_env()
    for k in ("HOMEDRIVE", "HOMEPATH"):
        env.pop(k, None)
    (home / "AppData" / "Roaming").mkdir(parents=True, exist_ok=True)
    (home / "AppData" / "Local").mkdir(parents=True, exist_ok=True)
    env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(home / "AppData" / "Roaming"),
               LOCALAPPDATA=str(home / "AppData" / "Local"), XDG_CONFIG_HOME=str(home / ".config"),
               DOTNET_CLI_HOME=str(home), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    if os.name == "nt":
        caches = {"npm_config_cache": local / "npm-cache", "PIP_CACHE_DIR": local / "pip" / "Cache",
                  "ELECTRON_CACHE": local / "electron" / "Cache"}
    else:
        caches = {"npm_config_cache": real_home / ".npm", "PIP_CACHE_DIR": real_home / ".cache" / "pip",
                  "ELECTRON_CACHE": real_home / ".cache" / "electron"}
    caches.update(NUGET_PACKAGES=real_home / ".nuget" / "packages",
                  CARGO_HOME=Path(os.environ.get("CARGO_HOME") or real_home / ".cargo"),
                  RUSTUP_HOME=Path(os.environ.get("RUSTUP_HOME") or real_home / ".rustup"))
    for k, v in caches.items():
        env[k] = str(v)
    env["electron_config_cache"] = env["ELECTRON_CACHE"]
    return env


def _kill_tree(p: subprocess.Popen) -> None:
    """Matar el árbol entero: npm.cmd/npm lanzan node como nieto, y si el nieto sigue vivo con las
    tuberías abiertas, communicate() esperaría para siempre (PLAN_MEJORAS A9)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
    else:
        import signal

        try:
            os.killpg(p.pid, signal.SIGKILL)   # grupo creado con start_new_session=True
        except (OSError, AttributeError):
            pass
    try:
        p.kill()
    except OSError:
        pass


def _run(cmd: list[str], cwd: Path, timeout: float, env: dict[str, str] | None = None,
         full: bool = False) -> dict[str, Any]:
    start = time.time()
    try:
        p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             encoding="utf-8", errors="replace", env=env or safe_env(), stdin=subprocess.DEVNULL,
                             start_new_session=os.name != "nt")
    except OSError as exc:
        return {"cmd": " ".join(cmd), "exit": None, "seconds": 0, "tail": str(exc)}
    try:
        stdout, stderr = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(p)
        try:
            p.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        return {"cmd": " ".join(cmd), "exit": None, "seconds": round(time.time() - start, 1), "tail": "timeout"}
    out = (stdout + "\n" + stderr).strip()
    return {"cmd": " ".join(cmd[1:] if cmd[0].endswith(("npm.cmd", "npm")) else cmd[-3:]),
            "exit": p.returncode, "seconds": round(time.time() - start, 1),
            "tail": out if full else out[-2500:]}


def pin_nuget_versions(project: Path, dotnet: str) -> dict[str, str]:
    """Sustituye Version="*" por la versión que NuGet restauró de verdad (proyecto reproducible)."""
    import re

    r = _run([dotnet, "list", "package", "--format", "json"], project, 300, full=True)   # sin recortar (M26)
    try:
        start = r["tail"].index("{")
        doc = json.loads(r["tail"][start:])
    except ValueError:
        return {}
    resolved: dict[str, str] = {}
    for proj in doc.get("projects", []):
        for fw in proj.get("frameworks", []):
            for pkg in fw.get("topLevelPackages", []):
                resolved[pkg["id"]] = pkg.get("resolvedVersion", "")
    for csproj in project.rglob("*.csproj"):
        if any(part in ("bin", "obj") for part in csproj.parts):
            continue
        text = csproj.read_text(encoding="utf-8")
        for pid, ver in resolved.items():
            if ver:
                text = re.sub(rf'(<PackageReference Include="{re.escape(pid)}" Version=")\*"', lambda m, v=ver: m.group(1) + v + '"', text)
        csproj.write_text(text, encoding="utf-8")
    return resolved


def pin_npm_versions(project: Path) -> dict[str, str]:
    """Sustituye "latest" por ^<versión instalada> para que el proyecto sea reproducible."""
    pkg_path = project / "package.json"
    pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    pinned = {}
    for section in ("dependencies", "devDependencies"):
        for name, ver in list((pkg.get(section) or {}).items()):
            if ver != "latest":
                continue
            installed = project / "node_modules" / name / "package.json"
            if installed.is_file():
                v = json.loads(installed.read_text(encoding="utf-8")).get("version")
                if v:
                    pkg[section][name] = f"^{v}"
                    pinned[name] = v
    pkg_path.write_text(json.dumps(pkg, indent=2) + "\n", encoding="utf-8")
    return pinned


def verify(project: str | Path, target: str, *, progress: Callable[[str], None] | None = None,
           timeout: float = 900.0, install: bool = True, sandbox: bool = False) -> dict[str, Any]:
    """install=False reutiliza node_modules/.venv existentes (solo compila y prueba).
    sandbox=True (código escrito por una IA): carpeta personal temporal, ver sandbox_env()."""
    if not sandbox:
        return _verify(project, target, progress=progress, timeout=timeout, install=install, env=None)
    import shutil as _shutil
    import tempfile

    home = Path(tempfile.mkdtemp(prefix="eolfi-sandbox-home-"))
    try:
        (progress or (lambda _m: None))(f"verificación aislada: carpeta personal temporal {home}")
        return _verify(project, target, progress=progress, timeout=timeout, install=install, env=sandbox_env(home))
    finally:
        _shutil.rmtree(home, ignore_errors=True)


def _verify(project: str | Path, target: str, *, progress: Callable[[str], None] | None,
            timeout: float, install: bool, env: dict[str, str] | None) -> dict[str, Any]:
    log = progress or (lambda _m: None)
    root = Path(project).resolve()
    steps: list[dict[str, Any]] = []
    pinned: dict[str, str] = {}

    def step(cmd: list[str], label: str, extra_env: dict[str, str] | None = None,
             step_timeout: float | None = None) -> bool:
        log(f"→ {label}")
        run_env = {**(env or safe_env()), **(extra_env or {})}
        r = _run(cmd, root, step_timeout or timeout, env=run_env)
        r["step"] = label
        steps.append(r)
        log(f"  {'OK' if r['exit'] == 0 else 'FALLO'} ({r['seconds']} s)")
        return r["exit"] == 0

    if target == "dotnet":
        dotnet = shutil.which("dotnet") or next(
            (str(c) for c in (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "dotnet" / "dotnet.exe",
                              Path("/usr/local/share/dotnet/dotnet"), Path("/usr/share/dotnet/dotnet")) if c.is_file()), None)
        if not dotnet:
            return {"ok": False, "steps": [], "error": ".NET SDK no está instalado (https://dot.net)"}
        fresh = install or not any(root.glob("src/*/obj/project.assets.json"))
        ok = True
        if fresh:
            ok = step([dotnet, "restore"], "restaurar paquetes NuGet (última versión estable)")
            if ok:
                pinned = pin_nuget_versions(root, dotnet)
                log(f"  versiones: {', '.join(f'{k}@{v}' for k, v in pinned.items())}" if pinned else
                    "  AVISO: no se pudo leer «dotnet list package»: las versiones NuGet quedan sin fijar (*)")
        if ok:
            ok = step([dotnet, "build", "-c", "Release", "--no-restore"], "compilar (avisos = errores)")
        if ok:
            ok = step([dotnet, "test", "-c", "Release", "--no-build"], "pruebas (xUnit)")
        if ok:
            csproj = next((root / "src").glob("*/*.csproj"), None)
            if csproj is None:
                return {"ok": False, "steps": steps, "error": "no se encuentra el .csproj en src/"}
            exe = csproj.parent / "bin" / "Release" / "net10.0" / (csproj.stem + (".exe" if os.name == "nt" else ""))
            # Directo (sin envoltorio): si se cuelga, _run mata el árbol entero a los 180 s.
            ok = step([str(exe)], "prueba de humo: abrir la ventana nativa de verdad",
                      extra_env={"APP_SMOKE": "1"}, step_timeout=180)
        if ok and fresh:   # publicar solo en la verificación completa, no en cada ronda de la IA
            import platform

            os_rid = {"Windows": "win", "Darwin": "osx", "Linux": "linux"}.get(platform.system())
            if os_rid is None:   # FreeBSD y otros: .NET no publica autocontenido para ellos (B20)
                log(f"  publicar: {platform.system()} no tiene un identificador de .NET; se omite")
                ok = bool(steps) and all(s["exit"] == 0 for s in steps)
                return {"ok": ok, "steps": steps, "pinned": pinned}
            rid = os_rid +                 ("-arm64" if platform.machine().lower() in ("arm64", "aarch64") else "-x64")
            step([dotnet, "publish", str(csproj), "-c", "Release", "-r", rid, "--self-contained",
                  "-p:PublishSingleFile=true", "-o", str(root / "publish" / rid)],
                 f"publicar ejecutable autocontenido para este sistema ({rid})")
        ok = bool(steps) and all(s["exit"] == 0 for s in steps)
        return {"ok": ok, "steps": steps, "pinned": pinned}

    if target == "cli":
        venv = root / ".venv"
        py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        ok = True
        if install or not py.is_file():
            ok = step([sys.executable, "-m", "venv", str(venv)], "crear entorno virtual")
            if ok:
                ok = step([str(py), "-m", "pip", "install", "-q", "-e", ".[test]"], "instalar el comando (pip install -e .)")
        if ok:
            ok = step([str(py), "-m", "pytest", "-q"], "pruebas (pytest)")
        if ok:
            from eolfi import compat_toml as tomllib

            cmd = next(iter(tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]))
            exe = venv / ("Scripts" if os.name == "nt" else "bin") / (cmd + (".exe" if os.name == "nt" else ""))
            step([str(exe), "--json", "info"], f"ejecutar el comando instalado ({cmd} --json info)")
        ok = bool(steps) and all(s["exit"] == 0 for s in steps)
        return {"ok": ok, "steps": steps, "pinned": pinned}

    if target == "tauri":
        npm, cargo = shutil.which("npm"), shutil.which("cargo")
        if not (npm and cargo):
            return {"ok": False, "steps": [], "error": "Faltan Node.js/npm o Rust (cargo): https://rustup.rs"}
        fresh = install or not (root / "node_modules").is_dir()
        ok = True
        if fresh:
            ok = step([npm, "install", "--no-audit", "--no-fund"], "instalar la CLI de Tauri (latest)")
            pinned = pin_npm_versions(root) if ok else {}
        if ok:
            ok = step([npm, "test"], "pruebas (seguridad de la configuración e interfaz)")
        if ok and (fresh or not (root / "src-tauri" / "icons").is_dir()):
            ok = step([npm, "run", "icons"], "generar iconos (Windows .ico, macOS .icns, PNG)")
        if ok:
            ok = step([npm, "run", "build:debug"], "compilar la app nativa con Rust (tauri build --debug)")
        if ok:
            from eolfi import compat_toml as tomllib

            crate = tomllib.loads((root / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8"))["package"]["name"]
            exe = root / "src-tauri" / "target" / "debug" / (crate + (".exe" if os.name == "nt" else ""))
            step([str(exe)], "prueba de humo: arrancar la app nativa de verdad",
                 extra_env={"APP_SMOKE": "1"}, step_timeout=180)
        ok = bool(steps) and all(s["exit"] == 0 for s in steps)
        return {"ok": ok, "steps": steps, "pinned": pinned}

    if target == "desktop":
        npm = shutil.which("npm")
        if not npm:
            return {"ok": False, "steps": [], "error": "Node.js/npm no están instalados"}
        fresh = install or not (root / "node_modules").is_dir()
        ok = True
        if fresh:
            ok = step([npm, "install", "--no-audit", "--no-fund"], "instalar Electron y electron-builder (latest)")
            pinned = pin_npm_versions(root) if ok else {}
        if ok:
            ok = step([npm, "test"], "pruebas (seguridad de la ventana, interfaz e instaladores)")
        if ok:
            ok = step([npm, "run", "smoke"], "prueba de humo: arrancar la app de escritorio de verdad")
        if ok and fresh:
            step([npm, "run", "pack"], "empaquetar para este sistema (electron-builder --dir)")
        ok = bool(steps) and all(s["exit"] == 0 for s in steps)
        return {"ok": ok, "steps": steps, "pinned": pinned}

    if target == "expo":
        from eolfi.generador.generators_mobile import EXPO_DEPS, EXPO_DEV

        npm, npx = shutil.which("npm"), shutil.which("npx")
        if not (npm and npx):
            return {"ok": False, "steps": [], "error": "Node.js/npm no están instalados"}
        fresh = install or not (root / "node_modules").is_dir()
        ok = True
        if fresh:
            ok = step([npm, "install", "--no-audit", "--no-fund"], "instalar Expo (latest)")
            if ok:
                pinned = pin_npm_versions(root)
                ok = step([npx, "expo", "install", *EXPO_DEPS], "alinear React/React Native con el SDK (expo install)")
            if ok:
                ok = step([npx, "expo", "install", *EXPO_DEV, "--", "--save-dev"], "herramientas de pruebas y tipos")
        if ok:
            pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
            for sec in ("dependencies", "devDependencies"):
                pinned.update({k: v for k, v in (pkg.get(sec) or {}).items()})
            log(f"  versiones: {', '.join(f'{k}@{v}' for k, v in pinned.items())}")
            ok = step([npx, "expo", "config", "--type", "public", "--json"], "validar configuración nativa (app.json)")
        if ok:
            ok = step([npm, "run", "typecheck"], "comprobar tipos (tsc)")
        if ok:
            ok = step([npm, "test"], "pruebas (Jest + Testing Library)")
        if ok and fresh:
            step([npm, "run", "build:web"], "empaquetar versión web (expo export)")
        ok = bool(steps) and all(s["exit"] == 0 for s in steps)
        return {"ok": ok, "steps": steps, "pinned": pinned}

    if target in ("static", "react", "vue", "svelte", "next", "express"):
        npm = shutil.which("npm")
        node = shutil.which("node")
        if not (npm and node):
            return {"ok": False, "steps": [], "error": "Node.js/npm no están instalados"}
        if target == "static":
            step([node, "--test"], "pruebas (node --test)")
        else:
            ok = True
            if install or not (root / "node_modules").is_dir():
                ok = step([npm, "install", "--no-audit", "--no-fund"], "instalar dependencias (latest)")
                if ok:
                    pinned = pin_npm_versions(root)
                    log(f"  versiones fijadas: {', '.join(f'{k}@{v}' for k, v in pinned.items())}")
            if ok:
                if target in ("react", "vue", "svelte", "next"):
                    ok = step([npm, "run", "build"], "compilar (tipos + bundle)")
                if ok:
                    step([npm, "test"], "pruebas")
    elif target in ("fastapi", "django"):
        venv = root / ".venv"
        py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        fresh = install or not py.is_file()
        ok = True
        if fresh:
            ok = step([sys.executable, "-m", "venv", str(venv)], "crear entorno virtual")
            if ok:
                ok = step([str(py), "-m", "pip", "install", "-q", "-r", "requirements.txt"],
                          "instalar dependencias (latest)")
        if ok and fresh:
            freeze = _run([str(py), "-m", "pip", "freeze"], root, 120, full=True)
            wanted = {"fastapi", "uvicorn", "httpx", "httpx2", "pytest", "pydantic", "starlette", "django"}
            lines = [l for l in freeze["tail"].splitlines() if "==" in l and l.split("==")[0].lower() in wanted]
            pinned = {l.split("==")[0]: l.split("==")[1] for l in lines}
            if not pinned:
                log("  AVISO: «pip freeze» no devolvió versiones: requirements.txt queda sin fijar")
            reqs = (root / "requirements.txt").read_text(encoding="utf-8").split()
            fixed = []
            for r in reqs:
                base = r.split("[")[0].lower()
                v = next((ver for n, ver in pinned.items() if n.lower() == base), None)
                fixed.append(f"{r}>={v}" if v else r)
            (root / "requirements.txt").write_text("\n".join(fixed) + "\n", encoding="utf-8")
        if ok:
            if target == "django":
                if step([str(py), "manage.py", "check"], "comprobar proyecto (manage.py check)"):
                    step([str(py), "manage.py", "test", "-v", "1"], "pruebas (manage.py test)")
            else:
                step([str(py), "-m", "pytest", "-q"], "pruebas (pytest)")
    else:
        return {"ok": False, "steps": [], "error": f"target desconocido {target}"}
    ok = bool(steps) and all(s["exit"] == 0 for s in steps)
    return {"ok": ok, "steps": steps, "pinned": pinned}
