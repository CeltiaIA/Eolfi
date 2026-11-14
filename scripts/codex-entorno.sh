#!/usr/bin/env bash
# Entorno de Eolfi para Codex web (chatgpt.com/codex) — 14/11/2026.
# Pégalo en «Setup script» del entorno de Codex para CeltiaIA/Eolfi. Instala lo mismo que la CI
# (.github/workflows/ci.yml) para que Codex pueda ejecutar las suites de AGENTS.md.
# Codex lee AGENTS.md por sí solo: ahí están las reglas (validar antes de afirmar, NO VERIFICADO, sin borrar…).
set -euo pipefail

python --version
node --version

# Eolfi y sus dependencias de desarrollo (pytest, ruff…).
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

# Pruebas de navegador: dependencias exactas del package-lock. Necesitan un Chrome/Chromium; si el contenedor de
# Codex no lo trae, esa suite quedará NO VERIFICADO (las otras tres sí corren).
(cd tests/e2e && npm ci --no-audit --no-fund) || echo "AVISO: tests/e2e sin dependencias: suite de navegador NO VERIFICADO"

echo "Entorno listo. Suites: python -m pytest -q · node --test (eolfi/bridge y eolfi/vscode-bridge) · npm test (tests/e2e)"
