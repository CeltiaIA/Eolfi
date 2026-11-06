"""Generadores de proyectos nuevos a partir de una especificación.

Destinos: static (HTML/CSS/JS sin dependencias), react (Vite + TS), vue
(Vite + TS), fastapi (Python) y express (Node). Todo el código se escribe
aquí desde cero; las dependencias se declaran como "latest" y la
verificación las instala y fija a la versión real instalada.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from eolfi.generador import templates as tpl

# Cabeceras de seguridad de TODOS los destinos web (PLAN_MEJORAS A11). frame-ancestors, nosniff y
# Referrer-Policy solo valen como cabeceras HTTP; en las páginas estáticas va además una <meta> CSP.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; "
       "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
       "frame-ancestors 'none'")
CSP_META = CSP.replace("; frame-ancestors 'none'", "")   # frame-ancestors no se admite en <meta>
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
# Para vite.config.ts: la CSP se inyecta SOLO en el build (en desarrollo, el refresco en caliente usa
# scripts en línea y websockets) y «vite preview» sirve las cabeceras.
VITE_SECURITY = (
    "// Cabeceras de seguridad (generado por Eolfi): CSP en el HTML del build y cabeceras en «vite preview».\n"
    f"const SECURITY_HEADERS = {json.dumps(SECURITY_HEADERS, indent=2)};\n"
    "const cspMeta = () => ({\n"
    '  name: "csp-meta",\n'
    '  apply: "build" as const,\n'
    "  transformIndexHtml: (html: string) =>\n"
    f'    html.replace("<head>", `<head>\\n    <meta http-equiv="Content-Security-Policy" content="{CSP_META}" />`),\n'
    "});\n\n"
)
from eolfi.generador.templates import SECTIONS, base_css, content_for, page_title, tokens_css

Writer = Callable[[str, str], None]


def _writer(out: Path, written: list[str]) -> Writer:
    def w(rel: str, text: str) -> None:
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")
        written.append(rel)

    def write_bytes(rel: str, data: bytes) -> None:   # iconos y otros binarios generados
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        written.append(rel)

    w.write_bytes = write_bytes  # type: ignore[attr-defined]
    return w


def _check_spec(spec: dict[str, Any]) -> None:
    """Defensa en profundidad: build_spec ya sanea título, recursos y rutas; un spec que no cumpla esas reglas
    (editado a mano o de otra versión) no se interpola en código."""
    from eolfi.generador.spec import safe_resource

    if not re.fullmatch(r"[\w .,:;!?()+-]*", str(spec.get("title", ""))):
        raise ValueError("spec: título con caracteres no permitidos")
    for r in (spec.get("api") or {}).get("resources", []):
        if not (isinstance(r, str) and re.fullmatch(r"[a-z][a-z0-9_-]{1,30}", r) and safe_resource(r)):
            raise ValueError(f"spec: recurso no válido: {r!r}")


def generate(spec: dict[str, Any], out_dir: str | Path, *, force: bool = False) -> list[str]:
    _check_spec(spec)
    out = Path(out_dir)
    if out.exists() and any(out.iterdir()) and not force:
        raise FileExistsError(f"{out} no está vacía (usa --force para escribir encima)")
    out.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    w = _writer(out, written)
    from eolfi.generador.generators_backend import gen_express, gen_fastapi
    from eolfi.generador.generators_cli import gen_cli
    from eolfi.generador.generators_desktop import gen_desktop
    from eolfi.generador.generators_dotnet import gen_dotnet
    from eolfi.generador.generators_tauri import gen_tauri
    from eolfi.generador.generators_mobile import gen_expo
    from eolfi.generador.generators_more import gen_django, gen_next, gen_svelte

    {"static": gen_static, "react": gen_react, "vue": gen_vue, "svelte": gen_svelte, "next": gen_next,
     "fastapi": gen_fastapi, "express": gen_express, "django": gen_django, "expo": gen_expo,
     "desktop": gen_desktop, "tauri": gen_tauri, "cli": gen_cli,
     "dotnet": gen_dotnet}[spec["target"]](spec, w)
    w("eolfi.spec.json", json.dumps(spec, indent=2, ensure_ascii=False))
    # .gitignore base + las líneas propias de cada objetivo (.gitignore.extra: build/, bin/, obj/…), sin repetir.
    # Antes .gitignore.extra se borraba sin fusionarse: p. ej. los proyectos .NET quedaban sin ignorar bin/ y obj/.
    ignore = ["node_modules/", "dist/", ".venv/", "__pycache__/", "*.pyc", ".pytest_cache/", ".env", "data/"]
    extra = out / ".gitignore.extra"
    if ".gitignore.extra" in written and extra.exists():
        for line in extra.read_text(encoding="utf-8").splitlines():
            if line.strip() and line.strip() not in ignore:
                ignore.append(line.strip())
        extra.unlink()
        written.remove(".gitignore.extra")
    w(".gitignore", "\n".join(ignore) + "\n")
    _ci(spec, w)
    if spec["conventions"].get("docker") and spec["target"] not in ("expo", "desktop", "tauri", "cli", "dotnet"):
        _docker(spec, w)
    w("README.md", _readme(spec))
    return written


def _routes(spec: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(slug, path, título) de cada página."""
    out = []
    for slug in spec["pages"]:
        out.append((slug, "/" if slug == "home" else f"/{slug}", "Inicio" if slug == "home" else page_title(slug)))
    return out


def _page_sections(spec: dict[str, Any], slug: str) -> list[str]:
    if slug == "home":
        return spec["sections"]
    extra = [s for s in ("Features", "CardGrid", "Faq") if s in spec["sections"]][:1] or ["Features"]
    return extra + (["CallToAction"] if "CallToAction" in spec["sections"] else [])


