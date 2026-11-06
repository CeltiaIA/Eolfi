"""Ejecuta UN proveedor local en un proceso aparte (Fase E).

    python -m eolfi.providers.isolated <módulo> <Clase> <archivo>

Escribe los hallazgos en JSON por la salida estándar. Si el archivo hostil agota la memoria o se cuelga,
cae este proceso, no el servidor. En Linux y macOS además se limita la memoria (RLIMIT_AS).
"""
from __future__ import annotations

import importlib
import json
import os
import sys

MEMORY_LIMIT = int(os.environ.get("EOLFI_ISOLATED_MEMORY", str(2 * 1024 ** 3)))   # 2 GB


def main(argv: list[str]) -> int:
    module, cls, target = argv
    if not module.startswith("eolfi.providers."):
        print(json.dumps({"error": "módulo no permitido"}))
        return 2
    if os.name != "nt":
        import resource

        try:
            resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT, MEMORY_LIMIT))
        except (ValueError, OSError):
            pass
    prov = getattr(importlib.import_module(module), cls)()
    from eolfi.providers.binfmt import parse_budget

    size = os.path.getsize(target)
    with parse_budget(max_bytes=64 * size + 256 * 1024 * 1024, seconds=float(os.environ.get("EOLFI_ISOLATED_SECONDS", "120"))):
        findings = prov.run(target)
    sys.stdout.write(json.dumps({"version": getattr(prov, "version", "?"), "findings": findings}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
