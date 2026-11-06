"""Fase 1: flujos enlazados con casos, identidad reproducible, conclusiones tipadas e informe navegable."""
import json
import re
import sqlite3
import sys

import pytest

from eolfi.core.case_report import build_case_report, render_case_html
from eolfi.core.cases import CaseStore, environment_identity
from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Authority, Confidence, Evidence, Status
from eolfi.flows.compare_flow import compare
from eolfi.flows.create_flow import create_project
from eolfi.flows.diff_flow import run_diff
from eolfi.flows.learn_flow import run_repo, run_web
from eolfi.flows.triage_flow import LOCAL_PROVIDERS, run_triage
from eolfi.providers.base import Provider
from eolfi.providers.binfmt import BinaryFormatProvider
from eolfi.providers.triage import FileTriageProvider
from tests.elfgen import build_elf64
from tests.fixtures import build_site


class Boom(Provider):
    name = "boom"
    version = "9.9"

    def available(self):
        return True

    def run(self, target):
        raise RuntimeError("kaput")


def _elf(tmp_path, name="a.elf", extra=b""):
    f = tmp_path / name
    f.write_bytes(build_elf64() + extra)
    return f


def _record(case, flow):
    return next(r for r in case["records"] if r["payload"].get("flow") == flow)


def test_triage_in_case_records_identity_tools_environment_and_survives_restart(tmp_path):
    db = tmp_path / "e.db"
    store = EvidenceStore(db)
    case = CaseStore(store).create("ELF propio", "muestra sintética")
    f = _elf(tmp_path)
    rep = run_triage(str(f), store, LOCAL_PROVIDERS, case_id=case["case_id"], provenance="generado por elfgen")
    store.close()

    reopened = EvidenceStore(db)   # continuar después de reiniciar: todo sale de la SQLite
    saved = CaseStore(reopened).get(case["case_id"])
    art = saved["artifacts"][0]
    assert art["subject"] == rep["subject"] == art["content_sha256"]
    assert art["identity"] == "content" and art["size"] == f.stat().st_size and art["format"] == "elf"
    assert art["provenance"] == "generado por elfgen" and art["path"] == str(f.resolve())
    assert {"name": "eolfi.triage", "version": FileTriageProvider().version} in art["tools"]
    assert art["environment"]["os"] == environment_identity()["os"]
    rec = _record(saved, "triage")
    assert rec["kind"] == "analysis" and rec["record_id"] == rep["case_record"]
    p = rec["payload"]
    assert p["status"] == "done" and p["artifacts"] == [rep["subject"]]
    assert set(p["evidence_ids"]) == set(rep["evidence_ids"])
    assert all(t["status"] == "ran" and t["version"] for t in p["tools"])
    assert p["environment"]["machine"] and p["environment"]["eolfi"]
    assert p["result"]["summary"]["format"] == "elf"
    assert {e["evidence_id"] for e in saved["evidence"]} >= set(rep["evidence_ids"])
    reopened.close()


def test_triage_partial_and_error_are_recorded_with_partial_results(tmp_path, monkeypatch):
    store = EvidenceStore(":memory:")
    cases = CaseStore(store)
    cid = cases.create("Errores")["case_id"]
    f = _elf(tmp_path)
    rep = run_triage(str(f), store, [FileTriageProvider(), Boom(), BinaryFormatProvider()], case_id=cid)
    p = _record(cases.get(cid), "triage")["payload"]
    assert p["status"] == "partial"
    assert any("boom" in e and "kaput" in e for e in p["errors"])
    assert {"name": "boom", "version": "", "status": "failed"} in p["tools"]
    assert p["evidence_ids"] and rep["providers_run"] == ["eolfi.triage", "eolfi.binfmt"]

    import eolfi.flows.triage_flow as tf

    def explode(*_a, **_k):
        raise RuntimeError("disco lleno")
    monkeypatch.setattr(tf, "_run_triage", explode)
    with pytest.raises(RuntimeError):
        run_triage(str(f), store, LOCAL_PROVIDERS, case_id=cid)
    last = cases.get(cid)["records"][-1]["payload"]
    assert last["status"] == "error" and "disco lleno" in last["errors"][0]