# ---------------------------------------------------------------------------
# Estático (también lo usan los backends como frontend)
# ---------------------------------------------------------------------------
def _static_page(spec: dict[str, Any], slug: str, title: str, routes, content, css_prefix: str,
                 resources: list[str]) -> str:
    nav = "\n".join(
        f'        <a href="{css_prefix}{"index" if s == "home" else s}.html"'
        f'{" aria-current=\"page\"" if s == slug else ""}>{tpl.html.escape(t)}</a>'
        for s, _p, t in routes)
    secs = []
    if slug != "home":
        secs.append(f'    <section class="page-header"><div class="container"><h1>{tpl.html.escape(title)}</h1>'
                    f'<p class="lead">Página de ejemplo: cambia este texto.</p></div></section>')
    for s in _page_sections(spec, slug):
        secs.append(tpl.render_html(SECTIONS[s], content[s], indent=2))
    if resources and slug == "home":
        secs.append(_api_demo_html(resources, bool((spec.get("options") or {}).get("auth"))))
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Security-Policy" content="{CSP_META}">
  <meta name="referrer" content="strict-origin-when-cross-origin">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{tpl.html.escape(title if slug != "home" else spec["title"])}</title>
  <meta name="description" content="{tpl.html.escape(spec["title"])}: proyecto generado con Eolfi.">
  <link rel="stylesheet" href="{css_prefix}css/tokens.css">
  <link rel="stylesheet" href="{css_prefix}css/base.css">
  <script src="{css_prefix}js/main.js" defer></script>
</head>
<body>
  <a class="skip-link" href="#contenido">Saltar al contenido</a>
  <header class="site-header">
    <div class="container">
      <a class="brand" href="{css_prefix}index.html">{tpl.html.escape(spec["title"])}</a>
      <nav class="site-nav" aria-label="Principal">
{nav}
        <button class="theme-toggle" type="button" data-theme-toggle aria-label="Tema oscuro" aria-pressed="false">◐</button>
      </nav>
    </div>
  </header>
  <main><span id="contenido" tabindex="-1"></span>
{chr(10).join(secs)}
  </main>
  <footer class="site-footer">
    <div class="container">© {tpl.html.escape(spec["title"])} · Hecho con código nuevo.</div>
  </footer>
</body>
</html>"""


def _api_demo_html(resources: list[str], auth: bool = False) -> str:
    blocks = []
    for r in resources:
        blocks.append(f"""      <div class="card">
        <h3>{tpl.html.escape(r)}</h3>
        <ul class="resource-list" data-resource="{r}"><li class="muted">Cargando…</li></ul>
        <form class="contact-form" data-resource-form="{r}">
          <label>Nombre <input name="name" required></label>
          <button class="btn btn-primary" type="submit">Añadir</button>
        </form>
      </div>""")
    login = """
        <form class="contact-form narrow" data-login-form>
          <p class="form-status" data-login-status>Inicia sesión para añadir datos.</p>
          <label>Correo <input name="email" type="email" required autocomplete="email"></label>
          <label>Contraseña <input name="password" type="password" required minlength="8" autocomplete="current-password"></label>
          <span class="hero-actions">
            <button class="btn btn-primary" type="submit" data-mode="login">Entrar</button>
            <button class="btn btn-ghost" type="submit" data-mode="register">Crear cuenta</button>
          </span>
        </form>""" if auth else ""
    return f"""    <section class="api-demo" id="datos">
      <div class="container">
        <h2>Datos en vivo</h2>
        <p class="section-lead">Estas listas vienen de la API del propio proyecto.</p>{login}
        <div class="grid grid-3">
{chr(10).join(blocks)}
        </div>
      </div>
    </section>"""


STATIC_JS = """// Comportamiento del sitio: tema claro/oscuro, formulario y datos de la API.
(function () {
  "use strict";
  var root = document.documentElement;
  var saved = null;
  try { saved = localStorage.getItem("theme"); } catch (e) { /* almacenamiento bloqueado */ }
  if (saved) root.setAttribute("data-theme", saved);

  function authHeaders() {
    var h = { "Content-Type": "application/json" };
    var t = null;
    try { t = sessionStorage.getItem("token"); } catch (e) { /* sin almacenamiento */ }
    if (t) h.Authorization = "Bearer " + t;
    return h;
  }
  function loginStatus(text) {
    var el = document.querySelector("[data-login-status]");
    if (el) el.textContent = text;
  }

  document.addEventListener("DOMContentLoaded", function () {
    var toggle = document.querySelector("[data-theme-toggle]");
    if (toggle) toggle.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      toggle.setAttribute("aria-pressed", String(next === "dark"));
      try { localStorage.setItem("theme", next); } catch (e) { /* sin persistencia */ }
    });
    if (toggle) toggle.setAttribute("aria-pressed", String(root.getAttribute("data-theme") === "dark"));

    document.querySelectorAll("form[data-contact]").forEach(function (form) {
      form.addEventListener("submit", function (ev) {
        ev.preventDefault();
        var status = form.querySelector(".form-status") || document.createElement("p");
        status.className = "form-status";
        status.setAttribute("role", "status");
        status.textContent = "Formulario de ejemplo: el mensaje aún no se envía a ningún sitio (conéctalo a tu servidor).";
        form.appendChild(status);
        form.reset();
      });
    });

    document.querySelectorAll("[data-resource]").forEach(function (list) {
      var name = list.getAttribute("data-resource");
      function load() {
        fetch("/api/" + name).then(function (r) { return r.json(); }).then(function (items) {
          list.textContent = "";
          if (!items.length) { list.innerHTML = '<li class="muted">Vacío</li>'; return; }
          items.forEach(function (it) {
            var li = document.createElement("li");
            li.textContent = it.name;      // textContent: nunca HTML de la API
            list.appendChild(li);
          });
        }).catch(function () { list.innerHTML = '<li class="muted">API no disponible</li>'; });
      }
      load();
      var form = document.querySelector('[data-resource-form="' + name + '"]');
      if (form) form.addEventListener("submit", function (ev) {
        ev.preventDefault();
        var data = { name: form.elements.name.value };
        fetch("/api/" + name, { method: "POST", headers: authHeaders(),
          body: JSON.stringify(data) }).then(function (r) {
            if (r.status === 401) { loginStatus("Inicia sesión para añadir datos."); return; }
            form.reset(); load();
          });
      });
    });

    // Inicio de sesión (solo si el proyecto se generó con --auth). El token vive en
    // sessionStorage: se borra al cerrar la pestaña.
    var loginForm = document.querySelector("[data-login-form]");
    if (loginForm) {
      if (sessionStorage.getItem("token")) loginStatus("Sesión iniciada.");
      loginForm.addEventListener("submit", function (ev) {
        ev.preventDefault();
        var mode = (ev.submitter && ev.submitter.getAttribute("data-mode")) || "login";
        var body = JSON.stringify({ email: loginForm.elements.email.value, password: loginForm.elements.password.value });
        var post = function (path) { return fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: body }); };
        var start = mode === "register" ? post("/api/auth/register") : Promise.resolve({ ok: true });
        start.then(function (r) {
          if (!r.ok && r.status !== 409) throw new Error("No se pudo crear la cuenta");
          return post("/api/auth/login");
        }).then(function (r) {
          if (!r.ok) throw new Error("Correo o contraseña incorrectos");
          return r.json();
        }).then(function (d) {
          sessionStorage.setItem("token", d.token);
          loginForm.elements.password.value = "";
          loginStatus("Sesión iniciada.");
        }).catch(function (e) { loginStatus(e.message); });
      });
    }
  });
})();
"""

SERVE_MJS = """// Servidor estático mínimo (sin dependencias): node scripts/serve.mjs
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize, resolve, sep } from "node:path";

