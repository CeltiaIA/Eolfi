"""Destinos adicionales: Svelte 5 (Vite), Next.js (App Router) y Django.

Mismo principio que eolfi.generador.generators: código nuevo desde plantillas
propias, contenido de ejemplo separado en datos, dependencias "latest" que
la verificación instala y fija.
"""
from __future__ import annotations

import json
from typing import Any

from eolfi.generador import templates as tpl
from eolfi.generador.generators import (CSP, SECURITY_HEADERS, VITE_SECURITY, Writer, _page_sections, _pascal, _routes, _ts_api_client, _vite_index,
                                    STATIC_JS)
from eolfi.generador.templates import SECTIONS, base_css, content_for, tokens_css


def _all_sections(spec: dict[str, Any]) -> list[str]:
    return sorted(set(sum((_page_sections(spec, slug) for slug, _p, _t in _routes(spec)), [])))


def _content_ts(spec: dict[str, Any]) -> str:
    return ("// Textos de ejemplo: cámbialos por los tuyos.\nexport const content = "
            + json.dumps(content_for(spec), indent=2, ensure_ascii=False) + " as const;\n")


# ---------------------------------------------------------------------------
# Svelte 5 + Vite + TypeScript
# ---------------------------------------------------------------------------
def gen_svelte(spec: dict[str, Any], w: Writer) -> None:
    routes = _routes(spec)
    resources = spec["api"]["resources"]
    w("package.json", json.dumps({
        "name": spec["name"], "version": "0.1.0", "private": True, "type": "module",
        "scripts": {"dev": "vite", "build": "svelte-check --tsconfig ./tsconfig.json && vite build",
                    "preview": "vite preview", "test": "vitest run"},
        "devDependencies": {"svelte": "latest", "vite": "latest", "@sveltejs/vite-plugin-svelte": "latest",
                            "typescript": "latest", "svelte-check": "latest", "vitest": "latest"},
    }, indent=2))
    w("index.html", _vite_index(spec, "/src/main.ts").replace('    <div id="root"></div>\n', ""))
    w("vite.config.ts", """/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

""" + VITE_SECURITY + """export default defineConfig({
  plugins: [svelte(), cspMeta()],
  server: { proxy: { "/api": "http://localhost:8000" } },
  preview: { headers: SECURITY_HEADERS },
  test: { environment: "node" },
});
""")
    w("svelte.config.js", """import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

export default { preprocess: vitePreprocess() };
""")
    w("tsconfig.json", json.dumps({"compilerOptions": {
        "target": "ES2022", "lib": ["ES2022", "DOM", "DOM.Iterable"], "module": "ESNext",
        "moduleResolution": "bundler", "strict": True, "skipLibCheck": True, "noEmit": True,
        "isolatedModules": True, "verbatimModuleSyntax": True, "types": ["vite/client"]},
        "include": ["src/**/*.ts", "src/**/*.svelte"]}, indent=2))
    w("src/content.ts", _content_ts(spec))
    w("src/styles/tokens.css", tokens_css(spec))
    w("src/styles/base.css", base_css(spec))
    w("src/router.svelte.ts", """// Enrutador mínimo con runas de Svelte 5 (sin dependencias).
import { getContext, setContext } from "svelte";

export class Router {
  path = $state("/");

  constructor(initialPath?: string) {
    this.path = initialPath ?? (typeof window === "undefined" ? "/" : window.location.pathname);
    if (typeof window !== "undefined") {
      window.addEventListener("popstate", () => { this.path = window.location.pathname; });
    }
  }

  go(to: string) {
    window.history.pushState({}, "", to);
    this.path = to;
    window.scrollTo(0, 0);
  }
}

const KEY = Symbol("router");
export const provideRouter = (router: Router) => setContext(KEY, router);
export const useRouter = () => getContext<Router>(KEY);
""")
    w("src/components/Link.svelte", """<script lang="ts">
  import type { Snippet } from "svelte";
  import { useRouter } from "../router.svelte";

  let { to, children }: { to: string; children: Snippet } = $props();
  const router = useRouter();

  function onclick(e: MouseEvent) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    router.go(to);
  }
</script>

<a href={to} {onclick} aria-current={router.path === to ? "page" : undefined}>{@render children()}</a>
""")
    for s in _all_sections(spec):
        node = SECTIONS[s]
        script = f'  import {{ content }} from "../content";\n\n  const data = content.{s};\n'
        markup = tpl.render_svelte(node)
        if tpl.has_form(node):
            script += """  let sent = $state(false);

  function onSubmit(e: SubmitEvent) {
    e.preventDefault();
    (e.currentTarget as HTMLFormElement).reset();
    sent = true;
  }
"""
            markup = markup.replace("</form>", '  {#if sent}<p class="form-status" role="status">{data.thanks}</p>{/if}\n    </form>', 1)
        w(f"src/components/{s}.svelte", f'<script lang="ts">\n{script}</script>\n\n{markup}\n')
    if resources:
        w("src/api.ts", _ts_api_client(resources))
        w("src/components/ApiDemo.svelte", """<script lang="ts">
  import { onMount } from "svelte";
  import { api, resources, type Item } from "../api";

  let state = $state<Record<string, { items: Item[] | null; error: boolean }>>(
    Object.fromEntries(resources.map((r) => [r, { items: null, error: false }])),
  );

  async function load(name: string) {
    try {
      state[name].items = await api.list(name);
    } catch {
      state[name].error = true;
    }
  }

  async function add(name: string, e: SubmitEvent) {
    e.preventDefault();
    const form = e.currentTarget as HTMLFormElement;
    await api.create(name, { name: String(new FormData(form).get("name")) });
    form.reset();
    await load(name);
  }

  onMount(() => { resources.forEach((r) => void load(r)); });
</script>

<section class="api-demo" id="datos">
  <div class="container">
    <h2>Datos en vivo</h2>
    <div class="grid grid-3">
      {#each resources as r (r)}
        <div class="card">
          <h3>{r}</h3>
          <ul class="resource-list">
            {#if state[r].error}
              <li class="muted">API no disponible (arranca el backend en :8000)</li>
            {:else if state[r].items === null}
              <li class="muted">Cargando…</li>
            {:else}
              {#each state[r].items ?? [] as it (it.id)}<li>{it.name}</li>{/each}
            {/if}
          </ul>
          <form class="contact-form" onsubmit={(e) => add(r, e)}>
            <label>Nombre <input name="name" required /></label>
            <button class="btn btn-primary" type="submit">Añadir</button>
          </form>
        </div>
      {/each}
    </div>
  </div>
</section>
""")
    for slug, _path, title in routes:
        comp = _pascal(slug) + "Page"
        secs = _page_sections(spec, slug)
        imports = "\n".join(f'  import {s} from "../components/{s}.svelte";' for s in secs)
        body = "\n".join(f"<{s} />" for s in secs)
        if slug == "home" and resources:
            imports += '\n  import ApiDemo from "../components/ApiDemo.svelte";'
            body += "\n<ApiDemo />"
        header = "" if slug == "home" else f"""<section class="page-header">
  <div class="container">
    <h1>{title}</h1>
    <p class="lead">Página de ejemplo: cambia este texto.</p>
  </div>
</section>
"""
        w(f"src/pages/{comp}.svelte", f'<script lang="ts">\n{imports}\n</script>\n\n{header}{body}\n')
    page_imports = "\n".join(f'import {_pascal(s)}Page from "./pages/{_pascal(s)}Page.svelte";' for s, _p, _t in routes)
    table = ",\n".join(f'  {{ path: "{p}", title: "{t}", page: {_pascal(s)}Page }}' for s, p, t in routes)
    w("src/routes.ts", f"{page_imports}\n\nexport const routes = [\n{table},\n];\n")
    w("src/App.svelte", f"""<script lang="ts">
  import Link from "./components/Link.svelte";
  import {{ Router, provideRouter }} from "./router.svelte";
  import {{ routes }} from "./routes";

  let {{ initialPath }}: {{ initialPath?: string }} = $props();
  const router = new Router(initialPath);
  provideRouter(router);

  const route = $derived(routes.find((r) => r.path === router.path));
  let theme = $state("light");

  $effect(() => {{
    theme = localStorage.getItem("theme") ?? "light";
  }});
  $effect(() => {{
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
    document.title = route && route.path !== "/" ? `${{route.title}} · {spec["title"]}` : "{spec["title"]}";
  }});
</script>

<header class="site-header">
  <div class="container">
    <Link to="/"><span class="brand">{spec["title"]}</span></Link>
    <nav class="site-nav" aria-label="Principal">
      {{#each routes as r (r.path)}}<Link to={{r.path}}>{{r.title}}</Link>{{/each}}
      <button class="theme-toggle" type="button" aria-label="Cambiar tema"
        onclick={{() => (theme = theme === "dark" ? "light" : "dark")}}>◐</button>
    </nav>
  </div>
</header>
<main>
  {{#if route}}
    <route.page />
  {{:else}}
    <section class="page-header">
      <div class="container">
        <h1>Página no encontrada</h1>
        <Link to="/">Volver al inicio</Link>
      </div>
    </section>
  {{/if}}
</main>
<footer class="site-footer">
  <div class="container">© {spec["title"]} · Hecho con código nuevo.</div>
</footer>
""")
    w("src/main.ts", """import { mount } from "svelte";
import App from "./App.svelte";
import "./styles/tokens.css";
import "./styles/base.css";

mount(App, { target: document.getElementById("app")! });
""")
    w("src/App.test.ts", f"""import {{ describe, expect, it }} from "vitest";
import {{ render }} from "svelte/server";
import App from "./App.svelte";
import {{ routes }} from "./routes";

const html = (path: string) => render(App, {{ props: {{ initialPath: path }} }}).body;

describe("App", () => {{
  it("renderiza la portada con un único h1", () => {{
    const out = html("/");
    expect(out).toContain({tpl.js_string(spec["title"])});
    expect(out.match(/<h1[ >]/g)?.length).toBe(1);
  }});

  it.each(routes.map((r) => [r.path]))("la ruta %s renderiza", (path) => {{
    expect(html(path)).not.toContain("Página no encontrada");
  }});

  it("muestra 404 en rutas desconocidas", () => {{
    expect(html("/no-existe")).toContain("Página no encontrada");
  }});
}});
""")


