"""Plan REA, puntos 8 a 11 (16/11/2026): mapa de la app, móvil/gestionado, firmware y entorno de agente.

REA simulado: las formas de Android/IL2CPP/firmware/grafo NO están comprobadas con muestras reales (ver PLAN_REA.md);
la de inspect_managed_artifact (resumen) sí, con una DLL nativa del equipo el 16/11/2026.
"""
import json

import pytest

from eolfi import rea_compuestas as rc


class Fake:
    def __init__(self, data=None, fail=()):
        self.calls, self.args, self.data, self.fail = [], {}, data or {}, set(fail)

    def call(self, name, args, limit=None):
        self.calls.append(name)
        self.args[name] = args
        if name in self.fail:
            return '{"error": "no disponible en este REA"}', False
        return json.dumps(self.data.get(name, {})), True


def _file(tmp_path, name, head=b"\0\0\0\0"):
    f = tmp_path / name
    f.write_bytes(head + b"\0" * 32)
    return str(f)


def _managed(path, status="managed"):
    return {"normalized_result": {"parent_evidence_id": "ev_x", "summary": {
        "artifact": {"path": path, "sha256": "ab" * 32},
        "classification": {"status": status, "runtime_family": "dotnet", "implementation": "il"},
        "metadata": {"status": "complete"}, "assembly": {"name": "Demo", "version": "1.0.0.0"},
        "target_frameworks": [".NETCoreApp,Version=v8.0"], "reported_counts": {"references": 3},
        "limitations": []}}}


def test_ruta_para_managed_artifact_va_sin_unidad_y_se_comprueba_lo_leido(tmp_path):
    assert rc._ruta_rea_absoluta(r"D:\a\b.dll") == "/a/b.dll"
    assert rc._ruta_rea_absoluta("/ya/posix.dll") == "/ya/posix.dll"
    dll = _file(tmp_path, "demo.dll", b"MZ\0\0")
    rea = Fake({"inspect_managed_artifact": _managed(dll)})
    out = rc.analizar_movil(rea, dll)
    assert out["tipo"] == "gestionado" and out["clasificacion"] == "managed" and out["marcos"]
    assert rea.args["inspect_managed_artifact"]["path"].startswith("/")
    # Si REA resolvió la ruta en otra unidad, no se presenta como análisis del archivo pedido.
    otra = Fake({"inspect_managed_artifact": _managed(r"D:\otra\demo.dll")})
    with pytest.raises(RuntimeError, match="otro archivo"):
        rc.analizar_movil(otra, dll)


def test_pe_nativo_sugiere_inventario(tmp_path):
    dll = _file(tmp_path, "nativo.dll", b"MZ\0\0")
    out = rc.analizar_movil(Fake({"inspect_managed_artifact": _managed(dll, "not-managed")}), dll)
    assert out["tipo"] == "pe-nativo" and "inventario" in out["siguiente_paso"]


def test_apk_sin_jadx_queda_en_no_aplica_y_sigue_con_firmas_y_flutter(tmp_path):
    apk = _file(tmp_path, "app.apk", b"PK\x03\x04")
    rea = Fake({"inspect_apk_signature": {"normalized_result": {"summary": {"schemes": ["v2"], "signers": [1]}}},
                "identify_flutter_build": {"dart_snapshot_hash": "abc"}}, fail={"inspect_android_package"})
    out = rc.analizar_movil(rea, apk)
    assert out["tipo"] == "android" and "paquete" in out["no_aplica"] and "JADX" in out["siguiente_paso"]
    assert out["firmas"] == {"schemes": "1 elementos", "signers": "1 elementos"}
    assert out["flutter"]["dart_snapshot_hash"] == "abc"


def test_il2cpp_avisa_sin_binario_y_lo_pasa_si_se_da(tmp_path):
    meta = _file(tmp_path, "global-metadata.dat", b"\xaf\x1b\xb1\xfa")
    rea = Fake({"inspect_il2cpp_metadata": {"normalized_result": {"summary": {"version": 31}}}})
    out = rc.analizar_movil(rea, meta)
    assert out["metadatos"]["version"] == 31 and "direcciones_nativas" in out["no_aplica"]
    rc.analizar_movil(rea, meta, binario=r"D:\j\GameAssembly.dll")
    assert rea.args["inspect_il2cpp_metadata"]["binary_path"].endswith("GameAssembly.dll")


def test_formato_desconocido_no_se_inventa(tmp_path):
    with pytest.raises(ValueError, match="no reconocido"):
        rc.analizar_movil(Fake(), _file(tmp_path, "x.bin"))