const root = resolve(process.argv[2] ?? ".");
const security = __SECURITY__;
const port = Number(process.env.PORT ?? 5173);
const types = { ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript",
  ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".json": "application/json" };

createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", "http://localhost");
  let path = normalize(decodeURIComponent(url.pathname));
  if (path.endsWith("/") || path.endsWith("\\\\")) path += "index.html";
  const file = join(root, path);
  if (file !== root && !file.startsWith(root + sep)) { res.writeHead(403).end("Prohibido"); return; }
  try {
    const body = await readFile(file);
    res.writeHead(200, { ...security, "Content-Type": types[extname(file)] ?? "application/octet-stream" }).end(body);
  } catch {
    res.writeHead(404, { ...security, "Content-Type": "text/plain; charset=utf-8" }).end("No encontrado");
  }
}).listen(port, () => console.log(`Sirviendo ${root} en http://localhost:${port}`));
"""


def _write_static_site(spec: dict[str, Any], w: Writer, base: str, resources: list[str]) -> None:
    content = content_for(spec)
    routes = _routes(spec)
    for slug, _path, title in routes:
        name = "index.html" if slug == "home" else f"{slug}.html"
        w(f"{base}{name}", _static_page(spec, slug, title, routes, content, "", resources))
    w(f"{base}css/tokens.css", tokens_css(spec))
    w(f"{base}css/base.css", base_css(spec))
    w(f"{base}js/main.js", STATIC_JS)


def gen_static(spec: dict[str, Any], w: Writer) -> None:
    _write_static_site(spec, w, "", [])
    w("scripts/serve.mjs", SERVE_MJS.replace("__SECURITY__", json.dumps(SECURITY_HEADERS)))
    w("package.json", json.dumps({
        "name": spec["name"], "version": "0.1.0", "private": True, "type": "module",
        "scripts": {"start": "node scripts/serve.mjs", "test": "node --test"},
    }, indent=2))
    pages = [("index.html" if s == "home" else f"{s}.html") for s, _p, _t in _routes(spec)]
    w("tests/site.test.mjs", f"""import {{ test }} from "node:test";
import assert from "node:assert/strict";
import {{ readFileSync, existsSync }} from "node:fs";

const pages = {json.dumps(pages)};