# ---------------------------------------------------------------------------
# Next.js (App Router)
# ---------------------------------------------------------------------------
def _next_update_verb(spec: dict[str, Any], r: str) -> str:
    """PATCH si la fuente lo expone (y no PUT) en /api/<r>/[id]; si no se observó, PUT."""
    ms = (spec["api"].get("observed_methods") or {}).get(f"/api/{r}/[id]", [])
    return "PATCH" if "PATCH" in ms and "PUT" not in ms else "PUT"


def _next_auth(spec: dict[str, Any], w: Writer) -> list[str]:
    """Inicio y cierre de sesión con implementación propia: usuario y contraseña por variables de entorno
    (AUTH_USER, AUTH_PASSWORD), sesión firmada con HMAC-SHA256 (AUTH_SECRET) en cookie HttpOnly."""
    observed = spec["api"].get("auth_endpoints") or []
    if not observed and not (spec.get("options") or {}).get("auth"):
        return []
    logout_methods = (spec["api"].get("observed_methods") or {}).get("/api/auth/logout", ["POST"])
    logout_methods = [m for m in logout_methods if m in ("GET", "POST")] or ["POST"]
    w("lib/auth.ts", """import { createHash, createHmac, timingSafeEqual } from "node:crypto";

// Implementación propia de Eolfi: los usuarios y la política de sesiones del original NO son observables;
// aquí hay un único usuario configurado por variables de entorno (pendiente de adaptar a tu base de datos).
// Igual en todos los módulos del servidor (rutas de la API y páginas se cargan por separado): AUTH_SECRET o, si
// falta, una clave derivada de las credenciales configuradas. En producción define AUTH_SECRET.
const SECRET = process.env.AUTH_SECRET
  || createHash("sha256").update(`eolfi-sesion:${process.env.AUTH_USER}:${process.env.AUTH_PASSWORD}`).digest("hex");
export const COOKIE = "session";
const MAX_AGE = 60 * 60 * 8;

const same = (a: string, b: string) => {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
};

export function configured(): boolean {
  return Boolean(process.env.AUTH_USER && process.env.AUTH_PASSWORD);
}

export function check(user: unknown, password: unknown): boolean {
  return typeof user === "string" && typeof password === "string" && configured()
    && same(user, process.env.AUTH_USER as string) && same(password, process.env.AUTH_PASSWORD as string);
}

export function sign(user: string): string {
  const payload = `${user}.${Math.floor(Date.now() / 1000) + MAX_AGE}`;
  return `${payload}.${createHmac("sha256", SECRET).update(payload).digest("hex")}`;
}

export function cookie(value: string, maxAge = MAX_AGE): string {
  return `${COOKIE}=${value}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${maxAge}`;
}

/** Usuario de una sesión válida (firma y caducidad) o null. */
export function verify(token: string | undefined): string | null {
  if (!token) return null;
  const i = token.lastIndexOf(".");
  if (i < 0) return null;
  const payload = token.slice(0, i), sig = token.slice(i + 1);
  const good = createHmac("sha256", SECRET).update(payload).digest("hex");
  if (!same(sig, good)) return null;
  const j = payload.lastIndexOf(".");
  const exp = Number(payload.slice(j + 1));
  return Number.isFinite(exp) && exp > Date.now() / 1000 ? payload.slice(0, j) : null;
}
""")
    w("app/api/auth/login/route.ts", """import { check, configured, cookie, sign } from "@/lib/auth";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  if (!configured()) return Response.json({ error: "Inicio de sesión no configurado (AUTH_USER, AUTH_PASSWORD)" }, { status: 503 });
  const body = (await request.json().catch(() => null)) as { user?: unknown; password?: unknown } | null;
  if (!check(body?.user, body?.password)) return Response.json({ error: "Credenciales incorrectas" }, { status: 401 });
  return Response.json({ ok: true }, { headers: { "Set-Cookie": cookie(sign(body!.user as string)) } });
}
""")
    handler = "\n".join(f"""export function {m}() {{
  return Response.json({{ ok: true }}, {{ headers: {{ "Set-Cookie": cookie("", 0) }} }});
}}
""" for m in logout_methods)
    w("app/api/auth/logout/route.ts", f"""import {{ cookie }} from "@/lib/auth";

export const dynamic = "force-dynamic";

{handler}""")
    return logout_methods


