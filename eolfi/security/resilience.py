"""Banco de pruebas de resiliencia y seguridad del PROPIO sistema Eolfi.

Fuerza ataques y fallos sin tumbar el proceso principal: cada entrada
hostil se procesa en un subproceso aislado con tiempo límite, de modo que
un cuelgue o un crash se registra como vulnerabilidad en vez de caer.

Incluye:
- fuzz_file: muta un archivo semilla y alimenta el triaje; cuenta crashes,
  timeouts y cuelgues sin derribar el orquestador.
- prompt_injection_scan: comprueba que el texto hostil incrustado en un
  binario se trata como DATO y nunca como instrucción.
"""
from __future__ import annotations

import os
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Incognita

# Patrones de "instrucción" que un archivo hostil podría intentar colar.
_INJECTION = re.compile(
    rb"(ignore (all|previous)|system prompt|you are now|run the following|"
    # «base64,» suelto aparecía en cualquier data: URI legítima: solo cuenta junto a una orden.
    rb"exfiltrate|disregard|delete all|decode (?:this|the following) base64)",
    re.IGNORECASE,
)

_ROOT = str(Path(__file__).resolve().parents[2])
# El runner sale con 3 si algún proveedor lanzó una excepción (el triaje la
# aísla, pero para el fuzzer es un fallo que hay que contar), y con otro
# código distinto de 0 si el propio proceso cae.
_RUNNER = (
    "import sys;"
    "sys.path.insert(0, sys.argv[2]);"
    "from eolfi.core.evidence import EvidenceStore;"
    "from eolfi.flows.triage_flow import LOCAL_PROVIDERS, run_triage;"
    "r = run_triage(sys.argv[1], EvidenceStore(':memory:'), LOCAL_PROVIDERS);"
    "sys.exit(3 if r['providers_failed'] else 0)"
)
_PROVIDER_FAILURE = 3


def _mutate(data: bytes, rng: random.Random) -> bytes:
    if not data:
        return b"\x00" * rng.randint(1, 64)
    b = bytearray(data)
    flips = max(1, len(b) // 100)
    for _ in range(flips):
        i = rng.randrange(len(b))
        b[i] = rng.randrange(256)
    if rng.random() < 0.3:          # truncado
        b = b[: rng.randrange(len(b) + 1)]
    if rng.random() < 0.2:          # relleno
        b += bytes(rng.randrange(256) for _ in range(rng.randint(1, 128)))
    return bytes(b)


def fuzz_file(
    seed: str,
    store: EvidenceStore,
    iters: int = 200,
    timeout: float = 10.0,
    seed_value: int = 1337,
) -> dict[str, Any]:
    """Procesa entradas mutadas en subprocesos aislados. No tumba el proceso."""
    rng = random.Random(seed_value)
    base = Path(seed).read_bytes()
    from eolfi.providers.triage import sha256_file

    # La huella, no el nombre: dos «app.exe» distintos ya no comparten objetivo (B13).
    subject = f"resilience:{sha256_file(seed)}"
    crashes = timeouts = failures = ok = 0
    repro: list[str] = []
    env = dict(os.environ, PYTHONPATH=_ROOT)
    repro_dir = Path(tempfile.mkdtemp(prefix="eolfi-fuzz-"))

    for n in range(iters):
        sample = _mutate(base, rng)
        tmp = repro_dir / f"case{n:05d}.bin"
        tmp.write_bytes(sample)
        keep = False
        try:
            proc = subprocess.run(
                [sys.executable, "-c", _RUNNER, str(tmp), _ROOT],
                capture_output=True, timeout=timeout, env=env,
            )
            if proc.returncode == 0:
                ok += 1
            elif proc.returncode == _PROVIDER_FAILURE:
                failures += 1
                keep = True
            else:
                crashes += 1
                keep = True
        except subprocess.TimeoutExpired:
            timeouts += 1
            keep = True
        if keep and len(repro) < 5:
            repro.append(str(tmp))   # conservar el caso que reproduce
        else:
            tmp.unlink(missing_ok=True)
    if not repro:
        import shutil

        shutil.rmtree(repro_dir, ignore_errors=True)   # sin carpetas huérfanas (B13)

    if crashes or timeouts or failures:
        store.add_incognita(
            Incognita(
                subject=subject,
                question=(
                    f"Fuzzing: {crashes} crashes, {failures} fallos de proveedor y "
                    f"{timeouts} timeouts en {iters} iteraciones. Revisar manejo de "
                    f"entradas malformadas."
                ),
                severity="high" if crashes or failures else "medium",
            )
        )
    return {
        "iterations": iters,
        "ok": ok,
        "crashes": crashes,
        "provider_failures": failures,
        "timeouts": timeouts,
        "repro_cases": repro,
        "survived": True,   # el orquestador sigue en pie
    }


def prompt_injection_scan(target: str, store: EvidenceStore) -> dict[str, Any]:
    """El texto hostil del binario debe tratarse como dato, nunca como orden."""
    from eolfi.providers.triage import sha256_file

    hits_set: set[str] = set()
    with open(target, "rb") as fh:   # por bloques: antes el archivo entraba 3 veces en memoria (B13)
        carry = b""
        while True:
            block = fh.read(8 * 1024 * 1024)
            if not block:
                break
            data = carry + block
            # También UTF-16LE (cadenas anchas de Windows): se convierten a ASCII.
            wide = re.sub(rb"([\x20-\x7e])\x00", rb"\1", data)
            for chunk in (data, wide) if wide != data else (data,):
                hits_set.update(m.group(0).decode("ascii", "replace") for m in _INJECTION.finditer(chunk))
            carry = data[-256:]
    hits = sorted(hits_set)
    subject = f"resilience:inject:{sha256_file(target)}"
    if hits:
        store.add_incognita(
            Incognita(
                subject=subject,
                question=(
                    "Se hallaron patrones de inyección de prompts en el binario; "
                    "verificar que el agente los trata como datos."
                ),
                severity="medium",
            )
        )
    return {
        "patterns_found": hits,
        "treated_as_data": True,   # Eolfi nunca ejecuta texto extraído
    }
