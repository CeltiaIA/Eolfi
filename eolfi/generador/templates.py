"""Bloques de construcción comunes a todos los generadores.

Cada sección (Hero, Features, Pricing…) se describe UNA vez como un árbol
neutro (El/T/Each) y tres renderizadores lo convierten en HTML estático,
JSX (React) o plantilla Vue. El contenido de ejemplo vive aparte, en datos,
para que el usuario lo cambie sin tocar componentes.
"""
from __future__ import annotations

import re

import html
import json
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Mini-DSL
# ---------------------------------------------------------------------------
@dataclass
class El:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[Any] = field(default_factory=list)


@dataclass
class T:
    """Texto desde los datos: 'title' (de la sección) o 'item.title' (del bucle)."""
    path: str


@dataclass
class Each:
    path: str          # lista dentro de los datos de la sección
    node: El


def E(tag: str, attrs: dict[str, str] | None = None, *children: Any) -> El:
    return El(tag, attrs or {}, list(children))


def C(cls: str) -> dict[str, str]:
    return {"class": cls}


SECTIONS: dict[str, El] = {
    "Hero": E("section", {"class": "hero", "id": "inicio"}, E("div", C("container hero-inner"),
        E("p", C("eyebrow"), T("eyebrow")), E("h1", {}, T("title")), E("p", C("lead"), T("subtitle")),
        E("div", C("hero-actions"),
          E("a", {"class": "btn btn-primary", "href": "#contacto"}, T("cta")),
          E("a", {"class": "btn btn-ghost", "href": "#funciones"}, T("secondary"))))),
    "LogoCloud": E("section", {"class": "logos", "aria-label": "Clientes"}, E("div", C("container"),
        E("p", C("muted center"), T("title")),
        E("ul", C("logo-row"), Each("items", E("li", C("logo"), T("item.name")))))),
    "Features": E("section", {"class": "features", "id": "funciones"}, E("div", C("container"),
        E("h2", {}, T("title")), E("p", C("section-lead"), T("subtitle")),
        E("div", C("grid grid-3"), Each("items", E("article", C("card feature"),
            E("span", {"class": "feature-icon", "aria-hidden": "true"}, T("item.icon")),
            E("h3", {}, T("item.title")), E("p", {}, T("item.text"))))))),
    "CardGrid": E("section", {"class": "cards", "id": "catalogo"}, E("div", C("container"),
        E("h2", {}, T("title")),
        E("div", C("grid grid-3"), Each("items", E("article", C("card"),
            E("div", {"class": "card-media", "aria-hidden": "true"}),
            E("h3", {}, T("item.title")), E("p", {}, T("item.text")),
            E("a", {"class": "link", "href": "#"}, T("item.link"))))))),
    "Stats": E("section", C("stats"), E("div", C("container grid grid-3"),
        Each("items", E("div", C("stat"), E("strong", {}, T("item.value")), E("span", {}, T("item.label")))))),
    "Testimonials": E("section", {"class": "testimonials", "id": "opiniones"}, E("div", C("container"),
        E("h2", {}, T("title")),
        E("div", C("grid grid-3"), Each("items", E("figure", C("card quote"),
            E("blockquote", {}, T("item.text")), E("figcaption", {}, T("item.author"))))))),
    "Team": E("section", {"class": "team", "id": "equipo"}, E("div", C("container"),
        E("h2", {}, T("title")),
        E("div", C("grid grid-4"), Each("items", E("article", C("card member"),
            E("div", {"class": "avatar", "aria-hidden": "true"}, T("item.initials")),
            E("h3", {}, T("item.name")), E("p", C("muted"), T("item.role"))))))),
    "PostList": E("section", {"class": "posts", "id": "blog"}, E("div", C("container"),
        E("h2", {}, T("title")),
        E("div", C("grid grid-3"), Each("items", E("article", C("card post"),
            E("p", C("muted small"), T("item.date")), E("h3", {}, T("item.title")),
            E("p", {}, T("item.excerpt"))))))),
    "Pricing": E("section", {"class": "pricing", "id": "precios"}, E("div", C("container"),
        E("h2", {}, T("title")),
        E("div", C("grid grid-3"), Each("items", E("article", C("card plan"),
            E("h3", {}, T("item.name")), E("p", C("price"), T("item.price")),
            E("p", C("muted"), T("item.text")),
            E("a", {"class": "btn btn-primary", "href": "#contacto"}, T("item.cta"))))))),
    "Faq": E("section", {"class": "faq", "id": "faq"}, E("div", C("container narrow"),
        E("h2", {}, T("title")),
        Each("items", E("details", C("faq-item"), E("summary", {}, T("item.q")), E("p", {}, T("item.a")))))),
    "CallToAction": E("section", C("cta"), E("div", C("container cta-inner"),
        E("h2", {}, T("title")), E("p", {}, T("text")),
        E("a", {"class": "btn btn-light", "href": "#contacto"}, T("button")))),
    "ContactForm": E("section", {"class": "contact", "id": "contacto"}, E("div", C("container narrow"),
        E("h2", {}, T("title")), E("p", C("section-lead"), T("subtitle")),
        E("form", {"class": "contact-form", "data-contact": "", "@submit": "contact"},
          E("label", {}, T("name_label"), E("input", {"name": "name", "required": "", "autocomplete": "name"})),
          E("label", {}, T("email_label"), E("input", {"name": "email", "type": "email", "required": "",
                                                       "autocomplete": "email"})),
          E("label", {}, T("message_label"), E("textarea", {"name": "message", "rows": "4", "required": ""})),
          E("button", {"class": "btn btn-primary", "type": "submit"}, T("button"))))),
}


