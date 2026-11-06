import random
import struct
import sys
from pathlib import Path

import pytest

from eolfi.providers.binfmt import BinaryFormatProvider, ParseError, parse_elf, parse_pe, shannon_entropy
from eolfi.providers.triage import detect_format
from eolfi.security.resilience import _mutate
from tests.elfgen import build_elf64


def _ops(findings):
    return {f["operation"]: f["result"] for f in findings}


def test_entropy_bounds():
    assert shannon_entropy(b"") == 0.0
    assert shannon_entropy(b"a" * 100) == 0.0
    assert abs(shannon_entropy(bytes(range(256))) - 8.0) < 1e-9


def test_elf_synthetic():
    info = parse_elf(build_elf64())
    h = info["headers"]
    assert (h["class"], h["machine"], h["type"]) == (64, "x86_64", "dyn")
    assert h["interpreter"] == "/lib64/ld-linux-x86-64.so.2"
    assert h["entry_point"] == 0x1040
    assert info["dynamic"]["needed"] == ["libc.so.6"]
    assert set(info["dynamic"]["imported_symbols"]) == {"__stack_chk_fail", "puts", "__printf_chk"}
    sec = info["security"]
    assert sec == {"nx": True, "pie": True, "relro": "full", "stack_canary": True,
                   "fortify": True, "stripped": True}
    assert [s["name"] for s in info["sections"]][1:] == [".interp", ".dynstr", ".dynsym", ".dynamic", ".shstrtab"]


def test_elf_provider_findings(tmp_path):
    f = tmp_path / "a.elf"
    f.write_bytes(build_elf64())
    ops = _ops(BinaryFormatProvider().run(str(f)))
    assert {"elf_headers", "elf_sections", "elf_security", "elf_dynamic", "entropy", "packing_signals"} <= set(ops)


@pytest.mark.skipif(sys.platform != "win32", reason="requiere un PE real del sistema")
def test_pe_real_python():
    data = Path(sys.executable).read_bytes()
    info = parse_pe(data)
    assert info["headers"]["machine"] in ("amd64", "i386", "arm64")
    assert info["headers"]["entry_section"] == ".text"
    assert any(d.lower().startswith("python3") for d in info["imports"]["dlls"])
    assert info["security"]["aslr"] and info["security"]["dep_nx"]


def _minimal_pe() -> bytes:
    """PE32+ mínimo: una sección .text, sin directorios."""
    buf = bytearray(0x400)
    buf[0:2] = b"MZ"
    struct.pack_into("<I", buf, 0x3C, 0x80)
    buf[0x80:0x84] = b"PE\x00\x00"
    struct.pack_into("<HHIIIHH", buf, 0x84, 0x8664, 1, 0, 0, 0, 240, 0x22)
    opt = 0x98
    struct.pack_into("<H", buf, opt, 0x20B)
    struct.pack_into("<I", buf, opt + 16, 0x1000)          # entry
    struct.pack_into("<Q", buf, opt + 24, 0x140000000)     # image base
    struct.pack_into("<I", buf, opt + 60, 0x200)           # SizeOfHeaders
    struct.pack_into("<HH", buf, opt + 68, 3, 0x0160)      # CUI, ASLR|HEVA|NX
    struct.pack_into("<I", buf, opt + 108, 16)
    sec = opt + 240
    buf[sec:sec + 8] = b".text\x00\x00\x00"
    struct.pack_into("<IIII", buf, sec + 8, 0x100, 0x1000, 0x200, 0x200)
    struct.pack_into("<I", buf, sec + 36, 0x60000020)
    return bytes(buf)


def test_pe_minimal():
    info = parse_pe(_minimal_pe())
    assert info["headers"]["machine"] == "amd64"
    assert info["headers"]["entry_section"] == ".text"
    assert info["headers"]["subsystem"] == "windows_cui"
    # DYNAMIC_BASE declarado pero sin .reloc: el cargador no puede reubicarlo, no hay ASLR efectivo (B16).
    assert info["security"]["aslr_flag"] and not info["security"]["aslr"]
    assert info["security"]["dep_nx"] and not info["security"]["cfg"]
    assert info["sections"][0]["flags"] == "rx"
    assert info["overlay_size"] == 0


def test_dos_only_is_parse_error():
    with pytest.raises(ParseError):
        parse_pe(b"MZ" + b"\x00" * 100)


@pytest.mark.parametrize("seed_fn", [build_elf64, _minimal_pe])
def test_parsers_never_crash_on_mutations(seed_fn):
    """Fuzzing en proceso: solo puede salir ParseError, nunca otra excepción."""
    rng = random.Random(7)
    seed = seed_fn()
    parser = parse_elf if seed.startswith(b"\x7fELF") else parse_pe
    for _ in range(400):
        data = _mutate(seed, rng)
        try:
            parser(data)
        except ParseError:
            pass


def test_magic_disambiguation():
    assert detect_format(b"\xca\xfe\xba\xbe\x00\x00\x00\x02")[0] == "macho_fat"
    assert detect_format(b"\xca\xfe\xba\xbe\x00\x00\x00\x34")[0] == "java_class"
    assert detect_format(b"MZ\x90\x00")[0] == "pe"
    assert detect_format(b"hola")[0] == "unknown"