for (const page of pages) {{
  test(`${{page}} es HTML accesible y enlaza recursos existentes`, () => {{
    const html = readFileSync(page, "utf8");
    assert.match(html, /<html lang="es">/);
    assert.match(html, /<main>/);
    assert.match(html, /name="viewport"/);
    for (const [, ref] of html.matchAll(/(?:href|src)="([^"#:]+\\.(?:html|css|js))"/g)) {{
      assert.ok(existsSync(ref), `${{page}} enlaza ${{ref}}, que no existe`);
    }}
    assert.equal((html.match(/<h1[ >]/g) ?? []).length, 1, "debe haber un único h1");
    assert.match(html, /http-equiv="Content-Security-Policy" content="default-src 'self'/, "falta la CSP");
  }});
}}
""")


# ---------------------------------------------------------------------------
# React (Vite + TypeScript), sin librerías de enrutado
# ---------------------------------------------------------------------------
def gen_react(spec: dict[str, Any], w: Writer) -> None:
    routes = _routes(spec)
    resources = spec["api"]["resources"]
    deps = {"react": "latest", "react-dom": "latest"}
    dev = {"vite": "latest", "@vitejs/plugin-react": "latest", "typescript": "latest",
           "@types/react": "latest", "@types/react-dom": "latest", "vitest": "latest"}
    w("package.json", json.dumps({
        "name": spec["name"], "version": "0.1.0", "private": True, "type": "module",
        "scripts": {"dev": "vite", "build": "tsc --noEmit && vite build", "preview": "vite preview",
                    "test": "vitest run"},
        "dependencies": deps, "devDependencies": dev,
    }, indent=2))
    w("index.html", _vite_index(spec, "/src/main.tsx"))
    w("vite.config.ts", """import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

""" + VITE_SECURITY + """export default defineConfig({
  plugins: [react(), cspMeta()],
  server: { proxy: { "/api": "http://localhost:8000" } },
  preview: { headers: SECURITY_HEADERS },
});
""")
    w("tsconfig.json", json.dumps({"compilerOptions": {
        "target": "ES2022", "lib": ["ES2022", "DOM", "DOM.Iterable"], "module": "ESNext",
        "moduleResolution": "bundler", "jsx": "react-jsx", "strict": True, "skipLibCheck": True,
        "noEmit": True, "isolatedModules": True, "types": ["vite/client"]}, "include": ["src"]}, indent=2))
    w("src/content.ts", "// Textos de ejemplo: cámbialos por los tuyos.\nexport const content = "
      + json.dumps(content_for(spec), indent=2, ensure_ascii=False) + " as const;\n")
    w("src/styles/tokens.css", tokens_css(spec))
    w("src/styles/base.css", base_css(spec))
    w("src/router.tsx", """// Enrutador mínimo: History API, sin dependencias.
import { createContext, useContext, useEffect, useState, type MouseEvent, type ReactNode } from "react";

const RouteContext = createContext<{ path: string; go: (to: string) => void }>({ path: "/", go: () => {} });

export function RouterProvider({ initialPath, children }: { initialPath?: string; children: ReactNode }) {
  const [path, setPath] = useState(initialPath ?? (typeof window === "undefined" ? "/" : window.location.pathname));
  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const go = (to: string) => {
    window.history.pushState({}, "", to);
    setPath(to);
    window.scrollTo(0, 0);
  };
  return <RouteContext.Provider value={{ path, go }}>{children}</RouteContext.Provider>;
}

export const useRoute = () => useContext(RouteContext);

export function Link({ to, children }: { to: string; children: ReactNode }) {
  const { path, go } = useRoute();
  const onClick = (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    go(to);
  };
  return (
    <a href={to} onClick={onClick} aria-current={path === to ? "page" : undefined}>
      {children}
    </a>
  );
}
""")
    for s in sorted(set(sum((_page_sections(spec, slug) for slug, _p, _t in routes), []))):
        node = SECTIONS[s]
        form = tpl.has_form(node)
        handler = ""
        imports = 'import { content } from "../content";\n'
        if form:
            imports = 'import { useState, type FormEvent } from "react";\n' + imports
            handler = """  const [sent, setSent] = useState(false);
  const onSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    e.currentTarget.reset();
    setSent(true);
  };
"""
        jsx = tpl.render_jsx(node, 2)
        if form:
            jsx = jsx.replace("</form>", "  {sent && <p className=\"form-status\" role=\"status\">{data.thanks}</p>}\n          </form>", 1)
        w(f"src/components/{s}.tsx", f"""{imports}
export default function {s}() {{
  const data = content.{s};
{handler}  return (
{jsx}
  );
}}
""")
    if resources:
        w("src/api.ts", _ts_api_client(resources))
        w("src/components/ApiDemo.tsx", """import { useEffect, useState, type FormEvent } from "react";
import { api, resources, type Item } from "../api";

function ResourceCard({ name }: { name: string }) {
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState(false);
  const load = () => api.list(name).then(setItems).catch(() => setError(true));
  useEffect(() => { void load(); }, []);
  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    await api.create(name, { name: String(new FormData(form).get("name")) });
    form.reset();
    void load();
  };
  return (
    <div className="card">
      <h3>{name}</h3>
      <ul className="resource-list">
        {error && <li className="muted">API no disponible (arranca el backend en :8000)</li>}
        {!error && items === null && <li className="muted">Cargando…</li>}
        {items?.map((it) => <li key={it.id}>{it.name}</li>)}
      </ul>
      <form className="contact-form" onSubmit={onSubmit}>
        <label>Nombre <input name="name" required /></label>
        <button className="btn btn-primary" type="submit">Añadir</button>
      </form>
    </div>
  );
}

export default function ApiDemo() {
  return (
    <section className="api-demo" id="datos">
      <div className="container">
        <h2>Datos en vivo</h2>
        <div className="grid grid-3">
          {resources.map((r) => <ResourceCard key={r} name={r} />)}
        </div>
      </div>
    </section>
  );
}
""")
    for slug, path, title in routes:
        comp = _pascal(slug) + "Page"
        secs = _page_sections(spec, slug)
        imports = "\n".join(f'import {s} from "../components/{s}";' for s in secs)
        body = "\n".join(f"      <{s} />" for s in secs)
        if slug == "home" and resources:
            imports += '\nimport ApiDemo from "../components/ApiDemo";'
            body += "\n      <ApiDemo />"
        header = "" if slug == "home" else f"""      <section className="page-header">
        <div className="container">
          <h1>{title}</h1>
          <p className="lead">Página de ejemplo: cambia este texto.</p>
        </div>
      </section>
"""
        w(f"src/pages/{comp}.tsx", f"""{imports}

