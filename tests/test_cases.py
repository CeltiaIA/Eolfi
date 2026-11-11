import json

import pytest

from eolfi.core.cases import CaseStore
from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Authority, Confidence, Evidence


def test_case_persists_artifacts_records_and_links_evidence(tmp_path):
    db = tmp_path / "eolfi.db"
    store = EvidenceStore(db)
    cases = CaseStore(store)
    case = cases.create("Calculadora", "Caso de prueba")
    subject = "a" * 64
    cases.add_artifact(case["case_id"], subject, size=123, format="ELF", version="1.2.3", provenance="muestra propia",
                       path="samples/calc", platform="Linux x86_64")
    ev = Evidence(subject=subject, provider="fixture", provider_version="1", operation="detect_format",
                  params={}, result={"format": "ELF"}, authority=Authority.DISTRIBUTED_ARTIFACT,
                  confidence=Confidence.HIGH)
    evidence_id, _ = store.add_evidence(ev)
    record_id = cases.add_record(case["case_id"], "observation", {
        "scenario": "inicio", "artifacts": [subject], "evidence_ids": [evidence_id],
        "result": {"exit_code": 0},
    })
    store.close()

    reopened = EvidenceStore(db)
    saved = CaseStore(reopened).get(case["case_id"])
    assert saved["artifacts"][0]["subject"] == subject
    assert saved["artifacts"][0]["version"] == "1.2.3"
    assert saved["records"][0]["record_id"] == record_id
    assert saved["records"][0]["payload"]["evidence_ids"] == [evidence_id]
    assert [e["evidence_id"] for e in saved["evidence"]] == [evidence_id]
    reopened.close()


def test_case_record_rejects_unknown_references_and_bad_kind():
    store = EvidenceStore(":memory:")
    cases = CaseStore(store)
    case = cases.create("Caso")
    with pytest.raises(ValueError, match="artefactos"):
        cases.add_record(case["case_id"], "observation", {"artifacts": ["b" * 64]})
    with pytest.raises(ValueError, match="kind"):
        cases.add_record(case["case_id"], "guess", {})
    store.close()


def test_case_history_keeps_only_three_most_recent_cases():
    store = EvidenceStore(":memory:")
    cases = CaseStore(store)
    created = [cases.create(f"Proyecto {number}")["case_id"] for number in range(4)]
    listed = [case["case_id"] for case in cases.list()]
    assert listed == list(reversed(created[1:]))
    with pytest.raises(ValueError, match="no encontrado"):
        cases.get(created[0])
    store.close()


def test_case_artifact_requires_sha256_and_export_contains_bundle(tmp_path):
    store = EvidenceStore(":memory:")
    cases = CaseStore(store)
    case = cases.create("Caso")
    with pytest.raises(ValueError, match="SHA-256"):
        cases.add_artifact(case["case_id"], "not-a-hash", size=0, format="unknown", provenance="declared")
    subject = "c" * 64
    cases.add_artifact(case["case_id"], subject, size=0, format="unknown", provenance="declared")
    ev = Evidence(subject=subject, provider="fixture", provider_version="1", operation="detect_format",
                  params={}, result={"format": "unknown"}, authority=Authority.DISTRIBUTED_ARTIFACT,
                  confidence=Confidence.HIGH)
    evidence_id, _ = store.add_evidence(ev)
    record_id = cases.add_record(case["case_id"], "specification", {
        "title": "Formato observado", "artifacts": [subject], "evidence_ids": [evidence_id],
    })
    out = tmp_path / "case.json"
    cases.export(case["case_id"], out)
    bundle = json.loads(out.read_text(encoding="utf-8"))
    assert bundle["case_package_version"] == 2
    assert bundle["case"]["artifacts"][0]["identity"] == "content"
    assert bundle["case"]["artifacts"][0]["content_sha256"] == subject
    assert bundle["case"]["artifacts"][0]["subject"] == subject
    assert bundle["evidence_package"]["schema_version"] == 1
    restored = EvidenceStore(":memory:")
    restored_cases = CaseStore(restored)
    assert restored_cases.import_case(out) is True
    imported = restored_cases.get(case["case_id"])
    assert imported["records"][0]["record_id"] == record_id
    assert imported["evidence"][0]["evidence_id"] == evidence_id
    assert restored_cases.import_case(out) is False
    restored.close()
    store.close()


def test_case_import_rejects_damaged_record_without_partial_case(tmp_path):
    source = EvidenceStore(":memory:")
    cases = CaseStore(source)
    case = cases.create("Caso")
    cases.add_artifact(case["case_id"], "d" * 64, size=10, format="ELF", provenance="declarada")
    cases.add_record(case["case_id"], "observation", {"artifacts": ["d" * 64]})
    package = tmp_path / "case.json"
    cases.export(case["case_id"], package)
    data = json.loads(package.read_text(encoding="utf-8"))
    data["case"]["records"][0]["payload"]["artifacts"] = ["f" * 64]
    package.write_text(json.dumps(data), encoding="utf-8")

    target = EvidenceStore(":memory:")
    target_cases = CaseStore(target)
    with pytest.raises(ValueError, match="artefactos ajenos"):
        target_cases.import_case(package)
    assert target_cases.list() == []
    target.close()
    source.close()
