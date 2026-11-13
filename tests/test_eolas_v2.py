import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _sin_eolas_real(monkeypatch, tmp_path):
    """Las pruebas nunca consultan ni descargan el Eolas real de 127.0.0.1:11435 (cada prueba puede simularlo)
    ni escriben aportes en la carpeta real de Alejandría."""
    from eolfi import eolas_v2

    monkeypatch.setattr(eolas_v2, "_legacy_eolas_models", lambda: [])
    monkeypatch.setenv("EOLFI_APORTES", str(tmp_path / "aportes"))
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(tmp_path / "eolas-v2-defecto.json"))   # nunca la real (ni su clave)
    monkeypatch.delenv("EOLAS_V2_API_KEY", raising=False)


def _config(path, *, active="gemma", feedback_enabled=False):
    from eolfi.eolas_v2 import DEFAULT_CONFIG

    profiles = {
        "gemma": {**DEFAULT_CONFIG["profiles"]["gemma"], "model": str(path / "gemma.gguf")},
        "gemma_q4": {**DEFAULT_CONFIG["profiles"]["gemma_q4"], "model": str(path / "gemma-q4.gguf")},
        "mistral": {**DEFAULT_CONFIG["profiles"]["mistral"], "model": str(path / "mistral.gguf")},
    }
    for name in profiles:
        profiles[name]["model"] = str(path / ("mistral.gguf" if name == "mistral" else "gemma-q4.gguf" if name == "gemma_q4" else "gemma.gguf"))
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
    assert "--reasoning-format" not in args


def test_nemo_uses_mistral_template_and_not_deepseek_reasoning(tmp_path, monkeypatch):
    from eolfi import eolas_v2

    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(tmp_path / "eolas.json"))
    server = tmp_path / "llama-server.exe"
    server.touch()
    monkeypatch.setattr(eolas_v2, "_server_default", lambda: str(server))
    cfg = eolas_v2.load_config()
    nemo = tmp_path / "nemo.gguf"
    nemo.touch()
    cfg["profiles"]["nemo_q4"]["model"] = str(nemo)

    assert "--reasoning-format" not in eolas_v2.server_args("nemo_q4", cfg)
    assert eolas_v2.is_mistral_profile("nemo_q4") is True
    assert eolas_v2.is_mistral_profile("gemma_q4") is False


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
    assert _parser().parse_args(["eolas-v2", "switch", "gemma_q4"]).profile == "gemma_q4"
    assert _parser().parse_args(["eolas-v2", "train-sft", "--checkpoint", "c", "--dataset", "d", "--out", "o"]).eolas_action == "train-sft"
    provider = make_provider("eolas-v2", model="mistral")
    assert provider.profile == "mistral"
    composed = make_provider("celtia-v2")
    assert composed.name == "celtia-v2"
    nemo_moe = make_provider("nemo-moe")
    assert nemo_moe.name == "nemo-moe"
    assert _parser().parse_args(["create", "--from", "x", "--out", "y", "--provider", "nemo-moe"]).provider == "nemo-moe"
    legacy = make_provider("eolas")
    assert legacy.name == "eolas"


def test_celtia_v2_compone_redactor_y_revisor_secuencial(monkeypatch):
    """13/11/2026: el ganador de la ronda (gemma) redacta y gemma_q4 revisa; antes, Mistral → gemma_q4."""
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
            if self.profile == "gemma":
                return llm.Reply({"summary": "borrador", "notes": [], "files": []}, "draft",
                                 {"input_tokens": 10, "output_tokens": 5}, "gemma")
            return llm.Reply({"summary": "final revisado", "notes": [], "files": []}, "final",
                             {"input_tokens": 8, "output_tokens": 4}, "gemma")

    monkeypatch.setattr(llm, "EolasEngineProvider", FakeEngine)
    provider = llm.CeltiaV2ComposerProvider()
    result = provider.complete("system", [{"role": "user", "content": "hazlo"}], {}, "high")
    assert [call["profile"] for call in calls] == ["gemma", "gemma_q4"]
    assert constructors[1]["profile"] == "gemma_q4"
    assert constructors[1]["kwargs"]["reasoning_override"] is False
    assert "REVISOR SENIOR" in calls[1]["system"]
    assert '"summary": "borrador"' in calls[1]["messages"][-1]["content"]
    assert result.data["summary"] == "final revisado"
    assert result.usage == {"input_tokens": 18, "output_tokens": 9}
    assert "gemma borrador" in result.model and "gemma_q4 revisión" in result.model
    # Configurable en eolas-v2.json.
    assert llm.celtia_v2_roles({"celtia_v2_redactor": "msmall_q5"}) == ("msmall_q5", "gemma_q4")
    assert "gemma borrador → gemma_q4 revisión final" in result.model


def test_nemo_moe_usa_tres_pases_del_mismo_perfil_en_secuencia(monkeypatch):
    from eolfi.generador import llm
    from contextlib import nullcontext
    from eolfi import eolas_v2

    calls = []
    schemas, options = [], []

    class FakeEngine:
        def __init__(self, profile, **kwargs):
            assert profile == "nemo_q4"
            options.append(kwargs)
            self.last_reasoning = ""

        def complete(self, system, messages, schema, effort):
            schemas.append(schema)
            calls.append((system, messages))
            number = len(calls)
            return llm.Reply({"resultado": number}, str(number),
                             {"input_tokens": number, "output_tokens": number}, "nemo")

    monkeypatch.setattr(llm, "EolasEngineProvider", FakeEngine)
    monkeypatch.setattr(eolas_v2, "inference_profile", lambda _: nullcontext({}))
    provider = llm.NemoMoEReasoningProvider()
    result = provider.complete("reglas", [{"role": "user", "content": "Calcula 17*3-8"}],
                               {"type": "object"}, "high")

    assert len(calls) == 3
    assert "review" in schemas[0]["properties"]
    assert schemas[0] == schemas[1]
    assert schemas[2] == {"type": "object"}
    assert "max_tokens_override" not in options[2]
    assert "EXPERTO DE CÁLCULO" in calls[0][1][-1]["content"]
    assert "17*3-8 = 43" in calls[0][0]
    assert "VERIFICADOR INDEPENDIENTE" in calls[1][1][-1]["content"]
    assert calls[0][0] == calls[1][0]
    assert "COMPOSITOR FINAL" in calls[2][0]
    assert result.data == {"resultado": 3}
    assert result.usage == {"input_tokens": 6, "output_tokens": 6}


def test_banco_moe_exige_candidatos_compactos(monkeypatch):
    from eolfi import eolas_v2
    seen = []
    monkeypatch.setattr(eolas_v2, "_evaluation_request", lambda _c, messages, max_tokens=0, **_kwargs: seen.append((messages, max_tokens)) or {"content": "{}", "usage": {}, "finish": "stop"})
    eolas_v2._nemo_moe_evaluation({"alias": "nemo"}, "Devuelve SOLO JSON", lambda _: None)
    assert seen[0][1] == 384 and "sin explicar" in seen[0][0][0]["content"]
    assert seen[1][1] == 384 and "sin explicación" in seen[1][0][0]["content"]
    assert seen[2][1] == 512


