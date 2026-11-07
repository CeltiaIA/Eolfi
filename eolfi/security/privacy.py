"""Detección y ocultación de datos personales y secretos en los artefactos de observación y de prueba.

Se aplica a lo que Eolfi GUARDA como texto (vistas previas de stdout/stderr, cuerpos HTTP, texto visible, árbol de
accesibilidad, consola). Los hashes se calculan antes sobre los bytes reales, así que las comparaciones entre
ejecuciones no cambian. Cada valor se sustituye por ``<dato personal:TIPO #huella>``; la huella (12 hex de SHA-256)
permite ver que dos apariciones son el mismo valor sin revelarlo.

Detección por patrones con validación (Luhn, IBAN mod 97, letra de DNI/NIE): no es exhaustiva —nombres propios o
direcciones postales no se detectan— y así se declara.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

LIMITS = ("Detección por patrones: correo, teléfono, IBAN, tarjeta (Luhn), DNI/NIE (letra de control), IPv4 pública, "
          "JWT y claves con prefijo conocido. Nombres propios y direcciones postales no se detectan.")

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,24}\b")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?\b")
_CARD = re.compile(r"(?<![\w.-])(?:\d[ -]?){12,18}\d(?![\w.-])")   # sin guion pegado: no partir UUID
_DNI = re.compile(r"\b([XYZ]?)(\d{7,8})-?([A-Za-z])\b")
_PHONE = re.compile(r"(?<![\w.-])(?:\+\d{1,3}[ .-]?)?(?:\(?\d{2,4}\)?[ .-]?){2,4}\d{2,4}(?![\w.-])")
_IPV4 = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_KEY = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"
                  r"|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|xox[abpr]-[A-Za-z0-9-]{10,})\b")
_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def _card_ok(digits: str) -> bool:
    """Longitud de tarjeta, primer dígito de emisor real (2-6) y Luhn; descarta series repetidas (0000…)."""
    return 13 <= len(digits) <= 19 and digits[0] in "23456" and len(set(digits)) > 1 and _luhn(digits)


def _iban_ok(raw: str) -> bool:
    s = raw.replace(" ", "")
    if not 15 <= len(s) <= 34:
        return False
    rearranged = s[4:] + s[:4]
    try:
        return int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1
    except ValueError:
        return False


def _dni_ok(prefix: str, num: str, letter: str) -> bool:
    if prefix:
        if len(num) != 7:
            return False
        num = str("XYZ".index(prefix.upper())) + num
    elif len(num) != 8:
        return False
    return _DNI_LETTERS[int(num) % 23] == letter.upper()


def _public_ip(m: re.Match) -> bool:
    parts = [int(x) for x in m.groups()]
    if any(p > 255 for p in parts):
        return False
    a, b = parts[0], parts[1]
    private = a in (0, 10, 127) or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168) or (a == 169 and b == 254) \
        or a >= 224
    return not private


def _tag(kind: str, value: str) -> str:
    return f"<dato personal:{kind} #{hashlib.sha256(value.encode('utf-8', 'replace')).hexdigest()[:12]}>"


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Devuelve (texto con los datos ocultados, recuento por tipo)."""
    if not text:
        return text, {}
    found: dict[str, int] = {}

    def sub(pattern: re.Pattern, kind: str, check=None):
        nonlocal text

        def repl(m: re.Match) -> str:
            if check is not None and not check(m):
                return m.group(0)
            found[kind] = found.get(kind, 0) + 1
            return _tag(kind, m.group(0))
        text = pattern.sub(repl, text)

    # Orden: lo más específico primero (una tarjeta o un IBAN también parecerían un teléfono).
    sub(_KEY, "clave")
    sub(_JWT, "token")
    sub(_EMAIL, "correo")
    sub(_IBAN, "iban", lambda m: _iban_ok(m.group(0)))
    sub(_CARD, "tarjeta", lambda m: _card_ok(re.sub(r"\D", "", m.group(0))))
    sub(_DNI, "dni", lambda m: _dni_ok(*m.groups()))
    sub(_IPV4, "ip", _public_ip)
    sub(_PHONE, "telefono", lambda m: 9 <= len(re.sub(r"\D", "", m.group(0))) <= 15
        and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", m.group(0).strip()))
    return text, found


def merge(total: dict[str, int], more: dict[str, int]) -> dict[str, int]:
    for k, v in more.items():
        total[k] = total.get(k, 0) + v
    return total


_ID_KEYS = {"evidence_id", "subject", "incognita_id", "record_id", "case_id", "content_sha256", "sha256",
            "package_sha256", "params", "path", "out", "url", "provider", "provider_version", "operation", "identity",
            "evidence_for", "evidence_against", "links", "evidence_ids", "artifacts", "id"}


def redact_report(obj: Any, counts: dict[str, int] | None = None) -> Any:
    """Oculta datos personales en todo el texto de un informe salvo identificadores, huellas y rutas."""
    counts = {} if counts is None else counts
    if isinstance(obj, dict):
        return {k: (v if k in _ID_KEYS else redact_report(v, counts)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_report(v, counts) for v in obj]
    if isinstance(obj, str):
        text, found = redact(obj)
        merge(counts, found)
        return text
    return obj


def redact_tree(obj: Any, keys: set[str], counts: dict[str, int]) -> Any:
    """Oculta en las claves indicadas de una estructura JSON (p. ej. text_preview, preview, text)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in keys and isinstance(v, str):
                v, found = redact(v)
                merge(counts, found)
                out[k] = v
            else:
                out[k] = redact_tree(v, keys, counts)
        return out
    if isinstance(obj, list):
        return [redact_tree(v, keys, counts) for v in obj]
    return obj