def _next_session_pages(spec: dict[str, Any], w: Writer, resource: str, logout_method: str, slugs: set[str]) -> None:
    """Pantalla de inicio de sesión que usa /api/auth/login y panel protegido que usa la API del recurso."""
    if "login" in slugs:
        w("components/LoginForm.tsx", """"use client";
import { useState } from "react";

export default function LoginForm() {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const data = new FormData(e.currentTarget);
    const res = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user: data.get("user"), password: data.get("password") }) });
    setBusy(false);
    if (res.ok) { window.location.href = "/panel"; return; }
    const body = await res.json().catch(() => ({}));
    setError(body.error || "No se pudo iniciar sesión");
  }
  return (
    <form className="card login-form" onSubmit={onSubmit}>
      <label>Usuario <input name="user" autoComplete="username" required /></label>
      <label>Contraseña <input name="password" type="password" autoComplete="current-password" required /></label>
      {error && <p role="alert" className="error">{error}</p>}
      <button className="btn" type="submit" disabled={busy}>{busy ? "Entrando…" : "Entrar"}</button>
    </form>
  );
}
""")
        w("app/login/page.tsx", """import LoginForm from "@/components/LoginForm";

export const metadata = { title: "Iniciar sesión" };

export default function Page() {
  return (
    <section className="page-header">
      <div className="container">
        <h1>Iniciar sesión</h1>
        <LoginForm />
      </div>
    </section>
  );
}
""")
    if "panel" in slugs:
        w("components/ResourcePanel.tsx", f""""use client";
import {{ useEffect, useState }} from "react";

type Item = {{ id: number; name: string; description?: string }};

export default function ResourcePanel() {{
  const [items, setItems] = useState<Item[]>([]);
  const [name, setName] = useState("");
  const load = () => fetch("/api/{resource}").then((r) => r.json()).then(setItems).catch(() => setItems([]));
  useEffect(() => {{ load(); }}, []);
  async function add(e: React.FormEvent) {{
    e.preventDefault();
    if (!name.trim()) return;
    await fetch("/api/{resource}", {{ method: "POST", headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ name }}) }});
    setName("");
    load();
  }}
  async function remove(id: number) {{
    await fetch(`/api/{resource}/${{id}}`, {{ method: "DELETE" }});
    load();
  }}
  async function logout() {{
    await fetch("/api/auth/logout", {{ method: "{logout_method}" }});
    window.location.href = "/login";
  }}
  return (
    <div className="card">
      <form onSubmit={{add}} className="row">
        <label>Nuevo <input value={{name}} onChange={{(e) => setName(e.target.value)}} /></label>
        <button className="btn" type="submit">Añadir</button>
      </form>
      <ul aria-label="{resource}">
        {{items.map((i) => (
          <li key={{i.id}}>{{i.name}} <button type="button" onClick={{() => remove(i.id)}}>Borrar</button></li>
        ))}}
      </ul>
      <button type="button" className="btn-secondary" onClick={{logout}}>Cerrar sesión</button>
    </div>
  );
}}
""")
        w("app/panel/page.tsx", """import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import ResourcePanel from "@/components/ResourcePanel";
import { COOKIE, verify } from "@/lib/auth";

export const metadata = { title: "Panel" };
export const dynamic = "force-dynamic";

export default async function Page() {
  const user = verify((await cookies()).get(COOKIE)?.value);
  if (!user) redirect("/login");
  return (
    <section className="page-header">
      <div className="container">
        <h1>Panel</h1>
        <p className="lead">Sesión iniciada como {user}.</p>
        <ResourcePanel />
      </div>
    </section>
  );
}
""")


