"""D2 (18/11/2026): destino Go del generador (servidor web y API REST con solo la biblioteca estándar)."""
import json
import re
import shutil
from collections import Counter

import pytest

from eolfi.core.evidence import EvidenceStore
from eolfi.flows.learn_flow import run_repo, run_web
from eolfi.flows.project_flow import _TARGET_WORDS
from eolfi.generador.generators import generate
from eolfi.generador.spec import TARGETS, _choose_target, build_spec
from tests.fixtures import build_repo, build_site


@pytest.fixture(scope="module")
def fuentes(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("fuentes-go")
    s = EvidenceStore(":memory:")
    subs = [run_web(str(build_site(tmp / "site")), s)["subject"], run_repo(str(build_repo(tmp / "repo")), s)["subject"]]
    return s, subs


def _generar(fuentes, out, name="Tienda Go", idioma="es", **opciones):
    s, subs = fuentes
    spec = build_spec(s, subs, name=name, target="go")
    spec["options"] = {"auth": False, "db": "memory", **opciones}
    spec["idioma"] = idioma
    generate(spec, out)
    return out, spec


def test_go_es_un_destino_y_se_elige_con_un_backend_en_go():
    assert "go" in TARGETS
    assert _choose_target(Counter({"Gin": 2}), {}, Counter()) == "go"
    assert _choose_target(Counter({"Echo": 1, "React": 1}), {}, Counter()) != "go"   # con frontend, no
    assert _choose_target(Counter({"Gin": 1, "FastAPI": 2}), {}, Counter()) == "fastapi"
    palabras = lambda t: [d for rx, d in _TARGET_WORDS if re.search(rx, t, re.IGNORECASE)]
    assert "go" in palabras("quiero una API en Go") and "go" in palabras("hazlo con golang")
    assert "go" not in palabras("let's go to the shop")


def test_proyecto_go_sin_dependencias_y_con_la_web_dentro(tmp_path, fuentes):
    out, spec = _generar(fuentes, tmp_path / "p", name='Tienda "Go" 100% \\ fin')
    gomod = (out / "go.mod").read_text(encoding="utf-8")
    assert gomod.startswith("module ") and "require" not in gomod and "go 1.22" in gomod
    assert not (out / "go.sum").exists()
    for f in ("main.go", "server.go", "store.go", "server_test.go", "web/index.html", "web/js/main.js",
              "DESPLIEGUE.md", "README.md", ".github/workflows/ci.yml"):
        assert (out / f).is_file(), f
    server = (out / "server.go").read_text(encoding="utf-8")
    assert "//go:embed web" in server and "http.MaxBytesReader" in server
    for r in spec["api"]["resources"] or ["items"]:
        assert json.dumps(r) in server
    for k in ("Content-Security-Policy", "X-Frame-Options"):
        assert f'"{k}"' in server
    # El título va como literal de Go bien escapado (comillas, % y barra invertida).
    main = (out / "main.go").read_text(encoding="utf-8")
    assert "const appTitle = " + json.dumps(spec["title"], ensure_ascii=False) in main
    assert 'log.Printf("%s en http://%s", appTitle' in main
    # Sin inicio de sesión en este destino: la web no ofrece un formulario que no funcionaría.
    assert "data-login-form" not in "".join(p.read_text(encoding="utf-8") for p in (out / "web").glob("*.html"))
    assert "/bin/" in (out / ".gitignore").read_text(encoding="utf-8")
    assert "setup-go" in (out / ".github/workflows/ci.yml").read_text(encoding="utf-8")


def test_proyecto_go_en_ingles(tmp_path, fuentes):
    out, _ = _generar(fuentes, tmp_path / "en", idioma="en")
    server = (out / "server.go").read_text(encoding="utf-8")
    assert '"Not found"' in server and '"Invalid JSON"' in server and "No encontrado" not in server
    assert 'lang="en"' in (out / "server_test.go").read_text(encoding="utf-8")
    assert (out / "DEPLOYMENT.md").is_file() and not (out / "DESPLIEGUE.md").exists()


def test_docker_go(tmp_path, fuentes):
    s, subs = fuentes
    spec = build_spec(s, subs, name="Con Docker", target="go")
    spec["conventions"]["docker"] = True
    spec["options"] = {"auth": False, "db": "memory"}
    generate(spec, tmp_path / "d")
    docker = (tmp_path / "d" / "Dockerfile").read_text(encoding="utf-8")
    assert "go build" in docker and "distroless" in docker and "HOST=0.0.0.0" in docker


@pytest.mark.skipif(not shutil.which("go"), reason="requiere Go")
@pytest.mark.parametrize("idioma", ["es", "en"])
def test_verificacion_real_con_go(tmp_path, fuentes, idioma):
    """go vet, go test, go build y la prueba de humo del ejecutable, sin red (GOPROXY=off), en la verificación
    aislada (carpeta personal temporal), como la usa assist."""
    from eolfi.generador.verify import verify

    out, _ = _generar(fuentes, tmp_path / idioma, idioma=idioma)
    r = verify(out, "go", sandbox=True)
    assert r["ok"], [(st["step"], st["exit"], st["tail"][-800:]) for st in r["steps"]]
    assert [st["step"].split(" (")[0].split(":")[0] for st in r["steps"]] == [
        "revisar el código", "pruebas", "compilar el ejecutable", "prueba de humo"]
