"""Crear proyecto con plan razonado: propuesta sin ejecutar, aprobación/edición, modos auto y guiado, cambios de
plan y decisiones en el caso. Fuente: sitio sintético propio (tests.fixtures.build_site)."""
import json
import threading
import time

import pytest

from eolfi.core.cases import CaseStore
from eolfi.core.evidence import EvidenceStore
from eolfi.flows import project_flow as pf
from tests.fixtures import build_site


@pytest.fixture
def store(tmp_path):
    s = EvidenceStore(tmp_path / "e.db")
    yield s
    s.close()


def test_interpret_directives_and_uninterpreted():
    r = pf.interpret("Quiero una web en HTML estático. Con login de usuarios. Que tenga modo oscuro.")
    assert r["target"] == "static" and r["options"] == {"sqlite": False, "auth": True}
    assert [d["effect"] for d in r["directives"]] == ["tecnología destino: static", "incluir inicio de sesión"]
    assert r["uninterpreted"] == ["Que tenga modo oscuro."]
    assert pf.interpret("")["target"] == "auto"


def test_plan_is_proposed_without_running_anything(store, tmp_path):
    site = build_site(tmp_path / "sitio")
    st = pf.propose_plan(store, name="Demo", description="Una web estática. Con modo oscuro.",
                         sources=[str(site)], out=str(tmp_path / "out"))
    assert st["status"] == "awaiting_approval" and not st["approved"]
    plan = st["plan"]
    assert [s["id"] for s in plan["steps"]] == ["analizar-1", "especificar", "generar"]
    for s in plan["steps"]:
        assert s["what"] and s["verification"] and s["rationale"] and "risks" in s
    assert any("nunca se copia código" in r for r in plan["reasoning"])
    assert plan["interpretation"]["uninterpreted"] == ["Con modo oscuro."]
    case = CaseStore(store).get(st["case_id"])
    assert case["artifacts"] == [] and store.list_evidence() == []          # nada analizado todavía
    assert not (tmp_path / "out").exists()
    with pytest.raises(pf.PlanError, match="no está aprobado"):
        pf.run_plan(store, st["case_id"])
    with pytest.raises(pf.PlanError):
        pf.propose_plan(store, name="", description="", sources=[str(site)])
    with pytest.raises(pf.PlanError, match="fuente"):
        pf.propose_plan(store, name="x", description="", sources=[])
    with pytest.raises(pf.PlanError, match="no es una URL"):
        pf.propose_plan(store, name="x", description="", sources=["no-existe-eolfi-zz"])


def test_auto_mode_runs_approved_plan_and_records_everything(store, tmp_path):
    site = build_site(tmp_path / "sitio")
    st = pf.propose_plan(store, name="Demo", description="web estática", sources=[str(site)],
                         out=str(tmp_path / "out"))
    cid = st["case_id"]
    st = pf.approve_plan(store, cid, version=1, note="adelante")
    assert st["approved"] and st["status"] == "ready"
    logs = []
    st = pf.run_plan(store, cid, progress=logs.append)
    assert st["status"] in ("done", "done_unverified")
    res = st["results"]
    assert res["analizar-1"]["status"] == "done" and res["especificar"]["spec_version"] == 1
    gen = res["generar"]
    assert gen["target"] == "static" and gen["files"] > 0
    assert gen["status"] == ("done" if gen["verified"] else "partial")
    if not gen["verified"]:
        assert "NO VERIFICADO" in gen["note"] and st["status"] == "done_unverified"
    assert any("paso generar" in m for m in logs)
    case = CaseStore(store).get(cid)
    kinds = [(r["kind"], r["payload"].get("flow") or r["payload"].get("project", {}).get("type")) for r in case["records"]]
    assert ("execution", "plan") in kinds and ("execution", "approval") in kinds
    assert ("analysis", "web") in kinds and ("reconstruction", "create") in kinds
    assert [k for k in kinds if k[1] == "step_result"] == [("execution", "step_result")] * 3


def test_guided_mode_edit_instruction_and_change_proposal(store, tmp_path):
    site = build_site(tmp_path / "sitio")
    st = pf.propose_plan(store, name="Guiado", description="", sources=[str(site)], mode="guided",
                         out=str(tmp_path / "out"))
    cid = st["case_id"]
    with pytest.raises(pf.PlanError, match="versión vigente"):
        pf.approve_plan(store, cid, version=2)
    # Editar el plan antes de aprobar: crea la versión 2, ya aprobada.
    st = pf.approve_plan(store, cid, version=1, edits={"target": "static"}, note="mejor estático")
    assert st["plan"]["version"] == 2 and st["plan"]["changes"] == ["tecnología auto → static"] and st["approved"]
    st = pf.run_plan(store, cid)                                    # guiado: un solo paso
    assert list(st["results"]) == ["analizar-1"] and st["status"] == "awaiting_continue"
    # Una instrucción que no cambia nada queda como nota; una que cambia el plan exige aprobación.
    st = pf.add_instruction(store, cid, "Revisa bien los textos")
    assert st["status"] == "awaiting_continue"
    st = pf.add_instruction(store, cid, "Añade base de datos")
    assert st["status"] == "change_proposed" and st["pending_change"]["edits"]["options"] == {"sqlite": True}
    with pytest.raises(pf.PlanError, match="pendiente"):
        pf.run_plan(store, cid)
    st = pf.accept_change(store, cid, accept=True)
    assert st["plan"]["version"] == 3 and st["plan"]["options"]["sqlite"] is True and st["approved"]
    assert "Añade base de datos" in st["plan"]["instructions"]
    st = pf.run_plan(store, cid)
    assert list(st["results"]) == ["analizar-1", "especificar"]
    # Rechazar un cambio: se sigue con el plan vigente.
    pf.add_instruction(store, cid, "hazlo con django")
    st = pf.accept_change(store, cid, accept=False)
    assert st["plan"]["target"] == "static" and st["status"] == "awaiting_continue"
    types = [d["type"] for d in st["decisions"]]
    assert types.count("approval") == 3 and "instruction" in types and "change_decision" in types


