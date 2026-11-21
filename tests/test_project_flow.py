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
    prompt_only = pf.propose_plan(store, name="x", description="Una herramienta CLI para organizar notas", sources=[])
    assert [step["id"] for step in prompt_only["plan"]["steps"]] == ["especificar", "generar"]
    assert "No hay fuentes adjuntas" in prompt_only["plan"]["reasoning"][0]
    with pytest.raises(pf.PlanError, match="descripción o adjunta"):
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
    monkeypatch.setenv("EOLFI_PROYECTOS", str(tmp_path / "generated"))
    site = build_site(tmp_path / "sitio")
    (tmp_path / "generated" / "demo").mkdir(parents=True)
    (tmp_path / "generated" / "demo" / "x.txt").write_text("x", encoding="utf-8")
    st = pf.propose_plan(store, name="Demo", description="", sources=[str(site)])
    assert st["plan"]["out"] == str((tmp_path / "generated" / "demo-2").resolve())
    st2 = pf.propose_plan(store, name="Demo", description="", sources=[str(site)], out=str(tmp_path / "generated" / "demo"))
    assert any("ya existe y no está vacía" in r for r in st2["plan"]["reasoning"])


def test_spec_from_description_is_a_marked_base():
    from eolfi.generador.spec import build_spec, spec_from_description

    s = spec_from_description("Notas que se guardan en el navegador al recargar. Con contacto.", name="Notas rápidas")
    assert s["target"] == "static" and s["from_description"] and s["sources"] == []
    assert s["features"] == ["localStorage"] and s["design"]["dark_mode"]
    assert s["sections"] == ["Hero", "Features", "ContactForm"] and s["sections_added"] == ["Hero", "Features"]
    assert "Notas que se guardan" not in json.dumps(s, ensure_ascii=False)       # la descripción no se copia
    assert spec_from_description("una calculadora", target="cli")["target"] == "cli"
    with pytest.raises(ValueError, match="target desconocido"):
        spec_from_description("x", target="cobol")
    with pytest.raises(ValueError, match="al menos una fuente"):
        build_spec(None, [], description="  ")


def _sin_fuentes(store, tmp_path, monkeypatch, asistencia):
    """Plan solo con descripción (20/11/2026): antes fallaba en «generar» con «no hay fuentes analizadas»."""
    from eolfi.flows import create_flow
    from eolfi.generador import verify as verify_mod

    monkeypatch.setattr(verify_mod, "verify", lambda root, target, progress=None: {
        "ok": True, "steps": [{"step": "pruebas", "exit": 0, "seconds": 0.1, "tail": ""}]})
    briefs = []

    def falsa(store_, out, brief, **kw):
        briefs.append(brief)
        return asistencia()
    monkeypatch.setattr(create_flow, "run_assist", falsa)
    st = pf.propose_plan(store, name="Notas rápidas", description="Una web estática de notas que se guardan.",
                         sources=[], out=str(tmp_path / "notas"))
    cid = st["case_id"]
    pf.approve_plan(store, cid, version=1, note="adelante", edits={"instructions": ["Hazla accesible."]})
    return pf.run_plan(store, cid), briefs


def test_plan_without_sources_creates_from_description_with_ai(store, tmp_path, monkeypatch):
    st, briefs = _sin_fuentes(store, tmp_path, monkeypatch, lambda: {
        "ok": True, "summary": "notas implementadas", "files_changed": ["app.js"]})
    gen = st["results"]["generar"]
    assert briefs == ["Una web estática de notas que se guardan.\n\nHazla accesible."]
    assert gen["status"] == "done" and gen["verified"] and gen["from_description"]
    assert gen["assist"] == {"ok": True, "summary": "notas implementadas", "files_changed": ["app.js"]}
    assert st["status"] == "done" and (tmp_path / "notas" / "eolfi.spec.json").is_file()
    assert json.loads((tmp_path / "notas" / "eolfi.spec.json").read_text(encoding="utf-8"))["from_description"]


def test_plan_without_sources_is_not_verified_if_the_ai_fails(store, tmp_path, monkeypatch):
    st, _ = _sin_fuentes(store, tmp_path, monkeypatch, lambda: {"ok": False, "summary": "pruebas en rojo"})
    gen = st["results"]["generar"]
    assert gen["status"] == "partial" and gen["verified"] is False and "NO VERIFICADO" in gen["note"]
    assert "la IA no implementó lo pedido" in gen["verification"]["error"] and "pruebas en rojo" in \
        gen["verification"]["error"]
    assert st["status"] == "done_unverified"
    assert any("solo desde la descripción" in i["question"] for i in store.list_incognitas())


