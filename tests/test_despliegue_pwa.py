"""C4: PWA del destino static y receta de despliegue (DESPLIEGUE.md) de los proyectos generados."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from eolfi.core.evidence import EvidenceStore
from eolfi.flows.create_flow import create_project
from eolfi.generador import juez
from eolfi.generador.despliegue import VARIABLES
from tests.fixtures import build_site

ROOT = Path(__file__).resolve().parents[1]


def _crear(tmp_path: Path, destino: str, **kw) -> Path:
    out = tmp_path / destino
    create_project([str(build_site(tmp_path / f"site-{destino}"))], EvidenceStore(":memory:"), out, name="Bicis",
                   target=destino, do_verify=False, **kw)
    return out


def test_static_trae_manifiesto_icono_y_service_worker_coherentes(tmp_path):
    out = _crear(tmp_path, "static")
    m = json.loads((out / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert m["display"] == "standalone" and m["start_url"] == "./index.html" and m["icons"][0]["src"] == "icon.svg"
    spec = json.loads((out / "eolfi.spec.json").read_text(encoding="utf-8"))
    assert m["theme_color"] == spec["design"]["palette"]["primary"]
    sw = (out / "sw.js").read_text(encoding="utf-8")
    propios = json.loads(re.search(r"const PROPIOS = (\[.*\]);", sw).group(1))
    assert propios and all((out / p).is_file() for p in propios)          # todo lo precacheado existe
    for pagina in ("index.html", "about.html"):
        html = (out / pagina).read_text(encoding="utf-8")
        assert '<link rel="manifest" href="manifest.webmanifest">' in html and 'name="theme-color"' in html
    assert "/api/" in sw and "url.origin !== self.location.origin" in sw  # ni terceros ni la API


def test_los_backends_no_llevan_pwa(tmp_path):
    out = _crear(tmp_path, "fastapi")                     # su web estática sale de la misma plantilla
    paginas = list(out.rglob("*.html"))
    assert paginas and not list(out.rglob("sw.js"))
    assert all('rel="manifest"' not in h.read_text(encoding="utf-8") for h in paginas)


@pytest.mark.parametrize("destino,entrada", [("react", "src/main.tsx"), ("vue", "src/main.ts"), ("svelte", "src/main.ts")])
def test_los_destinos_con_vite_llevan_pwa_en_public(tmp_path, destino, entrada):
    """C4 (18/11/2026): manifiesto, icono y service worker en public/ (Vite los copia a dist/), enlazados desde
    index.html y registrados solo en la compilación de producción."""
    out = _crear(tmp_path, destino)
    m = json.loads((out / "public/manifest.webmanifest").read_text(encoding="utf-8"))
    assert m["display"] == "standalone" and m["start_url"] == "./" and m["icons"][0]["src"] == "icon.svg"
    assert (out / "public/icon.svg").is_file()
    html = (out / "index.html").read_text(encoding="utf-8")
    assert '<link rel="manifest" href="/manifest.webmanifest" />' in html and 'name="theme-color"' in html
    sw = (out / "public/sw.js").read_text(encoding="utf-8")
    assert "/api/" in sw and "url.origin !== self.location.origin" in sw and "index.html" in sw
    main = (out / entrada).read_text(encoding="utf-8")
    assert 'if (import.meta.env.PROD && "serviceWorker" in navigator)' in main and "sw.js" in main


def _compilacion_como_vite(out: Path) -> Path:
    """dist/ con la forma de `vite build`: public/ copiado a la raíz, el index con el script con hash y la CSP de
    la compilación, y un JS que pinta la página y registra el service worker como el main generado en producción."""
    from eolfi.generador.generators import CSP_META

    dist = out / "dist"
    shutil.copytree(out / "public", dist)
    html = (out / "index.html").read_text(encoding="utf-8")
    html = re.sub(r'<script type="module" src="[^"]+"></script>',
                  '<script type="module" crossorigin src="/assets/index-a1b2c3.js"></script>', html)
    html = html.replace("<head>", f'<head>\n    <meta http-equiv="Content-Security-Policy" content="{CSP_META}" />')
    (dist / "index.html").write_text(html, encoding="utf-8")
    main = next((out / "src").glob("main.ts*")).read_text(encoding="utf-8")
    registro = main[main.index("// PWA:"):].replace("import.meta.env.PROD", "true").replace(
        "${import.meta.env.BASE_URL}", "/")
    (dist / "assets").mkdir()
    (dist / "assets/index-a1b2c3.js").write_text(
        'const raiz = document.getElementById("root") || document.getElementById("app");\n'
        'const h1 = document.createElement("h1");\n'
        'h1.textContent = location.pathname === "/about" ? "Acerca" : "Inicio";\n'
        "raiz.append(h1);\n" + registro, encoding="utf-8")
    return dist


@pytest.mark.skipif(not shutil.which("node") or juez._playwright() is None, reason="requiere Node.js y Playwright")
@pytest.mark.parametrize("destino", ["react", "vue", "svelte"])
def test_la_pwa_de_vite_funciona_sin_conexion_en_un_navegador_real(tmp_path, destino):
    """Con una compilación con la forma de la de Vite (con `npm install` y `vite build` reales, NO VERIFICADO: exige
    red): el service worker toma el control, precarga los recursos con hash que enlaza el index y, sin red, la
    portada y una ruta de la SPA cargan desde la caché."""
    dist = _compilacion_como_vite(_crear(tmp_path, destino))
    env = {**os.environ, "EOLFI_PLAYWRIGHT": juez._playwright()}
    from eolfi import navegador

    if not os.environ.get("EOLFI_BROWSER_PATH") and navegador.ejecutable():
        env["EOLFI_BROWSER_PATH"] = str(navegador.ejecutable())
    p = subprocess.run(["node", str(ROOT / "tests" / "pwa_sin_conexion.mjs"), str(dist), "/about"],
                       capture_output=True, text=True, timeout=120, env=env, check=False)
    r = json.loads(p.stdout or "{}")
    assert "error" not in r and r["errores"] == [], (r, p.stderr[-500:])
    assert r["manifiesto"] == "/manifest.webmanifest" and r["controlada"] is True
    assert r["h1_sin_red"] == "Inicio" and r["about_sin_red"] == "Acerca"
    assert r["terceros_sin_red"] == "falla"


@pytest.mark.parametrize("destino,opciones", [
    ("static", {}), ("react", {}), ("next", {"auth": True}), ("express", {"db": "sqlite"}),
    ("fastapi", {"db": "sqlite"}), ("django", {}), ("cli", {}), ("go", {})])
def test_la_receta_solo_cita_variables_que_la_plantilla_lee(tmp_path, destino, opciones):
    out = _crear(tmp_path, destino, **opciones)
    receta = (out / "DESPLIEGUE.md").read_text(encoding="utf-8")
    assert "el despliegue (hosting, proxy y HTTPS) no lo ha probado Eolfi" in receta
    codigo = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in out.rglob("*")
                       if p.is_file() and p.name != "DESPLIEGUE.md" and p.suffix in
                       (".py", ".js", ".mjs", ".ts", ".tsx", ".json", ".html", ".go"))
    citadas = set(re.findall(r"\| `([A-Z][A-Z0-9_]+)` \|", receta.split("## Cabeceras")[0]))
    assert citadas == {k for k, _ in VARIABLES.get(destino, [])}
    for var in citadas:
        assert var in codigo, f"{destino}: la receta cita {var} y la plantilla no la lee"
    if destino in ("static", "react", "next", "express", "fastapi", "django", "go"):
        assert "Content-Security-Policy" in receta and "add_header" in receta
    else:
        assert "## Cabeceras" not in receta


@pytest.mark.skipif(not shutil.which("node") or juez._playwright() is None, reason="requiere Node.js y Playwright")
def test_la_pwa_funciona_sin_conexion_en_un_navegador_real(tmp_path):
    out = _crear(tmp_path, "static")
    env = {**os.environ, "EOLFI_PLAYWRIGHT": juez._playwright()}
    from eolfi import navegador

    if not os.environ.get("EOLFI_BROWSER_PATH") and navegador.ejecutable():
        env["EOLFI_BROWSER_PATH"] = str(navegador.ejecutable())
    p = subprocess.run(["node", str(ROOT / "tests" / "pwa_sin_conexion.mjs"), str(out)], capture_output=True,
                       text=True, timeout=120, env=env, check=False)
    r = json.loads(p.stdout or "{}")
    assert "error" not in r and r["errores"] == [], (r, p.stderr[-500:])
    assert r["manifiesto"] == "manifest.webmanifest" and r["controlada"] is True
    assert r["h1_sin_red"] and r["about_sin_red"]                       # las dos páginas, sin red
    assert r["terceros_sin_red"] == "falla"                             # el SW no inventa respuestas ajenas
