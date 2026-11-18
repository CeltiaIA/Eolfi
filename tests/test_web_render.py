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


# ── Interacciones (C3, 18/11/2026) ───────────────────────────────────────────────────────────────────────────────
def test_lo_que_aparece_al_pulsar_entra_en_el_rastreo():
    llamadas = []

    def renderer(urls, hosts, interactuar=0):
        llamadas.append(interactuar)
        return {"status": "ok", "browser": "fake/1", "blocked_non_get": ["POST /api/guardar"],
                "pages": [{"status": "ok", "title": u, "final_url": u, "text_chars": 10, "links": [], "routes": [],
                           "forms": [{"action": "/alta", "method": "post", "fields": [{"name": "email"}]}],
                           "requests": ["GET https://sitio.example/api/items"],
                           "interactions": {"pulsados": [{"control": "Detalle", "rutas_nuevas":
                                                          ["https://sitio.example/detalle"],
                                                          "enlaces_nuevos": ["https://otro.example/x"]}],
                                            "saltados": ["Borrar todo"]} if u.endswith("/") else
                           {"pulsados": [], "saltados": []}} for u in urls]}

    res = R.rastrear("https://sitio.example/", max_paginas=5, max_profundidad=1, renderer=renderer, interactuar=4)
    assert llamadas == [4, 4]
    detalle = next(p for p in res["paginas"] if p["url"] == "https://sitio.example/detalle")
    assert detalle["via"] == "interaccion"
    portada = res["paginas"][0]
    assert portada["interacciones"]["saltados"] == ["Borrar todo"]
    assert portada["formularios"][0]["action"] == "/alta" and portada["peticiones"]
    assert res["peticiones_no_get_bloqueadas"] == ["POST /api/guardar"]
    assert "nunca envía formularios" in res["limite"]
    # Sin interacciones, el renderizador no recibe el argumento (compatibilidad con los de dos argumentos).
    renderer2, _ = _fake({})
    assert R.rastrear("https://sitio.example/", max_profundidad=0, renderer=renderer2)["interactuar"] == 0


INTERACTIVA = """<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Tienda</title></head><body>
<div id="app"><h1>Tienda</h1>
<div role="tablist"><button role="tab" id="t1">Detalle</button><button role="tab" id="t2">Opiniones</button></div>
<section id="panel"></section>
<button id="mas">Cargar más</button> <button id="guardar">Guardar cambios</button>
<button id="borrar">Borrar todo</button> <button id="aviso">Ver aviso</button> <button id="ventana">Abrir ayuda</button>
<details><summary>Más información</summary><p>Plegado</p></details>
<form action="/alta" method="post"><label>Nombre <input name="nombre" required minlength="2"></label>
<label>Correo <input name="correo" type="email"></label>
<select name="plan" aria-label="Plan"><option value="basico">Básico</option><option value="pro">Pro</option></select>
<button type="submit">Darme de alta</button></form></div>
<script>
const panel = document.getElementById('panel');
document.getElementById('t1').onclick = () => { history.pushState({}, '', '/detalle');
  panel.innerHTML = '<p>' + 'detalle '.repeat(40) + '</p><a href="/oculta">Página oculta</a>'; };
document.getElementById('t2').onclick = () => { panel.textContent = 'opiniones '.repeat(20); };
document.getElementById('mas').onclick = () => fetch('/api/items.json').then((r) => r.json())
  .then((d) => { panel.textContent = d.items.join(', '); });
document.getElementById('guardar').onclick = () => fetch('/api/guardar', { method: 'POST', body: '{}' }).catch(() => {});
document.getElementById('borrar').onclick = () => fetch('/api/borrar', { method: 'DELETE' });
document.getElementById('aviso').onclick = () => alert('Hola');
document.getElementById('ventana').onclick = () => window.open('/acerca', '_blank');
</script></body></html>"""


@pytest.fixture
def tienda(tmp_path):
    (tmp_path / "index.html").write_text(INTERACTIVA, encoding="utf-8")
    for d in ("oculta", "detalle", "acerca"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "index.html").write_text(f"<title>{d}</title><p>{d}</p>", encoding="utf-8")
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "items.json").write_text(json.dumps({"items": ["a", "b"]}), encoding="utf-8")
    recibidas = []

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(tmp_path), **k)

        def do_POST(self):  # noqa: N802 — si llega alguna, la prueba falla
            recibidas.append(("POST", self.path))
            self.send_response(204)
            self.end_headers()

        def do_DELETE(self):  # noqa: N802
            recibidas.append(("DELETE", self.path))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/", recibidas
    srv.shutdown()


def test_interacciones_reales_sin_efectos(tienda):
    if not _navegador_disponible():
        pytest.skip("sin Node, playwright-core o Chrome: interacciones reales NO VERIFICADAS en este equipo")
    sitio, recibidas = tienda
    res = R.rastrear(sitio, max_paginas=5, max_profundidad=1, interactuar=10)
    assert res["estado"] == "ok", res
    portada = res["paginas"][0]
    inter = portada["interacciones"]
    pulsados = {p["control"]: p for p in inter["pulsados"]}
    # Pestaña que cambia la ruta y descubre un enlace: la ruta y el enlace entran en el rastreo.
    assert sitio + "detalle" in pulsados["Detalle"]["rutas_nuevas"]
    assert sitio + "oculta" in pulsados["Detalle"]["enlaces_nuevos"]
    assert any(p["url"] == sitio + "oculta" and p["via"] == "interaccion" for p in res["paginas"])
    assert pulsados["Opiniones"]["texto"] != 0
    assert any("/api/items.json" in r for r in pulsados["Cargar más"]["peticiones"])
    assert "Más información" in pulsados
    # Con efectos: «Borrar todo» ni se pulsa; el POST de «Guardar cambios» no sale del navegador; el formulario se
    # inventaría sin enviarse.
    assert "Borrar todo" in inter["saltados"] and "Darme de alta" not in pulsados
    assert "POST /api/guardar" in res["peticiones_no_get_bloqueadas"]
    assert recibidas == []
    form = portada["formularios"][0]
    assert form["method"] == "post" and form["action"] == "/alta"
    campos = {c["name"]: c for c in form["fields"]}
    assert campos["nombre"]["required"] is True and campos["nombre"]["minlength"] == 2
    assert campos["correo"]["type"] == "email" and campos["plan"]["options"] == ["basico", "pro"]
    # El aviso se descarta y queda anotado; la ventana nueva se cierra sin romper el resto.
    assert any("Hola" in d for d in portada["dialogos"])
    assert "Abrir ayuda" in pulsados and not pulsados["Abrir ayuda"].get("error")