def test_plan_without_sources_without_ai_engine_is_not_verified(store, tmp_path, monkeypatch):
    from eolfi.generador.assist import AssistError

    def sin_motor():
        raise AssistError("el motor local no responde")
    st, _ = _sin_fuentes(store, tmp_path, monkeypatch, sin_motor)
    gen = st["results"]["generar"]
    assert gen["verified"] is False and "el motor local no responde" in gen["verification"]["error"]


def test_plan_without_sources_waits_while_eolas_is_busy(store, tmp_path, monkeypatch):
    """Prueba real del 20/11/2026: el encargo nace en un turno del chat que aún retiene Eolas («EolasBusy»)."""
    from eolfi.eolas_v2 import EolasBusy
    from eolfi.flows import create_flow

    esperas = []
    monkeypatch.setattr(create_flow, "_dormir", esperas.append)
    ocupado = iter([True, True, False])

    def asistencia():
        if next(ocupado):
            raise EolasBusy("Eolas V2 está respondiendo una petición")
        return {"ok": True, "summary": "hecho", "files_changed": ["js/main.js"]}
    st, briefs = _sin_fuentes(store, tmp_path, monkeypatch, asistencia)
    assert esperas == [10, 10] and len(briefs) == 3 and st["results"]["generar"]["verified"]


def test_plan_without_sources_gives_up_if_eolas_stays_busy(store, tmp_path, monkeypatch):
    from eolfi.eolas_v2 import EolasBusy
    from eolfi.flows import create_flow

    monkeypatch.setenv("EOLFI_ESPERA_IA_SEG", "20")
    monkeypatch.setattr(create_flow, "_dormir", lambda s: None)

    def siempre_ocupado():
        raise EolasBusy("Eolas V2 está respondiendo una petición")
    st, briefs = _sin_fuentes(store, tmp_path, monkeypatch, siempre_ocupado)
    gen = st["results"]["generar"]
    assert len(briefs) == 3 and gen["status"] == "partial" and gen["verified"] is False
    assert "esperados 20 s" in gen["verification"]["error"]


@pytest.mark.parametrize("plazo,esperas", [("6", [6.0]), ("15", [10.0, 5.0]), ("inf", [10.0] * 120),
                                           ("nan", [10.0] * 120), ("-3", []), ("x", [10.0] * 120)])
def test_plan_without_sources_never_waits_past_the_limit(store, tmp_path, monkeypatch, plazo, esperas):
    """El último intervalo se recorta al remanente y un plazo no finito o ilegible vuelve a 1200 s (como la cola)."""
    from eolfi.eolas_v2 import EolasBusy
    from eolfi.flows import create_flow

    monkeypatch.setenv("EOLFI_ESPERA_IA_SEG", plazo)
    dormidas = []
    monkeypatch.setattr(create_flow, "_dormir", dormidas.append)

    def siempre_ocupado():
        raise EolasBusy("Eolas V2 está respondiendo una petición")
    st, _ = _sin_fuentes(store, tmp_path, monkeypatch, siempre_ocupado)
    assert dormidas == esperas and st["results"]["generar"]["verified"] is False


def test_interpretation_keeps_extra_orders_and_dotted_names():
    r = pf.interpret("Reconstruir la app con Next.js y base de datos, manteniendo sus páginas y su API.")
    assert r["target"] == "next" and r["options"]["sqlite"] is True
    assert r["uninterpreted"] == ["Reconstruir la app con Next.js y base de datos, manteniendo sus páginas y su API."]
    assert pf.interpret("web estática")["uninterpreted"] == []


def test_los_proyectos_generados_van_fuera_del_repositorio(store, tmp_path, monkeypatch):
    """21/11/2026, titular: «los proyectos generados tienen que quedar siempre fuera; después, si son válidos,
    tendrán su repo propio»."""
    from eolfi import proyectos
    from eolfi.flows.create_flow import create_project

    monkeypatch.delenv("EOLFI_PROYECTOS", raising=False)
    assert proyectos.carpeta() == (proyectos.REPO.parent / "Eolfi-proyectos").resolve()
    assert not proyectos.dentro_del_repo(proyectos.carpeta())
    site = build_site(tmp_path / "sitio")
    st = pf.propose_plan(store, name="Demo fuera", description="", sources=[str(site)])
    assert not proyectos.dentro_del_repo(st["plan"]["out"])
    dentro = proyectos.REPO / "generated" / "zz-prueba-no-crear"
    with pytest.raises(pf.PlanError, match="fuera del repositorio de Eolfi"):
        pf.propose_plan(store, name="x", description="", sources=[str(site)], out=str(dentro))
    with pytest.raises(ValueError, match="fuera del repositorio de Eolfi"):
        create_project([str(site)], store, dentro, name="x", do_verify=False)
    assert not dentro.exists()