def content_for(spec: dict[str, Any]) -> dict[str, Any]:
    """Textos de ejemplo (genéricos, nuevos) para cada sección."""
    t = spec["title"]
    return {
        "Hero": {"eyebrow": "Nuevo", "title": t, "subtitle": "Una base moderna, accesible y rápida "
                 "para empezar tu proyecto. Cambia estos textos por los tuyos.", "cta": "Empezar",
                 "secondary": "Ver funciones"},
        "LogoCloud": {"title": "Confían en nosotros", "items": [{"name": f"Marca {c}"} for c in "ABCDE"]},
        "Features": {"title": "Funciones", "subtitle": "Todo lo necesario, nada de sobra.", "items": [
            {"icon": "⚡", "title": "Rápido", "text": "Carga en milisegundos y funciona sin conexión lenta."},
            {"icon": "♿", "title": "Accesible", "text": "Semántica correcta, foco visible y contraste suficiente."},
            {"icon": "🧩", "title": "Modular", "text": "Secciones independientes que puedes reordenar."}]},
        "CardGrid": {"title": "Catálogo", "items": [
            {"title": f"Elemento {i}", "text": "Descripción breve del elemento.", "link": "Ver más"} for i in range(1, 7)]},
        "Stats": {"items": [{"value": "99,9 %", "label": "disponibilidad"}, {"value": "< 1 s", "label": "tiempo de carga"},
                            {"value": "24/7", "label": "soporte"}]},
        "Testimonials": {"title": "Opiniones", "items": [
            {"text": "Lo pusimos en marcha en una tarde.", "author": "Ana, diseñadora"},
            {"text": "Claro, rápido y fácil de mantener.", "author": "Luis, desarrollador"},
            {"text": "Justo lo que necesitábamos para empezar.", "author": "Marta, producto"}]},
        "Team": {"title": "Equipo", "items": [
            {"initials": n[:2].upper(), "name": n, "role": r} for n, r in
            (("Alex", "Dirección"), ("Sam", "Diseño"), ("Robin", "Ingeniería"), ("Kim", "Soporte"))]},
        "PostList": {"title": "Últimas entradas", "items": [
            {"date": f"2026-0{i}-15", "title": f"Entrada de ejemplo {i}", "excerpt": "Resumen corto de la entrada."}
            for i in range(1, 4)]},
        "Pricing": {"title": "Precios", "items": [
            {"name": "Básico", "price": "0 €", "text": "Para probar.", "cta": "Empezar"},
            {"name": "Pro", "price": "12 €/mes", "text": "Para equipos pequeños.", "cta": "Elegir Pro"},
            {"name": "Empresa", "price": "A medida", "text": "Para organizaciones.", "cta": "Contactar"}]},
        "Faq": {"title": "Preguntas frecuentes", "items": [
            {"q": "¿Puedo cambiar los textos?", "a": "Sí: están todos en el archivo de contenido."},
            {"q": "¿Funciona en móvil?", "a": "Sí, el diseño es adaptable."},
            {"q": "¿Cómo lo despliego?", "a": "Sigue los pasos del README."}]},
        "CallToAction": {"title": "¿Empezamos?", "text": "Crea tu primera versión hoy mismo.", "button": "Hablemos"},
        "ContactForm": {"title": "Contacto", "subtitle": "Escríbenos y te respondemos pronto.",
                        "name_label": "Nombre", "email_label": "Correo", "message_label": "Mensaje",
                        "button": "Enviar", "thanks": "Formulario de ejemplo: el mensaje aún no se envía a ningún sitio (conéctalo a tu servidor)."},
    }