def test_banco_moe_reintenta_un_experto_truncado(monkeypatch):
    from eolfi import eolas_v2
    calls, notices = [], []
    replies = iter((
        {"content": "demasiado", "usage": {}, "finish": "length"},
        {"content": "{}", "usage": {}, "finish": "stop"},
        {"content": "{}", "usage": {}, "finish": "stop"},
        {"content": "{}", "usage": {}, "finish": "stop"},
    ))
    monkeypatch.setattr(eolas_v2, "_evaluation_request", lambda *args, **kwargs: calls.append(kwargs) or next(replies))
    eolas_v2._nemo_moe_evaluation({"alias": "nemo"}, "Devuelve SOLO JSON", notices.append)
    assert calls[0]["allow_truncation"] is True and calls[1]["max_tokens"] == 160
    assert any("reintento compacto" in note for note in notices)


def test_calculadora_moe_maneja_signos_parentesis_y_limites():
    from eolfi.arithmetic import arithmetic_evidence
    from eolfi.generador.llm import _verified_arithmetic_evidence

    assert arithmetic_evidence("Calcula -5+2") == "EVIDENCIA DE CALCULADORA LOCAL: -5+2 = -3."
    assert arithmetic_evidence("Calcula (2+3)*4") == "EVIDENCIA DE CALCULADORA LOCAL: (2+3)*4 = 20."
    assert _verified_arithmetic_evidence([{"content": "Calcula 17*3-8"}]) == "EVIDENCIA DE CALCULADORA LOCAL: 17*3-8 = 43."
    assert arithmetic_evidence("1+" + "1+" * 80 + "1") is None


def test_evidencia_inventario_extrae_lotes_reserva_paquetes_y_comision():
    from eolfi.arithmetic import inventory_evidence
    text = ("Lote A: 84 unidades, 7 defectuosas. Lote B: 65 unidades, 5 defectuosas. "
            "Lote C: 91 unidades, 9 defectuosas. Se reserva primero un stock fijo de 17 unidades "
            "y el resto se vende exclusivamente en paquetes de 6. Cada paquete se vende a 19.50 euros. "
            "Comisión de plataforma del 12% sobre el ingreso bruto.")
    assert inventory_evidence(text) == ('EVIDENCIA DE INVENTARIO LOCAL: '
                                        '{"utilizables":219,"paquetes":33,"sobrantes":4,"bruto":643.5,"comision":77.22,"neto":566.28}.')


def test_banco_conserva_el_error_de_un_modelo_y_continua(tmp_path, monkeypatch):
    from eolfi import eolas_v2

    cfg = _config(tmp_path)
    for name in ("gemma_q4", "nemo_q4"):
        model = tmp_path / f"{name}.gguf"
        model.touch()
        cfg["profiles"][name] = {**eolas_v2.DEFAULT_PROFILES[name], "model": str(model)}
    monkeypatch.setattr(eolas_v2, "load_config", lambda **kwargs: cfg)
    monkeypatch.setattr(eolas_v2, "_runtime", lambda: None)
    monkeypatch.setattr(eolas_v2, "_start_locked", lambda *args, **kwargs: {})
    monkeypatch.setattr(eolas_v2, "_stop_locked", lambda *args, **kwargs: False)
    monkeypatch.setattr(eolas_v2, "_exclusive_lock", lambda: __import__("contextlib").nullcontext())
    monkeypatch.setattr(eolas_v2, "_evaluation_request", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("fallo simulado")))
    report = eolas_v2.run_fair_evaluation(prompt="caso", profiles=["gemma_q4"])
    assert report["results"][0]["passed"] is False
    assert "fallo simulado" in report["results"][0]["error"]


def test_validador_acepta_json_envuelto_pero_no_cambia_su_contenido():
    from eolfi.eolas_v2 import _answer_match, _expected_match, _structured_match

    assert _structured_match('La respuesta final es:\n```json\n{"resultado": 43}\n```', {"resultado": 43})
    assert not _structured_match('```json\n{"resultado": 41}\n```', {"resultado": 43})
    assert not _structured_match('{"resultado": true}', {"resultado": 1})
    assert _answer_match('{"answer": 43}', '43')
    assert _expected_match('{"resultado": 43}', '{"resultado": 43}')


def test_sonda_nemo_moe_exige_el_gguf_de_nemo(tmp_path, monkeypatch):
    from eolfi import eolas_v2
    from eolfi.generador.llm import probe

    cfg = _config(tmp_path)
    nemo = tmp_path / "nemo.gguf"
    nemo.touch()
    cfg["profiles"]["nemo_q4"] = {**eolas_v2.DEFAULT_PROFILES["nemo_q4"], "model": str(nemo)}
    monkeypatch.setattr(eolas_v2, "load_config", lambda **kwargs: cfg)
    assert probe("nemo-moe")["available"] is True
    nemo.unlink()
    assert probe("nemo-moe")["available"] is False


def test_sonda_celtia_v2_exige_ambos_gguf_sin_arrancarlos(tmp_path, monkeypatch):
    from eolfi import eolas_v2
    from eolfi.generador.llm import probe

    cfg = _config(tmp_path)
    monkeypatch.setattr(eolas_v2, "load_config", lambda **kwargs: cfg)
    available = probe("celtia-v2")
    assert available["available"] is True
    assert "runtime NO VERIFICADO" in available["detail"]
    assert "gemma redacta" in available["detail"]
    cfg["retired_profiles"] = ["gemma_q4"]                       # un revisor retirado tampoco vale
    retired = probe("celtia-v2")
    assert retired["available"] is False and "gemma_q4" in retired["detail"]
    cfg["retired_profiles"] = []
    (tmp_path / "gemma.gguf").unlink()
    missing = probe("celtia-v2")
    assert missing["available"] is False and "gemma" in missing["detail"]


def test_cli_eolas_v2_entra_al_despachador(tmp_path, capsys):
    from eolfi.cli import main

    gguf = tmp_path / "model.gguf"
    gguf.touch()
    rc = main(["eolas-v2", "training-check", "--checkpoint", str(gguf),
               "--dataset", str(tmp_path / "missing.jsonl")])
    captured = capsys.readouterr()
    assert rc == 0
    assert '"status": "NO VERIFICADO"' in captured.out


@pytest.mark.parametrize(("effort", "expected"), [("low", "mistral"), ("high", "gemma_q4")])
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


def test_banco_libera_eolas_y_no_deja_un_perfil_cargado_al_terminar(tmp_path, monkeypatch):
    """Mejoras 2026-11-12: la prueba en vivo pide a Eolas que suelte su modelo antes de empezar y, si no había ningún
    perfil en marcha, no arranca active_profile al terminar (dejaba un modelo olvidado en la GPU)."""
    from eolfi import eolas_v2

    cfg_path = tmp_path / "eolas.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(cfg_path))
    cfg = _config(tmp_path, active="nemo_q4")
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    loaded = ["gemma-4-12b-it:latest"]
    posts = []
    monkeypatch.setattr(eolas_v2, "_legacy_eolas_models", lambda: list(loaded))

    class _Resp:
        def __enter__(self):
            posts.append(1)
            loaded.clear()
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(eolas_v2.urllib.request, "urlopen", lambda *a, **k: _Resp())
    started = []
    monkeypatch.setattr(eolas_v2, "_start_locked", lambda name, cfg=None, **k: started.append(name) or {"started": True})
    monkeypatch.setattr(eolas_v2, "_stop_locked", lambda *a, **k: False)
    monkeypatch.setattr(eolas_v2, "_evaluation_request", lambda c, msgs, *a, **k: {"content": "43", "usage": {}})
    log = []
    report = eolas_v2.run_fair_evaluation(prompt="Calcula 17*3-8", expected="43", profiles=["gemma_q4"], progress=log.append)
    assert posts == [1] and any("descargue" in m for m in log)
    assert started == ["gemma_q4"]                     # solo el motor del banco; nada al terminar
    assert report["restored_profile"] is None
    assert any("no se carga ninguno al terminar" in m for m in log)


