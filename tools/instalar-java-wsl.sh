#!/usr/bin/env bash
# Java 21 (OpenJDK de Ubuntu) en el espacio del usuario de WSL, sin sudo, para el Ghidra del REA de WSL.
# El REA de Windows solo abre PE con Ghidra; para Mach-O (apps de Apple) y ELF se usa el de WSL con la misma
# instalación de Ghidra de Windows vista desde /mnt (trae el descompilador de Linux).
# Uso (dentro de Ubuntu/WSL): bash tools/instalar-java-wsl.sh
set -euo pipefail
B="$HOME/.local/eolfi-rea"
R="$B/jdk21"
D="$B/descargas/jdk"
mkdir -p "$D" "$R"
cd "$D"
apt-get download openjdk-21-jre-headless openjdk-21-jdk-headless
sha256sum ./*.deb
for deb in ./*.deb; do dpkg -x "$deb" "$R"; done
# Los paquetes enlazan su configuración (java.security, jvm.cfg…) a /etc, que no se instala: se apuntan a la copia.
cd "$R"
find usr -type l -lname "/etc/*" | while read -r l; do
  t="$(readlink "$l")"
  if [ -e "$R$t" ]; then ln -sfn "$R$t" "$l"; fi
done
J="$R/usr/lib/jvm/java-21-openjdk-amd64"
"$J/bin/java" -version
echo "Java 21 en $J"
