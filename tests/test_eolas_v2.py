import json
from pathlib import Path

import pytest


def _config(path, *, active="gemma", feedback_enabled=False):
    from eolfi.eolas_v2 import DEFAULT_CONFIG

    profiles = {
        "gemma": {**DEFAULT_CONFIG["profiles"]["gemma"], "model": str(path / "gemma.gguf")},
        "mistral": {**DEFAULT_CONFIG["profiles"]["mistral"], "model": str(path / "mistral.gguf")},
    }
    for name in profiles:
        profiles[name]["model"] = str(path / ("gemma.gguf" if name == "gemma" else "mistral.gguf"))
        Path(profiles[name]["model"]).touch()
    server = path / "llama-server.exe"
    server.touch()
    return {**DEFAULT_CONFIG, "server": str(server), "active_profile": active,
            "profiles": profiles, "feedback_enabled": feedback_enabled}


def test_configuracion_y_argumentos_por_perfil(tmp_path, monkeypatch):
    from eolfi import eolas_v2

    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(tmp_path / "eolas.json"))
    server = tmp_path / "llama-server.exe"
    server.touch()
    monkeypatch.setattr(eolas_v2, "_server_default", lambda: str(server))
    cfg = eolas_v2.load_config()
    (tmp_path / "gemma.gguf").touch()
    (tmp_path / "mistral.gguf").touch()
    cfg["profiles"]["mistral"]["model"] = str(tmp_path / "mistral.gguf")
    args = eolas_v2.server_args("mistral", cfg)
    assert args[0] == str(server)
    assert args[args.index("-m") + 1].endswith("mistral.gguf")
    assert args[args.index("-ngl") + 1] == "8"
    assert args[args.index("-c") + 1] == "32000"
    assert args[args.index("-b") + 1] == "128" and args[args.index("-ub") + 1] == "64"
    assert args[args.index("--host") + 1] == "127.0.0.1"


def test_pid_alive_reconoce_proceso_actual_y_pid_inexistente():
    import os
    from eolfi.eolas_v2 import _pid_alive

    assert _pid_alive(os.getpid()) is True
    assert _pid_alive(0x7FFFFFFF) is False


def test_feedback_exige_doble_optin_redacta_secreto_y_calibra(tmp_path, monkeypatch):
    from eolfi import eolas_v2

    config_path = tmp_path / "eolas.json"
    records_path = tmp_path / "feedback.jsonl"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(config_path))
    monkeypatch.setenv("EOLFI_EOLAS_V2_FEEDBACK", str(records_path))
    cfg = _config(tmp_path, feedback_enabled=False)
    config_path.write_text(json.dumps(cfg), encoding="utf-8")
    with pytest.raises(PermissionError):
        eolas_v2.record_feedback(profile="mistral", task="codigo", prompt="p", response="r", rating=5,
                                     consent=True)

    eolas_v2.set_feedback_consent(True)
    row = eolas_v2.record_feedback(profile="mistral", task="codigo", prompt="api_key=abc123", response="token: secret",
                                   parameters={"api_key": "abc123", "temperature": 0.2}, rating=5, consent=True)
    assert row["prompt"] == "api_key=[REDACTED]"
    assert row["response"] == "token: [REDACTED]"
    assert row["parameters"] == {"api_key": "[REDACTED]", "temperature": 0.2}
    assert eolas_v2.read_feedback()[0]["consent"] is True
    rows = eolas_v2.read_feedback()
    rows += [{**row, "id": f"m{i}", "profile": "mistral", "rating": 5} for i in range(2)]
    rows += [{**row, "id": f"g{i}", "profile": "gemma", "rating": 2} for i in range(3)]
    recommendation = eolas_v2.recommend_profile("codigo", feedback=rows)
    assert recommendation["profile"] == "mistral" and recommendation["calibrated"]
    assert recommendation["weights_updated"] is False


