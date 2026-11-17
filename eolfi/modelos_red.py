"""Instantánea de sockets por PID, sin lanzar ni instrumentar el proceso.

Windows usa IP Helper directamente. Una instantánea no demuestra ausencia de
conexiones pasadas/futuras ni que un archivo GGUF sea el modelo cargado.
"""
from __future__ import annotations

import ctypes
import ipaddress
import os
import socket
import sys
from datetime import datetime, timezone

U32 = ctypes.c_uint32
ADDR6 = ctypes.c_ubyte * 16


class Tcp4(ctypes.Structure):
    _fields_ = [(x, U32) for x in ("state", "local", "port", "remote", "remote_port", "pid")]


class Tcp6(ctypes.Structure):
    _fields_ = [("local", ADDR6), ("scope", U32), ("port", U32), ("remote", ADDR6),
                ("remote_scope", U32), ("remote_port", U32), ("state", U32), ("pid", U32)]


class Udp4(ctypes.Structure):
    _fields_ = [(x, U32) for x in ("local", "port", "pid")]


class Udp6(ctypes.Structure):
    _fields_ = [("local", ADDR6), ("scope", U32), ("port", U32), ("pid", U32)]


STATES = {1: "CLOSED", 2: "LISTEN", 3: "SYN_SENT", 4: "SYN_RECEIVED", 5: "ESTABLISHED",
          6: "FIN_WAIT_1", 7: "FIN_WAIT_2", 8: "CLOSE_WAIT", 9: "CLOSING", 10: "LAST_ACK",
          11: "TIME_WAIT", 12: "DELETE_TCB"}
TABLES = (("tcp_ipv4", Tcp4, 4, True), ("tcp_ipv6", Tcp6, 6, True),
          ("udp_ipv4", Udp4, 4, False), ("udp_ipv6", Udp6, 6, False))


def _address(row, field, family):
    value = getattr(row, field)
    return str(ipaddress.ip_address(int(value).to_bytes(4, "little") if family == 4 else bytes(value)))


def _network_ip(text):
    address = ipaddress.ip_address(text)
    return (address.ipv4_mapped or address) if isinstance(address, ipaddress.IPv6Address) else address


def _decode(data, row_type, family, tcp, pid):
    if len(data) < 4:
        raise ValueError("Tabla de sockets truncada")
    count = int.from_bytes(data[:4], "little")
    size = ctypes.sizeof(row_type)
    if count > 100_000 or 4 + count * size > len(data):
        raise ValueError("Tabla de sockets incompleta o fuera de presupuesto")
    rows = []
    for i in range(count):
        start = 4 + i * size
        row = row_type.from_buffer_copy(data[start:start + size])
        if row.pid != pid:
            continue
        address = _address(row, "local", family)
        result = {"protocolo": "TCP" if tcp else "UDP", "familia": family,
                  "local": address, "puerto_local": socket.ntohs(row.port & 0xffff)}
        if family == 6:
            result["scope_local"] = socket.ntohl(row.scope)
        if tcp:
            # En LISTEN, la API declara indefinidos los campos del extremo remoto.
            remote = _address(row, "remote", family) if row.state != 2 else None
            remote_ip = _network_ip(remote) if remote is not None else None
            result.update(remoto=remote, puerto_remoto=socket.ntohs(row.remote_port & 0xffff) if remote else None,
                          estado=STATES.get(row.state, f"UNKNOWN_{row.state}"),
                          remoto_no_loopback=bool(remote_ip and not (remote_ip.is_loopback or remote_ip.is_unspecified)),
                          escucha_no_loopback=row.state == 2 and not _network_ip(address).is_loopback)
            if family == 6:
                result["scope_remoto"] = socket.ntohl(row.remote_scope) if remote else None
        rows.append(result)
    return rows


def _windows_table(row_type, family, tcp):
    api = ctypes.WinDLL("iphlpapi.dll", use_last_error=True, winmode=0x800)  # solo System32
    fn = api.GetExtendedTcpTable if tcp else api.GetExtendedUdpTable
    fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(U32), ctypes.c_int, U32, U32, U32]
    fn.restype = U32
    size = U32(0)
    af = socket.AF_INET if family == 4 else socket.AF_INET6
    table_class = 5 if tcp else 1  # OWNER_PID_ALL / UDP_TABLE_OWNER_PID
    code = fn(None, ctypes.byref(size), False, af, table_class, 0)
    if code not in (0, 122):
        raise OSError(code, "IP Helper no permite consultar la tabla")
    for _ in range(3):
        if size.value < 4 or size.value > 16 * 1024 * 1024:
            raise ValueError("Tamaño de tabla de sockets fuera de presupuesto")
        buffer = ctypes.create_string_buffer(size.value)
        code = fn(buffer, ctypes.byref(size), False, af, table_class, 0)
        if code == 0:
            return buffer.raw[:size.value]
        if code != 122:
            raise OSError(code, "No se pudo leer la tabla de sockets")
    raise OSError("La tabla de sockets cambió durante tres lecturas; repetir la instantánea")


def snapshot(pid):
    if type(pid) is not int or not 0 < pid <= 0xffffffff:
        raise ValueError("PID inválido")
    result = {"schema": "eolfi.modelos.conexiones/v1", "pid": pid,
              "fecha_utc": datetime.now(timezone.utc).isoformat(), "conexiones": [], "incognitas": [],
              "proveedor": {"nombre": "Windows IP Helper API", "version_windows":
                            ".".join(map(str, sys.getwindowsversion()[:3])) if hasattr(sys, "getwindowsversion") else "NO VERIFICADA"},
              "cobertura": {}, "limites": [
                  "Instantánea: no descarta conexiones anteriores ni posteriores",
                  "Las tablas se leen una tras otra; las conexiones pueden cambiar entre lecturas",
                  "No verifica que el PID esté vivo ni que haya cargado el GGUF indicado",
                  "Un remoto no loopback no distingue conexiones entrantes de salientes",
                  "UDP solo muestra enlaces locales; destinos e historial no observados",
              ]}
    if os.name != "nt":
        result["incognitas"].append("Proveedor de conexiones no implementado en esta plataforma")
    else:
        for label, row_type, family, tcp in TABLES:
            try:
                result["conexiones"].extend(_decode(_windows_table(row_type, family, tcp), row_type,
                                                   family, tcp, pid))
                result["cobertura"][label] = "consultada"
            except (OSError, ValueError, AttributeError) as exc:
                result["incognitas"].append(f"{label}: {exc}")
                result["cobertura"][label] = "NO VERIFICADO"
    result["tcp_remotos_no_loopback"] = sum(x.get("remoto_no_loopback", False) for x in result["conexiones"])
    result["tcp_escuchas_no_loopback"] = sum(x.get("escucha_no_loopback", False) for x in result["conexiones"])
    result["estado"] = "NO VERIFICADO" if result["incognitas"] else "observado"
    return result
