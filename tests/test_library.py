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


def test_search_ranks_definition_and_whole_words_first(tmp_path):
    """12/11/2026: «class AlexandriaLibrary» devolvía componentes con muchas líneas «class» antes que la definición."""
    code = tmp_path / "Alejandria" / "corpus" / "codigo" / "Eolfi"
    root = _library(tmp_path, [{"path": f"corpus/codigo/Eolfi/{n}"} for n in ("ui.tsx", "uso.py", "lib.py", "otro.py")])
    code.mkdir(parents=True, exist_ok=True)
    (code / "ui.tsx").write_text("\n".join(f'<div className="class-{i}">class</div>' for i in range(200)), encoding="utf-8")
    (code / "uso.py").write_text("from lib import Biblioteca\nb = Biblioteca('x')\nBiblioteca.leer(b)\n", encoding="utf-8")
    (code / "lib.py").write_text("import os\n\n\nclass Biblioteca:\n    pass\n\n\ndef _normal(t):\n    return t\n", encoding="utf-8")
    (code / "otro.py").write_text("def _normalize_all(x):\n    return _normalize_all(x)\n# _normalize _normalize\n", encoding="utf-8")
    lib = AlexandriaLibrary(root)
    first = lib.search("class Biblioteca")["resultados"][0]
    assert first["ruta"].endswith("lib.py") and first["fragmento"].startswith("4: class Biblioteca:")
    assert lib.search("_normal")["resultados"][0]["ruta"].endswith("lib.py")        # palabra completa, no «_normalize»
    assert lib.search("def _normal")["resultados"][0]["ruta"].endswith("lib.py")


def test_search_prefiere_la_definicion_a_un_archivo_que_repite_el_contexto(tmp_path):
    """13/11/2026: «MAX_READ_CHARS eolfi» devolvía el archivo del examen (con «eolfi» cientos de veces) antes que el
    que define la constante, y el motor contestaba con otra constante de ese archivo."""
    code = tmp_path / "Alejandria" / "corpus" / "codigo" / "Eolfi" / "eolfi"
    root = _library(tmp_path, [{"path": f"corpus/codigo/Eolfi/eolfi/{n}"} for n in ("examen.py", "library.py")])
    code.mkdir(parents=True, exist_ok=True)
    (code / "examen.py").write_text("from eolfi import x  # eolfi\n" * 50 + "PROMPT = 'Lee el archivo de Eolfi que define "
                                    "MAX_READ_CHARS'\nLIMITE = 300\n", encoding="utf-8")
    (code / "library.py").write_text("import json\n\nMAX_READ_CHARS = 30_000\n\nchunk = MAX_READ_CHARS\n", encoding="utf-8")
    first = AlexandriaLibrary(root).search("MAX_READ_CHARS eolfi")["resultados"][0]
    assert first["ruta"].endswith("library.py") and "MAX_READ_CHARS = 30_000" in first["fragmento"]


def test_la_definicion_gana_al_enunciado_entre_comillas_y_a_los_comentarios(tmp_path):
    """14/11/2026: «definición de la clase AlexandriaLibrary» devolvía el archivo del EXAMEN (la frase literal dentro de
    un texto entre comillas) y un comentario con la frase exacta impedía contar la definición del propio archivo."""
    code = tmp_path / "Alejandria" / "corpus" / "codigo" / "Eolfi" / "eolfi"
    root = _library(tmp_path, [{"path": f"corpus/codigo/Eolfi/eolfi/{n}"} for n in ("examen.py", "biblioteca.py")])
    code.mkdir(parents=True, exist_ok=True)
    (code / "examen.py").write_text(
        'CASOS = [{"prompt": "Encuentra la '
        'definición de la clase Biblioteca y "\n'
        '           "definición de la clase Biblioteca otra vez"}]\n' * 20, encoding="utf-8")
    (code / "biblioteca.py").write_text(
        "# Aquí está la definición de la clase Biblioteca (comentario con la frase exacta)\n"
        "import os\n\n\nclass Biblioteca:\n    pass\n", encoding="utf-8")
    first = AlexandriaLibrary(root).search("definición de la clase Biblioteca")["resultados"][0]
    assert first["ruta"].endswith("biblioteca.py")
