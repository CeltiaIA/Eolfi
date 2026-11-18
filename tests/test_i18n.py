"""C1: idiomas es/en del panel, la API y la CLI."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pytest

from eolfi import i18n
from eolfi.cli import _parser, main
from tests.test_server import req, srv  # noqa: F401  (fixture del servidor)

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "tools"))
import i18n_panel  # noqa: E402

sys.path.remove(str(RAIZ / "tools"))


def _ayudas_subcomandos(p: argparse.ArgumentParser) -> list[str]:
    out = []
    for a in p._actions:
        if isinstance(a, argparse._SubParsersAction):
            out += [c.help for c in a._choices_actions if c.help]
            for sub in a.choices.values():
                out += _ayudas_subcomandos(sub)
    return out


def test_idioma_de_la_cli(monkeypatch):
    monkeypatch.delenv("EOLFI_IDIOMA", raising=False)
    assert i18n.idioma_cli([]) == "es"
    assert i18n.idioma_cli(["--idioma", "en", "doctor"]) == "en"
    assert i18n.idioma_cli(["--idioma=EN"]) == "en"
    assert i18n.idioma_cli(["--idioma", "fr"]) == "es"
    monkeypatch.setenv("EOLFI_IDIOMA", "en")
    assert i18n.idioma_cli(["doctor"]) == "en"
    assert i18n.idioma_cli(["--idioma", "es"]) == "es"


def test_idioma_http_prioridad_y_pesos():
    assert i18n.idioma_http() == "es"
    assert i18n.idioma_http(accept_language="en-US,en;q=0.9,es;q=0.8") == "en"
    assert i18n.idioma_http(accept_language="fr-FR, es;q=0.5, en;q=0.4") == "es"
    assert i18n.idioma_http(accept_language="es;q=0.2, en;q=0.9") == "en"
    assert i18n.idioma_http(cookie="eolfi_token=x; eolfi_idioma=es", accept_language="en") == "es"
    assert i18n.idioma_http(lang="en", cookie="eolfi_idioma=es") == "en"
    assert i18n.idioma_http(lang="xx", accept_language="q=;;,") == "es"


def test_todas_las_ayudas_de_subcomandos_tienen_traduccion():
    faltan = [h for h in _ayudas_subcomandos(_parser()) if h not in i18n.CLI_EN]
    assert not faltan, faltan


def test_ayuda_en_ingles_y_castellano_por_defecto(capsys, monkeypatch):
    monkeypatch.delenv("EOLFI_IDIOMA", raising=False)
    with pytest.raises(SystemExit):
        main(["--idioma", "en", "acciones", "-h"])
    assert "Recomputes the log's SHA-256 chain" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["acciones", "-h"])
    assert "Recalcula la cadena SHA-256 del registro" in capsys.readouterr().out


def test_el_resultado_json_no_cambia_con_el_idioma(capsys):
    assert main(["--idioma", "en", "acciones", "verificar"]) == 0
    assert '"nota": "sin registro todavía"' in capsys.readouterr().out


def test_todos_los_errores_fijos_de_la_api_tienen_traduccion():
    fuente = (RAIZ / "eolfi" / "server.py").read_text(encoding="utf-8")
    fijos = set(re.findall(r'ApiError\(\d+,\s*"([^"]+)"', fuente)) | set(re.findall(r'"error":\s*"([^"{}]+)"', fuente))
    faltan = sorted(f for f in fijos if f not in i18n.API_EN)
    assert not faltan, faltan


def test_api_traduce_errores_y_declara_el_idioma(srv):  # noqa: F811
    port, _ = srv
    st, body, cab = req(port, "POST", "/api/cases", body=b"[]", headers={"X-Eolfi": "1", "Content-Type": "application/json"})
    assert st == 400 and body["error"] == "el cuerpo debe ser un objeto JSON" and cab["Content-Language"] == "es"
    st, body, cab = req(port, "POST", "/api/cases?lang=en", body=b"[]",
                        headers={"X-Eolfi": "1", "Content-Type": "application/json"})
    assert body["error"] == "the body must be a JSON object" and cab["Content-Language"] == "en"
    st, body, _ = req(port, "POST", "/api/cases", body=b"[]", headers={
        "X-Eolfi": "1", "Content-Type": "application/json", "Cookie": "eolfi_idioma=en", "Accept-Language": "es"})
    assert body["error"] == "the body must be a JSON object"


def test_panel_sirve_el_script_y_el_diccionario(srv):  # noqa: F811
    port, _ = srv
    st, js, cab = req(port, "GET", "/i18n.js")
    assert st == 200 and b"eolfiT" in js and cab["Content-Type"].startswith("text/javascript")
    st, dic, cab = req(port, "GET", "/i18n-en.json")
    assert st == 200 and dic["Crear proyecto"] == "Create project"


def test_textos_fijos_del_panel_cubiertos_y_diccionario_valido():
    c = i18n_panel.cobertura()
    assert c["faltan"] == [], c["faltan"][:20]
    dic = json.loads((RAIZ / "eolfi" / "web" / "i18n-en.json").read_text(encoding="utf-8"))
    assert all(isinstance(v, str) and v.strip() for v in dic.values())
    # Ninguna clave huérfana: cada texto del diccionario aparece en el panel o en su JS.
    web = "".join((RAIZ / "eolfi" / "web" / n).read_text(encoding="utf-8") for n in
                  ("index.html", "app.js", "cases.js", "eolas-chat.js", "projects.js", "subjects.js", "voz.js"))
    web_norm = i18n_panel.normalizar(web.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"))
    huerfanas = [k for k in dic if k not in web_norm and k not in i18n_panel.textos_panel()
                 and k not in i18n_panel.textos_js()]
    assert not huerfanas, huerfanas[:20]


def test_contenido_marcado_no_se_traduce():
    html = (RAIZ / "eolfi" / "web" / "index.html").read_text(encoding="utf-8")
    for ident in ("chat-log", "eolas-chat-log", "evidence", "incognitas", "case-body"):
        assert re.search(rf'id="{ident}" data-i18n-no', html), ident


def test_textos_del_js_del_panel_cubiertos():
    """C1 (18/11/2026): los avisos y estados que escribe el JS del panel, fijos o con partes variables (plantillas
    con «{}»), están todos en el diccionario inglés y cada plantilla tiene los mismos huecos que su traducción."""
    c = i18n_panel.cobertura_js()
    assert c["textos"] > 250 and c["faltan"] == [], c["faltan"][:20]
    dic = i18n_panel.diccionario()
    for k, v in dic.items():
        assert k.count("{}") == len(re.findall(r"\{\d*\}", v)), (k, v)


def test_traducir_por_plantilla():
    cat = {"modo inválido: {}": "invalid mode: {}", "{} de {}": "{1} by {0}", "carpeta": "folder",
           "{} fuera de {}": "{} outside {}", "x": "y"}
    assert i18n.traducir("modo inválido: rápido", "en", cat) == "invalid mode: rápido"
    assert i18n.traducir("modo inválido: rápido", "es", cat) == "modo inválido: rápido"
    assert i18n.traducir("a de b", "en", cat) == "b by a"
    assert i18n.traducir("carpeta fuera de C:/x", "en", cat) == "folder outside C:/x"   # hueco traducido
    assert i18n.traducir("x", "en", cat) == "y" and i18n.traducir("otra cosa", "en", cat) == "otra cosa"


def test_errores_con_partes_variables_de_la_api_tienen_plantilla():
    """Cada error de eolfi/server.py escrito con f-string tiene su plantilla («{}» en cada hueco) en el catálogo,
    salvo los que son solo el texto de una excepción."""
    fuente = (RAIZ / "eolfi" / "server.py").read_text(encoding="utf-8")
    trozos = re.findall(r'(?:ApiError\(\d+,\s*|"error":\s*)((?:f"[^"]*"\s*)+)', fuente)
    plantillas = {re.sub(r"\{[^{}]*\}", "{}", "".join(re.findall(r'f"([^"]*)"', t))) for t in trozos}
    plantillas = {p for p in plantillas if re.search(r"[a-záéíóúñ]{3}", p.replace("{}", ""))}
    assert len(plantillas) >= 15, plantillas
    faltan = sorted(p for p in plantillas if p not in i18n.API_EN)
    assert not faltan, faltan


def test_api_traduce_un_error_con_parte_variable(srv):  # noqa: F811
    port, _ = srv
    st, body, cab = req(port, "GET", "/api/incognitas?status=raro&lang=en")
    assert st == 400 and body["error"] == "invalid status: raro" and cab["Content-Language"] == "en"
    st, body, _ = req(port, "GET", "/api/incognitas?status=raro")
    assert body["error"] == "status inválido: raro"


def _ayudas_argumentos(p: argparse.ArgumentParser) -> list[str]:
    out = []
    for a in p._actions:
        if isinstance(a, argparse._SubParsersAction):
            for sub in a.choices.values():
                out += _ayudas_argumentos(sub)
        elif a.help and a.help is not argparse.SUPPRESS and a.dest not in ("help", "version"):
            out.append(a.help)
    return out


def test_todas_las_ayudas_de_argumentos_tienen_traduccion():
    """C1 (18/11/2026): también la ayuda de cada argumento (antes faltaban; las de argparse ya vienen en inglés)."""
    ayudas = _ayudas_argumentos(_parser())
    assert len(ayudas) > 200
    faltan = sorted({h for h in ayudas if h not in i18n.CLI_EN})
    assert not faltan, faltan