# ---------------------------------------------------------------------------
# Renderizadores
# ---------------------------------------------------------------------------
VOID = {"input", "img", "br", "hr", "meta", "link"}


def _lookup(data: dict[str, Any], item: dict[str, Any] | None, path: str) -> Any:
    if path.startswith("item."):
        return (item or {}).get(path[5:], "")
    return data.get(path, "")


def render_html(node: Any, data: dict[str, Any], item: dict[str, Any] | None = None, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(node, T):
        return html.escape(str(_lookup(data, item, node.path)))
    if isinstance(node, Each):
        return "\n".join(render_html(node.node, data, it, indent) for it in data.get(node.path, []))
    attrs = "".join(f' {k}' if v == "" else f' {k}="{html.escape(v)}"' for k, v in node.attrs.items()
                    if not k.startswith("@"))
    if node.tag in VOID:
        return f"{pad}<{node.tag}{attrs}>"
    inner = [render_html(c, data, item, indent + 1) for c in node.children]
    if all(isinstance(c, T) for c in node.children):
        return f"{pad}<{node.tag}{attrs}>{''.join(inner)}</{node.tag}>"
    body = "\n".join(x if x.startswith(" ") or x.startswith("<") else "  " * (indent + 1) + x for x in inner)
    return f"{pad}<{node.tag}{attrs}>\n{body}\n{pad}</{node.tag}>"



def _attr_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_:][-A-Za-z0-9_:.]*", name):
        raise ValueError(f"nombre de atributo no válido: {name!r}")
    return name


def _attr_value(v: Any, braces: bool = False) -> str:
    """Valor de atributo escapado (hoy son literales internos; mañana podrían no serlo).
    En Svelte, {…} dentro de comillas se interpreta: se escapa también."""
    out = html.escape(str(v), quote=True)
    return out.replace("{", "&#123;").replace("}", "&#125;") if braces else out

def render_jsx(node: Any, indent: int = 2, var: str = "data") -> str:
    pad = "  " * indent
    if isinstance(node, T):
        return "{" + (node.path if node.path.startswith("item.") else f"{var}.{node.path}") + "}"
    if isinstance(node, Each):
        inner = render_jsx(node.node, indent + 1, var)
        inner = inner.replace(f"<{node.node.tag}", f"<{node.node.tag} key={{i}}", 1)
        return f"{pad}{{{var}.{node.path}.map((item, i) => (\n{inner}\n{pad}))}}"
    attrs = []
    for k, v in node.attrs.items():
        if k == "@submit":
            attrs.append("onSubmit={onSubmit}")
            continue
        name = {"class": "className", "for": "htmlFor", "autocomplete": "autoComplete"}.get(k, k)
        if k == "rows":
            attrs.append(f"{name}={{{v}}}")
        elif v == "":
            attrs.append(name)
        else:
            attrs.append(f'{_attr_name(name)}="{_attr_value(v)}"')
    a = (" " + " ".join(attrs)) if attrs else ""
    if node.tag in VOID or not node.children:
        return f"{pad}<{node.tag}{a} />"
    if all(isinstance(c, T) for c in node.children):
        return f"{pad}<{node.tag}{a}>{''.join(render_jsx(c, 0, var) for c in node.children)}</{node.tag}>"
    inner = "\n".join(render_jsx(c, indent + 1, var) if not isinstance(c, T) else "  " * (indent + 1) + render_jsx(c, 0, var)
                      for c in node.children)
    return f"{pad}<{node.tag}{a}>\n{inner}\n{pad}</{node.tag}>"


