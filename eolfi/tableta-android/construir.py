"""Construye «Eolfi Tableta» (APK para Android 4.1, API 16, hasta Android 14) sin Android SDK ni Gradle.

Herramientas, todas ya instaladas en el equipo y localizables por variables de entorno:
- JDK (javac, jar, jarsigner, keytool): JAVA_HOME o PATH;
- D8 (dex) dentro del jar de jadx: EOLFI_D8_JAR, o ~/.eolfi/tools/jadx-headless-mcp-*-all.jar;
- aapt2 y los recursos del framework dentro de apktool: EOLFI_APKTOOL_JAR, o ~/.eolfi/tools/apktool/apktool_*.jar.

Pasos: stubs de la API 16 → javac (Java 8) → D8 (--min-api 16) → aapt2 link del manifiesto → classes.dex en el APK →
firma v1 (SHA-1, la única que entiende Android < 4.3) con una clave local de ~/.eolfi/tableta/ (nunca en el repo).

    python construir.py [--salida DIR] [--comprobar-api DIR_CON_core.odex_Y_framework.odex]

Escribe `construccion.json` con el SHA-256 de cada herramienta y del APK.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
PAQUETE = "com.celtiaia.eolfi.tableta"
VERSION = ("4", "0.4.0")
# minSdk 16: la Galaxy Tab 2 (Android 4.1). targetSdk 28: Android 14 no instala apps con targetSdk < 23 (Redmi,
# 20/11/2026); 28 evita el almacenamiento con ámbito (29+) y deja válida la firma v1 (la v2 se exige desde 30).
TARGET_SDK = 28


class ErrorConstruccion(RuntimeError):
    pass


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _jdk(nombre: str) -> str:
    home = os.environ.get("JAVA_HOME")
    for cand in ([Path(home) / "bin" / (nombre + (".exe" if os.name == "nt" else ""))] if home else []):
        if cand.is_file():
            return str(cand)
    w = shutil.which(nombre)
    if not w:
        raise ErrorConstruccion(f"no se encuentra {nombre} (instala un JDK 17+ o define JAVA_HOME)")
    return w


def _jar(variable: str, carpeta: Path, patron: str, contiene: str) -> Path:
    if os.environ.get(variable):
        p = Path(os.environ[variable])
        if not p.is_file():
            raise ErrorConstruccion(f"{variable} no apunta a un archivo: {p}")
        return p
    for p in sorted(carpeta.glob(patron), reverse=True):
        with zipfile.ZipFile(p) as z:
            if contiene in z.namelist():
                return p
    raise ErrorConstruccion(f"no se encuentra {patron} con {contiene} en {carpeta} (define {variable})")


def herramientas() -> dict[str, Path | str]:
    tools = Path.home() / ".eolfi" / "tools"
    return {"javac": _jdk("javac"), "java": _jdk("java"), "jarsigner": _jdk("jarsigner"), "keytool": _jdk("keytool"),
            "d8": _jar("EOLFI_D8_JAR", tools, "jadx-headless-mcp-*-all.jar", "com/android/tools/r8/D8.class"),
            "apktool": _jar("EOLFI_APKTOOL_JAR", tools / "apktool", "apktool_*.jar", "prebuilt/android-framework.jar")}


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, **kw)
    if r.returncode != 0:
        raise ErrorConstruccion(f"falló {Path(cmd[0]).name} ({r.returncode}):\n{(r.stdout + r.stderr)[-4000:]}")
    return r


def _aapt2(apktool: Path, destino: Path) -> tuple[Path, Path]:
    sub = {"nt": "windows", "posix": "macosx" if sys.platform == "darwin" else "linux"}[os.name]
    exe = destino / ("aapt2.exe" if os.name == "nt" else "aapt2")
    fw = destino / "android-framework.jar"
    destino.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(apktool) as z:
        for nombre, salida in ((f"prebuilt/{sub}/{exe.name}", exe), ("prebuilt/android-framework.jar", fw)):
            salida.write_bytes(z.read(nombre))
    if os.name != "nt":
        exe.chmod(0o755)
    return exe, fw


def _clave(keytool: str) -> tuple[Path, str]:
    """Clave de firma local (RSA 2048). Si se pierde, la tableta pedirá desinstalar antes de actualizar."""
    d = Path(os.environ.get("EOLFI_TABLETA_DIR") or Path.home() / ".eolfi" / "tableta")
    d.mkdir(parents=True, exist_ok=True)
    ks, pw = d / "firma.p12", d / "firma.clave"
    if not ks.is_file():
        clave = secrets.token_urlsafe(24)
        pw.write_text(clave, encoding="utf-8")
        _run([keytool, "-genkeypair", "-keystore", str(ks), "-storetype", "PKCS12", "-storepass", clave,
              "-alias", "eolfi", "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
              "-dname", "CN=Eolfi Tableta, O=CeltIA, C=ES"])
    return ks, pw.read_text(encoding="utf-8").strip()


MANIFIESTO = f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="{PAQUETE}"
    android:versionCode="{VERSION[0]}" android:versionName="{VERSION[1]}">
    <uses-sdk android:minSdkVersion="16" android:targetSdkVersion="{TARGET_SDK}" />
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.RECORD_AUDIO" />
    <uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE" />
    <application android:label="Eolfi Tableta" android:icon="@android:drawable/sym_def_app_icon"
        android:allowBackup="false" android:theme="@android:style/Theme.Holo">
        <activity android:name=".Principal" android:label="Eolfi Tableta"
            android:configChanges="orientation|screenSize|keyboardHidden"
            android:windowSoftInputMode="adjustResize">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
"""


