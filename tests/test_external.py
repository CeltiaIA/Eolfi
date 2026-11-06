"""Adaptadores externos probados con ejecutables falsos en el PATH."""
import json
import os
import sys

import pytest

from eolfi.providers.external import CapaProvider, RizinProvider, parse_capa_json

CAPA_DOC = {
    "meta": {"analysis": {"format": "pe", "arch": "amd64", "os": "windows"}},
    "rules": {
        "create process on Windows": {"meta": {
            "namespace": "host-interaction/process/create",
            "attack": [{"parts": ["Execution", "System Services"], "id": "T1569"}],
            "mbc": [{"parts": ["Process", "Create Process"], "id": "C0017"}],
        }},
        "contain loop": {"meta": {"namespace": "internal", "lib": True}},
        "encode data using XOR": {"meta": {"namespace": "data-manipulation/encoding/xor",
                                           "attack": ["Defense Evasion::Obfuscated Files [T1027]"]}},
    },
}


def test_parse_capa():
    r = parse_capa_json(CAPA_DOC)
    assert r["rules"] == ["create process on Windows", "encode data using XOR"]
    assert "Execution::System Services [T1569]" in r["attack"]
    assert "Defense Evasion::Obfuscated Files [T1027]" in r["attack"]
    assert r["mbc"] == ["Process::Create Process [C0017]"]
    assert r["format"] == "pe"


def _fake_tool(tmp_path, name, script_body):
    script = tmp_path / f"{name}_impl.py"
    script.write_text(script_body, encoding="utf-8")
    if os.name == "nt":
        (tmp_path / f"{name}.cmd").write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        exe = tmp_path / name
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        exe.chmod(0o755)


@pytest.fixture
def fake_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    return tmp_path


def test_capa_adapter(fake_path, tmp_path):
    _fake_tool(fake_path, "capa", f"""
import sys, json
if "--version" in sys.argv: print("capa 9.9.9"); sys.exit(0)
print("WARNING: aviso previo")
print({json.dumps(json.dumps(CAPA_DOC))})
""")
    target = tmp_path / "t.bin"
    target.write_bytes(b"MZ")
    p = CapaProvider()
    assert p.available()
    [f] = p.run(str(target))
    assert f["result"]["rules"][0] == "create process on Windows"
    assert p.version == "capa 9.9.9"


def test_capa_failure_is_low_confidence(fake_path, tmp_path):
    _fake_tool(fake_path, "capa", "import sys; sys.stderr.write('unsupported'); sys.exit(14)")
    target = tmp_path / "t.bin"
    target.write_bytes(b"x")
    [f] = CapaProvider().run(str(target))
    assert f["confidence"] == "low" and "unsupported" in f["result"]["error"]


def test_rizin_adapter(fake_path, tmp_path):
    funcs = [{"name": "main", "offset": 4096, "size": 120, "nbbs": 5, "cc": 3},
             {"name": "sym.big", "offset": 8192, "size": 900, "nbbs": 40, "cc": 12}]
    info = {"bin": {"arch": "x86", "bits": 64, "os": "linux", "nx": True, "canary": False}}
    _fake_tool(fake_path, "rizin", f"""
import sys, json
args = " ".join(sys.argv)
if "-v" in sys.argv: print("rizin 0.7.0"); sys.exit(0)
if "aflj" in args: print({json.dumps(json.dumps(funcs))})
else: print({json.dumps(json.dumps(info))})
""")
    target = tmp_path / "t.bin"
    target.write_bytes(b"\x7fELF")
    ops = {f["operation"]: f["result"] for f in RizinProvider().run(str(target))}
    assert ops["rizin_info"] == {"arch": "x86", "bits": 64, "os": "linux", "nx": True, "canary": False}
    assert ops["rizin_functions"]["count"] == 2
    assert ops["rizin_functions"]["functions"][0]["name"] == "sym.big"   # ordenado por tamaño
