"""``loads`` de TOML: ``tomllib`` en Python 3.11+; en 3.10, un lector propio del subconjunto que usan los
manifiestos (pyproject.toml, Cargo.toml, Pipfile): tablas, arrays de tablas, claves con puntos o comillas,
cadenas básicas/literales (también multilínea), enteros, decimales, booleanos, fechas como texto, arrays (también
multilínea) y tablas en línea. Lo que no entiende lo rechaza con ``ValueError`` (como tomllib.TOMLDecodeError)."""
from __future__ import annotations

import re
from typing import Any

try:  # pragma: no cover - depende de la versión
    import tomllib as _tomllib
except ModuleNotFoundError:  # Python 3.10
    _tomllib = None

TOMLDecodeError = getattr(_tomllib, "TOMLDecodeError", ValueError)


def loads(text: str) -> dict[str, Any]:
    if _tomllib is not None:
        return _tomllib.loads(text)
    return _Parser(text).parse()


_BARE = re.compile(r"[A-Za-z0-9_-]+")
_NUM = re.compile(r"[+-]?(0x[0-9A-Fa-f_]+|0o[0-7_]+|0b[01_]+|\d[\d_]*(\.\d[\d_]*)?([eE][+-]?\d+)?|inf|nan)")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}([Tt ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?([Zz]|[+-]\d{2}:\d{2})?|\d{2}:\d{2}:\d{2}(\.\d+)?")
_ESC = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", '"': '"', "\\": "\\"}


def _datetime(t: str) -> Any:
    import datetime as dt

    if ":" in t and "-" not in t[:5]:
        return dt.time.fromisoformat(t)
    if len(t) == 10:
        return dt.date.fromisoformat(t)
    t = t[:10] + "T" + t[11:]
    if t[-1] in "Zz":
        t = t[:-1] + "+00:00"
    return dt.datetime.fromisoformat(t)


class _Parser:
    def __init__(self, text: str):
        self.s, self.i = text.replace("\r\n", "\n"), 0

    def err(self, msg: str) -> ValueError:
        line = self.s.count("\n", 0, self.i) + 1
        return ValueError(f"TOML inválido (línea {line}): {msg}")

    def ws(self, newlines: bool = False) -> None:
        while self.i < len(self.s):
            c = self.s[self.i]
            if c in " \t" or (newlines and c == "\n"):
                self.i += 1
            elif c == "#":
                while self.i < len(self.s) and self.s[self.i] != "\n":
                    self.i += 1
            else:
                break

    def parse(self) -> dict[str, Any]:
        root: dict[str, Any] = {}
        cur = root
        while True:
            self.ws(newlines=True)
            if self.i >= len(self.s):
                return root
            if self.s.startswith("[[", self.i):
                self.i += 2
                keys = self.keys()
                self.expect("]]")
                parent = self.walk(root, keys[:-1])
                arr = parent.setdefault(keys[-1], [])
                if not isinstance(arr, list):
                    raise self.err("array de tablas sobre una clave existente")
                cur = {}
                arr.append(cur)
            elif self.s[self.i] == "[":
                self.i += 1
                keys = self.keys()
                self.expect("]")
                cur = self.walk(root, keys)
            else:
                keys = self.keys()
                self.expect("=")
                self.ws()
                tgt = self.walk(cur, keys[:-1])
                if keys[-1] in tgt:
                    raise self.err(f"clave repetida: {keys[-1]}")
                tgt[keys[-1]] = self.value()
            self.ws()
            if self.i < len(self.s) and self.s[self.i] != "\n":
                raise self.err("se esperaba fin de línea")

    def walk(self, d: dict[str, Any], keys: list[str]) -> dict[str, Any]:
        for k in keys:
            nxt = d.setdefault(k, {})
            if isinstance(nxt, list):
                nxt = nxt[-1]
            if not isinstance(nxt, dict):
                raise self.err(f"la clave {k} no es una tabla")
            d = nxt
        return d

    def expect(self, tok: str) -> None:
        self.ws()
        if not self.s.startswith(tok, self.i):
            raise self.err(f"se esperaba «{tok}»")
        self.i += len(tok)

    def keys(self) -> list[str]:
        out = []
        while True:
            self.ws()
            c = self.s[self.i:self.i + 1]
            if c in ('"', "'"):
                out.append(self.string())
            else:
                m = _BARE.match(self.s, self.i)
                if not m:
                    raise self.err("clave inválida")
                out.append(m.group(0))
                self.i = m.end()
            self.ws()
            if self.s[self.i:self.i + 1] != ".":
                return out
            self.i += 1

    def string(self) -> str:
        s = self.s
        for q, raw in (('"""', False), ("'''", True), ('"', False), ("'", True)):
            if s.startswith(q, self.i):
                self.i += len(q)
                multi = len(q) == 3
                if multi and s.startswith("\n", self.i):
                    self.i += 1
                buf = []
                while True:
                    if self.i >= len(s):
                        raise self.err("cadena sin cerrar")
                    if s.startswith(q, self.i):
                        self.i += len(q)
                        return "".join(buf)
                    c = s[self.i]
                    if c == "\n" and not multi:
                        raise self.err("salto de línea en cadena")
                    if c == "\\" and not raw:
                        n = s[self.i + 1:self.i + 2]
                        if multi and n == "\n":
                            self.i += 1
                            while self.i < len(s) and s[self.i] in " \t\n":
                                self.i += 1
                            continue
                        if n in _ESC:
                            buf.append(_ESC[n])
                            self.i += 2
                        elif n in ("u", "U"):
                            width = 4 if n == "u" else 8
                            buf.append(chr(int(s[self.i + 2:self.i + 2 + width], 16)))
                            self.i += 2 + width
                        else:
                            raise self.err("escape inválido")
                        continue
                    buf.append(c)
                    self.i += 1
        raise self.err("cadena esperada")

    def value(self) -> Any:
        s, c = self.s, self.s[self.i:self.i + 1]
        if c in ('"', "'"):
            return self.string()
        if c == "[":
            self.i += 1
            arr = []
            while True:
                self.ws(newlines=True)
                if s.startswith("]", self.i):
                    self.i += 1
                    return arr
                arr.append(self.value())
                self.ws(newlines=True)
                if s.startswith(",", self.i):
                    self.i += 1
                elif not s.startswith("]", self.i):
                    raise self.err("se esperaba «,» o «]»")
        if c == "{":
            self.i += 1
            tbl: dict[str, Any] = {}
            self.ws()
            if s.startswith("}", self.i):
                self.i += 1
                return tbl
            while True:
                keys = self.keys()
                self.expect("=")
                self.ws()
                self.walk(tbl, keys[:-1])[keys[-1]] = self.value()
                self.ws()
                if s.startswith("}", self.i):
                    self.i += 1
                    return tbl
                self.expect(",")
        for word, val in (("true", True), ("false", False)):
            if s.startswith(word, self.i):
                self.i += len(word)
                return val
        m = _DATE.match(s, self.i)
        if m and (len(m.group(0)) >= 8):
            self.i = m.end()
            return _datetime(m.group(0))
        m = _NUM.match(s, self.i)
        if m:
            self.i = m.end()
            t = m.group(0).replace("_", "")
            if t.lstrip("+-") in ("inf", "nan"):
                return float(t)
            if t[:2].lower() in ("0x", "0o", "0b") or t[1:3].lower() in ("0x", "0o", "0b"):
                return int(t, 0)
            return float(t) if any(x in t for x in ".eE") else int(t)
        raise self.err("valor no admitido")