def render_vue(node: Any, indent: int = 1, loop: bool = False) -> str:
    pad = "  " * indent
    if isinstance(node, T):
        return "{{ " + (node.path if node.path.startswith("item.") else f"data.{node.path}") + " }}"
    if isinstance(node, Each):
        el = El(node.node.tag, {**node.node.attrs, "v-for": f"(item, i) in data.{node.path}", ":key": "i"},
                node.node.children)
        return render_vue(el, indent, True)
    attrs = []
    for k, v in node.attrs.items():
        if k == "@submit":
            attrs.append('@submit.prevent="onSubmit"')
        elif v == "":
            attrs.append(k)
        elif k.startswith((":", "@", "v-")):
            attrs.append(f'{k}="{v}"')            # directiva: expresión interna de la plantilla
        else:
            attrs.append(f'{_attr_name(k)}="{_attr_value(v)}"')
    a = (" " + " ".join(attrs)) if attrs else ""
    if node.tag in VOID:
        return f"{pad}<{node.tag}{a} />"
    if not node.children:
        return f"{pad}<{node.tag}{a}></{node.tag}>"
    if all(isinstance(c, T) for c in node.children):
        return f"{pad}<{node.tag}{a}>{''.join(render_vue(c) for c in node.children)}</{node.tag}>"
    inner = "\n".join(render_vue(c, indent + 1) if not isinstance(c, T) else "  " * (indent + 1) + render_vue(c)
                      for c in node.children)
    return f"{pad}<{node.tag}{a}>\n{inner}\n{pad}</{node.tag}>"


def has_form(node: Any) -> bool:
    if isinstance(node, Each):
        return has_form(node.node)
    if isinstance(node, El):
        return "@submit" in node.attrs or any(has_form(c) for c in node.children)
    return False


# ---------------------------------------------------------------------------
# Estilos (mismos para todos los destinos)
# ---------------------------------------------------------------------------
def tokens_css(spec: dict[str, Any]) -> str:
    p = spec["design"]["palette"]
    font = spec["design"]["font"]
    font_stack = (f'"{font}", ' if font and font != "system-ui" else "") + \
        'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'
    bp = spec["design"]["breakpoints"]
    return f"""/* Tokens de diseño generados por Eolfi a partir de los colores, fuentes y
   puntos de corte observados en las fuentes. Ajústalos a tu marca. */
:root {{
  --color-primary: {p['primary']};
  --color-accent: {p['accent']};
  --color-on-primary: {p.get('on_primary', '#ffffff')};
  --color-bg: {p['background']};
  --color-surface: {p['surface']};
  --color-text: {p['text']};
  --color-muted: {p['muted']};
  --font-sans: {font_stack};
  --radius: 12px;
  --shadow: 0 1px 2px rgb(0 0 0 / 6%), 0 8px 24px rgb(0 0 0 / 6%);
  --container: 1120px;
  /* puntos de corte (en las media queries van como valor literal) */
  --bp-sm: {bp['sm']}px;
  --bp-md: {bp['md']}px;
  --bp-lg: {bp['lg']}px;
}}

:root[data-theme="dark"] {{
  --color-bg: #12141a;
  --color-surface: #1b1e26;
  --color-text: #e8eaf0;
  --color-muted: #a0a7b4;
}}
"""


