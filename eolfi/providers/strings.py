"""Extracción de cadenas ASCII (complemento barato al triaje)."""
from __future__ import annotations

import re
from typing import Any

from eolfi.providers.base import Provider

CHUNK = 8 * 1024 * 1024
MAX_CARRY = 64 * 1024
MAX_SAMPLE_STR = 400            # cada cadena de la muestra, como mucho (M14)
MAX_SAMPLE_BYTES = 256 * 1024   # y la muestra entera


class StringsProvider(Provider):
    name = "eolfi.strings"
    version = "0.1.0"

    def __init__(self, min_len: int = 5, limit: int = 500):
        self.min_len = min_len
        self.limit = limit
        self._rx = re.compile(rb"[\x20-\x7e]{%d,}" % min_len)

    def available(self) -> bool:
        return True

    def run(self, target: str) -> list[dict[str, Any]]:
        # Por bloques y sin guardar todas las cadenas: un binario de varios GB no agota la memoria.
        count, sample, carry = 0, [], b""
        used, truncated = 0, 0

        def keep(raw: bytes) -> None:
            nonlocal used, truncated
            if len(sample) >= self.limit or used >= MAX_SAMPLE_BYTES:
                return
            text = raw[:MAX_SAMPLE_STR].decode("ascii")
            if len(raw) > MAX_SAMPLE_STR:
                truncated += 1
                text += "…"
            sample.append(text)
            used += len(text)
        with open(target, "rb") as fh:
            while True:
                block = fh.read(CHUNK)
                if not block:
                    break
                data = carry + block
                last_end = 0
                for m in self._rx.finditer(data):
                    if m.end() == len(data):       # puede continuar en el siguiente bloque
                        break
                    count += 1
                    keep(m.group())
                    last_end = m.end()
                tail = data[last_end:]
                # Conservar el posible principio de una cadena cortada por el bloque.
                k = len(tail)
                while k > 0 and 0x20 <= tail[k - 1] <= 0x7E:
                    k -= 1
                carry = tail[k:][-MAX_CARRY:]
        if len(carry) >= self.min_len:
            count += 1
            keep(carry)
        return [
            {
                "operation": "strings_ascii",
                "result": {"count": count, "sample": sample, "truncated_strings": truncated},
                "authority": "distributed_artifact",
                "confidence": "high",
                "limitations": (
                    "Solo ASCII; no recupera cadenas ofuscadas o construidas "
                    "en runtime (para eso, un proveedor tipo FLOSS)."
                ),
            }
        ]
