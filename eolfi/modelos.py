"""Identidad y auditoría GGUF local. Los metadatos nunca se ejecutan.

Una estructura válida y un hash conocido no descartan puertas traseras en los pesos.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
from pathlib import Path

SCHEMA = "eolfi.modelos.audit/v1"
SCALARS = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?",
           10: "Q", 11: "q", 12: "d"}
# GGML: elementos por bloque, bytes por bloque. Tipos no conocidos quedan pendientes.
BLOCKS = {0: (1, 4), 1: (1, 2), 2: (32, 18), 3: (32, 20), 6: (32, 22),
          7: (32, 24), 8: (32, 34),
          24: (1, 1), 25: (1, 2), 26: (1, 4), 27: (1, 8), 28: (1, 8), 30: (1, 2)}
PATTERN = re.compile(r"https?://[^\s\"'<>]+|\b(?:curl|wget|socket|subprocess|powershell|eval|exec)\b", re.I)
LIMIT = 256 * 1024 * 1024


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Reader:
    def __init__(self, stream):
        self.stream = stream
        self.items = 0

    def read(self, count):
        if count < 0 or self.stream.tell() + count > LIMIT:
            raise ValueError("Presupuesto de cabecera GGUF excedido")
        data = self.stream.read(count)
        if len(data) != count:
            raise ValueError("GGUF truncado")
        return data

    def number(self, fmt):
        return struct.unpack("<" + fmt, self.read(struct.calcsize("<" + fmt)))[0]

    def string(self):
        count = self.number("Q")
        if count > 16 * 1024 * 1024:
            raise ValueError("Cadena GGUF demasiado grande")
        return self.read(count).decode("utf-8", "strict")

    def value(self, kind, depth=0):
        self.items += 1
        if self.items > 4_000_000 or depth > 4:
            raise ValueError("Presupuesto de metadatos excedido")
        if kind == 8:
            return self.string()
        if kind == 9:
            subtype, count = self.number("I"), self.number("Q")
            if subtype == 9 or count > 2_000_000:
                raise ValueError("Array GGUF no admitido o demasiado grande")
            return [self.value(subtype, depth + 1) for _ in range(count)]
        if kind not in SCALARS:
            raise ValueError(f"Tipo de metadato desconocido: {kind}")
        return self.number(SCALARS[kind])


def audit(path):
    """Lectura acotada de estructura y hash completo, sin cargar el modelo."""
    path = Path(path).resolve()
    result = {"schema": SCHEMA, "archivo": str(path), "errores": [], "incognitas": [],
              "limites": ["No descarta puertas traseras en los pesos ni vulnerabilidades del motor",
                          "No observa conexiones; no ejecuta el modelo ni la plantilla"]}
    errors, unknown = result["errores"], result["incognitas"]
    try:
        before = path.stat()
        result["bytes"] = before.st_size
        with path.open("rb") as stream:
            reader = Reader(stream)
            if reader.read(4) != b"GGUF":
                raise ValueError("No es GGUF")
            version = reader.number("I")
            if version not in (2, 3):
                raise ValueError(f"Versión GGUF no admitida: {version}")
            nt, nk = reader.number("Q"), reader.number("Q")
            if nt > 200_000 or nk > 100_000:
                raise ValueError("Demasiados tensores o metadatos")
            metadata = {}
            findings = []
            for _ in range(nk):
                key = reader.string()
                if key in metadata:
                    raise ValueError(f"Clave duplicada: {key}")
                value = reader.value(reader.number("I"))
                metadata[key] = value
                # Tokens y reglas BPE son vocabulario: una palabra no es una orden.
                if key not in ("tokenizer.ggml.tokens", "tokenizer.ggml.merges"):
                    strings = [value] if isinstance(value, str) else value if isinstance(value, list) else []
                    for item in strings:
                        if isinstance(item, str):
                            for match in PATTERN.finditer(item):
                                if len(findings) < 100:
                                    findings.append({"clave": key, "cadena": match.group(0)[:200]})
                                elif "Hallazgos textuales truncados a 100" not in unknown:
                                    unknown.append("Hallazgos textuales truncados a 100")
            alignment = metadata.get("general.alignment", 32)
            if type(alignment) is not int or alignment < 1 or alignment > 4096 or alignment & (alignment - 1):
                raise ValueError("Alineación GGUF inválida")
            tensors, names, uncovered, tensor_types, declarations = [], set(), {}, {}, []
            for _ in range(nt):
                name, nd = reader.string(), reader.number("I")
                if name in names or not 1 <= nd <= 4:
                    raise ValueError("Tensor duplicado o dimensiones inválidas")
                names.add(name)
                dims = [reader.number("Q") for _ in range(nd)]
                declarations.append((name, dims))
                kind, offset = reader.number("I"), reader.number("Q")
                tensor_types[str(kind)] = tensor_types.get(str(kind), 0) + 1
                if not all(dims) or offset % alignment:
                    raise ValueError("Dimensiones vacías u offset sin alinear")
                if kind not in BLOCKS:
                    uncovered[str(kind)] = uncovered.get(str(kind), 0) + 1
                    tensors.append((offset, None, name))
                    continue
                elements, size = BLOCKS[kind]
                if dims[0] % elements:
                    raise ValueError(f"Bloque de cuantización incompleto: {name}")
                tensors.append((offset, math.prod(dims) // elements * size, name))
            base = (stream.tell() + alignment - 1) // alignment * alignment
            for kind, count in uncovered.items():
                unknown.append(f"Tipo de tensor con tamaño no establecido: {kind} ({count} tensores)")
            result["tipos_no_cubiertos"] = uncovered
            result["tipos_tensores"] = tensor_types
            result["tipo_archivo"] = metadata.get("general.file_type")
            result["division"] = {}
            for key in ("split.count", "split.no", "split.tensors.count"):
                if key in metadata:
                    value = metadata[key]
                    if type(value) is not int or value < 0 or (key == "split.count" and value == 0):
                        errors.append(f"Metadato de división inválido: {key}")
                    else:
                        result["division"][key] = value
            layout = hashlib.sha256()
            for declaration in sorted(declarations):
                layout.update(json.dumps(declaration, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                layout.update(b"\n")
            result["declaraciones_tensores_sha256"] = layout.hexdigest()
            result["cabecera_bytes"] = stream.tell()
            result["datos_offset"] = base
            end = base
            previous = 0
            for offset, length, name in sorted(tensors):
                if base + offset > before.st_size:
                    errors.append(f"Tensor fuera del archivo: {name}")
                if length is None:
                    continue
                if offset < previous:
                    errors.append(f"Tensores solapados: {name}")
                previous = offset + length
                end = max(end, base + previous)
            if end > before.st_size:
                errors.append("Datos de tensor truncados")
            if all(length is not None for _, length, _ in tensors):
                result["bytes_sobrantes"] = before.st_size - end
                if before.st_size > end:
                    errors.append("Bytes sobrantes tras los tensores")
            template = metadata.get("tokenizer.chat_template", "")
            if not isinstance(template, str):
                unknown.append("Plantilla de chat no textual")
                template = ""
            architecture = metadata.get("general.architecture")
            result.update(version=version, tensores=nt, claves=nk, arquitectura=architecture,
                          nombre=metadata.get("general.name"), cadenas_a_revisar=findings,
                          plantilla_sha256=hashlib.sha256(template.encode()).hexdigest(),
                          plantilla_bytes=len(template.encode()),
                          planificador={k: v for k, v in metadata.items() if isinstance(v, (int, float, str, bool))
                                        and k in {f"{architecture}.{s}" for s in
                                                  ("block_count", "context_length", "attention.sliding_window",
                                                   "embedding_length", "attention.head_count", "attention.head_count_kv")}})
        result["sha256"] = sha256(path)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            errors.append("El archivo cambió durante la auditoría")
    except (OSError, ValueError, UnicodeError, OverflowError) as exc:
        errors.append(str(exc))
    result["estado"] = "fallido" if errors else "NO VERIFICADO" if unknown else "estructura_verificada"
    return result


def check_trust(path, manifest):
    """Verifica todos los shards declarados; nunca añade confianza automáticamente."""
    data = json.loads(Path(manifest).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != "eolfi.modelos.confianza/v1" or not isinstance(data.get("modelos"), list):
        raise ValueError("Manifiesto de confianza inválido")
    path = Path(path).resolve()
    entries = data["modelos"]
    if any(not isinstance(x, dict) or not isinstance(x.get("archivo"), str)
           or not Path(x["archivo"]).is_absolute() for x in entries):
        raise ValueError("Cada modelo necesita una ruta absoluta")
    matches = [x for x in entries if Path(x["archivo"]).resolve() == path]
    if len(matches) > 1:
        raise ValueError("Modelo duplicado en el manifiesto")
    entry = matches[0] if matches else None
    if entry is None:
        raise ValueError(f"Modelo no autorizado en el manifiesto: {path}")
    # Los modelos divididos se autorizan juntos, con hash individual por parte.
    parts = entry.get("partes") or [{"archivo": str(path), "sha256": entry.get("sha256")}]
    if not isinstance(parts, list) or any(not isinstance(x, dict) or not isinstance(x.get("archivo"), str)
                                         or not Path(x["archivo"]).is_absolute() for x in parts):
        raise ValueError("Partes inválidas: se requieren rutas absolutas")
    if len({Path(x["archivo"]).resolve() for x in parts}) != len(parts):
        raise ValueError("Partes duplicadas en el manifiesto")
    if not any(Path(x["archivo"]).resolve() == path for x in parts):
        raise ValueError("El manifiesto no incluye el archivo principal")
    if re.search(r"-\d{5}-of-\d{5}\.gguf$", path.name, re.I):
        match = re.search(r"-(\d{5})-of-(\d{5})\.gguf$", path.name, re.I)
        total = int(match.group(2))
        expected = {path.with_name(path.name[:match.start()] + f"-{i:05d}-of-{total:05d}.gguf").resolve()
                    for i in range(1, total + 1)}
        if {Path(x["archivo"]).resolve() for x in parts} != expected:
            raise ValueError("Faltan partes del modelo dividido")
    for part in parts:
        expected = part.get("sha256", "")
        if not isinstance(expected, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", expected):
            raise ValueError("SHA-256 esperado inválido")
        if sha256(part["archivo"]) != expected.lower():
            raise ValueError(f"SHA-256 distinto: {part['archivo']}")
    return {"estado": "hash_autorizado", "archivo": str(path), "partes": len(parts),
            "limite": "La autorización del hash no demuestra seguridad de los pesos"}


def enforce_trust(path):
    manifest = os.environ.get("EOLFI_MODELOS_CONFIANZA")
    if manifest:
        return check_trust(path, manifest)
    return None