export default function {comp}() {{
  return (
    <>
{header}{body}
    </>
  );
}}
""")
    page_imports = "\n".join(f'import {_pascal(s)}Page from "./pages/{_pascal(s)}Page";' for s, _p, _t in routes)
    table = ",\n".join(f'  {{ path: "{p}", title: "{t}", Page: {_pascal(s)}Page }}' for s, p, t in routes)
    w("src/App.tsx", f"""import {{ useEffect, useState }} from "react";
import {{ Link, RouterProvider, useRoute }} from "./router";
{page_imports}

export const routes = [
{table},
];

function NotFound() {{
  return (
    <section className="page-header">
      <div className="container">
        <h1>Página no encontrada</h1>
        <Link to="/">Volver al inicio</Link>
      </div>
    </section>
  );
}}

function ThemeToggle() {{
  const [theme, setTheme] = useState<string>(() =>
    typeof localStorage === "undefined" ? "light" : localStorage.getItem("theme") ?? "light");
  useEffect(() => {{
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }}, [theme]);
  return (
    <button className="theme-toggle" type="button" aria-label="Cambiar tema"
      onClick={{() => setTheme(theme === "dark" ? "light" : "dark")}}>◐</button>
  );
}}

function Shell() {{
  const {{ path }} = useRoute();
  const route = routes.find((r) => r.path === path);
  const Page = route?.Page ?? NotFound;
  useEffect(() => {{
    document.title = route && route.path !== "/" ? `${{route.title}} · {spec["title"]}` : "{spec["title"]}";
  }}, [route]);
  return (
    <>
      <header className="site-header">
        <div className="container">
          <Link to="/"><span className="brand">{spec["title"]}</span></Link>
          <nav className="site-nav" aria-label="Principal">
            {{routes.map((r) => <Link key={{r.path}} to={{r.path}}>{{r.title}}</Link>)}}
            <ThemeToggle />
          </nav>
        </div>
      </header>
      <main>
        <Page />
      </main>
      <footer className="site-footer">
        <div className="container">© {spec["title"]} · Hecho con código nuevo.</div>
      </footer>
    </>
  );
}}

export default function App({{ initialPath }}: {{ initialPath?: string }}) {{
  return (
    <RouterProvider initialPath={{initialPath}}>
      <Shell />
    </RouterProvider>
  );
}}
""")
    w("src/main.tsx", """import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/tokens.css";
import "./styles/base.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
""")
    w("src/App.test.tsx", f"""import {{ describe, expect, it }} from "vitest";
import {{ renderToString }} from "react-dom/server";
import App, {{ routes }} from "./App";

describe("App", () => {{
  it("renderiza la portada con un único h1", () => {{
    const html = renderToString(<App initialPath="/" />);
    expect(html).toContain({tpl.js_string(spec["title"])});
    expect(html.match(/<h1[ >]/g)?.length).toBe(1);
    expect(html).toContain("<main>");
  }});

  it.each(routes.map((r) => [r.path]))("la ruta %s renderiza", (path) => {{
    const html = renderToString(<App initialPath={{path}} />);
    expect(html).not.toContain("Página no encontrada");
  }});

  it("muestra 404 en rutas desconocidas", () => {{
    expect(renderToString(<App initialPath="/no-existe" />)).toContain("Página no encontrada");
  }});
}});
""")


def _ts_api_client(resources: list[str]) -> str:
    return f"""// Cliente de la API del proyecto (el backend escucha en :8000; Vite hace de proxy de /api).
export type Item = {{ id: number; name: string; description?: string }};
export const resources = {json.dumps(resources)} as const;

async function request<T>(url: string, init?: RequestInit): Promise<T> {{
  const res = await fetch(url, {{ headers: {{ "Content-Type": "application/json" }}, ...init }});
  if (!res.ok) throw new Error(`HTTP ${{res.status}}`);
  return (await res.json()) as T;
}}

export const api = {{
  list: (resource: string) => request<Item[]>(`/api/${{resource}}`),
  create: (resource: string, data: Omit<Item, "id">) =>
    request<Item>(`/api/${{resource}}`, {{ method: "POST", body: JSON.stringify(data) }}),
  remove: (resource: string, id: number) => request<void>(`/api/${{resource}}/${{id}}`, {{ method: "DELETE" }}),
}};
"""


def _vite_index(spec: dict[str, Any], entry: str) -> str:
    return f"""<!doctype html>
<html lang="es">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="description" content="{tpl.html.escape(spec["title"])}: proyecto generado con Eolfi." />
    <title>{tpl.html.escape(spec["title"])}</title>
  </head>
  <body>
    <div id="app"></div>
    <div id="root"></div>
    <script type="module" src="{entry}"></script>
  </body>
</html>"""


def _pascal(s: str) -> str:
    return "".join(p.capitalize() for p in s.replace("_", "-").split("-")) or "Page"


# ---------------------------------------------------------------------------
# Vue (Vite + TypeScript)
# ---------------------------------------------------------------------------
def gen_vue(spec: dict[str, Any], w: Writer) -> None:
    routes = _routes(spec)
    resources = spec["api"]["resources"]
    w("package.json", json.dumps({
        "name": spec["name"], "version": "0.1.0", "private": True, "type": "module",
        "scripts": {"dev": "vite", "build": "vue-tsc --noEmit && vite build", "preview": "vite preview",
                    "test": "vitest run"},
        "dependencies": {"vue": "latest"},
        "devDependencies": {"vite": "latest", "@vitejs/plugin-vue": "latest", "typescript": "latest",
                            "vue-tsc": "latest", "vitest": "latest"},
    }, indent=2))
    w("index.html", _vite_index(spec, "/src/main.ts").replace('    <div id="root"></div>\n', ""))
    w("vite.config.ts", """import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

