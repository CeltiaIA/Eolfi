"""Genera un ELF64 little-endian mínimo pero estructuralmente válido.

Contiene PT_INTERP, PT_GNU_STACK (no ejecutable), PT_GNU_RELRO, PT_DYNAMIC,
secciones .interp/.dynstr/.dynsym/.dynamic/.shstrtab, DT_NEEDED libc.so.6,
DT_FLAGS_1 = NOW|PIE y símbolos importados __stack_chk_fail, puts y
__printf_chk. No es ejecutable: solo sirve para probar el parser.
"""
from __future__ import annotations

import struct


def _align(buf: bytearray, n: int = 8) -> None:
    while len(buf) % n:
        buf.append(0)


def build_elf64() -> bytes:
    body = bytearray(64 + 4 * 56)   # cabecera + 4 phdrs (se rellenan después)

    interp_off = len(body)
    interp = b"/lib64/ld-linux-x86-64.so.2\x00"
    body += interp
    _align(body)

    dynstr_off = len(body)
    dynstr = b"\x00libc.so.6\x00__stack_chk_fail\x00puts\x00__printf_chk\x00"
    body += dynstr
    _align(body)
    name_off = {n: dynstr.index(n.encode() + b"\x00") for n in ("libc.so.6", "__stack_chk_fail", "puts", "__printf_chk")}

    dynsym_off = len(body)
    body += b"\x00" * 24
    for n in ("__stack_chk_fail", "puts", "__printf_chk"):
        body += struct.pack("<IBBHQQ", name_off[n], 0x12, 0, 0, 0, 0)   # GLOBAL FUNC, UND
    dynsym_size = len(body) - dynsym_off

    dynamic_off = len(body)
    body += struct.pack("<qQ", 1, name_off["libc.so.6"])               # DT_NEEDED
    body += struct.pack("<qQ", 0x6FFFFFFB, 0x1 | 0x08000000)          # DT_FLAGS_1 NOW|PIE
    body += struct.pack("<qQ", 0, 0)                                    # DT_NULL
    dynamic_size = len(body) - dynamic_off

    shstr = b"\x00.interp\x00.dynstr\x00.dynsym\x00.dynamic\x00.shstrtab\x00"
    shstr_off = len(body)
    body += shstr
    _align(body)
    sn = {n: shstr.index(n.encode() + b"\x00") for n in (".interp", ".dynstr", ".dynsym", ".dynamic", ".shstrtab")}

    shoff = len(body)
    def sh(name, typ, flags, off, size, link=0, entsize=0):
        return struct.pack("<IIQQQQIIQQ", name, typ, flags, off, off, size, link, 0, 8, entsize)
    body += b"\x00" * 64
    body += sh(sn[".interp"], 1, 2, interp_off, len(interp))
    body += sh(sn[".dynstr"], 3, 2, dynstr_off, len(dynstr))
    body += sh(sn[".dynsym"], 11, 2, dynsym_off, dynsym_size, link=2, entsize=24)
    body += sh(sn[".dynamic"], 6, 3, dynamic_off, dynamic_size, link=2, entsize=16)
    body += sh(sn[".shstrtab"], 3, 0, shstr_off, len(shstr))

    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\x00" * 8
    ehdr = ident + struct.pack(
        "<HHIQQQIHHHHHH",
        3, 62, 1, 0x1040, 64, shoff, 0, 64, 56, 4, 64, 6, 5,
    )
    body[0:64] = ehdr

    def ph(typ, flags, off, size):
        return struct.pack("<IIQQQQQQ", typ, flags, off, off, off, size, size, 8)
    phdrs = (
        ph(3, 4, interp_off, len(interp))
        + ph(0x6474E551, 6, 0, 0)
        + ph(0x6474E552, 4, dynamic_off, dynamic_size)
        + ph(2, 6, dynamic_off, dynamic_size)
    )
    body[64:64 + len(phdrs)] = phdrs
    return bytes(body)
