"""Fase 6: herramientas fijadas por ruta, versión y SHA-256 para repetir resultados."""
import json

from eolfi.security import toolpin


def test_lock_roundtrip_and_drift(tmp_path, capsys):
    lock = tmp_path / "herramientas.lock.json"
    data = toolpin.write_lock(lock)
    assert data["tools"]["python"]["sha256"] and data["tools"]["python"]["version"]
    assert toolpin.check_lock(lock)["matches"] is True
    changed = json.loads(lock.read_text(encoding="utf-8"))
    changed["tools"]["python"]["sha256"] = "0" * 64
    changed["tools"]["herramienta-retirada"] = {"path": "x", "version": "1", "sha256": "1" * 64}
    lock.write_text(json.dumps(changed), encoding="utf-8")
    rep = toolpin.check_lock(lock)
    assert not rep["matches"]
    kinds = {(d["tool"], d["change"]) for d in rep["drift"]}
    assert ("python", "sha256") in kinds and ("herramienta-retirada", "ausente") in kinds
    from eolfi.cli import main
    assert main(["--db", str(tmp_path / "d.db"), "doctor", "--check-pin", str(lock)]) == 6
    capsys.readouterr()


def test_external_evidence_records_tool_fingerprint(tmp_path):
    """Un proveedor externo (falso, sintético) deja ruta y huella del ejecutable en el entorno de la evidencia."""
    import sys

    from eolfi.core.evidence import EvidenceStore
    from eolfi.flows.triage_flow import record_findings
    from eolfi.providers.external import ExternalCommandProvider

    class Fake(ExternalCommandProvider):
        name = "falso"
        binaries = ()

        def resolve(self):
            return sys.executable

        def run(self, target):
            return []

    s = EvidenceStore(tmp_path / "e.db")
    try:
        prov = Fake()
        ids = record_findings(s, "a" * 64, prov, [{"operation": "x", "result": {"ok": True}}], "Windows 11 py3.12")
        env = s.get_evidence(ids[0])["environment"]
        assert "falso" in env and "sha256:" + toolpin.file_fingerprint(sys.executable)[:16] in env
    finally:
        s.close()