def test_project_api_plan_approve_run_job(tmp_path):
    from eolfi.server import make_server
    from tests.test_server import req

    W = {"X-Eolfi": "1"}
    httpd = make_server(str(tmp_path / "s.db"), "127.0.0.1", 0, tmp_path / "samples")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    try:
        site = build_site(tmp_path / "sitio")
        st, up, _ = req(port, "POST", "/api/projects/upload?name=a.bin", b"\x7fELF-sintetico", W)
        assert st == 200 and up["size"] == 14 and up["path"].endswith(up["sha256"] + ".bin")
        st, plan, _ = req(port, "POST", "/api/projects/plan", json.dumps({
            "name": "API", "description": "estático", "sources": [str(site), up["path"]], "mode": "auto",
            "out": str(tmp_path / "out")}), W)
        assert st == 201 and plan["status"] == "awaiting_approval"
        cid = plan["case_id"]
        assert [s["action"] for s in plan["plan"]["steps"]] == ["analyze", "analyze", "specify", "generate"]
        st, job, _ = req(port, "POST", "/api/jobs", json.dumps({"kind": "project", "body": {"case_id": cid}}), W)
        for _ in range(100):
            _s, d, _ = req(port, "GET", f"/api/jobs?id={job['job_id']}")
            if d["status"] not in ("queued", "running"):
                break
            time.sleep(0.1)
        assert d["status"] == "error" and d["code"] == 409               # sin aprobar no se ejecuta
        st, ok, _ = req(port, "POST", f"/api/projects/{cid}/approve", json.dumps({"version": 1}), W)
        assert st == 200 and ok["approved"]
        st, job, _ = req(port, "POST", "/api/jobs", json.dumps({"kind": "project", "body": {"case_id": cid}}), W)
        for _ in range(600):
            _s, d, _ = req(port, "GET", f"/api/jobs?id={job['job_id']}")
            if d["status"] not in ("queued", "running"):
                break
            time.sleep(0.2)
        assert d["status"] == "done", d
        st, got, _ = req(port, "GET", f"/api/projects/{cid}")
        assert got["status"] in ("done", "done_unverified") and got["results"]["analizar-2"]["status"] == "done"
        st, bad, _ = req(port, "POST", f"/api/projects/{cid}/approve", json.dumps({"version": "1"}), W)
        assert st == 400
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_plan_texts_distinguish_local_and_remote_sources(store, tmp_path):
    site = build_site(tmp_path / ("carpeta-con-un-nombre-largo-" + "x" * 150))
    st = pf.propose_plan(store, name="Local", description="", sources=[str(site), "https://ejemplo.org/"],
                         out=str(tmp_path / "out"))
    local, remote = st["plan"]["steps"][0], st["plan"]["steps"][1]
    assert "sitio local" in local["what"] and "remoto" not in " ".join(local["risks"])
    assert local["title"].startswith("Analizar web: …") and local["title"].endswith(site.name[-20:])
    assert "descarga" in remote["what"] and "remoto" in " ".join(remote["risks"])


def test_default_out_never_collides_and_explicit_existing_out_is_warned(store, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    site = build_site(tmp_path / "sitio")
    (tmp_path / "generated" / "demo").mkdir(parents=True)
    (tmp_path / "generated" / "demo" / "x.txt").write_text("x", encoding="utf-8")
    st = pf.propose_plan(store, name="Demo", description="", sources=[str(site)])
    assert st["plan"]["out"].replace("\\", "/") == "generated/demo-2"
    st2 = pf.propose_plan(store, name="Demo", description="", sources=[str(site)], out=str(tmp_path / "generated" / "demo"))
    assert any("ya existe y no está vacía" in r for r in st2["plan"]["reasoning"])


def test_interpretation_keeps_extra_orders_and_dotted_names():
    r = pf.interpret("Reconstruir la app con Next.js y base de datos, manteniendo sus páginas y su API.")
    assert r["target"] == "next" and r["options"]["sqlite"] is True
    assert r["uninterpreted"] == ["Reconstruir la app con Next.js y base de datos, manteniendo sus páginas y su API."]
    assert pf.interpret("web estática")["uninterpreted"] == []
