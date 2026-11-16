import json
import os
import struct
from pathlib import Path

import pytest

from eolfi import modelos
from eolfi import modelos_reconstruir as rebuild
from eolfi.cli import main
from tests.test_modelos import fixture


@pytest.fixture
def recipe_inputs(tmp_path):
    source = fixture(tmp_path / "entrada original.gguf")
    tool = tmp_path / "cuantizador.exe"
    tool.write_bytes(b"dummy-tool-not-executed")
    return source, tmp_path / "salida nueva", tool


def test_preview_never_runs_or_creates_output(recipe_inputs, monkeypatch):
    source, output, tool = recipe_inputs
    monkeypatch.setattr(rebuild.subprocess, "Popen", lambda *a, **k: pytest.fail("No debe ejecutar"))
    result = rebuild.prepare(source, output, tool, "Q4_0")
    assert result["estado"] == "preparado" and result["ejecutado"] is False
    assert not output.exists()
    assert result["argv"][3:6] == [str(source), str(output / "modelo.gguf"), "Q4_0"]


@pytest.mark.parametrize("changes", [{"source_sha": "0" * 64}, {"tool_sha": "0" * 64},
                                     {"bundle_sha": "0" * 64}, {"threads": 0}, {"buffer_mib": 0},
                                     {"timeout": float("nan")}])
def test_invalid_or_mismatched_pin_no_output(recipe_inputs, changes):
    source, output, tool = recipe_inputs
    with pytest.raises(ValueError):
        rebuild.prepare(source, output, tool, "Q4_0", **changes)
    assert not output.exists()


def test_bundle_pin_includes_dll(recipe_inputs):
    source, output, tool = recipe_inputs
    dll = tool.with_name("quantizer-impl.dll")
    dll.write_bytes(b"version1")
    first = rebuild.prepare(source, output, tool, "Q4_0")
    dll.write_bytes(b"version2")
    with pytest.raises(ValueError, match="paquete"):
        rebuild.prepare(source, output, tool, "Q4_0", bundle_sha=first["herramienta"]["bundle_sha256"])


def test_existing_output_preserved(recipe_inputs):
    source, output, tool = recipe_inputs
    output.mkdir()
    note = output / "conservar.txt"
    note.write_text("usuario")
    with pytest.raises(FileExistsError):
        rebuild.prepare(source, output, tool, "Q4_0")
    assert note.read_text() == "usuario"


def test_rejects_requantization_and_split(recipe_inputs):
    source, output, tool = recipe_inputs
    source = source.rename(source.with_name("entrada-00001-of-00002.gguf"))
    with pytest.raises(ValueError, match="divididas"):
        rebuild.prepare(source, output, tool, "Q4_0")
    source = source.rename(source.with_name("m.gguf"))
    fixture(source, kind=24, dims=(32,))
    with pytest.raises(ValueError, match="requantizan"):
        rebuild.prepare(source, output, tool, "Q4_0")


def test_rejects_renamed_shard_and_zero_layers(recipe_inputs):
    source, output, tool = recipe_inputs
    fixture(source, metadata=[("general.architecture", 8, "gemma"), ("split.count", 4, 2)])
    with pytest.raises(ValueError, match="divididas"):
        rebuild.prepare(source, output, tool, "Q4_0")
    fixture(source, metadata=[("general.architecture", 8, "gemma"), ("gemma.block_count", 4, 0)])
    with pytest.raises(ValueError, match="capas"):
        rebuild.prepare(source, output, tool, "Q4_0")


def fake_process(monkeypatch, code=0, mutate=False):
    class Process:
        pid = 123456789
        returncode = code
        def __init__(self, argv, **kwargs):
            assert kwargs["stdin"] is rebuild.subprocess.DEVNULL
            assert "EOLAS_V2_API_KEY" not in kwargs["env"]
            assert "PIP_INDEX_URL" not in kwargs["env"] and "NPM_CONFIG_REGISTRY" not in kwargs["env"]
            target = Path(argv[4])
            fixture(target, metadata=[("general.architecture", 8, "gemma"), ("gemma.block_count", 4, 2),
                                      ("general.file_type", 4, 2)])
            if code:
                target.write_bytes(b"incomplete artifact")
            if mutate:
                with open(argv[3], "ab") as stream:
                    stream.write(b"changed")
        def poll(self):
            return self.returncode
    monkeypatch.setattr(rebuild.subprocess, "Popen", Process)


