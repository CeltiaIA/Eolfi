#!/usr/bin/env bash
# Entorno de Eolfi para Codex web (chatgpt.com/codex) — 14/11/2026.
# Pégalo en «Setup script» del entorno de Codex para CeltiaIA/Eolfi. Instala lo mismo que la CI
# (.github/workflows/ci.yml) para que Codex pueda ejecutar las suites de AGENTS.md.
# Codex lee AGENTS.md por sí solo: ahí están las reglas (validar antes de afirmar, NO VERIFICADO, sin borrar…).
set -euo pipefail

python --version
node --version

# Eolfi y las mismas dependencias de desarrollo que usa la CI.
python -m pip install -e ".[dev]"
python -m eolfi navegador instalar

# Dependencias exactas del package-lock para las pruebas del panel.
(cd tests/e2e && npm ci --no-audit --no-fund)

# Comprueba el acceso al servidor local que requieren las cuatro suites.
python - <<'PY'
import socket

try:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with socket.create_connection(listener.getsockname(), timeout=2):
            pass
except OSError as exc:
    raise SystemExit(f"NO VERIFICADO: conexión de loopback bloqueada: {exc}") from None
PY

echo "Dependencias instaladas y loopback disponible."
echo 'Para el panel, usa el Chrome del runner o define EOLFI_E2E_BROWSER con la ruta de un navegador compatible.'
echo "Suites pendientes: python -m pytest -q · node --test (eolfi/bridge y eolfi/vscode-bridge) · npm test (tests/e2e)"
