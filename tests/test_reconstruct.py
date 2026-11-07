"""Fase 4: reconstrucción independiente desde la especificación (muestras sintéticas propias)."""
import json
import subprocess
import sys

import pytest

from eolfi.core.cases import CaseStore
from eolfi.core.evidence import EvidenceStore
from eolfi.observe import run_observation, run_replay
from eolfi.reconstruct import build_model, generate, reconstruct, verify
from eolfi.reconstruct.core import MANIFEST
from eolfi.spec import store_spec
from tests import observe_samples as samples
from tests.test_observe import _script


@pytest.fixture
def store(tmp_path):
    s = EvidenceStore(tmp_path / "e.db")
    yield s
    s.close()


def _observed_case(store, tmp_path):
    cid = CaseStore(store).create("rec")["case_id"]
    t = samples.write(tmp_path, "app.py", samples.APP_V1)
    steps = [{"id": "hola", "action": "run", "argv": ["{python}", "{target}"], "stdin": {"text": "hola"}},
             {"id": "vacio", "action": "run", "argv": ["{python}", "{target}"], "stdin": {"text": ""}},
             {"id": "hijo", "action": "run", "argv": ["{python}", "{target}", "--hijo"], "stdin": {"text": "x"}}]
    a = run_observation(_script(t, steps), store, authorized=True, case_id=cid)
    run_replay(store, a["evidence_id"], authorized=True, case_id=cid)
    store_spec(store, cid)
    return cid


def test_model_is_independent_and_explains_decisions(store, tmp_path):
    cid = _observed_case(store, tmp_path)
    model = build_model(store, cid)
    ids = {c["id"] for c in model["components"]}
    assert ids == {"cli", "persistence"}
    cli = next(c for c in model["components"] if c["id"] == "cli")
    assert len(cli["cases"]) == 3 and all(c["requirement"].startswith("REQ-") for c in cli["cases"])
    hola = next(c for c in cli["cases"] if c["stdin"] == "hola")
    assert hola["args"] == [] and hola["exit_code"] == 0 and "eco=hola" in hola["stdout"]
    assert any("{sandbox}" in c["stdout"] for c in cli["cases"])
    # Los efectos en archivos solo se conocen por hash: el caso se marca con lo pendiente.
    assert any("efectos en archivos" in p for p in hola["pending"])
    assert next(c for c in cli["cases"] if c["args"] == ["--hijo"])["exit_code"] == 0
    assert all(d["reason"] and d["alternatives"] for d in model["decisions"])
    persistence = next(c for c in model["components"] if c["id"] == "persistence")
    assert "{sandbox}/estado/datos.txt" in persistence["data"]
    assert model["spec_version"] >= 1 and len(model["content_sha256"]) == 64
    with pytest.raises(ValueError, match="especificación"):
        build_model(store, CaseStore(store).create("vacío")["case_id"])


def test_generate_verify_and_trace(store, tmp_path):
    cid = _observed_case(store, tmp_path)
    out = tmp_path / "rec"
    rep = reconstruct(store, cid, out, name="muestra")
    gen, ver = rep["generation"], rep["verification"]
    assert set(gen["written"]) == {"app.py", "comportamiento.json", "tests/test_app.py", "README.md"}
    assert gen["simulated"] == 3 and gen["pending"] == 0
    assert ver["match"] == 3 and ver["differ"] == 0 and ver["equivalent_on_observed"] is True
    assert "no demuestra equivalencia general" in ver["limits"]
    # La base generada arranca, reproduce lo observado y declara lo no especificado.
    p = subprocess.run([sys.executable, str(out / "app.py")], input=b"hola", capture_output=True, cwd=tmp_path)
    assert p.returncode == 0 and f"cwd={tmp_path}" in p.stdout.decode() and "eco=hola" in p.stdout.decode()
    p = subprocess.run([sys.executable, str(out / "app.py"), "--otra"], input=b"", capture_output=True)
    assert p.returncode == 2 and "no especificado" in p.stderr.decode("utf-8", "replace")
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(out / "tests")],
                       capture_output=True, cwd=out)
    assert p.returncode == 0, p.stdout.decode()[-2000:]
    # No copia código del original: ninguna línea característica del objetivo aparece en lo generado.
    gen_text = "".join(f.read_text(encoding="utf-8") for f in out.rglob("*.py"))
    assert "subprocess.run([sys.executable, \"-c\"" not in gen_text and "winreg" not in gen_text
    m = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    assert m["files"]["app.py"]["requirements"] and m["cases"][0]["evidence_ids"]
    assert {c["id"]: c["generated"] for c in m["components"]} == {"cli": True, "persistence": False}
    # Registro del caso con la verificación como evidencia.
    rec = [r for r in CaseStore(store).get(cid)["records"] if r["payload"].get("flow") == "reconstruct"][0]
    assert rec["kind"] == "reconstruction" and rec["payload"]["status"] == "done"
    assert rec["payload"]["result"]["match"] == 3


