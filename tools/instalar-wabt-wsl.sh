#!/usr/bin/env bash
# Instala WABT 1.0.42 dentro de Ubuntu (WSL) para el REA de WSL, en ~/.local/eolfi-rea/wabt-1.0.42.
#
#   wsl -e bash tools/instalar-wabt-wsl.sh
#
# Paquete oficial de https://github.com/WebAssembly/wabt/releases/tag/1.0.42, instalado SOLO si su SHA-256 coincide con
# el publicado. El REA de Windows usa tools/instalar-wabt.ps1; este es para cuando el análisis vaya por WSL.
set -euo pipefail
VERSION=1.0.42
NAME="wabt-$VERSION-linux-x64.tar.gz"
SHA256=84895407a6bbb80e918f33b16b2fb2206021c150b6bc9ff6f761263a745ab131
BASE="$HOME/.local/eolfi-rea"
DEST="$BASE/wabt-$VERSION"

if [ -e "$DEST" ]; then
  echo "WABT $VERSION ya está instalado en $DEST"
else
  TMP=$(mktemp -d)
  trap 'rm -rf "$TMP"' EXIT
  curl -fsSL -o "$TMP/$NAME" "https://github.com/WebAssembly/wabt/releases/download/$VERSION/$NAME"
  echo "$SHA256  $TMP/$NAME" | sha256sum -c -
  mkdir -p "$BASE"
  tar -xzf "$TMP/$NAME" -C "$TMP"
  mv "$TMP/wabt-$VERSION" "$DEST"
fi
for t in wasm-validate wasm-objdump wasm2wat; do
  v=$("$DEST/bin/$t" --version)
  [ "$v" = "$VERSION" ] || { echo "$t informa la versión «$v», no $VERSION" >&2; exit 1; }
  echo "$t $v"
done
