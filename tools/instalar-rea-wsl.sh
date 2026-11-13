#!/usr/bin/env bash
# REA en WSL2 para lo que solo funciona en Linux x64 (13/11/2026): recuperar fuentes JavaScript con Wakaru.
# Instala en el espacio del usuario (~/.local/eolfi-rea), sin sudo y sin tocar el sistema:
#   - Node.js v24.22.3 linux-x64 (nodejs.org, verificado con SHASUMS256.txt)
#   - rea-agents@6.8.0 (npm, misma versión que en Windows)
#   - Wakaru v1.14.0 linux-x64 (GitHub, verificado con su SHA-256 publicado; versión verificada por REA)
# Uso: wsl -e bash /mnt/d/Eolfi/tools/instalar-rea-wsl.sh
set -euo pipefail

BASE="$HOME/.local/eolfi-rea"
NODE_VERSION="v24.22.3"
NODE_DIR="node-$NODE_VERSION-linux-x64"
WAKARU_URL="https://github.com/pionxzh/wakaru/releases/download/v1.14.0/wakaru-linux-x64.tar.gz"
WAKARU_SHA256="db0e620034723195ab426e94d00d55dbd8fd0106a928ada2563f1103196d09fa"

mkdir -p "$BASE/descargas"
cd "$BASE/descargas"

if [ ! -x "$BASE/$NODE_DIR/bin/node" ]; then
  echo "== Node.js $NODE_VERSION"
  curl -fsSLO "https://nodejs.org/dist/$NODE_VERSION/$NODE_DIR.tar.xz"
  curl -fsSL "https://nodejs.org/dist/$NODE_VERSION/SHASUMS256.txt" -o SHASUMS256.txt
  grep " $NODE_DIR.tar.xz\$" SHASUMS256.txt | sha256sum -c -
  tar -xJf "$NODE_DIR.tar.xz" -C "$BASE"
fi
export PATH="$BASE/$NODE_DIR/bin:$PATH"
node --version

echo "== rea-agents@6.8.0"
npm install --prefix "$BASE/npm" --no-audit --no-fund rea-agents@6.8.0 >/dev/null
test -f "$BASE/npm/node_modules/rea-agents/scripts/rea.mjs"

if [ ! -x "$BASE/wakaru/wakaru" ]; then
  echo "== Wakaru 1.14.0"
  curl -fsSL "$WAKARU_URL" -o wakaru-linux-x64.tar.gz
  echo "$WAKARU_SHA256  wakaru-linux-x64.tar.gz" | sha256sum -c -
  mkdir -p "$BASE/wakaru"
  tar -xzf wakaru-linux-x64.tar.gz -C "$BASE/wakaru"
fi
WAKARU="$(find "$BASE/wakaru" -type f -name wakaru -perm -u+x | head -1)"
"$WAKARU" --version
command -v prlimit

echo "LISTO node=$BASE/$NODE_DIR/bin/node rea=$BASE/npm/node_modules/rea-agents/scripts/rea.mjs wakaru=$WAKARU"
