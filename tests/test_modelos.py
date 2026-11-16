"""GGUF hostiles y control de identidad, sin ejecutar ningún modelo."""
import hashlib
import json
import struct

import pytest

from eolfi import modelos
from eolfi.cli import main


def string(text):
    raw = text.encode()
    return struct.pack("<Q", len(raw)) + raw


def fixture(path, *, tail=b"", kind=0, dims=(8,), offset=0, second=False, metadata=None):
    metadata = metadata or [("general.architecture", 8, "gemma"), ("gemma.block_count", 4, 2)]
    raw = b"GGUF" + struct.pack("<IQQ", 3, 2 if second else 1, len(metadata))
    for key, tp, value in metadata:
        raw += string(key) + struct.pack("<I", tp)
        raw += string(value) if tp == 8 else struct.pack("<" + modelos.SCALARS[tp], value)
    tensor = lambda name: string(name) + struct.pack("<I", len(dims)) + b"".join(struct.pack("<Q", d) for d in dims) + struct.pack("<IQ", kind, offset)
    raw += tensor("peso")
    if second:
        raw += tensor("otro")
    raw += b"\0" * (-len(raw) % 32) + b"\0" * 32 + tail
    path.write_bytes(raw)
    return path


def test_valid_identity_and_planner(tmp_path):
    path = fixture(tmp_path / "m.gguf")
    result = modelos.audit(path)
    assert result["estado"] == "estructura_verificada", result
    assert result["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result["bytes_sobrantes"] == 0
    assert result["planificador"] == {"gemma.block_count": 2}
    assert "No observa conexiones" in result["limites"][1]


@pytest.mark.parametrize("options", [{"tail": b"payload"}, {"dims": (0,)}, {"offset": 1},
                                   {"offset": 64}, {"second": True}, {"kind": 2, "dims": (31,)}])
def test_rejects_bad_tensors(tmp_path, options):
    result = modelos.audit(fixture(tmp_path / "bad.gguf", **options))
    assert result["estado"] == "fallido", result


@pytest.mark.parametrize("kind", [9, 10, 11, 12, 13, 14, 15, 999])
def test_unknown_tensor_never_green(tmp_path, kind):
    result = modelos.audit(fixture(tmp_path / "unknown.gguf", kind=kind))
    assert result["estado"] == "NO VERIFICADO"
    assert result["incognitas"]
    assert "bytes_sobrantes" not in result
    assert result["tipos_no_cubiertos"] == {str(kind): 1}


@pytest.mark.parametrize("data", [b"", b"GGUF", b"GGUF" + struct.pack("<IQQ", 3, 1, 1) + struct.pack("<Q", 2**63),
                                b"GGUF" + struct.pack("<IQQ", 999, 0, 0)])
def test_truncated_or_budgeted(tmp_path, data):
    path = tmp_path / "bad.gguf"
    path.write_bytes(data)
    assert modelos.audit(path)["estado"] == "fallido"


def test_duplicate_metadata(tmp_path):
    path = fixture(tmp_path / "bad.gguf", metadata=[("x", 4, 1), ("x", 4, 2)])
    assert modelos.audit(path)["estado"] == "fallido"


def test_template_is_data_and_unicode_bytes(tmp_path):
    path = fixture(tmp_path / "m.gguf", metadata=[("tokenizer.chat_template", 8, "{{ eval('á') }}")])
    result = modelos.audit(path)
    assert result["plantilla_bytes"] == len("{{ eval('á') }}".encode())
    assert result["cadenas_a_revisar"][0]["cadena"] == "eval"


def manifest(tmp_path, path):
    target = tmp_path / "trust.json"
    target.write_text(json.dumps({"schema": "eolfi.modelos.confianza/v1", "modelos": [
        {"archivo": str(path), "sha256": modelos.sha256(path)}]}))
    return target


def test_trust_checks_contents_again(tmp_path):
    path = fixture(tmp_path / "m.gguf")
    trust = manifest(tmp_path, path)
    assert modelos.check_trust(path, trust)["estado"] == "hash_autorizado"
    path.write_bytes(path.read_bytes() + b"modified")
    with pytest.raises(ValueError, match="SHA-256 distinto"):
        modelos.check_trust(path, trust)


def test_split_requires_every_shard(tmp_path):
    path = fixture(tmp_path / "m-00001-of-00002.gguf")
    with pytest.raises(ValueError, match="Faltan partes"):
        modelos.check_trust(path, manifest(tmp_path, path))


def test_policy_blocks_start_before_process_or_network(tmp_path, monkeypatch):
    from eolfi import eolas_v2

    path = fixture(tmp_path / "m.gguf")
    trust = manifest(tmp_path, path)
    path.write_bytes(b"changed")
    monkeypatch.setenv("EOLFI_MODELOS_CONFIANZA", str(trust))
    monkeypatch.setattr(eolas_v2, "is_retired", lambda *a: False)
    monkeypatch.setattr(eolas_v2, "profile_config", lambda *a: {"model": str(path)})
    monkeypatch.setattr(eolas_v2, "_runtime", lambda: pytest.fail("No debe consultar runtime"))
    with pytest.raises(ValueError, match="SHA-256 distinto"):
        eolas_v2._start_locked("gemma_q4", {"profiles": {}})


def test_cli_without_database(tmp_path, capsys):
    path = fixture(tmp_path / "m.gguf")
    assert main(["modelos", "auditar", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["estado"] == "estructura_verificada"
    path.write_bytes(b"bad")
    assert main(["modelos", "auditar", str(path)]) == 2


def test_missing_manifest_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("EOLFI_MODELOS_CONFIANZA", str(tmp_path / "missing.json"))
    with pytest.raises(OSError):
        modelos.enforce_trust(tmp_path / "model.gguf")


@pytest.mark.parametrize("data", [[], {}, {"schema": "eolfi.modelos.confianza/v1", "modelos": ["bad"]},
                                 {"schema": "eolfi.modelos.confianza/v1", "modelos": [{"archivo": "relative"}]}])
def test_malformed_manifest(tmp_path, data):
    target = tmp_path / "bad.json"
    target.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        modelos.check_trust(tmp_path / "m.gguf", target)


def test_policy_rejects_model_overrides(tmp_path, monkeypatch):
    from eolfi import eolas_v2

    path = fixture(tmp_path / "m.gguf")
    monkeypatch.setenv("EOLFI_MODELOS_CONFIANZA", str(manifest(tmp_path, path)))
    monkeypatch.setattr(eolas_v2, "is_retired", lambda *a: False)
    monkeypatch.setattr(eolas_v2, "profile_config", lambda *a: {"model": str(path)})
    monkeypatch.setattr(eolas_v2, "_runtime", lambda: pytest.fail("No debe consultar runtime"))
    with pytest.raises(ValueError, match="extra_args"):
        eolas_v2._start_locked("gemma_q4", {"extra_args": ["-m", "otro.gguf"]})


def test_split_hashes_every_part(tmp_path):
    first = fixture(tmp_path / "m-00001-of-00002.gguf")
    second = fixture(tmp_path / "m-00002-of-00002.gguf")
    target = tmp_path / "trust.json"
    target.write_text(json.dumps({"schema": "eolfi.modelos.confianza/v1", "modelos": [
        {"archivo": str(first), "partes": [{"archivo": str(p), "sha256": modelos.sha256(p)}
                                          for p in (first, second)]}]}))
    assert modelos.check_trust(first, target)["partes"] == 2
    second.write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA-256 distinto"):
        modelos.check_trust(first, target)


def test_vocabulary_is_not_executable(tmp_path):
    path = fixture(tmp_path / "m.gguf", metadata=[("tokenizer.ggml.merges", 8, "exec socket wget")])
    assert modelos.audit(path)["cadenas_a_revisar"] == []


def test_mcp_audits_stored_bin_and_obeys_roots(tmp_path):
    from eolfi.mcp_server import EolfiMCP

    allowed = tmp_path / "samples"
    allowed.mkdir()
    path = fixture(allowed / "abc.bin")
    mcp = EolfiMCP(db=str(tmp_path / "no-db.db"), roots=[str(allowed)])
    result = mcp.call_tool("eolfi_modelos_auditar", {"ruta": str(path)})
    assert result["isError"] is False, result
    assert result["structuredContent"]["sha256"] == modelos.sha256(path)
    assert "DATOS" in result["content"][0]["text"]
    assert not (tmp_path / "no-db.db").exists()
    outside = fixture(tmp_path / "outside.gguf")
    assert mcp.call_tool("eolfi_modelos_auditar", {"ruta": str(outside)})["isError"]
    path.write_bytes(b"not a model")
    assert mcp.call_tool("eolfi_modelos_auditar", {"ruta": str(path)})["isError"]