def test_conversion_preserves_unknown_readiness_and_receipt(recipe_inputs, monkeypatch):
    source, output, tool = recipe_inputs
    monkeypatch.setenv("EOLAS_V2_API_KEY", "secret-not-in-child")
    monkeypatch.setenv("PIP_INDEX_URL", "https://example.invalid/private-test-marker")
    monkeypatch.setenv("NPM_CONFIG_REGISTRY", "https://example.invalid/private-test-marker")
    fake_process(monkeypatch)
    result = rebuild.execute(rebuild.prepare(source, output, tool, "Q4_0"))
    assert result["estado"] == "NO VERIFICADO"
    assert result["conversion"]["exit"] == 0 and result["conversion"]["error"] is None
    assert result["sha256_entrada_despues"] == modelos.sha256(source)
    assert result["auditoria_salida"]["sha256"] == modelos.sha256(output / "modelo.gguf")
    assert json.loads((output / "receta.json").read_text(encoding="utf-8"))["estado"] == "NO VERIFICADO"


def test_failed_conversion_keeps_partial_and_original(recipe_inputs, monkeypatch):
    source, output, tool = recipe_inputs
    original = source.read_bytes()
    fake_process(monkeypatch, code=7)
    result = rebuild.execute(rebuild.prepare(source, output, tool, "Q4_0"))
    assert result["estado"] == "fallido" and result["conversion"]["exit"] == 7
    assert (output / "modelo.gguf").read_bytes() == b"incomplete artifact"
    assert source.read_bytes() == original


def test_input_mutated_by_process_is_not_accepted(recipe_inputs, monkeypatch):
    source, output, tool = recipe_inputs
    fake_process(monkeypatch, mutate=True)
    result = rebuild.execute(rebuild.prepare(source, output, tool, "Q4_0"))
    assert result["estado"] == "fallido"
    assert "entrada cambió" in result["conversion"]["error"]


def test_tool_or_argv_change_after_preparation_blocks_execution(recipe_inputs, monkeypatch):
    source, output, tool = recipe_inputs
    result = rebuild.prepare(source, output, tool, "Q4_0")
    monkeypatch.setattr(rebuild.subprocess, "Popen", lambda *a, **k: pytest.fail("No debe ejecutar"))
    result["argv"].append("--allow-requantize")
    with pytest.raises(ValueError, match="argumentos modificados"):
        rebuild.execute(result)
    result["argv"].pop()
    tool.write_bytes(b"changed tool")
    with pytest.raises(ValueError, match="biblioteca cambió"):
        rebuild.execute(result)
    assert not output.exists()


def test_execute_requires_user_pins(recipe_inputs, capsys):
    source, output, tool = recipe_inputs
    assert main(["modelos", "reconstruir", str(source), "--out", str(output), "--cuantizador", str(tool),
                 "--ejecutar"]) == 2
    assert "sha256-paquete" in capsys.readouterr().out
    assert not output.exists()


def test_timeout_stops_own_process_and_records_failure(recipe_inputs, monkeypatch):
    source, output, tool = recipe_inputs
    stopped = []
    class Process:
        pid = 123456789
        returncode = None
        def __init__(self, *args, **kwargs):
            pass
        def poll(self):
            return self.returncode
    def terminate(proc):
        stopped.append(proc.pid)
        proc.returncode = -9
    monkeypatch.setattr(rebuild.subprocess, "Popen", Process)
    monkeypatch.setattr(rebuild, "_terminate", terminate)
    result = rebuild.execute(rebuild.prepare(source, output, tool, "Q4_0"), timeout=0.000001)
    assert stopped == [123456789]
    assert result["estado"] == "fallido" and result["conversion"]["exit"] == -9
    assert "agotado" in result["conversion"]["error"]
    assert (output / "receta.json").exists()


def test_keyboard_interrupt_never_claims_completed(recipe_inputs, monkeypatch):
    source, output, tool = recipe_inputs
    stopped = []
    class Process:
        pid = 123456789
        returncode = None
        calls = 0
        def __init__(self, *args, **kwargs):
            pass
        def poll(self):
            self.calls += 1
            if self.calls == 1:
                raise KeyboardInterrupt
            return self.returncode
    def terminate(proc):
        stopped.append(proc.pid)
        proc.returncode = -9
    monkeypatch.setattr(rebuild.subprocess, "Popen", Process)
    monkeypatch.setattr(rebuild, "_terminate", terminate)
    recipe = rebuild.prepare(source, output, tool, "Q4_0")
    with pytest.raises(KeyboardInterrupt):
        rebuild.execute(recipe)
    saved = json.loads((output / "receta.json").read_text(encoding="utf-8"))
    assert saved["estado"] == "interrumpido" and stopped == [123456789]
    assert "NO VERIFICADO" in saved["verificacion"]["entrada_despues"]