""" + VITE_SECURITY + """export default defineConfig({
  plugins: [vue(), cspMeta()],
  server: { proxy: { "/api": "http://localhost:8000" } },
  preview: { headers: SECURITY_HEADERS },
});
""")
    w("tsconfig.json", json.dumps({"compilerOptions": {
        "target": "ES2022", "lib": ["ES2022", "DOM", "DOM.Iterable"], "module": "ESNext",
        "moduleResolution": "bundler", "strict": True, "skipLibCheck": True, "noEmit": True,
        "isolatedModules": True, "jsx": "preserve", "types": ["vite/client"]},
        "include": ["src/**/*.ts", "src/**/*.vue"]}, indent=2))
    w("src/env.d.ts", '/// <reference types="vite/client" />\n')
    w("src/content.ts", "// Textos de ejemplo: cámbialos por los tuyos.\nexport const content = "
      + json.dumps(content_for(spec), indent=2, ensure_ascii=False) + " as const;\n")
    w("src/styles/tokens.css", tokens_css(spec))
    w("src/styles/base.css", base_css(spec))
    w("src/router.ts", """// Enrutador mínimo: History API, sin dependencias.
import { inject, ref, type InjectionKey, type Ref } from "vue";

export type Router = { path: Ref<string>; go: (to: string) => void };
export const RouterKey: InjectionKey<Router> = Symbol("router");

export function createRouter(initialPath?: string): Router {
  const path = ref(initialPath ?? (typeof window === "undefined" ? "/" : window.location.pathname));
  if (typeof window !== "undefined") {
    window.addEventListener("popstate", () => { path.value = window.location.pathname; });
  }
  return {
    path,
    go(to: string) {
      window.history.pushState({}, "", to);
      path.value = to;
      window.scrollTo(0, 0);
    },
  };
}

export function useRouter(): Router {
  const r = inject(RouterKey);
  if (!r) throw new Error("Router no instalado");
  return r;
}
""")
    w("src/components/RouterLink.vue", """<script setup lang="ts">
import { useRouter } from "../router";

const props = defineProps<{ to: string }>();
const router = useRouter();

function onClick(e: MouseEvent) {
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
  e.preventDefault();
  router.go(props.to);
}
</script>

<template>
  <a :href="to" :aria-current="router.path.value === to ? 'page' : undefined" @click="onClick"><slot /></a>
</template>
""")
    for s in sorted(set(sum((_page_sections(spec, slug) for slug, _p, _t in routes), []))):
        node = SECTIONS[s]
        form = tpl.has_form(node)
        script = f'import {{ content }} from "../content";\n\nconst data = content.{s};\n'
        markup = tpl.render_vue(node, 1)
        if form:
            script = 'import { ref } from "vue";\n' + script + """const sent = ref(false);

function onSubmit(e: Event) {
  (e.target as HTMLFormElement).reset();
  sent.value = true;
}
"""
            markup = markup.replace("</form>", '  <p v-if="sent" class="form-status" role="status">{{ data.thanks }}</p>\n        </form>', 1)
        w(f"src/components/{s}.vue", f"""<script setup lang="ts">
{script}</script>

<template>
{markup}
</template>
""")
    if resources:
        w("src/api.ts", _ts_api_client(resources))
        w("src/components/ApiDemo.vue", """<script setup lang="ts">
import { onMounted, reactive } from "vue";
import { api, resources, type Item } from "../api";

const state = reactive<Record<string, { items: Item[] | null; error: boolean }>>(
  Object.fromEntries(resources.map((r) => [r, { items: null, error: false }])),
);

async function load(name: string) {
  try {
    state[name].items = await api.list(name);
  } catch {
    state[name].error = true;
  }
}

async function add(name: string, e: Event) {
  const form = e.target as HTMLFormElement;
  await api.create(name, { name: String(new FormData(form).get("name")) });
  form.reset();
  await load(name);
}

onMounted(() => resources.forEach((r) => void load(r)));
</script>

<template>
  <section class="api-demo" id="datos">
    <div class="container">
      <h2>Datos en vivo</h2>
      <div class="grid grid-3">
        <div v-for="r in resources" :key="r" class="card">
          <h3>{{ r }}</h3>
          <ul class="resource-list">
            <li v-if="state[r].error" class="muted">API no disponible (arranca el backend en :8000)</li>
            <li v-else-if="state[r].items === null" class="muted">Cargando…</li>
            <li v-for="it in state[r].items ?? []" :key="it.id">{{ it.name }}</li>
          </ul>
          <form class="contact-form" @submit.prevent="add(r, $event)">
            <label>Nombre <input name="name" required /></label>
            <button class="btn btn-primary" type="submit">Añadir</button>
          </form>
        </div>
      </div>
    </div>
  </section>
</template>
""")
    for slug, _path, title in routes:
        comp = _pascal(slug) + "Page"
        secs = _page_sections(spec, slug)
        imports = "\n".join(f'import {s} from "../components/{s}.vue";' for s in secs)
        body = "\n".join(f"  <{s} />" for s in secs)
        if slug == "home" and resources:
            imports += '\nimport ApiDemo from "../components/ApiDemo.vue";'
            body += "\n  <ApiDemo />"
        header = "" if slug == "home" else f"""  <section class="page-header">
    <div class="container">
      <h1>{title}</h1>
      <p class="lead">Página de ejemplo: cambia este texto.</p>
    </div>
  </section>
"""
        w(f"src/pages/{comp}.vue", f"""<script setup lang="ts">
{imports}
</script>

