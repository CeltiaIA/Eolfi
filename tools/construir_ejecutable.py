"""Construye el ejecutable de Eolfi con PyInstaller y lo verifica (C2 del plan).

PyInstaller no es dependencia de Eolfi: se usa el de un entorno propio (por defecto
``~/.eolfi/tools/pyinstaller``, o el de ``--pyinstaller`` o ``EOLFI_PYINSTALLER``). Sin red y sin tocar el repositorio:

1. Copia los archivos con seguimiento a una carpeta temporal y construye allí, en modo carpeta (``--onedir``), con
   todos los submódulos de ``eolfi`` (la CLI los importa bajo demanda) y sus datos (panel, scripts .mjs, puente).
   El punto de entrada es ``eolfi/_ejecutable.py``, que además acepta ``-m MÓDULO`` para los relanzamientos.
2. Deja el resultado en ``dist/eolfi-VERSIÓN-PLATAFORMA/`` (``dist/`` está ignorado por Git) con un ``SHA256SUMS.txt``
   del ejecutable. Si esa carpeta ya existe no la sustituye.
3. Verifica el ejecutable con un directorio personal temporal y sin red: ``--version``, ``update --check`` (modo
   ``ejecutable``), los archivos de datos del paquete, ``-m eolfi --version`` y el panel (``/api/health`` y ``/``).

En Windows, ``--certificado HUELLA`` firma el ejecutable con SignTool y comprueba Authenticode antes de distribuirlo.
Node.js y las dependencias del puente y de playwright-core siguen siendo externas;
``verify`` de proyectos Python necesita un Python del sistema (``python_base`` en ``eolfi/generador/verify.py``).
Uso: python tools/construir_ejecutable.py [--pyinstaller RUTA] [--salida CARPETA] [--conservar]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verificar_paquete as vp  # noqa: E402

LIMITES = ("Node.js, las dependencias del puente y playwright-core siguen siendo externas. "
           "«verify» de proyectos Python usa el Python del sistema.")


def pyinstaller_por_defecto() -> Path:
    if os.environ.get("EOLFI_PYINSTALLER"):
        return Path(os.environ["EOLFI_PYINSTALLER"])
    base = Path.home() / ".eolfi" / "tools" / "pyinstaller"
    return base / ("Scripts/pyinstaller.exe" if os.name == "nt" else "bin/pyinstaller")


def plataforma() -> str:
    sistema = {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}.get(platform.system(), platform.system())
    return f"{sistema}-{platform.machine().lower()}"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for bloque in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def opciones_paquete(fuente: Path, rutas: list[str]) -> list[str]:
    """Módulos y datos de ``eolfi`` en explícito, sacados de los archivos con seguimiento.

    ``--collect-submodules``/``--collect-data`` no ven el paquete desde la copia temporal (no está instalado en el
    entorno de PyInstaller) y además la CLI importa casi todo bajo demanda; por eso cada módulo va como
    ``--hidden-import`` y los datos, por carpeta y extensión, como ``--add-data``."""
    opciones: list[str] = []
    for rel in rutas:
        if rel.startswith("eolfi/") and rel.endswith(".py"):
            modulo = rel[:-3].replace("/", ".").removesuffix(".__init__")
            opciones += ["--hidden-import", modulo]
    grupos: set[tuple[str, str]] = set()
    for rel in vp.esperados(rutas, sin_py=True):
        carpeta, _, nombre = rel.rpartition("/")
        ext = Path(nombre).suffix
        grupos.add((carpeta, f"*{ext}" if ext else nombre))
    for carpeta, patron in sorted(grupos):
        opciones += ["--add-data", f"{fuente / carpeta / patron}{os.pathsep}{carpeta}"]
    return opciones


def construir(pyinstaller: Path, salida: Path, tmp: Path, certificado: str | None = None) -> dict:
    pasos: list[dict] = []
    version = vp.version_codigo()
    destino = salida / f"eolfi-{version}-{plataforma()}"
    out = {"schema": "eolfi.construir_ejecutable/v1", "version_codigo": version, "pyinstaller": str(pyinstaller),
           "destino": str(destino), "pasos": pasos, "firma": "no solicitada"}
    if certificado is not None:
        out["firma"] = "NO VERIFICADO"
        signtool = shutil.which("signtool.exe")
        if os.name != "nt" or not signtool or not re.fullmatch(r"[0-9A-Fa-f]{40}", certificado):
            out.update(ok=False, estado="NO VERIFICADO", motivo="La firma requiere Windows, SignTool y la huella del certificado (40 hex)")
            return out
    if not pyinstaller.is_file():
        out.update(ok=False, estado="NO VERIFICADO", motivo=f"no está PyInstaller en {pyinstaller}")
        return out
    if destino.exists():
        out.update(ok=False, estado="fallido", motivo=f"{destino} ya existe: no se sustituye (muévelo o bórralo antes)")
        return out

    fuente = tmp / "fuente"
    rutas = vp.copiar_fuente(fuente)
    p = vp.paso(pasos, "pyinstaller_version", [str(pyinstaller), "--version"])
    out["pyinstaller_version"] = p.stdout.strip()
    p = vp.paso(pasos, "pyinstaller", [
        str(pyinstaller), "--noconfirm", "--clean", "--onedir", "--console", "--name", "eolfi",
        "--paths", str(fuente), *opciones_paquete(fuente, rutas),
        "--distpath", str(tmp / "dist"), "--workpath", str(tmp / "build"), "--specpath", str(tmp),
        str(fuente / "eolfi" / "_ejecutable.py")], cwd=tmp, timeout=1800)
    construido = tmp / "dist" / "eolfi"
    if p.returncode or not construido.is_dir():
        return vp.cerrar(out, pasos, LIMITES)

    if certificado is not None:
        exe_temporal = str(construido / "eolfi.exe")
        for nombre, argumentos in (("firmar", ["sign", "/sha1", certificado, "/fd", "SHA256"]),
                                   ("verificar_firma", ["verify", "/pa", "/all"])):
            p = vp.paso(pasos, nombre, [signtool, *argumentos, exe_temporal], cwd=tmp, timeout=120)
            if p.returncode:
                return vp.cerrar(out, pasos, LIMITES)
        out["firma"] = "verificada"

    salida.mkdir(parents=True, exist_ok=True)
    shutil.move(str(construido), str(destino))
    exe = destino / ("eolfi.exe" if os.name == "nt" else "eolfi")
    huella = sha256(exe)
    (destino / "SHA256SUMS.txt").write_text(f"{huella}  {exe.name}\n", encoding="utf-8")
    out.update(ejecutable=str(exe), sha256=huella,
               megabytes=round(sum(f.stat().st_size for f in destino.rglob("*") if f.is_file()) / 2**20, 1))

    home, env = vp.entorno_aislado(tmp)
    vp.comprobar_version_y_modo(pasos, [str(exe)], home, env, version, "ejecutable")
    p = vp.paso(pasos, "relanzar_modulo", [str(exe), "-m", "eolfi", "--version"], cwd=home, env=env, timeout=120)
    vp.comprobacion(pasos, "relanzar_modulo_salida", p.stdout.strip() == f"eolfi {version}", salida=p.stdout.strip())

    # Los .py van compilados dentro del ejecutable; los datos (panel, .mjs, puente, scripts) deben estar en disco.
    internos = next((d for d in (destino / "_internal", destino) if (d / "eolfi").is_dir()), destino)
    presentes = {f.relative_to(internos).as_posix() for f in (internos / "eolfi").rglob("*") if f.is_file()}
    faltan = [r for r in vp.esperados(rutas, sin_py=True) if r not in presentes]
    vp.comprobacion(pasos, "archivos_datos", not faltan, esperados=len(vp.esperados(rutas, sin_py=True)),
                    faltan=faltan[:50])

    vp.comprobar_panel(pasos, [str(exe)], home, env, tmp)
    return vp.cerrar(out, pasos, LIMITES)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pyinstaller", type=Path, default=pyinstaller_por_defecto())
    ap.add_argument("--salida", type=Path, default=vp.RAIZ / "dist")
    ap.add_argument("--conservar", action="store_true", help="Conserva la carpeta temporal de construcción")
    ap.add_argument("--certificado", help="Huella del certificado de firma del almacén personal de Windows")
    args = ap.parse_args(argv)
    tmp = Path(tempfile.mkdtemp(prefix="eolfi-ejecutable-"))
    try:
        out = construir(args.pyinstaller, args.salida.resolve(), tmp, args.certificado)
    finally:
        if not args.conservar:
            shutil.rmtree(tmp, ignore_errors=True)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