def gen_next(spec: dict[str, Any], w: Writer) -> None:
    routes = _routes(spec)
    resources = spec["api"]["resources"] or ["items"]
    logout_methods = _next_auth(spec, w)
    if logout_methods:
        spec.setdefault("notes", []).append(
            "Inicio de sesión: implementación propia (usuario por AUTH_USER/AUTH_PASSWORD, sesión firmada con "
            "AUTH_SECRET). PENDIENTE: usuarios, roles y almacenamiento de credenciales del original no son "
            "observables y no se reproducen.")
    w("package.json", json.dumps({
        "name": spec["name"], "version": "0.1.0", "private": True,
        "scripts": {"dev": "next dev", "build": "next build", "start": "next start", "test": "node --test"},
        "dependencies": {"next": "latest", "react": "latest", "react-dom": "latest"},
        "devDependencies": {"typescript": "latest", "@types/node": "latest", "@types/react": "latest",
                            "@types/react-dom": "latest"},
    }, indent=2))
    # Next necesita scripts en línea para hidratar: CSP sin script-src estricto (sin nonce) pero con el resto.
    next_headers = dict(SECURITY_HEADERS, **{"Content-Security-Policy": CSP.replace(
        "script-src 'self'", "script-src 'self' 'unsafe-inline'")})
    w("next.config.ts", """import type { NextConfig } from "next";

// Cabeceras de seguridad (generado por Eolfi). La CSP solo en producción: «next dev» usa eval.
const ALL_HEADERS = """ + json.dumps([{"key": k, "value": v} for k, v in next_headers.items()], indent=2) + """;
const SECURITY_HEADERS = process.env.NODE_ENV === "production"
  ? ALL_HEADERS : ALL_HEADERS.filter((h) => h.key !== "Content-Security-Policy");

const nextConfig: NextConfig = {
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
};

export default nextConfig;
""")
    w("tsconfig.json", json.dumps({"compilerOptions": {
        "target": "ES2022", "lib": ["dom", "dom.iterable", "esnext"], "allowJs": False, "skipLibCheck": True,
        "strict": True, "noEmit": True, "esModuleInterop": True, "module": "esnext", "moduleResolution": "bundler",
        "resolveJsonModule": True, "isolatedModules": True, "jsx": "react-jsx", "incremental": True,
        "plugins": [{"name": "next"}], "paths": {"@/*": ["./*"]}},
        "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
        "exclude": ["node_modules"]}, indent=2))
    w("lib/content.ts", _content_ts(spec))
    w("app/globals.css", tokens_css(spec) + "\n" + base_css(spec))
    for s in _all_sections(spec):
        node = SECTIONS[s]
        jsx = tpl.render_jsx(node, 2)
        if tpl.has_form(node):
            jsx = jsx.replace("</form>", "  {sent && <p className=\"form-status\" role=\"status\">{data.thanks}</p>}\n          </form>", 1)
            w(f"components/{s}.tsx", f""""use client";

import {{ useState, type FormEvent }} from "react";
import {{ content }} from "@/lib/content";

export default function {s}() {{
  const data = content.{s};
  const [sent, setSent] = useState(false);
  const onSubmit = (e: FormEvent<HTMLFormElement>) => {{
    e.preventDefault();
    e.currentTarget.reset();
    setSent(true);
  }};
  return (
{jsx}
  );
}}
""")
        else:
            w(f"components/{s}.tsx", f"""import {{ content }} from "@/lib/content";

export default function {s}() {{
  const data = content.{s};
  return (
{jsx}
  );
}}
""")
    w("lib/api.ts", _ts_api_client(resources))
    w("components/ApiDemo.tsx", """"use client";

import { useEffect, useState, type FormEvent } from "react";
import { api, resources, type Item } from "@/lib/api";

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
        {error && <li className="muted">API no disponible</li>}
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
    w("components/ThemeToggle.tsx", """"use client";

import { useEffect, useState } from "react";

export default function ThemeToggle() {
  const [theme, setTheme] = useState("light");
  useEffect(() => { setTheme(localStorage.getItem("theme") ?? "light"); }, []);
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);
  return (
    <button className="theme-toggle" type="button" aria-label="Cambiar tema"
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>◐</button>
  );
}
""")
    nav = "\n".join(f'            <Link href="{p}">{t}</Link>' for _s, p, t in routes)
    w("app/layout.tsx", f"""import type {{ Metadata }} from "next";
