"""Análisis de páginas web para aprender cómo están construidas.

Fuente: una URL http(s), un archivo .html local o una carpeta de sitio
estático. Produce evidencias de estructura, assets, CSS, JS, source maps,
cabeceras, accesibilidad, SEO y pila tecnológica, más un *plano* (blueprint)
con lo necesario para construir algo parecido: comando de arranque,
esqueleto de página, tokens de diseño y componentes repetidos.

Principios:
- Todo lo descargado es DATO: nunca se ejecuta ni se interpreta como orden.
- Se guarda la ESTRUCTURA, no el contenido: de los source maps solo se
  registran rutas de archivos, nunca el código original; del texto, solo
  títulos y encabezados.
- Solo recursos del mismo origen por defecto; robots.txt respetado.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from eolfi.sites import stack
from eolfi.sites.fetch import Fetcher, FetchError, Response

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
        "source", "track", "wbr"}
LANDMARKS = ("header", "nav", "main", "footer", "aside", "section", "article", "form", "dialog")
MAX_OUTLINE_NODES = 600
MAX_INLINE = 400_000
SECURITY_HEADERS = {
    "content-security-policy": "CSP",
    "strict-transport-security": "HSTS",
    "x-frame-options": "X-Frame-Options",
    "x-content-type-options": "X-Content-Type-Options",
    "referrer-policy": "Referrer-Policy",
    "permissions-policy": "Permissions-Policy",
    "cross-origin-opener-policy": "COOP",
}


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.doctype: str | None = None
        self.lang: str | None = None
        self.title = ""
        self.metas: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.scripts: list[dict[str, Any]] = []
        self.inline_scripts: list[str] = []
        self.inline_styles: list[str] = []
        self.style_attrs = 0
        self.headings: list[tuple[int, str]] = []
        self.forms: list[dict[str, Any]] = []
        self.images: list[dict[str, Any]] = []
        self.iframes: list[str] = []
        self.anchors: list[str] = []
        self.tags: Counter = Counter()
        self.classes: Counter = Counter()
        self.data_attrs: Counter = Counter()
        self.custom_elements: Counter = Counter()
        self.blocks: Counter = Counter()
        self.label_for: set[str] = set()
        self.inputs: list[dict[str, Any]] = []
        self.buttons_without_text = 0
        self.aria = 0
        self.jsonld: list[str] = []
        self.stack: list[dict[str, Any]] = []
        self.root: dict[str, Any] = {"tag": "#document", "children": []}
        self.nodes = 1
        self.in_head = False
        self._capture: list[dict[str, Any]] = []   # elementos cuyo texto se acumula

    # -- árbol -------------------------------------------------------------
    def _parent(self) -> dict[str, Any]:
        return self.stack[-1]["node"] if self.stack else self.root

    def handle_decl(self, decl: str) -> None:
        if decl.lower().startswith("doctype"):
            self.doctype = decl[7:].strip() or "html"

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs_list}
        self.tags[tag] += 1
        cls = a.get("class", "").split()
        for c in cls:
            self.classes[c] += 1
        for k in a:
            if k.startswith("data-"):
                self.data_attrs[re.sub(r"-[0-9a-f]{6,}$", "-*", k)] += 1
            elif k.startswith("aria-") or k == "role":
                self.aria += 1
        if "-" in tag:
            self.custom_elements[tag] += 1
        if "style" in a:
            self.style_attrs += 1
        if cls and tag not in VOID:
            self.blocks[f"{tag}.{cls[0]}"] += 1

        if tag == "html":
            self.lang = a.get("lang") or None
        elif tag == "head":
            self.in_head = True
        elif tag == "body":
            self.in_head = False
        elif tag == "meta":
            self.metas.append({k: a[k] for k in ("name", "property", "content", "charset", "http-equiv") if k in a})
        elif tag == "link":
            self.links.append({"rel": a.get("rel", "").lower(), "href": a.get("href", ""), "as": a.get("as", ""),
                               "type": a.get("type", ""), "media": a.get("media", "")})
        elif tag == "script":
            self.scripts.append({"src": a.get("src"), "type": a.get("type", ""), "async": "async" in a,
                                 "defer": "defer" in a, "module": a.get("type") == "module",
                                 "in_head": self.in_head, "inline_len": 0})
        elif tag == "img":
            self.images.append({"src": a.get("src", "")[:300], "alt": a.get("alt"), "loading": a.get("loading"),
                                "srcset": bool(a.get("srcset")), "width": "width" in a})
        elif tag == "iframe":
            self.iframes.append(a.get("src", "")[:300])
        elif tag == "a" and "href" in a:
            self.anchors.append(a["href"][:500])
        elif tag == "form":
            self.forms.append({"action": a.get("action", "")[:200], "method": (a.get("method") or "get").lower(),
                               "fields": []})
        elif tag in ("input", "select", "textarea"):
            typ = a.get("type", "text").lower() if tag == "input" else tag
            field_ = {"type": typ, "id": a.get("id"), "aria_label": bool(a.get("aria-label") or a.get("aria-labelledby")),
                      "in_label": any(c["tag"] == "label" for c in self._capture)}
            if typ not in ("hidden", "submit", "button", "reset", "image"):
                self.inputs.append(field_)
            if self.forms:
                self.forms[-1]["fields"].append(typ)
        elif tag == "label" and a.get("for"):
            self.label_for.add(a["for"])

        if tag in ("title", "h1", "h2", "h3", "h4", "h5", "h6", "button", "label") or (
                tag == "script" and a.get("type") == "application/ld+json"):
            self._open_capture({"tag": tag, "text": [], "n": 0, "aria": bool(a.get("aria-label")), "attrs": a})
        if tag == "script" and not a.get("src") and a.get("type") != "application/ld+json":
            self._open_capture({"tag": "#script", "text": [], "n": 0, "aria": False, "attrs": a})
        if tag == "style":
            self._open_capture({"tag": "#style", "text": [], "n": 0, "aria": False, "attrs": a})

        if tag in VOID:
            self._add_node(tag, a, push=False)
        else:
            self._add_node(tag, a, push=True)

    def _open_capture(self, c: dict[str, Any]) -> None:
        """Como mucho MAX_OPEN_CAPTURES abiertas: miles de <button> o <label> sin cerrar no pueden
        hacer cuadrático cada fragmento de texto (DoS). Las más antiguas se cierran tal cual."""
        if len(self._capture) >= MAX_OPEN_CAPTURES:
            self._close_capture(self._capture.pop(0))
        self._capture.append(c)

    def _add_node(self, tag: str, a: dict[str, str], push: bool) -> None:
        node = None
        depth = len(self.stack)
        if self.nodes < MAX_OUTLINE_NODES and depth < 14 and tag not in ("script", "style", "meta", "link", "br", "wbr"):
            parent = self._parent()
            if parent is not None and len(parent.get("children", [])) < 15:
                node = {"tag": tag}
                if a.get("id"):
                    node["id"] = a["id"][:40]
                if a.get("class"):
                    node["class"] = " ".join(a["class"].split()[:3])[:60]
                if tag in LANDMARKS or a.get("role"):
                    node["landmark"] = a.get("role") or tag
                node["children"] = []
                parent.setdefault("children", []).append(node)
                self.nodes += 1
        if push and len(self.stack) < MAX_STACK:
            self.stack.append({"tag": tag, "node": node if node is not None else None})
            if node is None:
                # Sin nodo propio: los hijos cuelgan del ancestro con nodo (o se descartan si ya no caben).
                self.stack[-1]["node"] = self._parent_of_stack()

    def _parent_of_stack(self) -> dict[str, Any] | None:
        # Cada entrada de la pila ya guarda su nodo o el de su ancestro: basta con mirar la anterior
        # (recorrer toda la pila era cuadrático con miles de etiquetas sin cerrar).
        return self.stack[-2]["node"] if len(self.stack) > 1 and self.stack[-2]["node"] is not None else self.root

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self.in_head = False
        # cerrar capturas
        cap_tag = "#script" if tag == "script" else "#style" if tag == "style" else tag
        for i in range(len(self._capture) - 1, -1, -1):
            if self._capture[i]["tag"] == cap_tag or (tag == "script" and self._capture[i]["tag"] == "script"):
                c = self._capture.pop(i)
                self._close_capture(c)
                break
        # cerrar en la pila (tolerante a HTML mal formado)
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data: str) -> None:
        for c in self._capture:
            if c["n"] < (MAX_INLINE if c["tag"].startswith("#") or c["tag"] == "script" else 400):
                c["text"].append(data)
                c["n"] += len(data)

    def _close_capture(self, c: dict[str, Any]) -> None:
        text = "".join(c["text"])
        t = c["tag"]
        clean = re.sub(r"\s+", " ", text).strip()
        if t == "title":
            self.title = clean[:200]
        elif t.startswith("h") and len(t) == 2:
            self.headings.append((int(t[1]), clean[:120]))
        elif t == "button":
            if not clean and not c["aria"]:
                self.buttons_without_text += 1
        elif t == "script":
            self.jsonld.append(text[:50_000])
        elif t == "#script":
            if self.scripts:
                self.scripts[-1]["inline_len"] = len(text)
            if sum(len(s) for s in self.inline_scripts) < MAX_INLINE:
                self.inline_scripts.append(text)
        elif t == "#style":
            self.inline_styles.append(text)

    def outline(self) -> dict[str, Any]:
        def prune(n: dict[str, Any]) -> dict[str, Any]:
            out = {k: v for k, v in n.items() if k != "children"}
            ch = [prune(c) for c in n.get("children", [])]
            if ch:
                out["children"] = ch
            return out
        return prune(self.root)


# ---------------------------------------------------------------------------
# CSS y JS
# ---------------------------------------------------------------------------
_COLOR = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b|(?:rgba?|hsla?|oklch|oklab|lab|lch)\([^)]{3,60}\)")
_MEDIA = re.compile(r"@media([^{]{1,200})\{")
_BP = re.compile(r"(min|max)-width\s*:\s*([\d.]+)(px|em|rem)")
_BP_RANGE = re.compile(r"width\s*(>=|<=|>|<)\s*([\d.]+)(px|em|rem)")
# (?<![\w-]): solo empieza en un límite; antes, 2 MB de «-» tardaban ~6 s (PLAN_MEJORAS A16).
_VAR_DEF = re.compile(r"(?<![\w-])(--[\w-]{1,60})\s*:")
_FONT = re.compile(r"font-family\s*:\s*([^;}{]{1,200})")
_KEYFRAMES = re.compile(r"@keyframes\s+([\w-]+)")
_IMPORT = re.compile(r"@import\s+(?:url\()?['\"]?([^'\")\s;]+)")
_SMAP = re.compile(r"[#@]\s*sourceMappingURL\s*=\s*(\S+)")


MAX_CSS_CHARS = 5 * 1024 * 1024
MAX_OPEN_CAPTURES = 32
MAX_STACK = 512   # HTML con miles de etiquetas sin cerrar: más allá no se anida


def strip_css_comments(css: str) -> str:
    """Lineal: el regex no codicioso de comentarios es cuadrático con muchos '/*' sin cerrar."""
    out, i = [], 0
    while True:
        j = css.find("/*", i)
        if j < 0:
            out.append(css[i:])
            break
        out.append(css[i:j])
        k = css.find("*/", j + 2)
        if k < 0:
            break          # comentario sin cerrar: el resto es comentario
        i = k + 2
    return "".join(out)


def analyze_css(files: list[tuple[str, str]]) -> dict[str, Any]:
    colors, bps, varsdef, fonts, kfs = Counter(), Counter(), Counter(), Counter(), Counter()
    rules = grid = flex = imports = font_faces = 0
    maps = []
    total = 0
    for src, css in files:
        total += len(css)
        css = css[:MAX_CSS_CHARS]
        body = strip_css_comments(css)
        rules += body.count("{")
        for m in _MEDIA.finditer(body):
            for kind, val, unit in _BP.findall(m.group(1)):
                bps[f"{kind}-width:{float(val):g}{unit}"] += 1
            for op, val, unit in _BP_RANGE.findall(m.group(1)):
                bps[f"{'min' if '>' in op else 'max'}-width:{float(val):g}{unit}"] += 1
        for m in _COLOR.finditer(body):
            colors[m.group(0).lower().replace(" ", "")] += 1
        for m in _VAR_DEF.finditer(body):
            varsdef[m.group(1)] += 1
        for m in _FONT.finditer(body):
            first = m.group(1).split(",")[0].strip().strip("'\"")
            if first and not first.startswith("var("):
                fonts[first] += 1
        for m in _KEYFRAMES.finditer(body):
            kfs[m.group(1)] += 1
        grid += len(re.findall(r"display\s*:\s*(?:inline-)?grid", body))
        flex += len(re.findall(r"display\s*:\s*(?:inline-)?flex", body))
        imports += len(_IMPORT.findall(body))
        font_faces += body.count("@font-face")
        sm = _SMAP.search(css)
        if sm:
            maps.append(urllib.parse.urljoin(src, sm.group(1)))

    def bp_key(k: str) -> float:
        v = float(re.findall(r"[\d.]+", k)[0])
        return v * 16 if ("em" in k) else v
    return {
        "files": len(files),
        "bytes": total,
        "rules_approx": rules,
        "breakpoints": sorted(bps, key=bp_key)[:20],
        "custom_properties": {"count": len(varsdef), "sample": [k for k, _ in varsdef.most_common(25)]},
        "colors": [k for k, _ in colors.most_common(16)],
        "fonts": [k for k, _ in fonts.most_common(8)],
        "font_faces": font_faces,
        "keyframes": [k for k, _ in kfs.most_common(12)],
        "layout": {"grid": grid, "flex": flex},
        "imports": imports,
        "sourcemaps": maps[:20],
    }


_URL_LIT = re.compile(r"""["'`](https?://[a-zA-Z0-9.-]+(?::\d+)?)[/"'`]""")
_API_LIT = re.compile(r"""["'`](/(?:api|graphql|v\d)/[\w\-/{}.:]{0,80})["'`]""")
_JS_FEATURES = {
    "fetch": r"\bfetch\(", "XMLHttpRequest": r"XMLHttpRequest", "WebSocket": r"new WebSocket\(",
    "localStorage": r"localStorage\.", "sessionStorage": r"sessionStorage\.", "indexedDB": r"indexedDB\.open",
    "serviceWorker": r"serviceWorker\.register", "WebAssembly": r"WebAssembly\.(?:instantiate|compile)",
    "Web Workers": r"new (?:Shared)?Worker\(", "Canvas/WebGL": r"getContext\(['\"](?:2d|webgl2?)",
    "IntersectionObserver": r"IntersectionObserver", "customElements": r"customElements\.define",
    "eval/new Function": r"\beval\(|new Function\(",
}


def analyze_js(files: list[tuple[str, str]]) -> dict[str, Any]:
    domains, endpoints, features = Counter(), Counter(), Counter()
    minified = modules = 0
    maps = []
    total = 0
    for src, js in files:
        total += len(js)
        lines = js.count("\n") + 1
        if len(js) > 2000 and len(js) / lines > 300:
            minified += 1
        if re.search(r"^[ \t]*(?:import|export)\s", js[:1_000_000], re.M) or "import(" in js:
            modules += 1
        for m in _URL_LIT.finditer(js):
            domains[urllib.parse.urlsplit(m.group(1)).hostname or m.group(1)] += 1
        for m in _API_LIT.finditer(js):
            endpoints[m.group(1)] += 1
        for name, rx in _JS_FEATURES.items():
            n = len(re.findall(rx, js))
            if n:
                features[name] += n
        sm = _SMAP.search(js[-2000:])
        if sm and not sm.group(1).startswith("data:"):
            maps.append(urllib.parse.urljoin(src, sm.group(1)))
        elif sm:
            maps.append("(inline data: URI)")
    return {
        "files": len(files),
        "bytes": total,
        "minified_files": minified,
        "module_files": modules,
        "features": dict(features.most_common()),
        "external_domains": [d for d, _ in domains.most_common(25)],
        "api_endpoints": [e for e, _ in endpoints.most_common(30)],
        "sourcemaps": maps[:20],
    }


def summarize_sourcemap(doc: dict[str, Any]) -> dict[str, Any]:
    """Solo rutas: revela la estructura del proyecto original sin copiar código."""
    sources = [s for s in doc.get("sources", []) if isinstance(s, str)][:20000]
    app, pkgs = [], Counter()
    for s in sources:
        clean = re.sub(r"^(?:webpack|vite|rollup)?:/+(?:[^/]+/)?", "", s)
        clean = re.sub(r"^(?:\.\./)+|^\./", "", clean).split("?")[0]
        if "node_modules/" in clean:
            rest = clean.split("node_modules/")[-1].split("/")
            pkgs["/".join(rest[:2]) if rest[0].startswith("@") else rest[0]] += 1
        else:
            app.append(clean)
    exts = Counter(Path(p).suffix or "(sin ext)" for p in app)
    dirs = Counter("/".join(p.split("/")[:2]) for p in app if "/" in p)
    return {
        "sources": len(sources),
        "app_files": sorted(set(app))[:300],
        "app_extensions": dict(exts.most_common(10)),
        "app_dirs": [d for d, _ in dirs.most_common(30)],
        "npm_packages": [p for p, _ in pkgs.most_common(80)],
        "sources_content_available": bool(doc.get("sourcesContent")),
    }


# ---------------------------------------------------------------------------
# Cargadores: URL o disco
# ---------------------------------------------------------------------------
@dataclass
class Loaded:
    ref: str
    text: str
    size: int
    status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    error: str | None = None


class UrlLoader:
    def __init__(self, fetcher: Fetcher, cross_origin: bool):
        self.f = fetcher
        self.cross_origin = cross_origin
        self.origin: str | None = None

    def same_origin(self, url: str) -> bool:
        u = urllib.parse.urlsplit(url)
        return f"{u.scheme}://{u.netloc}" == self.origin

    def main(self, url: str) -> tuple[Loaded, Response]:
        r = self.f.get(url)
        u = urllib.parse.urlsplit(r.final_url)
        self.origin = f"{u.scheme}://{u.netloc}"
        if r.error and r.status is None:
            raise FetchError(r.error)
        return Loaded(r.final_url, r.text(), len(r.body), r.status, r.headers, r.error), r

    def resolve(self, base: str, href: str) -> str:
        return urllib.parse.urljoin(base, href).split("#")[0]

    def load(self, url: str) -> Loaded | None:
        if not url.startswith(("http://", "https://")):
            return None
        if not self.same_origin(url) and not self.cross_origin:
            return None
        try:
            r = self.f.get(url)
        except FetchError as exc:
            return Loaded(url, "", 0, error=str(exc))
        if r.status is None or r.status >= 400:
            return Loaded(url, "", 0, r.status, r.headers, r.error or f"HTTP {r.status}")
        if not self.cross_origin and not self.same_origin(r.final_url):
            # Un recurso del mismo origen que redirige a otro sitio no cuela si cross_origin está desactivado.
            return Loaded(url, "", 0, r.status, r.headers, f"redirige fuera del origen: {r.final_url[:120]}")
        return Loaded(url, r.text(), len(r.body), r.status, r.headers, r.error)


class DiskLoader:
    """Lee un sitio local sin salir nunca de la carpeta raíz."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.origin = self.root.as_uri()

    def same_origin(self, ref: str) -> bool:
        return ref.startswith(self.origin)

    def resolve(self, base: str, href: str) -> str:
        if re.match(r"^[a-z][a-z0-9+.-]*:", href) and not href.startswith("file:"):
            return href    # URL absoluta externa: no se carga
        if href.startswith("/"):
            return urllib.parse.urljoin(self.origin + "/", href.lstrip("/"))
        return urllib.parse.urljoin(base, href).split("#")[0].split("?")[0]

    def load(self, ref: str) -> Loaded | None:
        if not ref.startswith("file:"):
            return None
        path = Path(urllib.request.url2pathname(urllib.parse.urlsplit(ref).path)).resolve()
        if self.root not in path.parents and path != self.root:
            return Loaded(ref, "", 0, error="fuera de la carpeta del sitio")
        if not path.is_file():
            return Loaded(ref, "", 0, error="no existe")
        with open(path, "rb") as fh:   # solo lo que se analiza, no el archivo entero (M35)
            data = fh.read(5 * 1024 * 1024)
        return Loaded(ref, data.decode("utf-8", "replace"), len(data), 200)


# ---------------------------------------------------------------------------
# Análisis principal
# ---------------------------------------------------------------------------
def _f(op: str, result: Any, authority: str = "distributed_artifact", confidence: str = "high",
       limitations: str = "") -> dict[str, Any]:
    return {"operation": op, "result": result, "authority": authority,
            "confidence": confidence, "limitations": limitations}


def analyze_web(source: str, *, fetcher: Fetcher | None = None, max_assets: int = 40,
                cross_origin: bool = False, save_dir: str | Path | None = None,
                progress: Callable[[str], None] | None = None) -> tuple[str, list[dict[str, Any]]]:
    log = progress or (lambda _m: None)
    is_url = source.startswith(("http://", "https://"))
    pages_inventory = None
    if is_url:
        fetcher = fetcher or Fetcher()
        loader: UrlLoader | DiskLoader = UrlLoader(fetcher, cross_origin)
        main, resp = loader.main(source)
        subject = "url:" + main.ref
    else:
        p = Path(source)
        if p.is_dir():
            root = p
            htmls = sorted(walk_files(p, suffixes=(".html", ".htm"), limit=500))
            if not htmls:
                raise FileNotFoundError(f"sin archivos .html en {source}")
            index = next((h for h in htmls if h.name == "index.html" and h.parent == p), htmls[0])
            pages_inventory = _inventory(htmls, root)
        elif p.is_file():
            root, index = p.parent, p
        else:
            raise FileNotFoundError(source)
        loader = DiskLoader(root)
        main = loader.load(index.resolve().as_uri())
        resp = None
        subject = "local:" + str(index.resolve())
    log(f"página principal: {main.ref} ({main.size} B)")

    parser = PageParser()
    parser.feed(main.text)
    parser.close()

    # -- assets -------------------------------------------------------------
    styles: list[tuple[str, str]] = [("(inline)", s) for s in parser.inline_styles]
    scripts: list[tuple[str, str]] = [("(inline)", s) for s in parser.inline_scripts]
    asset_rows: list[dict[str, Any]] = []
    saved: list[str] = []
    budget = max_assets

    def take(kind: str, href: str) -> Loaded | None:
        nonlocal budget
        url = loader.resolve(main.ref, href)
        row = {"kind": kind, "url": url[:300], "same_origin": loader.same_origin(url)}
        asset_rows.append(row)
        if budget <= 0:
            row["fetched"] = False
            row["reason"] = "límite de assets"
            return None
        got = loader.load(url)
        if got is None:
            row["fetched"] = False
            row["reason"] = "otro origen" if not row["same_origin"] else "no cargable"
            return None
        budget -= 1
        row.update({"fetched": not got.error or bool(got.text), "bytes": got.size, "status": got.status})
        if got.error:
            row["error"] = got.error[:200]
        if save_dir and got.text and row["same_origin"]:
            path = _save(save_dir, subject, url, got.text)
            if path:
                saved.append(path)
        return got if got.text else None

    for link in parser.links:
        if "stylesheet" in link["rel"].split() and link["href"]:
            got = take("css", link["href"])
            if got:
                styles.append((got.ref, got.text))
                for imp in _IMPORT.findall(got.text)[:10]:
                    sub = take("css-import", urllib.parse.urljoin(got.ref, imp))
                    if sub:
                        styles.append((sub.ref, sub.text))
    for s in parser.scripts:
        if s["src"]:
            got = take("js", s["src"])
            if got:
                scripts.append((got.ref, got.text))
    manifest = next((l for l in parser.links if l["rel"] == "manifest"), None)
    manifest_info = None
    if manifest and manifest["href"]:
        got = take("manifest", manifest["href"])
        if got:
            try:
                m = json.loads(got.text)
                if not isinstance(m, dict):
                    raise ValueError("el manifest no es un objeto")
                manifest_info = {k: str(m.get(k))[:200] for k in ("name", "short_name", "display", "theme_color",
                                                                  "background_color", "start_url") if k in m}
            except (ValueError, RecursionError):
                manifest_info = {"error": "manifest no es un objeto JSON válido"}
    if save_dir:
        p = _save(save_dir, subject, main.ref if is_url else main.ref, main.text, index_name=True)
        if p:
            saved.append(p)
    log(f"assets: {sum(1 for r in asset_rows if r.get('fetched'))} descargados de {len(asset_rows)}")

    css = analyze_css(styles)
    js = analyze_js(scripts)

    # -- source maps (solo rutas) ------------------------------------------
    smaps = []
    for ref in (css["sourcemaps"] + js["sourcemaps"])[:6]:
        if ref.startswith("(inline"):
            continue
        got = take("sourcemap", ref)
        if got:
            try:
                smaps.append({"map": ref[:300], **summarize_sourcemap(json.loads(got.text))})
            except (ValueError, AttributeError, TypeError, RecursionError):
                smaps.append({"map": ref[:300], "error": "source map no válido"})

    headers = (resp.headers if resp else {})
    findings: list[dict[str, Any]] = []
    if is_url:
        findings.append(_f("web_fetch", {
            "requested": source, "final_url": main.ref, "status": main.status,
            "redirects": resp.redirects, "elapsed_ms": round(resp.elapsed * 1000),
            "bytes": main.size, "content_type": resp.content_type,
            "requests_made": fetcher.requests, "total_bytes": fetcher.total,
        }, "controlled_repro", "high", "Una sola petición; el contenido puede variar por usuario, idioma o A/B."))
        findings.append(_f("web_headers", _headers_report(headers), "controlled_repro", "high",
                           "Cabeceras de la página principal; los assets pueden tener otras."))

    # -- estructura -----------------------------------------------------------
    metas = {(m.get("name") or m.get("property") or m.get("http-equiv") or ("charset" if "charset" in m else "?")).lower():
             m.get("content", m.get("charset", ""))[:300] for m in parser.metas}
    internal, external = _split_links(parser.anchors, main.ref, loader)
    findings.append(_f("web_structure", {
        "doctype": parser.doctype, "lang": parser.lang, "title": parser.title,
        "meta": {k: v for k, v in metas.items() if k in (
            "description", "viewport", "generator", "theme-color", "robots", "charset",
            "og:title", "og:type", "og:image", "twitter:card", "color-scheme")},
        "headings": [{"level": l, "text": t} for l, t in parser.headings[:60]],
        "landmarks": {k: parser.tags[k] for k in LANDMARKS if parser.tags[k]},
        "tag_counts": dict(parser.tags.most_common(25)),
        "elements": sum(parser.tags.values()),
        "custom_elements": dict(parser.custom_elements.most_common(20)),
        "data_attributes": dict(parser.data_attrs.most_common(20)),
        "top_classes": dict(parser.classes.most_common(30)),
        "forms": [{**f, "fields": dict(Counter(f["fields"]))} for f in parser.forms[:20]],
        "iframes": parser.iframes[:20],
        "links": {"internal": len(internal), "external": len(external),
                  "internal_sample": internal[:40], "external_domains": _domains(external)[:20]},
        "outline": parser.outline(),
        "pages": pages_inventory,
        "web_manifest": manifest_info,
    }, limitations="HTML servido inicialmente; el contenido que inserta JavaScript después no aparece."))

    imgs = parser.images
    preload = [l for l in parser.links if l["rel"] in ("preload", "preconnect", "dns-prefetch", "modulepreload", "prefetch")]
    blocking = [s["src"] for s in parser.scripts if s["src"] and s["in_head"] and not (s["async"] or s["defer"] or s["module"])]
    findings.append(_f("web_assets", {
        "assets": asset_rows[:150],
        "stylesheets": sum(1 for r in asset_rows if r["kind"] == "css"),
        "scripts": {"external": sum(1 for s in parser.scripts if s["src"]),
                    "inline": sum(1 for s in parser.scripts if not s["src"]),
                    "modules": sum(1 for s in parser.scripts if s["module"]),
                    "async_or_defer": sum(1 for s in parser.scripts if s["async"] or s["defer"])},
        "render_blocking_scripts": blocking[:20],
        "images": {"count": len(imgs), "lazy": sum(1 for i in imgs if i["loading"] == "lazy"),
                   "responsive_srcset": sum(1 for i in imgs if i["srcset"]),
                   "formats": dict(Counter(_ext(i["src"]) for i in imgs).most_common(8)),
                   "sample": [i["src"] for i in imgs[:15]]},
        "resource_hints": [{"rel": l["rel"], "href": l["href"][:200]} for l in preload[:20]],
        "icons": [l["href"][:200] for l in parser.links if "icon" in l["rel"]][:10],
        "saved_files": saved[:200],
    }))
    findings.append(_f("web_css", css, limitations="Análisis por expresiones regulares; no evalúa la cascada."))
    findings.append(_f("web_js", js, limitations="Búsqueda estática de patrones; no ejecuta el código."))
    if smaps:
        findings.append(_f("web_sourcemaps", smaps, limitations=(
            "Solo se registran rutas y nombres de paquetes; el código original no se guarda.")))
    findings.append(_f("web_accessibility", _a11y(parser, metas), "analyst_inference", "medium",
                       "Comprobaciones básicas automáticas; no sustituyen una auditoría WCAG."))
    findings.append(_f("web_seo", _seo(parser, metas, fetcher if is_url else None, main.ref),
                       "distributed_artifact", "high", ""))

    # -- pila y plano ---------------------------------------------------------
    techs = stack.detect_web(main.text, scripts, styles, headers)
    npm = {p for sm in smaps for p in sm.get("npm_packages", [])}
    if npm:
        names = {t["name"] for t in techs}
        for t in stack.detect_repo({"npm": npm}, set()):
            if t["name"] not in names:
                t["evidence"] = ["source map: " + e for e in t["evidence"]]
                techs.append(t)
    findings.append(_f("web_stack", {"technologies": techs}, "analyst_inference", "medium",
                       "Huellas heurísticas: indican presencia probable, no versión exacta."))
    findings.append(_f("web_blueprint", _blueprint(parser, css, js, techs, smaps), "analyst_inference", "medium",
                       "Propuesta para construir algo parecido; no es una copia ni un clon."))
    return subject, findings


PRUNE_DIRS = {"node_modules", ".git", ".hg", ".svn", ".venv", "venv", "__pycache__", "bower_components",
              ".next", ".nuxt", ".cache", "target", ".gradle", ".idea"}


def walk_files(root: Path, *, suffixes: tuple[str, ...] | None = None, limit: int = 10_000,
               max_visited: int = 200_000):
    """Recorre con poda (sin node_modules, .git…) y con tope de archivos devueltos y vistos (M35)."""
    import os

    found = visited = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in PRUNE_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            visited += 1
            if visited > max_visited or found >= limit:
                return
            if suffixes is None or name.lower().endswith(suffixes):
                f = Path(dirpath, name)
                if f.is_file():
                    found += 1
                    yield f


def _inventory(htmls: list[Path], root: Path) -> list[dict[str, Any]]:
    out = []
    for h in htmls[:200]:
        p = PageParser()
        try:
            with open(h, "rb") as fh:
                p.feed(fh.read(2_000_000).decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001 — una página rota no tumba el inventario
            continue
        out.append({"path": str(h.relative_to(root)).replace("\\", "/"), "title": p.title,
                    "h1": next((t for l, t in p.headings if l == 1), None)})
    return out


def _ext(src: str) -> str:
    path = urllib.parse.urlsplit(src).path.lower()
    if src.startswith("data:"):
        return "data-uri"
    return Path(path).suffix or "(sin ext)"


def _split_links(anchors: list[str], base: str, loader) -> tuple[list[str], list[str]]:
    internal, external = [], []
    seen = set()
    for href in anchors:
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        url = loader.resolve(base, href)
        if url in seen:
            continue
        seen.add(url)
        if loader.same_origin(url):
            rel = url[len(loader.origin):] if isinstance(loader, DiskLoader) else urllib.parse.urlsplit(url).path
            internal.append(rel or "/")
        else:
            external.append(url)
    return internal, external


def _domains(urls: list[str]) -> list[str]:
    return [d for d, _ in Counter(urllib.parse.urlsplit(u).hostname or "?" for u in urls).most_common()]


def _headers_report(h: dict[str, str]) -> dict[str, Any]:
    present = {label: h[k][:300] for k, label in SECURITY_HEADERS.items() if k in h}
    cookies = []
    raw = h.get("set-cookie", "")
    pieces = [c for line in raw.split("\n") for c in re.split(r",(?=\s*[\w.-]+=)", line)] if raw else []
    for c in (x for x in pieces if x.strip()):
        parts = [p.strip() for p in c.split(";")]
        name = parts[0].split("=")[0]
        low = [p.lower() for p in parts[1:]]
        cookies.append({"name": name[:60], "secure": "secure" in low, "httponly": "httponly" in low,
                        "samesite": next((p.split("=")[1] for p in low if p.startswith("samesite=")), None)})
    return {
        "security": present,
        "missing_security": [label for k, label in SECURITY_HEADERS.items() if k not in h],
        "server": h.get("server"), "powered_by": h.get("x-powered-by"),
        "cache_control": h.get("cache-control"), "content_encoding": h.get("content-encoding"),
        "cookies": cookies,   # solo nombres y flags: nunca valores
    }


def _a11y(p: PageParser, metas: dict[str, str]) -> dict[str, Any]:
    issues = []
    if not p.lang:
        issues.append("Falta lang en <html>.")
    no_alt = sum(1 for i in p.images if i["alt"] is None)
    if no_alt:
        issues.append(f"{no_alt} imágenes sin atributo alt.")
    unlabeled = sum(1 for i in p.inputs if not (i["in_label"] or i["aria_label"] or (i["id"] and i["id"] in p.label_for)))
    if unlabeled:
        issues.append(f"{unlabeled} campos de formulario sin etiqueta asociada.")
    if p.buttons_without_text:
        issues.append(f"{p.buttons_without_text} botones sin texto ni aria-label.")
    levels = [l for l, _ in p.headings]
    skips = sum(1 for a, b in zip(levels, levels[1:]) if b > a + 1)
    if skips:
        issues.append(f"{skips} saltos de nivel en los encabezados (p. ej. h2 → h4).")
    h1 = levels.count(1)
    if h1 != 1:
        issues.append(f"{h1} encabezados h1 (lo habitual es uno).")
    if "viewport" not in metas:
        issues.append("Falta <meta name=viewport> (no adaptado a móvil).")
    if not p.tags["main"]:
        issues.append("Sin landmark <main>.")
    return {"issues": issues, "images_without_alt": no_alt, "unlabeled_inputs": unlabeled,
            "heading_skips": skips, "aria_attributes": p.aria}


def _seo(p: PageParser, metas: dict[str, str], fetcher: Fetcher | None, base: str) -> dict[str, Any]:
    types = []
    for block in p.jsonld:
        try:
            doc = json.loads(block)
        except (ValueError, RecursionError):
            continue
        for d in doc if isinstance(doc, list) else doc.get("@graph", [doc]) if isinstance(doc, dict) else []:
            if isinstance(d, dict) and d.get("@type"):
                types.append(str(d["@type"])[:60])
    out: dict[str, Any] = {
        "title_length": len(p.title),
        "description_length": len(metas.get("description", "")),
        "canonical": next((l["href"] for l in p.links if l["rel"] == "canonical"), None),
        "robots_meta": metas.get("robots"),
        "open_graph": sorted(k for k in metas if k.startswith("og:")),
        "twitter": sorted(k for k in metas if k.startswith("twitter:")),
        "structured_data_types": sorted(set(types)),
        "hreflang": [l["href"][:200] for l in p.links if l["rel"] == "alternate"][:20],
    }
    if fetcher:
        u = urllib.parse.urlsplit(base)
        try:
            r = fetcher.get(f"{u.scheme}://{u.netloc}/sitemap.xml")
            if r.status == 200 and (b"<urlset" in r.body[:2000] or b"<sitemapindex" in r.body[:2000]):
                locs = re.findall(rb"<loc>\s*([^<]{1,500})\s*</loc>", r.body)
                out["sitemap"] = {"urls": len(locs),
                                  "sample": [urllib.parse.urlsplit(l.decode("utf-8", "replace")).path for l in locs[:25]]}
        except FetchError:
            pass
    return out


def _blueprint(p: PageParser, css: dict[str, Any], js: dict[str, Any], techs: list[dict[str, Any]],
               smaps: list[dict[str, Any]]) -> dict[str, Any]:
    names = [t["name"] for t in techs]
    scaffold = stack.scaffold_for(names) or "Sitio estático: index.html + styles.css + main.js (sin bundler)"
    landmarks = []

    def walk(n: dict[str, Any], depth: int) -> None:
        if n.get("landmark") and depth <= 12:
            label = n["landmark"]
            if n.get("id"):
                label += f"#{n['id']}"
            elif n.get("class"):
                label += "." + n["class"].split()[0]
            landmarks.append(label)
        for c in n.get("children", []):
            walk(c, depth + 1)
    walk(p.outline(), 0)

    utility = re.compile(
        r"[:\[/]|^-?[a-z]{1,3}-\d|^(?:text|bg|p[xytrbl]?|m[xytrbl]?|w|h|min|max|gap|flex|grid|items|justify|"
        r"self|place|rounded|border|shadow|font|leading|tracking|relative|absolute|fixed|sticky|inline|block|"
        r"hidden|overflow|z|top|left|right|bottom|inset|space|col|row|container|sm|md|lg|xl|2xl|break|"
        r"opacity|transition|duration|ease|cursor|select|sr|object|aspect|order|basis|grow|shrink|"
        r"underline|uppercase|lowercase|truncate|whitespace|align|list|outline|ring|fill|stroke)(?:-|$)")
    components = [f"{k} ×{n}" for k, n in p.blocks.most_common(80)
                  if n >= 3 and not utility.search(k.split(".", 1)[1])][:15]
    app_dirs = next((sm.get("app_dirs") for sm in smaps if sm.get("app_dirs")), None)
    notes = []
    if any(t["category"] == "meta-framework" for t in techs):
        notes.append("Usa un meta-framework con renderizado en servidor: el HTML inicial ya trae contenido.")
    if css["custom_properties"]["count"] > 20:
        notes.append("Diseño basado en variables CSS (design tokens): define tu paleta como --color-* en :root.")
    if css["layout"]["grid"] > css["layout"]["flex"]:
        notes.append("La maquetación se apoya sobre todo en CSS Grid.")
    elif css["layout"]["flex"]:
        notes.append("La maquetación se apoya sobre todo en Flexbox.")
    if js["minified_files"]:
        notes.append("El JS está minificado: pasa por un bundler en producción.")
    if smaps and any(sm.get("app_files") for sm in smaps):
        notes.append("Hay source maps públicos: las rutas muestran cómo organizan los componentes.")
    if not p.tags["main"]:
        notes.append("Al recrearla, añade landmarks semánticos (<header>, <main>, <footer>).")
    return {
        "suggested_scaffold": scaffold,
        "stack": names,
        # Etiqueta legible: «HTML estático» solo si la evidencia lo sostiene (ninguna tecnología detectada, sin JS
        # minificado ni source maps); si no se detecta nada pero hay indicios de compilación, queda sin determinar.
        "stack_label": (", ".join(names) if names else
                        "HTML estático sin framework detectado" if not js["minified_files"] and not smaps
                        else None),
        "page_skeleton": landmarks[:40],
        "headings_outline": ["  " * (l - 1) + f"h{l}: {t}" for l, t in p.headings[:30]],
        "design_tokens": {"colors": css["colors"][:10], "fonts": css["fonts"][:5],
                          "breakpoints": css["breakpoints"][:8],
                          "custom_properties_sample": css["custom_properties"]["sample"][:12]},
        "component_candidates": components,
        "original_project_dirs": app_dirs,
        "learning_notes": notes,
    }


def _save(save_dir: str | Path, subject: str, url: str, text: str, index_name: bool = False) -> str | None:
    """Guarda una copia de estudio bajo save_dir/<sitio>/<ruta saneada>."""
    site = re.sub(r"[^\w.-]", "_", urllib.parse.urlsplit(url).netloc or "local")[:80] or "local"
    path = urllib.parse.urlsplit(url).path
    parts = [re.sub(r"[^\w.\-]", "_", unquote_part)[:80] for unquote_part in
             urllib.parse.unquote(path).split("/") if unquote_part not in ("", ".", "..")]
    # Nombres reservados de Windows (CON, NUL, COM1…): se les añade «_».
    parts = [x + "_" if re.fullmatch(r"(?i)(con|prn|aux|nul|com\d|lpt\d)(\..*)?", x) else x for x in parts]
    if index_name and (not parts or "." not in parts[-1]):
        parts.append("index.html")
    if not parts:
        return None
    base = Path(save_dir).resolve() / site
    dst = (base.joinpath(*parts)).resolve()
    if base not in dst.parents:
        return None
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_dir():                     # /a ya guardado como carpeta por /a/b.css
            dst = dst / "index.html"
        dst.write_text(text, encoding="utf-8")
    except OSError:
        # /a guardado como archivo y ahora llega /a/b.css (o nombre no válido): se omite esta
        # copia de estudio, sin abortar el análisis.
        return None
    return str(dst)


def page_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
