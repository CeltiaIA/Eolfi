"""Análisis de repositorios para aprender cómo están organizados.

Fuente: una carpeta local o una URL git (se clona en superficial). Produce
evidencias de lenguajes, manifiestos y dependencias, pila tecnológica,
estructura de carpetas, pruebas, CI, contenedores, documentación e higiene,
más un plano para empezar un proyecto parecido.

Seguridad: el clon se hace sin hooks, sin submódulos, sin enlaces
simbólicos y sin pedir credenciales. NUNCA se ejecuta nada del repositorio
(ni scripts de npm, ni setup.py, ni Makefile): todo se lee como texto.
De archivos sensibles (.env, claves) solo se informa del nombre.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from eolfi import compat_toml as tomllib
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from eolfi.sites import stack

SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", "out", "target", ".next", ".nuxt", ".svelte-kit",
             ".venv", "venv", "env", "__pycache__", ".gradle", ".idea", "Pods", "DerivedData", "coverage",
             ".cache", "bin", "obj", ".tox", ".mypy_cache", ".pytest_cache", ".turbo", ".parcel-cache", ".dart_tool"}
MAX_FILES = 60_000
MAX_TEXT = 1024 * 1024
LINE_COUNT_BUDGET = 400 * 1024 * 1024
MAX_MANIFEST = 2 * 1024 * 1024
CLONE_TTL = 7 * 24 * 3600   # los clones de samples/repos se borran a los 7 días

LANG = {
    ".py": "Python", ".pyi": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".jsx": "JavaScript (JSX)", ".ts": "TypeScript", ".tsx": "TypeScript (TSX)", ".vue": "Vue", ".svelte": "Svelte",
    ".astro": "Astro", ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "SCSS", ".sass": "Sass",
    ".less": "Less", ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".scala": "Scala", ".groovy": "Groovy",
    ".go": "Go", ".rs": "Rust", ".c": "C", ".h": "C/C++ header", ".cc": "C++", ".cpp": "C++", ".cxx": "C++",
    ".hpp": "C++", ".cs": "C#", ".fs": "F#", ".vb": "Visual Basic", ".swift": "Swift", ".m": "Objective-C",
    ".mm": "Objective-C++", ".dart": "Dart", ".rb": "Ruby", ".php": "PHP", ".lua": "Lua", ".pl": "Perl",
    ".r": "R", ".jl": "Julia", ".ex": "Elixir", ".exs": "Elixir", ".erl": "Erlang", ".hs": "Haskell",
    ".clj": "Clojure", ".zig": "Zig", ".nim": "Nim", ".sol": "Solidity", ".sh": "Shell", ".bash": "Shell",
    ".ps1": "PowerShell", ".bat": "Batch", ".sql": "SQL", ".graphql": "GraphQL", ".proto": "Protocol Buffers",
    ".md": "Markdown", ".mdx": "MDX", ".rst": "reStructuredText", ".json": "JSON", ".yaml": "YAML",
    ".yml": "YAML", ".toml": "TOML", ".xml": "XML", ".ipynb": "Jupyter", ".tf": "Terraform", ".gd": "GDScript",
    ".glsl": "GLSL", ".wgsl": "WGSL", ".asm": "Assembly", ".s": "Assembly",
}
CODE_LANGS = {v for k, v in LANG.items() if k not in (".md", ".mdx", ".rst", ".json", ".yaml", ".yml", ".toml", ".xml")}
SENSITIVE = re.compile(r"(?:^|/)(?:\.env(?:\.(?!example|sample|template|dist)[\w.-]+)?|id_rsa|id_ed25519|.*\.pem|.*\.p12|.*\.pfx|"
                       r"credentials\.json|service-account.*\.json|\.npmrc|\.pypirc|secrets?\.ya?ml)$", re.I)
TOOLING = {
    "tsconfig.json": "TypeScript", ".editorconfig": "EditorConfig", "biome.json": "Biome", ".prettierrc": "Prettier",
    "prettier.config.js": "Prettier", ".eslintrc": "ESLint", ".eslintrc.json": "ESLint", ".eslintrc.js": "ESLint",
    "eslint.config.js": "ESLint", "eslint.config.mjs": "ESLint", "ruff.toml": "Ruff", ".ruff.toml": "Ruff",
    ".flake8": "Flake8", "mypy.ini": "mypy", ".pre-commit-config.yaml": "pre-commit", "Makefile": "Make",
    "justfile": "just", "turbo.json": "Turborepo", "nx.json": "Nx", "lerna.json": "Lerna",
    "pnpm-workspace.yaml": "pnpm workspaces", ".nvmrc": "nvm", ".tool-versions": "asdf", "renovate.json": "Renovate",
    ".github/dependabot.yml": "Dependabot", "rustfmt.toml": "rustfmt", ".golangci.yml": "golangci-lint",
    "Dockerfile": "Docker", "docker-compose.yml": "Docker Compose", "compose.yaml": "Docker Compose",
    "docker-compose.yaml": "Docker Compose", ".devcontainer/devcontainer.json": "Dev Container",
    "vercel.json": "Vercel", "netlify.toml": "Netlify", "fly.toml": "Fly.io", "render.yaml": "Render",
    "Procfile": "Heroku/Procfile", "wrangler.toml": "Cloudflare Workers", "wrangler.jsonc": "Cloudflare Workers",
}
LOCKFILES = {"package-lock.json": "npm", "yarn.lock": "yarn", "pnpm-lock.yaml": "pnpm", "bun.lockb": "bun",
             "bun.lock": "bun", "poetry.lock": "poetry", "uv.lock": "uv", "Pipfile.lock": "pipenv",
             "Cargo.lock": "cargo", "go.sum": "go modules", "Gemfile.lock": "bundler", "composer.lock": "composer",
             "pubspec.lock": "pub", "packages.lock.json": "nuget"}
DIR_ROLES = {
    "src": "código fuente", "lib": "librería / código", "app": "aplicación (rutas/pantallas)",
    "pages": "páginas / rutas", "components": "componentes de UI", "public": "assets estáticos servidos tal cual",
    "static": "assets estáticos", "assets": "recursos (imágenes, fuentes)", "styles": "estilos",
    "test": "pruebas", "tests": "pruebas", "__tests__": "pruebas", "spec": "pruebas", "e2e": "pruebas end-to-end",
    "docs": "documentación", "doc": "documentación", "examples": "ejemplos", "scripts": "scripts de tareas",
    "tools": "herramientas internas", "cmd": "binarios (Go)", "internal": "paquetes internos (Go)",
    "pkg": "paquetes reutilizables", "api": "API / endpoints", "server": "servidor", "client": "cliente",
    "packages": "monorepo: paquetes", "apps": "monorepo: aplicaciones", "config": "configuración",
    ".github": "CI y plantillas de GitHub", "migrations": "migraciones de base de datos",
    "android": "proyecto Android", "ios": "proyecto iOS", "src-tauri": "backend Rust de Tauri",
    "include": "cabeceras C/C++", "benches": "benchmarks", "crates": "monorepo: crates de Rust",
}


# ---------------------------------------------------------------------------
# Clonado seguro
# ---------------------------------------------------------------------------
_GIT_URL = re.compile(r"^(?:https?://[\w.-]+(?::\d+)?/[\w./~%-]+|git@[\w.-]+:[\w./~-]+|ssh://[\w.@-]+/[\w./~-]+)$")


def is_git_url(s: str) -> bool:
    return bool(_GIT_URL.match(s.strip()))


def redact_url(url: str) -> str:
    return re.sub(r"//[^/@\s]+@", "//", url)


# ---------------------------------------------------------------------------
# git aislado: un repo analizado (o su .git/config) nunca puede ejecutar nada
# ---------------------------------------------------------------------------
# Opciones que git podría tomar del .git/config del repo (o de un [include]) y que ejecutan programas o
# usan credenciales. Las opciones de línea de comandos (-c) tienen prioridad sobre cualquier archivo.
SAFE_GIT_CONFIG = (
    f"core.hooksPath={os.devnull}", "core.fsmonitor=false", "core.pager=cat", "core.askPass=",
    "core.sshCommand=ssh -F none -o BatchMode=yes -o IdentitiesOnly=yes -o IdentityAgent=none",
    "credential.helper=", "log.showSignature=false", "gpg.program=false", "gpg.ssh.program=false",
    "gpg.x509.program=false", "diff.external=", "core.symlinks=false", "submodule.recurse=false",
    "protocol.allow=never",
)


def safe_git_env() -> dict[str, str]:
    """Sin configuración del sistema ni global del usuario, sin agente SSH ni preguntas de credenciales."""
    env = {k: v for k, v in os.environ.items() if k not in ("SSH_AUTH_SOCK", "GIT_SSH", "GIT_SSH_COMMAND",
                                                            "GIT_ASKPASS", "GIT_EXEC_PATH", "GIT_DIR",
                                                            "GIT_WORK_TREE", "GIT_CONFIG_PARAMETERS")
           and not k.startswith(("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0",
               GIT_PAGER="cat", GCM_INTERACTIVE="never", GIT_LFS_SKIP_SMUDGE="1",
               GIT_SSH_COMMAND="ssh -F none -o BatchMode=yes -o IdentitiesOnly=yes -o IdentityAgent=none")
    return env


def github_auth_env(url: str) -> dict[str, str]:
    """GITHUB_TOKEN (del entorno o del .env) para clonar repos privados de github.com por https.

    Va como cabecera HTTP en variables GIT_CONFIG_* del proceso de git: no sale en la línea de comandos (la ven
    otros programas), no se guarda en el .git/config del clon y solo se aplica a https://github.com/ (sin
    redirecciones, así que nunca viaja a otro host)."""
    import base64
    import urllib.parse

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token or not url.startswith("https://"):
        return {}
    parts = urllib.parse.urlsplit(url)
    if (parts.hostname or "").lower() != "github.com" or parts.port not in (None, 443) or parts.username:
        return {}
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}"}


def safe_git(git: str, args: list[str], *, cwd: Path | None = None, extra_config: tuple[str, ...] = (),
             timeout: float = 30.0, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    cmd = [git]
    if cwd is not None:
        cmd += ["-C", str(cwd)]
    for kv in SAFE_GIT_CONFIG + extra_config:
        cmd += ["-c", kv]
    cmd += ["--no-pager", *args]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, env={**safe_git_env(), **(extra_env or {})}, stdin=subprocess.DEVNULL)


def clone(url: str, workdir: str | Path, timeout: float = 600.0) -> Path:
    """Clon superficial y endurecido: solo https/ssh, host público, sin redirecciones, sin hooks,
    sin submódulos, sin symlinks y en una carpeta única (dos análisis a la vez no se pisan)."""
    import tempfile
    import time
    import urllib.parse

    if not is_git_url(url):
        raise ValueError(f"URL git no válida: {redact_url(url)[:120]}")
    if url.startswith("http://"):
        raise ValueError("Solo se clona por https:// o ssh (http:// permitiría alcanzar servicios internos)")
    git = shutil.which("git")
    if not git:
        raise FileNotFoundError("git no está instalado")
    host = (urllib.parse.urlsplit(url).hostname if "://" in url else url.split("@", 1)[-1].split(":", 1)[0]) or ""
    from eolfi.sites.fetch import host_is_private

    if host_is_private(host):
        raise ValueError(f"bloqueado: {host} es una dirección no pública (anti-SSRF)")
    name = re.sub(r"\.git$", "", url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]) or "repo"
    name = re.sub(r"[^\w.-]", "_", name)[:60]
    prefix = f"{name}-{hashlib.sha256(url.encode()).hexdigest()[:10]}-"
    base = Path(workdir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    for old in base.iterdir():
        # Clones anteriores de esta URL con más de 1 h, y CUALQUIER clon con más de 7 días: samples/repos
        # ya no crece sin límite (M33).
        try:
            age = time.time() - old.stat().st_mtime
            ours = re.match(r"^[\w.-]+-[0-9a-f]{10}-\w+$", old.name)   # solo carpetas creadas por clone()
            if ours and old.is_dir() and ((old.name.startswith(prefix) and age > 3600) or age > CLONE_TTL):
                _rmtree(old)
        except OSError:
            pass
    dest = Path(tempfile.mkdtemp(prefix=prefix, dir=base))
    auth = github_auth_env(url)
    try:
        # Tope de tamaño de cada archivo (evita llenar el disco con blobs enormes) y sin redirecciones.
        proc = safe_git(git, ["clone", "--depth", "1", "--single-branch", "--no-recurse-submodules",
                              "--filter=blob:limit=5m", "--", url, str(dest)],
                        extra_config=("protocol.https.allow=always", "protocol.ssh.allow=always",
                                      "http.followRedirects=false"), timeout=timeout, extra_env=auth)
    except subprocess.TimeoutExpired as exc:
        _rmtree(dest)
        raise ValueError(f"git clone superó {int(timeout)} s") from exc
    if proc.returncode != 0:
        _rmtree(dest)
        err = redact_url(proc.stderr.strip())[-400:]
        if "github.com" in url and re.search(r"not found|could not read Username|Authentication failed|403", err, re.I):
            err += (" · Si es un repositorio privado: pon tu token en GITHUB_TOKEN del archivo .env (permiso «repo»)"
                    if not auth else " · El GITHUB_TOKEN no da acceso a este repositorio (¿caducado o sin permiso «repo»?)")
        raise ValueError(f"git clone falló: {err}")
    return dest


def _rmtree(path: Path) -> None:
    import sys

    def fix(func, p, _exc):
        os.chmod(p, 0o700)   # git marca sus objetos como solo lectura en Windows
        func(p)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=fix)
    else:
        shutil.rmtree(path, onerror=fix)


_SIZE_CACHE: dict[str, int] = {}


def _size(p: Path) -> int:
    """Tamaño con caché por análisis (antes cada archivo se consultaba dos veces en repos grandes; B23)."""
    key = str(p)
    if key in _SIZE_CACHE:
        return _SIZE_CACHE[key]
    try:
        n = p.stat().st_size
    except OSError:
        n = -1
    if len(_SIZE_CACHE) < 500_000:
        _SIZE_CACHE[key] = n
    return max(n, 0)


# ---------------------------------------------------------------------------
# Lectura de manifiestos (todo como texto; nada se ejecuta)
# ---------------------------------------------------------------------------
def _is_link(path: str) -> bool:
    """Enlace simbólico o junction de Windows: no se siguen (podrían apuntar fuera del repo)."""
    return os.path.islink(path) or (hasattr(os.path, "isjunction") and os.path.isjunction(path))


def _read(p: Path, limit: int = MAX_MANIFEST) -> str:
    try:
        if _is_link(str(p)):
            return ""
        if p.stat().st_size > limit:
            return ""
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _pkg_name(spec: str) -> str:
    return re.split(r"[\s<>=!~;\[@(]", spec.strip(), maxsplit=1)[0].lower()


def parse_package_json(text: str) -> tuple[set[str], dict[str, Any]]:
    d = json.loads(text)
    if not isinstance(d, dict):
        return set(), {}
    deps = {**(d.get("dependencies") or {}), **(d.get("peerDependencies") or {})}
    dev = d.get("devDependencies") or {}
    info = {
        "name": d.get("name"), "version": d.get("version"), "private": d.get("private"), "type": d.get("type"),
        "scripts": {k: str(v)[:200] for k, v in list((d.get("scripts") or {}).items())[:40]},
        "dependencies": sorted(deps)[:120], "dev_dependencies": sorted(dev)[:120],
        "engines": d.get("engines"), "workspaces": d.get("workspaces"),
        "package_manager": d.get("packageManager"),
        "entry": {k: d[k] for k in ("main", "module", "bin", "exports") if k in d and not isinstance(d[k], dict)},
    }
    return {k.lower() for k in deps} | {"dev:" + k.lower() for k in dev}, info


def parse_pyproject(text: str) -> tuple[set[str], dict[str, Any]]:
    d = tomllib.loads(text)
    proj = d.get("project", {})
    deps = [_pkg_name(x) for x in proj.get("dependencies", [])]
    for group in (proj.get("optional-dependencies") or {}).values():
        deps += [_pkg_name(x) for x in group]
    for group in (d.get("dependency-groups") or {}).values():
        deps += ["dev:" + _pkg_name(x) for x in group if isinstance(x, str)]
    poetry = d.get("tool", {}).get("poetry", {})
    deps += [k.lower() for k in poetry.get("dependencies", {}) if k.lower() != "python"]
    deps += ["dev:" + k.lower() for k in poetry.get("group", {}).get("dev", {}).get("dependencies", {})]
    info = {"name": proj.get("name") or poetry.get("name"), "requires_python": proj.get("requires-python"),
            "build_backend": d.get("build-system", {}).get("build-backend"),
            "scripts": proj.get("scripts") or poetry.get("scripts"),
            "dependencies": sorted(x for x in set(deps) if not x.startswith("dev:"))[:120],
            "dev_dependencies": sorted(x[4:] for x in set(deps) if x.startswith("dev:"))[:120], "tools": sorted(d.get("tool", {}))[:20]}
    return set(deps), info


def parse_requirements(text: str) -> set[str]:
    out = set()
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if line and not line.startswith(("-", "git+", "http")):
            out.add(_pkg_name(line))
    return out


def parse_cargo(text: str) -> tuple[set[str], dict[str, Any]]:
    d = tomllib.loads(text)
    deps = set()
    for key in ("dependencies", "dev-dependencies", "build-dependencies"):
        deps |= {k.lower() for k in d.get(key, {})}
    deps |= {k.lower() for k in d.get("workspace", {}).get("dependencies", {})}
    return deps, {"name": d.get("package", {}).get("name"), "edition": d.get("package", {}).get("edition"),
                  "workspace_members": d.get("workspace", {}).get("members"), "dependencies": sorted(deps)[:120]}


def parse_go_mod(text: str) -> tuple[set[str], dict[str, Any]]:
    module = re.search(r"^module\s+(\S+)", text, re.M)
    gov = re.search(r"^go\s+(\S+)", text, re.M)
    # ^[ \t]* y no ^\s*: con miles de saltos de línea ^\s* era cuadrático (A15). También «require x v1» en una línea.
    deps = set(re.findall(r"^[ \t]*(?:require[ \t]+)?([\w.-]+\.[\w.-]+/[\w./-]+)[ \t]+v[\w.+-]+", text, re.M))
    return {d.lower() for d in deps}, {"module": module.group(1) if module else None,
                                       "go": gov.group(1) if gov else None, "dependencies": sorted(deps)[:120]}


def parse_pom(text: str) -> tuple[set[str], dict[str, Any]]:
    if "<!ENTITY" in text or "<!DOCTYPE" in text:
        raise ValueError("pom.xml con DOCTYPE/ENTITY: no se parsea (posible XML hostil)")
    root = ET.fromstring(text)
    ns = re.match(r"\{.*\}", root.tag)
    n = ns.group(0) if ns else ""
    deps = set()
    for dep in root.iter(f"{n}dependency"):
        g, a = dep.findtext(f"{n}groupId") or "", dep.findtext(f"{n}artifactId") or ""
        deps.add(f"{g}:{a}".lower())
    parent = root.find(f"{n}parent")
    if parent is not None:
        deps.add(f"{parent.findtext(f'{n}groupId') or ''}:{parent.findtext(f'{n}artifactId') or ''}".lower())
    return deps, {"artifact": root.findtext(f"{n}artifactId"), "packaging": root.findtext(f"{n}packaging"),
                  "dependencies": sorted(deps)[:120]}


def parse_gradle(text: str) -> set[str]:
    conf = r"(?:implementation|api|compileOnly|runtimeOnly|testImplementation|androidTestImplementation|kapt|ksp|classpath)"
    deps = {m.lower() for m in re.findall(conf + r"""\s*\(?\s*["']([^"':]+:[^"':]+)""", text)}
    # Catálogo de versiones: implementation(libs.androidx.core.ktx) → libs:androidx.core.ktx (M37).
    deps |= {"libs:" + m.lower().replace("_", ".").replace("-", ".")
             for m in re.findall(conf + r"\s*\(?\s*libs\.([\w.]+)", text)}
    # Plugins: id("com.android.application"), id 'kotlin-android', alias(libs.plugins.android.application).
    deps |= {"plugin:" + m.lower() for m in re.findall(r"""\bid\s*\(?\s*["']([\w.-]+)["']""", text)}
    deps |= {"plugin:" + m.lower().replace("android.application", "com.android.application")
             .replace("android.library", "com.android.library")
             for m in re.findall(r"alias\s*\(\s*libs\.plugins\.([\w.]+)", text)}
    if re.search(r"""apply\s+plugin:\s*["']com\.android\.application["']""", text):
        deps.add("plugin:com.android.application")
    return deps


def parse_csproj(text: str) -> tuple[set[str], dict[str, Any]]:
    deps = set(re.findall(r'<PackageReference\s+Include="([^"]+)"', text))
    deps |= set(re.findall(r'<PackageVersion\s+Include="([^"]+)"', text))   # Directory.Packages.props (CPM)
    tfm = re.search(r"<TargetFrameworks?>([^<]+)<", text)
    sdk = re.search(r'<Project\s+Sdk="([^"]+)"', text)
    out = {d.lower() for d in deps}
    # Propiedades que deciden el tipo de app (M37): WPF, WinForms, MAUI y web (Sdk.Web).
    for prop in ("UseWPF", "UseWindowsForms", "UseMaui"):
        if re.search(rf"<{prop}>\s*true\s*</{prop}>", text, re.I):
            out.add(f"msbuild:{prop.lower()}")
    if sdk:
        out.add("sdk:" + sdk.group(1).lower())
    return out, {"target_framework": tfm.group(1) if tfm else None,
                 "sdk": sdk.group(1) if sdk else None, "dependencies": sorted(deps)[:120]}


def parse_pubspec(text: str) -> set[str]:
    deps, block = set(), False
    for line in text.splitlines():
        if re.match(r"^(dependencies|dev_dependencies):", line):
            block = True
            continue
        if block and re.match(r"^\S", line):
            block = False
        m = re.match(r"^  ([a-z_][\w]*):", line) if block else None
        if m:
            deps.add(m.group(1))
    return deps


# ---------------------------------------------------------------------------
# Análisis principal
# ---------------------------------------------------------------------------
_PAGE_FILE = re.compile(r"^(?:src/)?app/(?:(.*)/)?page\.(?:tsx|jsx|ts|js|mdx)$")
_ROUTE_FILE = re.compile(r"^(?:src/)?app/(?:(.*)/)?route\.(?:ts|js|mjs)$")
_PAGES_FILE = re.compile(r"^(?:src/)?pages/(.+)\.(?:tsx|jsx|ts|js)$")
_HTTP_EXPORT = re.compile(r"export\s+(?:async\s+)?(?:function\s+|const\s+)(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b")


def _route_path(dirpart: str | None) -> str:
    """app/(grupo)/@slot/x/[id] → /x/[id]: los grupos y slots no forman parte de la URL."""
    segs = [s for s in (dirpart or "").split("/") if s and not (s.startswith("(") and s.endswith(")"))
            and not s.startswith("@")]
    return "/" + "/".join(segs)


def _routes(files: list[str], root: Path) -> dict[str, Any]:
    """Rutas por convención de archivos (Next.js app/ y pages/): páginas y API con sus métodos HTTP exportados.
    Es un contrato de interfaz (qué URL y métodos existen), no se copia código."""
    pages, api = set(), {}
    for p in files:
        if m := _PAGE_FILE.match(p):
            pages.add(_route_path(m.group(1)))
        elif m := _ROUTE_FILE.match(p):
            text = _read(root / p, 256 * 1024)
            api[_route_path(m.group(1))] = sorted(set(_HTTP_EXPORT.findall(text))) or ["?"]
        elif m := _PAGES_FILE.match(p):
            rel = m.group(1)
            if rel.split("/")[-1].startswith("_"):
                continue
            path = "/" + re.sub(r"(?:^|/)index$", "", rel)
            if path.startswith("/api/") or path == "/api":
                api[path] = ["?"]
            else:
                pages.add(path if path != "/" else "/")
    return {"framework": "next" if pages or api else None, "pages": sorted(pages)[:200],
            "api": [{"path": k, "methods": v} for k, v in sorted(api.items())][:200]}


def _f(op: str, result: Any, authority: str = "distributed_artifact", confidence: str = "high",
       limitations: str = "") -> dict[str, Any]:
    return {"operation": op, "result": result, "authority": authority, "confidence": confidence,
            "limitations": limitations}


def walk(root: Path) -> tuple[list[str], dict[str, int], bool]:
    _SIZE_CACHE.clear()   # cada análisis empieza sin tamaños de otro
    files: list[str] = []
    skipped: Counter = Counter()
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        keep = []
        for d in dirnames:
            if d in SKIP_DIRS:
                skipped[d] += 1
            elif not _is_link(os.path.join(dirpath, d)):
                keep.append(d)
        dirnames[:] = sorted(keep)
        rel = os.path.relpath(dirpath, root).replace("\\", "/")
        for f in sorted(filenames):
            if _is_link(os.path.join(dirpath, f)):
                skipped["(enlace simbólico)"] += 1   # README.md -> ~/.ssh/... no se lee nunca
                continue
            files.append(f if rel == "." else f"{rel}/{f}")
            if len(files) >= MAX_FILES:
                return files, dict(skipped), True
    return files, dict(skipped), truncated


def analyze_repo(source: str, *, workdir: str | Path = "samples/repos",
                 progress: Callable[[str], None] | None = None) -> tuple[str, list[dict[str, Any]]]:
    log = progress or (lambda _m: None)
    remote = None
    if is_git_url(source):
        log(f"clonando {redact_url(source)} (superficial, sin hooks)…")
        root = clone(source, workdir)
        remote = redact_url(source)
    else:
        root = Path(source)
        if not root.is_dir():
            raise FileNotFoundError(source)
    root = root.resolve()
    subject = "repo:" + (remote or str(root))
    files, skipped, truncated = walk(root)
    log(f"{len(files)} archivos")
    paths = set(files)
    findings: list[dict[str, Any]] = []

    # -- lenguajes -----------------------------------------------------------
    by_lang: dict[str, dict[str, int]] = {}
    line_budget = LINE_COUNT_BUDGET   # bytes leídos en total para contar líneas (repos enormes)
    for rel in files:
        lang = LANG.get(Path(rel).suffix.lower())
        if not lang:
            continue
        p = root / rel
        size = _size(p)
        if _SIZE_CACHE.get(str(p)) == -1:
            continue
        e = by_lang.setdefault(lang, {"files": 0, "bytes": 0, "lines": 0})
        e["files"] += 1
        e["bytes"] += size
        if size <= MAX_TEXT and line_budget >= size:
            line_budget -= size
            try:
                n, last, binary, first = 0, b"", False, True
                with open(p, "rb") as fh:   # por bloques: no se guarda el archivo entero
                    while chunk := fh.read(1 << 16):
                        if first and b"\x00" in chunk[:8192]:
                            binary = True
                            break
                        first = False
                        n += chunk.count(b"\n")
                        last = chunk[-1:]
                if not binary:
                    e["lines"] += n + (1 if last and last != b"\n" else 0)
            except OSError:
                pass
        elif size <= MAX_TEXT:
            e["lines"] += size // 40   # presupuesto agotado: estimación (~40 bytes por línea)
    code = {k: v for k, v in by_lang.items() if k in CODE_LANGS}
    total_code = sum(v["lines"] for v in code.values()) or 1
    langs = sorted(({"language": k, **v, "share": round(v["lines"] / total_code, 3)} for k, v in code.items()),
                   key=lambda x: -x["lines"])
    findings.append(_f("repo_languages", {
        "code": langs[:25], "other": {k: v for k, v in by_lang.items() if k not in CODE_LANGS},
        "files_total": len(files), "truncated": truncated, "skipped_dirs": skipped,
    }, limitations="Líneas físicas (incluye comentarios y vacías); carpetas generadas excluidas."))

    # -- manifiestos ---------------------------------------------------------
    deps: dict[str, set[str]] = {}
    manifests: dict[str, Any] = {}
    errors: list[str] = []

    def add(eco: str, names: set[str]) -> None:
        deps.setdefault(eco, set()).update(names)

    def depth(rel: str) -> int:
        return rel.count("/")

    sample_dir = re.compile(r"(?:^|/)(?:examples?|samples?|fixtures|__fixtures__|testdata|test-fixtures|demo)/", re.I)
    for rel in files:
        name = rel.rsplit("/", 1)[-1]
        if depth(rel) > 4 or sample_dir.search(rel):
            continue   # los manifiestos de ejemplos y fixtures no son la pila del proyecto (M37)
        p = root / rel
        try:
            if name == "package.json":
                n, info = parse_package_json(_read(p))
                add("npm", n)
                manifests[rel] = info
            elif name == "pyproject.toml":
                n, info = parse_pyproject(_read(p))
                add("pypi", n)
                manifests[rel] = info
            elif re.match(r"requirements[\w.-]*\.txt$", name):
                n = parse_requirements(_read(p))
                add("pypi", n)
                manifests[rel] = {"dependencies": sorted(n)[:120]}
            elif name == "Pipfile":
                d = tomllib.loads(_read(p))
                n = {k.lower() for k in list(d.get("packages", {})) + list(d.get("dev-packages", {}))}
                add("pypi", n)
                manifests[rel] = {"dependencies": sorted(n)}
            elif name == "Cargo.toml":
                n, info = parse_cargo(_read(p))
                add("cargo", n)
                manifests[rel] = info
            elif name == "go.mod":
                n, info = parse_go_mod(_read(p))
                add("go", n)
                manifests[rel] = info
            elif name == "pom.xml":
                n, info = parse_pom(_read(p))
                add("maven", n)
                manifests[rel] = info
            elif name in ("build.gradle", "build.gradle.kts"):
                n = parse_gradle(_read(p))
                add("maven", n)
                manifests[rel] = {"dependencies": sorted(n)[:120]}
            elif name == "composer.json":
                d = json.loads(_read(p) or "{}")
                n = {k.lower() for k in list(d.get("require", {})) + list(d.get("require-dev", {}))}
                add("composer", n)
                manifests[rel] = {"name": d.get("name"), "dependencies": sorted(n)[:120]}
            elif name == "Gemfile":
                n = {m.lower() for m in re.findall(r"""^[ \t]*gem\s+['"]([\w-]+)""", _read(p), re.M)}
                add("gem", n)
                manifests[rel] = {"dependencies": sorted(n)[:120]}
            elif name.endswith((".csproj", ".fsproj", ".vbproj")) or name == "Directory.Packages.props":
                n, info = parse_csproj(_read(p))
                add("nuget", n)
                manifests[rel] = info
            elif name == "pubspec.yaml":
                n = parse_pubspec(_read(p))
                add("pub", n)
                manifests[rel] = {"dependencies": sorted(n)[:120]}
        except Exception as exc:  # noqa: BLE001 — un manifiesto hostil (tipos raros, JSON muy anidado…) no tumba el análisis
            errors.append(f"{rel}: {type(exc).__name__}: {exc}"[:200])
    lock = sorted({pm for f, pm in LOCKFILES.items() if f in paths})
    findings.append(_f("repo_manifests", {
        "manifests": dict(list(manifests.items())[:40]), "package_managers": lock,
        "dependency_counts": {k: {"runtime": sum(1 for d in v if not d.startswith("dev:")),
                                  "dev": sum(1 for d in v if d.startswith("dev:"))} for k, v in deps.items()}, "errors": errors[:20],
    }, confidence="high" if not errors else "medium",
        limitations="Se leen como texto; dependencias dinámicas o generadas no aparecen."))

    techs = stack.detect_repo(deps, paths)
    findings.append(_f("repo_stack", {"technologies": techs}, "analyst_inference", "medium",
                       "Deducido de dependencias y archivos; no implica que todo se use en producción."))

    # -- estructura ----------------------------------------------------------
    top: Counter = Counter()
    second: Counter = Counter()
    for rel in files:
        parts = rel.split("/")
        top[parts[0] + ("/" if len(parts) > 1 else "")] += 1
        if len(parts) > 2:
            second[f"{parts[0]}/{parts[1]}/"] += 1
    tooling = sorted({label for f, label in TOOLING.items() if f in paths or any(p.endswith("/" + f) for p in paths if p.count("/") <= 2)})
    entry_candidates = [p for p in files if re.search(
        r"^(?:src/|source/|lib/)?(?:main|index|app|server|cli|__main__)\.(?:py|ts|tsx|js|mjs|go|rs|java|kt|cs|dart|swift)$|"
        r"^cmd/[^/]+/main\.go$|^manage\.py$|^src/main/java/.*/[A-Z]\w*Application\.java$|^lib/main\.dart$", p)][:20]
    findings.append(_f("repo_structure", {
        "top_level": [{"path": k, "files": v, "role": DIR_ROLES.get(k.rstrip("/"))} for k, v in sorted(top.items())][:80],
        "second_level": [k for k, _ in second.most_common(60)],
        "entry_points": entry_candidates,
        "tooling": tooling,
        "monorepo": any(k.rstrip("/") in ("packages", "apps", "crates") for k in top) or bool(
            any(m.get("workspaces") for m in manifests.values() if isinstance(m, dict))),
    }))

    routes = _routes(files, root)
    if routes["pages"] or routes["api"]:
        findings.append(_f("repo_routes", routes, "distributed_artifact", "high",
                           "Rutas deducidas por la convención de archivos de Next.js (app/ y pages/); los métodos "
                           "HTTP son las funciones exportadas. No se ejecuta nada ni se resuelven rutas dinámicas."))

    # -- pruebas, CI, contenedores ---------------------------------------------
    test_files = [p for p in files if re.search(
        r"(?:^|/)(?:tests?|__tests__|spec|e2e)/|(?:^|/)test_[^/]+\.py$|_test\.(?:go|py)$|\.(?:test|spec)\.[jt]sx?$|Tests?\.(?:java|kt|cs|swift)$", p)]
    workflows = []
    for p in files:
        if re.match(r"^\.github/workflows/[^/]+\.ya?ml$", p):
            text = _read(root / p, 256 * 1024)
            name = re.search(r"^name:\s*(.+)$", text, re.M)
            uses = sorted(set(re.findall(r"uses:\s*([\w.-]+/[\w.-]+)@", text)))[:15]
            on = re.findall(r"^\s{2}(push|pull_request|schedule|workflow_dispatch|release|tag)s?:", text, re.M)
            workflows.append({"file": p, "name": name.group(1).strip()[:80] if name else None,
                              "triggers": sorted(set(on)), "actions": uses})
    ci_other = [f for f in (".gitlab-ci.yml", "azure-pipelines.yml", "Jenkinsfile", ".circleci/config.yml",
                            ".travis.yml", "bitbucket-pipelines.yml") if f in paths]
    dockerfiles = [p for p in files if re.search(r"(?:^|/)Dockerfile(?:\.[\w-]+)?$|\.dockerfile$", p)][:10]
    images = []
    for d in dockerfiles:
        images += re.findall(r"^[ \t]*FROM\s+(?:--\S+\s+)?(\S+)", _read(root / d, 256 * 1024), re.M | re.I)
    compose = next((root / p for p in files if p in ("docker-compose.yml", "docker-compose.yaml", "compose.yaml", "compose.yml")), None)
    services = re.findall(r"^  ([\w.-]+):\s*$", _read(compose, 256 * 1024), re.M) if compose else []
    makefile = root / "Makefile"
    targets = re.findall(r"^([A-Za-z][\w.-]*):(?!=)", _read(makefile, 256 * 1024), re.M)[:30] if "Makefile" in paths else []
    findings.append(_f("repo_quality", {
        "tests": {"files": len(test_files), "sample": test_files[:15],
                  "ratio_to_code": round(len(test_files) / max(1, sum(v["files"] for v in code.values())), 3)},
        "ci": {"github_actions": workflows[:20], "other": ci_other},
        "containers": {"dockerfiles": dockerfiles, "base_images": sorted(set(images))[:15],
                       "compose_services": services[:20]},
        "make_targets": targets,
    }))

    # -- documentación e higiene ----------------------------------------------
    readme = next((p for p in files if re.match(r"^readme(?:\.\w+)?$", p, re.I)), None)
    rd = _read(root / readme, 512 * 1024) if readme else ""
    lic_file = next((p for p in files if re.match(r"^(?:licen[cs]e|copying)(?:\.\w+)?$", p, re.I)), None)
    lic_text = _read(root / lic_file, 256 * 1024) if lic_file else ""
    env_examples = [p for p in files if re.search(r"(?:^|/)\.env\.(?:example|sample|template|dist)$", p)]
    env_vars = sorted(set(re.findall(r"^([A-Z][A-Z0-9_]{1,60})=", "".join(_read(root / e, 64 * 1024) for e in env_examples[:5]), re.M)))
    findings.append(_f("repo_docs", {
        "readme": readme, "readme_sections": [h.strip()[:80] for h in re.findall(r"^#{1,3}\s+(.+)$", rd, re.M)][:30],
        "readme_lines": rd.count("\n"),
        "license": _license(lic_text) if lic_file else None, "license_file": lic_file,
        "community": [f for f in ("CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md", "CHANGELOG.md",
                                  ".github/ISSUE_TEMPLATE", ".github/PULL_REQUEST_TEMPLATE.md")
                      if f in paths or any(p.startswith(f + "/") for p in paths)],
        "docs_dir": any(p.startswith(("docs/", "doc/")) for p in files),
        "env_variables": env_vars[:60],
    }, limitations="Nombres de variables de entorno, nunca valores."))
    sensitive = [p for p in files if SENSITIVE.search(p)]
    findings.append(_f("repo_hygiene", {
        "possibly_sensitive_files": sensitive[:30],
        "committed_generated_dirs": [d for d in skipped if d in ("node_modules", "dist", "build", "venv", ".venv")],
        "large_files": sorted(((p, n) for p in files if (n := _size(root / p)) > 5_000_000),
                              key=lambda x: -x[1])[:15],
    }, "analyst_inference", "medium",
        "Solo nombres de archivo: su contenido no se lee ni se guarda."))

    git_info = _git_info(root, remote)
    if git_info:
        findings.append(_f("repo_git", git_info, "controlled_repro", "high",
                           "Clon superficial: el historial puede estar truncado." if remote else ""))

    findings.append(_f("repo_blueprint", _blueprint(techs, manifests, lock, top, tooling, workflows, dockerfiles,
                                                    test_files, langs), "analyst_inference", "medium",
                       "Guía para empezar algo parecido; revisa la licencia antes de reutilizar código."))
    return subject, findings


def _license(text: str) -> str:
    t = text[:4000].lower()
    for key, name in (("mit license", "MIT"), ("permission is hereby granted, free of charge", "MIT"),
                      ("apache license", "Apache-2.0"), ("gnu affero", "AGPL-3.0"),
                      ("gnu lesser general public", "LGPL"), ("gnu general public license", "GPL"),
                      ("mozilla public license", "MPL-2.0"), ("bsd 3-clause", "BSD-3-Clause"),
                      ("redistribution and use in source and binary forms", "BSD"), ("unlicense", "Unlicense"),
                      ("isc license", "ISC"), ("creative commons", "Creative Commons")):
        if key in t:
            return name
    return "desconocida"


def _git_info(root: Path, remote: str | None) -> dict[str, Any] | None:
    git = shutil.which("git")
    if not git or not (root / ".git").exists():
        return None

    def run(*args: str) -> str:
        try:
            # Repos locales no confiables: su .git/config no puede ejecutar nada (gpg.program con
            # log.showSignature, fsmonitor, pager, sshCommand…) ni pedir credenciales: ver safe_git().
            p = safe_git(git, list(args), cwd=root)
            return p.stdout.strip() if p.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""
    last = run("log", "-1", "--no-show-signature", "--format=%H%x1f%cI%x1f%s")
    parts = last.split("\x1f") if last else []
    return {
        "remote": remote or redact_url(run("remote", "get-url", "origin")) or None,
        "branch": run("rev-parse", "--abbrev-ref", "HEAD") or None,
        "commits_visible": int(run("rev-list", "--count", "HEAD") or 0),
        "last_commit": {"sha": parts[0], "date": parts[1], "subject": parts[2][:120]} if len(parts) == 3 else None,
        "tags": run("tag", "--list").splitlines()[:20],
    }


def _key_dependencies(root_pkg: Any, manifests: dict[str, Any]) -> list[str]:
    """Las del package.json raíz o, en un monorepo (raíz sin dependencias), las más repetidas entre sus
    paquetes (B23)."""
    own = (root_pkg.get("dependencies") or []) if isinstance(root_pkg, dict) else []
    if own:
        return own[:20]
    counts: Counter = Counter()
    for rel, info in manifests.items():
        if rel != "package.json" and isinstance(info, dict):
            counts.update(d for d in (info.get("dependencies") or []) if isinstance(d, str))
    return [d for d, _ in counts.most_common(20)]


def _blueprint(techs, manifests, lock, top, tooling, workflows, dockerfiles, test_files, langs) -> dict[str, Any]:
    names = stack.app_stack(techs)
    scaffold = stack.scaffold_for(names)
    root_pkg = manifests.get("package.json", {})
    scripts = root_pkg.get("scripts", {}) if isinstance(root_pkg, dict) else {}
    pm = next((x for x in lock if x in ("pnpm", "yarn", "bun", "npm")), "npm" if "package.json" in manifests else None)
    run_steps = []
    if pm:
        run_steps.append(f"{pm} install")
        for k in ("dev", "start", "build", "test", "lint"):
            if k in scripts:
                run_steps.append(f"{pm} run {k}    # {scripts[k][:80]}")
    if "pyproject.toml" in manifests or any(k.startswith("requirements") for k in manifests):
        run_steps.append("python -m venv .venv && pip install -e .  # o pip install -r requirements.txt")
        if any("pytest" in str(m) for m in manifests.values()):
            run_steps.append("pytest")
    if "Cargo.toml" in manifests:
        run_steps += ["cargo build", "cargo test"]
    if "go.mod" in manifests:
        run_steps += ["go build ./...", "go test ./..."]
    if any(k.endswith(".csproj") for k in manifests):
        run_steps += ["dotnet build", "dotnet test"]
    layout = [f"{k}  → {DIR_ROLES[k.rstrip('/')]}" for k in sorted(top) if k.rstrip("/") in DIR_ROLES]
    conventions = []
    if "TypeScript" in tooling:
        conventions.append("TypeScript con tsconfig.json")
    for lint in ("ESLint", "Biome", "Prettier", "Ruff", "Flake8", "rustfmt", "golangci-lint", "pre-commit"):
        if lint in tooling:
            conventions.append(f"{lint} para estilo/lint")
    if test_files:
        conventions.append(f"{len(test_files)} archivos de pruebas")
    if workflows:
        conventions.append(f"CI con GitHub Actions ({len(workflows)} workflows)")
    if dockerfiles:
        conventions.append("Contenedor Docker")
    return {
        "suggested_scaffold": scaffold,
        "primary_language": langs[0]["language"] if langs else None,
        "stack": names,
        "package_manager": pm or (lock[0] if lock else None),
        "how_to_run": run_steps,
        "layout": layout,
        "conventions": conventions,
        "key_dependencies": _key_dependencies(root_pkg, manifests),
    }