def test_bateria_carga_cada_motor_una_vez_en_el_orden_pedido(tmp_path, monkeypatch):
    """Mejora 2026-11-12: antes la batería recargaba cada motor en cada caso (~50 s por carga)."""
    from eolfi import eolas_v2

    cfg_path = tmp_path / "eolas.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(cfg_path))
    cfg = _config(tmp_path, active="gemma_q4")
    qwen = tmp_path / "qwen.gguf"
    qwen.touch()
    cfg["profiles"]["qwen14_q4"] = {**eolas_v2.DEFAULT_PROFILES["qwen14_q4"], "model": str(qwen)}
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    started = []
    monkeypatch.setattr(eolas_v2, "_start_locked", lambda name, cfg=None, **k: started.append(name) or {"started": True})
    monkeypatch.setattr(eolas_v2, "_stop_locked", lambda *a, **k: False)
    answers = {case["prompt"]: json.dumps(case["expected"], ensure_ascii=False) for case in eolas_v2.FULL_EVALUATION_CASES}

    def fake_request(c, msgs, *a, **k):
        prompt = msgs[-1]["content"]
        if prompt in answers:                                   # fase de análisis
            return {"content": "análisis", "usage": {}}
        question = prompt.split("Pregunta:\n", 1)[1].split("\n\nAnálisis previo", 1)[0]
        right = answers[question]
        # Qwen acierta todo; Gemma falla los porcentajes (84 en vez de 80) y responde 150.0 en las unidades.
        if c["alias"].startswith("gemma") and "precio_final" in right:
            right = '{"precio_final": 84}'
        if c["alias"].startswith("gemma") and "minutos" in right:
            right = '{"minutos": 150.0, "metros": 3000}'
        return {"content": right, "usage": {}}

    monkeypatch.setattr(eolas_v2, "_evaluation_request", fake_request)
    report = eolas_v2.run_full_evaluation(profiles=["qwen14_q4", "gemma_q4"])
    n = len(eolas_v2.FULL_EVALUATION_CASES)
    assert started == ["qwen14_q4", "gemma_q4"]                  # una carga por motor, Qwen primero
    assert report["order"] == ["qwen14_q4", "gemma_q4"] and len(report["results"]) == 2 * n
    assert report["summary"]["qwen14_q4"]["correctos"] == n
    assert report["summary"]["gemma_q4"]["correctos"] == n - 1  # 84 falla; 150.0 cuenta como 150
    assert report["restored_profile"] is None


def test_bateria_codigo_corrige_con_el_error_real_y_cuenta_el_primer_intento(tmp_path, monkeypatch):
    """La batería de código ejecuta en un contenedor (aquí simulado) y, si falla, da al modelo el error real una vez."""
    from eolfi import eolas_v2

    cfg_path = tmp_path / "eolas.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(cfg_path))
    cfg = _config(tmp_path, active="gemma_q4")
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(eolas_v2, "_start_locked", lambda *a, **k: {"started": True})
    monkeypatch.setattr(eolas_v2, "_stop_locked", lambda *a, **k: False)
    monkeypatch.setattr(eolas_v2, "sandbox_ready", lambda: (True, ""))
    seen = []

    def fake_request(c, msgs, *a, **k):
        seen.append(msgs[0]["content"])
        if msgs[0]["content"].startswith("Corrige"):
            assert "NameError" in msgs[-1]["content"]          # recibe el error real, no las pruebas
            return {"content": "```python\ndef bien(): pass\n```", "usage": {}}
        return {"content": "```python\ndef mal(): pass\n```", "usage": {}}

    monkeypatch.setattr(eolas_v2, "_evaluation_request", fake_request)
    monkeypatch.setattr(eolas_v2, "_run_code_case", lambda code, tests, **k: (
        {"passed": True, "executed": True, "output": "EOLFI-OK"} if "bien" in code else
        {"passed": False, "executed": True, "output": "NameError: name 'parsear_log' is not defined"}))
    report = eolas_v2.run_full_evaluation(profiles=["gemma_q4"], battery="codigo")
    n = len(eolas_v2.CODE_EVALUATION_CASES)
    assert report["battery"] == "codigo" and len(report["results"]) == n
    assert all(r["first_try"] is False and r["repaired"] and r["passed"] for r in report["results"])
    assert report["summary"]["gemma_q4"]["correctos"] == n
    assert report["summary"]["gemma_q4"]["correctos_primer_intento"] == 0
    assert sum(s.startswith("Corrige") for s in seen) == n


def test_codigo_generado_nunca_se_ejecuta_sin_contenedor(monkeypatch):
    from eolfi import eolas_v2

    monkeypatch.setattr(eolas_v2.shutil, "which", lambda name: None)
    r = eolas_v2._run_code_case("print('hola')", "", run=lambda *a, **k: pytest.fail("no debe ejecutar nada"))
    assert r["executed"] is False and r["passed"] is False and "Docker" in r["output"]



def test_si_cae_el_contenedor_no_se_culpa_al_modelo(tmp_path, monkeypatch):
    """12/11/2026: con Docker Desktop parado, el banco puntuaba como fallo del modelo lo que nunca se ejecutó."""
    from eolfi import eolas_v2

    class P:
        returncode = 1
        stdout = b""
        stderr = b"failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine"

    monkeypatch.setattr(eolas_v2.shutil, "which", lambda name: "docker")
    r = eolas_v2._run_code_case("def f(): pass", "f()", run=lambda *a, **k: P())
    assert r["executed"] is False and r["sandbox_error"] and "no es un fallo del código" in r["output"]
    P.returncode, P.stderr = 125, b"docker: Error response from daemon"
    assert eolas_v2._run_code_case("x = 1", "", run=lambda *a, **k: P())["sandbox_error"]

    cfg_path = tmp_path / "eolas.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(cfg_path))
    cfg_path.write_text(json.dumps(_config(tmp_path, active="gemma_q4")), encoding="utf-8")
    monkeypatch.setattr(eolas_v2, "sandbox_ready", lambda: (False, "Docker no está en marcha"))
    monkeypatch.setattr(eolas_v2, "_start_locked", lambda *a, **k: pytest.fail("no debe cargar motores sin contenedor"))
    with pytest.raises(RuntimeError, match="necesita el contenedor"):
        eolas_v2.run_full_evaluation(profiles=["gemma_q4"], battery="codigo")
    # Si cae a mitad, la batería se detiene en vez de seguir puntuando.
    monkeypatch.setattr(eolas_v2, "sandbox_ready", lambda: (True, ""))
    monkeypatch.setattr(eolas_v2, "_start_locked", lambda *a, **k: {"started": True})
    monkeypatch.setattr(eolas_v2, "_stop_locked", lambda *a, **k: False)
    monkeypatch.setattr(eolas_v2, "_evaluation_request", lambda *a, **k: {"content": "```python\nx=1\n```", "usage": {}})
    monkeypatch.setattr(eolas_v2, "_run_code_case", lambda *a, **k: {"passed": False, "executed": False,
                                                                     "sandbox_error": True, "output": "Docker parado"})
    with pytest.raises(RuntimeError, match="se detuvo: el contenedor dejó de estar disponible"):
        eolas_v2.run_full_evaluation(profiles=["gemma_q4"], battery="codigo")