import Link from "next/link";
import ThemeToggle from "@/components/ThemeToggle";
import "./globals.css";

export const metadata: Metadata = {{
  title: {{ default: {tpl.js_string(spec["title"])}, template: {tpl.js_string("%s · " + spec["title"])} }},
  description: {tpl.js_string(spec["title"] + ": proyecto generado con Eolfi.")},
}};

export default function RootLayout({{ children }}: {{ children: React.ReactNode }}) {{
  return (
    <html lang="es">
      <body>
        <header className="site-header">
          <div className="container">
            <Link className="brand" href="/">{spec["title"]}</Link>
            <nav className="site-nav" aria-label="Principal">
{nav}
              <ThemeToggle />
            </nav>
          </div>
        </header>
        <main>{{children}}</main>
        <footer className="site-footer">
          <div className="container">© {spec["title"]} · Hecho con código nuevo.</div>
        </footer>
      </body>
    </html>
  );
}}
""")
    if logout_methods:
        _next_session_pages(spec, w, resources[0], logout_methods[0], {slug for slug, _p, _t in routes})
    for slug, _path, title in routes:
        if logout_methods and slug in ("login", "panel"):
            continue        # pantallas reales de sesión (ver _next_session_pages)
        secs = _page_sections(spec, slug)
        imports = "\n".join(f'import {s} from "@/components/{s}";' for s in secs)
        body = "\n".join(f"      <{s} />" for s in secs)
        if slug == "home":
            imports += '\nimport ApiDemo from "@/components/ApiDemo";'
            body += "\n      <ApiDemo />"
            meta = ""
            file = "app/page.tsx"
            header = ""
        else:
            meta = f'\nexport const metadata = {{ title: "{title}" }};\n'
            file = f"app/{slug}/page.tsx"
            header = f"""      <section className="page-header">
        <div className="container">
          <h1>{title}</h1>
          <p className="lead">Página de ejemplo: cambia este texto.</p>
        </div>
      </section>
"""
        w(file, f"""{imports}
{meta}
export default function Page() {{
  return (
    <>
{header}{body}
    </>
  );
}}
""")
    w("app/not-found.tsx", """import Link from "next/link";

export default function NotFound() {
  return (
    <section className="page-header">
      <div className="container">
        <h1>Página no encontrada</h1>
        <Link href="/">Volver al inicio</Link>
      </div>
    </section>
  );
}
""")
    w("lib/store.ts", """// Almacén en memoria por recurso (se reinicia con el servidor). Sustitúyelo por una base de datos.
export type Item = { id: number; name: string; description?: string };

const stores = new Map<string, { next: number; items: Map<number, Item> }>();

export function store(resource: string) {
  let s = stores.get(resource);
  if (!s) {
    s = { next: 1, items: new Map() };
    stores.set(resource, s);
    const first = { id: s.next++, name: `Primer elemento de ${resource}`, description: "Dato de ejemplo" };
    s.items.set(first.id, first);
  }
  const st = s;
  return {
    list: () => [...st.items.values()],
    get: (id: number) => st.items.get(id),
    create: (data: Omit<Item, "id">) => {
      const item = { id: st.next++, ...data };
      st.items.set(item.id, item);
      return item;
    },
    update: (id: number, data: Omit<Item, "id">) => {
      if (!st.items.has(id)) return undefined;
      const item = { id, ...data };
      st.items.set(id, item);
      return item;
    },
    remove: (id: number) => st.items.delete(id),
  };
}

export function parseItem(body: unknown): { value?: Omit<Item, "id">; error?: string } {
  const b = body as { name?: unknown; description?: unknown } | null;
  if (!b || typeof b.name !== "string" || !b.name.trim() || b.name.length > 200) {
    return { error: "name es obligatorio (1-200 caracteres)" };
  }
  if (b.description !== undefined && (typeof b.description !== "string" || b.description.length > 2000)) {
    return { error: "description debe ser texto (máx. 2000)" };
  }
  return { value: { name: b.name.trim(), description: b.description as string | undefined } };
}
""")
    w("app/api/health/route.ts", """export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ ok: true });
}
""")
    for r in resources:
        w(f"app/api/{r}/route.ts", f"""import {{ parseItem, store }} from "@/lib/store";

export const dynamic = "force-dynamic";
const db = store("{r}");

