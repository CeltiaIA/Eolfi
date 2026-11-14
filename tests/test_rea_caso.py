"""Lo que REA analiza dentro de un caso queda en ese caso de Eolfi (plan REA, punto 6)."""
import json

import pytest

from eolfi import rea_caso
from eolfi.core.cases import CaseStore
from eolfi.core.evidence import EvidenceStore


@pytest.fixture
def store(tmp_path):
    s = EvidenceStore(str(tmp_path / "caso.db"))
    yield s
    s.close()


def _case(store):
    return CaseStore(store).create("Análisis con REA", "")["case_id"]


def test_revisar_modelo_deja_artefacto_evidencia_e_incognita(store, tmp_path):
    case = _case(store)
    gguf = tmp_path / "m-Q4_K_M.gguf"
    gguf.write_bytes(b"GGUF" + b"\0" * 32)
    result = {"archivo": str(gguf), "formato": "gguf", "aprobado": False, "aviso": "solo cabecera",
              "comprobaciones": [{"comprobacion": "formato legible", "ok": True},
                                 {"comprobacion": "la cuantización real coincide con el nombre (Q4_K_M)", "ok": False,
                                  "dominante": "Q5_K"}]}
    out = rea_caso.registrar(store, case, "revisar_modelo", {"ruta": str(gguf)}, result)
    got = CaseStore(store).get(case)
    assert out["artefactos"] == [f"local:{gguf.resolve()}"] and len(got["artifacts"]) == 1
    assert got["artifacts"][0]["tools"][0]["name"] == "rea-agents"
    ev = [e for e in got["evidence"] if e["evidence_id"] == out["evidencia"]][0]
    assert ev["provider"] == "rea" and ev["operation"] == "revisar_modelo" and ev["authority"] == "distributed_artifact"
    incs = store.list_incognitas(subject=out["artefactos"][0])
    assert len(incs) == 1 and "Q5_K" in incs[0]["question"] and incs[0]["severity"] == "medium"


def test_comparar_registra_los_dos_y_lo_desconocido_como_incognita(store):
    case = _case(store)
    result = {"original": {"ruta": "C:/v1.exe", "sha256": "aa" * 32}, "nueva": {"ruta": "C:/v2.exe", "sha256": "bb" * 32},
              "formato": "pe", "verificacion": {"estado": "unknown", "afirmaciones": [
                  {"claim_id": "mismo-artefacto", "status": "unknown"}]}, "aviso": "estático"}
    out = rea_caso.registrar(store, case, "comparar_versiones", {}, result)
    assert out["artefactos"] == ["aa" * 32, "bb" * 32]
    assert {a["subject"] for a in CaseStore(store).get(case)["artifacts"]} == {"aa" * 32, "bb" * 32}
    assert "mismo-artefacto" in store.list_incognitas(subject="aa" * 32)[0]["question"]


def test_verificar_comportamiento_es_reproduccion_controlada(store):
    case = _case(store)
    result = {"escenario": {"original": {"executable": "C:/m/app.exe", "arguments": ["-v"]},
                            "reconstruccion": {"executable": "python", "arguments": ["app.py", "-v"]}},
              "verificacion": {"estado": "pass", "afirmaciones": []}, "aviso": "solo este escenario"}
    out = rea_caso.registrar(store, case, "verificar_comportamiento", {}, result)
    assert out["artefactos"] == ["cmd:C:/m/app.exe -v", "cmd:python app.py -v"]
    ev = [e for e in CaseStore(store).get(case)["evidence"] if e["evidence_id"] == out["evidencia"]][0]
    assert ev["authority"] == "controlled_repro" and out["incognitas"] == []


def test_el_chat_registra_solo_con_caso_activo(tmp_path):
    from eolfi import rea_compuestas, server

    app = server.EolfiApp(str(tmp_path / "app.db"))
    s = app.store()
    case = CaseStore(s).create("Caso", "")["case_id"]
    s.close()
    f = tmp_path / "m-Q4_K_M.gguf"
    f.write_bytes(b"GGUF")

    class Tools:
        client = object()
        authorizer = None

    original = rea_compuestas.revisar_modelo
    rea_compuestas.revisar_modelo = lambda client, path: {"archivo": path, "formato": "gguf", "comprobaciones": [], "aviso": ""}
    try:
        sin = app._chat_rea_composites(Tools(), None)["eolfi_revisar_modelo"]({"ruta": str(f)})
        con = app._chat_rea_composites(Tools(), case)["eolfi_revisar_modelo"]({"ruta": str(f)})
    finally:
        rea_compuestas.revisar_modelo = original
    assert "caso" not in sin and con["caso"]["caso"] == case
    s = app.store()
    try:
        assert len(CaseStore(s).get(case)["artifacts"]) == 1
    finally:
        s.close()