<template>
{header}{body}
</template>
""")
    page_imports = "\n".join(f'import {_pascal(s)}Page from "./pages/{_pascal(s)}Page.vue";' for s, _p, _t in routes)
    table = ",\n".join(f'  {{ path: "{p}", title: "{t}", page: {_pascal(s)}Page }}' for s, p, t in routes)
    w("src/routes.ts", f"""{page_imports}

export const routes = [
{table},
];
""")
    w("src/App.vue", f"""<script setup lang="ts">
import {{ computed, onMounted, ref, watchEffect }} from "vue";
import RouterLink from "./components/RouterLink.vue";
import {{ useRouter }} from "./router";
import {{ routes }} from "./routes";

const router = useRouter();
const route = computed(() => routes.find((r) => r.path === router.path.value));
const theme = ref("light");

onMounted(() => {{
  theme.value = localStorage.getItem("theme") ?? "light";
  watchEffect(() => {{
    document.documentElement.setAttribute("data-theme", theme.value);
    localStorage.setItem("theme", theme.value);
    document.title = route.value && route.value.path !== "/" ? `${{route.value.title}} · {spec["title"]}` : "{spec["title"]}";
  }});
}});
</script>

<template>
  <header class="site-header">
    <div class="container">
      <RouterLink to="/"><span class="brand">{spec["title"]}</span></RouterLink>
      <nav class="site-nav" aria-label="Principal">
        <RouterLink v-for="r in routes" :key="r.path" :to="r.path">{{{{ r.title }}}}</RouterLink>
        <button class="theme-toggle" type="button" aria-label="Cambiar tema"
          @click="theme = theme === 'dark' ? 'light' : 'dark'">◐</button>
      </nav>
    </div>
  </header>
  <main>
    <component :is="route.page" v-if="route" />
    <section v-else class="page-header">
      <div class="container">
        <h1>Página no encontrada</h1>
        <RouterLink to="/">Volver al inicio</RouterLink>
      </div>
    </section>
  </main>
  <footer class="site-footer">
    <div class="container">© {spec["title"]} · Hecho con código nuevo.</div>
  </footer>
</template>
""")
    w("src/main.ts", """import { createApp } from "vue";
import App from "./App.vue";
import { createRouter, RouterKey } from "./router";
import "./styles/tokens.css";
import "./styles/base.css";

createApp(App).provide(RouterKey, createRouter()).mount("#app");
""")
    w("src/App.test.ts", f"""import {{ describe, expect, it }} from "vitest";
import {{ createSSRApp }} from "vue";
import {{ renderToString }} from "vue/server-renderer";
import App from "./App.vue";
import {{ createRouter, RouterKey }} from "./router";
import {{ routes }} from "./routes";

const render = (path: string) => renderToString(createSSRApp(App).provide(RouterKey, createRouter(path)));

describe("App", () => {{
  it("renderiza la portada con un único h1", async () => {{
    const html = await render("/");
    expect(html).toContain({tpl.js_string(spec["title"])});
    expect(html.match(/<h1[ >]/g)?.length).toBe(1);
  }});

  it.each(routes.map((r) => [r.path]))("la ruta %s renderiza", async (path) => {{
    expect(await render(path)).not.toContain("Página no encontrada");
  }});

  it("muestra 404 en rutas desconocidas", async () => {{
    expect(await render("/no-existe")).toContain("Página no encontrada");
  }});
}});
""")


def _camel(s: str) -> str:
    parts = s.replace("_", "-").split("-")
    return parts[0] + "".join(p.capitalize() for p in parts[1:]) + "Router"


# ---------------------------------------------------------------------------
# Comunes
# ---------------------------------------------------------------------------
_RUN = {
    "static": (["node --test"], "npm start   # http://localhost:5173"),
    "react": (["npm ci || npm install", "npm run build", "npm test"], "npm install && npm run dev"),
    "vue": (["npm ci || npm install", "npm run build", "npm test"], "npm install && npm run dev"),
    "svelte": (["npm ci || npm install", "npm run build", "npm test"], "npm install && npm run dev"),
    "next": (["npm ci || npm install", "npm run build", "npm test"], "npm install && npm run dev   # http://localhost:3000"),
    "tauri": (["npm ci || npm install", "npm test", "npm run icons", "npm run build:debug"],
              "npm install && npm run icons && npm run dev   # npm run build crea los instaladores"),
    "dotnet": (["dotnet restore", "dotnet build -c Release", "dotnet test"],
               "dotnet run --project src/<Proyecto>   # dotnet publish -r win-x64|osx-arm64|linux-x64"),
    "cli": (["pip install -e .[test]", "pytest -q"],
            "python -m venv .venv && .venv/bin/pip install -e . && .venv/bin/<comando> --help   "
            "# Windows: .venv\\Scripts\\"),
    "desktop": (["npm ci || npm install", "npm test", "npm run smoke"],
                "npm install && npm start   # npm run dist crea el instalador de tu sistema"),
    "expo": (["npm ci || npm install", "npm run typecheck", "npm test", "npm run build:web"],
             "npm install && npm run setup && npx expo start   # escanea el QR con Expo Go"),
    "django": (["pip install -r requirements.txt", "python manage.py check", "python manage.py test"],
               "python -m venv .venv && .venv/bin/pip install -r requirements.txt && "
               ".venv/bin/python manage.py migrate && .venv/bin/python manage.py runserver"),
    "express": (["npm ci || npm install", "npm test"], "npm install && npm start   # http://localhost:8000"),
    "fastapi": (["pip install -r requirements.txt", "pytest -q"],
                "python -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/uvicorn app.main:app --reload"),
}


def _ci(spec: dict[str, Any], w: Writer) -> None:
    if spec["target"] == "tauri":
        w(".github/workflows/ci.yml", """name: CI
