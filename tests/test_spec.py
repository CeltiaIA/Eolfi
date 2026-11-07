"""Fase 3: especificación versionada sustentada por observaciones (muestras sintéticas propias)."""
import json
import sys

import pytest

from eolfi.core.cases import CaseStore
from eolfi.core.evidence import EvidenceStore
from eolfi.observe import run_observation, run_replay
from eolfi.spec import build_spec, diff_specs, latest_spec, review_requirement, spec_tests, store_spec
from tests import observe_samples as samples
from tests.test_observe import _app_steps, _script


@pytest.fixture
def store(tmp_path):
    s = EvidenceStore(tmp_path / "e.db")
    yield s
    s.close()


def _case(store, name="spec"):
    return CaseStore(store).create(name)["case_id"]


def test_spec_from_observations_with_evidence_confidence_and_tests(store, tmp_path):
    cid = _case(store)
    t = samples.write(tmp_path, "app.py", samples.APP_V1)
    script = _script(t, _app_steps("hola") + [
        {"id": "vacio", "action": "run", "argv": ["{python}", "{target}"], "stdin": {"text": ""}}])
    a = run_observation(script, store, authorized=True, case_id=cid)
    spec1 = store_spec(store, cid)
    assert spec1["spec_version"] == 1
    reqs = {r["title"]: r for r in spec1["requirements"]}
    ok, err = reqs["run «arranque»"], reqs["run «vacio»"]
    assert ok["kind"] == "use_case" and ok["status"] == "observed" and ok["confidence"] == "medium"
    assert err["kind"] == "error" and err["expected"]["código de salida"] == 3
    assert ok["evidence_ids"] == [a["evidence_id"]]
    assert {"kind": "file", "path": "{sandbox}/estado/datos.txt", "change": "created"} in ok["persistence"]
    assert ok["inputs"]["stdin"]["size"] == 4 and ok["inputs"]["program"].startswith("python")
    assert spec1["artifacts"][0]["subject"] == a["subject"] and spec1["artifacts"][0]["status"] == "derived"
    assert "reloj" in spec1["unknowns"]["unfixed_factors"]
    assert any(g.startswith("system_calls: not_available") for g in spec1["unknowns"]["coverage_gaps"])
    # La repetición coincidente sube la confianza: versión nueva con requisitos más fuertes.
    run_replay(store, a["evidence_id"], authorized=True, case_id=cid)
    spec2 = store_spec(store, cid)
    assert spec2["spec_version"] == 2
    assert {r["confidence"] for r in spec2["requirements"]} == {"high"}
    d = diff_specs(spec1, spec2)
    assert d["added"] == [] and all("confidence" in c["fields"] for c in d["changed"])
    # Sin cambios no hay versión nueva.
    assert store_spec(store, cid).get("unchanged") is True
    # Pruebas generadas solo desde lo observado.
    tests = spec_tests(spec2)
    assert {x["origin"] for x in tests["tests"]} == {"observed"} and len(tests["tests"]) == 2
    t_ok = next(x for x in tests["tests"] if x["requirement"] == ok["id"])
    assert t_ok["expect"]["código de salida"] == 0 and t_ok["expect"]["stdout"]
    # Registro del caso: specification con claims observadas y enlace a la versión anterior.
    recs = [r for r in CaseStore(store).get(cid)["records"] if r["kind"] == "specification"]
    assert recs[1]["payload"]["parent"] == recs[0]["record_id"]
    assert {c["status"] for c in recs[1]["payload"]["claims"]} == {"observed"}