def test_lecciones_por_causa_sin_pistas_y_aplicadas_al_motor(tmp_path, monkeypatch):
    """Los fallos se clasifican por causa a partir del error real; la lección es general, por motor, y se aplica."""
    from eolfi import eolas_v2

    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(tmp_path / "eolas-v2.json"))
    assert eolas_v2.classify_failure("  File \"<stdin>\", line 4\nAttributeError: 'int' object has no attribute 'decode'") == "tipos"
    assert eolas_v2.classify_failure("Traceback\nAssertionError") == "logica"
    assert eolas_v2.classify_failure("todo bien") is None
    eolas_v2.record_lessons("gemma_q4", ["NameError: name 'parsear_log' is not defined", "AssertionError", "AssertionError"])
    report = eolas_v2.lessons_report()["motores"]["gemma_q4"]
    assert {(l["categoria"], l["veces"]) for l in report} == {("nombre", 1), ("logica", 2)}
    lessons = eolas_v2.active_lessons("gemma_q4")
    text = " ".join(lessons)
    assert "parsear_log" not in text and len(lessons) == 2           # sin rastro de la tarea ni de la solución
    assert eolas_v2.active_lessons("qwen14_q4") == []                # cada motor aprende de sus propios fallos
    eolas_v2.set_lesson_active("gemma_q4", "logica", False)
    assert len(eolas_v2.active_lessons("gemma_q4")) == 1
    with pytest.raises(ValueError):
        eolas_v2.set_lesson_active("gemma_q4", "inventada", True)


def test_bateria_aprende_de_los_fallos_y_las_tareas_nuevas_no_alimentan_lecciones(tmp_path, monkeypatch):
    from eolfi import eolas_v2

    cfg_path = tmp_path / "eolas.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(cfg_path))
    cfg_path.write_text(json.dumps(_config(tmp_path, active="gemma_q4")), encoding="utf-8")
    monkeypatch.setattr(eolas_v2, "sandbox_ready", lambda: (True, ""))
    monkeypatch.setattr(eolas_v2, "_start_locked", lambda *a, **k: {"started": True})
    monkeypatch.setattr(eolas_v2, "_stop_locked", lambda *a, **k: False)
    systems = []
    monkeypatch.setattr(eolas_v2, "_evaluation_request", lambda c, msgs, *a, **k: systems.append(msgs[0]["content"])
                        or {"content": "```python\nx = 1\n```", "usage": {}})
    monkeypatch.setattr(eolas_v2, "_run_code_case", lambda *a, **k: {"passed": False, "executed": True,
                                                                     "output": "NameError: name 'f' is not defined"})
    eolas_v2.run_full_evaluation(profiles=["gemma_q4"], battery="codigo")
    assert eolas_v2.lessons_report()["motores"]["gemma_q4"][0]["categoria"] == "nombre"
    systems.clear()
    eolas_v2.run_full_evaluation(profiles=["gemma_q4"], battery="codigo_nuevo", learn=False)
    writing = [s for s in systems if s.startswith("Escribe la solución final")]
    assert writing and all("Lecciones de tus errores anteriores" in s for s in writing)   # se aplican
    before = eolas_v2.lessons_report()["motores"]["gemma_q4"][0]["veces"]
    assert before == len(eolas_v2.CODE_EVALUATION_CASES)        # una causa por tarea (primer intento); las nuevas no suman
    systems.clear()
    eolas_v2.run_full_evaluation(profiles=["gemma_q4"], battery="codigo_nuevo", learn=False, use_lessons=False)
    assert not any("Lecciones de tus errores" in s for s in systems)                      # comparación sin lecciones


def test_aporte_para_alejandria_lleva_cabecera_y_no_se_duplica(tmp_path):
    """El código que pasa sus pruebas se guarda con su procedencia; Alejandría lo valida al organizarlo."""
    from eolfi import eolas_v2

    case = {"id": "palindromo", "label": "Código · palíndromo", "prompt": "Escribe es_palindromo(texto) con C:\ruta"}
    first = eolas_v2.save_contribution("gemma_q4", "gemma:q4", case, "def es_palindromo(t):\n    return t == t[::-1]", True)
    assert first and first.parent == tmp_path / "aportes" / "palindromo"
    text = first.read_text(encoding="utf-8")
    assert text.startswith("# Aporte de Eolfi a Alejandría") and "a la primera" in text and "Motor: gemma_q4" in text
    compile(text, str(first), "exec")                                  # la cabecera nunca rompe el código
    again = eolas_v2.save_contribution("gemma_q4", "gemma:q4", case, "def es_palindromo(t):\n    return t == t[::-1]", False)
    assert again == first and len(list(first.parent.iterdir())) == 1  # mismo código, un solo aporte
    assert eolas_v2.save_contribution("gemma_q4", "gemma:q4", case, "   ", True) is None


def test_sesion_de_herramientas_usa_las_herramientas_reales_y_devuelve_datos(monkeypatch):
    from eolfi import eolas_v2

    class FakeMCP:
        tools = {name: ({"name": name, "description": "d", "inputSchema": {"type": "object"}}, None)
                 for name in ("eolfi_triage", "eolfi_biblioteca_buscar", "eolfi_biblioteca_leer", "eolfi_otra")}

        def call_tool(self, name, args):
            return {"content": [{"type": "text", "text": "MAX_READ_CHARS = 30_000"}], "isError": False}

    sent = []
    replies = iter([
        {"tool_calls": [{"id": "1", "function": {"name": "eolfi_biblioteca_leer", "arguments": '{"ruta": "x"}'}},
                        {"id": "2", "function": {"name": "ejecutar_python", "arguments": '{"codigo": "print(1)"}'}},
                        {"id": "3", "function": {"name": "borrar_todo", "arguments": "{}"}}]},
        {"content": '{"valor": 30000}'},
    ])
    monkeypatch.setattr(eolas_v2, "_chat_tools", lambda c, msgs, tools, **k: sent.append((list(msgs), tools)) or next(replies))
    monkeypatch.setattr(eolas_v2, "_run_code_case", lambda code, tests, **k: {"passed": True, "executed": True,
                                                                             "output": "1\nEOLFI-OK"})
    final, calls = eolas_v2._tool_session({"alias": "m", "url": "u"}, "tarea", FakeMCP(), lambda _: None, "gemma_q4")
    assert final == '{"valor": 30000}'
    names = {t["function"]["name"] for t in sent[0][1]}
    assert names == {"eolfi_triage", "eolfi_biblioteca_buscar", "eolfi_biblioteca_leer", "ejecutar_python"}
    assert [(c["name"], c["ok"]) for c in calls] == [("eolfi_biblioteca_leer", True), ("ejecutar_python", True),
                                                     ("borrar_todo", False)]
    tool_msgs = [m for m in sent[1][0] if m["role"] == "tool"]
    assert tool_msgs[0]["content"] == "MAX_READ_CHARS = 30_000" and tool_msgs[1]["content"] == "1"
    assert "desconocida" in tool_msgs[2]["content"]


