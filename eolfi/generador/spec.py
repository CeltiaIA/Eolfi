"""Fusiona los análisis de una o varias fuentes en una especificación de proyecto.

La especificación describe QUÉ construir (pila, páginas, secciones, tokens de
diseño, recursos de API, convenciones), nunca CÓMO lo hicieron las fuentes:
no contiene código ni textos de ellas. Los generadores escriben código nuevo
a partir de esta especificación.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from eolfi.core.evidence import EvidenceStore

TARGETS = ("static", "react", "vue", "svelte", "next", "fastapi", "express", "django", "expo", "desktop", "tauri", "cli", "dotnet")

# Palabras clave en clases/ids/landmarks -> tipo de sección que generaremos.
SECTION_KEYWORDS = [
    ("hero", "Hero"), ("banner", "Hero"), ("jumbotron", "Hero"),
    ("feature", "Features"), ("benefit", "Features"), ("service", "Features"),
    ("card", "CardGrid"), ("grid", "CardGrid"), ("product", "CardGrid"), ("gallery", "CardGrid"),
    ("testimonial", "Testimonials"), ("review", "Testimonials"), ("quote", "Testimonials"),
    ("pricing", "Pricing"), ("plan", "Pricing"), ("price", "Pricing"),
    ("faq", "Faq"), ("question", "Faq"), ("accordion", "Faq"),
    ("logo", "LogoCloud"), ("sponsor", "LogoCloud"), ("partner", "LogoCloud"), ("brand", "LogoCloud"),
    ("team", "Team"), ("member", "Team"),
    ("post", "PostList"), ("blog", "PostList"), ("article", "PostList"), ("news", "PostList"),
    ("stat", "Stats"), ("metric", "Stats"), ("counter", "Stats"),
    ("cta", "CallToAction"), ("signup", "CallToAction"), ("newsletter", "CallToAction"),
    ("contact", "ContactForm"),
]
SECTION_ORDER = ["Hero", "LogoCloud", "Features", "CardGrid", "Stats", "Testimonials", "Team",
                 "PostList", "Pricing", "Faq", "CallToAction", "ContactForm"]
PAGE_WORDS = {"about": "Sobre", "pricing": "Precios", "blog": "Blog", "docs": "Docs", "contact": "Contacto",
              "features": "Funciones", "team": "Equipo", "faq": "FAQ", "products": "Productos",
              "services": "Servicios", "guide": "Guía", "news": "Noticias", "careers": "Empleo"}


def latest(store: EvidenceStore, subject: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for ev in store.list_evidence(subject):
        out[ev["operation"]] = json.loads(ev["result"])
    return out


def _hex_to_rgb(c: str) -> tuple[int, int, int] | None:
    m = re.fullmatch(r"#([0-9a-f]{3,8})", c.lower())
    if not m:
        return None
    h = m.group(1)
    if len(h) in (3, 4):
        if len(h) == 4 and int(h[3] * 2, 16) < 200:   # casi transparente
            return None
        h = "".join(ch * 2 for ch in h[:3])
    elif len(h) == 8:
        if int(h[6:8], 16) < 200:      # muy transparente: no sirve de token
            return None
        h = h[:6]
    elif len(h) != 6:
        return None
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _sat_light(rgb: tuple[int, int, int]) -> tuple[float, float]:
    r, g, b = (x / 255 for x in rgb)
    mx, mn = max(r, g, b), min(r, g, b)
    light = (mx + mn) / 2
    sat = 0.0 if mx == mn else (mx - mn) / (1 - abs(2 * light - 1))
    return sat, light


def _luminance(rgb: tuple[int, int, int]) -> float:
    def ch(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    """Relación de contraste WCAG entre dos colores #rrggbb (1 a 21)."""
    la, lb = _luminance(_hex_to_rgb(a) or (0, 0, 0)), _luminance(_hex_to_rgb(b) or (0, 0, 0))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _mix(c: str, toward: tuple[int, int, int], t: float) -> str:
    r, g, b = _hex_to_rgb(c) or (0, 0, 0)
    return "#{:02x}{:02x}{:02x}".format(*(round(x + (y - x) * t) for x, y in zip((r, g, b), toward)))


