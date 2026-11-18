"""D1 (18/11/2026): «eolfi sync», volver a analizar las fuentes y fusión a tres bandas."""
import json
from pathlib import Path

import pytest

from eolfi.cli import main
from eolfi.core.evidence import EvidenceStore
from eolfi.flows.create_flow import create_project
from eolfi.flows.sync_flow import CARPETA_COPIAS, fusionar3, sync_project
from tests.fixtures import build_site


# ── Fusión por líneas ───────────────────────────────────────────────────────────────────────────────────────────
BASE = "uno\ndos\ntres\ncuatro\ncinco\n"


def test_cambios_en_zonas_distintas_se_juntan():
    tuyo = BASE.replace("dos", "DOS (mío)")
    fuente = BASE.replace("cinco", "CINCO (fuente)")
    assert fusionar3(BASE, tuyo, fuente) == ("uno\nDOS (mío)\ntres\ncuatro\nCINCO (fuente)\n", 0)


def test_el_mismo_cambio_en_los_dos_no_es_conflicto():
    igual = BASE.replace("tres", "TRES")
    assert fusionar3(BASE, igual, igual) == (igual, 0)


def test_solo_un_lado_cambia():
    tuyo = BASE + "seis\n"
    assert fusionar3(BASE, tuyo, BASE) == (tuyo, 0)
    assert fusionar3(BASE, BASE, tuyo) == (tuyo, 0)
    sin_tres = BASE.replace("tres\n", "")
    assert fusionar3(BASE, BASE, sin_tres) == (sin_tres, 0)


def test_cambios_que_chocan_quedan_marcados():
    texto, n = fusionar3(BASE, BASE.replace("tres", "mío"), BASE.replace("tres", "fuente"))
    assert n == 1
    assert texto == "uno\ndos\n<<<<<<< tuyo\nmío\n=======\nfuente\n>>>>>>> fuente\ncuatro\ncinco\n"


def test_inserciones_en_el_mismo_punto_chocan_y_en_puntos_distintos_no():
    texto, n = fusionar3(BASE, BASE.replace("dos\n", "dos\nA\n"), BASE.replace("dos\n", "dos\nB\n"))
    assert n == 1 and "<<<<<<< tuyo\nA\n=======\nB\n>>>>>>> fuente\n" in texto
    texto, n = fusionar3(BASE, BASE.replace("uno\n", "uno\nA\n"), BASE.replace("cuatro\n", "cuatro\nB\n"))
    assert (texto, n) == ("uno\nA\ndos\ntres\ncuatro\nB\ncinco\n", 0)


def test_sin_salto_de_linea_final():
    texto, n = fusionar3("a\nb", "a\nX", "a\nY")
    assert n == 1 and texto.endswith(">>>>>>> fuente\n") and "X\n=======\nY\n" in texto


# ── Proyecto real: crear, editar, cambiar la fuente y sincronizar ───────────────────────────────────────────────
@pytest.fixture()
def proyecto(tmp_path):
    store = EvidenceStore(":memory:")
    site = build_site(tmp_path / "site")
    out = tmp_path / "proyecto"
    create_project([str(site)], store, out, name="Bicis", target="static", do_verify=False)
    return store, site, out


def _cambiar_fuente(site: Path) -> None:
    css = site / "css" / "app.css"
    css.write_text(css.read_text(encoding="utf-8").replace("#e11d48", "#2563eb"), encoding="utf-8")
    js = site / "js" / "app.js"
    js.write_text(js.read_text(encoding="utf-8") + '; fetch("/api/customers")', encoding="utf-8")


def test_sin_cambios_en_la_fuente_no_propone_nada(proyecto):
    store, _site, out = proyecto
    r = sync_project(store, out)
    assert r["changes"] == [] and r["applied"] is False and "al día" in r["note"]
    assert r["spec_changes"] == {}


def test_propone_sin_escribir_y_conserva_lo_tuyo_al_aplicar(proyecto):
    store, site, out = proyecto
    # Tu cambio: una regla propia al final de base.css y un archivo tuyo que la plantilla no conoce.
    base_css = out / "css" / "base.css"
    base_css.write_text(base_css.read_text(encoding="utf-8") + "\n.mia { color: red; }\n", encoding="utf-8")
    (out / "notas.txt").write_text("mío", encoding="utf-8")
    antes = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}
    _cambiar_fuente(site)

    r = sync_project(store, out)
    assert r["applied"] is False and r["summary"]["conflicto"] == 0
    assert {p: p.read_bytes() for p in out.rglob("*") if p.is_file()} == antes        # proponer no escribe
    assert r["spec_changes"]["palette"]["primary"] == ["#e11d48", "#2563eb"]
    assert "customers" in r["spec_changes"]["resources"]["añadidos"]
    rutas = {c["ruta"]: c for c in r["changes"]}
    assert rutas["css/tokens.css"]["accion"] == "actualizado" and "#2563eb" in rutas["css/tokens.css"]["diff"]
    assert "notas.txt" not in rutas

    r = sync_project(store, out, aplicar=True, verificar=False)
    assert r["applied"] is True and r["verification"]["ok"] is False and "NO VERIFICADO" in r["verification"]["error"]
    assert "#2563eb" in (out / "css" / "tokens.css").read_text(encoding="utf-8")
    assert ".mia { color: red; }" in base_css.read_text(encoding="utf-8")            # lo tuyo sigue
    assert (out / "notas.txt").read_text(encoding="utf-8") == "mío"
    spec = json.loads((out / "eolfi.spec.json").read_text(encoding="utf-8"))
    assert "customers" in spec["api"]["resources"] and spec["title"] == "Bicis"
    copia = Path(r["backup"])
    assert copia.parent.name == CARPETA_COPIAS and "#e11d48" in (copia / "css" / "tokens.css").read_text(encoding="utf-8")
    # Ya al día: otra pasada no propone nada.
    assert sync_project(store, out)["changes"] == []


def test_un_cambio_tuyo_en_la_misma_linea_queda_como_conflicto(proyecto):
    store, site, out = proyecto
    tokens = out / "css" / "tokens.css"
    texto = tokens.read_text(encoding="utf-8")
    linea = next(l for l in texto.splitlines() if "#e11d48" in l)
    tokens.write_text(texto.replace(linea, linea.replace("#e11d48", "#111111")), encoding="utf-8")
    _cambiar_fuente(site)
    r = sync_project(store, out, aplicar=True, verificar=False)
    c = next(c for c in r["changes"] if c["ruta"] == "css/tokens.css")
    assert c["accion"] == "conflicto" and c["conflictos"] >= 1
    final = tokens.read_text(encoding="utf-8")
    assert "<<<<<<< tuyo" in final and "#111111" in final and "#2563eb" in final
    assert "conflictos sin resolver" in r["verification"]["error"]


def test_no_es_un_proyecto_de_eolfi(tmp_path):
    with pytest.raises(ValueError, match="eolfi.spec.json"):
        sync_project(EvidenceStore(":memory:"), tmp_path)


def test_cli_sync(proyecto, capsys, tmp_path):
    _store, site, out = proyecto
    _cambiar_fuente(site)
    db = tmp_path / "e.db"
    assert main(["--db", str(db), "sync", str(out)]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["applied"] is False and r["summary"]["actualizado"] >= 1


def test_aplicar_verifica_en_una_carpeta_limpia(proyecto):
    store, site, out = proyecto
    _cambiar_fuente(site)
    r = sync_project(store, out, aplicar=True)
    assert r["applied"] is True
    assert r["verification"]["ok"] is True, r["verification"]
    assert r["verification"]["steps"]