def test_preferencias_separan_splits_por_caso_y_exigen_minimo(tmp_path):
    from eolfi import eolas_v2

    rows = []
    for i in range(60):
        common = {"schema": eolas_v2.SCHEMA, "consent": True, "task": "codigo", "prompt": f"Pregunta {i}"}
        rows.append({**common, "id": f"good-{i}", "profile": "mistral", "rating": 5, "response": f"respuesta correcta {i}"})
        rows.append({**common, "id": f"bad-{i}", "profile": "gemma", "rating": 1, "response": f"respuesta incorrecta {i}"})
    out = tmp_path / "preferences.jsonl"
    manifest = eolas_v2.build_dataset(kind="preference", out=out, min_examples=20, feedback=rows)
    assert manifest["examples"] == 60
    assert all(manifest["split_counts"][part] > 0 for part in ("train", "validation", "test"))
    data = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert all(set(row) >= {"prompt", "chosen", "rejected", "split"} for row in data)
    assert len({(row["prompt"], row["split"]) for row in data}) == 60
    assert json.loads(out.with_suffix(".jsonl.manifest.json").read_text(encoding="utf-8"))["dataset_sha256"] == manifest["dataset_sha256"]
    with pytest.raises(ValueError, match="Dataset insuficiente"):
        eolas_v2.build_dataset(kind="preference", out=tmp_path / "small.jsonl", min_examples=61, feedback=rows)


def test_switch_detiene_antes_de_cambiar_y_no_inicia_dos_perfiles(tmp_path, monkeypatch):
    from eolfi import eolas_v2

    cfg_path = tmp_path / "eolas.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(cfg_path))
    monkeypatch.setattr(eolas_v2, "lock_file", lambda: tmp_path / "eolas-v2.lock")
    cfg = _config(tmp_path)
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    events = []
    monkeypatch.setattr(eolas_v2, "_stop_locked", lambda: events.append("stop") or True)

    def launch(profile, cfg=None, **kwargs):
        events.append(f"start:{profile}")
        return {"running": True, "profile": profile}

    monkeypatch.setattr(eolas_v2, "_start_locked", launch)
    result = eolas_v2.switch("mistral")
    assert events == ["stop", "start:mistral"]
    assert result["stopped_previous"] is True
    assert json.loads(cfg_path.read_text(encoding="utf-8"))["active_profile"] == "mistral"


def test_switch_con_runtime_inexistente_conserva_el_servidor(tmp_path, monkeypatch):
    from eolfi import eolas_v2

    cfg_path = tmp_path / "eolas.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(cfg_path))
    cfg = _config(tmp_path)
    Path(cfg["server"]).unlink()
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8-sig")
    monkeypatch.setattr(eolas_v2, "_stop_locked", lambda: pytest.fail("no debe detener Gemma"))

    with pytest.raises(FileNotFoundError, match="llama-server"):
        eolas_v2.switch("mistral")

    assert eolas_v2.load_config()["active_profile"] == "gemma"


def test_motor_v2_se_abstiene_si_celtia_v1_anuncia_modelo(tmp_path, monkeypatch):
    from eolfi import eolas_v2

    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(tmp_path / "eolas-v2.json"))
    (tmp_path / "gemma.gguf").touch()
    cfg = {**eolas_v2.DEFAULT_CONFIG, "server": "X:/llama-server.exe", "profiles": {
        **eolas_v2.DEFAULT_PROFILES, "gemma": {**eolas_v2.DEFAULT_PROFILES["gemma"], "model": str(tmp_path / "gemma.gguf")}}}
    monkeypatch.setattr(eolas_v2, "_legacy_eolas_models", lambda: ["gemma-4-12b-it:latest"])
    monkeypatch.setattr(eolas_v2, "_healthy", lambda *args, **kwargs: False)
    with pytest.raises(RuntimeError, match="Eolas V1/CeltIA sigue anunciando"):
        eolas_v2._start_locked("gemma", cfg, popen=lambda *a, **kw: pytest.fail("no debe lanzar llama-server"))


def test_training_check_gufu_no_se_considera_checkpoint(tmp_path):
    from eolfi.eolas_v2 import training_readiness

    gguf = tmp_path / "mistral.gguf"
    gguf.touch()
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("{}\n", encoding="utf-8")
    report = training_readiness(gguf, dataset)
    assert report["ready"] is False
    assert report["status"] == "NO VERIFICADO"
    assert any("checkpoint HF" in blocker for blocker in report["blockers"])


def test_train_sft_exige_consentimiento_y_no_sobrescribe(tmp_path):
    from eolfi.eolas_v2 import train_sft

    with pytest.raises(PermissionError, match="--consent"):
        train_sft(tmp_path / "checkpoint", tmp_path / "data.jsonl", tmp_path / "adapter")
    output = tmp_path / "already-there"
    output.mkdir()
    with pytest.raises(FileExistsError, match="no se sobrescribirá"):
        train_sft(tmp_path / "checkpoint", tmp_path / "data.jsonl", output, consent=True)


