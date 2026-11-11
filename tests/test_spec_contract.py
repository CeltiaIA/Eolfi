"""Fase 3, aceptación: implementar desde la especificación sin el original y distinguir seguro/inferido/desconocido.

La muestra es ejemplos/caja-negra (contador sintético propio). La implementación candidata
ejemplos/caja-negra/desde-contrato/contador_contrato.py se escribió leyendo solo el contrato; aquí se comprueba que
el contrato tiene lo necesario (ejemplos literales, orden, grado de cada afirmación), que no lleva código del
original y que la implementación es equivalente en lo observado.
"""
import json
import shutil
from pathlib import Path

import pytest

from eolfi.cli import main
from eolfi.core.cases import CaseStore
from eolfi.core.evidence import EvidenceStore
from eolfi.observe import run_observation
from eolfi.spec import build_contract, build_spec, certainty, contract_markdown
from tests import observe_samples as samples
from tests.test_observe import _script

EJEMPLO = Path(__file__).resolve().parent.parent / "ejemplos" / "caja-negra"


@pytest.fixture
def guia(tmp_path, monkeypatch):
    work = tmp_path / "caja-negra"
    shutil.copytree(EJEMPLO, work)
    monkeypatch.chdir(work)
    return work


def run(capsys, *args):
    code = main(["--db", "guia.db", *args])
    out = capsys.readouterr().out
    return code, (json.loads(out) if out.strip().startswith(("{", "[")) else out)


def test_contrato_basta_para_implementar_sin_el_original(guia, capsys):
    cid = run(capsys, "case", "create", "Contador desde contrato")[1]["case_id"]
    code, obs = run(capsys, "observe", "run", "guion-contenidos.json", "--autorizo", "--case", cid)
    assert code == 0 and [s["exit_code"] for s in obs["steps"]] == [0, 0, 2]
    # Regresión: capturar el contenido en «restar» no debe inventar un cambio en el paso siguiente.
    assert obs["steps"][2]["effects"]["files"] == []
    assert run(capsys, "observe", "replay", obs["evidence_id"], "--autorizo", "--case", cid)[0] == 0
    assert run(capsys, "spec", "build", "--case", cid)[0] == 0

    code, out = run(capsys, "spec", "contract", "--case", cid, "--format", "json", "--out", "contrato.json")
    assert code == 0 and out["requirements"] == 3 and out["seguro"] == 3
    contrato = json.loads((guia / "contrato.json").read_text(encoding="utf-8"))
    reqs = {r["title"]: r for r in contrato["requirements"]}
    sumar = reqs["run «sumar»"]
    assert sumar["certainty"] == "seguro" and sumar["given"] == {"argv": [], "stdin": "suma 2\nsuma 3\ntotal\n"}
    assert sumar["then"]["stdout"] == "total=5\n" and sumar["then"]["exit_code"] == 0
    assert sumar["then"]["files"] == [{"path": "{sandbox}/estado/total.txt", "change": "created", "content": "5"}]
    assert reqs["run «restar»"]["then"]["files"][0] == {"path": "{sandbox}/estado/total.txt", "change": "modified",
                                                         "content": "6"}
    invalida = reqs["run «invalida»"]
    assert invalida["then"]["stderr"] == "orden desconocida: multiplica 3\n" and invalida["then"]["exit_code"] == 2
    assert "files" not in invalida["then"]
    assert [x["step"] for x in contrato["sequences"][0]["steps"]] == ["sumar", "restar", "invalida"]
    assert "entradas no observadas: comportamiento no especificado" in contrato["summary"]["desconocido"]

    code, out = run(capsys, "spec", "contract", "--case", cid, "--out", "contrato.md")
    md = (guia / "contrato.md").read_text(encoding="utf-8")
    assert code == 0 and "## Grado de cada afirmación" in md and "**seguro** (3)" in md and "total=6" in md
    # Sin código del original: ninguna línea significativa de contador.py aparece en el contrato.
    fuente = [ln.strip() for ln in (guia / "contador.py").read_text(encoding="utf-8").splitlines()
              if len(ln.strip()) >= 20 and not ln.strip().startswith(('"', "#"))]
    texto = md + json.dumps(contrato, ensure_ascii=False)
    assert fuente and not [ln for ln in fuente if ln in texto]

    # La implementación hecha desde el contrato es equivalente en todo lo observado (incluido el archivo).
    code, eq = run(capsys, "reconstruct", "--case", cid, "--equivalence", "desde-contrato/contador_contrato.py",
                   "--autorizo")
    assert code == 0 and eq["equivalent"] is True, eq
    assert {r["result"] for r in eq["requirements"]} == {"equivalent"}


@pytest.fixture
def store(tmp_path):
    s = EvidenceStore(tmp_path / "e.db")
    yield s
    s.close()


def test_grados_inferido_y_desconocido(store, tmp_path):
    cid = CaseStore(store).create("grados")["case_id"]
    t = samples.write(tmp_path, "app.py", samples.APP_V1)
    run_observation(_script(t, [{"id": "hola", "action": "run", "argv": ["{python}", "{target}"],
                                 "stdin": {"text": "hola"}}]), store, authorized=True, case_id=cid)
    spec = build_spec(store, cid)
    req = spec["requirements"][0]
    # Una sola observación: el comportamiento consta, pero su repetición no; se presenta como inferido.
    assert req["confidence"] == "medium" and req["certainty"] == "inferido"
    assert req["examples"]["stdin"] == "hola" and "eco=hola" in req["examples"]["stdout"]
    # Contenido de archivos sin capturar: se dice que es desconocido, no se inventa.
    assert any("no capturado" in o for o in req["examples"]["omitted"])
    contrato = build_contract(spec | {"spec_version": 1})
    assert any("no capturado" in u for u in contrato["requirements"][0]["unknown"])
    assert certainty({"status": "contradicted", "confidence": "low"}) == "desconocido"
    assert certainty({"status": "observed", "confidence": "high", "unstable_aspects": ["stdout"]}) == "inferido"
    assert certainty({"status": "observed", "confidence": "high", "unstable_aspects": []}) == "seguro"
    # Especificaciones anteriores (sin ejemplos) siguen pudiéndose leer y lo dicen.
    viejo = {**spec, "spec_version": 1, "requirements": [{k: v for k, v in req.items()
                                                          if k not in ("examples", "certainty")}]}
    md = contract_markdown(build_contract(viejo))
    assert "sin ejemplos literales" in md