export function GET() {{
  return Response.json(db.list());
}}

export async function POST(request: Request) {{
  const {{ value, error }} = parseItem(await request.json().catch(() => null));
  if (error || !value) return Response.json({{ error }}, {{ status: 422 }});
  return Response.json(db.create(value), {{ status: 201 }});
}}
""")
        w(f"app/api/{r}/[id]/route.ts", f"""import {{ parseItem, store }} from "@/lib/store";

export const dynamic = "force-dynamic";
const db = store("{r}");
type Ctx = {{ params: Promise<{{ id: string }}> }};
const notFound = () => Response.json({{ error: "No encontrado" }}, {{ status: 404 }});

export async function GET(_request: Request, {{ params }}: Ctx) {{
  const item = db.get(Number((await params).id));
  return item ? Response.json(item) : notFound();
}}

export async function {_next_update_verb(spec, r)}(request: Request, {{ params }}: Ctx) {{
  const {{ value, error }} = parseItem(await request.json().catch(() => null));
  if (error || !value) return Response.json({{ error }}, {{ status: 422 }});
  const item = db.update(Number((await params).id), value);
  return item ? Response.json(item) : notFound();
}}

export async function DELETE(_request: Request, {{ params }}: Ctx) {{
  return db.remove(Number((await params).id)) ? new Response(null, {{ status: 204 }}) : notFound();
}}
""")
    first = resources[0]
    first_verb = _next_update_verb(spec, first)
    paths = [p for _s, p, _t in routes]
    auth_test = "" if not logout_methods else f"""
test("inicio y cierre de sesión", async () => {{
  const login = (user, password) => fetch(base + "/api/auth/login", {{
    method: "POST", headers: {{ "Content-Type": "application/json" }}, body: JSON.stringify({{ user, password }}) }});
  assert.equal((await login("demo", "mal")).status, 401);
  const ok = await login("demo", "clave-de-prueba");
  assert.equal(ok.status, 200);
  assert.match(ok.headers.get("set-cookie") || "", /session=.+; Path=\\/; HttpOnly/);
  const out = await fetch(base + "/api/auth/logout", {{ method: "{logout_methods[0]}" }});
  assert.match(out.headers.get("set-cookie") || "", /Max-Age=0/);
  const session = (ok.headers.get("set-cookie") || "").split(";")[0];
  const loginHtml = await (await fetch(base + "/login")).text();
  assert.match(loginHtml, /name="password"/);
  const anon = await fetch(base + "/panel", {{ redirect: "manual" }});
  assert.ok([303, 307, 308].includes(anon.status) && /\\/login/.test(anon.headers.get("location") || ""));
  const panel = await fetch(base + "/panel", {{ headers: {{ cookie: session }} }});
  assert.equal(panel.status, 200);
  assert.match(await panel.text(), /Sesión iniciada como/);
}});
"""
    w("test/app.test.mjs", f"""// Prueba de extremo a extremo: arranca `next start` (requiere `npm run build` antes).
import {{ test, before, after }} from "node:test";
import assert from "node:assert/strict";
import {{ spawn }} from "node:child_process";
import {{ createServer }} from "node:net";
import {{ createRequire }} from "node:module";

const require = createRequire(import.meta.url);
const nextBin = require.resolve("next/dist/bin/next");
let proc;
let base;

const freePort = () => new Promise((resolve) => {{
  const s = createServer().listen(0, () => {{ const p = s.address().port; s.close(() => resolve(p)); }});
}});

before(async () => {{
  const port = await freePort();
  base = `http://127.0.0.1:${{port}}`;
  proc = spawn(process.execPath, [nextBin, "start", "-p", String(port), "-H", "127.0.0.1"],
    {{ stdio: "ignore", env: {{ ...process.env, NEXT_TELEMETRY_DISABLED: "1", AUTH_USER: "demo",
                               AUTH_PASSWORD: "clave-de-prueba" }} }});
  for (let i = 0; i < 120; i++) {{
    try {{ if ((await fetch(base + "/api/health")).ok) return; }} catch {{ /* aún arrancando */ }}
    await new Promise((r) => setTimeout(r, 500));
  }}
  throw new Error("next start no respondió");
}});
after(() => proc?.kill());

for (const path of {json.dumps(paths)}) {{
  test(`la página ${{path}} responde`, async () => {{
    const res = await fetch(base + path);
    assert.equal(res.status, 200);
    const html = await res.text();
    assert.match(html, /<main>/);
    assert.match(html, /<html lang="es"/);
  }});
}}

test("404 en rutas desconocidas", async () => {{
  assert.equal((await fetch(base + "/no-existe")).status, 404);
}});

