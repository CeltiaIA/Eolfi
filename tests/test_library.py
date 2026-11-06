import json

from eolfi.library import AlexandriaLibrary


def _library(tmp_path, entries):
    root = tmp_path / "Alejandria"
    (root / "manifests").mkdir(parents=True)
    (root / "corpus" / "texto" / "Eolfi").mkdir(parents=True)
    (root / "corpus" / "codigo" / "Eolfi" / "backups").mkdir(parents=True)
    (root / "corpus" / "texto" / "Eolfi" / "guia.md").write_text(
        "Alejandría: consultar documentación de configuración local.\n", encoding="utf-8")
    (root / "corpus" / "codigo" / "Eolfi" / "backups" / "old.py").write_text(
        "documentación configuración antigua", encoding="utf-8")
    (tmp_path / "outside.md").write_text("documentación configuración fuera", encoding="utf-8")
    (root / "manifests" / "corpus.index.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return root


def test_search_reads_indexed_curated_corpus_and_skips_backups_and_traversal(tmp_path):
    entries = [
        {"path": "corpus/texto/Eolfi/guia.md"},
        {"path": "corpus/codigo/Eolfi/backups/old.py"},
        {"path": "../outside.md"},
    ]
    root = _library(tmp_path, entries)
    result = AlexandriaLibrary(root).search("CONFIGURACION", 20)
    assert len(result["resultados"]) == 1
    assert result["resultados"][0]["ruta"] == "corpus/texto/Eolfi/guia.md"
    assert "configuración" in result["resultados"][0]["fragmento"].lower()


def test_search_rejects_empty_and_bounds_query(tmp_path):
    root = _library(tmp_path, [])
    for query in ("", "x" * 301):
        try:
            AlexandriaLibrary(root).search(query)
        except ValueError:
            pass
        else:
            raise AssertionError("consulta inválida aceptada")


def test_read_fetches_only_indexed_document_and_rejects_traversal(tmp_path):
    root = _library(tmp_path, [{"path": "corpus/texto/Eolfi/guia.md"}])
    library = AlexandriaLibrary(root)
    result = library.read("corpus/texto/Eolfi/guia.md")
    assert "documentación de configuración" in result["contenido"]
    assert result["recortado"] is False
    for path in ("../outside.md", "corpus/codigo/Eolfi/backups/old.py"):
        try:
            library.read(path)
        except ValueError:
            pass
        else:
            raise AssertionError("se aceptó una ruta fuera de lo permitido")


def test_read_returns_bounded_chunks(tmp_path):
    root = _library(tmp_path, [{"path": "corpus/texto/Eolfi/guia.md"}])
    doc = root / "corpus" / "texto" / "Eolfi" / "guia.md"
    doc.write_text("A" * 31_000, encoding="utf-8")
    library = AlexandriaLibrary(root)
    first = library.read("corpus/texto/Eolfi/guia.md")
    second = library.read("corpus/texto/Eolfi/guia.md", first["siguiente_desde"])
    assert len(first["contenido"]) == 30_000 and first["recortado"]
    assert second["contenido"] == "A" * 1_000 and not second["recortado"]
