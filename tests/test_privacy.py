"""Fase 5: ocultación de datos personales y secretos en artefactos de observación (datos sintéticos)."""
import json

import pytest

from eolfi.core.evidence import EvidenceStore
from eolfi.observe import run_observation
from eolfi.security.privacy import redact
from tests import observe_samples as samples
from tests.test_observe import _script

# Valores sintéticos válidos por su dígito/letra de control (no son de personas reales).
CARD = "4111 1111 1111 1111"          # tarjeta de prueba pública (Luhn válido)
IBAN = "ES91 2100 0418 4502 0005 1332"  # IBAN de ejemplo de la documentación bancaria
DNI = "12345678Z"


@pytest.mark.parametrize("value, kind", [
    ("ana.perez@ejemplo.org", "correo"), (CARD, "tarjeta"), (IBAN, "iban"), (DNI, "dni"), ("X1234567L", "dni"),
    ("+34 612 345 678", "telefono"), ("8.8.8.8", "ip"), ("sk-ant-" + "a" * 24, "clave"),
    ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJhLWZhbHNh", "token"),
])
def test_detects_and_redacts(value, kind):
    out, found = redact(f"dato: {value} fin")
    assert value not in out and found == {kind: 1}
    assert out.startswith("dato: <dato personal:" + kind + " #")
    # misma huella para el mismo valor, sin revelarlo
    assert redact(value)[0] == redact(value)[0]


@pytest.mark.parametrize("text", [
    "4111 1111 1111 1112",            # Luhn inválido
    "12345678A",                      # letra de DNI incorrecta
    "ES00 0000 0000 0000 0000 0000",  # IBAN con control inválido
    "127.0.0.1 192.168.1.10 10.0.0.1",  # IP privadas/locales
    "2026-11-07 versión 1.2.3 puerto 8080 código 0",
    "cwd={sandbox} secreto_visible=False eco=hola",
])
def test_no_false_positives_on_common_text(text):
    out, found = redact(text)
    assert out == text and found == {}


def test_observation_redacts_previews_but_keeps_hashes(tmp_path):
    store = EvidenceStore(tmp_path / "e.db")
    try:
        t = samples.write(tmp_path, "pii.py", f"print('contacto: ana.perez@ejemplo.org tarjeta {CARD}')\n")
        s = _script(t, [{"id": "p", "action": "run", "argv": ["{python}", "{target}"]}])
        rep = run_observation(s, store, authorized=True)
        out = rep["steps"][0]["stdout"]
        assert "ana.perez" not in out["preview"] and CARD not in out["preview"]
        assert "<dato personal:correo" in out["preview"]
        assert rep["coverage"]["personal_data"]["status"] == "redacted"
        assert rep["coverage"]["personal_data"]["redacted"] == {"correo": 1, "tarjeta": 1}
        stored = json.dumps(store.get_evidence(rep["evidence_id"])["result"])
        assert "ana.perez" not in stored and "4111" not in stored
        # Los hashes son de los bytes reales: dos ejecuciones siguen comparándose igual.
        rep2 = run_observation(s, store, authorized=True)
        assert rep2["steps"][0]["stdout"]["sha256"] == out["sha256"]
        # Desactivado explícitamente en el guion: se declara.
        s_off = dict(s, privacy={"redact_personal_data": False})
        off = run_observation(s_off, store, authorized=True)
        assert "ana.perez" in off["steps"][0]["stdout"]["preview"]
        assert off["coverage"]["personal_data"]["status"] == "not_redacted"
    finally:
        store.close()


def test_reconstruction_marks_redacted_output_pending(tmp_path):
    from eolfi.core.cases import CaseStore
    from eolfi.reconstruct import build_model
    from eolfi.spec import store_spec

    store = EvidenceStore(tmp_path / "e.db")
    try:
        cid = CaseStore(store).create("pii")["case_id"]
        t = samples.write(tmp_path, "pii.py", "print('correo: ana.perez@ejemplo.org')\n")
        run_observation(_script(t, [{"id": "p", "action": "run", "argv": ["{python}", "{target}"]}]), store,
                        authorized=True, case_id=cid)
        store_spec(store, cid)
        case = next(c for c in build_model(store, cid)["components"] if c["id"] == "cli")["cases"][0]
        assert case["status"] == "pendiente" and any("datos personales" in p for p in case["pending"])
    finally:
        store.close()


def test_uuid_and_hashes_are_not_personal_data():
    text = "caso 12345678-1234-4123-8123-123456789012 sha 0123456789abcdef0123456789abcdef"
    assert redact(text) == (text, {})


def test_reports_and_job_logs_redact_but_keep_identifiers(tmp_path):
    from eolfi.core.case_report import build_case_report, render_case_html
    from eolfi.core.cases import CaseStore
    from eolfi.core.report import build_report, render_html, render_markdown
    from eolfi.server import EolfiApp

    store = EvidenceStore(tmp_path / "e.db")
    try:
        cases = CaseStore(store)
        cid = cases.create("pii")["case_id"]
        cases.add_record(cid, "specification", {"claims": [
            {"text": "El soporte contesta desde soporte@ejemplo.org", "status": "hypothesis"}]})
        html = render_case_html(build_case_report(cases.get(cid)))
        assert "soporte@ejemplo.org" not in html and "dato personal:correo" in html and cid in html
        t = samples.write(tmp_path, "pii.py", "print('mail ana.perez@ejemplo.org')\n")
        rep = run_observation(_script(t, [{"id": "p", "action": "run", "argv": ["{python}", "{target}"],
                                           "stdin": {"text": "x"}}], privacy={"redact_personal_data": False}),
                              store, authorized=True)
        r = build_report(store, rep["subject"])
        for out in (render_markdown(r), render_html(r)):
            assert "ana.perez@ejemplo.org" not in out and rep["subject"][:16] in out
    finally:
        store.close()
    app = EolfiApp(str(tmp_path / "s.db"))
    job = {"log": [], "started": 0}
    app._tl.job = job
    app._progress("descargando de https://x.org con token sk-ant-" + "a" * 24 + " para ana@ejemplo.org")
    app._tl.job = None
    msg = job["log"][0]["msg"]
    assert "ana@ejemplo.org" not in msg and "sk-ant-aaaa" not in msg