def test_ronda_completa_decide_aprobados_y_aporta_lo_que_pasa(tmp_path, monkeypatch):
    """Aprueba quien resuelve ≥75 % a la primera en código y en herramientas; el código aprobado se aporta."""
    import hashlib

    from eolfi import eolas_v2, mcp_server

    cfg_path = tmp_path / "eolas.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(cfg_path))
    cfg_path.write_text(json.dumps(_config(tmp_path, active="gemma_q4")), encoding="utf-8")
    monkeypatch.setattr(eolas_v2, "sandbox_ready", lambda: (True, ""))
    current = {}
    monkeypatch.setattr(eolas_v2, "_start_locked", lambda name, cfg=None, **k: current.update(name=name) or {"started": True})
    monkeypatch.setattr(eolas_v2, "_stop_locked", lambda *a, **k: False)

    class FakeMCP:
        def __init__(self, db=None, roots=None, library=None):
            self.tools = {n: ({"name": n, "description": "d", "inputSchema": {"type": "object"}}, None)
                          for n in eolas_v2.ROUND_MCP_TOOLS}

        def call_tool(self, name, args):
            return {"content": [{"type": "text", "text": "datos"}], "isError": False}

    monkeypatch.setattr(mcp_server, "EolfiMCP", FakeMCP)
    monkeypatch.setattr(eolas_v2, "_evaluation_request", lambda *a, **k: {"content": "```python\ndef bien(): pass\n```", "usage": {}})
    monkeypatch.setattr(eolas_v2, "_run_code_case", lambda code, tests, **k: {"passed": "bien" in code, "executed": True,
                                                                             "output": "EOLFI-OK"})
    sha = hashlib.sha256(eolas_v2._WASM_SAMPLE).hexdigest()
    answers = {"identificar_binario": ("eolfi_triage", json.dumps({"formato": "wasm", "sha256": sha})),
               "buscar_definicion": ("eolfi_biblioteca_buscar", json.dumps({"ruta": "corpus/codigo/Eolfi/eolfi/library.py"})),
               "leer_constante": ("eolfi_biblioteca_leer", '{"valor": 30000}'),
               "calcular_con_codigo": ("ejecutar_python", '{"resultado": 49345379}'),
               "reimplementar_de_biblioteca": ("eolfi_biblioteca_leer", "```python\ndef bien(): pass\n```")}

    def fake_chat(c, msgs, tools, **k):
        prompt = msgs[1]["content"]
        case = next(x for x in eolas_v2.TOOL_EVALUATION_CASES if x["prompt"].split("{")[0][:40] in prompt)
        tool, answer = answers[case["id"]]
        if current["name"] == "mistral":                    # responde sin usar herramientas: lo supone
            return {"content": answer}
        if msgs[-1]["role"] != "tool":
            return {"tool_calls": [{"id": "1", "function": {"name": tool, "arguments": '{"codigo": "print(1)"}'}}]}
        return {"content": answer}

    monkeypatch.setattr(eolas_v2, "_chat_tools", fake_chat)
    report = eolas_v2.run_full_evaluation(profiles=["gemma_q4", "mistral"], battery="completa")
    assert report["battery"] == "completa" and "nemo_moe" not in report["summary"]
    g, m = report["summary"]["gemma_q4"], report["summary"]["mistral"]
    assert g["herramientas"] == {"casos": 5, "primera": 5, "final": 5} and g["codigo_primera_pct"] == 100 and g["aprobado"]
    assert m["herramientas_pct"] == 0 and not m["aprobado"]          # acertar sin usar la herramienta no cuenta
    assert report["mejor"] == "gemma_q4" and report["no_aprueban"] == ["mistral"]
    aportes = list((tmp_path / "aportes").rglob("*.py"))
    assert aportes and any(p.parent.name == "reimplementar_de_biblioteca" for p in aportes)


def test_objeto_json_acepta_rutas_de_windows_sin_escapar():
    from eolfi import eolas_v2

    assert eolas_v2._json_object(r'Aquí: {"ruta": "codigo\Eolfi\eolfi\library.py"}')["ruta"].endswith(r"eolfi\library.py")
    assert eolas_v2._json_object(json.dumps({"ruta": r"a\b.py"}))["ruta"] == r"a\b.py"
    assert eolas_v2._json_object("sin json") == {} and eolas_v2._json_object("[1]") == {}


def test_herramientas_basta_usar_una_de_las_exigidas():
    from eolfi import eolas_v2

    lib = next(c for c in eolas_v2.TOOL_EVALUATION_CASES if c["id"] == "leer_constante")
    assert eolas_v2._tools_requirement_met(lib, {"eolfi_biblioteca_buscar"})
    assert eolas_v2._tools_requirement_met(lib, {"eolfi_biblioteca_leer", "ejecutar_python"})
    assert not eolas_v2._tools_requirement_met(lib, set())                # suponer el dato no cuenta
    assert not eolas_v2._tools_requirement_met(lib, {"ejecutar_python"})


def test_imprimir_la_marca_y_salir_no_aprueba_sin_pasar_las_pruebas(monkeypatch):
    """Un código que imprime «EOLFI-OK» y sale antes de las pruebas no puede aprobar: la marca real es aleatoria."""
    import subprocess
    import sys

    from eolfi import eolas_v2

    monkeypatch.setattr(eolas_v2.shutil, "which", lambda name: "docker")

    def local_run(argv, input, capture_output, timeout):        # el programa se ejecuta aquí en vez del contenedor
        return subprocess.run([sys.executable, "-I", "-"], input=input, capture_output=True, timeout=timeout)

    trampa = "import sys\nprint('EOLFI-OK')\nsys.exit(0)\ndef f(): return 1"
    assert not eolas_v2._run_code_case(trampa, "assert f() == 2", run=local_run)["passed"]
    bueno = eolas_v2._run_code_case("def f(): return 2", "assert f() == 2", run=local_run)
    assert bueno["passed"] and bueno["output"].strip() == "EOLFI-OK"
    malo = eolas_v2._run_code_case("def f(): return 1", "assert f() == 2", run=local_run)
    assert not malo["passed"] and "se esperaba" in malo["output"]


def test_eolas_v2_exige_clave_de_api_que_no_aparece_en_la_linea_de_ordenes(tmp_path, monkeypatch):
    """12/11/2026: Eolfi necesita la clave de Eolas V2; llama-server la lee de un archivo, no de sus argumentos."""
    from eolfi import eolas_v2

    cfg_path = tmp_path / "eolas.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(cfg_path))
    cfg = _config(tmp_path)
    key = eolas_v2.api_key()
    assert len(key) >= 32 and eolas_v2.api_key() == key                       # se crea una vez y se conserva
    assert eolas_v2.api_key_file() == tmp_path / "eolas-v2.key"
    args = eolas_v2.server_args("mistral", cfg)
    assert args[args.index("--api-key-file") + 1] == str(eolas_v2.api_key_file())
    assert key not in " ".join(args) and "--api-key" not in args
    assert eolas_v2.auth_headers() == {"Authorization": f"Bearer {key}"}
    monkeypatch.setenv("EOLAS_V2_API_KEY", "clave-del-titular")
    assert eolas_v2.api_key() == "clave-del-titular"
    assert eolas_v2.api_key_file().read_text(encoding="utf-8") == "clave-del-titular"   # el motor usa la misma


