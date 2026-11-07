"""Python 3.10 no trae tomllib: el lector propio (eolfi.compat_toml) debe dar lo mismo en los manifiestos que lee
Eolfi. Se compara con tomllib (disponible en 3.11+, donde corre esta comparación)."""
import sys
from pathlib import Path

import pytest

from eolfi.compat_toml import _Parser, loads

CARGO = r'''
# Cargo
[package]
name = "app"   # nombre
edition = "2021"
[dependencies]
serde = { version = "1", features = ["derive"] }
"tokio-x" = "1.2"
[workspace]
members = [
  "a",
  'b',
]
[[bin]]
name = "uno"
[[bin]]
name = "dos"
[tool.x.y]
n = 1_000
f = 3.5e2
h = 0xff
t = 1979-05-27T07:32:00Z
s = """
linea \
  junta"""
lit = 'C:\ruta'
esc = "tab\tu\u00e9"
ok = true
'''

PIPFILE = '[packages]\nrequests = "*"\n[dev-packages]\npytest = {version="*"}\n'


@pytest.mark.skipif(sys.version_info < (3, 11), reason="la referencia tomllib existe desde 3.11")
@pytest.mark.parametrize("doc", [Path("pyproject.toml").read_text(encoding="utf-8"), CARGO, PIPFILE])
def test_fallback_matches_tomllib(doc):
    import tomllib

    assert _Parser(doc).parse() == tomllib.loads(doc)


def test_fallback_values():
    d = _Parser(CARGO).parse()
    assert d["dependencies"]["serde"] == {"version": "1", "features": ["derive"]}
    assert [b["name"] for b in d["bin"]] == ["uno", "dos"]
    assert d["tool"]["x"]["y"]["s"] == "linea junta" and d["tool"]["x"]["y"]["lit"] == "C:\\ruta"
    assert loads(PIPFILE)["dev-packages"]["pytest"] == {"version": "*"}


@pytest.mark.parametrize("bad", ["a = ", "[a\nb=1", "a = 1\na = 2", 'a = "x'])
def test_fallback_rejects_invalid(bad):
    with pytest.raises(ValueError):
        _Parser(bad).parse()
