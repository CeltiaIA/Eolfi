import json

import pytest

from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Authority, Confidence, Evidence, Status


def _ev(result, provider="p1", params=None):
    return Evidence(subject="abc", provider=provider, provider_version="1",
                    operation="detect_format", params=params or {}, result=result,
                    authority=Authority.DISTRIBUTED_ARTIFACT, confidence=Confidence.HIGH)


def test_dedup_and_conflict():
    s = EvidenceStore(":memory:")
    id1, new1 = s.add_evidence(_ev({"format": "elf"}))
    assert new1 is True
    _id2, new2 = s.add_evidence(_ev({"format": "elf"}))     # duplicado exacto
    assert new2 is False
    assert len(s.list_evidence()) == 1
    id3, _ = s.add_evidence(_ev({"format": "pe"}, provider="p2"))      # conflicto
    incs = [i for i in s.list_incognitas() if "Conflicto" in i["question"]]
    assert len(incs) == 1
    assert json.loads(incs[0]["evidence_for"]) == [id3]
    assert json.loads(incs[0]["evidence_against"]) == [id1]


def test_different_params_is_not_conflict():
    s = EvidenceStore(":memory:")
    s.add_evidence(_ev({"count": 3}, params={"min_len": 4}))
    s.add_evidence(_ev({"count": 9}, params={"min_len": 8}))
    assert s.list_incognitas() == []


def test_roundtrip(tmp_path):
    pkg = tmp_path / "pkg.json"
    s = EvidenceStore(":memory:")
    s.add_evidence(_ev({"format": "elf", "nota": "año ñ — ✓"}))
    s.export_package(pkg)
    s2 = EvidenceStore(":memory:")
    assert s2.import_package(pkg) == 1
    assert s2.import_package(pkg) == 0          # idempotente
    assert len(s2.list_evidence()) == 1


def _tamper(tmp_path, mutate):
    pkg = tmp_path / "pkg.json"
    s = EvidenceStore(":memory:")
    s.add_evidence(_ev({"format": "elf"}))
    s.export_package(pkg)
    doc = json.loads(pkg.read_text(encoding="utf-8"))
    mutate(doc)
    pkg.write_text(json.dumps(doc), encoding="utf-8")
    return pkg


def test_import_rejects_unknown_column(tmp_path):
    def evil(doc):
        doc["evidence"][0]["x) VALUES (1); DROP TABLE evidence; --"] = 1
    pkg = _tamper(tmp_path, evil)
    s = EvidenceStore(":memory:")
    with pytest.raises(ValueError, match="columnas desconocidas"):
        s.import_package(pkg)
    assert s.list_evidence() == []


def test_import_rejects_tampered_result(tmp_path):
    def forge(doc):
        doc["evidence"][0]["result"] = json.dumps({"format": "pe"})
    pkg = _tamper(tmp_path, forge)
    with pytest.raises(ValueError, match="huella"):
        EvidenceStore(":memory:").import_package(pkg)


def test_import_is_atomic(tmp_path):
    def half_bad(doc):
        good = dict(doc["evidence"][0])
        bad = dict(good, evidence_id="0" * 64)
        doc["evidence"] = [good, bad]
    pkg = _tamper(tmp_path, half_bad)
    s = EvidenceStore(":memory:")
    with pytest.raises(ValueError):
        s.import_package(pkg)
    assert s.list_evidence() == []


def test_resolve_incognita():
    s = EvidenceStore(":memory:")
    s.add_evidence(_ev({"format": "elf"}))
    s.add_evidence(_ev({"format": "pe"}, provider="p2"))
    iid = s.list_incognitas()[0]["incognita_id"]
    assert s.resolve_incognita(iid)
    assert s.list_incognitas(Status.OPEN) == []
    assert not s.resolve_incognita("nope")
