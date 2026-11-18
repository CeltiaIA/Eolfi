"""C4 (18/11/2026): idioma de los proyectos generados (--idioma-proyecto es|en)."""
import re
import shutil

import pytest

from eolfi.core.evidence import EvidenceStore
from eolfi.flows.create_flow import create_project
from eolfi.flows.learn_flow import run_repo, run_web
from eolfi.generador import textos
from eolfi.generador.generators import generate
from eolfi.generador.spec import TARGETS, build_spec
from tests.fixtures import build_repo, build_site

# Líneas de código (no comentarios ni docstrings) que pueden llevar letras del castellano en inglés:
# el dato de prueba de Unicode del destino cli.
PERMITIDAS = ("Canción ñandú",)
COMENTARIO = re.compile(r"""^\s*(#|//|/\*|\*|<!--|-|\"\"\"|''')""")


@pytest.fixture(scope="module")
def fuentes(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("fuentes")
    s = EvidenceStore(":memory:")
    subs = [run_web(str(build_site(tmp / "site")), s)["subject"], run_repo(str(build_repo(tmp / "repo")), s)["subject"]]
    return s, subs


def _generar(fuentes, out, target, idioma=None, db="memory"):
    s, subs = fuentes
    spec = build_spec(s, subs, name="Mi Tienda", target=target)
    spec["conventions"]["auth"] = True
    spec["options"] = {"auth": True, "db": db}
    if idioma is not None:
        spec["idioma"] = idioma
    generate(spec, out)
    return out


def _textos(out):
    for f in sorted(out.rglob("*")):
        if f.is_file():
            try:
                yield f, f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue


def test_traducir_respeta_palabras_y_prefiere_la_frase_mas_larga():
    assert textos.traducir("Inicio", "es") == "Inicio"
    assert textos.traducir("<a>Inicio</a> <b>Inicios</b>", "en") == "<a>Home</a> <b>Inicios</b>"
    assert textos.traducir("Inicia sesión para añadir datos.", "en") == "Sign in to add data."
    assert textos.traducir('"Añadir"', "en") == '"Add"'
    # Un comentario con «Inicio de sesión» no se convierte en «Home de sesión».
    assert "Home de" not in textos.traducir("// Inicio de sesión (solo si el proyecto se generó con --auth). "
                                           "El token vive en", "en")


def test_idioma_no_admitido(tmp_path, fuentes):
    with pytest.raises(ValueError, match="idioma"):
        _generar(fuentes, tmp_path / "x", "static", idioma="fr")


def test_castellano_por_defecto_y_sin_cambios(tmp_path, fuentes):
    a = _generar(fuentes, tmp_path / "a", "static")
    b = _generar(fuentes, tmp_path / "b", "static", idioma="es")
    for f, texto in _textos(a):
        if f.name == "eolfi.spec.json":   # la de «b» anota "idioma": "es"; el resto es idéntico
            continue
        assert texto == (b / f.relative_to(a)).read_text(encoding="utf-8"), f
    assert '<html lang="es">' in (a / "index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("target", TARGETS)
def test_en_ingles_no_queda_castellano_en_el_codigo(tmp_path, fuentes, target):
    """Interfaz, mensajes de error y nombres de las pruebas generadas en inglés; los comentarios siguen en
    castellano (pendiente C4). README y DEPLOYMENT.md, aparte (test_readme_y_receta_en_ingles)."""
    restos = []
    for db in ("memory", "sqlite"):
        out = _generar(fuentes, tmp_path / db, target, idioma="en", db=db)
        for f, texto in _textos(out):
            if f.name in textos.NO_TRADUCIR:
                continue
            docstring = False
            for linea in texto.splitlines():
                abre = f.suffix == ".py" and linea.count('"""') % 2 == 1
                if docstring or abre:
                    docstring ^= abre
                    continue
                codigo = re.split(r"\s(?:#|//) ", linea)[0]
                if (re.search(r"[áéíóúñ¿¡]", codigo) and not COMENTARIO.match(linea)
                        and not any(p in linea for p in PERMITIDAS)):
                    restos.append(f"{f.relative_to(out)}: {linea.strip()}")
            assert 'lang="es"' not in texto and '"lang": "es"' not in texto, f
            for frase in ("Saltar al contenido", "Página no encontrada", "Datos en vivo", "Preguntas frecuentes",
                          "gestiona {res}", "lista {res}", "No hay migraciones", "Bearer nada", ">Entrar<"):
                assert frase not in texto, (f, frase)
    assert not restos, restos


def test_la_portada_y_sus_pruebas_cambian_a_la_vez(tmp_path, fuentes):
    out = _generar(fuentes, tmp_path / "s", "static", idioma="en")
    html = (out / "index.html").read_text(encoding="utf-8")
    assert '<html lang="en">' in html and "Skip to content" in html and ">Home<" in html
    pruebas = "\n".join(t for f, t in _textos(out) if "test" in f.name)
    assert '<html lang="en">' in pruebas
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "## Run" in readme and "## Verify" in readme and "DEPLOYMENT.md" in readme


@pytest.mark.parametrize("target", TARGETS)
def test_readme_y_receta_en_ingles(tmp_path, fuentes, target):
    """C4 (18/11/2026): en inglés, README.md y DEPLOYMENT.md enteros en inglés (sin DESPLIEGUE.md) y con las mismas
    órdenes, variables y cabeceras que la versión en castellano."""
    from eolfi.generador.despliegue import VARIABLES, VARIABLES_EN

    en = _generar(fuentes, tmp_path / "en", target, idioma="en")
    es = _generar(fuentes, tmp_path / "es", target, idioma="es")
    assert not (en / "DESPLIEGUE.md").exists() and not (es / "DEPLOYMENT.md").exists()
    for nombre_en, nombre_es in (("README.md", "README.md"), ("DEPLOYMENT.md", "DESPLIEGUE.md")):
        texto_en = (en / nombre_en).read_text(encoding="utf-8")
        texto_es = (es / nombre_es).read_text(encoding="utf-8")
        # Fuera de los datos del proyecto (nombre de la fuente, título), nada en castellano.
        limpio = texto_en.replace("Mi Tienda", "").replace("Inicio", "")
        for linea in limpio.splitlines():
            assert not re.search(r"[áéíóúñ¿¡]", linea) or "`local:" in linea or "`repo:" in linea, (nombre_en, linea)
        for palabra in ("Arrancar", "Verificar", "Publicar", "Compilar", "Despliegue", "Cabeceras", "Variables de"):
            assert palabra not in texto_en, (nombre_en, palabra)
        # Mismas órdenes: cada bloque de código coincide salvo los comentarios traducidos.
        bloques = lambda s: [re.sub(r"\s+#.*", "", b).replace("<Proyecto>", "<Project>").replace("<comando>", "<command>")
                             for b in re.findall(r"```[a-z]*\n(.*?)```", s, re.DOTALL)]
        assert bloques(texto_en) == bloques(texto_es), nombre_en
    receta = (en / "DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "the deployment (hosting, proxy and HTTPS) has not been tested by Eolfi" in receta
    citadas = set(re.findall(r"\| `([A-Z][A-Z0-9_]+)` \|", receta.split("## Security headers")[0]))
    assert citadas == {k for k, _ in VARIABLES.get(target, [])} == set(VARIABLES_EN.get(target, {}))


def test_cli_y_api_pasan_el_idioma(monkeypatch, tmp_path):
    from eolfi import cli
    from eolfi.flows import create_flow

    assert cli._parser().parse_args(["create", "--from", "f", "--out", "d"]).idioma_proyecto == "es"
    assert cli._parser().parse_args(["create", "--from", "f", "--out", "d", "--idioma-proyecto", "en"]
                                    ).idioma_proyecto == "en"
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["create", "--from", "f", "--out", "d", "--idioma-proyecto", "fr"])
    with pytest.raises(ValueError, match="idioma"):
        create_flow.create_project(["x"], EvidenceStore(":memory:"), tmp_path / "o", idioma="fr", do_verify=False)


@pytest.mark.skipif(not shutil.which("node"), reason="requiere Node.js")
def test_proyecto_estatico_en_ingles_se_verifica(tmp_path):
    s = EvidenceStore(":memory:")
    site = build_site(tmp_path / "site")
    r = create_project([str(site)], s, tmp_path / "nuevo", name="Site", target="static", do_verify=True,
                       idioma="en")
    assert r["verification"]["ok"], r["verification"]
    assert '<html lang="en">' in (tmp_path / "nuevo" / "index.html").read_text(encoding="utf-8")
