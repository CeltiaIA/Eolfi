#!/usr/bin/env bash
# sigrok-cli 0.7.2 (Ubuntu) en el espacio del usuario de WSL, sin sudo, para decodificar grabaciones de señales con
# REA (decode_signal_recording / inspect_signal_decoders: solo en Linux y con prlimit de util-linux).
# Descarga los .deb de sigrok-cli y de las bibliotecas que falten, los desempaqueta y crea el lanzador
# ~/.local/eolfi-rea/sigrok/eolfi-sigrok (LD_LIBRARY_PATH y SIGROKDECODE_DIR). No toca hardware.
# Uso (dentro de Ubuntu/WSL): bash tools/instalar-sigrok-wsl.sh [carpeta destino]
set -euo pipefail
B="$HOME/.local/eolfi-rea"
R="${1:-$B/sigrok}"
D="$B/descargas/sigrok"
command -v prlimit >/dev/null || { echo "falta prlimit (util-linux)" >&2; exit 1; }
mkdir -p "$D" "$R"
cd "$D"
pkgs="sigrok-cli libsigrok4t64 libsigrokdecode4 libzip5 libserialport0 libftdi1-2 libusb-1.0-0 libhidapi-hidraw0 libieee1284-3t64 libbluetooth3"
need=""
for p in $pkgs; do
  if [ "$p" = sigrok-cli ] || ! dpkg -s "$p" >/dev/null 2>&1; then need="$need $p"; fi
done
# shellcheck disable=SC2086
apt-get download $need
sha256sum ./*.deb
for deb in ./*.deb; do dpkg -x "$deb" "$R"; done
L="$R/usr/lib/x86_64-linux-gnu"
cat > "$R/eolfi-sigrok" <<EOF
#!/usr/bin/env bash
# sigrok-cli 0.7.2 desempaquetado en el espacio del usuario (tools/instalar-sigrok-wsl.sh)
export LD_LIBRARY_PATH="$L\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
export SIGROKDECODE_DIR="$R/usr/share/libsigrokdecode/decoders"
exec "$R/usr/bin/sigrok-cli" "\$@"
EOF
chmod +x "$R/eolfi-sigrok"
"$R/eolfi-sigrok" --version | head -1
echo "decodificadores: $(ls "$R/usr/share/libsigrokdecode/decoders" | wc -l)"
echo "lanzador: $R/eolfi-sigrok"