def test_training_readiness_rechaza_dataset_preference_para_sft(tmp_path):
    from eolfi.eolas_v2 import training_readiness, DATASET_SCHEMA
    import hashlib

    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "config.json").write_text("{}", encoding="utf-8")
    (checkpoint / "model.safetensors").touch()
    dataset = tmp_path / "preferences.jsonl"
    rows = [{"prompt": "p", "chosen": "a", "rejected": "b", "split": "train"} for _ in range(18)]
    rows += [{"prompt": "p", "chosen": "a", "rejected": "b", "split": "validation"},
             {"prompt": "p", "chosen": "a", "rejected": "b", "split": "test"}]
    payload = "".join(json.dumps(row) + "\n" for row in rows)
    dataset.write_bytes(payload.encode("utf-8"))
    dataset.with_suffix(".jsonl.manifest.json").write_text(json.dumps({
        "schema": DATASET_SCHEMA, "kind": "preference", "examples": 20,
        "dataset_sha256": hashlib.sha256(payload.encode()).hexdigest()}), encoding="utf-8")
    report = training_readiness(checkpoint, dataset)
    assert report["ready"] is False
    assert any("DPO aún" in blocker for blocker in report["blockers"])


def test_feedback_exporta_importa_sin_duplicar(tmp_path, monkeypatch):
    from eolfi import eolas_v2

    source_config = tmp_path / "source.json"
    source_feedback = tmp_path / "source.jsonl"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(source_config))
    monkeypatch.setenv("EOLFI_EOLAS_V2_FEEDBACK", str(source_feedback))
    source_config.write_text(json.dumps(_config(tmp_path, feedback_enabled=True)), encoding="utf-8")
    eolas_v2.record_feedback(profile="mistral", task="t", prompt="p", response="r", rating=5, consent=True)
    bundle = tmp_path / "export.jsonl"
    assert eolas_v2.export_feedback(bundle)["records"] == 1

    target_config = tmp_path / "target.json"
    target_feedback = tmp_path / "target.jsonl"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(target_config))
    monkeypatch.setenv("EOLFI_EOLAS_V2_FEEDBACK", str(target_feedback))
    target_config.write_text(json.dumps(_config(tmp_path, feedback_enabled=False)), encoding="utf-8")
    with pytest.raises(PermissionError):
        eolas_v2.import_feedback(bundle)
    target_config.write_text(json.dumps(_config(tmp_path, feedback_enabled=True)), encoding="utf-8")
    assert eolas_v2.import_feedback(bundle)["imported"] == 1
    assert eolas_v2.import_feedback(bundle)["imported"] == 0


def test_cli_eolas_y_provider_nuevo_sin_romper_alias_legacy():
    from eolfi.cli import _parser
    from eolfi.generador.llm import make_provider

    assert _parser().parse_args(["eolas-v2", "switch", "mistral"]).eolas_action == "switch"
    assert _parser().parse_args(["eolas-v2", "train-sft", "--checkpoint", "c", "--dataset", "d", "--out", "o"]).eolas_action == "train-sft"
    provider = make_provider("eolas-v2", model="mistral")
    assert provider.profile == "mistral"
    composed = make_provider("celtia-v2")
    assert composed.name == "celtia-v2"
    legacy = make_provider("eolas")
    assert legacy.name == "eolas"


def test_celtia_v2_compone_mistral_y_gemma_secuencial(monkeypatch):
    from eolfi.generador import llm

    calls = []
    constructors = []

    class FakeEngine:
        def __init__(self, profile, **kwargs):
            self.profile = profile
            self.kwargs = kwargs
            constructors.append({"profile": profile, "kwargs": kwargs})
            self.last_reasoning = profile + " reasoning"

        def complete(self, system, messages, schema, effort):
            calls.append({"profile": self.profile, "system": system, "messages": messages})
            if self.profile == "mistral":
                return llm.Reply({"summary": "borrador", "notes": [], "files": []}, "draft",
                                 {"input_tokens": 10, "output_tokens": 5}, "mistral")
            return llm.Reply({"summary": "final revisado", "notes": [], "files": []}, "final",
                             {"input_tokens": 8, "output_tokens": 4}, "gemma")

    monkeypatch.setattr(llm, "EolasEngineProvider", FakeEngine)
    provider = llm.CeltiaV2ComposerProvider()
    result = provider.complete("system", [{"role": "user", "content": "hazlo"}], {}, "high")
    assert [call["profile"] for call in calls] == ["mistral", "gemma"]
    assert constructors[1]["kwargs"]["reasoning_override"] is False
    assert "REVISOR SENIOR" in calls[1]["system"]
    assert '"summary": "borrador"' in calls[1]["messages"][-1]["content"]
    assert result.data["summary"] == "final revisado"
    assert result.usage == {"input_tokens": 18, "output_tokens": 9}
    assert "Mistral borrador → Gemma revisión final" in result.model