def compilar_java(t: dict, salida: Path, fuentes: list[Path], extra_cp: list[Path] | None = None) -> Path:
    """Stubs + javac --release 8. Devuelve la carpeta de clases de la app."""
    sys.path.insert(0, str(AQUI / "stubs"))
    from generar_stubs import generar

    stubs_src, stubs_cls, cls = salida / "stubs-src", salida / "stubs-classes", salida / "classes"
    for d in (stubs_src, stubs_cls, cls):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    _run([t["javac"], "--release", "8", "-nowarn", "-d", str(stubs_cls), *map(str, generar(stubs_src))])
    cp = os.pathsep.join(map(str, [stubs_cls, *(extra_cp or [])]))
    _run([t["javac"], "--release", "8", "-Xlint:all,-options", "-Werror", "-encoding", "UTF-8", "-cp", cp,
          "-d", str(cls), *map(str, fuentes)])
    return cls


def comprobar_api(t: dict, cls: Path, odex_dir: Path) -> dict:
    """Cada clase y miembro de android.*, org.json, java.* y javax.* que usa la app debe aparecer en el framework
    de la tableta (core, framework y framework2.odex). Comprueba nombres (clase y miembro), no firmas completas."""
    datos = b"".join((odex_dir / n).read_bytes() for n in ("core.odex", "framework.odex", "framework2.odex"))

    def en_dex(s: str) -> bool:
        # string_data_item de dex: longitud ULEB128 (en unidades UTF-16; ASCII y < 128 → un byte), texto y NUL.
        b = s.encode("ascii")
        return len(b) < 128 and (bytes([len(b)]) + b + b"\x00") in datos

    r = _run([_jdk("javap"), "-c", "-p", *map(str, sorted(cls.rglob("*.class")))])
    pref = r"(?:android|org/json|java|javax)/[\w/$]+"
    refs = set(re.findall(rf"// (?:Method|Field|InterfaceMethod) ({pref})\.\"?([\w<>$]+)\"?:", r.stdout))
    refs |= {(c, "") for c in re.findall(rf"// class ({pref})", r.stdout)}
    faltan = sorted(f"{c}.{m}" for c, m in refs
                    if not en_dex(f"L{c};") or (m and m not in ("<init>", "<clinit>") and not en_dex(m)))
    return {"referencias": len(refs), "faltan": faltan, "ok": not faltan,
            "alcance": "nombres de clase y miembro en core, framework y framework2.odex; no firmas completas"}


