"""WebAssembly (Fase E, grupo 2): secciones, importaciones y exportaciones, sección «name», «producers» y
la cadena de herramientas que lo generó (Emscripten, Rust/wasm-bindgen, Go, TinyGo, AssemblyScript, .NET…)."""
from __future__ import annotations

from collections import Counter
from typing import Any

from eolfi.providers.binfmt import ParseError, Reader

SECTION_NAMES = {0: "custom", 1: "type", 2: "import", 3: "function", 4: "table", 5: "memory", 6: "global",
                 7: "export", 8: "start", 9: "element", 10: "code", 11: "data", 12: "datacount", 13: "tag"}
KIND = {0: "function", 1: "table", 2: "memory", 3: "global", 4: "tag"}
MAX_ITEMS = 20_000
MAX_SECTIONS = 1000


class _W:
    def __init__(self, r: Reader, off: int, end: int):
        self.r, self.p, self.end = r, off, end

    def leb(self, signed: bool = False) -> int:
        result = shift = 0
        while True:
            if self.p >= self.end:
                raise ParseError("LEB128 truncado")
            b = self.r.u8(self.p)
            self.p += 1
            result |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                break
            if shift > 63:
                raise ParseError("LEB128 demasiado largo")
        if signed and b & 0x40:
            result -= 1 << shift
        return result

    def name(self) -> str:
        n = self.leb()
        if self.p + n > self.end:
            raise ParseError("nombre fuera de la sección")
        s = self.r.raw(self.p, min(n, 4096)).decode("utf-8", "replace")
        self.p += n
        return s

    def limits(self) -> dict[str, int | None]:
        flags = self.leb()
        lo = self.leb()
        hi = self.leb() if flags & 1 else None
        return {"min": lo, "max": hi, "shared": bool(flags & 2), "memory64": bool(flags & 4)}

    def skip_type(self) -> None:
        t = self.r.u8(self.p)
        self.p += 1
        if t in (0x63, 0x64):   # referencia con tipo (GC/funciones con tipo)
            self.leb(signed=True)


def parse_wasm(data) -> dict[str, Any]:
    r = Reader(data)
    if r.raw(0, 4) != b"\x00asm":
        raise ParseError("sin firma WebAssembly")
    version = r.u32(4)
    off, size = 8, r.size
    sections, imports, exports, customs = [], [], [], {}
    counts: dict[str, int] = {}
    memory: list[dict] = []
    start = None
    names: dict[str, Any] = {}
    producers: dict[str, list[str]] = {}
    features: list[str] = []
    while off < size and len(sections) < MAX_SECTIONS:
        sid = r.u8(off)
        w = _W(r, off + 1, size)
        length = w.leb()
        body, end = w.p, w.p + length
        if end > size:
            raise ParseError(f"sección {sid} fuera del archivo")
        s = _W(r, body, end)
        label = SECTION_NAMES.get(sid, f"desconocida({sid})")
        if sid == 0:
            cname = s.name()
            label = f"custom:{cname}"
            customs[cname] = end - s.p
            try:
                if cname == "name":
                    names = _names(s)
                elif cname == "producers":
                    producers = _producers(s)
                elif cname == "target_features":
                    for _ in range(min(s.leb(), 100)):
                        prefix = chr(r.u8(s.p))
                        s.p += 1
                        features.append(prefix + s.name())
            except ParseError:
                pass   # una sección personalizada rota no invalida el módulo
        elif sid == 2:
            for _ in range(min(s.leb(), MAX_ITEMS)):
                mod, nm = s.name(), s.name()
                kind = r.u8(s.p)
                s.p += 1
                if kind == 0:
                    s.leb()
                elif kind == 1:
                    s.skip_type()
                    s.limits()
                elif kind == 2:
                    memory.append({"imported": True, **s.limits()})
                elif kind == 3:
                    s.skip_type()
                    s.p += 1
                elif kind == 4:
                    s.p += 1
                    s.leb()
                imports.append({"module": mod, "name": nm, "kind": KIND.get(kind, str(kind))})
        elif sid == 5:
            for _ in range(min(s.leb(), 100)):
                memory.append({"imported": False, **s.limits()})
        elif sid == 7:
            for _ in range(min(s.leb(), MAX_ITEMS)):
                nm = s.name()
                kind = r.u8(s.p)
                s.p += 1
                exports.append({"name": nm, "kind": KIND.get(kind, str(kind)), "index": s.leb()})
        elif sid == 8:
            start = s.leb()
        elif sid in (1, 3, 6, 9, 10, 11, 12, 13):
            counts[label] = s.leb() if sid != 12 else s.leb()
        sections.append({"id": sid, "name": label, "size": length})
        off = end
    return {
        "version": version, "sections": sections, "counts": counts,
        "imports": imports[:2000], "import_count": len(imports),
        "import_modules": dict(Counter(i["module"] for i in imports).most_common(30)),
        "exports": exports[:2000], "export_count": len(exports),
        "memory": memory, "start_function": start, "custom_sections": customs,
        "names": names, "producers": producers, "target_features": features,
        "debug_info": any(k.startswith(".debug_") for k in customs),
        "source_map": "sourceMappingURL" in customs,
        "toolchain": _toolchain(imports, exports, producers, customs),
    }


def _names(s: _W) -> dict[str, Any]:
    out: dict[str, Any] = {}
    while s.p < s.end:
        sub = s.r.u8(s.p)
        s.p += 1
        n = s.leb()
        nxt = s.p + n
        if sub == 0:
            out["module"] = s.name()
        elif sub == 1:
            count = s.leb()
            out["function_names"] = count
            sample = []
            for _ in range(min(count, 50)):
                s.leb()
                sample.append(s.name())
            out["function_sample"] = sample
        s.p = nxt
    return out


def _producers(s: _W) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for _ in range(min(s.leb(), 20)):
        field = s.name()
        vals = []
        for _v in range(min(s.leb(), 50)):
            name, ver = s.name(), s.name()
            vals.append(f"{name} {ver}".strip())
        out[field] = vals
    return out


def _toolchain(imports, exports, producers, customs) -> list[str]:
    mods = {i["module"] for i in imports}
    imp = {f'{i["module"]}.{i["name"]}' for i in imports}
    exp = {e["name"] for e in exports}
    langs = " ".join(producers.get("language", []) + producers.get("processed-by", []) + producers.get("sdk", []))
    out = []
    if any(n.startswith(("env.emscripten_", "env.__syscall", "wasi_snapshot_preview1.")) for n in imp) or "Emscripten" in langs:
        out.append("Emscripten" if "Emscripten" in langs or any(".emscripten_" in n for n in imp) else "WASI")
    if any(i["module"] == "wbg" or i["name"].startswith("__wbindgen") for i in imports) or "wasm-bindgen" in langs:
        out.append("Rust + wasm-bindgen")
    elif "Rust" in langs or "rustc" in langs:
        out.append("Rust")
    if "go" in mods or "gojs" in mods:
        out.append("Go (GOOS=js)")
    if "TinyGo" in langs:
        out.append("TinyGo")
    if "env.abort" in imp and "__new" in exp or "AssemblyScript" in langs:
        out.append("AssemblyScript")
    if "mono_wasm_" in " ".join(exp) or "dotnet" in langs.lower():
        out.append(".NET (Blazor/Mono)")
    if not out and mods == {"a"} and imports and all(len(i["name"]) <= 2 for i in imports):
        out.append("Emscripten (minificado)")   # importaciones «a.a», «a.b»… típicas de emcc -O2/-O3
    if "clang" in langs and not out:
        out.append("C/C++ (clang)")
    return list(dict.fromkeys(out))