def test_regeneration_keeps_manual_changes(store, tmp_path):
    cid = _observed_case(store, tmp_path)
    out = tmp_path / "rec"
    model = build_model(store, cid)
    generate(model, out)
    (out / "README.md").write_text("mis notas", encoding="utf-8")
    again = generate(model, out)
    assert again["kept_manual"] == ["README.md"]
    assert (out / "README.md").read_text(encoding="utf-8") == "mis notas"
    assert (out / "README.md.nuevo").exists()
    assert json.loads((out / MANIFEST).read_text(encoding="utf-8"))["files"]["README.md"]["manual_changes"] is True
    # Un archivo no tocado sí se regenera.
    assert "app.py" in again["written"]


def test_contradicted_requirement_stays_pending(store, tmp_path):
    cid = CaseStore(store).create("azar")["case_id"]
    n = samples.write(tmp_path, "azar.py", samples.NONDETERMINISTIC)
    s = _script(n, [{"id": "azar", "action": "run", "argv": ["{python}", "{target}"]}])
    run_observation(s, store, authorized=True, case_id=cid)
    run_observation(s, store, authorized=True, case_id=cid)
    store_spec(store, cid)
    rep = reconstruct(store, cid, tmp_path / "rec")
    assert rep["generation"]["pending"] == 1 and rep["verification"]["pending"] == 1
    assert rep["verification"]["equivalent_on_observed"] is False
    p = subprocess.run([sys.executable, str(tmp_path / "rec" / "app.py")], input=b"", capture_output=True)
    assert p.returncode == 3 and "pendiente" in p.stderr.decode("utf-8", "replace")


def test_cli_reconstruct(store, tmp_path, capsys):
    from eolfi.cli import main

    db = tmp_path / "c.db"
    s = EvidenceStore(db)
    cid = _observed_case(s, tmp_path)
    s.close()
    assert main(["--db", str(db), "reconstruct", "--case", cid, "--model"]) == 0
    assert json.loads(capsys.readouterr().out)["components"]
    assert main(["--db", str(db), "reconstruct", "--case", cid, "--out", str(tmp_path / "r")]) == 0
    assert json.loads(capsys.readouterr().out)["verification"]["match"] == 3


def test_equivalence_same_script_structured_effects_coverage_and_incognitas(store, tmp_path):
    from eolfi.core.models import Status
    from eolfi.reconstruct import check_equivalence

    cid = _observed_case(store, tmp_path)
    # Un guion sin objetivo (solo escribe un archivo) no se puede ejercitar contra el candidato: queda listado.
    run_observation(_script(None, [{"id": "solo", "action": "write_file", "path": "a.txt", "text": "x"}]),
                    store, authorized=True, case_id=cid)
    store_spec(store, cid)
    rep = reconstruct(store, cid, tmp_path / "rec")
    cand = tmp_path / "rec" / "app.py"
    with pytest.raises(PermissionError):
        check_equivalence(store, cid, cand, authorized=False)
    eq = check_equivalence(store, cid, cand, authorized=True)
    reqs = {r["title"]: r for r in eq["requirements"]}
    assert reqs["write_file «solo»"]["result"] == "not_exercised"
    assert eq["coverage"]["not_exercised"] == [reqs["write_file «solo»"]["id"]]
    hola = next(r for r in eq["requirements"] if r["result"] != "not_exercised" and "hola" in r["title"])
    # stdout/código coinciden; los efectos en archivos (y el proceso hijo) no se reconstruyeron: divergencia visible.
    assert hola["result"] == "divergent" and "archivos" in hola["aspects"] and "stdout" not in hola["aspects"]
    assert hola["severity"] == "medium"
    hijo = next(r for r in eq["requirements"] if r["title"] == "run «hijo»")
    assert "procesos hijos" in hijo["aspects"]
    assert eq["equivalent"] is False and eq["incognitas_opened"] >= 3
    subj = rep["model"]["components"] and store.get_evidence(eq["runs"][0]["original"])["subject"]
    open_q = [i for i in store.list_incognitas(Status.OPEN, subject=subj) if i["question"].startswith("Equivalencia:")]
    assert open_q
    # Con tolerancias declaradas, lo que queda coincide y las incógnitas de esos requisitos se cierran.
    eq2 = check_equivalence(store, cid, cand, authorized=True, tolerances=["archivos", "procesos hijos"])
    assert eq2["counts"]["divergent"] == 0 and eq2["counts"]["equivalent"] == 3
    assert eq2["equivalent"] is False                        # hay un requisito sin ejercitar: no se declara total
    assert eq2["incognitas_closed"] >= 1
    assert not [i for i in store.list_incognitas(Status.OPEN, subject=subj)
                if i["question"].startswith("Equivalencia:") and hola["id"] in i["question"]]
    rec = [r for r in CaseStore(store).get(cid)["records"] if r["payload"].get("flow") == "equivalence"]
    assert len(rec) == 2 and rec[-1]["kind"] == "comparison"