def construir(salida: Path, odex_dir: Path | None = None) -> dict:
    t = herramientas()
    salida.mkdir(parents=True, exist_ok=True)
    fuentes = sorted((AQUI / "src").rglob("*.java"))
    cls = compilar_java(t, salida, fuentes)
    api = comprobar_api(t, cls, odex_dir) if odex_dir else None
    if api and not api["ok"]:
        raise ErrorConstruccion("la app usa API que no está en la tableta: " + ", ".join(api["faltan"][:20]))

    dex_dir = salida / "dex"
    shutil.rmtree(dex_dir, ignore_errors=True)
    dex_dir.mkdir()
    _run([t["java"], "-cp", str(t["d8"]), "com.android.tools.r8.D8", "--release", "--min-api", "16",
          "--lib", str(Path(t["javac"]).resolve().parent.parent), "--lib", str(salida / "stubs-classes"),
          "--output", str(dex_dir), *map(str, sorted(cls.rglob("*.class")))])

    aapt2, fw = _aapt2(Path(t["apktool"]), salida / "herramientas")
    man = salida / "AndroidManifest.xml"
    man.write_text(MANIFIESTO, encoding="utf-8")
    base = salida / "base.apk"
    _run([str(aapt2), "link", "--manifest", str(man), "-I", str(fw), "--min-sdk-version", "16",
          "--target-sdk-version", str(TARGET_SDK), "-o", str(base)])

    apk = salida / "eolfi-tableta.apk"
    sin_firmar = salida / "sin-firmar.apk"
    with zipfile.ZipFile(base) as zin, zipfile.ZipFile(sin_firmar, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            zout.writestr(info, zin.read(info.filename))
        zout.write(dex_dir / "classes.dex", "classes.dex")
    ks, clave = _clave(t["keytool"])
    firmar_v1(sin_firmar, apk, ks, clave)
    with zipfile.ZipFile(apk) as z:
        nombres = z.namelist()
        mf = z.read("META-INF/MANIFEST.MF").decode()
    if "classes.dex" not in nombres or "SHA1-Digest" not in mf or not any(n.endswith(".RSA") for n in nombres):
        raise ErrorConstruccion("el APK no quedó firmado con SHA-1 (necesario en Android 4.1)")
    informe = {"apk": str(apk), "sha256": sha256(apk), "bytes": apk.stat().st_size, "paquete": PAQUETE,
               "version": VERSION[1], "min_sdk": 16, "target_sdk": TARGET_SDK, "firma": "v1 SHA1withRSA", "huella_clave": _huella_cert(t, ks, clave),
               "herramientas": {k: {"ruta": str(v), "sha256": sha256(Path(v))} for k, v in t.items()
                                if k in ("d8", "apktool")} | {"aapt2": {"sha256": sha256(aapt2)},
                                                              "android-framework.jar": {"sha256": sha256(fw)}},
               "jdk": _run([t["javac"], "-version"]).stdout.strip() or "javac",
               "comprobacion_api": api}
    (salida / "construccion.json").write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    return informe


def _der(tag: int, cuerpo: bytes) -> bytes:
    n = len(cuerpo)
    largo = bytes([n]) if n < 128 else bytes([0x80 | ((n.bit_length() + 7) // 8)]) + n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([tag]) + largo + cuerpo


def _oid(texto: str) -> bytes:
    p = [int(x) for x in texto.split(".")]
    out = bytearray([40 * p[0] + p[1]])
    for v in p[2:]:
        trozo = [v & 0x7F]
        while v > 0x7F:
            v >>= 7
            trozo.insert(0, 0x80 | (v & 0x7F))
        out += bytes(trozo)
    return _der(0x06, bytes(out))


def _entero(v: int) -> bytes:
    return _der(0x02, v.to_bytes(v.bit_length() // 8 + 1, "big", signed=True))


def pkcs7_sha1(datos: bytes, key, cert) -> bytes:
    """PKCS#7 SignedData separado, SHA-1 + rsaEncryption, sin atributos firmados (formato de jarsigner antiguo)."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    seq, nulo = (lambda *xs: _der(0x30, b"".join(xs))), b"\x05\x00"
    sha1 = seq(_oid("1.3.14.3.2.26"), nulo)
    firma = key.sign(datos, padding.PKCS1v15(), hashes.SHA1())
    firmante = seq(_entero(1), seq(cert.issuer.public_bytes(), _entero(cert.serial_number)), sha1,
                   seq(_oid("1.2.840.113549.1.1.1"), nulo), _der(0x04, firma))
    signed = seq(_entero(1), _der(0x31, sha1), seq(_oid("1.2.840.113549.1.7.1")),
                 _der(0xA0, cert.public_bytes(serialization.Encoding.DER)), _der(0x31, firmante))
    return seq(_oid("1.2.840.113549.1.7.2"), _der(0xA0, signed))


def _seccion(nombre: str, digest: str) -> bytes:
    """Sección de manifiesto JAR; las líneas de más de 72 bytes siguen en otra que empieza por espacio."""
    linea = f"Name: {nombre}".encode()
    partes = [linea[:72]] + [b" " + linea[i:i + 71] for i in range(72, len(linea), 71)]
    return b"\r\n".join(partes) + f"\r\nSHA1-Digest: {digest}\r\n\r\n".encode()


def firmar_v1(entrada: Path, salida: Path, ks: Path, clave: str) -> None:
    """Firma JAR v1 al estilo de Android < 4.3: MANIFEST.MF y CERT.SF con SHA-1, y CERT.RSA como PKCS#7 separado
    SIN atributos firmados (el verificador de Harmony en 4.1 no los admite; el jarsigner del JDK 21 siempre los pone)."""
    import base64

    from cryptography.hazmat.primitives.serialization import pkcs12

    key, cert, _ = pkcs12.load_key_and_certificates(ks.read_bytes(), clave.encode())
    b64 = lambda d: base64.b64encode(d).decode()
    with zipfile.ZipFile(entrada) as zin:
        entradas = [(i, zin.read(i.filename)) for i in zin.infolist()
                    if not i.filename.startswith("META-INF/") and not i.is_dir()]
    secciones = [(i.filename, _seccion(i.filename, b64(hashlib.sha1(d).digest()))) for i, d in entradas]
    mf_cab = b"Manifest-Version: 1.0\r\nCreated-By: Eolfi\r\n\r\n"
    mf = mf_cab + b"".join(s for _n, s in secciones)
    sf = (b"Signature-Version: 1.0\r\nCreated-By: Eolfi\r\n"
          + f"SHA1-Digest-Manifest: {b64(hashlib.sha1(mf).digest())}\r\n"
            f"SHA1-Digest-Manifest-Main-Attributes: {b64(hashlib.sha1(mf_cab).digest())}\r\n\r\n".encode()
          + b"".join(_seccion(n, b64(hashlib.sha1(s).digest())) for n, s in secciones))
    rsa = pkcs7_sha1(sf, key, cert)
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as zout:
        for nombre, datos in (("META-INF/MANIFEST.MF", mf), ("META-INF/CERT.SF", sf), ("META-INF/CERT.RSA", rsa)):
            zout.writestr(nombre, datos)
        for info, datos in entradas:
            zout.writestr(info, datos)


def _huella_cert(t: dict, ks: Path, clave: str) -> str:
    r = _run([t["keytool"], "-list", "-v", "-keystore", str(ks), "-storetype", "PKCS12", "-storepass", clave,
              "-alias", "eolfi"])
    m = re.search(r"SHA256:\s*([0-9A-F:]+)", r.stdout)
    return m.group(1) if m else "?"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salida", default=str(AQUI / "build"))
    ap.add_argument("--comprobar-api", metavar="DIR", help="carpeta con core.odex, framework.odex y framework2.odex de la tableta")
    a = ap.parse_args()
    try:
        inf = construir(Path(a.salida), Path(a.comprobar_api) if a.comprobar_api else None)
    except ErrorConstruccion as exc:
        print(f"construir: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(inf, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
