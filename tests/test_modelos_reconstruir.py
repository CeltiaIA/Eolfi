import json
import os
import struct
from pathlib import Path

import pytest

from eolfi import modelos
from eolfi import modelos_reconstruir as rebuild
from eolfi import eolas_v2
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


def fake_process(monkeypatch, code=0, mutate=False, metadata=None):
    class Process:
        pid = 123456789
        returncode = code
        def __init__(self, argv, **kwargs):
            assert kwargs["stdin"] is rebuild.subprocess.DEVNULL
            assert "EOLAS_V2_API_KEY" not in kwargs["env"]
            assert "PIP_INDEX_URL" not in kwargs["env"] and "NPM_CONFIG_REGISTRY" not in kwargs["env"]
            target = Path(argv[4])
            fixture(target, metadata=metadata or [("general.architecture", 8, "gemma"),
                                                  ("gemma.block_count", 4, 2),
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


# --- Smoke de inferencia ---

@pytest.fixture
def rebuilt(recipe_inputs, monkeypatch):
    source, output, tool = recipe_inputs
    fake_process(monkeypatch)
    assert rebuild.execute(rebuild.prepare(source, output, tool, "Q4_0"))["estado"] == "NO VERIFICADO"
    runner = tool.with_name("ejecutor.exe")
    runner.write_bytes(b"dummy-runner-not-executed")
    return output, runner


def fake_runner(monkeypatch, answer="43\n", code=0, mutate=False, raw=False):
    class Process:
        pid = 123456789
        returncode = code
        def __init__(self, argv, **kwargs):
            assert kwargs["stdin"] is rebuild.subprocess.DEVNULL
            assert "EOLAS_V2_API_KEY" not in kwargs["env"]
            assert argv[3:6] == ["--device", "none", "-ngl"] and argv[6] == "0"
            assert argv[argv.index("--chat-template-kwargs") + 1] == '{"enable_thinking":false}'
            # Forma de la salida de llama-cli: pancarta, eco «> pregunta», respuesta y estadísticas.
            shown = answer if raw else (f"build      : b1-test\r\n\r\n> {argv[-1]}\r\n{answer}\r\n\r\n"
                                        "[ Prompt: 9.0 t/s | Generation: 2.0 t/s ]\r\n\r\nExiting...\r\n")
            kwargs["stdout"].write(shown.encode("utf-8"))
            kwargs["stderr"].write(b"llama_perf: carga\n")
            if mutate:
                with open(argv[2], "ab") as stream:
                    stream.write(b"changed")
        def poll(self):
            return self.returncode
    monkeypatch.setattr(rebuild.subprocess, "Popen", Process)


def test_smoke_preview_never_runs_or_writes(rebuilt, monkeypatch):
    output, runner = rebuilt
    before = sorted(p.name for p in output.iterdir())
    monkeypatch.setattr(rebuild.subprocess, "Popen", lambda *a, **k: pytest.fail("No debe ejecutar"))
    plan = rebuild.prepare_smoke(output, runner)
    assert plan["estado"] == "preparado" and plan["ejecutado"] is False
    assert plan["modelo_sha256"] == modelos.sha256(output / "modelo.gguf")
    assert sorted(p.name for p in output.iterdir()) == before


def test_smoke_pass_keeps_bench_unverified_and_recipe_untouched(rebuilt, monkeypatch):
    output, runner = rebuilt
    recipe = (output / "receta.json").read_bytes()
    monkeypatch.setenv("EOLAS_V2_API_KEY", "secret-not-in-child")
    fake_runner(monkeypatch, answer="La respuesta es 43.\n")
    result = rebuild.execute_smoke(rebuild.prepare_smoke(output, runner))
    assert result["estado"] == "smoke_superado" and result["ejecucion"]["exit"] == 0
    assert result["verificacion"]["banco"] == "NO VERIFICADO"
    assert result["ejecucion"]["velocidad_declarada_en_log"] == "2.0 t/s"
    assert result["herramienta"]["version_declarada_en_log"] == "b1-test"
    assert (output / "receta.json").read_bytes() == recipe
    assert json.loads(Path(result["resultado"]).read_text(encoding="utf-8"))["estado"] == "smoke_superado"


@pytest.mark.parametrize("answer,code", [("143\n", 0), ("no lo sé\n", 0), ("43\n", 3),
                                       ("<|channel>thought 43", 0),
                                       ("<think>43</think>No lo sé", 0), ("<think>43", 0)])
def test_smoke_wrong_answer_or_exit_fails(rebuilt, monkeypatch, answer, code):
    output, runner = rebuilt
    fake_runner(monkeypatch, answer=answer, code=code)
    result = rebuild.execute_smoke(rebuild.prepare_smoke(output, runner))
    assert result["estado"] == "fallido" and result["verificacion"]["inferencia"] == "NO VERIFICADO"
    assert Path(result["ejecucion"]["log"]).is_file()


def test_smoke_model_mutated_by_runner_is_not_accepted(rebuilt, monkeypatch):
    output, runner = rebuilt
    fake_runner(monkeypatch, mutate=True)
    result = rebuild.execute_smoke(rebuild.prepare_smoke(output, runner))
    assert result["estado"] == "fallido" and "modelo cambió" in result["ejecucion"]["error"]


@pytest.mark.parametrize("answer", ["<|channel>thought\nincorrecto 17<channel|>43",
                                    "<think>incorrecto</think>43"])
def test_smoke_uses_final_answer(rebuilt, monkeypatch, answer):
    output, runner = rebuilt
    fake_runner(monkeypatch, answer=answer)
    result = rebuild.execute_smoke(rebuild.prepare_smoke(output, runner))
    assert result["estado"] == "smoke_superado" and result["respuesta"] == "43"


def test_smoke_never_matches_outside_the_answer(rebuilt, monkeypatch):
    output, runner = rebuilt
    # Sin el eco de la pregunta no hay respuesta identificable, aunque el valor esté en la salida.
    fake_runner(monkeypatch, answer="43\n", raw=True)
    assert rebuild.execute_smoke(rebuild.prepare_smoke(output, runner))["estado"] == "fallido"
    # El valor que solo aparece en la pregunta no cuenta como respuesta.
    fake_runner(monkeypatch, answer="no lo sé")
    result = rebuild.execute_smoke(rebuild.prepare_smoke(output, runner, prompt="Repite 43 al revés",
                                                         expected="43"))
    assert result["estado"] == "fallido" and result["respuesta"] == "no lo sé"


def test_smoke_interrupt_during_final_hash_is_recorded(rebuilt, monkeypatch):
    output, runner = rebuilt
    plan = rebuild.prepare_smoke(output, runner)
    fake_runner(monkeypatch)
    original = rebuild.sha256
    def interrupted(path):
        if Path(path) == output / "modelo.gguf":
            raise KeyboardInterrupt
        return original(path)
    monkeypatch.setattr(rebuild, "sha256", interrupted)
    with pytest.raises(KeyboardInterrupt):
        rebuild.execute_smoke(plan)
    saved = json.loads(Path(plan["resultado"]).read_text(encoding="utf-8"))
    assert saved["estado"] == "interrumpido"
    assert saved["verificacion"]["inferencia"] == "NO VERIFICADO"


def test_smoke_rejects_unfinished_tampered_or_changed(rebuilt, monkeypatch):
    output, runner = rebuilt
    monkeypatch.setattr(rebuild.subprocess, "Popen", lambda *a, **k: pytest.fail("No debe ejecutar"))
    with pytest.raises(ValueError, match="paquete"):
        rebuild.prepare_smoke(output, runner, bundle_sha="0" * 64)
    plan = rebuild.prepare_smoke(output, runner)
    plan["argv"].append("--rpc")
    with pytest.raises(ValueError, match="argumentos modificados"):
        rebuild.execute_smoke(plan)
    plan["argv"].pop()
    runner.write_bytes(b"changed runner")
    with pytest.raises(ValueError, match="biblioteca cambió"):
        rebuild.execute_smoke(plan)
    with (output / "modelo.gguf").open("ab") as stream:
        stream.write(b"x")
    with pytest.raises(ValueError, match="SHA-256 de salida"):
        rebuild.prepare_smoke(output, runner)
    saved = json.loads((output / "receta.json").read_text(encoding="utf-8"))
    saved["estado"] = "fallido"
    (output / "receta.json").write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(ValueError, match="terminada sin errores"):
        rebuild.prepare_smoke(output, runner)
    assert not list(output.glob("inferencia-*"))


def test_smoke_timeout_stops_own_process(rebuilt, monkeypatch):
    output, runner = rebuilt
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
    result = rebuild.execute_smoke(rebuild.prepare_smoke(output, runner, timeout=0.000001))
    assert stopped == [123456789] and result["estado"] == "fallido"
    assert "agotado" in result["ejecucion"]["error"]


def test_smoke_cli_requires_pin_and_reports_exit(rebuilt, monkeypatch, capsys):
    output, runner = rebuilt
    base = ["modelos", "probar", str(output), "--ejecutor", str(runner)]
    assert main([*base, "--ejecutar"]) == 2
    assert "sha256-paquete" in capsys.readouterr().out
    assert main(base) == 0
    pin = json.loads(capsys.readouterr().out)["herramienta"]["bundle_sha256"]
    fake_runner(monkeypatch)
    assert main([*base, "--ejecutar", "--sha256-paquete", pin]) == 0
    assert json.loads(capsys.readouterr().out)["verificacion"]["banco"] == "NO VERIFICADO"
    fake_runner(monkeypatch, answer="7\n")
    assert main([*base, "--ejecutar", "--sha256-paquete", pin]) == 2


# --- Plan de perfil Eolas (G6; no adopta ni arranca) ---

@pytest.fixture
def profiled(recipe_inputs, monkeypatch):
    source, output, tool = recipe_inputs
    metadata = [("general.architecture", 8, "gemma"), ("general.name", 8, "Gemma prueba"),
                ("gemma.block_count", 4, 48), ("gemma.context_length", 4, 262144),
                ("gemma.attention.sliding_window", 4, 1024),
                ("tokenizer.chat_template", 8, "{{ messages }}")]
    fixture(source, metadata=metadata)
    fake_process(monkeypatch, metadata=[*metadata, ("general.file_type", 4, 2)])
    assert rebuild.execute(rebuild.prepare(source, output, tool, "Q4_0"))["estado"] == "NO VERIFICADO"
    runner = tool.with_name("llama-cli.exe")
    runner.write_bytes(b"runner")
    fake_runner(monkeypatch)
    assert rebuild.execute_smoke(rebuild.prepare_smoke(output, runner))["estado"] == "smoke_superado"
    return output


def test_profile_plan_validates_recipe_smoke_metadata_and_does_not_adopt(profiled):
    before = sorted(p.name for p in profiled.iterdir())
    result = rebuild.plan_profile(profiled, "gemma4_recon_q4", ctx=32000, gpu_layers=8)
    assert result["schema"] == rebuild.PROFILE_SCHEMA and result["adoptado"] is False
    assert result["perfil"] == "gemma4_recon_q4"
    assert result["metadatos_planificador"]["gemma.context_length"] == 262144
    assert result["propuesta"]["ctx"] == 32000 and result["propuesta"]["gpu_layers"] == 8
    assert result["propuesta"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert result["verificacion"]["banco"] == "NO VERIFICADO"
    assert sorted(p.name for p in profiled.iterdir()) == before


@pytest.mark.parametrize("kwargs,match", [({"ctx": 262145}, "contexto solicitado"),
                                          ({"gpu_layers": 49}, "capas GPU"),
                                          ({"batch": 32, "ubatch": 64}, "ubatch")])
def test_profile_plan_rejects_limits_outside_metadata(profiled, kwargs, match):
    with pytest.raises(ValueError, match=match):
        rebuild.plan_profile(profiled, "gemma4_recon_q4", **kwargs)


def test_profile_plan_requires_same_successful_smoke(profiled):
    evidence = next(profiled.glob("inferencia-*.json"))
    data = json.loads(evidence.read_text(encoding="utf-8"))
    data["modelo_sha256"] = "0" * 64
    evidence.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="smoke superado"):
        rebuild.plan_profile(profiled, "gemma4_recon_q4")


def test_profile_plan_rejects_tampered_recorded_metadata(profiled):
    recipe_path = profiled / "receta.json"
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    recipe["auditoria_salida"]["planificador"]["gemma.context_length"] = 999999
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
    with pytest.raises(ValueError, match="planificador"):
        rebuild.plan_profile(profiled, "gemma4_recon_q4")


def test_profile_plan_cli(profiled, capsys):
    assert main(["eolas-v2", "plan", str(profiled), "--profile", "gemma4_recon_q4",
                 "--ctx", "4096", "--gpu-layers", "4"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["propuesta"]["ctx"] == 4096 and result["adoptado"] is False


def test_adoption_preview_and_apply_adds_inactive_pinned_profile(profiled, tmp_path, monkeypatch):
    config = tmp_path / "eolas-v2.json"
    server = tmp_path / "llama-server.exe"
    server.write_bytes(b"server")
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(config))
    monkeypatch.setattr(eolas_v2, "_server_default", lambda: str(server))
    eolas_v2.load_config()
    before = config.read_bytes()
    plan = rebuild.plan_profile(profiled, "gemma4_recon_q4")
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")

    preview = rebuild.adopt_profile(plan_file, plan["modelo_sha256"])
    assert preview["estado"] == "adopcion_preparada" and preview["aplicado"] is False
    assert config.read_bytes() == before

    applied = rebuild.adopt_profile(plan_file, plan["modelo_sha256"], apply=True)
    assert applied["estado"] == "perfil_instalado_inactivo" and applied["aplicado"] is True
    cfg = eolas_v2.load_config()
    assert cfg["active_profile"] == "gemma_q4"
    custom = cfg["profiles"]["gemma4_recon_q4"]
    assert custom["sha256"] == plan["modelo_sha256"] and custom["managed_by"] == rebuild.PROFILE_SCHEMA
    args = eolas_v2.server_args("gemma4_recon_q4", cfg)
    assert args[args.index("-m") + 1] == str(profiled / "modelo.gguf")
    assert args[args.index("--reasoning-format") + 1] == "deepseek"
    assert custom["reasoning"] is False
    with pytest.raises(FileExistsError):
        rebuild.adopt_profile(plan_file, plan["modelo_sha256"], apply=True)
    model = profiled / "modelo.gguf"
    removed = eolas_v2.remove_custom_profile("gemma4_recon_q4", plan["modelo_sha256"])
    assert removed["quitado"] is True and model.is_file()
    assert "gemma4_recon_q4" not in eolas_v2.load_config()["profiles"]


def test_adoption_rejects_wrong_pin_or_injectable_custom_profile(profiled, tmp_path, monkeypatch):
    config = tmp_path / "eolas-v2.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(config))
    monkeypatch.setattr(eolas_v2, "_server_default", lambda: str(tmp_path / "server.exe"))
    plan = rebuild.plan_profile(profiled, "gemma4_recon_q4")
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 revisado"):
        rebuild.adopt_profile(plan_file, "0" * 64)
    record = {"managed_by": rebuild.PROFILE_SCHEMA, **plan["propuesta"], "sha256": plan["modelo_sha256"],
              "source_recipe": plan["receta"], "source_smoke": plan["smoke"], "extra_args": ["--rpc"]}
    with pytest.raises(ValueError, match="Campos no admitidos"):
        eolas_v2._validate_custom_profile("gemma4_recon_q4", record)


def test_adoption_cli_preview_never_applies(profiled, tmp_path, monkeypatch, capsys):
    config = tmp_path / "eolas-v2.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(config))
    monkeypatch.setattr(eolas_v2, "_server_default", lambda: str(tmp_path / "server.exe"))
    plan = rebuild.plan_profile(profiled, "gemma4_recon_q4")
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    assert main(["eolas-v2", "adoptar", str(plan_file), "--sha256-modelo", plan["modelo_sha256"]]) == 0
    assert json.loads(capsys.readouterr().out)["aplicado"] is False
    assert not config.exists()
    assert "gemma4_recon_q4" not in eolas_v2.load_config()["profiles"]
