#!/usr/bin/env bash
# REA en WSL2 para lo que solo funciona en Linux x64 (13/11/2026): recuperar fuentes JavaScript con Wakaru.
# Instala en el espacio del usuario (~/.local/eolfi-rea), sin sudo y sin tocar el sistema:
#   - Node.js v24.22.3 linux-x64 (nodejs.org, verificado con SHASUMS256.txt)
#   - rea-agents@6.8.0 (npm, misma versión que en Windows)
#   - Wakaru v1.14.0 linux-x64 (GitHub, verificado con su SHA-256 publicado; versión verificada por REA)
#   - Kuna v1.833 linux-x86_64 (GitHub Noelo-Lab/kuna, Apache-2.0, verificado con su SHA-256 publicado; versión
#     verificada por rea-agents 6.8.0). REA solo admite Kuna en Linux y macOS: «eolfi rea explicar --motor kuna».
# Uso: wsl -e bash /mnt/d/Eolfi/tools/instalar-rea-wsl.sh
set -euo pipefail

BASE="$HOME/.local/eolfi-rea"
NODE_VERSION="v24.22.3"
NODE_DIR="node-$NODE_VERSION-linux-x64"
WAKARU_URL="https://github.com/pionxzh/wakaru/releases/download/v1.14.0/wakaru-linux-x64.tar.gz"
WAKARU_SHA256="db0e620034723195ab426e94d00d55dbd8fd0106a928ada2563f1103196d09fa"
KUNA_VERSION="1.833"
KUNA_URL="https://github.com/Noelo-Lab/kuna/releases/download/v$KUNA_VERSION/kuna-v$KUNA_VERSION-linux-x86_64.tar.gz"
KUNA_SHA256="e9f047fb5a93925ede6d869df22c26c1c0ced90764ace7467ae90f880625d530"

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

KUNA_DIR="$BASE/kuna-$KUNA_VERSION"
if [ ! -x "$KUNA_DIR/kuna-v$KUNA_VERSION-linux-x86_64/kuna" ]; then
  echo "== Kuna $KUNA_VERSION"
  curl -fsSL "$KUNA_URL" -o "kuna-v$KUNA_VERSION-linux-x86_64.tar.gz"
  echo "$KUNA_SHA256  kuna-v$KUNA_VERSION-linux-x86_64.tar.gz" | sha256sum -c -
  mkdir -p "$KUNA_DIR"
  tar -xzf "kuna-v$KUNA_VERSION-linux-x86_64.tar.gz" -C "$KUNA_DIR"
fi
ln -sfn "$KUNA_DIR/kuna-v$KUNA_VERSION-linux-x86_64/kuna" "$BASE/kuna"   # lo que Eolfi pasa como REA_KUNA_COMMAND
"$BASE/kuna" --version

echo "LISTO node=$BASE/$NODE_DIR/bin/node rea=$BASE/npm/node_modules/rea-agents/scripts/rea.mjs wakaru=$WAKARU kuna=$BASE/kuna"
