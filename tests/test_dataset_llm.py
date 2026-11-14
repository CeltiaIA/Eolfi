"""Conjunto de datos para entrenar modelos a partir de Alejandría (14/11/2026)."""
import json
from pathlib import Path

from eolfi.dataset_llm import MAX_BYTES, _normalized_sha, build, clean_text


def _library(tmp_path):
    lib = tmp_path / "Alejandria"
    (lib / "manifests").mkdir(parents=True)
    entries = []

    def add(rel, content, tipo, lenguaje, sha=None):
        f = lib / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        text = content if isinstance(content, str) else content.decode("utf-8", "replace")
        entries.append({"sha256": sha or _normalized_sha(text), "tipo": tipo, "lenguaje": lenguaje,
                        "path": rel.replace("/", "\\"), "bytes": f.stat().st_size})

    code = "def suma(a, b):\n    \"\"\"Suma dos números.\"\"\"\n    return a + b\n"
    add("corpus/codigo/Eolfi/eolfi/suma.py", code, "codigo", "py")
    add("corpus/codigo/Force/otra/suma.py", code.replace("    ", "        ").upper(), "codigo", "py")   # casi duplicado
    add("corpus/codigo/Eolfi/.codex-tmp/pytest-of-x/pytest-3/t0/evil.bat", "@echo off\r\necho pwned > x\r\n" * 3,
        "codigo", "bat")                                                                             # carga de prueba
    add("corpus/codigo/Eolfi/generated/app/main.py", "print('proyecto generado por una prueba')\n" * 3, "codigo", "py")
    add("corpus/codigo/Eolfi/eolfi/alterado.py", "x = 1  # contenido distinto del indexado\n" * 3, "codigo", "py",
        sha="0" * 64)
    add("corpus/codigo/Eolfi/eolfi/enorme.py", "x = 1\n" * (MAX_BYTES // 6 + 10), "codigo", "py")
    add("corpus/texto/Eolfi/guia.md", "# Guía\n\nEscribe a ana@example.com. El proyecto está en "
        "C:\\Users\\mejil\\proyectos\\eolfi y en /home/juan/eolfi.\n", "texto", "md")
    good = {"esquema": "eolfi.ejemplo-entrenamiento/1", "id": "a", "tipo": "codigo", "caso": "suma",
            "version_caso": "v1", "calidad": "a-la-primera",
            "mensajes": [{"role": "user", "content": "Escribe suma(a, b)."},
                         {"role": "assistant", "content": "```python\ndef suma(a, b):\n    return a + b\n```"}],
            "herramientas_usadas": [], "verificacion": {"pruebas": "assert suma(1, 2) == 3", "esperado": None,
                                                         "salida": "EOLFI-OK\n"},
            "motor": {"perfil": "gemma", "gguf": "g.gguf", "cuantizacion": "Q5_K_M"},
            "procedencia": {"ronda": "r", "maquina": "MI-EQUIPO"}}
    rule = {**good, "id": "b", "tipo": "herramientas", "caso": "buscar_definicion",
            "mensajes": [{"role": "user", "content": "¿Dónde se define AlexandriaLibrary?"},
                         {"role": "assistant", "content": '{"ruta": "corpus/codigo/Eolfi/eolfi/library.py"}'}],
            "verificacion": {"pruebas": None, "esperado": None, "salida": None}}
    unverified = {**rule, "id": "c", "mensajes": [rule["mensajes"][0],
                                                  {"role": "assistant", "content": '{"ruta": "otro.py"}'}]}
    duplicate = {**good, "id": "d", "motor": {"perfil": "gemma_q4"}}
    sft = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in (good, rule, unverified, duplicate))
    add("corpus/datos/Eolfi-aportes/corpus-entrenamiento/codigo/a-la-primera/suma.jsonl", sft, "datos", "jsonl")
    add("corpus/datos/Eolfi-aportes/examenes/ronda-1.jsonl", json.dumps({"esquema": "eolfi.examen-motor/1"}) + "\n",
        "datos", "jsonl")
    (lib / "manifests" / "corpus.index.json").write_text(
        json.dumps({"generated_utc": "2026-11-14T00:00:00Z", "entries": entries}), encoding="utf-8")
    return lib


def _rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


def test_conjunto_verificado_sin_duplicados_y_con_privacidad(tmp_path):
    lib = _library(tmp_path)
    report = build(lib)
    out = Path(report["salida"])
    assert out == lib / "datasets" / "llm-eolfi"
    code = _rows(out / "pretrain-codigo.jsonl")
    assert [r["metadata"]["ruta"] for r in code] == ["eolfi/suma.py"]            # solo el bueno
    assert code[0]["text"].startswith("def suma") and code[0]["metadata"]["sha256"]
    excl = report["excluidos"]
    assert excl["temporal, prueba, copia de seguridad o generado"] == 2                               # evil.bat y el generado
    assert excl["casi duplicado (solo cambian espacios o mayúsculas)"] == 1
    assert excl["no coincide con el SHA-256 del índice"] == 1
    assert excl[f"mayor de {MAX_BYTES} bytes"] == 1
    assert excl["datos que no son ejemplos de entrenamiento (exámenes)"] == 1
    text = _rows(out / "pretrain-texto.jsonl")[0]
    assert "ana@example.com" not in text["text"] and "mejil" not in text["text"] and "juan" not in text["text"]
    assert "<usuario>" in text["text"] and text["metadata"]["redactado"] is True
    sft = _rows(out / "sft-chat.jsonl")
    assert [r["metadata"]["caso"] for r in sft] == ["suma", "buscar_definicion"]
    assert [m["role"] for m in sft[0]["messages"]] == ["user", "assistant"]
    assert sft[0]["metadata"]["verificacion"] == "pruebas ejecutadas"
    assert sft[1]["metadata"]["verificacion"] == "regla de la tarea"             # vuelta a comprobar aquí
    assert excl["sft: sin verificación superada"] == 1 and excl["sft: duplicado"] == 1
    assert "MI-EQUIPO" not in (out / "sft-chat.jsonl").read_text(encoding="utf-8")   # sin el nombre de la máquina
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["archivos"]["sft-chat.jsonl"]["registros"] == 2
    import hashlib
    assert manifest["archivos"]["pretrain-codigo.jsonl"]["sha256"] == hashlib.sha256(
        (out / "pretrain-codigo.jsonl").read_bytes()).hexdigest()
    assert "Conjunto de datos LLM" in (out / "README.md").read_text(encoding="utf-8")


def test_en_seco_no_escribe_y_regenerar_sustituye_de_golpe(tmp_path):
    lib = _library(tmp_path)
    dry = build(lib, dry_run=True)
    assert dry["salida"] is None and not (lib / "datasets").exists()
    build(lib)
    (lib / "datasets" / "llm-eolfi" / "viejo.txt").write_text("resto", encoding="utf-8")
    build(lib)                                                                    # se regenera entero
    assert not (lib / "datasets" / "llm-eolfi" / "viejo.txt").exists()
    assert not list((lib / "datasets").glob(".llm-eolfi-*")) and not (lib / "datasets" / "llm-eolfi.anterior").exists()


def test_rutas_de_usuario_y_datos_personales():
    out, changed = clean_text(r"C:\Users\Ana\x y /home/bob/y y /Users/eva/z; correo ana@example.com")
    assert changed and "Ana" not in out and "bob" not in out and "eva" not in out and "ana@example.com" not in out
    assert clean_text("sin datos personales")[1] is False


def test_la_cuenta_del_equipo_se_oculta_tambien_fuera_de_las_rutas(monkeypatch):
    """14/11/2026: quedaban «pytest-of-<cuenta>» y «EQUIPO/<cuenta>» (con barra invertida) en la documentación."""
    monkeypatch.setenv("USERNAME", "pepito")
    monkeypatch.setenv("USER", "pepito")
    monkeypatch.setattr("getpass.getuser", lambda: "pepito")
    out, _ = clean_text(r"pytest-of-pepito/pytest-3 y CELTIA\pepito, S4U; pepitorro no es la cuenta")
    assert "pytest-of-<usuario>" in out and r"CELTIA\<usuario>" in out and "pepitorro" in out


def test_las_copias_de_seguridad_no_entran():
    from eolfi.dataset_llm import _JUNK

    assert _JUNK.search(r"corpus\texto\Eolfi\backups\antes-modo-agente\SESION.md")
    assert _JUNK.search("corpus/texto/Force/_backup-2026/notas.md")
    assert not _JUNK.search("corpus/texto/Eolfi/docs/copias-de-seguridad.md")