def ensure_contrast(color: str, against: str, minimum: float) -> str:
    """Oscurece (o aclara, si el fondo es oscuro) el color lo justo para llegar al contraste mínimo
    (PLAN_MEJORAS A13): conserva el tono de la marca en lugar de cambiarlo por otro."""
    if contrast(color, against) >= minimum:
        return color
    toward = (0, 0, 0) if _luminance(_hex_to_rgb(against) or (255, 255, 255)) > 0.18 else (255, 255, 255)
    for i in range(1, 21):
        cand = _mix(color, toward, i / 20)
        if contrast(cand, against) >= minimum:
            return cand
    return "#000000" if toward == (0, 0, 0) else "#ffffff"


def on_color(bg: str) -> str:
    """Texto legible sobre «bg»: blanco o casi negro, el de más contraste (siempre ≥ 4,5:1)."""
    return "#ffffff" if contrast("#ffffff", bg) >= contrast("#111111", bg) else "#111111"


def palette(colors: list[str]) -> dict[str, str]:
    """Elige primario/acento/fondo/texto a partir de los colores observados y garantiza contraste AA:
    primario ≥ 4,5:1 sobre el fondo (se usa en enlaces), acento ≥ 3:1 (anillo de foco), texto ≥ 4,5:1
    y «on_primary» (texto de botones) por luminancia."""
    base = _palette_raw(colors)
    bg = base["background"]
    base["primary"] = ensure_contrast(base["primary"], bg, 4.5)
    base["accent"] = ensure_contrast(base["accent"], bg, 3.0)
    base["text"] = ensure_contrast(base["text"], bg, 7.0)
    base["muted"] = ensure_contrast(base["muted"], bg, 4.5)
    base["on_primary"] = on_color(base["primary"])
    return base


def _palette_raw(colors: list[str]) -> dict[str, str]:
    rgbs = [(c, _hex_to_rgb(c)) for c in colors]
    rgbs = [(c, x) for c, x in rgbs if x]
    vivid = [c for c, x in rgbs if _sat_light(x)[0] > 0.35 and 0.2 < _sat_light(x)[1] < 0.75]
    lights = [c for c, x in rgbs if _sat_light(x)[1] > 0.93]
    darks = [c for c, x in rgbs if _sat_light(x)[1] < 0.2]
    return {
        "primary": vivid[0] if vivid else "#4f46e5",
        "accent": vivid[1] if len(vivid) > 1 else "#f59e0b",
        "background": lights[0] if lights else "#ffffff",
        "surface": lights[1] if len(lights) > 1 else "#f6f7f9",
        "text": darks[0] if darks else "#1d232b",
        "muted": "#6b7480",
    }


def _sections_from(words: list[str]) -> list[str]:
    found: list[str] = []
    for w in words:
        lw = w.lower()
        for kw, sec in SECTION_KEYWORDS:
            if kw in lw and sec not in found:
                found.append(sec)
    return found


def _route_name(path: str) -> str | None:
    seg = path.strip("/").split("/")[0].split(".")[0].lower()
    if not seg or seg in ("index", "home", "assets", "static", "api", "cdn-cgi") or len(seg) > 30:
        return None
    if not re.fullmatch(r"[a-z][a-z0-9-]*", seg):
        return None
    return seg


_JS_RESERVED = {"await", "break", "case", "catch", "class", "const", "continue", "debugger", "default", "delete",
                "do", "else", "enum", "export", "extends", "false", "finally", "for", "function", "if", "implements",
                "import", "in", "instanceof", "interface", "let", "new", "null", "package", "private", "protected",
                "public", "return", "static", "super", "switch", "this", "throw", "true", "try", "typeof", "var",
                "void", "while", "with", "yield", "arguments", "eval"}
# Nombres que ya usan los proyectos generados (módulos, rutas o tablas propias).
_RESERVED_RESOURCES = {"auth", "app", "health", "static", "main", "store", "migrate", "migrations", "routers",
                       "models", "api", "test", "tests", "public", "src", "admin", "core", "config", "schema",
                       "schema_migrations", "sqlite_master", "index", "login", "register", "me", "users"}


