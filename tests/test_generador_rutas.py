"""Confinamiento de rutas y del contexto enviado al asistente."""
from pathlib import Path

import pytest

from eolfi.generador.assist import collect_context
from eolfi.generador.generators import _check_spec, _writer


def _link(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"el sistema no permite crear symlinks: {exc}")


def test_contexto_no_lee_archivos_enlazados_fuera_del_proyecto(tmp_path):
    root = tmp_path / "proyecto"
    (root / "src").mkdir(parents=True)
    (root / "src" / "propio.py").write_text("print('propio')", encoding="utf-8")
    secret = tmp_path / "secreto.py"
    secret.write_text("CLAVE_PRIVADA", encoding="utf-8")
    _link(root / "src" / "enlace.py", secret)

    tree, files = collect_context(root, "cli")
    assert "src/propio.py" in tree and files["src/propio.py"] == "print('propio')"
    assert "src/enlace.py" not in tree and "CLAVE_PRIVADA" not in str(files)


def test_writer_rechaza_traversal_y_symlink_antes_de_escribir(tmp_path):
    root = tmp_path / "proyecto"
    root.mkdir()
    outside = tmp_path / "fuera.txt"
    outside.write_text("original", encoding="utf-8")
    _link(root / "enlace.txt", outside)
    writer = _writer(root, [])

    for rel in ("../fuera.txt", "enlace.txt"):
        with pytest.raises(ValueError):
            writer(rel, "cambio")
    assert outside.read_text(encoding="utf-8") == "original"
    writer("css/normal.css", "body {}")
    assert (root / "css" / "normal.css").is_file()


def test_writer_rechaza_directorio_enlazado(tmp_path):
    root, outside = tmp_path / "proyecto", tmp_path / "fuera"
    root.mkdir()
    outside.mkdir()
    _link(root / "css", outside, directory=True)
    with pytest.raises(ValueError):
        _writer(root, [])("css/a.css", "body {}")
    assert not (outside / "a.css").exists()


@pytest.mark.parametrize("pages", [["home", "../escape"], ["home", "x/y"], ["home", "a.html"], "home"])
def test_spec_manual_rechaza_paginas_inseguras(pages):
    with pytest.raises(ValueError, match="páginas"):
        _check_spec({"title": "Demo", "pages": pages, "api": {"resources": []}})
