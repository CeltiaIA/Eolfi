"""Java (Fase E, grupo 2): archivos .class y JAR con la stdlib.

- .class: versión de Java, clase, superclase, interfaces, métodos y campos, clases y cadenas referenciadas
  (pool de constantes).
- JAR: MANIFEST.MF (Main-Class, Spring Boot, Created-By, módulo automático, multi-release), dependencias
  incrustadas (BOOT-INF/lib, WEB-INF/lib, lib/), paquetes y versiones de bytecode.
"""
from __future__ import annotations

import re
import zipfile
from collections import Counter
from typing import Any

from eolfi.providers.binfmt import ParseError, Reader

MAX_POOL = 65535
MAX_CLASSES_SAMPLED = 200
JAVA_VERSION = {45: "1.1", 46: "1.2", 47: "1.3", 48: "1.4", 49: "5", 50: "6", 51: "7", 52: "8"}


def java_version(major: int) -> str:
    return JAVA_VERSION.get(major, str(major - 44) if major > 52 else f"? ({major})")


def parse_class(data: bytes) -> dict[str, Any]:
    r = Reader(data, little=False)
    if r.u32(0) != 0xCAFEBABE:
        raise ParseError("sin firma de clase Java")
    minor, major = r.u16(4), r.u16(6)
    if major < 45:
        raise ParseError(f"versión de clase {major} inválida")
    count = r.u16(8)
    pool: list[Any] = [None] * count
    tags: list[int] = [0] * count
    p, i = 10, 1
    while i < count:
        tag = r.u8(p)
        tags[i] = tag
        if tag == 1:
            n = r.u16(p + 1)
            pool[i] = r.raw(p + 3, n).decode("utf-8", "replace")   # (UTF-8 modificado: suficiente para nombres)
            p += 3 + n
        elif tag in (3, 4):
            p += 5
        elif tag in (5, 6):
            p += 9
            i += 1   # ocupan dos entradas
        elif tag in (7, 8, 16, 19, 20):
            pool[i] = r.u16(p + 1)
            p += 3
        elif tag in (9, 10, 11, 12, 17, 18):
            pool[i] = (r.u16(p + 1), r.u16(p + 3))
            p += 5
        elif tag == 15:
            p += 4
        else:
            raise ParseError(f"etiqueta {tag} desconocida en el pool de constantes")
        i += 1

    def utf8(k: int) -> str:
        return pool[k] if 0 < k < count and tags[k] == 1 else ""

    def cls(k: int) -> str:
        return utf8(pool[k]).replace("/", ".") if 0 < k < count and tags[k] == 7 else ""

    access, this, sup = r.u16(p), r.u16(p + 2), r.u16(p + 4)
    n_if = r.u16(p + 6)
    interfaces = [cls(r.u16(p + 8 + 2 * k)) for k in range(min(n_if, 256))]
    p += 8 + 2 * n_if

    def members(q: int) -> tuple[list[str], int]:
        n = r.u16(q)
        q += 2
        names = []
        for _ in range(n):
            names.append(utf8(r.u16(q + 2)))
            attrs = r.u16(q + 6)
            q += 8
            for _a in range(attrs):
                q += 6 + r.u32(q + 2)
        return names, q

    fields, p = members(p)
    methods, p = members(p)
    referenced = sorted({cls(k) for k in range(1, count) if tags[k] == 7} - {cls(this), ""})
    strings = [utf8(pool[k])[:200] for k in range(1, count) if tags[k] == 8 and utf8(pool[k])]
    return {
        "java_version": java_version(major), "major": major, "minor": minor,
        "class": cls(this), "super": cls(sup) or None, "interfaces": interfaces,
        "access": {"public": bool(access & 1), "final": bool(access & 0x10), "interface": bool(access & 0x200),
                   "abstract": bool(access & 0x400), "enum": bool(access & 0x4000), "module": bool(access & 0x8000)},
        "fields": len(fields), "methods": len(methods), "method_names": methods[:200],
        "referenced_classes": referenced[:300], "strings": strings[:100],
    }


def parse_manifest(text: str) -> dict[str, str]:
    """MANIFEST.MF: líneas «Clave: valor» con continuación por un espacio inicial; solo la sección principal."""
    out: dict[str, str] = {}
    key = None
    for line in text.replace("\r\n", "\n").split("\n"):
        if not line.strip():
            break   # fin de la sección principal
        if line.startswith(" ") and key:
            out[key] += line[1:]
        elif ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()[:80]
            out[key] = value.strip()
        if len(out) > 200:
            break
    return out


def analyze_jar(zf: zipfile.ZipFile, names: list[str]) -> dict[str, Any]:
    man = {}
    if "META-INF/MANIFEST.MF" in names:
        info = zf.getinfo("META-INF/MANIFEST.MF")
        if info.file_size < 1024 * 1024:
            man = parse_manifest(zf.read(info).decode("utf-8", "replace"))
    classes = [n for n in names if n.endswith(".class") and not n.startswith("META-INF/versions/")]
    libs = [n.rsplit("/", 1)[-1] for n in names if re.match(r"^(?:BOOT-INF|WEB-INF)/lib/[^/]+\.jar$|^lib/[^/]+\.jar$", n)]
    versions: Counter = Counter()
    for n in classes[:MAX_CLASSES_SAMPLED]:
        try:
            with zf.open(n) as fh:
                head = fh.read(8)
            if head[:4] == b"\xca\xfe\xba\xbe":
                versions[java_version(int.from_bytes(head[6:8], "big"))] += 1
        except (zipfile.BadZipFile, RuntimeError, OSError):
            continue
    pkgs = Counter(n.rsplit("/", 1)[0].replace("BOOT-INF/classes/", "").replace("/", ".") for n in classes if "/" in n)
    spring = "Spring-Boot-Version" in man or any(n.startswith("BOOT-INF/") for n in names)
    deps = [re.sub(r"-\d[\w.+-]*\.jar$|\.jar$", "", lib) for lib in libs]
    return {
        "manifest": {k: man[k][:300] for k in list(man)[:60]},
        "main_class": man.get("Start-Class") or man.get("Main-Class"),
        "launcher": man.get("Main-Class") if man.get("Start-Class") else None,
        "spring_boot": {"version": man.get("Spring-Boot-Version"), "start_class": man.get("Start-Class")} if spring else None,
        "war": any(n.startswith("WEB-INF/") for n in names),
        "multi_release": man.get("Multi-Release", "").lower() == "true",
        "module": man.get("Automatic-Module-Name") or ("module-info" if "module-info.class" in names else None),
        "built_with": man.get("Created-By") or man.get("Build-Jdk-Spec") or man.get("Build-Jdk"),
        "classes": len(classes), "bytecode_versions": dict(versions.most_common()),
        "embedded_libraries": sorted(set(deps))[:300], "embedded_library_count": len(libs),
        "top_packages": [p for p, _ in pkgs.most_common(20)],
        "signed": any(n.startswith("META-INF/") and n.upper().endswith((".SF", ".RSA", ".DSA", ".EC")) for n in names),
    }