def test_contradiction_unstable_aspect_and_hypotheses_kept_apart(store, tmp_path):
    cid = _case(store)
    n = samples.write(tmp_path, "azar.py", samples.NONDETERMINISTIC)
    s = _script(n, [{"id": "azar", "action": "run", "argv": ["{python}", "{target}"]}])
    a = run_observation(s, store, authorized=True, case_id=cid)
    b = run_observation(s, store, authorized=True, case_id=cid)      # misma entrada, otra salida
    CaseStore(store).add_record(cid, "specification", {"claims": [
        {"text": "Probablemente usa uuid4", "status": "hypothesis"}]})
    spec = store_spec(store, cid)
    req = spec["requirements"][0]
    assert req["status"] == "contradicted" and req["confidence"] == "low"
    assert req["contradictions"][0]["aspect"] == "stdout"
    assert "stdout" not in req["expected"] and req["expected"]["código de salida"] == 0
    assert spec["contradictions"] == [{"requirement": req["id"], "aspects": ["stdout"]}]
    assert spec["hypotheses"][0]["text"] == "Probablemente usa uuid4"
    assert not any("uuid4" in r["title"] for r in spec["requirements"])
    inc = [i for i in store.list_incognitas(subject=a["subject"]) if i["question"].startswith("Especificación:")]
    assert inc and req["id"] in inc[0]["question"]
    assert spec_tests(spec)["tests"] == []                            # nada contradicho se convierte en prueba
    # Una repetición que marca stdout como no reproducible lo deja «inestable», fuera de lo esperado.
    cid2 = _case(store, "otra")
    c = run_observation(s, store, authorized=True, case_id=cid2)
    run_replay(store, c["evidence_id"], authorized=True, case_id=cid2)
    spec_b = build_spec(store, cid2)
    # el caso 2 ve también las sesiones a y b del mismo objetivo (mismo subject): contradicción + inestable
    r2 = spec_b["requirements"][0]
    assert "stdout" in r2["unstable_aspects"] and "stdout" not in r2["expected"]
    assert b["evidence_id"] in r2["evidence_ids"]


def test_review_is_traceable_and_resets_when_requirement_changes(store, tmp_path):
    cid = _case(store)
    t = samples.write(tmp_path, "app.py", samples.APP_V1)
    a = run_observation(_script(t, _app_steps()), store, authorized=True, case_id=cid)
    spec = store_spec(store, cid)
    rid = spec["requirements"][0]["id"]
    with pytest.raises(ValueError):
        review_requirement(store, cid, rid, "quizá", reviewer="L")
    rv = review_requirement(store, cid, rid, "accepted", reviewer="Luis", note="coincide con el manual")
    assert rv["spec_version"] == 1
    spec2 = store_spec(store, cid)
    assert spec2["spec_version"] == 2 and spec2["requirements"][0]["review"]["state"] == "accepted"
    assert diff_specs(spec, spec2)["changed"] == [{"id": rid, "fields": ["review"]}]
    # Nueva observación con el mismo input → confianza cambia, pero lo esperado no: la revisión se mantiene.
    run_replay(store, a["evidence_id"], authorized=True, case_id=cid)
    spec3 = store_spec(store, cid)
    assert spec3["requirements"][0]["review"]["state"] == "accepted"
    # Rechazado → fuera de las pruebas.
    review_requirement(store, cid, rid, "rejected", reviewer="Luis")
    spec4 = store_spec(store, cid)
    assert spec_tests(spec4)["skipped"] == [{"requirement": rid, "reason": "rechazado en revisión"}]
    assert latest_spec(store, cid, 1)["spec_version"] == 1
    with pytest.raises(ValueError):
        latest_spec(store, cid, 99)


def test_state_machine_from_desktop_or_browser_steps():
    from eolfi.spec.build import _states

    step = {"action": "browser", "actions": [
        {"id": "_inicio", "do": "goto", "url_after": "http://h/", "visible": {"text_sha256": "a"}, "status": "ok"},
        {"id": "pulsar", "do": "click", "url_after": "http://h/", "visible": {"text_sha256": "b"}, "status": "ok"},
        {"id": "volver", "do": "click", "url_after": "http://h/", "visible": {"text_sha256": "a"}, "status": "ok"}]}
    sm = _states(step)
    assert len(sm["states"]) == 2
    assert [(t["action"], t["from"] is None) for t in sm["transitions"]] == [("pulsar", False), ("volver", False)]
    assert sm["transitions"][1]["to"] == sm["states"][0]["id"]