def test_unknown_case_is_rejected_before_any_work(tmp_path):
    store = EvidenceStore(":memory:")
    with pytest.raises(ValueError, match="caso no encontrado"):
        run_triage(str(_elf(tmp_path)), store, LOCAL_PROVIDERS, case_id="00000000-0000-0000-0000-000000000000")
    assert store.list_evidence() == []


def test_web_repo_diff_compare_and_create_link_to_case(tmp_path):
    store = EvidenceStore(":memory:")
    cases = CaseStore(store)
    cid = cases.create("Ciclo completo")["case_id"]
    site = build_site(tmp_path / "site")
    web = run_web(str(site), store, case_id=cid)
    repo = run_repo(str(site), store, workdir=str(tmp_path / "w"), case_id=cid)
    a = run_triage(str(_elf(tmp_path, "a.elf")), store, LOCAL_PROVIDERS, case_id=cid)
    b = run_triage(str(_elf(tmp_path, "b.elf", b"\x00extra")), store, LOCAL_PROVIDERS, case_id=cid)
    cmp_rep = compare(store, a["subject"], b["subject"], case_id=cid)

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for i, txt in enumerate(["uno", "dos"]):
        (corpus / f"in{i}.txt").write_text(txt, encoding="utf-8")
    ref = tmp_path / "ref.py"
    ref.write_text("import sys\nprint(len(open(sys.argv[1],'rb').read()))\n", encoding="utf-8")
    diff = run_diff([sys.executable, str(ref), "{input}"], [sys.executable, str(ref), "{input}"], corpus, store,
                    case_id=cid)
    out = tmp_path / "nuevo"
    created = create_project([str(site)], store, out, name="Demo", target="static", do_verify=False, case_id=cid)

    case = cases.get(cid)
    arts = {x["subject"]: x for x in case["artifacts"]}
    assert arts[web["subject"]]["identity"] == "content"            # local: hash del HTML principal
    assert arts[web["subject"]]["content_sha256"] and arts[web["subject"]]["format"] == "html"
    assert arts[repo["subject"]]["format"] == "repository"
    assert arts[repo["subject"]]["identity"] in ("descriptor", "git_commit")
    assert arts[cmp_rep["subject"]]["identity"] == "derived"
    assert arts[diff["subject"]]["identity"] == "content" and arts[diff["subject"]]["metadata"]["role"] == "referencia"
    assert arts[created["subject"]]["identity"] == "derived"
    flows = [r["payload"]["flow"] for r in case["records"]]
    # create re-analiza su fuente dentro del caso: su análisis queda como registro propio.
    assert flows.count("web") == 2 and {"repo", "triage", "compare", "diff", "create"} <= set(flows)
    kinds = {r["payload"]["flow"]: r["kind"] for r in case["records"]}
    assert kinds == {"web": "analysis", "repo": "analysis", "triage": "analysis", "compare": "comparison",
                     "diff": "comparison", "create": "reconstruction"}
    d = _record(case, "diff")["payload"]
    assert d["status"] == "done" and d["result"]["passed"] is True and d["evidence_ids"] == [diff["evidence_id"]]
    c = _record(case, "create")["payload"]
    assert c["status"] == "partial" and c["errors"] == ["proyecto no verificado"]   # sin verificación no hay verde
    assert set(c["artifacts"]) >= {web["subject"], created["subject"]}
    assert _record(case, "compare")["payload"]["evidence_ids"] == [cmp_rep["evidence_id"]]