def test_sonda_celtia_v2_exige_ambos_gguf_sin_arrancarlos(tmp_path, monkeypatch):
    from eolfi import eolas_v2
    from eolfi.generador.llm import probe

    cfg = _config(tmp_path)
    monkeypatch.setattr(eolas_v2, "load_config", lambda **kwargs: cfg)
    available = probe("celtia-v2")
    assert available["available"] is True
    assert "runtime NO VERIFICADO" in available["detail"]
    (tmp_path / "mistral.gguf").unlink()
    missing = probe("celtia-v2")
    assert missing["available"] is False and "mistral" in missing["detail"]


def test_cli_eolas_v2_entra_al_despachador(tmp_path, capsys):
    from eolfi.cli import main

    gguf = tmp_path / "model.gguf"
    gguf.touch()
    rc = main(["eolas-v2", "training-check", "--checkpoint", str(gguf),
               "--dataset", str(tmp_path / "missing.jsonl")])
    captured = capsys.readouterr()
    assert rc == 0
    assert '"status": "NO VERIFICADO"' in captured.out


@pytest.mark.parametrize(("effort", "expected"), [("low", "mistral"), ("high", "gemma")])
def test_enrutamiento_eolas_auto(tmp_path, monkeypatch, effort, expected):
    from contextlib import contextmanager
    from eolfi import eolas_v2
    from eolfi.generador import llm

    cfg = _config(tmp_path)
    monkeypatch.setattr(eolas_v2, "load_config", lambda: cfg)

    @contextmanager
    def inference(profile):
        assert profile == expected
        yield eolas_v2.profile_config(profile, cfg)

    monkeypatch.setattr(eolas_v2, "inference_profile", inference)
    monkeypatch.setattr(llm, "_post", lambda *args: {"choices": [{"message": {"content": "{}"}}]})
    reply = llm.EolasEngineProvider("auto").complete("system", [], {}, effort)
    assert reply.model.startswith(cfg["profiles"][expected]["alias"])


def test_perfil_moe_selecciona_gguf_y_argumentos(tmp_path, monkeypatch):
    from eolfi import eolas_v2

    model = tmp_path / "gemma-4-26b-a4b.gguf"
    model.touch()
    config = tmp_path / "eolas.json"
    cfg = _config(tmp_path)
    cfg["profiles"]["moe"] = {"extra_args": ["--cpu-moe"]}
    config.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(config))
    monkeypatch.setenv("EOLFI_EOLAS_V2_MOE_GGUF", str(model))

    args = eolas_v2.server_args("moe")
    assert args[args.index("-m") + 1] == str(model)
    assert "--cpu-moe" in args


def test_inferencia_impide_cambiar_perfil_hasta_terminar(tmp_path, monkeypatch):
    from eolfi import eolas_v2

    config = tmp_path / "eolas.json"
    config.write_text(json.dumps(_config(tmp_path)), encoding="utf-8")
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(config))
    monkeypatch.setattr(eolas_v2, "_start_locked", lambda name, cfg: None)

    with eolas_v2.inference_profile("gemma") as profile:
        assert profile["alias"] == eolas_v2.DEFAULT_PROFILES["gemma"]["alias"]
        with pytest.raises(RuntimeError, match="cambiando de perfil"):
            eolas_v2.switch("mistral")

    assert not eolas_v2.lock_file().exists()


def test_mistral_adapta_system_y_turnos_consecutivos():
    from eolfi.generador.llm import _mistral_chat_messages

    messages = [
        {"role": "user", "content": "primero"},
        {"role": "assistant", "content": "respuesta"},
        {"role": "user", "content": "segundo"},
        {"role": "user", "content": "detalle"},
    ]
    assert _mistral_chat_messages("reglas", messages) == [
        {"role": "user", "content": "reglas\n\nprimero"},
        {"role": "assistant", "content": "respuesta"},
        {"role": "user", "content": "segundo\n\ndetalle"},
    ]
    assert messages[0]["content"] == "primero"
