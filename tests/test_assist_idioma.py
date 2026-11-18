"""C4 (18/11/2026): la IA de assist/autofix recibe el idioma del proyecto generado y la memoria de ejemplos
verificados no mezcla idiomas. En castellano todo queda como antes (mismo prompt, mismos registros)."""
import json
import shutil

import pytest

from eolfi.core.evidence import EvidenceStore
from eolfi.flows.create_flow import create_project
from eolfi.generador.assist import (
    MEMORY_SCHEMA,
    SYSTEM,
    AssistError,
    _read_verified_examples,
    _remember_verified_example,
    assist,
    system_prompt,
)
from tests.fixtures import build_site
from tests.test_assist import FakeClient

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="requiere Node.js")


def _project(tmp_path, idioma):
    site = build_site(tmp_path / f"site-{idioma}")
    out = tmp_path / f"web-{idioma}"
    create_project([str(site)], EvidenceStore(":memory:"), out, name="Bikes", target="static", do_verify=False,
                   idioma=idioma)
    return out


def test_prompt_de_sistema_por_idioma():
    assert system_prompt("es") == SYSTEM          # el castellano no cambia ni un byte
    en = system_prompt("en")
    assert "Los textos en español" not in en and "en inglés" in en
    assert en.count("\n") == SYSTEM.count("\n") + 1   # solo cambia esa regla


def test_assist_en_ingles_lo_dice_y_solo_ve_ejemplos_en_ingles(tmp_path):
    memory = tmp_path / "verified.jsonl"
    rows = [{"schema": MEMORY_SCHEMA, "verified": True, "target": "static", "summary": "EJEMPLO EN CASTELLANO"},
            {"schema": MEMORY_SCHEMA, "verified": True, "target": "static", "summary": "ENGLISH EXAMPLE",
             "idioma": "en"}]
    memory.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    for idioma, visto, oculto in (("en", "ENGLISH EXAMPLE", "EJEMPLO EN CASTELLANO"),
                                  ("es", "EJEMPLO EN CASTELLANO", "ENGLISH EXAMPLE")):
        out = _project(tmp_path, idioma)
        page = (out / "index.html").read_text(encoding="utf-8")
        assert ('lang="en"' in page) == (idioma == "en")
        client = FakeClient([{"summary": "sin cambios", "notes": [],
                              "files": [{"path": "index.html", "content": page}]}])
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("EOLFI_ASSIST_MEMORY", str(memory))
            r = assist(out, "Review the page", provider=client)
        assert r["ok"]
        assert client.calls[0]["system"] == system_prompt(idioma)
        prompt = client.calls[0]["messages"][0]["content"]
        assert visto in prompt and oculto not in prompt


def test_memoria_guarda_el_idioma_solo_si_no_es_castellano(tmp_path, monkeypatch):
    memory = tmp_path / "m.jsonl"
    monkeypatch.setenv("EOLFI_ASSIST_MEMORY", str(memory))
    comun = {"target": "static", "brief": "Add search", "summary": "Search", "notes": [], "files": ["index.html"],
             "provider": "simulado", "model": None}
    assert _remember_verified_example(**comun)
    assert _remember_verified_example(**comun, idioma="en")      # mismo texto, otro idioma: otro registro
    assert not _remember_verified_example(**comun, idioma="en")  # repetido
    es, en = [json.loads(x) for x in memory.read_text(encoding="utf-8").splitlines()]
    assert "idioma" not in es and en["idioma"] == "en" and es["id"] != en["id"]
    assert [r["summary"] for r in _read_verified_examples("static")] == ["Search"]
    assert [r["summary"] for r in _read_verified_examples("static", idioma="en")] == ["Search"]
    assert len(_read_verified_examples("static", idioma="en")) == 1


def test_idioma_no_admitido_en_la_spec(tmp_path):
    out = _project(tmp_path, "es")
    spec = json.loads((out / "eolfi.spec.json").read_text(encoding="utf-8"))
    spec["idioma"] = "fr"
    (out / "eolfi.spec.json").write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(AssistError, match="idioma no admitido"):
        assist(out, "algo", provider=FakeClient([]))