def test_claims_keep_their_status_and_hypotheses_are_not_promoted(tmp_path):
    store = EvidenceStore(":memory:")
    cases = CaseStore(store)
    cid = cases.create("Conclusiones")["case_id"]
    rep = run_triage(str(_elf(tmp_path)), store, LOCAL_PROVIDERS, case_id=cid)
    observed = next(e for e in store.list_evidence(rep["subject"]) if e["authority"] == "distributed_artifact")
    guess, _ = store.add_evidence(Evidence(subject=rep["subject"], provider="analista", provider_version="1",
                                           operation="purpose", params={}, result={"guess": "calculadora"},
                                           authority=Authority.ANALYST_INFERENCE, confidence=Confidence.LOW))
    with pytest.raises(ValueError, match="observed"):
        cases.add_record(cid, "specification", {"claims": [
            {"text": "Es una calculadora", "status": "observed", "evidence_ids": [guess]}]})
    with pytest.raises(ValueError, match="derived"):
        cases.add_record(cid, "specification", {"claims": [{"text": "x", "status": "derived"}]})
    with pytest.raises(ValueError, match="estado"):
        cases.add_record(cid, "specification", {"claims": [{"text": "x", "status": "seguro"}]})
    inc = store.list_incognitas(subject=rep["subject"])
    rid = cases.add_record(cid, "specification", {"artifacts": [rep["subject"]], "claims": [
        {"text": "Formato ELF de 64 bits", "status": "observed", "evidence_ids": [observed["evidence_id"]]},
        {"text": "Probablemente una calculadora", "status": "hypothesis", "evidence_ids": [guess],
         "incognita_ids": [i["incognita_id"] for i in inc][:1], "limits": "sin ejecutar"}]})

    pkg = tmp_path / "caso.json"
    cases.export(cid, pkg)
    target = EvidenceStore(":memory:")
    tcases = CaseStore(target)
    assert tcases.import_case(pkg) is True
    imported = tcases.get(cid)
    claims = next(r for r in imported["records"] if r["record_id"] == rid)["payload"]["claims"]
    assert [c["status"] for c in claims] == ["observed", "hypothesis"]
    assert imported["imports"] and imported["imports"][0]["source_name"] == "caso.json"
    report = build_case_report(imported)
    hyp = next(c for c in report["conclusions"] if c["text"].startswith("Probablemente"))
    assert hyp["status"] == "hypothesis" and hyp["imported"] is True and hyp["observed_support"] == 0
    assert any("importadas" in x for x in report["limits"]) and any("hipótesis" in x for x in report["limits"])

    # Manipular el paquete para «ascender» la hipótesis a hecho se rechaza al importar.
    data = json.loads(pkg.read_text(encoding="utf-8"))
    rec = next(r for r in data["case"]["records"] if r["record_id"] == rid)
    rec["payload"]["claims"][1]["status"] = "observed"
    pkg.write_text(json.dumps(data), encoding="utf-8")
    other = CaseStore(EvidenceStore(":memory:"))
    with pytest.raises(ValueError, match="observed"):
        other.import_case(pkg)
    assert other.list() == []


def test_html_report_links_conclusions_to_evidence_incognitas_and_escapes(tmp_path):
    store = EvidenceStore(":memory:")
    cases = CaseStore(store)
    cid = cases.create("<script>alert(1)</script>", "desc <b>")["case_id"]
    rep = run_triage(str(_elf(tmp_path)), store, [FileTriageProvider(), Boom(), BinaryFormatProvider()], case_id=cid)
    ev = rep["evidence_ids"][0]
    cases.add_record(cid, "specification", {"claims": [
        {"text": "Formato <elf>", "status": "derived", "evidence_ids": [ev]}]})
    html = render_case_html(build_case_report(cases.get(cid)))
    assert "<script>" not in html and "&lt;script&gt;" in html and "Formato &lt;elf&gt;" in html
    for anchor in re.findall(r'href="#(ev-[0-9a-f]+|inc-[0-9a-f]+|rec-[0-9a-f-]+|art-\d+)"', html):
        assert f'id="{anchor}"' in html, anchor     # ningún enlace roto
    assert f'href="#ev-{ev}"' in html and 'id="limites"' in html
    assert "parcial" in html and "kaput" in html           # resultado parcial y error visibles
    open_inc = [i["incognita_id"] for i in store.list_incognitas(Status.OPEN, subject=rep["subject"])]
    assert open_inc and f'href="#inc-{open_inc[0]}"' in html


