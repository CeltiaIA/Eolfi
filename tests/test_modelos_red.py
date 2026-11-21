import ctypes
import ipaddress
import os
import socket
import sys
from types import SimpleNamespace

import pytest

from eolfi import modelos_red as red


def table(*rows):
    return len(rows).to_bytes(4, "little") + b"".join(bytes(row) for row in rows)


def v4(text):
    return int.from_bytes(ipaddress.ip_address(text).packed, "little")


def test_pid_filter_ports_and_remote_are_observations():
    own = red.Tcp4(5, v4("127.0.0.1"), socket.htons(8090), v4("192.0.2.1"), socket.htons(443), 123)
    other = red.Tcp4(5, v4("127.0.0.1"), socket.htons(9999), v4("127.0.0.1"), socket.htons(80), 999)
    rows = red._decode(table(own, other), red.Tcp4, 4, True, 123)
    assert len(rows) == 1
    assert rows[0]["puerto_local"] == 8090 and rows[0]["puerto_remoto"] == 443
    assert rows[0]["local"] == "127.0.0.1" and rows[0]["remoto"] == "192.0.2.1"
    assert rows[0]["remoto_no_loopback"] is True
    assert rows[0]["escucha_no_loopback"] is False


def test_ipv6_and_udp_layout():
    row = red.Tcp6()
    row.local[:] = ipaddress.ip_address("::").packed
    row.remote[:] = ipaddress.ip_address("::").packed
    row.scope, row.port, row.pid, row.state = socket.htonl(7), socket.htons(11435), 42, 2
    result = red._decode(table(row), red.Tcp6, 6, True, 42)[0]
    assert result["local"] == "::" and result["scope_local"] == 7
    assert result["escucha_no_loopback"] is True and result["remoto_no_loopback"] is False
    assert result["remoto"] is None and result["puerto_remoto"] is None
    udp = red.Udp6()
    udp.local[:] = ipaddress.ip_address("::1").packed
    udp.pid, udp.port = 42, socket.htons(53)
    result = red._decode(table(udp), red.Udp6, 6, False, 42)[0]
    assert result["local"] == "::1" and result["puerto_local"] == 53
    assert "remoto" not in result
    assert ctypes.sizeof(red.Tcp6) == 56 and ctypes.sizeof(red.Udp6) == 28


def test_ipv4_mapped_loopback_is_still_local():
    row = red.Tcp6()
    row.local[:] = ipaddress.ip_address("::ffff:127.0.0.1").packed
    row.remote[:] = ipaddress.ip_address("::ffff:127.0.0.2").packed
    row.pid, row.state = 42, 5
    result = red._decode(table(row), red.Tcp6, 6, True, 42)[0]
    assert result["remoto_no_loopback"] is False
    row.state = 2
    result = red._decode(table(row), red.Tcp6, 6, True, 42)[0]
    assert result["escucha_no_loopback"] is False


@pytest.mark.parametrize("data", [b"", b"\x01\x00\x00\x00", (100001).to_bytes(4, "little")])
def test_truncated_tables_not_green(data):
    with pytest.raises(ValueError):
        red._decode(data, red.Tcp4, 4, True, 1)


def test_partial_query_reports_unknown(monkeypatch):
    monkeypatch.setattr(red, "os", SimpleNamespace(name="nt"))
    def read(row_type, family, tcp):
        if family == 6:
            raise PermissionError("denegado")
        return table()
    monkeypatch.setattr(red, "_windows_table", read)
    result = red.snapshot(42)
    assert result["estado"] == "NO VERIFICADO"
    assert len(result["incognitas"]) == 2
    assert result["cobertura"]["tcp_ipv4"] == "consultada"
    assert result["cobertura"]["tcp_ipv6"] == "NO VERIFICADO"


def test_proveedor_posix_distingue_escucha_y_conexion(monkeypatch):
    import types

    tcp = SimpleNamespace(family=socket.AF_INET, type=socket.SOCK_STREAM, laddr=("0.0.0.0", 123),
                          raddr=(), status="LISTEN")
    udp = SimpleNamespace(family=socket.AF_INET6, type=socket.SOCK_DGRAM, laddr=("::1", 456))
    provider = types.ModuleType("psutil")
    provider.__version__ = "prueba"
    provider.Error = RuntimeError
    provider.Process = lambda pid: SimpleNamespace(net_connections=lambda kind: [tcp, udp], is_running=lambda: True)
    monkeypatch.setitem(sys.modules, "psutil", provider)
    monkeypatch.setattr(red, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(red, "os", SimpleNamespace(name="posix"))
    result = red.snapshot(42)
    assert result["estado"] == "observado" and result["tcp_escuchas_no_loopback"] == 1
    assert result["conexiones"][1] == {"protocolo": "UDP", "familia": 6, "local": "::1", "puerto_local": 456}
    provider.Process = lambda pid: (_ for _ in ()).throw(PermissionError("PID inaccesible"))
    assert red.snapshot(42)["estado"] == "NO VERIFICADO"


def test_cli_keeps_unknown_status(monkeypatch, capsys, tmp_path):
    import json
    from eolfi.cli import main
    from tests.test_modelos import fixture

    monkeypatch.setattr(red, "snapshot", lambda pid: {"estado": "NO VERIFICADO", "pid": pid})
    assert main(["modelos", "conexiones", "--pid", "42"]) == 2
    assert json.loads(capsys.readouterr().out)["pid"] == 42
    model = fixture(tmp_path / "m.gguf")
    assert main(["modelos", "auditar", str(model), "--pid", "42"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["estado"] == "NO VERIFICADO"
    assert result["conexiones_motor"]["pid"] == 42


@pytest.mark.parametrize("pid", [0, -1, 2**32, "42", True])
def test_invalid_pid(pid):
    with pytest.raises(ValueError):
        red.snapshot(pid)


def test_real_loopback_sockets_are_seen_without_starting_a_model():
    from contextlib import ExitStack

    if sys.platform != "win32":
        if not (sys.platform.startswith("linux") or sys.platform == "darwin"):
            pytest.skip("Sin proveedor para este sistema")
        pytest.importorskip("psutil", minversion="6.0")

    with ExitStack() as stack:
        expected = []
        for family, address in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
            listener = stack.enter_context(socket.socket(family))
            listener.bind((address, 0))
            listener.listen(1)
            client = stack.enter_context(socket.socket(family))
            client.connect(listener.getsockname())
            accepted, _ = listener.accept()
            stack.enter_context(accepted)
            udp = stack.enter_context(socket.socket(family, socket.SOCK_DGRAM))
            udp.bind((address, 0))
            expected.extend([("TCP", listener.getsockname()[1]), ("TCP", client.getsockname()[1]),
                             ("UDP", udp.getsockname()[1])])
        result = red.snapshot(os.getpid())
        assert result["estado"] == "observado", result
        actual = {(x["protocolo"], x["puerto_local"]) for x in result["conexiones"]}
        assert set(expected) <= actual
        assert all(x["local"] in ("127.0.0.1", "::1") for x in result["conexiones"]
                   if (x["protocolo"], x["puerto_local"]) in expected)