def test_low_disk_never_starts_process(recipe_inputs, monkeypatch):
    from types import SimpleNamespace
    source, output, tool = recipe_inputs
    recipe = rebuild.prepare(source, output, tool, "Q4_0")
    monkeypatch.setattr(rebuild.shutil, "disk_usage", lambda p: SimpleNamespace(free=0))
    monkeypatch.setattr(rebuild.subprocess, "Popen", lambda *a, **k: pytest.fail("No debe ejecutar"))
    with pytest.raises(OSError, match="Espacio insuficiente"):
        rebuild.execute(recipe)
    assert not output.exists()


def test_interrupt_during_final_hash_is_recorded(recipe_inputs, monkeypatch):
    source, output, tool = recipe_inputs
    recipe = rebuild.prepare(source, output, tool, "Q4_0")
    real_sha = rebuild.sha256
    def interrupt(path):
        if Path(path) == source:
            raise KeyboardInterrupt
        return real_sha(path)
    fake_process(monkeypatch)
    monkeypatch.setattr(rebuild, "sha256", interrupt)
    with pytest.raises(KeyboardInterrupt):
        rebuild.execute(recipe)
    saved = json.loads((output / "receta.json").read_text(encoding="utf-8"))
    assert saved["estado"] == "interrumpido"
    assert saved["conversion"]["exit"] == 0
    assert "NO VERIFICADO" in saved["verificacion"]["entrada_despues"]


@pytest.mark.skipif(not os.environ.get("EOLFI_TEST_QUANTIZER"), reason="Requiere cuantizador nativo autorizado explícitamente")
@pytest.mark.parametrize("quant", list(rebuild.TYPES))
def test_native_quantizer_bf16_targets(tmp_path, quant):
    from tests.ggufgen import build_bf16

    source = tmp_path / "sintetico-bf16.gguf"
    expected = build_bf16(source)
    output = tmp_path / quant.lower()
    tool = Path(os.environ["EOLFI_TEST_QUANTIZER"])
    recipe = rebuild.prepare(source, output, tool, quant, tool_sha=os.environ["EOLFI_TEST_QUANTIZER_SHA256"])
    result = rebuild.execute(recipe, timeout=60)
    assert result["estado"] == "NO VERIFICADO", result
    assert result["conversion"]["exit"] == 0 and result["conversion"]["error"] is None
    assert result["auditoria_salida"]["tipo_archivo"] == rebuild.TYPES[quant]
    assert result["sha256_entrada_despues"] == result["entrada"]["sha256"]
    if quant != "Q8_0":
        assert result["auditoria_salida"]["estado"] == "NO VERIFICADO"
        assert result["auditoria_salida"]["tipos_no_cubiertos"]
        if quant == "Q4_0":
            # El preset del SDK conserva output.weight en Q6_K, no es un modo --pure.
            assert result["auditoria_salida"]["tipos_no_cubiertos"] == {"14": 1}
    else:
        assert result["auditoria_salida"]["estado"] == "estructura_verificada"
    if quant != "Q8_0":
        return
    # Comprobación numérica del formato Q8_0, independiente de la aceptación del proceso.
    with (output / "modelo.gguf").open("rb") as stream:
        reader = modelos.Reader(stream)
        assert reader.read(4) == b"GGUF"
        reader.number("I")
        count, metadata = reader.number("Q"), reader.number("Q")
        for _ in range(metadata):
            reader.string()
            reader.value(reader.number("I"))
        tensors = []
        for _ in range(count):
            name, nd = reader.string(), reader.number("I")
            dims = [reader.number("Q") for _ in range(nd)]
            kind, offset = reader.number("I"), reader.number("Q")
            tensors.append((name, dims, kind, offset))
        base = (stream.tell() + 31) // 32 * 32
        name, dims, kind, offset = next(t for t in tensors if t[0] == "token_embd.weight")
        assert kind == 8 and dims == [256, 32]
        stream.seek(base + offset)
        actual = []
        for _ in range(len(expected) // 32):
            scale = struct.unpack("<e", stream.read(2))[0]
            actual.extend(scale * q for q in struct.unpack("<32b", stream.read(32)))
    errors = [abs(a - b) for a, b in zip(expected, actual)]
    assert 0 < max(errors) < 0.003