def test_v1_schema_and_v1_package_are_upgraded(tmp_path):
    db = tmp_path / "v1.db"
    store = EvidenceStore(db)
    store.conn.executescript("""
    CREATE TABLE cases (case_id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
      created_at REAL NOT NULL, updated_at REAL NOT NULL);
    CREATE TABLE case_artifacts (case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
      subject TEXT NOT NULL, size INTEGER NOT NULL, format TEXT NOT NULL, version TEXT NOT NULL,
      provenance TEXT NOT NULL, path TEXT NOT NULL, platform TEXT NOT NULL, metadata TEXT NOT NULL,
      added_at REAL NOT NULL, PRIMARY KEY(case_id, subject));
    INSERT INTO cases VALUES('11111111-1111-4111-8111-111111111111','viejo','',1,1);
    INSERT INTO case_artifacts VALUES('11111111-1111-4111-8111-111111111111','""" + "a" * 64 + """',5,'ELF','','d','','','{}',1);
    """)
    store.close()
    store = EvidenceStore(db)
    art = CaseStore(store).get("11111111-1111-4111-8111-111111111111")["artifacts"][0]
    assert art["identity"] == "content" and art["content_sha256"] == "a" * 64 and art["tools"] == []
    cols = [r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(case_artifacts)")]
    assert "identity" in cols
    store.close()

    v1 = {"case_package_version": 1, "case": {
        "case_id": "22222222-2222-4222-8222-222222222222", "name": "v1", "description": "", "created_at": 1,
        "updated_at": 1, "records": [], "artifacts": [{
            "case_id": "22222222-2222-4222-8222-222222222222", "subject": "b" * 64, "size": 1, "format": "x",
            "version": "", "provenance": "p", "path": "", "platform": "", "metadata": {}, "added_at": 1}]},
        "evidence_package": {"schema_version": 1, "evidence": [], "incognita": []}}
    pkg = tmp_path / "v1.json"
    pkg.write_text(json.dumps(v1), encoding="utf-8")
    fresh = CaseStore(EvidenceStore(":memory:"))
    assert fresh.import_case(pkg) is True
    assert fresh.get("22222222-2222-4222-8222-222222222222")["artifacts"][0]["identity"] == "content"


def test_cli_case_flow_and_report(tmp_path, capsys):
    from eolfi.cli import main

    db = str(tmp_path / "cli.db")
    assert main(["--db", db, "case", "create", "CLI"]) == 0
    cid = json.loads(capsys.readouterr().out)["case_id"]
    f = _elf(tmp_path)
    assert main(["--db", db, "triage", str(f), "--local", "--case", cid, "--provenance", "fixture"]) == 0
    capsys.readouterr()
    out = tmp_path / "caso.html"
    assert main(["--db", db, "case", "report", cid, "--out", str(out)]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["conclusions"] >= 1 and "Triaje" in out.read_text(encoding="utf-8")
    from eolfi.providers.triage import sha256_file

    sha = sha256_file(f)
    assert main(["--db", db, "case", "link", cid, sha, "--provenance", "repetido"]) == 0
    linked = json.loads(capsys.readouterr().out)
    assert linked["created"] is False and linked["identity"] == "content" and linked["format"] == "elf"
    assert main(["--db", db, "triage", str(f), "--local", "--case", "nope"]) == 1
    assert "caso no encontrado" in capsys.readouterr().err


def test_resolving_incognitas_and_cancellation_are_reflected_in_the_case(tmp_path, monkeypatch):
    store = EvidenceStore(":memory:")
    cases = CaseStore(store)
    cid = cases.create("Revisión")["case_id"]
    run_triage(str(_elf(tmp_path)), store, [FileTriageProvider(), Boom()], case_id=cid)
    before = cases.list()[0]["open_incognitas"]
    inc = next(i for i in cases.get(cid)["incognitas"] if i["status"] == "open")
    assert store.resolve_incognita(inc["incognita_id"])
    assert cases.list()[0]["open_incognitas"] == before - 1
    report = build_case_report(cases.get(cid))
    assert report["open_incognitas"] == before - 1

    class Cancelled(BaseException):   # como JobCancelled del servidor
        pass

    import eolfi.flows.triage_flow as tf

    def cancel(*_a, **_k):
        raise Cancelled()
    monkeypatch.setattr(tf, "_run_triage", cancel)
    with pytest.raises(Cancelled):
        run_triage(str(_elf(tmp_path)), store, LOCAL_PROVIDERS, case_id=cid)
    assert cases.get(cid)["records"][-1]["payload"]["status"] == "cancelled"