def test_peticiones_al_motor_llevan_la_clave(tmp_path, monkeypatch):
    from eolfi import eolas_v2

    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(tmp_path / "eolas.json"))
    sent = []

    class R:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                                           "data": [{"id": "gemma"}]}).encode()

    monkeypatch.setattr(eolas_v2.urllib.request, "urlopen", lambda req, timeout=0: sent.append(req) or R())
    eolas_v2._evaluation_request({"alias": "gemma", "url": "http://127.0.0.1:8090"}, [{"role": "user", "content": "x"}])
    assert eolas_v2._healthy({"url": "http://127.0.0.1:8090"}, "gemma")
    auth = f"Bearer {eolas_v2.api_key()}"
    assert [r.get_header("Authorization") for r in sent] == [auth, None, auth]   # /health es público; /v1/* con clave


def test_perfil_retirado_no_se_ofrece_ni_se_carga_y_se_puede_restaurar(tmp_path, monkeypatch):
    from eolfi import eolas_v2

    cfg_path = tmp_path / "eolas.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(cfg_path))
    cfg_path.write_text(json.dumps(_config(tmp_path, active="gemma_q4")), encoding="utf-8")
    assert "mistral" in eolas_v2.available_evaluation_profiles()
    assert eolas_v2.retire_profile("mistral") == ["mistral"]
    assert "mistral" not in eolas_v2.available_evaluation_profiles()
    with pytest.raises(RuntimeError, match="retirado"):
        eolas_v2._start_locked("mistral", popen=lambda *a, **k: pytest.fail("no debe arrancar"))
    with pytest.raises(ValueError, match="retirado"):
        eolas_v2.set_active_profile("mistral")
    with pytest.raises(ValueError, match="motor activo"):
        eolas_v2.retire_profile("gemma_q4")                               # nunca el motor en uso
    assert eolas_v2.restore_profile("mistral") == []
    assert "mistral" in eolas_v2.available_evaluation_profiles()


def test_fuera_de_alcance_en_cuanto_no_puede_llegar_al_umbral(monkeypatch):
    from eolfi import eolas_v2

    assert eolas_v2.ROUND_PASS_RATIO == 0.85                               # decisión del titular (14/11/2026)
    t = {k: {"casos": 0, "primera": 0, "final": 0} for k in ("codigo", "codigo_nuevo", "herramientas")}
    t["codigo"].update(casos=2, primera=0)
    assert eolas_v2._out_of_reach(t, 14, 5) is None                       # 2 fallos: aún puede (12/14 = 86 %)
    t["codigo_nuevo"].update(casos=1, primera=0)
    assert "85 %" in eolas_v2._out_of_reach(t, 14, 5)                     # 3 fallos: máximo 11/14 = 79 %
    t = {k: {"casos": 0, "primera": 0, "final": 0} for k in ("codigo", "codigo_nuevo", "herramientas")}
    t["herramientas"].update(casos=1, primera=0)
    assert "herramientas" in eolas_v2._out_of_reach(t, 14, 5)             # 1 fallo: máximo 4/5 = 80 %
    monkeypatch.setattr(eolas_v2, "ROUND_PASS_RATIO", 0.75)                # con el umbral anterior, como antes
    assert eolas_v2._out_of_reach(t, 14, 5) is None


def test_ronda_descarta_pronto_y_retira_al_que_no_aprueba(tmp_path, monkeypatch):
    from eolfi import eolas_v2, mcp_server

    cfg_path = tmp_path / "eolas.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(cfg_path))
    cfg_path.write_text(json.dumps(_config(tmp_path, active="gemma_q4")), encoding="utf-8")
    monkeypatch.setattr(eolas_v2, "sandbox_ready", lambda: (True, ""))
    monkeypatch.setattr(eolas_v2, "_start_locked", lambda *a, **k: {"started": True})
    monkeypatch.setattr(eolas_v2, "_stop_locked", lambda *a, **k: False)

    class FakeMCP:
        def __init__(self, *a, **k):
            self.tools = {}

    monkeypatch.setattr(mcp_server, "EolfiMCP", FakeMCP)
    asked = []
    monkeypatch.setattr(eolas_v2, "_evaluation_request", lambda *a, **k: asked.append(1) or {"content": "```python\nx=1\n```", "usage": {}})
    monkeypatch.setattr(eolas_v2, "_run_code_case", lambda *a, **k: {"passed": False, "executed": True, "output": "AssertionError"})
    monkeypatch.setattr(eolas_v2, "_tool_session", lambda *a, **k: ("no sé", []))
    report = eolas_v2.run_full_evaluation(profiles=["mistral"], battery="completa", retire_failed=True)
    m = report["summary"]["mistral"]
    assert "descartado" in m and not m["aprobado"] and m["retirado"]
    kinds = [r["kind"] for r in report["results"] if r["profile"] == "mistral"]
    # 13/11/2026: al 3.er fallo deja el código, pero hace IGUALMENTE las 5 de herramientas (antes no llegaba nunca).
    assert len(kinds) == 3 + len(eolas_v2.TOOL_EVALUATION_CASES) and kinds[3:] == ["herramientas"] * len(eolas_v2.TOOL_EVALUATION_CASES)
    assert m["codigo_primera_pct"] == 0 and "mistral" in eolas_v2.load_config()["retired_profiles"]


def test_desinstalar_un_motor_no_deja_restos_ni_toca_lo_compartido(tmp_path, monkeypatch):
    """13/11/2026: «los motores que se eliminan se autodesinstalan para no dejar restos»."""
    from eolfi import eolas_v2

    cfg_path = tmp_path / "eolas.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(cfg_path))
    cfg = _config(tmp_path, active="gemma_q4")
    parts = [tmp_path / f"q-0000{i}-of-00002.gguf" for i in (1, 2)]
    for f in parts:
        f.write_bytes(b"x" * 10)
    (tmp_path / "q.sha256").write_text("abc q", encoding="utf-8")
    cfg["profiles"]["qwen14_q4"] = {**eolas_v2.DEFAULT_PROFILES["qwen14_q4"], "model": str(parts[0])}
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    eolas_v2.record_lessons("qwen14_q4", ["AssertionError"])
    eolas_v2.record_lessons("gemma_q4", ["AssertionError"])
    out = eolas_v2.uninstall_profile("qwen14_q4")
    assert sorted(Path(f).name for f in out["archivos_borrados"]) == ["q-00001-of-00002.gguf", "q-00002-of-00002.gguf", "q.sha256"]
    assert out["lecciones_borradas"] and "qwen14_q4" not in eolas_v2.lessons_report()["motores"]
    assert "gemma_q4" in eolas_v2.lessons_report()["motores"]                    # las de los demás se quedan
    assert eolas_v2.is_retired("qwen14_q4")
    with pytest.raises(ValueError, match="motor activo"):
        eolas_v2.uninstall_profile("gemma_q4")
    shared = eolas_v2.load_config()["profiles"]["gemma"]["model"]
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["profiles"]["mistral"]["model"] = shared                               # dos perfiles, un archivo
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    out = eolas_v2.uninstall_profile("mistral")
    assert out["archivos_borrados"] == [] and out["gguf_compartido_con"] == ["gemma"] and Path(shared).exists()


