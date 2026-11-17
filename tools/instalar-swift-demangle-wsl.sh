#!/usr/bin/env bash
# swift-demangle oficial (Swift 6.4.2 para Ubuntu 26.04) en el espacio del usuario de WSL, sin sudo.
# REA solo ofrece demangle_swift en macOS; Eolfi usa este binario (rea_client.wsl_swift_demangle).
# El paquete completo (~1,1 GB) se lee en flujo: solo se guardan swift-demangle y sus bibliotecas, y la firma GPG
# se comprueba volviendo a leerlo, también sin guardarlo.
# Uso (dentro de Ubuntu/WSL): bash tools/instalar-swift-demangle-wsl.sh
set -euo pipefail
V=6.4.2
U="https://download.swift.org/swift-$V-release/ubuntu2604/swift-$V-RELEASE/swift-$V-RELEASE-ubuntu26.04.tar.gz"
B="$HOME/.local/eolfi-rea"
D="$B/swift-$V"
S="$B/descargas/swift"
mkdir -p "$D" "$S"
cd "$S"
curl -sfLO "$U.sig"
export GNUPGHOME="$(mktemp -d)"
trap 'rm -rf "$GNUPGHOME"' EXIT
curl -sfL https://www.swift.org/keys/all-keys.asc | gpg -q --import
# Primera lectura: firma GPG y SHA-256 de lo firmado.
curl -sfL "$U" | tee >(sha256sum > firmado.sha256) | gpg --verify "swift-$V-RELEASE-ubuntu26.04.tar.gz.sig" -
# Segunda lectura: se extrae y se calcula otra vez el SHA-256; si no coincide con lo firmado, se borra lo extraído.
curl -sfL "$U" | tee >(sha256sum > extraido.sha256) | tar xz -C "$D" --wildcards \
  "*/usr/bin/swift-demangle" "*/usr/lib/swift/linux/libswiftCore.so" "*/usr/lib/swift/linux/libswift_*" \
  "*/usr/lib/swift/linux/libFoundation*" "*/usr/lib/swift/linux/libdispatch.so" \
  "*/usr/lib/swift/linux/libBlocksRuntime.so" "*/usr/lib/libswiftDemangle*"
sleep 1   # las sustituciones de proceso de tee terminan de escribir el hash
if ! cmp -s firmado.sha256 extraido.sha256; then
  rm -rf "$D"
  echo "el paquete extraído no es el que se verificó con la firma; se ha borrado $D" >&2
  exit 1
fi
cut -d' ' -f1 firmado.sha256
X="$D/swift-$V-RELEASE-ubuntu26.04/usr/bin/swift-demangle"
echo '$s7Combine16ObservableObjectP' | "$X"
echo "swift-demangle en $X"
