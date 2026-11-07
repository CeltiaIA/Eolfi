"""La guía ejemplos/caja-negra/GUIA.md, ejecutada tal cual con su muestra sintética (criterios de aceptación)."""
import json
import shutil
from pathlib import Path

import pytest

from eolfi.cli import main

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


def test_guia_completa(guia, capsys):
    assert "eolfi " in (guia / "GUIA.md").read_text(encoding="utf-8")
    code, case = run(capsys, "case", "create", "Contador")
    cid = case["case_id"]
    # 1. plan
    code, plan = run(capsys, "observe", "plan", "guion.json")
    assert code == 0 and plan["level"] == "observed" and plan["warnings"]
    # 2. observar y repetir
    code, obs = run(capsys, "observe", "run", "guion.json", "--autorizo", "--case", cid)
    assert code == 0 and [s["exit_code"] for s in obs["steps"]] == [0, 0, 2]
    assert "total=5" in obs["steps"][0]["stdout"]["preview"]
    code, rep = run(capsys, "observe", "replay", obs["evidence_id"], "--autorizo", "--case", cid)
    assert code == 0 and rep["reproducible"] is True and rep["unfixed_factors"]
    # 3. especificar
    code, spec = run(capsys, "spec", "build", "--case", cid)
    assert len(spec["requirements"]) == 3 and {r["confidence"] for r in spec["requirements"]} == {"high"}
    assert [r["kind"] for r in spec["requirements"] if r["expected"]["código de salida"] == 2] == ["error"]
    req = spec["requirements"][0]["id"]
    assert run(capsys, "spec", "review", "--case", cid, req, "accepted", "--reviewer", "Guía")[0] == 0
    assert run(capsys, "spec", "build", "--case", cid)[0] == 0
    code, out = run(capsys, "spec", "tests", "--case", cid, "--out", "pruebas.json")
    assert code == 0 and out["tests"] == 3
    # 4. reconstruir
    code, rec = run(capsys, "reconstruct", "--case", cid, "--out", "reconstruccion")
    v = rec["verification"]
    assert code == 0 and v["match"] == 3 and v["differ"] == 0
    assert (guia / "reconstruccion" / ".eolfi" / "trazabilidad.json").is_file()
    assert "contador" not in (guia / "reconstruccion" / "app.py").read_text(encoding="utf-8").lower()
    # 5. equivalencia y exploración: las divergencias esperadas se ven
    code, eq = run(capsys, "reconstruct", "--case", cid, "--equivalence", "reconstruccion/app.py", "--autorizo")
    assert code == 5 and eq["equivalent"] is False
    assert {r["result"] for r in eq["requirements"]} <= {"equivalent", "divergent"}
    assert any("archivos" in r.get("aspects", []) for r in eq["requirements"])
    code, ex = run(capsys, "reconstruct", "--case", cid, "--explore", "reconstruccion/app.py", "--autorizo",
                   "--seed", "7", "--variants", "4", "--max-runs", "120")
    assert ex["divergent_variants"] > 0 and ex["config"]["seed"] == 7
    # 6. informe y borrado
    assert run(capsys, "case", "report", cid, "--out", "informe.html")[0] == 0
    assert "Contador" in (guia / "informe.html").read_text(encoding="utf-8")
    code, gone = run(capsys, "observe", "forget", obs["evidence_id"], "--confirmo")
    assert code == 0 and obs["evidence_id"] in gone["deleted"]