def test_ronda_endurecida_guarda_examenes_sin_duplicar_y_no_aprende(tmp_path, monkeypatch):
    """14/11/2026: sin lecciones, progreso legible y exámenes JSONL para Alejandría sin duplicados."""
    from eolfi import eolas_v2, mcp_server

    cfg_path = tmp_path / "eolas.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(cfg_path))
    cfg = _config(tmp_path, active="gemma_q4")
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / "gemma-q4.sha256").write_text("ab" * 32 + " gemma-q4.gguf", encoding="utf-8")
    monkeypatch.setattr(eolas_v2, "sandbox_ready", lambda: (True, ""))
    monkeypatch.setattr(eolas_v2, "_start_locked", lambda *a, **k: {"started": True})
    monkeypatch.setattr(eolas_v2, "_stop_locked", lambda *a, **k: False)

    class FakeMCP:
        def __init__(self, *a, **k):
            self.tools = {}

    monkeypatch.setattr(mcp_server, "EolfiMCP", FakeMCP)
    asked = []
    monkeypatch.setattr(eolas_v2, "_evaluation_request", lambda c, msgs, *a, **k: asked.append(msgs[0]["content"]) or
                        {"content": "```python\nx = 1  # contacto: ana@example.com\n```", "usage": {}})
    monkeypatch.setattr(eolas_v2, "_run_code_case", lambda *a, **k: {"passed": False, "executed": True, "output": "AssertionError"})
    monkeypatch.setattr(eolas_v2, "_tool_session", lambda *a, **k: ("no sé", []))
    eolas_v2.record_lessons("gemma_q4", ["NameError: name 'x' is not defined"])        # una lección previa
    report = eolas_v2.run_full_evaluation(profiles=["gemma_q4"], battery="completa")
    assert not any("Lecciones de tus errores" in s for s in asked)                     # no se aplican
    assert eolas_v2.lessons_report()["motores"]["gemma_q4"][0]["veces"] == 1           # ni se aprenden
    lines = [json.loads(l) for l in Path(report["examenes"]).read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 3 + len(eolas_v2.TOOL_EVALUATION_CASES)                        # 3 de código (descarte) + herramientas
    assert lines[0]["esquema"] == "eolfi.examen-motor/1"
    r = lines[0]
    assert r["motor"]["sha256"] == "ab" * 32 and r["motor"]["perfil"] == "gemma_q4" and r["examen"]["version"]
    assert r["correccion"]["aprobado"] is False and "AssertionError" in str(r["correccion"])
    assert "ana@example.com" not in json.dumps(lines)                                   # redactado de privacidad
    estado = json.loads(eolas_v2.progress_file().read_text(encoding="utf-8"))
    assert estado["estado"] == "terminada" and estado["examenes"] == report["examenes"] and estado["registro"]
    again = eolas_v2.run_full_evaluation(profiles=["gemma_q4"], battery="completa")
    assert not Path(again["examenes"]).exists()                                         # misma ronda: nada duplicado


def test_casos_ineditos_tienen_referencia_que_pasa_y_discriminan(monkeypatch):
    """14/11/2026: los casos inéditos son correctos (la referencia pasa) y una solución equivocada falla."""
    import subprocess
    import sys

    from eolfi import eolas_v2
    from tests.referencias_ineditos import REFERENCIAS

    monkeypatch.setattr(eolas_v2.shutil, "which", lambda name: "docker")

    def local_run(argv, input, capture_output, timeout):
        return subprocess.run([sys.executable, "-I", "-"], input=input, capture_output=True, timeout=timeout)

    assert {c["id"] for c in eolas_v2.CODE_UNSEEN_CASES} == set(REFERENCIAS)
    for case in eolas_v2.CODE_UNSEEN_CASES:
        assert eolas_v2._run_code_case(REFERENCIAS[case["id"]], case["tests"], run=local_run)["passed"], case["id"]
        wrong = f"def {case['id']}(*a, **k):\n    return None\n"
        assert not eolas_v2._run_code_case(wrong, case["tests"], run=local_run)["passed"], case["id"]


def test_formato_estricto_en_herramientas():
    from eolfi import eolas_v2

    assert eolas_v2._strict_json('{"valor": 30000}') == {"valor": 30000}
    assert eolas_v2._strict_json('```json\n{"valor": 30000}\n```') == {"valor": 30000}
    assert eolas_v2._strict_json('El valor es {"valor": 30000}') is None           # texto alrededor: inválido
    assert eolas_v2._strict_json('[1, 2]') is None and eolas_v2._strict_json('') is None


def test_ronda_endurecida_formato_tiempo_y_llamadas_erroneas(tmp_path, monkeypatch):
    """Código sin bloque ```python no cuenta a la primera; pasarse de tiempo suspende; ≥3 llamadas erróneas suspenden."""
    from eolfi import eolas_v2, mcp_server

    cfg_path = tmp_path / "eolas.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(cfg_path))
    cfg_path.write_text(json.dumps(_config(tmp_path, active="gemma_q4")), encoding="utf-8")
    monkeypatch.setattr(eolas_v2, "sandbox_ready", lambda: (True, ""))
    monkeypatch.setattr(eolas_v2, "_start_locked", lambda *a, **k: {"started": True})
    monkeypatch.setattr(eolas_v2, "_stop_locked", lambda *a, **k: False)

    class FakeMCP:
        def __init__(self, *a, **k):
            self.tools = {}

    monkeypatch.setattr(mcp_server, "EolfiMCP", FakeMCP)
    monkeypatch.setattr(eolas_v2, "CODE_EVALUATION_CASES", eolas_v2.CODE_EVALUATION_CASES[:1])
    monkeypatch.setattr(eolas_v2, "CODE_VALIDATION_CASES", ())
    monkeypatch.setattr(eolas_v2, "CODE_UNSEEN_CASES", ())
    # Código correcto pero SIN bloque ```python: pasa, pero no cuenta a la primera.
    monkeypatch.setattr(eolas_v2, "_evaluation_request", lambda *a, **k: {"content": "def es_palindromo(t): return True", "usage": {}})
    monkeypatch.setattr(eolas_v2, "_run_code_case", lambda *a, **k: {"passed": True, "executed": True, "output": "EOLFI-OK"})
    calls = iter([[{"name": "eolfi_triage", "ok": False}] * 3 + [{"name": "eolfi_triage", "ok": True}]] + [[]] * 10)
    monkeypatch.setattr(eolas_v2, "_tool_session", lambda c, prompt, mcp, announce, name: ('{"formato": "wasm", "sha256": "x"}', next(calls)))
    report = eolas_v2.run_full_evaluation(profiles=["gemma_q4"], battery="completa")
    code = [r for r in report["results"] if r["kind"] == "codigo"][0]
    assert code["passed"] and not code["first_try"] and "bloque" in code["formato_invalido"]
    assert "descartado" in report["summary"]["gemma_q4"]                   # con el 85 %, ese fallo ya descarta
    monkeypatch.setattr(eolas_v2, "CODE_EVALUATION_CASES", ())             # ahora solo herramientas
    calls = iter([[{"name": "eolfi_triage", "ok": False}] * 3 + [{"name": "eolfi_triage", "ok": True}]] + [[]] * 10)
    report = eolas_v2.run_full_evaluation(profiles=["gemma_q4"], battery="completa")
    tool = [r for r in report["results"] if r["kind"] == "herramientas"][0]
    assert not tool["passed"] and tool["llamadas_erroneas"] == 3
    # Pasarse del tiempo límite suspende aunque la respuesta sea correcta.
    monkeypatch.setattr(eolas_v2, "CASE_TIME_LIMIT_S", -1)
    monkeypatch.setattr(eolas_v2, "CODE_EVALUATION_CASES", eolas_v2.CODE_EVALUATION_CASES or ())
    monkeypatch.setattr(eolas_v2, "_evaluation_request", lambda *a, **k: {"content": "```python\ndef es_palindromo(t): return True\n```", "usage": {}})
    report = eolas_v2.run_full_evaluation(profiles=["gemma_q4"], battery="completa")
    assert all(r.get("tiempo_excedido") and not r["passed"] for r in report["results"])


def test_corpus_de_entrenamiento_solo_respuestas_buenas_clasificadas(tmp_path, monkeypatch):
    """14/11/2026: las respuestas verificadas como buenas van a Alejandría clasificadas por tipo y calidad."""
    from eolfi import eolas_v2, mcp_server

    cfg_path = tmp_path / "eolas.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(cfg_path))
    cfg_path.write_text(json.dumps(_config(tmp_path, active="gemma_q4")), encoding="utf-8")
    monkeypatch.setattr(eolas_v2, "sandbox_ready", lambda: (True, ""))
    monkeypatch.setattr(eolas_v2, "_start_locked", lambda *a, **k: {"started": True})
    monkeypatch.setattr(eolas_v2, "_stop_locked", lambda *a, **k: False)

    class FakeMCP:
        def __init__(self, *a, **k):
            self.tools = {}

    monkeypatch.setattr(mcp_server, "EolfiMCP", FakeMCP)
    monkeypatch.setattr(eolas_v2, "CODE_EVALUATION_CASES", eolas_v2.CODE_EVALUATION_CASES[:2])
    monkeypatch.setattr(eolas_v2, "CODE_VALIDATION_CASES", ())
    monkeypatch.setattr(eolas_v2, "CODE_UNSEEN_CASES", ())
    monkeypatch.setattr(eolas_v2, "TOOL_EVALUATION_CASES", ())
    monkeypatch.setattr(eolas_v2, "ROUND_PASS_RATIO", 0.5)
    answers = iter(["```python\ndef es_palindromo(t): return True\n```"] * 2 + ["```python\nmal\n```"] * 10)
    monkeypatch.setattr(eolas_v2, "_evaluation_request", lambda *a, **k: {"content": next(answers), "usage": {}})
    monkeypatch.setattr(eolas_v2, "_run_code_case", lambda code, tests, **k: {"passed": "def" in code, "executed": True,
                                                                             "output": "EOLFI-OK" if "def" in code else "AssertionError"})
    eolas_v2.run_full_evaluation(profiles=["gemma_q4"], battery="completa")
    base = eolas_v2.training_dir()
    files = sorted(p.relative_to(base).as_posix() for p in base.rglob("*.jsonl"))
    assert files == ["codigo/a-la-primera/palindromo.jsonl"]                  # solo la buena; la mala no entra
    ex = json.loads((base / files[0]).read_text(encoding="utf-8").splitlines()[0])
    assert ex["esquema"] == "eolfi.ejemplo-entrenamiento/1" and ex["calidad"] == "a-la-primera"
    assert [m["role"] for m in ex["mensajes"]] == ["user", "assistant"] and "def es_palindromo" in ex["mensajes"][1]["content"]
    assert ex["motor"]["perfil"] == "gemma_q4" and ex["verificacion"]["pruebas"]
    answers = iter(["```python\ndef es_palindromo(t): return True\n```"] * 2 + ["```python\nmal\n```"] * 10)
    eolas_v2.run_full_evaluation(profiles=["gemma_q4"], battery="completa")             # repetir no duplica
    assert len((base / files[0]).read_text(encoding="utf-8").splitlines()) == 1


def test_repesca_conserva_lo_aprobado_y_repite_lo_fallado(tmp_path, monkeypatch):
    """13/11/2026 (titular): cada motor repite solo lo que falló o no llegó a contestar en la ronda anterior."""
    from eolfi import eolas_v2, mcp_server

    cfg_path = tmp_path / "eolas.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(cfg_path))
    cfg_path.write_text(json.dumps(_config(tmp_path, active="gemma_q4")), encoding="utf-8")
    monkeypatch.setattr(eolas_v2, "sandbox_ready", lambda: (True, ""))
    monkeypatch.setattr(eolas_v2, "_start_locked", lambda *a, **k: {"started": True})
    monkeypatch.setattr(eolas_v2, "_stop_locked", lambda *a, **k: False)

    class FakeMCP:
        def __init__(self, *a, **k):
            self.tools = {}

    monkeypatch.setattr(mcp_server, "EolfiMCP", FakeMCP)
    monkeypatch.setattr(eolas_v2, "CODE_EVALUATION_CASES", eolas_v2.CODE_EVALUATION_CASES[:3])
    monkeypatch.setattr(eolas_v2, "CODE_VALIDATION_CASES", ())
    monkeypatch.setattr(eolas_v2, "CODE_UNSEEN_CASES", ())
    monkeypatch.setattr(eolas_v2, "TOOL_EVALUATION_CASES", ())
    first = eolas_v2.CODE_EVALUATION_CASES[0]["id"]
    monkeypatch.setattr(eolas_v2, "_evaluation_request", lambda c, msgs, *a, **k: {"content": "```python\nx=1\n```", "usage": {}})
    asked: list[str] = []

    def run(code, tests):
        asked.append(tests)
        ok = tests == eolas_v2.CODE_EVALUATION_CASES[0]["tests"]
        return {"passed": ok, "executed": True, "output": "EOLFI-OK" if ok else "AssertionError"}

    monkeypatch.setattr(eolas_v2, "_run_code_case", run)
    before = eolas_v2.run_full_evaluation(profiles=["gemma_q4"], battery="completa")
    assert before["summary"]["gemma_q4"]["codigo_primera_pct"] < 85
    asked.clear()
    monkeypatch.setattr(eolas_v2, "_run_code_case", lambda *a, **k: asked.append(1) or {"passed": True, "executed": True, "output": "EOLFI-OK"})
    again = eolas_v2.run_full_evaluation(profiles=["gemma_q4"], battery="completa", repesca=before["examenes"])
    kept = [r for r in again["results"] if r.get("arrastrado")]
    assert [r["case"] for r in kept] == [first]                     # lo aprobado no se repite
    assert len(asked) == 2                                           # solo las dos falladas
    assert again["summary"]["gemma_q4"]["codigo_primera_pct"] == 100