def test_severity_levels():
    from eolfi.reconstruct.equivalence import severity

    assert severity("código de salida") == "high" and severity("pulsar.url") == "high"
    assert severity("archivos") == "medium" and severity("ui.accesibilidad") == "medium"
    assert severity("stderr") == "low" and severity("procesos hijos") == "low"


def test_ddmin_reduces_to_minimal_failing_input():
    from eolfi.reconstruct.explore import ddmin

    data = b"linea uno\nlinea dos BOOM\nlinea tres\n"
    budget = [500]
    small = ddmin(data, lambda d: b"BOOM" in d, budget)
    assert small == b"BOOM" and budget[0] > 0


def test_variants_are_deterministic_and_exclude_original():
    import random

    from eolfi.reconstruct.explore import variants_for

    a = variants_for(b"hola mundo", 8, random.Random("1337:REQ-x"))
    b = variants_for(b"hola mundo", 8, random.Random("1337:REQ-x"))
    c = variants_for(b"hola mundo", 8, random.Random("7:REQ-x"))
    assert a == b and a != c and b"hola mundo" not in a and len(set(a)) == 8


def test_explore_variations_reduce_and_replay(store, tmp_path):
    from eolfi.reconstruct import explore

    cid = _observed_case(store, tmp_path)
    reconstruct(store, cid, tmp_path / "rec")
    cand = tmp_path / "rec" / "app.py"
    with pytest.raises(PermissionError):
        explore(store, cid, cand, authorized=False)
    rep = explore(store, cid, cand, authorized=True, variants=3, seed=11, max_runs=120,
                  tolerances=["archivos", "procesos hijos"])
    explored = [r for r in rep["requirements"] if r["status"] == "explored"]
    assert explored and rep["divergent_variants"] > 0          # la etapa 1 no generaliza: se ve con variantes
    hola = next(r for r in explored if "hola" in r["title"])
    assert len(hola["variants"]) == 3 and hola["minimal_failing"]
    m = hola["minimal_failing"][0]
    assert "código de salida" in m["aspects"] and m["size"] <= 4
    assert rep["config"] == {"seed": 11, "variants": 3, "max_runs": 120,
                             "tolerances": ["archivos", "procesos hijos"], "spec_version": rep["config"]["spec_version"]}
    again = explore(store, cid, cand, authorized=True, variants=3, seed=11, max_runs=120,
                    tolerances=["archivos", "procesos hijos"])
    h2 = next(r for r in again["requirements"] if r["title"] == hola["title"])
    assert [v["sha256"] for v in h2["variants"]] == [v["sha256"] for v in hola["variants"]]   # repetición determinista
    inc = [i for i in store.list_incognitas() if i["question"].startswith("Exploración:")]
    assert inc
    rec = [r for r in CaseStore(store).get(cid)["records"] if r["payload"].get("flow") == "explore"]
    assert rec and rec[0]["payload"]["result"]["config"]["seed"] == 11
    # Original cambiado: no se ejecuta otro binario en su lugar.
    t = tmp_path / "app.py"
    t.write_text(samples.APP_V2, encoding="utf-8")
    skipped = explore(store, cid, cand, authorized=True, variants=1, seed=11, max_runs=20)
    assert skipped["explored"] == 0 and all("original no disponible" in r["reason"] for r in skipped["requirements"])


def test_normalize_paths_longest_first_macos_private_var():
    """CI macOS: /var/folders/… es enlace de /private/var/folders/…; la forma larga debe sustituirse antes."""
    from eolfi.reconstruct.core import normalize_paths

    text = "cwd=/private/var/folders/ab/T/eolfi-rec-x\r\n"
    for forms in ({"/var/folders/ab/T/eolfi-rec-x", "/private/var/folders/ab/T/eolfi-rec-x"},
                  {"/private/var/folders/ab/T/eolfi-rec-x", "/var/folders/ab/T/eolfi-rec-x"}):
        assert normalize_paths(text, forms) == "cwd={sandbox}\n"