test("CRUD de {first}", async () => {{
  const json = (method, path, body) => fetch(base + path, {{
    method, headers: {{ "Content-Type": "application/json" }}, body: body && JSON.stringify(body) }});
  const created = await json("POST", "/api/{first}", {{ name: "prueba" }});
  assert.equal(created.status, 201);
  const item = await created.json();
  assert.equal((await (await fetch(`${{base}}/api/{first}/${{item.id}}`)).json()).name, "prueba");
  assert.equal((await (await json("{first_verb}", `/api/{first}/${{item.id}}`, {{ name: "cambio" }})).json()).name, "cambio");
  assert.equal((await json("DELETE", `/api/{first}/${{item.id}}`)).status, 204);
  assert.equal((await fetch(`${{base}}/api/{first}/${{item.id}}`)).status, 404);
  assert.equal((await json("POST", "/api/{first}", {{ name: "" }})).status, 422);
}});
""" + auth_test)


# ---------------------------------------------------------------------------
# Django
# ---------------------------------------------------------------------------
def _model(r: str) -> str:
    return _pascal(r)


def gen_django(spec: dict[str, Any], w: Writer) -> None:
    routes = _routes(spec)
    resources = spec["api"]["resources"] or ["items"]
    content = content_for(spec)
    w("requirements.txt", "django\n")
    w("manage.py", '''#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    # manage.py es la herramienta de desarrollo (runserver, test, check): modo depuración salvo que se
    # diga otra cosa. El servidor de producción (wsgi/asgi, gunicorn) arranca SIN depuración.
    os.environ.setdefault("DJANGO_DEBUG", "1")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
''')
    w("config/__init__.py", "")
    w("config/settings.py", f'''"""Ajustes de {spec["title"]}. En producción define DJANGO_SECRET_KEY, DJANGO_DEBUG=0 y DJANGO_ALLOWED_HOSTS."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"   # seguro por defecto (manage.py activa la depuración)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        # En producción una clave conocida permitiría falsificar sesiones y entrar al admin.
        raise RuntimeError("Define DJANGO_SECRET_KEY (obligatoria con DJANGO_DEBUG=0)")
    SECRET_KEY = "solo-desarrollo-no-usar-en-produccion"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")

# Cabeceras y cookies seguras siempre; HTTPS obligatorio en producción (detrás de un proxy TLS define
# DJANGO_SECURE_PROXY=1 para confiar en X-Forwarded-Proto).
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
if not DEBUG:
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SSL_REDIRECT", "1") == "1"
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    if os.environ.get("DJANGO_SECURE_PROXY") == "1":
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {{"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]}},
}}]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {{"default": {{"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}}}
LANGUAGE_CODE = "es"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
''')
    w("config/wsgi.py", '''import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_wsgi_application()
''')
    w("config/asgi.py", '''import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_asgi_application()
''')
    w("core/__init__.py", "")
    # CSP y cabeceras de seguridad, igual que el resto de destinos web (Fase E). Propio y sin dependencias:
    # funciona con cualquier versión de Django.
    w("core/middleware.py", f'''"""Cabeceras de seguridad en todas las respuestas (generado por Eolfi)."""

SECURITY_HEADERS = {SECURITY_HEADERS!r}


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        for key, value in SECURITY_HEADERS.items():
            if key not in response:
                response[key] = value
        return response
''')
    w("core/apps.py", '''from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
''')
    models = "\n\n".join(f'''class {_model(r)}(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name_plural = "{r}"

    def __str__(self) -> str:
        return self.name

    def as_dict(self) -> dict:
        return {{"id": self.id, "name": self.name, "description": self.description}}''' for r in resources)
    w("core/models.py", f"from django.db import models\n\n\n{models}\n")
    ops = ",\n".join(f'''        migrations.CreateModel(
            name="{_model(r)}",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True, default="")),
                ("created", models.DateTimeField(auto_now_add=True)),
            ],
            options={{"ordering": ["id"], "verbose_name_plural": "{r}"}},
        )''' for r in resources)
    w("core/migrations/__init__.py", "")
    w("core/migrations/0001_initial.py", f'''from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
{ops},
    ]
''')
    w("core/admin.py", "from django.contrib import admin\n\nfrom core import models\n\n" + "\n".join(
        f"admin.site.register(models.{_model(r)})" for r in resources) + "\n")
    w("core/content.py", "# Textos de ejemplo: cámbialos por los tuyos.\nCONTENT = "
      + json.dumps(content, indent=4, ensure_ascii=False) + "\n\nROUTES = "
      + json.dumps([{"slug": s, "path": p, "title": t} for s, p, t in routes], indent=4, ensure_ascii=False) + "\n")
    w("core/views.py", '''import json

from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from core.content import CONTENT, ROUTES

PAGES = {r["slug"]: r for r in ROUTES}


def page(request: HttpRequest, slug: str = "home") -> HttpResponse:
    route = PAGES.get(slug)
    if route is None:
        raise Http404
    template = "core/home.html" if slug == "home" else f"core/{slug}.html"
    return render(request, template, {"c": CONTENT, "routes": ROUTES, "route": route})


def health(_request: HttpRequest) -> JsonResponse:
    return JsonResponse({"ok": True})


def _parse(request: HttpRequest) -> tuple[dict | None, str | None]:
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return None, "JSON inválido"
    name = body.get("name") if isinstance(body, dict) else None
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        return None, "name es obligatorio (1-200 caracteres)"
    desc = body.get("description", "")
    if not isinstance(desc, str) or len(desc) > 2000:
        return None, "description debe ser texto (máx. 2000)"
    return {"name": name.strip(), "description": desc}, None


# API JSON de demostración: sin sesión ni cookies, por eso se exime de CSRF.
# Añade autenticación (tokens) antes de exponerla.
@csrf_exempt
def api_list(request: HttpRequest, model) -> JsonResponse:
    if request.method == "GET":
        return JsonResponse([o.as_dict() for o in model.objects.all()], safe=False)
    if request.method == "POST":
        data, error = _parse(request)
        if error:
            return JsonResponse({"error": error}, status=422)
        return JsonResponse(model.objects.create(**data).as_dict(), status=201)
    return JsonResponse({"error": "método no permitido"}, status=405)


@csrf_exempt
def api_detail(request: HttpRequest, model, pk: int) -> HttpResponse:
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        return JsonResponse({"error": "No encontrado"}, status=404)
    if request.method == "GET":
        return JsonResponse(obj.as_dict())
    if request.method == "PUT":
        data, error = _parse(request)
        if error:
            return JsonResponse({"error": error}, status=422)
        for k, v in data.items():
            setattr(obj, k, v)
        obj.save()
        return JsonResponse(obj.as_dict())
    if request.method == "DELETE":
        obj.delete()
        return HttpResponse(status=204)
    return JsonResponse({"error": "método no permitido"}, status=405)
''')
    api_urls = "\n".join(
        f'    path("api/{r}", views.api_list, {{"model": models.{_model(r)}}}),\n'
        f'    path("api/{r}/<int:pk>", views.api_detail, {{"model": models.{_model(r)}}}),' for r in resources)
    page_urls = "\n".join(f'    path("{s}/", views.page, {{"slug": "{s}"}}),' for s, _p, _t in routes if s != "home")
    w("config/urls.py", f'''from django.contrib import admin
from django.urls import path

from core import models, views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health", views.health),
{api_urls}
    path("", views.page, {{"slug": "home"}}),
{page_urls}
]
''')
    nav = "\n".join(
        f'        <a href="{p if p == "/" else p + "/"}"{{% if route.slug == "{s}" %}} aria-current="page"{{% endif %}}>{t}</a>'
        for s, p, t in routes)
    w("core/templates/core/base.html", f"""{{% load static %}}<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{% if route.slug != "home" %}}{{{{ route.title }}}} · {{% endif %}}{spec["title"]}</title>
  <meta name="description" content="{spec["title"]}: proyecto generado con Eolfi.">
  <link rel="stylesheet" href="{{% static 'css/tokens.css' %}}">
  <link rel="stylesheet" href="{{% static 'css/base.css' %}}">
  <script src="{{% static 'js/main.js' %}}" defer></script>
</head>
<body>
  <header class="site-header">
    <div class="container">
      <a class="brand" href="/">{spec["title"]}</a>
      <nav class="site-nav" aria-label="Principal">
{nav}
        <button class="theme-toggle" type="button" data-theme-toggle aria-label="Cambiar tema">◐</button>
      </nav>
    </div>
  </header>
  <main>
{{% block content %}}{{% endblock %}}
  </main>
  <footer class="site-footer">
    <div class="container">© {spec["title"]} · Hecho con código nuevo.</div>
  </footer>
</body>
</html>
""")
    for slug, _path, title in routes:
        blocks = []
        if slug != "home":
            blocks.append(f'<section class="page-header"><div class="container"><h1>{title}</h1>'
                          f'<p class="lead">Página de ejemplo: cambia este texto.</p></div></section>')
        for s in _page_sections(spec, slug):
            blocks.append(f"{{% with data=c.{s} %}}\n{tpl.render_django(SECTIONS[s], 1)}\n{{% endwith %}}")
        if slug == "home":
            from eolfi.generador.generators import _api_demo_html
            blocks.append(_api_demo_html(resources, False))
        name = "home" if slug == "home" else slug
        w(f"core/templates/core/{name}.html", '{% extends "core/base.html" %}\n{% block content %}\n'
          + "\n".join(blocks) + "\n{% endblock %}\n")
    w("core/static/css/tokens.css", tokens_css(spec))
    w("core/static/css/base.css", base_css(spec))
    w("core/static/js/main.js", STATIC_JS)
    first = resources[0]
    page_tests = "\n".join(f'            ("{p if p == "/" else p + "/"}", "{t}"),' for _s, p, t in routes)
    w("core/tests.py", f'''import json