def safe_title(name: str) -> str:
    """Título apto para interpolar en Python, JS/JSX, Vue, Svelte, Django y HTML: sin comillas, llaves,
    barras invertidas, < > ni $ (evita inyección de código y de plantillas)."""
    t = re.sub(r"[^\w .,:;!?()+-]", "", name or "", flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip(" .-")[:60]
    return t or "Nuevo proyecto"


def safe_resource(r: str) -> bool:
    import keyword
    ident = r.replace("-", "_")
    return (ident.isidentifier() and not keyword.iskeyword(ident) and not keyword.issoftkeyword(ident)
            and ident not in _JS_RESERVED and ident not in _RESERVED_RESOURCES)


def safe_font(f: str) -> str:
    """Familia tipográfica observada en CSS ajeno: solo letras, dígitos, espacios y guiones."""
    f = f.strip().strip("'\"")
    return f if re.fullmatch(r"[A-Za-z0-9 -]{1,40}", f) else ""


def build_spec(store: EvidenceStore, subjects: list[str], *, name: str = "nuevo-proyecto",
               target: str = "auto") -> dict[str, Any]:
    if not subjects:
        raise ValueError("hace falta al menos una fuente")
    votes: Counter = Counter()
    categories: dict[str, str] = {}
    sections: Counter = Counter()
    routes: Counter = Counter()
    colors: Counter = Counter()
    fonts: Counter = Counter()
    breakpoints: Counter = Counter()
    endpoints: Counter = Counter()
    methods: dict[str, list[str]] = {}       # métodos HTTP observados por ruta (repo_routes)
    features: set[str] = set()
    conventions = {"typescript": False, "tests": False, "ci": False, "docker": False, "lint": False}
    sources = []
    has_forms = False
    platforms: set[str] = set()

    for subj in subjects:
        ev = latest(store, subj)
        if not ev:
            raise ValueError(f"sin evidencias para {subj}: analízalo antes")
        kind = ("web" if "web_blueprint" in ev else "repo" if "repo_blueprint" in ev
                else "binary" if "hash" in ev else "otro")
        sources.append({"subject": subj, "kind": kind})
        if kind == "binary":
            # Tipo de app y sistema operativo según el propio binario o paquete analizado.
            fmt = str(ev.get("detect_format", {}).get("format", ""))
            console = False
            pkg = str(ev.get("archive_inventory", {}).get("kind", ""))
            if fmt == "pe":
                platforms.add("windows")
                console = ev.get("pe_headers", {}).get("subsystem") in ("windows_cui", "posix_cui")
            elif fmt == "elf":
                platforms.add("linux")
            elif fmt.startswith("macho"):
                platforms.add("macos")
            if pkg in ("apk", "xapk", "aar") or fmt == "dex":
                platforms.add("android")
            elif pkg == "ipa":
                platforms.add("ios")
            elif pkg == "jar":
                platforms.update({"windows", "macos", "linux"})   # Java de escritorio
            if platforms & {"android", "ios"}:
                votes["App móvil"] += 3
            elif fmt == "pe" and console:
                votes["App de consola"] += 3     # .exe de consola → herramienta de línea de comandos
            elif platforms & {"windows", "linux", "macos"}:
                votes["App de escritorio"] += 3
            for fw in ev.get("archive_inventory", {}).get("frameworks", []) or []:
                votes[str(fw)] += 1   # React Native, Flutter… (solo cuentan los que conoce _choose_target)
        for key in ("web_stack", "repo_stack"):
            for t in ev.get(key, {}).get("technologies", []):
                if key == "repo_stack" and not t.get("runtime", True) and t["category"] not in (
                        "testing", "bundler", "language", "css"):
                    continue
                votes[t["name"]] += 1
                categories[t["name"]] = t["category"]
        if kind == "web":
            bp, st = ev["web_blueprint"], ev.get("web_structure", {})
            words = list(bp.get("component_candidates", [])) + list(bp.get("page_skeleton", [])) + \
                list(st.get("top_classes", {}).keys())
            secs = _sections_from(words)
            if any(h.get("level") == 1 for h in st.get("headings", [])):
                secs.insert(0, "Hero")
            for s in secs:
                sections[s] += 1
            has_forms = has_forms or bool(st.get("forms"))
            for p in st.get("links", {}).get("internal_sample", []) + [
                    x["path"] for x in (st.get("pages") or [])] + ev.get("web_seo", {}).get("sitemap", {}).get("sample", []):
                r = _route_name(p)
                if r:
                    routes[r] += 1
            tok = bp.get("design_tokens", {})
            for i, c in enumerate(ev.get("web_css", {}).get("colors", [])):
                colors[c] += 20 - min(i, 19)
            for f in tok.get("fonts", []):
                fonts[f] += 1
            for b in tok.get("breakpoints", []):
                breakpoints[b] += 1
            js = ev.get("web_js", {})
            for e in js.get("api_endpoints", []):
                endpoints[e] += 1
            features |= {f for f in js.get("features", {}) if f in ("localStorage", "fetch", "WebSocket", "serviceWorker")}
            if js.get("minified_files"):
                conventions["typescript"] = conventions["typescript"] or "TypeScript" in votes
        elif kind == "repo":
            bp = ev["repo_blueprint"]
            conv = " ".join(bp.get("conventions", []))
            conventions["typescript"] |= "TypeScript" in conv
            conventions["tests"] |= "pruebas" in conv
            conventions["ci"] |= "CI" in conv
            conventions["docker"] |= "Docker" in conv
            conventions["lint"] |= any(x in conv for x in ("ESLint", "Biome", "Ruff", "Prettier"))
            for item in ev.get("repo_structure", {}).get("top_level", []):
                r = _route_name(item["path"])
                if r in PAGE_WORDS:
                    routes[r] += 1
            # Rutas reales del repositorio (Next.js): cada página cuenta como confirmada; la API, como endpoints.
            rr = ev.get("repo_routes", {})
            for page in rr.get("pages", []):
                r = _route_name(page)
                if r:
                    routes[r] += 2
            for a in rr.get("api", []):
                endpoints[a["path"]] += 1
                ms = [m for m in a.get("methods", []) if m != "?"]
                if ms:
                    methods[a["path"]] = sorted(set(methods.get(a["path"], [])) | set(ms))
        elif kind == "binary":
            imports = " ".join(ev.get("pe_imports", {}).get("dlls", {})).lower() + " ".join(
                ev.get("elf_dynamic", {}).get("needed", [])).lower()
            if any(x in imports for x in ("ws2_32", "winhttp", "wininet", "libcurl", "libssl")):
                features.add("network")
            if any(x in imports for x in ("user32", "gdi32", "libgtk", "libqt", "libx11")):
                features.add("gui")
            if any(x in imports for x in ("bcrypt", "crypt32", "libcrypto")):
                features.add("crypto")

    chosen = target if target != "auto" else _choose_target(votes, categories, endpoints)
    if chosen not in TARGETS:
        raise ValueError(f"target desconocido: {chosen} (opciones: {', '.join(TARGETS)})")
    secs = [s for s in SECTION_ORDER if s in sections]
    # Secciones que pone el generador sin evidencia en las fuentes: se anotan en «sections_added» (decisión del
    # titular, 2026-11-11) para distinguirlas de las observadas o inferidas (Hero desde un h1, ContactForm desde un
    # formulario).
    added: list[str] = []
    if "Hero" not in secs:
        secs.insert(0, "Hero")
        added.append("Hero")
    if not any(s in secs for s in ("Features", "CardGrid")):
        secs.insert(1, "Features")
        added.append("Features")
    if has_forms and "ContactForm" not in secs:
        secs.append("ContactForm")      # sale de un formulario observado: no se anota como añadida
    # Páginas reconocibles primero; otras solo si aparecen en varias fuentes/enlaces.
    known = [r for r, _ in routes.most_common() if r in PAGE_WORDS]
    other = [r for r, n in routes.most_common() if r not in PAGE_WORDS and n >= 2]
    pages = ["home"] + (known + other)[:5]
    resources = []
    for e, _ in endpoints.most_common(20):
        parts = [p for p in e.split("/") if p and not p.startswith(("{", ":")) and p not in ("api", "graphql")
                 and not re.fullmatch(r"v\d+", p)]
        if parts and re.fullmatch(r"[a-z][a-z0-9_-]{1,30}", parts[0]) and safe_resource(parts[0])                 and parts[0].replace("-", "_") not in [r.replace("-", "_") for r in resources]:
            resources.append(parts[0])
    if chosen in ("fastapi", "express") and not resources:
        resources = ["items"]
    return {
        "name": _slug(name),
        "title": safe_title(name),
        "target": chosen,
        "platforms": _platforms_for(chosen),              # dónde funcionará el proyecto nuevo
        "source_platforms": sorted(platforms),            # sistemas de las apps analizadas
        "sources": sources,
        "stack_votes": dict(votes.most_common(25)),
        "pages": pages,
        "sections": secs[:9],
        "sections_added": [x for x in added if x in secs[:9]],
        "design": {
            "palette": palette([c for c, _ in colors.most_common(40)]),
            "font": next((safe_font(f) for f, _ in fonts.most_common()
                          if f.lower() not in ("inherit", "initial") and safe_font(f)), "system-ui"),
            "breakpoints": _bps(breakpoints),
            "dark_mode": "localStorage" in features,
        },
        "api": {"resources": resources[:6], "observed_endpoints": [e for e, _ in endpoints.most_common(15)],
                "observed_methods": methods,
                "auth_endpoints": sorted(e for e in endpoints if re.match(r"^/api/auth/(login|logout|signin|signout|"
                                                                             r"session)$", e))},
        "features": sorted(features),
        "conventions": {**conventions, "tests": True},
        "notes": [
            "Código generado desde cero por Eolfi: ninguna línea procede de las fuentes analizadas.",
            "Los textos son de ejemplo: sustitúyelos por los tuyos.",
        ],
    }


def _choose_target(votes: Counter, cats: dict[str, str], endpoints: Counter) -> str:
    def score(*names: str) -> int:
        return sum(votes[n] for n in names)
    # Tipo de app según lo analizado: móvil (Android/iOS) o escritorio (Windows/macOS/Linux).
    mobile = score("React Native", "Expo", "Flutter", "Flutter Web", ".NET MAUI", "App móvil")
    desktop = score("Electron", "Tauri", "Qt", "wxPython", "Avalonia", "WPF", "Windows Forms", "GTK",
                    "App de escritorio")
    cli = score("Click", "Typer", "argparse CLI", "clap", "Cobra", "Commander.js", "yargs", "App de consola")
    if (mobile or desktop) and not score("Next.js", "Nuxt"):
        if mobile >= desktop:
            return "expo"
        # Rust/Tauri o apps nativas (Qt, WPF, Avalonia, GTK…) → escritorio nativo ligero (Tauri).
        dotnet = score("WPF", "Windows Forms", "Avalonia", ".NET MAUI")
        native = score("Tauri", "Qt", "GTK", "wxPython")
        if dotnet and dotnet >= max(native, score("Electron")):
            return "dotnet"          # apps .NET (WPF/WinForms/Avalonia) → C# nativo multiplataforma
        return "tauri" if native > score("Electron") else "desktop"
    if cli and not (score("React", "Vue", "Svelte", "Next.js", "Angular") or score("FastAPI", "Express", "Django")):
        return "cli"
    vue = score("Vue", "Nuxt", "VitePress")
    react = score("React", "Next.js", "Gatsby", "Remix / React Router", "Preact")
    svelte = score("Svelte", "SvelteKit")
    nxt = score("Next.js")
    py = score("FastAPI", "Flask", "Django")
    if votes["Django"] and votes["Django"] >= max(score("FastAPI", "Flask"), 1) and not (vue or react or svelte):
        return "django"
    node_be = score("Express", "Fastify", "NestJS", "Hono")
    frontend = vue + react + score("Svelte", "Angular", "Astro", "Tailwind CSS", "Vite")
    if frontend == 0 and (py or node_be):
        return "fastapi" if py >= node_be else "express"
    if svelte > max(vue, react):
        return "svelte"
    if vue > react:
        return "vue"
    if react:
        return "next" if nxt and (py or node_be or endpoints) else "react"
    if frontend or not (py or node_be):
        return "react" if score("Vite", "TypeScript", "webpack") else "static"
    return "fastapi"


def _platforms_for(target: str) -> list[str]:
    """Sistemas donde funciona el proyecto generado."""
    if target == "expo":
        return ["android", "ios", "web"]
    if target in ("desktop", "tauri", "cli", "dotnet"):
        return ["windows", "macos", "linux"]
    return ["web"]


def _bps(c: Counter) -> dict[str, int]:
    px = []
    for k in c:
        m = re.match(r"min-width:([\d.]+)(px|em|rem)", k)
        if m:
            v = float(m.group(1)) * (16 if m.group(2) != "px" else 1)
            if 320 <= v <= 1920:
                px.append(int(v))
    px = sorted(set(px))
    pick = lambda lo, hi, d: next((v for v in px if lo <= v <= hi), d)  # noqa: E731
    return {"sm": pick(480, 700, 640), "md": pick(701, 900, 768), "lg": pick(901, 1200, 1024), "xl": pick(1201, 1600, 1280)}


def _slug(s: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return out[:50] or "nuevo-proyecto"