def base_css(spec: dict[str, Any]) -> str:
    md = spec["design"]["breakpoints"]["md"]
    lg = spec["design"]["breakpoints"]["lg"]
    return f"""*, *::before, *::after {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{ margin: 0; font-family: var(--font-sans); color: var(--color-text); background: var(--color-bg);
  line-height: 1.6; -webkit-font-smoothing: antialiased; }}
img {{ max-width: 100%; display: block; }}
a {{ color: var(--color-primary); }}
:focus-visible {{ outline: 3px solid var(--color-accent); outline-offset: 2px; }}
.container {{ width: min(100% - 2rem, var(--container)); margin-inline: auto; }}
.narrow {{ max-width: 720px; }}
.muted {{ color: var(--color-muted); }} .small {{ font-size: .875rem; }} .center {{ text-align: center; }}
section {{ padding: 4.5rem 0; }}
h1, h2, h3 {{ line-height: 1.2; margin: 0 0 .75rem; }}
h1 {{ font-size: clamp(2.2rem, 5vw, 3.6rem); letter-spacing: -.02em; }}
h2 {{ font-size: clamp(1.6rem, 3vw, 2.3rem); }}
.section-lead, .lead {{ color: var(--color-muted); font-size: 1.125rem; max-width: 60ch; }}

/* Cabecera y pie */
.site-header {{ position: sticky; top: 0; z-index: 10; background: color-mix(in srgb, var(--color-bg) 88%, transparent);
  backdrop-filter: blur(8px); border-bottom: 1px solid color-mix(in srgb, var(--color-text) 10%, transparent); }}
.site-header .container {{ display: flex; align-items: center; gap: 1rem; min-height: 64px; }}
.brand {{ font-weight: 700; text-decoration: none; color: var(--color-text); font-size: 1.1rem; }}
.site-header a {{ text-decoration: none; }}
.site-nav {{ margin-left: auto; display: flex; gap: 1.25rem; align-items: center; }}
.site-nav a {{ text-decoration: none; color: var(--color-text); opacity: .8; }}
.site-nav a:hover, .site-nav a.active, .site-nav a[aria-current="page"] {{ opacity: 1; color: var(--color-primary); }}
.skip-link {{ position: absolute; left: -9999px; top: 0; padding: .5rem 1rem; background: var(--color-primary);
  color: var(--color-on-primary, #fff); z-index: 100; }}
.skip-link:focus {{ left: 1rem; top: 1rem; }}
.theme-toggle {{ background: none; border: 1px solid color-mix(in srgb, var(--color-text) 20%, transparent);
  border-radius: 999px; padding: .3rem .7rem; color: var(--color-text); cursor: pointer; }}
.site-footer {{ padding: 2.5rem 0; color: var(--color-muted); border-top: 1px solid color-mix(in srgb, var(--color-text) 10%, transparent); }}

/* Botones */
.btn {{ display: inline-block; padding: .75rem 1.25rem; border-radius: 999px; font-weight: 600; text-decoration: none;
  border: 2px solid transparent; cursor: pointer; font: inherit; }}
.btn-primary {{ background: var(--color-primary); color: var(--color-on-primary); }}
.btn-primary:hover {{ filter: brightness(1.08); }}
.btn-ghost {{ border-color: currentColor; color: var(--color-text); }}
.btn-light {{ background: #fff; color: var(--color-primary); }}

/* Secciones */
.hero {{ padding: 6rem 0 5rem; background: radial-gradient(1200px 400px at 10% -10%,
  color-mix(in srgb, var(--color-primary) 18%, transparent), transparent); }}
.eyebrow {{ display: inline-block; font-weight: 600; color: var(--color-primary); background:
  color-mix(in srgb, var(--color-primary) 12%, transparent); padding: .2rem .7rem; border-radius: 999px; }}
.hero-actions {{ display: flex; gap: .75rem; flex-wrap: wrap; margin-top: 1.5rem; }}
.grid {{ display: grid; gap: 1.25rem; margin-top: 2rem; }}
.card {{ background: var(--color-surface); border-radius: var(--radius); padding: 1.5rem; box-shadow: var(--shadow); }}
.card-media {{ aspect-ratio: 16 / 9; border-radius: calc(var(--radius) - 4px); margin-bottom: 1rem;
  background: linear-gradient(135deg, var(--color-primary), var(--color-accent)); opacity: .85; }}
.feature-icon {{ font-size: 1.6rem; }}
.logos {{ padding: 2rem 0; }}
.logo-row {{ list-style: none; padding: 0; margin: 1rem 0 0; display: flex; flex-wrap: wrap; justify-content: center; gap: 2.5rem; }}
.logo {{ font-weight: 700; color: var(--color-muted); letter-spacing: .05em; }}
.stats {{ background: var(--color-surface); }}
.stat {{ text-align: center; }} .stat strong {{ display: block; font-size: 2.2rem; color: var(--color-primary); }}
.quote blockquote {{ margin: 0 0 1rem; font-size: 1.05rem; }}
.quote figcaption {{ color: var(--color-muted); }}
.avatar {{ width: 56px; height: 56px; border-radius: 50%; display: grid; place-items: center; font-weight: 700;
  color: var(--color-on-primary); background: var(--color-primary); margin-bottom: .75rem; }}
.price {{ font-size: 1.8rem; font-weight: 700; margin: .25rem 0; }}
.plan .btn {{ margin-top: 1rem; }}
.faq-item {{ border-bottom: 1px solid color-mix(in srgb, var(--color-text) 12%, transparent); padding: 1rem 0; }}
.faq-item summary {{ cursor: pointer; font-weight: 600; }}
.cta {{ background: var(--color-primary); color: var(--color-on-primary); text-align: center; }}
.cta-inner p {{ opacity: .9; }}
.contact-form {{ display: grid; gap: 1rem; margin-top: 1.5rem; }}
.contact-form label {{ display: grid; gap: .35rem; font-weight: 600; }}
.contact-form input, .contact-form textarea {{ font: inherit; padding: .7rem .85rem; border-radius: 8px;
  border: 1px solid color-mix(in srgb, var(--color-text) 20%, transparent); background: var(--color-bg); color: var(--color-text); }}
.form-status {{ color: var(--color-primary); font-weight: 600; }}
.resource-list {{ list-style: none; padding: 0; display: grid; gap: .5rem; }}
.resource-list li {{ background: var(--color-surface); padding: .75rem 1rem; border-radius: 8px; }}
.page-header {{ padding: 4rem 0 1rem; }}

@media (min-width: {md}px) {{ .grid-3 {{ grid-template-columns: repeat(3, 1fr); }} .grid-4 {{ grid-template-columns: repeat(2, 1fr); }} }}
@media (min-width: {lg}px) {{ .grid-4 {{ grid-template-columns: repeat(4, 1fr); }} }}
@media (max-width: {md - 1}px) {{ .site-nav {{ gap: .75rem; font-size: .95rem; }} .site-nav .nav-extra {{ display: none; }} }}
@media (prefers-reduced-motion: reduce) {{ html {{ scroll-behavior: auto; }} }}
"""