from django.test import TestCase


class PagesTests(TestCase):
    def test_pages_render(self):
        for path, title in [
{page_tests}
        ]:
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertContains(r, "<main>")
            self.assertContains(r, '<html lang="es">')

    def test_single_h1_on_home(self):
        html = self.client.get("/").content.decode()
        self.assertEqual(html.count("<h1"), 1)

    def test_404(self):
        self.assertEqual(self.client.get("/no-existe/").status_code, 404)

    def test_security_headers(self):
        r = self.client.get("/")
        self.assertIn("default-src 'self'", r["Content-Security-Policy"])
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", r["Content-Security-Policy"])


class ApiTests(TestCase):
    def call(self, method, path, body=None):
        return getattr(self.client, method)(path, data=json.dumps(body) if body is not None else None,
                                            content_type="application/json")

    def test_crud_{first.replace("-", "_")}(self):
        r = self.call("post", "/api/{first}", {{"name": "prueba"}})
        self.assertEqual(r.status_code, 201)
        pk = r.json()["id"]
        self.assertEqual(self.client.get(f"/api/{first}/{{pk}}").json()["name"], "prueba")
        self.assertEqual(self.call("put", f"/api/{first}/{{pk}}", {{"name": "cambio"}}).json()["name"], "cambio")
        self.assertEqual(self.client.delete(f"/api/{first}/{{pk}}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/{first}/{{pk}}").status_code, 404)

    def test_validation(self):
        self.assertEqual(self.call("post", "/api/{first}", {{"name": ""}}).status_code, 422)

    def test_health(self):
        self.assertEqual(self.client.get("/api/health").json(), {{"ok": True}})
''')
