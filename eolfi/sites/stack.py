"""Huellas de tecnologías web y de repositorios (compartidas por ambos análisis).

Cada tecnología declara dónde puede aparecer su huella:
- html: subcadenas del HTML (atributos, ids, rutas de assets).
- js: subcadenas del JavaScript servido.
- css: subcadenas del CSS.
- header: (cabecera, subcadena) en la respuesta HTTP.
- npm / pypi / cargo / go / maven / gem / composer / nuget / pub: nombres de
  dependencia en los manifiestos de un repositorio.
- files: rutas o nombres de archivo en el repositorio.

`scaffold` es el comando habitual para empezar un proyecto así (sirve para
el plano de recreación; no se ejecuta nunca).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Tech:
    name: str
    category: str
    html: tuple[str, ...] = ()
    js: tuple[str, ...] = ()
    css: tuple[str, ...] = ()
    header: tuple[tuple[str, str], ...] = ()
    npm: tuple[str, ...] = ()
    pypi: tuple[str, ...] = ()
    cargo: tuple[str, ...] = ()
    go: tuple[str, ...] = ()
    maven: tuple[str, ...] = ()
    gem: tuple[str, ...] = ()
    composer: tuple[str, ...] = ()
    nuget: tuple[str, ...] = ()
    pub: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    scaffold: str = ""
    implies: tuple[str, ...] = field(default=())


TECHS: tuple[Tech, ...] = (
    # --- Meta-frameworks / SSR -------------------------------------------
    Tech("Next.js", "meta-framework", html=('id="__next"', "/_next/static/", "__NEXT_DATA__"),
         js=("__NEXT_DATA__", "next/router", "__next_f"), header=(("x-powered-by", "next.js"),),
         npm=("next",), files=("next.config.js", "next.config.mjs", "next.config.ts"),
         scaffold="npx create-next-app@latest", implies=("React",)),
    Tech("Nuxt", "meta-framework", html=('id="__nuxt"', "/_nuxt/", "window.__NUXT__"), js=("__NUXT__", "$nuxt"),
         npm=("nuxt",), files=("nuxt.config.ts", "nuxt.config.js"), scaffold="npx nuxi@latest init", implies=("Vue",)),
    Tech("Remix / React Router", "meta-framework", html=("__remixContext", "__reactRouterContext"),
         js=("__remixContext", "__reactRouterContext"), npm=("@remix-run/react", "@react-router/dev"),
         scaffold="npx create-react-router@latest", implies=("React",)),
    Tech("VitePress", "ssg", html=("VPNav", "VPContent", "VPLink"), css=("--vp-c-",), npm=("vitepress",),
         scaffold="npx vitepress init", implies=("Vue",)),
    Tech("Gatsby", "meta-framework", html=('id="___gatsby"', "/page-data/"), js=("___gatsby",), npm=("gatsby",),
         files=("gatsby-config.js", "gatsby-config.ts"), scaffold="npm init gatsby", implies=("React",)),
    Tech("Astro", "meta-framework", html=("astro-island", "data-astro-cid", "/_astro/"), npm=("astro",),
         files=("astro.config.mjs", "astro.config.ts"), scaffold="npm create astro@latest"),
    Tech("SvelteKit", "meta-framework", html=("__sveltekit", "/_app/immutable/"), js=("__sveltekit",),
         npm=("@sveltejs/kit",), files=("svelte.config.js",), scaffold="npx sv create", implies=("Svelte",)),
    Tech("Angular Universal / SSR", "meta-framework", html=("ng-server-context",), npm=("@angular/ssr",),
         implies=("Angular",)),
    # --- Frameworks de UI -------------------------------------------------
    Tech("React", "ui-framework", html=("data-reactroot", "data-reactid"),
         js=("react-dom", "__REACT_DEVTOOLS_GLOBAL_HOOK__", "react.production", "useState("),
         npm=("react", "react-dom"), scaffold="npm create vite@latest -- --template react-ts"),
    Tech("Preact", "ui-framework", js=("preact",), npm=("preact",), scaffold="npm create vite@latest -- --template preact-ts"),
    Tech("Vue", "ui-framework", html=("data-v-", "data-server-rendered", "v-cloak"),
         js=("__VUE__", "createApp(", "vue.runtime", "__vue_app__"), npm=("vue",),
         scaffold="npm create vue@latest"),
    Tech("Angular", "ui-framework", html=("ng-version", "_nghost-", "_ngcontent-"), js=("ɵcmp", "ngDevMode", "@angular/core"),
         npm=("@angular/core",), files=("angular.json",), scaffold="npx @angular/cli new"),
    Tech("Svelte", "ui-framework", html=("svelte-",), js=("svelte/internal", "$$props", "SvelteComponent"),
         npm=("svelte",), scaffold="npx sv create"),
    Tech("SolidJS", "ui-framework", js=("solid-js", "_$HY"), npm=("solid-js",), scaffold="npx degit solidjs/templates/ts"),
    Tech("Lit / Web Components", "ui-framework", js=("lit-html", "LitElement", "customElements.define"), npm=("lit",)),
    Tech("Alpine.js", "ui-library", html=("x-data=", "x-show=", "@click="), js=("Alpine.start",), npm=("alpinejs",)),
    Tech("htmx", "ui-library", html=("hx-get=", "hx-post=", "hx-target="), js=("htmx.org",), npm=("htmx.org",)),
    # Marcas concretas: «jquery» suelto aparecía en comentarios y nombres de otras librerías.
    Tech("jQuery", "ui-library", js=("jQuery.fn", "jquery.min.js", "jquery.js"),
         html=("jquery.min.js", "jquery.js", "code.jquery.com"), npm=("jquery",)),
    Tech("Ember", "ui-framework", html=("ember-application",), js=("Ember.Application",), npm=("ember-source",)),
    # En un repositorio, Flutter Web solo si además hay web/index.html (si no, es Flutter móvil/escritorio).
    Tech("Flutter Web", "ui-framework", html=("flutter.js", "flutter_bootstrap.js"), js=("_flutter",),
         scaffold="flutter create --platforms web"),
    # --- CSS ---------------------------------------------------------------
    Tech("Tailwind CSS", "css", css=("--tw-", "tailwindcss"), npm=("tailwindcss",),
         files=("tailwind.config.js", "tailwind.config.ts"), scaffold="npm install -D tailwindcss @tailwindcss/vite"),
    Tech("Bootstrap", "css", css=("--bs-", "bootstrap v"), html=("bootstrap.min.css", "bootstrap.bundle"),
         js=("bootstrap.bundle",), npm=("bootstrap",)),
    Tech("Bulma", "css", css=("bulma",), npm=("bulma",)),
    Tech("Material UI", "css", html=("MuiButtonBase-root", "MuiTypography-root"), css=(".MuiButtonBase-root",), npm=("@mui/material",)),
    Tech("Chakra UI", "css", css=("--chakra-",), npm=("@chakra-ui/react",)),
    Tech("styled-components", "css", html=("data-styled",), npm=("styled-components",)),
    Tech("Emotion", "css", html=("data-emotion",), npm=("@emotion/react",)),
    Tech("Sass", "css", npm=("sass",), files=(".scss",)),
    # --- Bundlers / build ---------------------------------------------------
    Tech("Vite", "bundler", html=("/@vite/client", "/assets/index-"), js=("import.meta.env", "__vite__"),
         npm=("vite",), files=("vite.config.ts", "vite.config.js"), scaffold="npm create vite@latest"),
    Tech("webpack", "bundler", js=("webpackChunk", "__webpack_require__", "webpackJsonp"), npm=("webpack",),
         files=("webpack.config.js",)),
    Tech("Parcel", "bundler", js=("parcelRequire",), npm=("parcel",)),
    Tech("esbuild", "bundler", npm=("esbuild",)),
    Tech("Turbopack", "bundler", js=("TURBOPACK",)),
    Tech("TypeScript", "language", npm=("typescript",), files=("tsconfig.json",)),
    # --- CMS / plataformas --------------------------------------------------
    Tech("WordPress", "cms", html=("wp-content/", "wp-includes/", 'content="WordPress'), header=(("link", "wp-json"),),
         composer=("johnpbloch/wordpress",), files=("wp-config.php",)),
    Tech("Drupal", "cms", html=("Drupal.settings", "/sites/default/files"), header=(("x-generator", "drupal"),)),
    Tech("Joomla", "cms", html=('content="Joomla',)),
    Tech("Shopify", "cms", html=("cdn.shopify.com", "Shopify.theme"), header=(("x-shopid", ""),)),
    Tech("Wix", "cms", html=("static.wixstatic.com", "wix-"), header=(("x-wix-request-id", ""),)),
    Tech("Squarespace", "cms", html=("static1.squarespace.com",)),
    Tech("Webflow", "cms", html=("data-wf-page", "webflow.js")),
    Tech("Ghost", "cms", html=('content="Ghost',), npm=("ghost",)),
    # config.toml y _config.yml solos no bastan (los usan muchas herramientas): ver _special_repo().
    Tech("Hugo", "ssg", html=('content="Hugo',), files=("hugo.toml",), scaffold="hugo new site"),
    Tech("Jekyll", "ssg", html=('content="Jekyll',), gem=("jekyll",), scaffold="jekyll new"),
    Tech("Docusaurus", "ssg", html=("docusaurus",), npm=("@docusaurus/core",), scaffold="npx create-docusaurus@latest"),
    Tech("Eleventy", "ssg", html=('content="Eleventy',), npm=("@11ty/eleventy",)),
    # --- Servidores / hosting (cabeceras) -----------------------------------
    Tech("Cloudflare", "hosting", header=(("server", "cloudflare"), ("cf-ray", ""))),
    Tech("Vercel", "hosting", header=(("server", "vercel"), ("x-vercel-id", "")), files=("vercel.json",)),
    Tech("Netlify", "hosting", header=(("server", "netlify"), ("x-nf-request-id", "")), files=("netlify.toml",)),
    Tech("GitHub Pages", "hosting", header=(("server", "github.com"),)),
    Tech("nginx", "server", header=(("server", "nginx"),)),
    Tech("Apache", "server", header=(("server", "apache"),)),
    Tech("Express", "backend", header=(("x-powered-by", "express"),), npm=("express",)),
    Tech("PHP", "backend", header=(("x-powered-by", "php"),), files=(".php",)),
    Tech("ASP.NET", "backend", header=(("x-powered-by", "asp.net"), ("x-aspnet-version", "")),
         nuget=("Microsoft.AspNetCore", "sdk:microsoft.net.sdk.web"), scaffold="dotnet new webapp"),
    # --- Backends por dependencias -----------------------------------------
    Tech("Fastify", "backend", npm=("fastify",)),
    Tech("NestJS", "backend", npm=("@nestjs/core",), scaffold="npx @nestjs/cli new"),
    Tech("Hono", "backend", npm=("hono",), scaffold="npm create hono@latest"),
    Tech("Django", "backend", pypi=("django",), files=("manage.py",), scaffold="django-admin startproject"),
    Tech("Flask", "backend", pypi=("flask",)),
    Tech("FastAPI", "backend", pypi=("fastapi",)),
    Tech("Ruby on Rails", "backend", gem=("rails",), files=("config/routes.rb",), scaffold="rails new"),
    Tech("Laravel", "backend", composer=("laravel/framework",), files=("artisan",),
         scaffold="composer create-project laravel/laravel"),
    Tech("Spring Boot", "backend", maven=("spring-boot",), scaffold="https://start.spring.io"),
    Tech("Gin", "backend", go=("github.com/gin-gonic/gin",)),
    Tech("Echo", "backend", go=("github.com/labstack/echo",)),
    Tech("Actix Web", "backend", cargo=("actix-web",)),
    Tech("Axum", "backend", cargo=("axum",)),
    # --- Escritorio / móvil -------------------------------------------------
    Tech("Electron", "desktop", npm=("electron",), scaffold="npm init electron-app@latest"),
    Tech("Tauri", "desktop", npm=("@tauri-apps/api",), cargo=("tauri",), files=("src-tauri/tauri.conf.json",),
         scaffold="npm create tauri-app@latest"),
    Tech("Click", "cli", pypi=("click",)),
    Tech("Typer", "cli", pypi=("typer",)),
    Tech("clap", "cli", cargo=("clap",)),
    Tech("Cobra", "cli", go=("github.com/spf13/cobra",)),
    Tech("Commander.js", "cli", npm=("commander",)),
    Tech("yargs", "cli", npm=("yargs",)),
    Tech("Qt", "desktop", pypi=("pyside6", "pyqt5", "pyqt6"), files=("CMakeLists.txt.qt",)),
    Tech("wxPython", "desktop", pypi=("wxpython",)),
    Tech("GTK", "desktop", pypi=("pygobject",)),
    Tech("Avalonia", "desktop", nuget=("Avalonia",)),
    Tech("WPF", "desktop", nuget=("Microsoft.WindowsDesktop.App.WPF", "msbuild:usewpf"), scaffold="dotnet new wpf"),
    Tech("Windows Forms", "desktop", nuget=("Microsoft.WindowsDesktop.App.WindowsForms", "msbuild:usewindowsforms"),
         scaffold="dotnet new winforms"),
    Tech("Android (Gradle)", "mobile", maven=("plugin:com.android.application", "plugin:com.android.library"),
         files=("AndroidManifest.xml",), scaffold="Android Studio: New Project"),
    Tech("React Native", "mobile", npm=("react-native",), scaffold="npx @react-native-community/cli init"),
    Tech("Expo", "mobile", npm=("expo",), scaffold="npx create-expo-app@latest", implies=("React Native",)),
    Tech("Flutter", "mobile", pub=("flutter",), scaffold="flutter create"),
    Tech(".NET MAUI", "mobile", nuget=("Microsoft.Maui", "msbuild:usemaui"), scaffold="dotnet new maui"),
    # --- Pruebas ------------------------------------------------------------
    Tech("Jest", "testing", npm=("jest",)),
    Tech("Vitest", "testing", npm=("vitest",)),
    Tech("Playwright", "testing", npm=("@playwright/test",), pypi=("playwright",)),
    Tech("Cypress", "testing", npm=("cypress",)),
    Tech("pytest", "testing", pypi=("pytest",)),
    Tech("JUnit", "testing", maven=("junit",)),
    # --- Librerías notables (web) ------------------------------------------
    Tech("Three.js", "library", js=("THREE.WebGLRenderer", "three.module"), npm=("three",)),
    Tech("GSAP", "library", js=("gsap", "TweenMax"), npm=("gsap",)),
    Tech("Chart.js", "library", js=("Chart.register", "chart.js"), npm=("chart.js",)),
    Tech("D3", "library", js=("d3.select", "d3-selection"), npm=("d3",)),
    Tech("Lodash", "library", js=("lodash",), npm=("lodash",)),
    Tech("Axios", "library", js=("axios",), npm=("axios",)),
    Tech("Google Analytics / gtag", "analytics", html=("googletagmanager.com", "google-analytics.com"), js=("gtag(",)),
    Tech("Google Tag Manager", "analytics", html=("GTM-",)),
    Tech("Plausible", "analytics", html=("plausible.io/js",)),
    Tech("Sentry", "monitoring", js=("Sentry.init", "sentry-cdn", "@sentry/"), npm=("@sentry/browser", "@sentry/react")),
    Tech("Stripe.js", "payments", html=("js.stripe.com",), npm=("@stripe/stripe-js",)),
    Tech("reCAPTCHA", "security", html=("www.google.com/recaptcha", "g-recaptcha")),
    Tech("Cloudflare Turnstile", "security", html=("challenges.cloudflare.com/turnstile",)),
    Tech("Font Awesome", "icons", html=("font-awesome", "fontawesome"), css=("Font Awesome",)),
    Tech("Google Fonts", "fonts", html=("fonts.googleapis.com",), css=("fonts.gstatic.com",)),
)

BY_NAME = {t.name: t for t in TECHS}


def _add(found: dict[str, dict[str, Any]], tech: Tech, where: str) -> None:
    entry = found.setdefault(tech.name, {"name": tech.name, "category": tech.category, "evidence": []})
    if where not in entry["evidence"] and len(entry["evidence"]) < 5:
        entry["evidence"].append(where)


def detect_web(html: str, scripts: list[tuple[str, str]], styles: list[tuple[str, str]],
               headers: dict[str, str]) -> list[dict[str, Any]]:
    """scripts/styles: lista de (origen, contenido). headers en minúsculas."""
    found: dict[str, dict[str, Any]] = {}
    for t in TECHS:
        for m in t.html:
            if m in html:
                _add(found, t, f"html contiene '{m}'")
        for src, body in scripts:
            for m in t.js:
                if m in body or m.lower() in src.lower():
                    _add(found, t, f"js {src[-60:]} contiene '{m}'")
        for src, body in styles:
            for m in t.css:
                if m in body:
                    _add(found, t, f"css {src[-60:]} contiene '{m}'")
        for h, m in t.header:
            v = headers.get(h)
            if v is not None and m in v.lower():
                _add(found, t, f"cabecera {h}: {v[:60]}")
    _apply_implies(found)
    return sorted(found.values(), key=lambda x: (x["category"], x["name"]))


def detect_repo(deps: dict[str, set[str]], paths: set[str]) -> list[dict[str, Any]]:
    """deps: ecosistema -> nombres de dependencia; paths: rutas relativas (con /)."""
    found: dict[str, dict[str, Any]] = {}
    basenames = {p.rsplit("/", 1)[-1] for p in paths}
    exts = {"." + p.rsplit(".", 1)[-1] for p in basenames if "." in p}
    for t in TECHS:
        for eco in ("npm", "pypi", "cargo", "go", "maven", "gem", "composer", "nuget", "pub"):
            names = deps.get(eco, set())
            for dep in getattr(t, eco):
                d = dep.lower()
                for n in names:
                    dev = n.startswith("dev:")
                    bare = n[4:] if dev else n
                    if bare == d or (eco in ("maven", "go", "nuget") and _segment_match(d, bare)):
                        _add(found, t, f"{eco}{' (dev)' if dev else ''}: {bare}")
                        found[t.name]["runtime"] = found[t.name].get("runtime", False) or not dev
                        break
        for f in t.files:
            if f.startswith(".") and f in exts:
                _add(found, t, f"archivos *{f}")
            elif "/" in f and f in paths:
                _add(found, t, f"archivo {f}")
            elif f in basenames:
                _add(found, t, f"archivo {f}")
    _special_repo(found, deps, paths)
    _apply_implies(found)
    return sorted(found.values(), key=lambda x: (x["category"], x["name"]))


def _segment_match(d: str, bare: str) -> bool:
    """«echo» casa con github.com/labstack/echo/v4 pero no con github.com/x/echoserver; «junit» con
    junit:junit o org.junit.jupiter:junit-jupiter, no con «xjunitx» (M37)."""
    import re

    return re.search(rf"(?:^|[/:.]){re.escape(d)}(?:$|[/:.\-])", bare) is not None


def _special_repo(found: dict[str, dict[str, Any]], deps: dict[str, set[str]], paths: set[str]) -> None:
    has_dir = lambda prefix: any(p.startswith(prefix) for p in paths)  # noqa: E731
    if "Flutter" in found and "web/index.html" in paths:
        _add(found, BY_NAME["Flutter Web"], "Flutter con web/index.html")
    if "config.toml" in paths and has_dir("content/") and (has_dir("layouts/") or has_dir("themes/")):
        _add(found, BY_NAME["Hugo"], "config.toml con content/ y layouts/ o themes/")
    if "_config.yml" in paths and (has_dir("_posts/") or has_dir("_layouts/")):
        _add(found, BY_NAME["Jekyll"], "_config.yml con _posts/ o _layouts/")


DEV_OK = {"testing", "bundler", "language", "css"}


def app_stack(techs: list[dict[str, Any]]) -> list[str]:
    """Tecnologías que forman parte de la aplicación: descarta frameworks que
    solo aparecen como dependencia de desarrollo (p. ej. Express en las pruebas)."""
    return [t["name"] for t in techs if t.get("runtime", True) or t["category"] in DEV_OK]


def _apply_implies(found: dict[str, dict[str, Any]]) -> None:
    """Transitivo: A implica B y B implica C ⇒ también C (M37)."""
    pending = list(found)
    while pending:
        name = pending.pop()
        for imp in BY_NAME[name].implies:
            if imp in BY_NAME and imp not in found:
                pending.append(imp)
            if imp in BY_NAME:
                _add(found, BY_NAME[imp], f"implicado por {name}")


def scaffold_for(names: list[str]) -> str | None:
    """El comando de arranque más específico disponible (meta-framework > UI > bundler)."""
    order = ("meta-framework", "ssg", "desktop", "mobile", "cli", "backend", "ui-framework", "bundler")
    for cat in order:
        for n in names:
            t = BY_NAME.get(n)
            if t and t.category == cat and t.scaffold:
                return t.scaffold
    return None
