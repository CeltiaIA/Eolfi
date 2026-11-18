"""D2 (18/11/2026): destino Rust del generador (comando de línea de comandos con serde y serde_json)."""
import os
import re
import shutil
from collections import Counter
from pathlib import Path

import pytest

from eolfi import compat_toml as tomllib
from eolfi.core.evidence import EvidenceStore
from eolfi.flows.learn_flow import run_repo, run_web
from eolfi.flows.project_flow import interpret
from eolfi.generador.generators import generate
from eolfi.generador.generators_rust import command_name
from eolfi.generador.spec import TARGETS, _choose_target, _platforms_for, build_spec
from tests.fixtures import build_repo, build_site


@pytest.fixture(scope="module")
def fuentes(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("fuentes-rust")
    s = EvidenceStore(":memory:")
    subs = [run_web(str(build_site(tmp / "site")), s)["subject"], run_repo(str(build_repo(tmp / "repo")), s)["subject"]]
    return s, subs


def _generar(fuentes, out, name="Notas Rust", idioma="es"):
    s, subs = fuentes
    spec = build_spec(s, subs, name=name, target="rust")
    spec["title"] = name   # tal cual (build_spec lo normalizaría)
    spec["options"] = {"auth": False, "db": "memory"}
    spec["idioma"] = idioma
    generate(spec, out)
    return out, spec


def test_rust_es_un_destino_de_escritorio_y_se_elige_con_clap():
    assert "rust" in TARGETS and _platforms_for("rust") == ["windows", "macos", "linux"]
    assert _choose_target(Counter({"clap": 1}), {}, Counter()) == "rust"
    assert _choose_target(Counter({"Click": 2, "clap": 1}), {}, Counter()) == "cli"
    assert interpret("una línea de comandos en Rust")["target"] == "rust"
    assert interpret("escritorio con Tauri y Rust")["target"] == "tauri"


@pytest.mark.parametrize("nombre,esperado", [("mi-app", "mi-app"), ("123", "app-123"), ("std", "app-std"),
                                             ("serde", "app-serde"), ("match", "app-match"), ("a--b", "a-b")])
def test_nombre_del_comando_valido_para_cargo(nombre, esperado):
    assert command_name({"name": nombre}) == esperado


def test_proyecto_rust(tmp_path, fuentes):
    out, spec = _generar(fuentes, tmp_path / "p", name="Notas: Rust (v2)! Sí")
    cargo = tomllib.loads((out / "Cargo.toml").read_text(encoding="utf-8"))
    assert set(cargo["dependencies"]) == {"serde", "serde_json"}
    cmd = cargo["package"]["name"]
    for f in ("src/lib.rs", "src/main.rs", "tests/cli.rs", "README.md", "DESPLIEGUE.md", ".github/workflows/ci.yml"):
        assert (out / f).is_file(), f
    lib = (out / "src/lib.rs").read_text(encoding="utf-8")
    # El título va en una constante (no dentro del formato); la especificación ya limita sus caracteres.
    assert 'pub const TITLE: &str = "Notas: Rust (v2)! Sí";' in lib
    for r in spec["api"]["resources"] or ["items"]:
        assert f'"{re.sub(r"[^a-z0-9_]", "_", r.lower())}"' in lib
    assert f'env!("CARGO_BIN_EXE_{cmd}")' in (out / "tests/cli.rs").read_text(encoding="utf-8")
    assert "target/" in (out / ".gitignore").read_text(encoding="utf-8")
    ci = (out / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "rust-toolchain" in ci and "--locked" in ci and "macos-latest" in ci
    assert not (out / "Dockerfile").exists()


def test_proyecto_rust_en_ingles(tmp_path, fuentes):
    out, _ = _generar(fuentes, tmp_path / "en", idioma="en")
    lib = (out / "src/lib.rs").read_text(encoding="utf-8")
    assert "Usage:" in lib and "unknown command" in lib and "orden desconocida" not in lib
    assert (out / "DEPLOYMENT.md").is_file()


def _serde_en_cache() -> bool:
    home = Path(os.environ.get("CARGO_HOME") or Path.home() / ".cargo")
    cache = list((home / "registry" / "cache").glob("*/"))
    return all(any(c.glob(f"{name}-1.*.crate") for c in cache) for name in ("serde", "serde_json", "serde_derive"))


@pytest.mark.skipif(not shutil.which("cargo"), reason="requiere Rust (cargo)")
@pytest.mark.parametrize("idioma", ["es", "en"])
def test_verificacion_real_con_cargo(tmp_path, fuentes, idioma, monkeypatch):
    """cargo build --release, cargo test y el ejecutable compilado (`--json info`), en la verificación aislada.
    Si la caché de Cargo ya tiene serde y serde_json, sin red (CARGO_NET_OFFLINE); si no (CI limpia), crates.io."""
    from eolfi.generador.verify import verify

    if _serde_en_cache():
        monkeypatch.setenv("CARGO_NET_OFFLINE", "true")
    out, _ = _generar(fuentes, tmp_path / idioma, idioma=idioma)
    r = verify(out, "rust", sandbox=True)
    assert r["ok"], [(st["step"], st["exit"], st["tail"][-1500:]) for st in r["steps"]]
    assert len(r["steps"]) == 3 and (out / "Cargo.lock").is_file()