def test_firmware_devicetree_y_binwalk_ausente(tmp_path):
    dtb = _file(tmp_path, "placa.dtb", b"\xd0\x0d\xfe\xed")
    out = rc.analizar_firmware(Fake({"inspect_devicetree": {"summary": {"nodes": [1, 2], "version": 17}}}), dtb)
    assert out["tipo"] == "devicetree" and out["devicetree"]["version"] == 17
    img = _file(tmp_path, "fw.bin")
    out = rc.analizar_firmware(Fake(fail={"inspect_firmware_regions"}), img)
    assert "regiones" in out["no_aplica"] and "WSL" in out["siguiente_paso"]
    regs = {"regions": [{"offset": 0, "length": 64, "description": "uImage header", "confidence": 250}]}
    out = rc.analizar_firmware(Fake({"inspect_firmware_regions": regs}), img)
    assert out["total_regiones"] == 1 and out["regiones"][0]["descripcion"] == "uImage header"


def test_mapa_nativo_pide_funcion_y_cierra_la_sesion(tmp_path):
    exe = _file(tmp_path, "a.exe", b"MZ\0\0")
    with pytest.raises(ValueError, match="función de partida"):
        rc.mapa_app(Fake(), exe)
    g = {"nodes": [{"address": "0x1", "name": "entry", "status": "ok"}, {"address": "0x2", "name": "f", "status": "ok"}],
         "edges": [{"from": "0x1", "to": "0x2"}]}
    rea = Fake({"get_call_graph": g})
    out = rc.mapa_app(rea, exe, "entry", "backward")
    assert out["nodos"] == 2 and out["enlaces"] == [["0x1", "0x2"]]
    assert rea.args["get_call_graph"] == {"address": "entry", "direction": "backward"}
    assert rea.calls[0] == "open_binary" and rea.calls[-1] == "close_binary"
    fallo = Fake(fail={"get_call_graph"})
    with pytest.raises(RuntimeError):
        rc.mapa_app(fallo, exe, "entry")
    assert fallo.calls[-1] == "close_binary"


def test_mapa_apk_pasa_la_evidencia_completa_a_la_proyeccion(tmp_path):
    apk = _file(tmp_path, "app.apk", b"PK\x03\x04")
    ev = {"evidence_id": "ev_inv", "normalized_result": {"artifacts": []}}
    rea = Fake({"inspect_artifact": ev, "project_android_application_graph": {"components": [1, 2, 3]}})
    out = rc.mapa_app(rea, apk)
    assert rea.args["project_android_application_graph"]["inventory_evidence"] == [ev]
    assert out["mapa"]["components"] == "3 elementos"


def test_entorno_agente_simula_por_defecto_y_valida_destino(tmp_path):
    har = tmp_path / "c.har"
    har.write_text("{}")
    with pytest.raises(ValueError, match="HAR"):
        rc.entorno_agente(Fake(), str(tmp_path / "c.pcap"), str(tmp_path / "env"))
    with pytest.raises(ValueError, match="NO debe existir"):
        rc.entorno_agente(Fake(), str(har), str(tmp_path))
    ev = {"evidence_id": "ev_har"}
    rea = Fake({"inspect_web_network_capture": ev, "export_environment_bundle": {"tools": {"read": 2}}})
    out = rc.entorno_agente(rea, str(har), str(tmp_path / "env"))
    args = rea.args["export_environment_bundle"]
    assert args["dry_run"] is True and args["source"] == ev and not out["escrito"]
    rc.entorno_agente(rea, str(har), str(tmp_path / "env"), escribir=True, nombre="demo")
    assert rea.args["export_environment_bundle"]["dry_run"] is False
    assert rea.args["export_environment_bundle"]["name"] == "demo"


def test_chat_expone_las_nuevas_y_el_rsi_observa_sus_fallos(tmp_path):
    from eolfi import chat, rsi, server

    for n in ("eolfi_analizar_movil", "eolfi_analizar_firmware", "eolfi_mapa_app", "eolfi_entorno_agente"):
        assert n in chat.APP_TOOLS
    app = server.EolfiApp(str(tmp_path / "r.db"))
    app.roots = [tmp_path]

    class Tools:
        client = Fake(fail={"inspect_firmware_regions"})

    tools = app._chat_rea_composites(Tools())
    img = _file(tmp_path, "fw.bin")
    assert "regiones" in tools["eolfi_analizar_firmware"]({"ruta": img})["no_aplica"]
    with pytest.raises(ValueError):
        tools["eolfi_mapa_app"]({"ruta": _file(tmp_path, "a.exe", b"MZ\0\0")})
    obs = [e["datos"] for e in rsi.eventos("observacion")]
    assert [(o["fuente"], o["operacion"], o["ok"]) for o in obs] == [
        ("chat", "analizar_firmware", True), ("chat", "mapa_app", False)]
