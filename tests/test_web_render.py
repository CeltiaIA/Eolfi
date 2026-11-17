"""C3: páginas renderizadas y rastreo limitado."""
from __future__ import annotations

import http.server
import json
import shutil
import threading
from pathlib import Path

import pytest

from eolfi.sites import render as R


def _fake(paginas: dict[str, dict]):
    llamadas = []

    def renderer(urls, hosts):
        llamadas.append((list(urls), list(hosts)))
        return {"status": "ok", "browser": "fake/1", "blocked_origins": ["https://cdn.example"],
                "pages": [{"status": "ok", "http": 200, "title": paginas.get(u, {}).get("title", u),
                           "final_url": u, "text_chars": 500, "html_bytes": 100, "html": "<html></html>",
                           "links": paginas.get(u, {}).get("links", []),
                           "routes": paginas.get(u, {}).get("routes", [])} for u in urls]}
    return renderer, llamadas


def test_rastreo_mismo_origen_profundidad_y_tope():
    paginas = {
        "https://sitio.example/": {"links": ["https://sitio.example/a", "https://sitio.example/b#x",
                                             "https://otro.example/", "https://sitio.example/logo.png",
                                             "mailto:x@y"], "routes": ["https://sitio.example/app/panel"]},
        "https://sitio.example/a": {"links": ["https://sitio.example/c"]},
    }
    renderer, llamadas = _fake(paginas)
    res = R.rastrear("https://sitio.example", max_paginas=4, max_profundidad=2, renderer=renderer)
    urls = [p["url"] for p in res["paginas"]]
    assert urls[0] == "https://sitio.example/"
    assert set(urls) <= {"https://sitio.example/", "https://sitio.example/a", "https://sitio.example/b",
                         "https://sitio.example/app/panel", "https://sitio.example/c"}
    assert len(urls) == 4 and res["renderizadas"] == 4
    assert {p["via"] for p in res["paginas"][1:]} >= {"enlace", "ruta_spa"}
    assert res["excluidas"]["otro_origen"] == 1 and res["excluidas"]["tope"] >= 1
    assert all(h == ["sitio.example"] for _u, h in llamadas)
    assert res["origenes_bloqueados"] == ["https://cdn.example"]


def test_profundidad_cero_solo_la_inicial():
    renderer, llamadas = _fake({"https://s.example/": {"links": ["https://s.example/a"]}})
    res = R.rastrear("https://s.example/", max_paginas=10, max_profundidad=0, renderer=renderer)
    assert [p["url"] for p in res["paginas"]] == ["https://s.example/"] and len(llamadas) == 1
    assert res["pendientes_sin_visitar"] == 1


def test_robots_excluye_sin_renderizar():
    renderer, llamadas = _fake({"https://s.example/": {"links": ["https://s.example/privado"]}})
    res = R.rastrear("https://s.example/", max_paginas=5, max_profundidad=1, renderer=renderer,
                     robots=lambda u: not u.endswith("/privado"))
    assert res["excluidas"]["robots"] == 1
    assert all("https://s.example/privado" not in urls for urls, _h in llamadas)


def test_topes_maximos_se_aplican():
    renderer, _ = _fake({})
    res = R.rastrear("https://s.example/", max_paginas=999, max_profundidad=99, renderer=renderer)
    assert res["max_paginas"] == R.MAX_PAGINAS and res["max_profundidad"] == R.MAX_PROFUNDIDAD


def test_sin_navegador_es_no_verificado():
    res = R.rastrear("https://s.example/", renderer=lambda u, h: {"status": "unavailable", "error": "sin Chrome"})
    assert res["estado"] == "unavailable" and "NO VERIFICADO" in res["limite"]


def test_url_no_http_rechazada():
    with pytest.raises(ValueError):
        R.rastrear("file:///c:/x.html", renderer=lambda u, h: {})


def test_indicio_spa():
    assert R.resumen_spa(20, {"texto_caracteres": 900})["parece_spa"] is True
    assert R.resumen_spa(800, {"texto_caracteres": 900})["parece_spa"] is False


SPA = """<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Cargando</title></head>
<body><div id="app"></div><script>
const app = document.getElementById('app');
document.title = 'Panel SPA';
app.innerHTML = '<h1>Panel construido por JavaScript</h1><p>' + 'contenido '.repeat(60) + '</p>' +
  '<a href="/acerca">Acerca</a> <a href="https://externo.example/">Fuera</a>';
history.pushState({}, '', '/inicio');
fetch('https://externo.example/rastreo').catch(() => {});
</script></body></html>"""


@pytest.fixture
def sitio(tmp_path):
    (tmp_path / "index.html").write_text(SPA, encoding="utf-8")
    (tmp_path / "acerca").mkdir()
    (tmp_path / "acerca" / "index.html").write_text("<title>Acerca</title><p>estática</p>", encoding="utf-8")
    (tmp_path / "inicio").mkdir()
    (tmp_path / "inicio" / "index.html").write_text(SPA, encoding="utf-8")

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(tmp_path), **k)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


def _navegador_disponible() -> bool:
    if shutil.which("node") is None or R._playwright() is None:
        return False
    res = R.render(["about:blank"], [], timeout=20, settle=1)
    return res.get("status") == "ok"


def test_render_real_de_una_spa_local(sitio):
    if not _navegador_disponible():
        pytest.skip("sin Node, playwright-core o Chrome: renderizado real NO VERIFICADO en este equipo")
    res = R.rastrear(sitio, max_paginas=3, max_profundidad=1)
    assert res["estado"] == "ok", res
    portada = res["paginas"][0]
    assert portada["titulo"] == "Panel SPA" and portada["texto_caracteres"] > 300
    assert "Panel construido por JavaScript" in portada["html"]
    urls = {p["url"] for p in res["paginas"]}
    assert sitio + "acerca" in urls and sitio + "inicio" in urls
    assert res["excluidas"]["otro_origen"] >= 1
    assert "https://externo.example" in res["origenes_bloqueados"]
    assert R.resumen_spa(0, portada)["parece_spa"] is True


def test_cli_web_render_con_archivo_local_no_aplica(tmp_path, capsys):
    from eolfi.cli import main

    html = tmp_path / "p.html"
    html.write_text("<title>t</title><p>hola</p>", encoding="utf-8")
    assert main(["web", str(html), "--render", "--max-assets", "0"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["render"]["estado"] == "no_aplica"
    assert Path(html).exists()
