"""Fase 6: resiliencia de los lectores nuevos ante entradas hostiles (guiones, TOML, privacidad, paquetes).

Cada lector debe rechazar con su error controlado (ValueError/ScriptError) o aceptar, nunca colgarse ni lanzar
otra excepción. Semilla fija: los fallos se pueden repetir.
"""
import json
import random
import time

import pytest

from eolfi.compat_toml import _Parser
from eolfi.observe import ScriptError, validate_script
from eolfi.security.privacy import redact

SEED = 20261107


def _random_json(rng, depth=0):
    kind = rng.randrange(7 if depth < 4 else 4)
    if kind == 0:
        return rng.choice([None, True, False])
    if kind == 1:
        return rng.choice([0, -1, 2 ** 63, 1e308, 0.5])
    if kind == 2:
        return "".join(rng.choice("ab{}[]\"\\/\x00ñ ") for _ in range(rng.randrange(20)))
    if kind == 3:
        return rng.choice(["run", "http", "browser", "desktop", "write_file", "../x", "C:/x", "{target}"])
    if kind == 4:
        return [_random_json(rng, depth + 1) for _ in range(rng.randrange(4))]
    keys = ["eolfi_observation_script", "name", "authorization", "steps", "action", "argv", "path", "url",
            "isolation", "mode", "image", "scope", "files", "registry", "actions", "do", "selector", "stdin",
            "text", "base64", "env", "timeout", "privacy", "target", "setup"]
    return {rng.choice(keys): _random_json(rng, depth + 1) for _ in range(rng.randrange(5))}


def test_script_validator_never_crashes_on_random_input():
    rng = random.Random(SEED)
    accepted = 0
    for _ in range(3000):
        raw = _random_json(rng)
        if isinstance(raw, dict) and rng.random() < 0.5:
            raw.update({"eolfi_observation_script": 1, "name": "x", "authorization": "y"})
        try:
            validate_script(raw)
            accepted += 1
        except ScriptError:
            pass
    assert accepted < 3000


def test_script_rejects_oversized_and_deep_input():
    big = {"eolfi_observation_script": 1, "name": "x", "authorization": "y",
           "steps": [{"action": "write_file", "path": "a", "text": "x" * (2 * 1024 * 1024)}]}
    with pytest.raises(ScriptError, match="mayor"):
        validate_script(big)
    deep: dict = {}
    cur = deep
    for _ in range(200):
        cur["actions"] = [{}]
        cur = cur["actions"][0]
    with pytest.raises(ScriptError):
        validate_script({"eolfi_observation_script": 1, "name": "x", "authorization": "y",
                         "steps": [{"action": "browser", "url": "http://127.0.0.1/", **deep}]})


def test_toml_fallback_never_crashes_and_stays_fast():
    rng = random.Random(SEED)
    alphabet = '[]{}="\'.,#\n \\abc123-_+:tfrueals'
    for _ in range(3000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randrange(60)))
        try:
            _Parser(text).parse()
        except ValueError:
            pass
    t = time.perf_counter()
    import eolfi.compat_toml as ct

    real = ct._tomllib
    ct._tomllib = None            # fuerza el lector propio (el de Python 3.10) aunque haya tomllib
    try:
        for doc in ("a = [" * 2000, "x." * 5000 + "y = 1", '"' * 100_000, "[" + "a." * 5000 + "b]"):
            try:
                ct.loads(doc)
            except ValueError:
                pass
    finally:
        ct._tomllib = real
    assert time.perf_counter() - t < 5


@pytest.mark.parametrize("hostile", [
    "1" * 200_000, "1 " * 100_000, "a@" * 50_000, "+" + "12-" * 50_000, ("x" * 63 + "@") * 3000 + "ejemplo.org",
    "9." * 100_000, "eyJ" + "a" * 100_000,
], ids=[f"hostil{i}" for i in range(7)])   # ids cortos: pytest pone el id en una variable de entorno
def test_privacy_patterns_have_no_catastrophic_backtracking(hostile):
    t = time.perf_counter()
    redact(hostile)
    assert time.perf_counter() - t < 3, "posible retroceso catastrófico en una expresión regular"


def test_hostile_case_package_with_observation_evidence_is_rejected_or_safe(tmp_path):
    from eolfi.core.cases import CaseStore
    from eolfi.core.evidence import EvidenceStore

    store = EvidenceStore(tmp_path / "e.db")
    try:
        cases = CaseStore(store)
        rng = random.Random(SEED)
        for i in range(60):
            pkg = {"case_package_version": 2, "case": _random_json(rng), "evidence_package": _random_json(rng)}
            if i % 3 == 0:
                pkg["case"] = {"case_id": "00000000-0000-0000-0000-000000000000", "name": "x", "description": "",
                               "created_at": 0, "updated_at": 0, "artifacts": [], "records": [
                                   {"record_id": "r", "kind": "observation", "created_at": 0,
                                    "payload": {"flow": "observe", "status": "done", "evidence_ids": ["no-existe"]}}]}
            p = tmp_path / f"p{i}.json"
            p.write_text(json.dumps(pkg), encoding="utf-8")
            try:
                cases.import_case(p)
            except ValueError:
                pass
        assert all(c["records"] <= 1 for c in cases.list())
    finally:
        store.close()