def test_cli_spec(tmp_path, capsys):
    from eolfi.cli import main

    db = str(tmp_path / "c.db")
    s = EvidenceStore(db)
    cid = CaseStore(s).create("cli")["case_id"]
    t = samples.write(tmp_path, "app.py", samples.APP_V1)
    run_observation(_script(t, _app_steps()), s, authorized=True, case_id=cid)
    s.close()
    assert main(["--db", db, "spec", "show", "--case", cid]) == 1
    capsys.readouterr()
    assert main(["--db", db, "spec", "build", "--case", cid]) == 0
    req = json.loads(capsys.readouterr().out)["requirements"][0]["id"]
    assert main(["--db", db, "spec", "review", "--case", cid, req, "accepted", "--reviewer", "L"]) == 0
    capsys.readouterr()
    assert main(["--db", db, "spec", "build", "--case", cid]) == 0
    capsys.readouterr()
    assert main(["--db", db, "spec", "diff", "--case", cid, "1", "2"]) == 0
    assert json.loads(capsys.readouterr().out)["changed"][0]["fields"] == ["review"]
    out = tmp_path / "t.json"
    assert main(["--db", db, "spec", "tests", "--case", cid, "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["tests"][0]["origin"] == "observed"


def test_sequences_model_persistent_state_and_divergence(store, tmp_path):
    """Máquina de estados del estado persistente: archivos y sesión HTTP (cookies) paso a paso; dos sesiones del
    mismo guion con secuencias distintas quedan como contradicción con el primer punto de divergencia."""
    from eolfi.spec.build import session_sequence

    cid = _case(store)
    t = samples.write(tmp_path, "app.py", samples.APP_V1)
    steps = _app_steps("hola") + [
        {"id": "borrar", "action": "delete_file", "path": "estado/datos.txt"},
        {"id": "otra", "action": "run", "argv": ["{python}", "{target}"], "stdin": {"text": "hola"}}]
    a = run_observation(_script(t, steps), store, authorized=True, case_id=cid)
    seq = session_sequence(a)
    tr = seq["transitions"]
    assert [x["step"] for x in tr] == ["arranque", "borrar", "otra"]
    assert tr[0]["from"] == seq["initial"] and tr[0]["to"] != seq["initial"]       # crea estado/datos.txt
    assert tr[1]["to"] != tr[0]["to"]                                               # lo borra
    assert len({s["id"] for s in seq["states"]}) == len(seq["states"])
    run_replay(store, a["evidence_id"], authorized=True, case_id=cid)
    spec = store_spec(store, cid)
    assert len(spec["sequences"]) == 1
    q = spec["sequences"][0]
    assert q["status"] == "observed" and q["confidence"] == "high" and q["observations"] == 2
    assert a["evidence_id"] in q["evidence_ids"]
    # Mismo guion y objetivo, pero el estado de partida externo cambia la secuencia: contradicción localizada.
    n = samples.write(tmp_path, "azar.py", samples.NONDETERMINISTIC + "import os\nopen(str(len(os.listdir('.'))) + '.txt', 'w').write('x')\n")
    cid2 = _case(store, "div")
    s = _script(n, [{"id": "uno", "action": "run", "argv": ["{python}", "{target}"]}])
    run_observation(s, store, authorized=True, case_id=cid2)
    s2 = dict(s, setup={"files": {"extra.txt": {"text": "x"}}})                    # otro guion: otro grupo
    run_observation(s2, store, authorized=True, case_id=cid2)
    spec2 = store_spec(store, cid2)
    assert len(spec2["sequences"]) == 2 and {x["status"] for x in spec2["sequences"]} == {"observed"}
    d = diff_specs(spec, spec2)
    assert set(d["sequences"]) == {"added", "removed", "changed"}


def test_sequence_divergence_detected():
    from eolfi.spec.build import _sequences

    def sess(sha):
        return {"script_sha256": "g", "target": {"sha256": "t"}, "initial_state": {"files": {}},
                "steps": [{"id": "p", "action": "write_file", "status": "ok",
                           "effects": {"files": [{"path": "{sandbox}/a", "change": "created", "after": {"sha256": sha}}]}}]}
    out = _sequences([{"evidence_id": "e1", "session": sess("1")}, {"evidence_id": "e2", "session": sess("2")}], {})
    assert out[0]["status"] == "contradicted" and out[0]["first_divergence"] == {"index": 0, "step": "p"}
    same = _sequences([{"evidence_id": "e1", "session": sess("1")}, {"evidence_id": "e2", "session": sess("1")}], {})
    assert same[0]["status"] == "observed" and same[0]["confidence"] == "high"
