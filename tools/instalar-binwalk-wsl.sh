#!/usr/bin/env bash
# Binwalk 3.1.0 en WSL2 para el análisis de firmware de REA (14/11/2026, autorizado por el titular: «instala los»).
# REA verifica Binwalk 3.1.x (commit auditado 4fdab3d464d97b68e0af9088df3f9e2e1545b21c) y no publica binarios: se
# compila desde ese commit. Todo en el espacio del usuario (~/.local/eolfi-rea), sin sudo y sin tocar el sistema:
#   - Rust estable (rustup-init oficial, verificado con su .sha256 publicado; perfil mínimo, sin tocar el PATH)
#   - Binwalk en el commit auditado, con su Cargo.lock (--locked)
# Ubuntu no trae las cabeceras de fontconfig (solo las usa el gráfico de entropía): se carga en tiempo de ejecución
# (RUST_FONTCONFIG_DLOPEN). xz y bzip2 se compilan desde las fuentes que incluyen sus crates.
# Uso: wsl -e bash /mnt/d/Eolfi/tools/instalar-binwalk-wsl.sh
set -euo pipefail

BASE="$HOME/.local/eolfi-rea"
COMMIT="4fdab3d464d97b68e0af9088df3f9e2e1545b21c"
DEST="$BASE/binwalk-3.1.0"
export RUSTUP_HOME="$BASE/rust/rustup" CARGO_HOME="$BASE/rust/cargo"
mkdir -p "$BASE/descargas"
cd "$BASE/descargas"

if [ ! -x "$CARGO_HOME/bin/cargo" ]; then
  echo "== Rust (rustup)"
  curl -fsSLO https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init
  curl -fsSL https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init.sha256 -o rustup-init.sha256
  echo "$(cut -d' ' -f1 rustup-init.sha256)  rustup-init" | sha256sum -c -
  chmod +x rustup-init
  ./rustup-init -y --no-modify-path --profile minimal --default-toolchain stable >/dev/null
fi
export PATH="$CARGO_HOME/bin:$PATH"
cargo --version

if [ ! -x "$DEST/bin/binwalk" ]; then
  echo "== Binwalk 3.1.0 ($COMMIT)"
  rm -rf "binwalk-$COMMIT"
  curl -fsSL "https://github.com/ReFirmLabs/binwalk/archive/$COMMIT.tar.gz" -o "binwalk-$COMMIT.tar.gz"
  tar -xzf "binwalk-$COMMIT.tar.gz"
  grep -q '^version = "3.1.0"' "binwalk-$COMMIT/Cargo.toml"
  # El enlazador por defecto de Rust es «cc», que esta Ubuntu no tiene: se usa gcc.
  CC=gcc CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=gcc RUST_FONTCONFIG_DLOPEN=on \
    cargo install --locked --root "$DEST" --path "binwalk-$COMMIT"
fi
"$DEST/bin/binwalk" --version
echo "REA_BINWALK_COMMAND=$DEST/bin/binwalk"
