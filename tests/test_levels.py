"""Fase 6: niveles de análisis, plan visible antes de ejecutar y borrado de sesiones."""
import json

import pytest

from eolfi.core.cases import CaseStore
from eolfi.core.evidence import EvidenceStore
from eolfi.observe import run_observation, run_replay
from eolfi.observe.session import load_script
from eolfi.security.levels import FLOW_LEVELS, LEVELS, flow_level, forget_session, session_plan
from tests import observe_samples as samples
from tests.test_observe import _app_steps, _script


@pytest.fixture
def store(tmp_path):
    s = EvidenceStore(tmp_path / "e.db")
    yield s
    s.close()


def test_levels_are_explicit():
    assert set(LEVELS) == {"static", "observed", "isolated"}
    assert LEVELS["observed"]["requires_authorization"] and LEVELS["observed"]["isolation"] == "ninguna"
    assert "NO es un sandbox" in LEVELS["observed"]["description"]
    assert flow_level("triage")["executes_target"] is False
    for f in ("observe", "replay", "equivalence", "explore", "diff"):
        assert flow_level(f)["requires_authorization"] is True
    assert "isolated" not in FLOW_LEVELS.values()           # ningún flujo dice estar aislado


def test_plan_shows_programs_permissions_data_without_running(store, tmp_path):
    t = samples.write(tmp_path, "app.py", samples.APP_V1)
    marker = tmp_path / "ejecutado.txt"
    script = _script(t, _app_steps() + [{"id": "api", "action": "http", "url": "http://ejemplo.org:{var:p}/"}],
                     environment={"inherit": True}, allow_hosts=["ejemplo.org"])
    sc, bdir = load_script(script)
    plan = session_plan(sc, bdir, db_path=store.path)
    assert plan["level"] == "observed" and plan["isolation"] == "ninguna"
    assert plan["target"]["sha256"] and plan["programs"][0]["found"] is True
    assert "ejemplo.org" in plan["permissions"]["network_hosts"]
    assert any("Hereda tu entorno" in w for w in plan["warnings"])
    assert any("hosts no locales" in w for w in plan["warnings"])
    assert plan["missing_variables"] == ["p"]
    assert plan["data"]["stored_in"].endswith("e.db") and "forget" in plan["data"]["deletion"]
    assert plan["data"]["not_captured"] and plan["data"]["personal_data_redaction"] is True
    assert store.list_evidence() == [] and not marker.exists()


def test_session_records_data_handling_and_forget_deletes_derived(store, tmp_path):
    cid = CaseStore(store).create("borrar")["case_id"]
    t = samples.write(tmp_path, "app.py", samples.APP_V1)
    a = run_observation(_script(t, _app_steps()), store, authorized=True, case_id=cid)
    dh = a["data_handling"]
    assert dh["level"] == "observed" and dh["stored_in"].endswith("e.db") and "forget" in dh["deletion"]
    r = run_replay(store, a["evidence_id"], authorized=True, case_id=cid)
    with pytest.raises(ValueError):
        forget_session(store, r["evidence_id"])           # solo sesiones, no derivadas sueltas
    out = forget_session(store, a["evidence_id"])
    assert a["evidence_id"] in out["deleted"] and r["evidence_id"] in out["deleted"]
    assert store.get_evidence(a["evidence_id"]) is None and store.get_evidence(r["evidence_id"]) is None
    assert out["case_records_referencing"] >= 1
    # La sesión repetida lleva el mismo guion y datos (replay_of): también se borra.
    assert r["replay"] in out["deleted"] and store.get_evidence(r["replay"]) is None
    assert CaseStore(store).get(cid)["records"]           # el caso sigue legible


def test_cli_plan_and_forget(tmp_path, capsys):
    from eolfi.cli import main

    t = samples.write(tmp_path, "app.py", samples.APP_V1)
    sp = tmp_path / "g.json"
    sp.write_text(json.dumps(_script("app.py", _app_steps())), encoding="utf-8")
    db = str(tmp_path / "c.db")
    assert main(["--db", db, "observe", "plan", str(sp)]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["target"]["path"] == str(t.resolve()) and plan["level"] == "observed"
    assert main(["--db", db, "observe", "run", str(sp), "--autorizo"]) == 0
    eid = json.loads(capsys.readouterr().out)["evidence_id"]
    assert main(["--db", db, "observe", "forget", eid]) == 2
    capsys.readouterr()
    assert main(["--db", db, "observe", "forget", eid, "--confirmo"]) == 0
    assert json.loads(capsys.readouterr().out)["deleted"] == [eid]


def test_every_executing_flow_declares_its_consent(tmp_path, capsys):
    from eolfi.cli import main
    from eolfi.security.levels import CONSENT

    executing = {f for f, lvl in FLOW_LEVELS.items() if LEVELS[lvl]["executes_target"]}
    assert executing <= set(CONSENT)
    ref = samples.write(tmp_path, "r.py", "import sys; print(sys.stdin.read())")
    (tmp_path / "in.txt").write_text("x", encoding="utf-8")
    cmd = f'python "{ref}"'
    assert main(["--db", str(tmp_path / "d.db"), "diff", str(tmp_path / "in.txt"), "--ref", cmd, "--cand", cmd]) == 2
    assert "--autorizo" in capsys.readouterr().out