on:
  push:
  pull_request:
jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        os: [windows-latest, macos-latest, ubuntu-22.04]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - if: runner.os == 'Linux'
        run: |
          sudo apt-get update
          sudo apt-get install -y libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev patchelf
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - uses: dtolnay/rust-toolchain@stable
      - run: npm ci || npm install
      - run: npm test
      - run: npm run icons
      - run: npm run build
      - uses: actions/upload-artifact@v4
        with:
          name: instaladores-${{ matrix.os }}
          path: src-tauri/target/release/bundle/
""")
        return
    if spec["target"] == "dotnet":
        w(".github/workflows/ci.yml", """name: CI
on:
  push:
  pull_request:
jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: windows-latest
            rid: win-x64
          - os: macos-latest
            rid: osx-arm64
          - os: ubuntu-latest
            rid: linux-x64
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-dotnet@v4
        with:
          global-json-file: global.json
      - run: dotnet restore
      - run: dotnet build -c Release --no-restore
      - run: dotnet test -c Release --no-build
      - run: dotnet publish src/*/*.csproj -c Release -r ${{ matrix.rid }} --self-contained -p:PublishSingleFile=true -o publish/${{ matrix.rid }}
      - uses: actions/upload-artifact@v4
        with:
          name: app-${{ matrix.rid }}
          path: publish/${{ matrix.rid }}
""")
        return
    if spec["target"] == "cli":
        w(".github/workflows/ci.yml", """name: CI
on:
  push:
  pull_request:
jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [windows-latest, macos-latest, ubuntu-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -e .[test]
      - run: pytest -q
      - run: pip install pyinstaller && python scripts/build_exe.py
      - uses: actions/upload-artifact@v4
        with:
          name: ejecutable-${{ matrix.os }}
          path: dist/
""")
        return
    if spec["target"] == "desktop":
        # Escritorio: pruebas e instaladores en los tres sistemas (cada instalador se crea en su SO).
        w(".github/workflows/ci.yml", """name: CI
on:
  push:
  pull_request:
jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        os: [windows-latest, macos-latest, ubuntu-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - run: npm ci || npm install
      - run: npm test
      - if: runner.os == 'Linux'
        run: xvfb-run -a npm run smoke
      - if: runner.os != 'Linux'
        run: npm run smoke
      - run: npx electron-builder --publish never
        env:
          CSC_IDENTITY_AUTO_DISCOVERY: false
      - uses: actions/upload-artifact@v4
        with:
          name: instalador-${{ matrix.os }}
          path: |
            dist/*.exe
            dist/*.dmg
            dist/*.AppImage
            dist/*.deb
""")
        return
    steps, _ = _RUN[spec["target"]]
    setup = ("      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.12'\n"
             if spec["target"] in ("fastapi", "django") else
             "      - uses: actions/setup-node@v4\n        with:\n          node-version: 22\n")
    run = "\n".join(f"      - run: {s}" for s in steps)
    w(".github/workflows/ci.yml", f"""name: CI
on:
  push:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
{setup}{run}
""")


def _docker(spec: dict[str, Any], w: Writer) -> None:
    t = spec["target"]
    if t == "fastapi":
        body = """FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]"""
    elif t == "express":
        body = """FROM node:22-slim
WORKDIR /app
COPY package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi
COPY src ./src
COPY public ./public
EXPOSE 8000
CMD ["node", "src/server.js"]"""
    elif t == "django":
        body = """FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY . .
ENV DJANGO_DEBUG=0
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate && gunicorn config.wsgi -b 0.0.0.0:8000"]"""
    elif t == "next":
        body = """FROM node:22-slim
WORKDIR /app
COPY package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
RUN npm run build
ENV NEXT_TELEMETRY_DISABLED=1
EXPOSE 3000
CMD ["npm", "start"]"""
    elif t in ("react", "vue", "svelte"):
        body = """FROM node:22-slim AS build
WORKDIR /app
COPY package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80"""
    else:
        body = """FROM nginx:alpine
COPY . /usr/share/nginx/html
EXPOSE 80"""
    w("Dockerfile", body)


def _readme(spec: dict[str, Any]) -> str:
    steps, run = _RUN[spec["target"]]
    srcs = "\n".join(f"- `{s['subject']}` ({s['kind']})" for s in spec["sources"])
    api = ""
    if spec["api"]["resources"]:
        api = "\n## API\n\n" + "\n".join(
            f"- `GET/POST /api/{r}` · `GET/PUT/DELETE /api/{r}/:id`" for r in spec["api"]["resources"]) + "\n"
    return f"""# {spec["title"]}

Proyecto **nuevo** generado por Eolfi (`{spec["target"]}`). Se inspira en la
estructura de las fuentes analizadas, pero todo el código y los textos son
nuevos; las dependencias se instalaron en su versión más reciente.

## Arrancar

```bash
{run}
```

## Verificar

```bash
{chr(10).join(steps)}
```
{api}
## Qué se tomó de las fuentes

- Pila elegida: **{spec["target"]}** (votos: {", ".join(f"{k} ×{v}" for k, v in list(spec["stack_votes"].items())[:8]) or "ninguno"}).
- Secciones: {", ".join(spec["sections"])}.
- Páginas: {", ".join(spec["pages"])}.
- Paleta: primario `{spec["design"]["palette"]["primary"]}`, acento `{spec["design"]["palette"]["accent"]}`; fuente `{spec["design"]["font"]}`.

Fuentes analizadas:

{srcs}

La especificación completa está en `eolfi.spec.json`.
"""
