"""Captura HTTP SINTÉTICA para probar «de captura de red a API» (13/11/2026). No contiene tráfico real de nadie:
una API de ejemplo inventada (api.ejemplo.test) con peticiones y respuestas JSON, en formato pcap clásico."""
from __future__ import annotations

import json
import struct
from pathlib import Path

CLIENT, SERVER = bytes([10, 0, 0, 2]), bytes([10, 0, 0, 1])
EXCHANGES = [
    ("GET", "/api/v1/productos?pagina=1&limite=20", None, 200,
     [{"id": 1, "nombre": "Mesa", "precio": 120.5}, {"id": 2, "nombre": "Silla", "precio": 45.0}]),
    ("GET", "/api/v1/productos/1", None, 200, {"id": 1, "nombre": "Mesa", "precio": 120.5, "stock": 7}),
    ("POST", "/api/v1/productos", {"nombre": "Lámpara", "precio": 30.0}, 201, {"id": 3, "nombre": "Lámpara", "precio": 30.0}),
    ("GET", "/api/v1/productos/99", None, 404, {"error": "no existe"}),
    ("DELETE", "/api/v1/productos/2", None, 204, None),
    ("POST", "/api/v1/sesion", {"usuario": "demo", "clave": "xxxx"}, 200, {"token": "tkn-de-prueba", "caduca": 3600}),
]


def _checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\0"
    s = sum(struct.unpack(f"!{len(data) // 2}H", data))
    s = (s >> 16) + (s & 0xFFFF)
    s += s >> 16
    return ~s & 0xFFFF


def _packet(src: bytes, dst: bytes, sport: int, dport: int, seq: int, ack: int, payload: bytes) -> bytes:
    tcp = struct.pack("!HHIIBBHHH", sport, dport, seq, ack, 5 << 4, 0x18, 65535, 0, 0) + payload
    pseudo = src + dst + struct.pack("!BBH", 0, 6, len(tcp))
    tcp = tcp[:16] + struct.pack("!H", _checksum(pseudo + tcp)) + tcp[18:]
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), 1, 0, 64, 6, 0, src, dst)
    ip = ip[:10] + struct.pack("!H", _checksum(ip)) + ip[12:]
    eth = b"\x02\x00\x00\x00\x00\x02" + b"\x02\x00\x00\x00\x00\x01" + b"\x08\x00"
    return eth + ip + tcp


def write(path: str | Path) -> Path:
    path = Path(path)
    out = [struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)]
    t = 1_763_000_000
    for i, (method, uri, req, code, resp) in enumerate(EXCHANGES):
        sport = 40000 + i
        body = json.dumps(req, ensure_ascii=False).encode("utf-8") if req is not None else b""
        head = f"{method} {uri} HTTP/1.1\r\nHost: api.ejemplo.test\r\nUser-Agent: prueba/1.0\r\n"
        if body:
            head += f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
        request = head.encode() + b"\r\n" + body
        rbody = json.dumps(resp, ensure_ascii=False).encode("utf-8") if resp is not None else b""
        reason = {200: "OK", 201: "Created", 204: "No Content", 404: "Not Found"}[code]
        rhead = f"HTTP/1.1 {code} {reason}\r\nContent-Length: {len(rbody)}\r\n"
        if rbody:
            rhead += "Content-Type: application/json; charset=utf-8\r\n"
        response = rhead.encode() + b"\r\n" + rbody
        for k, frame in enumerate((_packet(CLIENT, SERVER, sport, 80, 1000, 5000, request),
                                   _packet(SERVER, CLIENT, 80, sport, 5000, 1000 + len(request), response))):
            out.append(struct.pack("<IIII", t + i, k * 1000, len(frame), len(frame)) + frame)
    path.write_bytes(b"".join(out))
    return path


if __name__ == "__main__":
    import sys

    print(write(sys.argv[1]))