def page_title(slug: str) -> str:
    from eolfi.generador.spec import PAGE_WORDS
    return PAGE_WORDS.get(slug, slug.replace("-", " ").capitalize())


def js_string(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def render_svelte(node: Any, indent: int = 0) -> str:
    """Svelte 5: {expr}, {#each}, onsubmit={...}."""
    pad = "  " * indent
    if isinstance(node, T):
        return "{" + (node.path if node.path.startswith("item.") else f"data.{node.path}") + "}"
    if isinstance(node, Each):
        inner = render_svelte(node.node, indent + 1)
        return f"{pad}{{#each data.{node.path} as item, i (i)}}\n{inner}\n{pad}{{/each}}"
    attrs = []
    for k, v in node.attrs.items():
        if k == "@submit":
            attrs.append("onsubmit={onSubmit}")
        elif v == "":
            attrs.append(k)
        else:
            attrs.append(f'{_attr_name(k)}="{_attr_value(v, braces=True)}"')
    a = (" " + " ".join(attrs)) if attrs else ""
    if node.tag in VOID:
        return f"{pad}<{node.tag}{a} />"
    if not node.children:
        return f"{pad}<{node.tag}{a}></{node.tag}>"
    if all(isinstance(c, T) for c in node.children):
        return f"{pad}<{node.tag}{a}>{''.join(render_svelte(c) for c in node.children)}</{node.tag}>"
    inner = "\n".join(render_svelte(c, indent + 1) if not isinstance(c, T) else "  " * (indent + 1) + render_svelte(c)
                      for c in node.children)
    return f"{pad}<{node.tag}{a}>\n{inner}\n{pad}</{node.tag}>"


def render_django(node: Any, indent: int = 0) -> str:
    """Plantillas Django: {{ var }} (autoescapado), {% for %}."""
    pad = "  " * indent
    if isinstance(node, T):
        return "{{ " + (node.path if node.path.startswith("item.") else f"data.{node.path}") + " }}"
    if isinstance(node, Each):
        inner = render_django(node.node, indent + 1)
        return f"{pad}{{% for item in data.{node.path} %}}\n{inner}\n{pad}{{% endfor %}}"
    attrs = "".join(f" {k}" if v == "" else f' {k}="{v}"' for k, v in node.attrs.items() if not k.startswith("@"))
    if node.tag in VOID:
        return f"{pad}<{node.tag}{attrs}>"
    if all(isinstance(c, T) for c in node.children):
        return f"{pad}<{node.tag}{attrs}>{''.join(render_django(c) for c in node.children)}</{node.tag}>"
    inner = "\n".join(render_django(c, indent + 1) if not isinstance(c, T) else "  " * (indent + 1) + render_django(c)
                      for c in node.children)
    return f"{pad}<{node.tag}{attrs}>\n{inner}\n{pad}</{node.tag}>"
