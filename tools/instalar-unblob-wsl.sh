#!/usr/bin/env bash
# Unblob 26.6.4 en WSL2 para la extracción de firmware de REA (14/11/2026, autorizado por el titular: «si instala
# unblob»). REA verifica Unblob 26.6.x con 26.6.4 y lo busca en REA_UNBLOB_COMMAND. Todo en el espacio del usuario
# (~/.local/eolfi-rea), sin sudo y sin tocar el sistema:
#   - entorno virtual de Python con unblob==26.6.4 de PyPI (trae jefferson y ubi_reader)
#   - extractores externos de los paquetes oficiales de Ubuntu, desempaquetados con «apt-get download» + «dpkg -x»
#     (sin instalarlos en el sistema) junto con las librerías que les faltan
#   - sasquatch (squashfs) del .deb de onekey-sec, verificado con el SHA-256 que publica GitHub
#   - un lanzador (eolfi-unblob) que pone esos extractores y librerías en PATH/LD_LIBRARY_PATH y llama a unblob
# Uso: wsl -e bash /mnt/d/Eolfi/tools/instalar-unblob-wsl.sh
set -euo pipefail

BASE="$HOME/.local/eolfi-rea"
DEST="$BASE/unblob-26.6.4"
X="$BASE/extractores"
SASQ_URL="https://github.com/onekey-sec/sasquatch/releases/download/sasquatch-v4.5.1-6/sasquatch_1.0_amd64.deb"
SASQ_SHA="efbc92bd27594e01211e1b582f105a463a0017360a0746a93de3f283906ade95"

if [ ! -x "$DEST/bin/unblob" ]; then
  echo "== Unblob 26.6.4 (PyPI) en $DEST"
  rm -rf "$DEST"
  python3 -m venv "$DEST"
  "$DEST/bin/python" -m pip install --quiet --disable-pip-version-check "unblob==26.6.4"
fi

echo "== Extractores de Ubuntu en $X (sin instalar en el sistema)"
mkdir -p "$X/debs" "$X/raiz"
cd "$X/debs"
apt-get download 7zip zstd lz4 lzop lziprecover unar erofs-utils android-sdk-libsparse-utils partclone \
  libgnustep-base1.31 libwavpack1 libicu78 libobjc4 android-libbase android-liblog android-libsparse libisal2 \
  >/dev/null
if [ ! -f sasquatch_1.0_amd64.deb ]; then
  curl -fsSL -o sasquatch_1.0_amd64.deb "$SASQ_URL"
fi
echo "$SASQ_SHA  sasquatch_1.0_amd64.deb" | sha256sum -c -
for d in ./*.deb; do dpkg -x "$d" "$X/raiz"; done
# Los guiones de /usr/bin que llaman a otros programas por ruta absoluta (p. ej. 7z → /usr/lib/7zip/7z) se
# reescriben para que usen la copia desempaquetada.
grep -lI "/usr/lib/" "$X/raiz/usr/bin/"* 2>/dev/null | while read -r f; do
  sed -i "s#\([\"' ]\)/usr/lib/#\1$X/raiz/usr/lib/#g" "$f"
done

LIBS=$(find "$X/raiz" -name "*.so*" -printf "%h\n" | sort -u | tr "\n" ":")
cat > "$DEST/eolfi-unblob" <<LANZADOR
#!/usr/bin/env bash
# Generado por tools/instalar-unblob-wsl.sh: Unblob con los extractores de $X.
export PATH="$X/raiz/usr/bin:$X/raiz/usr/sbin:$DEST/bin:\$PATH"
export LD_LIBRARY_PATH="$LIBS\${LD_LIBRARY_PATH:-}"
exec "$DEST/bin/unblob" "\$@"
LANZADOR
chmod +x "$DEST/eolfi-unblob"

"$DEST/eolfi-unblob" --version
"$DEST/eolfi-unblob" --show-external-dependencies
echo "REA_UNBLOB_COMMAND=$DEST/eolfi-unblob"
