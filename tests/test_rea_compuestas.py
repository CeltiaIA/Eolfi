"""Herramientas compuestas sobre REA: revisar modelo, explicar binario y reimplementar función (13/11/2026)."""
import json
import os
from pathlib import Path

import pytest

from eolfi import rea_compuestas as rc


class FakeRea:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def call(self, name, args, limit=None):
        self.calls.append(name)
        if name == self.fail_on:
            return '{"error": "fallo simulado"}', False
        data = {
            "inspect_model_artifact": {"normalized_result": {"format": "gguf", "version": 3,
                "metadata": [{"key": "general.architecture", "value": "llama"}, {"key": "general.name", "value": "X"},
                             {"key": "llama.context_length", "value": 8192}],
                "totals": {"parameter_count": "7000000000", "by_type": [
                    {"type": "F32", "tensors": 10, "parameter_count": "1000"},
                    {"type": "Q5_K", "tensors": 200, "parameter_count": "6000000000"},
                    {"type": "Q6_K", "tensors": 20, "parameter_count": "900000000"}]}}},
            "open_binary": {"result": {"format": "pe", "architecture": "x86_64", "sha256": "ab" * 32}},
            "binary_overview": {"segments": [{"name": ".text"}, {"name": ".rdata"}]},
            "list_procedures": [
                {"address": "EXTERNAL:0x1", "value": "KERNEL32.DLL::ExitProcess", "procedure": {"external": True, "thunk": False}},
                {"address": "0x1", "value": "FUN_1", "procedure": {"external": False, "thunk": False}},
                {"address": "0x2", "value": "entry", "procedure": {"external": False, "thunk": False}},
                {"address": "0x3", "value": "FUN_3", "procedure": {"external": False, "thunk": False}},
                {"address": "0x4", "value": "thunk_x", "procedure": {"external": False, "thunk": True}}],
            "procedure_info": {"name": "FUN", "signature": "int f(int)", "length": 40, "basicblock_count": 3},
            "procedure_pseudo_code": "int f(int a) { return a + 1; }",
            "procedure_callees": ["0x9"],
            "list_strings": [{"value": "hola mundo"}, {"value": "no"}],
            "close_binary": {},
        }[name]
        return json.dumps(data), True


def test_revisar_modelo_detecta_cuantizacion_que_no_coincide_con_el_nombre():
    ok = rc.revisar_modelo(FakeRea(), r"D:\m\modelo-Q5_K_M.gguf")
    assert ok["aprobado"] and ok["modelo"]["architecture"] == "llama" and ok["modelo"]["context_length"] == 8192
    assert ok["parametros_legible"] == "7.00 B" and ok["tipos_de_tensor"]["Q5_K"] == 200
    mal = rc.revisar_modelo(FakeRea(), r"D:\m\modelo-Q4_K_M.gguf")     # promete Q4 y es Q5
    assert not mal["aprobado"] and mal["comprobaciones"][1]["dominante"] == "Q5_K"


def test_explicar_binario_elige_entrada_y_las_mas_complejas_y_cierra_la_sesion():
    rea = FakeRea()
    out = rc.explicar_binario(rea, r"C:\x.exe", funciones=2)
    names = [f["nombre"] for f in out["funciones_relevantes"]]
    assert names[0] == "entry" and len(names) == 2 and "thunk_x" not in names
    assert out["importaciones"] == 1 and out["funciones_propias"] == 3 and out["cadenas_muestra"] == ["hola mundo"]
    assert "no se ejecutó" in out["aviso"] and rea.calls[-1] == "close_binary"
    assert "Ghidra" in out["fuente_cifras"]["importaciones"] and "inventario" in out["fuente_cifras"]["importaciones"]


def test_reimplementar_funcion_avisa_de_que_una_prueba_verde_no_es_equivalencia():
    out = rc.reimplementar_funcion(FakeRea(), r"C:\x.exe", "entry")
    assert out["pseudocodigo"].startswith("int f") and out["llama_a"] == ["0x9"]
    assert "NO demuestra" in out["instrucciones"] and "no copies" in out["instrucciones"]


class FakeKuna:
    """Como Kuna vía REA (15/11/2026): sin marca de externas y sin procedure_info."""

    def __init__(self):
        self.calls, self.args = [], []

    def call(self, name, args, limit=None):
        self.calls.append(name)
        self.args.append(args)
        if name == "procedure_info":
            return json.dumps({"error": {"code": "capability_unavailable", "category": "unsupported_provider",
                                         "details": {"reason": "operation is not declared by this provider"}}}), False
        code = {"0x1": "int a(void) { return 0; }", "0x2": "int main(void) { return 1; }",
                "0x3": "void larga(void) {" + " x();" * 50 + " }"}
        data = {
            "open_binary": {"result": {"format": "elf", "architecture": "x86_64", "sha256": "cd" * 32}},
            "binary_overview": {"document": {}, "procedure_count": 3, "string_count": 1},
            "list_procedures": [{"address": "0x1", "value": "sub_1"}, {"address": "0x2", "value": "main"},
                                {"address": "0x3", "value": "sub_3"}],
            "procedure_pseudo_code": code.get(args.get("procedure"), ""),
            "procedure_callees": [],
            "list_strings": [{"value": "/lib64/ld-linux-x86-64.so.2"}],
            "close_binary": {},
        }[name]
        return json.dumps(data), True


def test_explicar_con_kuna_sin_tamanos_ni_externas():
    rea = FakeKuna()
    out = rc.explicar_binario(rea, "/tmp/x.elf", funciones=2, motor="kuna")
    assert rea.args[0]["provider_id"] == "kuna" and rea.calls[-1] == "close_binary"
    assert [f["nombre"] for f in out["funciones_relevantes"]] == ["main", "sub_3"]   # main y la de más pseudocódigo
    assert out["funciones_relevantes"][1]["bytes"] is None and out["funciones_relevantes"][1]["firma"] is None
    assert out["motor"] == "Kuna" and out["importaciones"] is None and "Kuna" in out["aviso"]
    assert "inventario" in out["fuente_cifras"]["importaciones"]
    assert "pseudocódigo" in out["fuente_cifras"]["funciones_relevantes"]
    assert rea.calls.count("procedure_info") == 1   # se deja de pedir en cuanto el motor dice que no lo tiene


def test_reimplementar_con_kuna_sin_firma():
    rea = FakeKuna()
    out = rc.reimplementar_funcion(rea, "/tmp/x.elf", "0x2", motor="kuna")
    assert out["motor"] == "Kuna" and out["firma"] is None and out["funcion"] == "0x2"
    assert out["pseudocodigo"].startswith("int main") and rea.calls[-1] == "close_binary"


def test_ghidra_no_pide_proveedor_explicito():
    rea, seen = FakeRea(), []
    orig = rea.call
    rea.call = lambda name, args, limit=None: (seen.append(args) if name == "open_binary" else None) or orig(name, args, limit)
    out = rc.explicar_binario(rea, "/tmp/x.exe", funciones=1)
    assert "provider_id" not in seen[0] and out["motor"] == "Ghidra" and out["importaciones"] == 1


def test_la_sesion_de_rea_se_cierra_aunque_falle():
    rea = FakeRea(fail_on="procedure_pseudo_code")
    with pytest.raises(RuntimeError, match="procedure_pseudo_code"):
        rc.reimplementar_funcion(rea, r"C:\x.exe", "entry")
    assert rea.calls[-1] == "close_binary"


def test_el_chat_valida_la_ruta_antes_de_llamar_a_rea(tmp_path):
    from eolfi import server

    app = server.EolfiApp(str(tmp_path / "r.db"))
    app.roots = [tmp_path]

    class Tools:
        client = FakeRea()

    tools = app._chat_rea_composites(Tools())
    with pytest.raises(server.ApiError):
        tools["eolfi_revisar_modelo"]({"ruta": r"C:\fuera\m-Q5_K_M.gguf"})
    assert Tools.client.calls == []                                       # no llegó a REA
    assert tools["eolfi_revisar_modelo"]({"ruta": str(tmp_path / "m-Q5_K_M.gguf")})["aprobado"]


class FakeCompare(FakeRea):
    """Dos versiones: la nueva añade una importación y quita una función con nombre."""

    def __init__(self, same=False):
        super().__init__()
        self.opened, self.same = [], same

    def call(self, name, args, limit=None):
        if name == "open_binary":
            self.opened.append(args["path"])
            self.calls.append(name)
            sha = "aa" * 32 if self.same or len(self.opened) == 1 else "bb" * 32
            return json.dumps({"result": {"format": "pe", "sha256": sha}}), True
        if name == "inspect_artifact":
            self.calls.append(name)
            return json.dumps({"evidence_id": f"ev_inv{len(self.opened)}", "normalized_result": {}}), True
        if name == "list_procedures":
            self.calls.append(name)
            base = [{"value": "K32::ExitProcess", "procedure": {"external": True}},
                    {"value": "FUN_1", "procedure": {"external": False}}]
            extra = ([{"value": "parse_config", "procedure": {"external": False}}] if len(self.opened) == 1 or self.same
                     else [{"value": "K32::CreateFileW", "procedure": {"external": True}}])
            return json.dumps(base + extra), True
        if name == "compare_artifacts":
            self.calls.append(name)
            assert args["left"]["evidence_id"] == "ev_inv1" and args["right"]["evidence_id"] == "ev_inv2"
            status = "unchanged" if self.same else "changed"
            return json.dumps({"evidence_id": "ev_cmp", "normalized_result": {"status": status, "summary": {"changed": int(not self.same)},
                                                                            "changes": []}}), True
        if name == "verify_reconstruction":
            self.calls.append(name)
            claim = args["specification"]["claims"][0]
            assert claim["comparison_evidence_id"] == "ev_cmp" and claim["kind"] == "structural-artifact"
            st = "unknown" if self.same else "fail"
            return json.dumps({"normalized_result": {"status": st, "claims": {"items": [
                {"claim_id": claim["claim_id"], "status": st, "observed_status": "x", "limitations": ["solo raíz"]}]}}}), True
        return super().call(name, args, limit)


def test_comparar_versiones_resume_cambios_y_veredicto_de_rea():
    rea = FakeCompare()
    out = rc.comparar_versiones(rea, r"C:\v1.exe", r"C:\v2.exe")
    assert out["rea_estado"] == "changed" and out["verificacion"]["estado"] == "fail" and not out["identicos"]
    assert out["importaciones_anadidas"] == ["K32::CreateFileW"] and out["funciones_con_nombre_quitadas"] == ["parse_config"]
    assert "FUN_1" not in out["funciones_con_nombre_anadidas"] + out["funciones_con_nombre_quitadas"]
    assert out["verificacion"]["limites"] == ["solo raíz"] and rea.calls[-1] == "close_binary"
    igual = rc.comparar_versiones(FakeCompare(same=True), r"C:\v1.exe", r"C:\v1.exe")
    assert igual["identicos"] and igual["rea_estado"] == "unchanged" and igual["verificacion"]["estado"] == "unknown"


def test_comparar_desde_el_chat_valida_las_dos_rutas(tmp_path):
    from eolfi import server

    app = server.EolfiApp(str(tmp_path / "c.db"))
    app.roots = [tmp_path]

    class Tools:
        client = FakeCompare()

    tools = app._chat_rea_composites(Tools())
    with pytest.raises(server.ApiError):
        tools["eolfi_comparar_versiones"]({"original": str(tmp_path / "a.exe"), "nueva": r"C:\fuera\b.exe"})
    assert Tools.client.calls == []
    assert tools["eolfi_comparar_versiones"]({"original": str(tmp_path / "a.exe"), "nueva": str(tmp_path / "b.exe")})["rea_estado"] == "changed"


class FakeInventory:
    def __init__(self, go_deps=True, fail=()):
        self.go_deps, self.fail, self.calls = go_deps, set(fail), []

    def call(self, name, args, limit=None):
        self.calls.append(name)
        if name in self.fail:
            return '{"error": {"code": "unsupported_target"}}', False
        module = "path\tgithub.com/x/app\nbuild\t-compiler=gc" + ("\ndep\tgithub.com/y/lib\tv1.2.3\th1:abc" if self.go_deps else "")
        data = {
            "inspect_pe_imports": {"artifact": {"sha256": "cd" * 32}, "architecture": "amd64", "imphash": "ff",
                                   "imports": [{"name": "KERNEL32.dll", "functions": [{"name": "ExitProcess"}, {"ordinal": 7}]}],
                                   "delay_imports": []},
            "inspect_pe_certificates": {"entries": [{"x": 1}]},
            "inspect_pe_resources": {"resources": [{"type": {"name": "MUI"}}, {"type": {"id": 16}}, {"type": {"id": 16}}]},
            "inspect_go_binary": {"build_info": {"go_version": "go1.26", "module_text": module}},
            "inspect_rust_binary": {"auditable_metadata": None, "rustc_commit": None},
        }[name]
        return json.dumps({"normalized_result": data}), True


def _pe(tmp_path):
    f = tmp_path / "app.exe"
    f.write_bytes(b"MZ" + b"\0" * 64)
    return str(f)


def test_inventario_de_un_pe_go_con_firma_y_recursos(tmp_path):
    out = rc.inventario_dependencias(FakeInventory(), _pe(tmp_path))
    assert out["formato"] == "pe" and out["imphash"] == "ff" and out["firma"]["certificados"] == 1
    assert out["librerias"] == [{"libreria": "KERNEL32.dll", "funciones": 2, "muestra": ["ExitProcess", "ordinal 7"]}]
    assert out["recursos"] == {"MUI": 1, "16": 2}
    assert out["go"]["modulo"] == "github.com/x/app" and out["go"]["dependencias"] == [{"modulo": "github.com/y/lib", "version": "v1.2.3"}]
    assert "rust" not in out and out["no_aplica"] == {}


def test_inventario_dice_lo_que_no_sabe_en_vez_de_inventarlo(tmp_path):
    out = rc.inventario_dependencias(FakeInventory(go_deps=False, fail={"inspect_pe_certificates"}), _pe(tmp_path))
    assert out["go"]["dependencias"].startswith("no declaradas")             # vacío no es «sin dependencias»
    assert "certificados" in out["no_aplica"] and "firma" not in out
    elf = tmp_path / "app"
    elf.write_bytes(b"\x7fELF" + b"\0" * 60)

    class Elf(FakeInventory):
        def call(self, name, args, limit=None):
            if name == "inspect_native_exports":
                self.calls.append(name)
                return json.dumps({"normalized_result": {"exports": [{"name": "f"}]}}), True
            return super().call(name, args, limit)

    rea = Elf(fail={"inspect_go_binary", "inspect_rust_binary"})
    out = rc.inventario_dependencias(rea, str(elf))
    assert out["formato"] == "elf" and out["exportaciones"] == 1 and "inspect_pe_imports" not in rea.calls


def test_analizar_app_js_resume_electron_y_cobertura_sin_ejecutar():
    class FakeJs:
        def call(self, name, args, limit=None):
            assert name == "analyze_javascript_application" and args["detail"] == "summary"
            return json.dumps({"normalized_result": {
                "parent_evidence_id": "ev_app", "unknowns": ["120 semantic graph unknowns remain in the parent Evidence."],
                "summary": {"format": "asar", "root_artifact_sha256": "ef" * 32,
                            "statistics": {"relevant_files": 3, "parsed_javascript_files": 2, "parse_failures": 0, "findings": 9},
                            "electron": {"browser_windows": 1, "preload_entrypoints": 1, "exposed_api_members": 4,
                                         "ipc": {"literal_channels": 5, "main_handlers": 3}},
                            "coverage": {"application": {"status": "partial"}, "semantic": {"status": "unknown", "families": [
                                {"family": "call-flow", "status": "partial", "retained_relations": 10, "unknown_count": 2}]}}}}}), True

    out = rc.analizar_app_js(FakeJs(), r"C:\app\app.asar")
    assert out["sha256"] == "ef" * 32 and out["electron"]["canales_ipc"] == 5 and out["electron"]["ventanas"] == 1
    assert out["incognitas_semanticas"] == 120 and out["cobertura"]["familias"][0]["relaciones"] == 10
    assert "no se ejecutó" in out["aviso"] and "Linux" in out["siguiente_paso"]


def test_rutas_de_windows_vistas_desde_wsl():
    from eolfi.rea_client import wsl_path

    assert wsl_path(r"D:\Eolfi\web\app.js") == "/mnt/d/Eolfi/web/app.js"
    assert wsl_path("C:/x/y.js") == "/mnt/c/x/y.js"


@pytest.mark.skipif(os.name != "nt", reason="puente Windows → WSL: solo tiene sentido con un anfitrión Windows "
                                            "(las rutas temporales de Linux no son rutas de unidad)")
def test_recuperar_fuentes_crea_en_ubuntu_copia_a_windows_y_limpia(tmp_path):
    import subprocess

    class FakeWakaru:
        def call(self, name, args, limit=None):
            assert name == "recover_javascript_sources"
            assert args["path"].startswith("/mnt/") and args["output_directory"].startswith("/home/u/.local/eolfi-rea/salidas/eolfi-")
            self.out = args["output_directory"]
            return json.dumps({"normalized_result": {"status": "complete", "source": {"sha256": "ab" * 32},
                                                     "engine": {"version": "1.14.0"}, "failed": 0,
                                                     "modules": [{"reported_filename": "a.js", "reported_status": "decompiled",
                                                                  "artifact": {"sha256": "cd" * 32}}]}}), True

    runs = []

    def run(argv, **kw):
        runs.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="/home/u\n", stderr="")

    src = tmp_path / "bundle.js"
    src.write_text("var a=1;", encoding="utf-8")
    dest = tmp_path / "salida"
    wakaru = FakeWakaru()
    out = rc.recuperar_fuentes_js(wakaru, str(src), str(dest), run=run)
    assert out["estado"] == "complete" and out["modulos"][0]["estado"] == "decompiled" and out["motor"] == "wakaru 1.14.0"
    assert runs[1][:4] == ["wsl.exe", "-e", "cp", "-r"] and runs[1][4] == wakaru.out and runs[1][5].startswith("/mnt/")
    assert runs[2][:4] == ["wsl.exe", "-e", "rm", "-rf"] and runs[2][4] == wakaru.out          # no deja restos en Ubuntu
    assert "no van a Alejandría" in out["aviso"]
    dest.mkdir(exist_ok=True)
    (dest / "ya.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="no está vacío"):
        rc.recuperar_fuentes_js(FakeWakaru(), str(src), str(dest), run=run)


def test_sin_rea_de_wsl_se_explica_como_instalarlo(tmp_path):
    from eolfi import server

    app = server.EolfiApp(str(tmp_path / "w.db"))
    with pytest.raises(RuntimeError, match="instalar-rea-wsl.sh"):
        app._recover_js(str(tmp_path / "a.js"))


class FakeCapture:
    """REA de Windows: resumen de la captura (URI pedidas)."""

    def call(self, name, args, limit=None):
        assert name == "inspect_pcap_capture"
        return json.dumps({"normalized_result": {"packet_count": 12, "file_type": "pcap", "tls_sni_values": ["cdn.x.test"],
                                                 "protocol_distribution": [{"protocol": "eth:ip:tcp:http:json"}],
                                                 "http_request_uris": ["http://api.x.test/v1/items?page=1&limit=5",
                                                                       "http://api.x.test/v1/items/42",
                                                                       "http://api.x.test/v1/items/7"]}}), True


class FakeFields:
    """REA de WSL con tshark, con la forma REAL: «packets», frame.number, http.request_in y cuerpos en hexadecimal."""

    def call(self, name, args, limit=None):
        assert name == "inspect_packet_capture" and args["display_filter"] == "http"
        assert "http.response_for.uri" not in args["fields"]            # no existe en tshark 4.6.4
        hexa = lambda d: json.dumps(d).encode().hex()
        rows = [
            {"frame.number": ["1"], "http.request.method": ["GET"], "http.request.uri": ["/v1/items/42"]},
            {"frame.number": ["2"], "http.request.uri": ["/v1/items/42"], "http.response.code": ["200"], "http.request_in": ["1"],
             "http.content_type": ["application/json; charset=utf-8"], "http.file_data": [hexa({"id": 42, "ok": True})]},
            {"frame.number": ["3"], "http.request.method": ["POST"], "http.request.uri": ["/v1/items"],
             "http.file_data": [hexa({"name": "a"})]},
            {"frame.number": ["4"], "http.response.code": ["201"], "http.request_in": ["3"]},
        ]
        return json.dumps({"normalized_result": {"packets": rows}}), True


def test_api_desde_captura_basico_agrupa_rutas_y_avisa():
    out = rc.api_desde_captura(FakeCapture(), r"C:\c.pcap")
    assert out["nivel"] == "basico" and out["servidores"] == ["http://api.x.test"] and out["hosts_cifrados_tls"] == ["cdn.x.test"]
    assert out["endpoints"]["/v1/items/{id}"]["ejemplos"] == ["http://api.x.test/v1/items/42", "http://api.x.test/v1/items/7"]
    assert out["endpoints"]["/v1/items"]["parametros_consulta"] == ["limit", "page"]
    assert "openapi" not in out and "Aún no es una especificación OpenAPI" in out["aviso"]


def test_api_desde_captura_completo_da_un_borrador_openapi():
    out = rc.api_desde_captura(FakeCapture(), r"C:\c.pcap", fields_client=FakeFields())
    spec = out["openapi"]
    assert out["nivel"] == "completo" and spec["openapi"] == "3.0.3" and spec["servers"] == [{"url": "http://api.x.test"}]
    get = spec["paths"]["/v1/items/{id}"]["get"]
    assert get["parameters"][0]["in"] == "path"
    assert get["responses"]["200"]["content"]["application/json"]["schema"] == {
        "type": "object", "properties": {"id": {"type": "integer"}, "ok": {"type": "boolean"}}}
    post = spec["paths"]["/v1/items"]["post"]
    assert post["requestBody"]["content"]["application/json"]["schema"]["properties"]["name"] == {"type": "string"}
    assert "201" in post["responses"] and {p["name"] for p in post["parameters"]} == {"page", "limit"}


def _mini_pe(code_byte: int, rsrc_byte: int) -> bytes:
    """PE32+ mínimo: .text (código) en 0x200 y .rsrc en 0x300, base de imagen 0x140000000."""
    import struct

    data = bytearray(0x400)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x40)
    data[0x40:0x44] = b"PE\0\0"
    struct.pack_into("<HH", data, 0x44, 0x8664, 2)                      # máquina, número de secciones
    struct.pack_into("<H", data, 0x54, 0xF0)                            # tamaño de la cabecera opcional
    struct.pack_into("<H", data, 0x58, 0x20B)                           # PE32+
    struct.pack_into("<Q", data, 0x58 + 24, 0x140000000)                # ImageBase
    table = 0x58 + 0xF0
    for i, (name, rva, ptr, chars) in enumerate(((b".text", 0x1000, 0x200, 0x60000020),
                                                  (b".rsrc", 0x2000, 0x300, 0x40000040))):
        off = table + 40 * i
        data[off:off + 8] = name.ljust(8, b"\0")
        struct.pack_into("<IIII", data, off + 8, 0x100, rva, 0x100, ptr)
        struct.pack_into("<I", data, off + 36, chars)
    data[0x210] = code_byte
    data[0x305] = rsrc_byte
    return bytes(data)


def test_bytes_cambiados_por_seccion_y_direccion_del_codigo(tmp_path):
    """14/11/2026: REA decía «changed: content» sin decir dónde. Con dos versiones reales de whoami.exe: 424 bytes
    (277 en .rsrc, 76 de cabecera, 68 en .rdata, 2 en .data y 1 en .text), igual que cmp + objdump."""
    from eolfi.rea_compuestas import pe_section_diff

    a, b, c = tmp_path / "a.exe", tmp_path / "b.exe", tmp_path / "c.exe"
    a.write_bytes(_mini_pe(0x90, 0x01))
    b.write_bytes(_mini_pe(0xCC, 0x02))          # cambia código y recursos
    c.write_bytes(_mini_pe(0x90, 0x07))          # solo recursos
    d = pe_section_diff(str(a), str(b))
    assert d["total"] == 2 and d["por_seccion"] == {".text": 1, ".rsrc": 1}
    assert d["codigo"] == 1 and d["direcciones_codigo"] == ["0x140001010"] and "0x140001010" in d["lectura"]
    only_data = pe_section_diff(str(a), str(c))
    assert only_data["codigo"] == 0 and "ningún byte de código" in only_data["lectura"]
    assert pe_section_diff(str(a), str(a))["lectura"].startswith("los dos archivos son idénticos")
    txt = tmp_path / "x.txt"
    txt.write_text("no es un PE")
    assert pe_section_diff(str(a), str(txt)) is None


class FakeBinwalk:
    """REA de WSL con Binwalk 3.1.0: forma real de inspect_firmware_regions (14/11/2026)."""

    def __init__(self, regions):
        self.regions, self.paths = regions, []

    def call(self, name, args, limit=None):
        assert name == "inspect_firmware_regions"
        self.paths.append(args["path"])
        return json.dumps({"normalized_result": {"engine": {"name": "binwalk", "version": "3.1.0",
                                                            "executable_sha256": "cd" * 32},
                                                 "regions": self.regions, "coverage": "signature_scan"}}), True


def test_firmware_regiones_ordena_y_clasifica_los_huecos(tmp_path):
    img = tmp_path / "fw.bin"
    img.write_bytes(b"\xff" * 16 + b"GZ" + b"\x00" * 6 + b"\x00" * 8 + b"zz" * 4 + b"\xff" * 8)  # 48 bytes
    fake = FakeBinwalk([{"offset": 26, "reported_size": 4, "signature": "png", "description": "PNG",
                         "reported_confidence": 250},
                        {"offset": 16, "reported_size": 8, "signature": "gzip", "description": "gzip",
                         "reported_confidence": 250}])
    out = rc.firmware_regiones(fake, str(img))
    assert fake.paths[0] == rc._rea_ruta(img) and out["motor"] == "binwalk 3.1.0" and out["bytes"] == 48
    assert [r["firma"] for r in out["regiones"]] == ["gzip", "png"] and out["regiones"][0]["hex"] == "0x10"
    assert out["huecos"] == [
        {"desde": 0, "hasta": 16, "bytes": 16, "contenido": "relleno 0xFF"},
        {"desde": 24, "hasta": 26, "bytes": 2, "contenido": "ceros"},
        {"desde": 30, "hasta": 48, "bytes": 18, "contenido": "datos sin firma"}]
    assert out["bytes_sin_firma"] == 18 and "Unblob" in out["siguientes_pasos"][-1]


def test_firmware_regiones_sugiere_devicetree_y_rechaza_lo_que_no_existe(tmp_path):
    img = tmp_path / "fw.bin"
    img.write_bytes(b"\x00" * 64)
    fake = FakeBinwalk([{"offset": 8, "reported_size": None, "signature": "fdt",
                         "description": "Device tree blob (DTB)", "reported_confidence": 250}])
    out = rc.firmware_regiones(fake, str(img))
    assert out["siguientes_pasos"][0] == "inspect_devicetree sobre la región en 0x8"
    assert out["huecos"][-1] == {"desde": 9, "hasta": 64, "bytes": 55, "contenido": "ceros"}
    with pytest.raises(ValueError, match="no existe"):
        rc.firmware_regiones(fake, str(tmp_path / "no.bin"))
class FakeEnv:
    """REA: resumen del HAR, vista de cobertura del entorno y exportación (formas reales del 14/11/2026)."""

    def __init__(self):
        self.calls = []

    def call(self, name, args, limit=None):
        self.calls.append((name, args))
        if name == "inspect_web_network_capture":
            assert args["format"] == "har" and args["detail"] == "summary"
            r = {"parent_evidence_id": "ev_padre", "artifact": {"sha256": "ab" * 32},
                 "summary": {"total_records": 6, "format": "har"}}
        elif name == "inspect_analysis_view":
            assert args["source"] == {"kind": "retained-evidence", "evidence_id": "ev_padre"}
            assert args["view"]["kind"] == "environment-coverage"
            r = {"origin": "https://tienda.example", "name": "tienda-example",
                 "reads": {"state": 2, "recorded": 0, "recorded_reasons": {}},
                 "writes": {"served": [{"tool": "post_items", "effect": "create"}], "withheld": []},
                 "unknowns": [{"kind": "authorization-model", "statement": "sin modelo de autorización"}]}
        else:
            assert name == "export_environment_bundle"
            r = {"status": "planned" if args["dry_run"] else "written", "directory": args["output_directory"],
                 "name": args.get("name", "tienda-example"), "tool_count": 3, "warnings": [],
                 "package_source": {"kind": "registry", "specifier": "rea-agents@6.8.0"},
                 "files": [{"path": "README.md", "bytes": 3224}]}
        return json.dumps({"normalized_result": r}), True


def test_entorno_agente_es_un_ensayo_por_defecto(tmp_path):
    har = tmp_path / "t.har"
    har.write_text("{}", encoding="utf-8")
    fake = FakeEnv()
    out = rc.entorno_agente(fake, str(har), str(tmp_path / "paquete"))
    export = [a for n, a in fake.calls if n == "export_environment_bundle"][0]
    assert export["dry_run"] is True and "name" not in export
    assert out["estado"].startswith("ensayo") and out["estado_rea"] == "planned" and out["herramientas"] == 3
    assert out["escrituras_servidas"] == [{"tool": "post_items", "effect": "create"}] and out["registros"] == 6
    assert out["incognitas"] == ["sin modelo de autorización"] and "datos personales" in out["aviso"]
    out = rc.entorno_agente(fake, str(har), str(tmp_path / "paquete"), "mi-tienda", escribir=True)
    export = [a for n, a in fake.calls if n == "export_environment_bundle"][-1]
    assert export["dry_run"] is False and export["name"] == "mi-tienda" and out["estado"] == "escrito"


def test_entorno_agente_rechaza_entradas_malas_sin_llamar_a_rea(tmp_path):
    har = tmp_path / "t.har"
    har.write_text("{}", encoding="utf-8")
    (tmp_path / "ya").mkdir()
    fake = FakeEnv()
    for captura, destino, texto in [(str(tmp_path / "t.pcap"), str(tmp_path / "p"), "HAR"),
                                    (str(tmp_path / "no.har"), str(tmp_path / "p"), "no existe"),
                                    (str(har), "relativa", "absoluta"),
                                    (str(har), str(tmp_path / "ya"), "ya existe"),
                                    (str(har), str(tmp_path / "x" / "y"), "no existe la carpeta")]:
        with pytest.raises(ValueError, match=texto):
            rc.entorno_agente(fake, captura, destino)
    assert fake.calls == []


class FakeAndroid:
    """REA: inspect_android_package (resumen de JADX), sesión, inventario y grafo, con las formas reales del 14/11."""

    def __init__(self):
        self.calls = []

    def call(self, name, args, limit=None):
        self.calls.append(name)
        comps = [
            {"kind": "activity", "name": "a.Main", "exported": True, "exported_default": True, "permission": None,
             "actions": ["android.intent.action.MAIN"], "categories": ["android.intent.category.LAUNCHER"]},
            {"kind": "activity", "name": "a.Interna", "exported": False, "exported_default": False, "permission": None},
            {"kind": "provider", "name": "a.Datos", "exported": None, "exported_default": True, "permission": None,
             "authorities": ["a.datos"]},
            {"kind": "service", "name": "a.Sync", "exported": True, "exported_default": False,
             "permission": "a.permission.SYNC"},
            {"kind": "receiver", "name": "a.Boot", "exported": True, "exported_default": True, "permission": None,
             "actions": ["android.intent.action.BOOT_COMPLETED"]},
        ]
        results = {
            "inspect_android_package": {"summary": {
                "engine": {"name": "jadx-headless-mcp", "version": "0.7.1"}, "package_name": "a", "version_name": "1.0",
                "version_code": "1", "min_sdk": "26", "target_sdk": "33", "class_count": 10, "resource_count": 5,
                "permissions": ["android.permission.CAMERA", "android.permission.INTERNET"],
                "components": {"status": "complete", "items": comps}, "signature_verification": "not_performed"}},
            "open_binary": {"result": {}},
            "inspect_artifact": {"evidence_id": "ev_inv"},
            "project_android_application_graph": {
                "root_sha256": "ef" * 32, "runtime_families": ["dalvik-art", "native"], "bridge_candidates": [],
                "components": {"dex": [{"path": "classes.dex"}], "native_libraries": [{"path": "lib/arm64-v8a/libx.so"}]},
                "coverage": {"status": "complete-within-inventory"}},
            "close_binary": {},
        }
        if name == "project_android_application_graph":
            assert args["inventory_evidence"] == [{"evidence_id": "ev_inv"}]
        return json.dumps({"normalized_result": results[name]} if name != "inspect_artifact" else results[name]), True


def test_mapa_app_android_resume_la_superficie_exportada(tmp_path):
    apk = tmp_path / "a.apk"
    apk.write_bytes(b"PK")
    fake = FakeAndroid()
    out = rc.mapa_app_android(fake, str(apk))
    assert fake.calls[-1] == "close_binary"
    assert out["paquete"]["nombre"] == "a" and out["motor"] == "jadx-headless-mcp 0.7.1"
    assert out["permisos_peligrosos"] == ["android.permission.CAMERA"] and out["lanzadores"] == ["a.Main"]
    assert out["componentes"]["activity"] == {"total": 2, "exportados": 1, "exportados_sin_permiso": 1}
    assert out["componentes"]["service"] == {"total": 1, "exportados": 1, "exportados_sin_permiso": 0}
    # Proveedores primero; el exportado por defecto lo dice; el servicio con permiso no aparece.
    assert [c["nombre"] for c in out["exportados_sin_permiso"]] == ["a.Datos", "a.Boot", "a.Main"]
    assert out["exportados_sin_permiso"][0] == {"tipo": "provider", "nombre": "a.Datos", "permiso": None,
                                                "exportado_por_defecto": True, "autoridades": ["a.datos"]}
    assert out["bibliotecas_nativas"] == ["lib/arm64-v8a/libx.so"] and out["estructura"] == {"dex": 1, "native_libraries": 1}
    out = rc.mapa_app_android(FakeAndroid(), str(apk), limite=1)
    assert len(out["exportados_sin_permiso"]) == 1 and out["exportados_sin_permiso_omitidos"] == 2


def test_mapa_app_android_rechaza_lo_que_no_es_un_apk(tmp_path):
    fake = FakeAndroid()
    (tmp_path / "x.zip").write_bytes(b"PK")
    for ruta in (tmp_path / "x.zip", tmp_path / "no.apk"):
        with pytest.raises(ValueError, match="apk"):
            rc.mapa_app_android(fake, str(ruta))
    assert fake.calls == []


class FakeCallGraph:
    """REA con Ghidra: list_procedures y get_call_graph por niveles (formas reales con whoami.exe, 14/11/2026)."""

    def __init__(self):
        self.calls = []

    def call(self, name, args, limit=None):
        self.calls.append((name, args))
        procs = [{"address": "0x10", "value": "entry"}, {"address": "0x20", "value": "FUN_20"},
                 {"address": "0x30", "value": 'raro"[x]'}, {"address": "EXTERNAL:0x1", "value": "KERNEL32.DLL::Sleep"},
                 {"address": "0x40", "value": "MSVCRT.DLL::exit"}]
        if name == "list_procedures":
            r = procs
        elif name == "get_call_graph":
            if args["direction"] == "backward":   # quién llama a 0x20: entry
                r = {"graph": {"0": [{"address": args["address"], "status": "ok", "calls": ["0x10"]}],
                               "1": [{"address": "0x10", "status": "ok", "calls": []}]}}
            else:
                r = {"graph": {"0": [{"address": args["address"], "status": "ok", "calls": ["0x20", "0x30"]}],
                               "1": [{"address": "0x20", "status": "ok", "calls": ["EXTERNAL:0x1", "0x40"]},
                                     {"address": "0x30", "status": "error", "calls": []}],
                               "2": [{"address": "EXTERNAL:0x1", "status": "ok", "calls": []},
                                     {"address": "0x40", "status": "ok", "calls": []}]}}
        else:
            r = {"result": {}}
        return json.dumps({"normalized_result": r}), True


def test_grafo_llamadas_resuelve_nombres_recorta_y_da_mermaid():
    fake = FakeCallGraph()
    out = rc.grafo_llamadas(fake, r"C:\x.exe", "ENTRY", profundidad=2)
    assert ("get_call_graph", {"address": "0x10", "direction": "forward"}) in fake.calls
    assert fake.calls[-1][0] == "close_binary"
    assert [n["nombre"] for n in out["nodos"]] == ["entry", "FUN_20", 'raro"[x]', "KERNEL32.DLL::Sleep", "MSVCRT.DLL::exit"]
    assert out["apis_externas"] == {"KERNEL32.DLL": ["Sleep"], "MSVCRT.DLL": ["exit"]}
    assert out["aristas"] == 4 and out["nodos_con_error"] == 1 and out["nodos_omitidos"] == 0
    assert 'n2["raro__x_"]' in out["mermaid"] and "n0 --> n1" in out["mermaid"] and "n1 --> n3" in out["mermaid"]
    assert out["enlaces"] == [["0x10", "0x20"], ["0x10", "0x30"], ["0x20", "EXTERNAL:0x1"], ["0x20", "0x40"]]
    corto = rc.grafo_llamadas(FakeCallGraph(), r"C:\x.exe", "entry", profundidad=1, max_nodos=2)
    assert len(corto["nodos"]) == 2 and corto["nodos_omitidos"] == 3 and corto["aristas"] == 1


def test_grafo_llamadas_hacia_atras_y_errores():
    out = rc.grafo_llamadas(FakeCallGraph(), r"C:\x.exe", "0x20", hacia="atras", profundidad=1)
    assert out["funcion"] == "FUN_20" and "n1 --> n0" in out["mermaid"]
    assert out["enlaces"] == [["0x10", "0x20"]]          # quien llama → la llamada, también hacia atrás
    with pytest.raises(ValueError, match="parecidas: FUN_20"):
        rc.grafo_llamadas(FakeCallGraph(), r"C:\x.exe", "fun")
    with pytest.raises(ValueError, match="adelante"):
        rc.grafo_llamadas(FakeCallGraph(), r"C:\x.exe", "entry", hacia="arriba")


class FakeDotnet:
    """REA gestionado simulado: artefacto, miembros (completos o parciales), frontera nativa y vistas paginadas."""

    # Por tipo: (métodos, cadenas #US). «global» la cargan dos tipos: debe contarse una sola vez.
    PER = {"<Module>": (1, [{"token": "0x70000001", "value": "global"}]),
           "App.Main": (4, [{"token": "0x70000001", "value": "global"},
                            {"token": "0x70000010", "value": "https://api.example.test/v1"}]),
           "App.Net": (1, [{"token": "0x70000020", "value": "hola"}])}

    def __init__(self, parcial=False, gestionado=True, modulo_nativo=False):
        self.calls, self.parcial, self.gestionado, self.modulo_nativo = [], parcial, gestionado, modulo_nativo

    def call(self, name, args, limit=None):
        self.calls.append((name, args))
        if name == "inspect_managed_artifact":
            assert args["path"].startswith("/")  # POSIX: /mnt/… desde Windows, la ruta local en Linux
            status = "managed" if self.gestionado else "native"
            out = {"parent_evidence_id": "ev_art", "summary": {
                "artifact": {"sha256": "ab" * 32}, "classification": {"status": status},
                "pe": {"cli": {"runtime_version": "v4.0.30319"}}, "module": {"mvid": "m-1", "name": "App.dll"},
                "assembly": {"name": "App", "version": "1.2.0.0", "public_key": {"token": "0011"}},
                "reported_counts": {"references": 3, "resources": 1}}}
        elif name == "inspect_managed_members" and "type_names" in args:
            # Partición: más de 2 tipos o App.Big (que no cabe ni solo) superan el presupuesto.
            sel = args["type_names"]
            if len(sel) > 2 or "App.Big" in sel:
                out = {"parent_evidence_id": "ev_x", "summary": {
                    "reported_counts": {"types": len(sel), "methods": 0, "user_strings": None},
                    "coverage": {"state": "partial", "issues": [{"code": "resource-limit", "detail": "budget"}]}}}
            else:
                strs = {s["token"]: s for t in sel for s in self.PER[t][1]}
                counts = {"types": len(sel), "methods": sum(self.PER[t][0] for t in sel), "fields": len(sel),
                          "member_refs": 7, "exported_types": 0, "user_strings": len(strs)}
                state = "partial" if "<Module>" in sel else "complete"
                out = {"parent_evidence_id": "ev_mem:" + "|".join(sel), "summary": {
                    "reported_counts": counts, "coverage": {"state": state, "issues": []}}}
        elif name == "inspect_managed_members":
            counts = {"types": 4 if self.parcial else 3, "methods": 5, "user_strings": None if self.parcial else 2}
            cov = ({"state": "partial", "issues": [{"code": "resource-limit", "detail": "budget"}]} if self.parcial
                   else {"state": "complete", "issues": []})
            out = {"parent_evidence_id": "ev_mem", "summary": {"reported_counts": counts, "coverage": cov}}
        elif name == "inspect_managed_native_boundaries":
            out = {"cli_native": {"il_only": False, "strong_name_signed": True, "ready_to_run_signature": False},
                   "module_refs": [{"name": "user32.dll"}],
                   "pinvoke_imports": [{"import_scope_name": "user32.dll", "import_name": "", "member_name": "MessageBoxW",
                                        "call_convention": "winapi"}],
                   "native_implementations": [{}, {}],
                   "summary": {"pinvoke_import_count": 1, "mixed_mode_or_native_header": False}}
        elif name == "inspect_analysis_view":
            view = args["view"]
            parent = args["source"]["evidence_id"]
            if parent.startswith("ev_mem:"):
                sel = parent[len("ev_mem:"):].split("|")
                data = ([s for t in sel for s in self.PER[t][1]] if view["collection"] == "user_strings" else
                        [{"declaring_type": t, "name": f"m{i}", "token": f"{t}#{i}", "rva": 16,
                          "body": {"status": "present"}} for t in sel for i in range(self.PER[t][0])])
                if self.modulo_nativo and sel == ["<Module>"] and view["collection"] == "methods":
                    # Como System.Data: cuerpos nativos de C++/CLI y un P/Invoke sin cuerpo (RVA 0).
                    data = [{"name": "n", "rva": 32, "body": {"status": "partial", "issue": "CIL decoding is "
                             "unavailable for native, runtime, unmanaged, or P/Invoke implementations"}},
                            {"name": "DecodePointer", "rva": 0, "body": {"status": "absent", "issue": None}}]
            else:
                types = [{"full_name": "<Module>"}, {"full_name": "App.Main", "method_list": {"count": 4}},
                         {"full_name": "App.Net", "method_list": {"count": 1}}]
                data = {"references": [{"name": f"Ref{i}", "version": "4.0.0.0"} for i in range(3)],
                        "resources": [{"name": "App.resources"}],
                        "types": types + ([{"full_name": "App.Big"}] if self.parcial else []),
                        "user_strings": [{"value": "https://api.example.test/v1"}, {"value": "hola"}]
                        }[view["collection"]]
            o, n = view["offset"], view["limit"]
            nxt = o + n if o + n < len(data) else None
            cov = {"total": len(data), "next_offset": nxt}
            if view["kind"] == "managed":
                out = {"item": data[o:o + n], "coverage": cov}
            else:
                out = {"page": {"rows": data[o:o + n]}, "coverage": cov}
        else:
            raise AssertionError(name)
        return json.dumps({"normalized_result": out}), True


def test_ensamblado_dotnet_resume_identidad_tipos_cadenas_y_pinvoke(tmp_path):
    f = tmp_path / "App.dll"
    f.write_bytes(b"MZ")
    fake = FakeDotnet()
    r = rc.ensamblado_dotnet(fake, str(f), limite=2)
    assert r["gestionado"] and r["ensamblado"]["nombre"] == "App" and r["ensamblado"]["token_clave_publica"] == "0011"
    assert r["runtime_metadatos"] == "v4.0.30319" and r["cli"]["firma_nombre_seguro"] is True
    # Paginación: el límite corta la lista pero el total es el de REA.
    assert r["referencias"] == ["Ref0 4.0.0.0", "Ref1 4.0.0.0"] and r["referencias_total"] == 3
    assert [t["tipo"] for t in r["tipos"]] == ["App.Main", "App.Net"] and r["tipos_total"] == 2
    assert r["cadenas"][0] == "https://api.example.test/v1" and r["cadenas_total"] == 2
    assert r["nativo"]["pinvoke"] == [{"dll": "user32.dll", "funcion": "MessageBoxW", "metodo": "MessageBoxW",
                                       "convencion": "winapi"}]
    assert r["nativo"]["implementaciones_nativas"] == 2 and r["cobertura_miembros"]["estado"] == "complete"
    vistas = [a["view"]["collection"] for n, a in fake.calls if n == "inspect_analysis_view"]
    assert vistas.count("references") == 1 and "user_strings" in vistas


def test_ensamblado_dotnet_grande_se_particiona_por_tipos_y_recupera_todo(tmp_path):
    f = tmp_path / "Big.dll"
    f.write_bytes(b"MZ")
    fake = FakeDotnet(parcial=True)
    r = rc.ensamblado_dotnet(fake, str(f))
    lotes = [a["type_names"] for n, a in fake.calls if n == "inspect_managed_members" and "type_names" in a]
    # <Module> va solo; el lote de 3 se pasa y se parte en mitades; App.Big no cabe ni solo.
    assert lotes == [["<Module>"], ["App.Main", "App.Net", "App.Big"], ["App.Main"], ["App.Net", "App.Big"],
                     ["App.Net"], ["App.Big"]]
    assert r["recuentos"]["methods"] == 6 and r["recuentos"]["fields"] == 3 and r["recuentos"]["member_refs"] == 7
    # «global» la cargan <Module> y App.Main: una sola vez.
    assert r["cadenas_total"] == 3 and sorted(r["cadenas"]) == ["global", "hola", "https://api.example.test/v1"]
    cob = r["cobertura_miembros"]
    assert cob["estado"] == "partial" and cob["particionado"] and cob["inspecciones"] == 6
    assert cob["tipos_sin_examinar"] == ["App.Big"] and cob["motivos"] == ["sin particionar: budget"]
    assert [p["desde"] for p in cob["lotes_parciales"]] == ["<Module>"]
    # Nunca se pide una colección que REA no examinó (la evidencia sin particionar no tiene cadenas).
    assert all(a["source"]["evidence_id"] != "ev_mem" or a["view"]["collection"] == "types"
               for n, a in fake.calls if n == "inspect_analysis_view" and a["view"]["kind"] == "managed-members")


def test_ensamblado_dotnet_volcado_completo_y_no_sobrescribe(tmp_path):
    f = tmp_path / "Big.dll"
    f.write_bytes(b"MZ")
    out = tmp_path / "todo.json"
    r = rc.ensamblado_dotnet(FakeDotnet(parcial=True), str(f), limite=1, salida=str(out))
    d = json.loads(out.read_text(encoding="utf-8"))
    assert len(r["cadenas"]) == 1 and len(d["cadenas"]) == 3 and len(d["metodos"]) == 6
    assert {m["tipo"] for m in d["metodos"]} == {"<Module>", "App.Main", "App.Net"}
    assert [t["tipo"] for t in d["tipos"]] == ["App.Main", "App.Net", "App.Big"] and len(d["referencias"]) == 3
    assert r["volcado"]["metodos"] == 6 and d["pinvoke"][0]["dll"] == "user32.dll"
    with pytest.raises(ValueError):
        rc.ensamblado_dotnet(FakeDotnet(parcial=True), str(f), salida=str(out))
    with pytest.raises(ValueError):
        rc.ensamblado_dotnet(FakeDotnet(), str(f), salida=str(tmp_path / "todo.txt"))


def test_ensamblado_dotnet_no_gestionado_o_inexistente(tmp_path):
    f = tmp_path / "nativo.exe"
    f.write_bytes(b"MZ")
    fake = FakeDotnet(gestionado=False)
    r = rc.ensamblado_dotnet(fake, str(f))
    assert r["gestionado"] is False and [n for n, _ in fake.calls] == ["inspect_managed_artifact"]
    with pytest.raises(ValueError):
        rc.ensamblado_dotnet(FakeDotnet(), str(tmp_path / "no.dll"))


def test_ensamblado_dotnet_module_parcial_solo_por_codigo_nativo_cuenta_como_completo(tmp_path):
    f = tmp_path / "Mixto.dll"
    f.write_bytes(b"MZ")
    r = rc.ensamblado_dotnet(FakeDotnet(parcial=True, modulo_nativo=True), str(f))
    cob = r["cobertura_miembros"]
    # <Module> ya no es un lote parcial: lo que falta es código nativo o P/Invoke, que no tiene CIL.
    assert cob["lotes_parciales"] == [] and cob["metodos_sin_cil"] == {"codigo_nativo": 1, "sin_cuerpo": 1}
    assert cob["tipos_sin_examinar"] == ["App.Big"] and cob["estado"] == "partial"  # App.Big sigue sin caber


class FakeJadx:
    """JADX simulado: búsqueda de clases, una clase con un método sobrecargado y descompilación."""

    CLASES = ["a.b.Main", "a.b.MainHelper", "a.b.Otra"]

    def __init__(self):
        self.calls = []

    def call(self, name, args, limit=None):
        self.calls.append((name, args))
        eng = {"name": "jadx-headless-mcp", "version": "0.7.1", "artifact_sha256": "cd" * 32}
        if name == "search_android_classes":
            out = {"engine": eng, "total_classes": 3, "matches": [c for c in self.CLASES if args["query"] in c],
                   "duplicate_names": []}
        elif name == "inspect_android_class":
            out = {"engine": eng, "class_name": args["class_name"],
                   "methods": [{"name": "<init>", "reported_signature": "<init>(): void", "dex_descriptor": "()V",
                                "overload_index": 0, "is_constructor": True},
                               {"name": "f", "reported_signature": "f(int): void", "overload_index": 0},
                               {"name": "f", "reported_signature": "f(java.lang.String): void", "overload_index": 1}],
                   "fields": [{"name": "MAX", "reported_type": "int", "dex_static_value": 7},
                              {"name": "x", "reported_type": "java.lang.String", "dex_static_value": None}],
                   "inner_classes": ["a.b.Main.Inner"]}
        elif name == "inspect_android_method":
            out = {"engine": eng, "method": {"reported_signature": "f(java.lang.String): void"},
                   "representation": "java", "body_status": "available", "fell_back": False, "markers": [],
                   "source": {"status": "complete", "text": "void f(String s) {\r\n    g(s);\r\n}"}}
        else:
            raise AssertionError(name)
        return json.dumps({"normalized_result": out}), True


def _apk(tmp_path):
    f = tmp_path / "app.apk"
    f.write_bytes(b"PK")
    return str(f)


def test_clase_android_varias_coincidencias_se_listan_sin_inspeccionar(tmp_path):
    fake = FakeJadx()
    r = rc.clase_android(fake, _apk(tmp_path), "Ma")
    assert r["clases"] == ["a.b.Main", "a.b.MainHelper"] and r["coincidencias"] == 2 and "siguiente" in r
    assert [n for n, _ in fake.calls] == ["search_android_classes"]
    assert rc.clase_android(FakeJadx(), _apk(tmp_path), "Nada")["clases"] == []


def test_clase_android_exacta_da_metodos_campos_y_pide_sobrecarga(tmp_path):
    fake = FakeJadx()
    r = rc.clase_android(fake, _apk(tmp_path), "a.b.Main", metodo="f")
    assert r["clase"] == "a.b.Main" and r["metodos_total"] == 3 and r["clases_internas"] == ["a.b.Main.Inner"]
    assert r["campos"] == [{"nombre": "MAX", "tipo": "int", "valor": 7}, {"nombre": "x", "tipo": "java.lang.String"}]
    assert [o["sobrecarga"] for o in r["sobrecargas"]] == [0, 1] and "descompilado" not in r
    assert "inspect_android_method" not in [n for n, _ in fake.calls]


def test_clase_android_descompila_la_sobrecarga_elegida(tmp_path):
    fake = FakeJadx()
    r = rc.clase_android(fake, _apk(tmp_path), "Otra", metodo="f", sobrecarga=1)
    d = r["descompilado"]
    assert r["clase"] == "a.b.Otra" and d["fuente"] == "void f(String s) {\n    g(s);\n}" and not d["recurrio_a_smali"]
    assert fake.calls[-1] == ("inspect_android_method", {"path": _apk(tmp_path), "class_name": "a.b.Otra",
                                                         "method_name": "f", "overload_index": 1})
    with pytest.raises(ValueError):
        rc.clase_android(FakeJadx(), _apk(tmp_path), "Otra", metodo="noexiste")
    with pytest.raises(ValueError):
        rc.clase_android(FakeJadx(), str(tmp_path / "x.txt"), "Otra")


class FakeFlutter:
    """REA simulado para una app Flutter: build por ABI, resumen del snapshot y pool de cadenas paginado."""

    def __init__(self, flutter=True, pkg_al_menos=4):
        self.calls, self.flutter, self.al_menos = [], flutter, pkg_al_menos

    def call(self, name, args, limit=None):
        self.calls.append((name, args))
        if name == "identify_flutter_build":
            abis = [{"abi": x, "libapp": {"bytes": 10, "sha256": "aa", "snapshot_hash": "h1"},
                     "libflutter": {"build_id": "b-" + x, "dart_version": None, "toolchain_lines": ["clang 9"]}}
                    for x in ("arm64-v8a", "x86_64")] if self.flutter else []
            out = {"target": {"sha256": "ff" * 32, "bytes": 99}, "flutter_detected": self.flutter, "abis": abis}
        elif name == "inspect_dart_aot":
            out = {"parent_evidence_id": "ev_dart", "summary": {
                "abi": args.get("abi", "arm64-v8a"), "coverage": "partial",
                "libapp": {"coverage": "complete", "sections": [{"name": "_kDartIsolateSnapshotData", "size": 5,
                                                                 "kind": 3}]},
                "string_pool": {"coverage": "partial", "package_uri_count_at_least": self.al_menos,
                                "dart_uri_count_at_least": 3, "class_like_token_count_at_least": 9}}}
        elif name == "inspect_analysis_view":
            v = args["view"]
            data = {"package_uris": ["package:app/main.dart", "package:app/home.dart", "package:http/http.dart",
                                     "package:flutter/widgets.dart"],
                    "dart_uris": ["dart:async/future.dart", "dart:core", "dart:async-patch8", "dart:ui/text.dart"]}
            rows = data[v["collection"]]
            o = v["offset"]
            page = rows[o:o + 2]  # páginas pequeñas para probar la paginación
            nxt = o + 2 if o + 2 < len(rows) else None
            out = {"items": page, "coverage": {"next_offset": nxt}}
        else:
            raise AssertionError(name)
        return json.dumps({"normalized_result": out}), True


def test_app_flutter_agrupa_paquetes_y_librerias_del_sdk(tmp_path):
    f = tmp_path / "app.apk"
    f.write_bytes(b"PK")
    fake = FakeFlutter()
    r = rc.app_flutter(fake, str(f), abi="x86_64")
    assert r["flutter"] and [a["abi"] for a in r["abis"]] == ["arm64-v8a", "x86_64"] and r["snapshot_hash"] == "h1"
    assert r["paquetes"][0] == {"paquete": "app", "archivos": 2} and r["paquetes_total"] == 3
    assert r["sdk_dart"] == ["dart:async", "dart:core", "dart:ui"]  # sin el resto «async-patch8»
    assert r["pool_cadenas"]["uris_package_devueltas"] == 4 and r["paquetes_incompletos"]  # cobertura parcial
    assert ("inspect_dart_aot", {"path": str(f), "detail": "summary", "abi": "x86_64"}) in fake.calls
    assert sum(1 for n, a in fake.calls if n == "inspect_analysis_view"
               and a["view"]["collection"] == "package_uris") == 2


def test_app_flutter_sin_libapp_o_ruta_invalida(tmp_path):
    f = tmp_path / "nativa.apk"
    f.write_bytes(b"PK")
    fake = FakeFlutter(flutter=False)
    r = rc.app_flutter(fake, str(f))
    assert r["flutter"] is False and [n for n, _ in fake.calls] == ["identify_flutter_build"]
    with pytest.raises(ValueError):
        rc.app_flutter(FakeFlutter(), str(tmp_path / "app.ipa"))


class FakeApple:
    """REA simulado: inventario y proyección de una app de Apple con un bundle principal y un servicio XPC."""

    def __init__(self):
        self.calls = []

    def call(self, name, args, limit=None):
        self.calls.append(name)
        if name == "open_binary":
            return json.dumps({"result": {"format": "zip"}}), True
        if name == "close_binary":
            return json.dumps({"result": None}), True
        if name == "inspect_artifact":
            return json.dumps({"inspection_id": "ai_1"}), True
        assert name == "project_apple_application_graph" and args["inventory_evidence"] == [{"inspection_id": "ai_1"}]
        out = {"root_sha256": "ee" * 32, "root_format": "zip", "platforms": ["macos"], "application_roots": ["X.app"],
               "bundles": [{"path": "X.app", "role": "application", "info_plist_path": "X.app/Contents/Info.plist",
                            "executable_candidates": ["X.app/Contents/MacOS/X"], "signing_paths": ["s"]},
                           {"path": "X.app/Contents/XPCServices/H.xpc", "role": "xpc-service",
                            "info_plist_path": "X.app/Contents/XPCServices/H.xpc/Contents/Info.plist",
                            "executable_candidates": [], "signing_paths": []}],
               "components": {"executables": [{"path": "X.app/Contents/MacOS/X", "format": "mach-o-universal"}],
                              "privileged_helpers": [], "launchd_plists": [{"path": "X.app/Contents/L.plist"}]},
               "symlinks": ["a"], "runtime_families": ["native"], "bridge_candidates": [],
               "coverage": {"status": "complete-within-inventory"}}
        return json.dumps({"normalized_result": out}), True


def _info_plist():
    import plistlib

    return plistlib.dumps({"CFBundleIdentifier": "org.x", "CFBundleShortVersionString": "1.0", "LSUIElement": "1",
                           "NSCameraUsageDescription": "Para escanear", "SUFeedURL": "https://x.test/appcast.xml",
                           "CFBundleURLTypes": [{"CFBundleURLSchemes": ["xapp"]}],
                           "NSAppTransportSecurity": {"NSAllowsArbitraryLoads": True,
                                                      "NSExceptionDomains": {"b.test": {}}}})


def test_mapa_app_apple_desde_zip_lee_info_plist_sin_extraer(tmp_path):
    import zipfile

    z = tmp_path / "X.app.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("X.app/Contents/Info.plist", _info_plist())
    fake = FakeApple()
    r = rc.mapa_app_apple(fake, str(z))
    main, xpc = r["bundles"]
    assert main["info_plist"]["id"] == "org.x" and main["info_plist"]["sin_icono_en_dock"] is True
    assert main["info_plist"]["esquemas_url"] == ["xapp"] and main["firmado"] and main["ejecutables"] == ["X"]
    assert main["info_plist"]["transporte"] == {"permite_http": True, "dominios_excepcion": ["b.test"]}
    assert "info_plist" not in xpc  # su Info.plist no está en el zip: no se inventa
    assert r["permisos_privacidad"] == ["NSCameraUsageDescription"] and r["launchd"] == ["X.app/Contents/L.plist"]
    assert r["papeles"] == {"application": 1, "xpc-service": 1} and fake.calls[-1] == "close_binary"
    assert not list(tmp_path.glob("X.app"))  # nada extraído a disco


def test_mapa_app_apple_desde_carpeta_app_y_rutas_invalidas(tmp_path):
    app = tmp_path / "X.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_bytes(_info_plist())
    r = rc.mapa_app_apple(FakeApple(), str(app))
    assert r["bundles"][0]["info_plist"]["canal_actualizaciones"] == "https://x.test/appcast.xml"
    with pytest.raises(ValueError):
        rc.mapa_app_apple(FakeApple(), str(tmp_path / "otra.exe"))


def _prop(name, text=None, strings=None, reg=None):
    raw = (text.encode() + b"\0").hex() if text is not None else "00000001"
    return {"name": name, "hex": raw, "truncated": False,
            "derived": {"strings": strings, "cells": None, "reg": reg}}


class FakeDevicetree:
    """REA simulado: árbol completo de un devicetree con CPU, memoria, memoria reservada y dos dispositivos."""

    def __init__(self):
        self.calls = []

    def call(self, name, args, limit=None):
        self.calls.append((name, args))
        assert name == "inspect_devicetree" and args["detail"] == "complete"
        nodes = [
            {"path": "/", "parent": None, "properties": [_prop("compatible", strings=["acme,board"])]},
            {"path": "/cpus/cpu@0", "parent": "/cpus", "properties": [
                _prop("device_type", "cpu"), _prop("compatible", strings=["arm,cortex-a53"])]},
            {"path": "/cpus/cpu@1", "parent": "/cpus", "properties": [
                _prop("device_type", "cpu"), _prop("compatible", strings=["arm,cortex-a53"])]},
            {"path": "/memory@0", "parent": "/", "properties": [
                _prop("device_type", "memory"), _prop("reg", reg=[{"address": "0x0", "size": "0x40000000"}])]},
            {"path": "/reserved-memory/fw@0", "parent": "/reserved-memory", "properties": [
                _prop("reg", reg=[{"address": "0x1000", "size": "0x100"}])]},
            {"path": "/soc/serial@100", "parent": "/soc", "properties": [
                _prop("compatible", strings=["acme,uart"]), _prop("reg", reg=[{"address": "0x100", "size": "0x40"}])]},
            {"path": "/soc/i2c@200", "parent": "/soc", "properties": [
                _prop("compatible", strings=["acme,i2c"]), _prop("status", "disabled")]},
        ]
        out = {"artifact": {"sha256": "dd" * 32}, "header": {"version": 17}, "reservations": [], "nodes": nodes,
               "references": [{"source": "/", "property": "interrupt-parent", "target": "/soc/gic"}],
               "summary": {"model": "Acme", "compatible": ["acme,board"], "stdout_path": "serial0:115200n8",
                           "aliases": [{"name": "serial0", "path": "/soc/serial@100"}]},
               "coverage": {"status": "complete"}}
        return json.dumps({"normalized_result": out}), True


def _dtb(tmp_path, magic=b"\xd0\x0d\xfe\xed"):
    f = tmp_path / "placa.dtb"
    f.write_bytes(magic + b"\0" * 36)
    return str(f)


def test_devicetree_resume_placa_cpu_memoria_y_dispositivos(tmp_path):
    r = rc.devicetree_hw(FakeDevicetree(), _dtb(tmp_path))
    assert r["placa"]["modelo"] == "Acme" and r["alias"] == {"serial0": "/soc/serial@100"}
    assert r["cpus"] == {"total": 2, "modelos": ["arm,cortex-a53"]}  # device_type decodificado del hex
    assert r["memoria"] == [{"direccion": "0x0", "tamano": "0x40000000"}] and not r["memoria_la_fija_el_arranque"]
    assert [m["ruta"] for m in r["memoria_reservada"]] == ["/reserved-memory/fw@0"]
    assert r["dispositivos_total"] == 5 and r["activos"] == 4 and r["desactivados"] == 1  # las CPU cuentan
    i2c = next(d for d in r["dispositivos"] if d["ruta"] == "/soc/i2c@200")
    assert i2c == {"ruta": "/soc/i2c@200", "compatible": ["acme,i2c"], "activo": False, "estado": "disabled"}
    assert r["fabricantes"] == {"acme": 3, "arm": 2}


def test_devicetree_filtro_y_entradas_invalidas(tmp_path):
    r = rc.devicetree_hw(FakeDevicetree(), _dtb(tmp_path), filtro="UART")
    assert [d["ruta"] for d in r["dispositivos"]] == ["/soc/serial@100"] and r["dispositivos_mostrados_de"] == 1
    assert r["dispositivos"][0]["direccion"] == "0x100"
    with pytest.raises(ValueError):
        rc.devicetree_hw(FakeDevicetree(), _dtb(tmp_path, magic=b"MZ\0\0"))
    with pytest.raises(ValueError):
        rc.devicetree_hw(FakeDevicetree(), str(tmp_path / "no.dtb"))


def test_dt_strings_solo_texto_imprimible_terminado_en_nul():
    assert rc._dt_strings(_prop("x", "okay")) == ["okay"]
    assert rc._dt_strings({"hex": "6f6b"}) == []  # sin NUL final
    assert rc._dt_strings({"hex": "0102ff00"}) == []  # binario
    assert rc._dt_strings({"hex": "61006200"}) == ["a", "b"]


@pytest.fixture
def wsl_falso(monkeypatch, tmp_path):
    """WSL simulado: la carpeta temporal de Ubuntu es una carpeta local y cp/rm se registran (y cp copia)."""
    import shutil
    from pathlib import Path

    from eolfi import rea_client

    staging = tmp_path / "ubuntu-salidas" / "firmware-x"
    orders = []

    def run(argv, timeout=900):
        orders.append(argv)
        if argv[0] == "cp":  # cp -r … <temporal de Ubuntu> /mnt/<unidad>/<destino>
            drive, rest = argv[-1][len("/mnt/"):].split("/", 1)
            shutil.copytree(staging, Path(f"{drive.upper()}:/{rest}"))
        return 0, ""

    monkeypatch.setattr(rea_client, "wsl_staging_dir", lambda prefix: str(staging))
    monkeypatch.setattr(rea_client, "wsl_run", run)
    return {"staging": staging, "orders": orders}


class FakeUnblob:
    """REA simulado: extract_firmware de una imagen con núcleo LZMA (falla su extractor) y un squashfs."""

    def __init__(self):
        self.calls = []

    def call(self, name, args, limit=None):
        self.calls.append((name, args))
        assert name == "extract_firmware"
        root = "fw.bin_extract/100-900.squashfs_v4_le_extract"
        files = [{"relative_path": "fw.bin_extract/0-100.unknown", "size": 100, "mime_type": None},
                 {"relative_path": f"{root}/bin/busybox", "size": 400, "sha256": "b1", "mime_type": "application/x-sharedlib"},
                 {"relative_path": f"{root}/usr/sbin/uhttpd", "size": 50, "sha256": "u1",
                  "mime_type": "application/x-pie-executable; charset=binary"},
                 {"relative_path": f"{root}/etc/config/network", "size": 10, "mime_type": "text/plain"}]
        out = {"engine": {"name": "unblob", "version": "26.6.4"}, "selection": {"sha256": "aa" * 32},
               "output_directory": args["output_directory"], "coverage": "partial", "files": files,
               "published_bytes": 560,
               "chunks": [{"input_path": f"$output/{root}/bin/busybox", "handler": "elf32"},
                          {"input_path": f"$output/{root}/usr/sbin/uhttpd", "handler": "elf32"},
                          {"input_path": "$input", "handler": "squashfs_v4_le"}],
               "unpublished_entries": [{"relative_path": f"{root}/bin/sh", "kind": "symlink"},
                                       {"relative_path": f"{root}/bin/ls", "kind": "symlink"}],
               "extraction_gaps": [{"kind": "unknown-chunk-handler", "input_path": "$input",
                                    "root_file_range": {"offset": 0, "length": 100}, "dependencies": []},
                                   {"kind": "missing-dependency", "input_path": "$input", "range": {"offset": 5, "length": 1},
                                    "dependencies": ["sasquatch"]},
                                   {"kind": "unpublished-entry", "input_path": f"$output/{root}/bin/sh"}],
               "diagnostics": [{"input_path": "$input", "stage": "lzma",
                                "report": {"command": "7z x -y k.lzma -so", "exit_code": 127, "severity": "WARNING",
                                           "stderr": "N3o6IG5vdCBmb3VuZAo=", "__typename__": "ExtractCommandFailedReport"}},
                               {"input_path": "$output/a.tar", "stage": "tar",
                                "report": {"severity": "WARNING", "path": "../fuera", "reason": "path traversal",
                                           "__typename__": "ExtractionProblem"}}],
               "depth_limited_paths": [], "extraction_continuations": [{"id": "c1", "instruction": "Usa un rango menor"}]}
        return json.dumps({"normalized_result": out}), True


@pytest.mark.skipif(os.name != "nt", reason="copia WSL→Windows: solo existe con el REA de WSL en Windows")
def test_extraer_firmware_resume_lo_extraido_y_lo_que_falta(tmp_path, wsl_falso):
    fw = tmp_path / "fw.bin"
    fw.write_bytes(b"\0" * 64)
    dest = tmp_path / "salida"
    wsl_falso["staging"].mkdir(parents=True)  # lo que REA publicaría en Ubuntu
    fake = FakeUnblob()
    r = rc.extraer_firmware(fake, str(fw), str(dest), profundidad=4)
    args = fake.calls[0][1]
    # Unblob escribe en Ubuntu (en /mnt no puede ser dueño del destino) y Eolfi copia a Windows y limpia.
    assert args["output_directory"] == str(wsl_falso["staging"]) and args["max_depth"] == 4
    assert [o[0] for o in wsl_falso["orders"]] == ["cp", "rm"] and r["copia_a_windows"]["correcta"]
    assert wsl_falso["orders"][0][-1].startswith("/mnt/") and dest.is_dir()
    assert args["publication_timeout_ms"] == rc.FIRMWARE_PUBLISH_MS and args["path"].startswith("/mnt/")
    assert r["destino"] == str(dest) and r["motor"] == "unblob 26.6.4" and r["archivos"] == 4
    assert [p["pieza"] for p in r["piezas"]] == ["0-100.unknown", "100-900.squashfs_v4_le_extract"]
    assert r["piezas"][1] == {"pieza": "100-900.squashfs_v4_le_extract", "archivos": 3, "bytes": 460}
    assert r["binarios_elf"] == 2 and r["elf_mayores"][0]["ruta"].endswith("bin/busybox")
    assert r["tipos"]["application/x-pie-executable"] == 1 and r["tipos"]["desconocido"] == 1
    assert r["no_publicadas"] == {"symlink": 2} and r["extractores_que_faltan"] == ["sasquatch"]
    assert r["huecos_por_tipo"] == {"unknown-chunk-handler": 1, "missing-dependency": 1, "unpublished-entry": 1}
    assert [h["tipo"] for h in r["huecos"]] == ["unknown-chunk-handler", "missing-dependency"]
    assert r["fallos_de_extractor"][0]["codigo"] == 127 and r["fallos_de_extractor"][0]["error"] == "7z: not found"
    tar = r["fallos_de_extractor"][1]
    assert "orden" not in tar and tar["detalle"] == {"path": "../fuera", "reason": "path traversal"}
    assert r["fallos_por_tipo"] == {"lzma:ExtractCommandFailedReport": 1, "tar:ExtractionProblem": 1}


@pytest.mark.skipif(os.name != "nt", reason="copia WSL→Windows: solo existe con el REA de WSL en Windows")
def test_extraer_firmware_conserva_la_temporal_si_la_copia_falla(tmp_path, wsl_falso, monkeypatch):
    from eolfi import rea_client

    fw = tmp_path / "fw.bin"
    fw.write_bytes(b"\0")
    orders = []
    monkeypatch.setattr(rea_client, "wsl_run", lambda argv, timeout=900: (orders.append(argv), (1, "cp: nombre inválido"))[1])
    r = rc.extraer_firmware(FakeUnblob(), str(fw), str(tmp_path / "salida"))
    assert [o[0] for o in orders] == ["cp"]  # sin rm: la extracción sigue en Ubuntu
    assert r["copia_a_windows"] == {"desde_wsl": str(wsl_falso["staging"]), "correcta": False,
                                    "errores": "cp: nombre inválido"} and r["rootfs"] is None


def test_extraer_firmware_valida_antes_de_llamar_a_rea(tmp_path, wsl_falso):
    fw = tmp_path / "fw.bin"
    fw.write_bytes(b"x")
    (tmp_path / "ya").mkdir()
    fake = FakeUnblob()
    for dest in (str(tmp_path / "ya"), "relativa", str(tmp_path / "no" / "existe")):
        with pytest.raises(ValueError):
            rc.extraer_firmware(fake, str(fw), dest)
    with pytest.raises(ValueError):
        rc.extraer_firmware(fake, str(tmp_path / "nada.bin"), str(tmp_path / "s"))
    assert fake.calls == []
    if os.name == "nt":  # en Windows, una ruta de Ubuntu la valida el REA de WSL, sin copia
        r = rc.extraer_firmware(fake, str(fw), "/home/u/salida")
        assert fake.calls[0][1]["output_directory"] == "/home/u/salida" and r["destino"] == "/home/u/salida"
        assert r["copia_a_windows"] is None and wsl_falso["orders"] == []


def test_extraer_firmware_con_rea_local_publica_en_el_destino_sin_copia(tmp_path, wsl_falso, monkeypatch):
    """Linux o macOS (simulado en cualquier sistema): REA es local, recibe rutas locales y escribe en el destino."""
    from pathlib import Path

    monkeypatch.setattr(rc, "_rea_local", lambda: True)
    fw = tmp_path / "fw.bin"
    fw.write_bytes(b"\0")
    dest = tmp_path / "salida"

    class Crea(FakeUnblob):
        def call(self, name, args, limit=None):
            _rootfs(Path(args["output_directory"]))
            return super().call(name, args, limit)

    fake = Crea()
    r = rc.extraer_firmware(fake, str(fw), str(dest))
    args = fake.calls[0][1]
    assert args["path"] == str(fw.resolve()) and args["output_directory"] == str(dest)
    assert r["copia_a_windows"] is None and wsl_falso["orders"] == [] and r["destino"] == str(dest)
    assert r["rootfs"]["sistemas_de_archivos"][0]["distribucion"]["DISTRIB_ID"] == "OpenWrt"
    with pytest.raises(ValueError):
        rc.extraer_firmware(fake, str(fw), "relativa")


def _rootfs(base):
    root = base / "fw.bin_extract" / "100-900.squashfs_v4_le_extract"
    for d in ("etc/init.d", "bin", "usr/sbin", "etc/ssl"):
        (root / d).mkdir(parents=True)
    (root / "etc" / "openwrt_release").write_text("DISTRIB_ID='OpenWrt'\nDISTRIB_RELEASE='25.12.6'\n"
                                                  "DISTRIB_TARGET='ath79/generic'\n# comentario\n")
    (root / "etc" / "passwd").write_text("root:x:0:0:root:/root:/bin/ash\ndaemon:*:1:1:daemon:/var:/bin/false\n"
                                         "ftp:*:55:55:ftp:/home/ftp:/bin/false\n")
    (root / "etc" / "shadow").write_text("root::0:0:99999:7:::\ndaemon:*:0:0:99999:7:::\n")
    for s in ("dropbear", "uhttpd"):
        (root / "etc" / "init.d" / s).write_text("#!/bin/sh /etc/rc.common\n")
    # ELF de 32 bits big-endian MIPS (e_machine 8) y ELF de 64 bits little-endian aarch64 (183).
    (root / "bin" / "busybox").write_bytes(b"\x7fELF\x01\x02\x01" + b"\0" * 11 + (8).to_bytes(2, "big") + b"\0" * 40)
    (root / "usr" / "sbin" / "x").write_bytes(b"\x7fELF\x02\x01\x01" + b"\0" * 11 + (183).to_bytes(2, "little"))
    (root / "etc" / "ssl" / "server.key").write_text("-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n")
    return root


def test_revisar_rootfs_distribucion_cuentas_servicios_y_claves(tmp_path):
    _rootfs(tmp_path)
    r = rc.revisar_rootfs(tmp_path)
    (fs,) = r["sistemas_de_archivos"]
    assert fs["raiz"] == "fw.bin_extract/100-900.squashfs_v4_le_extract"
    assert fs["distribucion"] == {"DISTRIB_ID": "OpenWrt", "DISTRIB_RELEASE": "25.12.6", "DISTRIB_TARGET": "ath79/generic"}
    assert fs["cuentas_con_shell"] == [{"usuario": "root", "uid": "0", "shell": "/bin/ash"}] and fs["uid_0"] == ["root"]
    assert fs["contrasena_vacia"] == ["root"] and fs["bloqueadas"] == ["daemon"]
    assert fs["servicios"] == ["dropbear", "uhttpd"] and fs["servicios_total"] == 2
    assert fs["elf_por_arquitectura"] == {"mips 32 bits BE": 1, "aarch64 64 bits LE": 1}
    assert fs["claves_privadas"] == ["etc/ssl/server.key"]
    assert "AAAA" not in json.dumps(r)  # el contenido de la clave no sale
    with pytest.raises(ValueError):
        rc.revisar_rootfs(tmp_path / "no")


@pytest.mark.skipif(os.name != "nt", reason="copia WSL→Windows: solo existe con el REA de WSL en Windows")
def test_extraer_firmware_incluye_la_revision_del_rootfs_si_el_destino_existe(tmp_path, wsl_falso):
    fw = tmp_path / "fw.bin"
    fw.write_bytes(b"\0")
    dest = tmp_path / "salida"

    class Crea(FakeUnblob):  # REA publica en la carpeta temporal de Ubuntu; Eolfi la copia al destino
        def call(self, name, args, limit=None):
            _rootfs(wsl_falso["staging"])
            return super().call(name, args, limit)

    r = rc.extraer_firmware(Crea(), str(fw), str(dest))
    assert r["rootfs"]["sistemas_de_archivos"][0]["distribucion"]["DISTRIB_ID"] == "OpenWrt"


def test_uci_oculta_secretos_pero_no_las_opciones_de_autenticacion():
    secs = rc._uci("config wifi-iface 'w0'\n\toption key 'secreto123'\n\toption ssid 'Casa'\n"
                   "\toption sae_password 'x'\n\toption PasswordAuth 'on'\n\tlist network 'lan'\n"
                   "# comentario\nconfig defaults\n\toption input 'REJECT'\n")
    assert secs[0] == {"_tipo": "wifi-iface", "_nombre": "w0", "key": "<oculto>", "ssid": "Casa",
                       "sae_password": "<oculto>", "PasswordAuth": "on", "network": ["lan"]}
    assert secs[1] == {"_tipo": "defaults", "_nombre": None, "input": "REJECT"}


def test_red_openwrt_web_ssh_cortafuegos_y_wifi(tmp_path):
    conf = tmp_path / "etc" / "config"
    conf.mkdir(parents=True)
    (conf / "uhttpd").write_text("config uhttpd 'main'\n\tlist listen_http '0.0.0.0:80'\n"
                                 "\tlist listen_https '0.0.0.0:443'\n\toption redirect_https '1'\n")
    (conf / "dropbear").write_text("config dropbear\n\toption PasswordAuth 'off'\n\toption Port '2222'\n")
    (conf / "firewall").write_text("config defaults\n\toption input 'REJECT'\nconfig zone\n\toption name 'wan'\n"
                                   "\toption input 'REJECT'\n\toption masq '1'\n\tlist network 'wan'\n"
                                   "config rule\n\toption name 'Allow-Ping'\nconfig redirect\n\toption dest_port '22'\n")
    (conf / "wireless").write_text("config wifi-iface 'default_radio0'\n\toption ssid 'OpenWrt'\n"
                                   "\toption encryption 'psk2'\n\toption key 'clave-secreta'\n")
    r = rc._red_openwrt(tmp_path / "etc")
    assert r["web"] == [{"instancia": "main", "http": ["0.0.0.0:80"], "https": ["0.0.0.0:443"], "redirige_a_https": True}]
    assert r["ssh"] == [{"puerto": "2222", "interfaz": "todas", "contrasena": False, "root_con_contrasena": True}]
    assert r["cortafuegos"] == {"entrada_por_defecto": "REJECT", "reglas": 1, "redirecciones": 1,
                                "zonas": [{"zona": "wan", "entrada": "REJECT", "reenvio": None, "nat": True,
                                           "redes": ["wan"]}]}
    assert r["wifi"] == [{"ssid": "OpenWrt", "cifrado": "psk2", "modo": None, "desactivada": False}]
    assert r["generada_al_arrancar"] == ["network"] and "clave-secreta" not in json.dumps(r)
    assert rc._red_openwrt(tmp_path / "otro") is None


class FakeWasm:
    """REA simulado para WASM: el resumen deja la evidencia en la sesión y las vistas leen sus facetas."""

    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def call(self, name, args, limit=None):
        self.calls.append((name, args))
        if name == self.fail:
            return "REA_WABT_BIN_DIRECTORY must be an absolute tool directory.", False
        if name == "inspect_wasm_artifact":
            ev = "ev_" + ("b" if args["path"].endswith("v2.wasm") else "a") * 64
            return json.dumps({"normalized_result": {
                "parent_evidence_id": ev, "artifact": {"path": args["path"], "sha256": "cd" * 32},
                "summary": {"bytes": 1000, "validation": "valid", "debug_name_metadata": "not-present",
                            "custom_section_warnings": [], "available_counts": {"sections": 2, "imports": 2, "exports": 3},
                            "wat": {"sha256": "ef" * 32, "code_units": 5000},
                            "tool_profile": {"release": "1.0.42", "commands": [
                                {"tool": "wasm-validate", "sha256": "11" * 32}, {"tool": "wasm-objdump", "sha256": "22" * 32}]}}}}), True
        if name == "inspect_analysis_view":
            facet, lim = args["view"]["facet"], args["view"]["limit"]
            rows = {"imports": ['(import "env" "abort" (func (;0;) (type 1)))', '(import "a" "b\\"c" (memory (;0;) 1))'],
                    "exports": ['(export "memory" (memory 0))', '(export "run" (func 7))', "(rara)"],
                    "sections": [{"kind": "Type", "bytes": 10, "description": "count: 2"},
                                 {"kind": "Code", "bytes": 900, "description": "count: 4"}],
                    "glue": [{"artifact": {"path": "/x/carga.mjs", "sha256": "99" * 32}, "parse_status": "complete",
                              "references": [{"value": "../dist/m.wasm", "line": 4, "column": 21,
                                              "candidate_paths": ["/x/m.wasm"], "association": "basename-candidates"}]}],
                    }[facet]
            return json.dumps({"normalized_result": {"item": rows[:lim], "coverage": {"total": len(rows)}}}), True
        assert name == "compare_wasm_interfaces"
        return json.dumps({"normalized_result": {
            "coverage": "complete-within-inputs", "summary": {"added": 1, "removed": 0, "changed": 1, "unchanged": 2, "unknown": 0},
            "changes": [{"direction": "export", "module": None, "name": "run", "state": "changed",
                         "left": [{"signature": {"kind": "func", "params": ["i32", "i32"], "results": ["i32"]}}],
                         "right": [{"signature": {"kind": "func", "params": ["i64"], "results": []}}], "reason": None},
                        {"direction": "export", "module": None, "name": "nueva", "state": "added", "left": [],
                         "right": [{"wat_form": "(func)"}], "reason": None},
                        {"direction": "import", "module": "env", "name": "abort", "state": "unchanged", "left": [], "right": []}]}}), True


def test_modulo_wasm_resume_validez_secciones_e_interfaz(tmp_path):
    w = tmp_path / "m.wasm"
    w.write_bytes(b"\0asm\1\0\0\0")
    fake = FakeWasm()
    r = rc.modulo_wasm(fake, str(w))
    first = fake.calls[0][1]
    # Sin el WAT entero (no cabe en la respuesta) y con más tiempo por orden de WABT que los 30 s de REA.
    assert first == {"path": str(w.resolve()), "detail": "summary", "command_timeout_ms": rc.WASM_TIMEOUT_MS}
    views = [a["view"]["facet"] for n, a in fake.calls if n == "inspect_analysis_view"]
    assert views == ["sections", "imports", "exports"]
    assert all(a["source"] == {"kind": "retained-evidence", "evidence_id": "ev_" + "a" * 64}
               for n, a in fake.calls if n == "inspect_analysis_view")
    assert r["validacion"] == "valid" and r["recuentos"] == {"sections": 2, "imports": 2, "exports": 3}
    assert r["wabt"]["version"] == "1.0.42" and [h["herramienta"] for h in r["wabt"]["herramientas"]] == [
        "wasm-validate", "wasm-objdump"]
    assert r["secciones"][1] == {"tipo": "Code", "bytes": 900, "detalle": "count: 4"}
    assert r["importaciones"] == [{"modulo": "env", "nombre": "abort", "tipo": "func"},
                                  {"modulo": "a", "nombre": 'b\\"c', "tipo": "memory"}]
    assert r["exportaciones"][:2] == [{"nombre": "memory", "tipo": "memory", "indice": 0},
                                      {"nombre": "run", "tipo": "func", "indice": 7}]
    assert r["exportaciones"][2] == {"wat": "(rara)"}  # lo que no se entiende se conserva tal cual
    assert "comparacion" not in r and "no se ejecuta" in r["limites"]


def test_modulo_wasm_dice_desde_que_javascript_se_carga(tmp_path):
    w, js = tmp_path / "m.wasm", tmp_path / "carga.mjs"
    w.write_bytes(b"\0asm")
    js.write_text('const p = new URL("../dist/m.wasm", import.meta.url);', encoding="utf-8")
    fake = FakeWasm()
    r = rc.modulo_wasm(fake, str(w), js=[str(js)])
    assert fake.calls[0][1]["glue_paths"] == [str(js.resolve())]
    (g,) = r["cargado_desde"]
    assert g["lectura"] == "complete" and g["sha256"] == "99" * 32
    (ref,) = g["referencias"]
    assert ref["literal"] == "../dist/m.wasm" and (ref["linea"], ref["columna"]) == (4, 21)
    assert ref["asociacion"] == "basename-candidates" and "solo coincide el nombre" in ref["significa"]
    sin_js = FakeWasm()
    r2 = rc.modulo_wasm(sin_js, str(w))
    assert "glue_paths" not in sin_js.calls[0][1] and "cargado_desde" not in r2
    assert "glue" not in [a["view"]["facet"] for n, a in sin_js.calls if n == "inspect_analysis_view"]
    with pytest.raises(ValueError, match="no existe el JavaScript"):
        rc.modulo_wasm(FakeWasm(), str(w), js=[str(tmp_path / "no.js")])


def test_modulo_wasm_recorta_y_lo_dice(tmp_path):
    w = tmp_path / "m.wasm"
    w.write_bytes(b"\0asm")
    r = rc.modulo_wasm(FakeWasm(), str(w), limite=1)
    assert len(r["importaciones"]) == 1 and r["recortado"] == {"importaciones": True, "exportaciones": True}


def test_modulo_wasm_compara_las_interfaces_de_dos_versiones(tmp_path):
    a, b = tmp_path / "v1.wasm", tmp_path / "v2.wasm"
    a.write_bytes(b"\0asm")
    b.write_bytes(b"\0asm")
    fake = FakeWasm()
    r = rc.modulo_wasm(fake, str(a), str(b))
    (cmp_args,) = [x for n, x in fake.calls if n == "compare_wasm_interfaces"]
    assert cmp_args == {"left": {"kind": "retained-evidence", "evidence_id": "ev_" + "a" * 64},
                        "right": {"kind": "retained-evidence", "evidence_id": "ev_" + "b" * 64}, "scope": "both"}
    c = r["comparacion"]
    assert c["resumen"]["changed"] == 1 and c["cobertura"] == "complete-within-inputs"
    assert [x["nombre"] for x in c["cambios"]] == ["run", "nueva"]  # lo que no cambió no se lista
    assert c["cambios"][0]["antes"] == ["(i32, i32) -> i32"] and c["cambios"][0]["despues"] == ["(i64) -> ()"]
    assert c["cambios"][1]["despues"] == ["(func)"]  # sin firma tipada: la forma WAT tal cual


def test_firma_wasm_de_memorias_tablas_y_globales():
    assert rc._firma_wasm({"signature": {"kind": "memory", "minimum": "1", "maximum": None, "address_type": "i32",
                                         "shared": False, "page_size": "65536"}}) == "memoria 1..sin límite (i32)"
    assert rc._firma_wasm({"signature": {"kind": "table", "element": "funcref", "minimum": "2", "maximum": "8",
                                         "address_type": "i32", "shared": True}}) == "tabla funcref 2..8 compartida"
    assert rc._firma_wasm({"signature": {"kind": "global", "value_type": "f64", "mutable": True}}) == "global f64 mutable"


def test_modulo_wasm_valida_y_explica_como_instalar_wabt(tmp_path):
    with pytest.raises(ValueError, match="no existe"):
        rc.modulo_wasm(FakeWasm(), str(tmp_path / "no.wasm"))
    w = tmp_path / "m.wasm"
    w.write_bytes(b"\0asm")
    with pytest.raises(RuntimeError, match="instalar-wabt"):
        rc.modulo_wasm(FakeWasm(fail="inspect_wasm_artifact"), str(w))

    class Grande(FakeWasm):
        def call(self, name, args, limit=None):
            return '{"error": {"code": "resource_constraint", "message": "WABT output exceeded the 33554432-byte output budget"}}', False

    with pytest.raises(RuntimeError, match="demasiado grande") as exc:
        rc.modulo_wasm(Grande(), str(w))
    assert "instalar-wabt" not in str(exc.value)  # no es que falte WABT


def _thin(cpu, size=64):
    import struct
    return b"\xcf\xfa\xed\xfe" + struct.pack("<i", cpu) + b"\0" * (size - 8)


def _fat(*pieces):
    import struct
    head, off = struct.pack(">II", 0xCAFEBABE, len(pieces)), 4096
    blobs = []
    for cpu, blob in pieces:
        head += struct.pack(">iiIII", cpu, 0, off, len(blob), 12)
        blobs.append((off, blob))
        off += 4096
    out = bytearray(head.ljust(4096, b"\0"))
    for o, blob in blobs:
        out[o:o + len(blob)] = blob
        out.extend(b"\0" * (o + 4096 - len(out)))
    return bytes(out)


def test_macho_slices_universal_fino_y_class_de_java():
    arm, x86 = 0x0100000C, 0x01000007
    fat = _fat((x86, _thin(x86)), (arm, _thin(arm)))
    assert [s["arquitectura"] for s in rc.macho_slices(fat)] == ["x86_64", "arm64"]
    assert rc.macho_slices(fat)[1]["desplazamiento"] == 8192
    assert rc.macho_slices(_thin(arm)) == [{"arquitectura": "arm64", "desplazamiento": 0, "bytes": 64}]
    with pytest.raises(ValueError, match="Java"):
        rc.macho_slices(b"\xca\xfe\xba\xbe\x00\x00\x00\x37" + b"\0" * 40)   # .class: versión 55 como «número»
    with pytest.raises(ValueError, match="Mach-O"):
        rc.macho_slices(b"MZ" + b"\0" * 62)


def test_swift_nominal_moderno_antiguo_y_no_literal():
    assert rc.swift_nominal("_$s5Maccy13LargeTextViewV11EditorStateC4initACycfc") == (
        "Maccy", "LargeTextView.EditorState", "clase")
    assert rc.swift_nominal("_TtCV5Maccy13LargeTextView11EditorState::init") == (
        "Maccy", "LargeTextView.EditorState", "clase")
    assert rc.swift_nominal("_$s10AppIntents12IntentDialogVMa") == ("AppIntents", "IntentDialog", "estructura")
    assert rc.swift_nominal("_$s7Combine16ObservableObjectPA2A0bC9PublisherC") == (
        "Combine", "ObservableObject", "protocolo")
    assert rc.swift_nominal("_$s4Demo4ModeO8allCasesSayACGvgZ") == ("Demo", "Mode", "enumeracion")
    for raw in ("_$s5Maccy", "FUN_100001234", "_TtC5Maccy", "_$s00punycode3AppC", "_$s0B3AppC"):
        assert rc.swift_nominal(raw) is None


def test_swift_contexto_sustituciones_palabras_extensiones_y_privados():
    cases = {
        "_$sScP13userInitiatedScPvgZ": ("Swift", "TaskPriority", "estructura"),
        "_$sSS9UTF16ViewV5index_8offsetBySS5IndexVAF_SitF": ("Swift", "String.UTF16View", "estructura"),
        "_$ss6HasherV8_combineyys6UInt32VF": ("Swift", "Hasher", "estructura"),
        "_$sS2Dyxq_GycfC": ("Swift", "Dictionary", "estructura"),
        "_$sSo7NSEventC6AppKitE10SpecialKeyV3f20AEvgZ": ("(Objective-C/C)", "NSEvent.SpecialKey", "estructura"),
        "_$s8Dispatch0A8WorkItemCMa": ("Dispatch", "DispatchWorkItem", "clase"),
        "_$s10AppIntents0A6IntentPAAE04openA7WhenRunSbvgZ": ("AppIntents", "AppIntent", "protocolo"),
        "_TtCV5Maccy22MouseMovedViewModifierP33_91A000BA8386CF59E70CA8865D68EE4211Coordinator::init":
            ("Maccy", "MouseMovedViewModifier.Coordinator", "clase"),
    }
    for raw, want in cases.items():
        assert rc.swift_nominal(raw) == want, raw
    # Nivel de módulo (funciones y variables globales): se lee el módulo, sin tipo.
    assert rc.swift_context("_$ss9_typeName_9qualifiedSSypXp_SbtF") == ("Swift", "", None)
    assert rc.swift_context("_$s2os0A4_log_3dso0B0__ySo0a1_B7_type_ta_SVSo03OS_a1_B0Cs12StaticStringVF")[:2] == (
        "os", "")


class FakeSwift:
    """REA simulado (Ghidra): secciones, nombres Swift de la app, de un paquete incluido y de un framework, y clases
    Objective-C importadas."""

    def __init__(self):
        self.calls, self.opened = [], None

    def call(self, name, args, limit=None):
        self.calls.append(name)
        if name == "open_binary":
            self.opened = args["path"]
            assert Path(self.opened).read_bytes()[:4] == b"\xcf\xfa\xed\xfe"   # la porción, no el universal
            return json.dumps({"result": {"format": "mach-o", "architecture": "arm64"}}), True
        if name == "close_binary":
            return json.dumps({"result": None}), True
        if name == "binary_overview":
            return json.dumps({"normalized_result": {"procedure_count": 900, "segments": [
                {"name": "__text", "start": "0x100001000", "end": "0x100100000"},
                {"name": "__stubs", "start": "0x100100000", "end": "0x100101000"}]}}), True
        if name == "analyze_swift_types":
            row = lambda a, n: {"address": a, "name": n, "mangled_names": [n]}  # noqa: E731
            cats = {"classes": [row("0x100002000", "_TtC1X11AppDelegate::init"),
                                row("0x100002100", "_$s1X11AppDelegateC5applyyyF"),
                                row("0x100002200", "_$s8Settings4PaneC4bodyQrvg"),
                                row("0x100002300", "_$s7SwiftUI4ViewP1XE4bodyQrvg"),
                                # especializaciones de frameworks del sistema compiladas en __text
                                row("0x100002400", "_$s7SwiftUI5ImageVMa"),
                                row("0x100002500", "_$s6Darwin7timevalVMa")],
                    "structs": [row("0x100100010", "_$s7SwiftUI4TextVMa"),
                                row("0x100100020", "_$s7SwiftUI4TextV7verbatimACSS_tcfC")],
                    "other": [row("0x100100030", "_$sScP13userInitiatedScPvgZ"),
                              row("0x100100040", "_$ss9_typeName_9qualifiedSSypXp_SbtF"),
                              row("0x100100050", "_$s00punycode3AppC")]}
            out = {"total": 6, "categories": {k: {"count": len(v), "items": v} for k, v in cats.items()},
                   "unclassified": cats["other"]}
            return json.dumps({"normalized_result": out}), True
        assert name == "get_objc_classes"
        lib = "/System/Library/Frameworks/AppKit.framework/Versions/C/AppKit::"
        return json.dumps({"normalized_result": {"classes": [
            {"address": "EXTERNAL:0x1", "name": lib + "_OBJC_CLASS_$_NSAlert"},
            {"address": "0x100200000", "name": "_OBJC_CLASS_$_NSAlert"},
            {"address": "EXTERNAL:0x2", "name": "/usr/lib/libobjc.A.dylib::_OBJC_CLASS_$_NSObject"}]}}), True


def _swift_app_zip(tmp_path):
    import plistlib
    import zipfile
    arm, x86 = 0x0100000C, 0x01000007
    z = tmp_path / "X.app.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("X.app/Contents/Info.plist", plistlib.dumps({"CFBundleExecutable": "X"}))
        f.writestr("X.app/Contents/MacOS/X", _fat((x86, _thin(x86)), (arm, _thin(arm))))
    return z


def test_tipos_swift_apple_separa_app_incluidos_y_frameworks(tmp_path):
    fake = FakeSwift()
    r = rc.tipos_swift_apple(fake, str(_swift_app_zip(tmp_path)), ruta_rea=lambda p: p)
    assert fake.calls == ["open_binary", "binary_overview", "analyze_swift_types", "get_objc_classes", "close_binary"]
    assert not Path(fake.opened).exists()   # la porción temporal se borra
    assert r["ejecutable"] == "X.app/Contents/MacOS/X" and r["arquitecturas"] == ["x86_64", "arm64"]
    assert r["arquitectura_analizada"] == "arm64" and r["modulo_de_la_app"] == "X"
    assert r["tipos_de_la_app"] == [{"tipo": "AppDelegate", "clase": "clase"}]
    assert r["tipos_de_la_app_total"] == 1 and r["tipos_de_la_app_por_clase"] == {"clase": 1}
    assert r["modulos_incluidos"] == {"Settings": {"tipos": 1, "muestra": ["Pane"]}}
    assert r["protocolos_implementados"] == ["SwiftUI.View"]
    assert r["frameworks_swift_usados"] == {
        "SwiftUI": {"tipos": 2, "por_clase": {"estructura": 2}, "muestra": ["Image", "Text"]},
        "Swift": {"tipos": 1, "por_clase": {"estructura": 1}, "muestra": ["TaskPriority"]},
        "Darwin": {"tipos": 1, "por_clase": {"estructura": 1}, "muestra": ["timeval"]}}
    assert r["clases_objc_importadas"] == {"AppKit": ["NSAlert"], "libobjc.A.dylib": ["NSObject"]}
    assert r["nombres_swift"] == 11 and r["nombres_globales"] == 1 and r["nombres_sin_resolver"] == 1
    assert r["procedimientos"] == 900


def test_tipos_swift_apple_arquitectura_pedida_y_errores(tmp_path):
    fake = FakeSwift()
    z = _swift_app_zip(tmp_path)
    with pytest.raises(ValueError, match="arm64e"):
        rc.tipos_swift_apple(fake, str(z), arquitectura="arm64e")
    assert fake.calls == []
    with pytest.raises(ValueError, match="no existe"):
        rc.tipos_swift_apple(fake, str(tmp_path / "nada.app"))
    app = tmp_path / "Y.app" / "Contents" / "MacOS"
    app.mkdir(parents=True)
    (app.parent / "Info.plist").write_bytes(__import__("plistlib").dumps({"CFBundleExecutable": "Y"}))
    (app / "Y").write_bytes(_thin(0x01000007))
    r = rc.tipos_swift_apple(FakeSwift(), str(tmp_path / "Y.app"), ruta_rea=lambda p: p)
    assert r["ejecutable"] == "Y.app/Contents/MacOS/Y" and r["arquitectura_analizada"] == "x86_64"


def test_tipos_swift_apple_desde_ipa_y_macho_suelto(tmp_path):
    import plistlib
    import zipfile
    ipa = tmp_path / "Z.ipa"
    with zipfile.ZipFile(ipa, "w") as f:
        f.writestr("Payload/Z.app/Frameworks/F.framework/Info.plist", plistlib.dumps({"CFBundleExecutable": "F"}))
        f.writestr("Payload/Z.app/Info.plist", plistlib.dumps({"CFBundleExecutable": "Z"}))
        f.writestr("Payload/Z.app/Z", _thin(0x0100000C))
    r = rc.tipos_swift_apple(FakeSwift(), str(ipa), ruta_rea=lambda p: p)
    assert r["ejecutable"] == "Payload/Z.app/Z" and r["arquitecturas"] == ["arm64"] and r["modulo_de_la_app"] == "Z"
    loose = tmp_path / "herramienta"
    loose.write_bytes(_thin(0x0100000C))
    assert rc.tipos_swift_apple(FakeSwift(), str(loose), ruta_rea=lambda p: p)["ejecutable"] == "herramienta"
    lower = tmp_path / "x"   # el módulo «X» de FakeSwift: la app se reconoce sin distinguir mayúsculas
    lower.write_bytes(_thin(0x0100000C))
    r = rc.tipos_swift_apple(FakeSwift(), str(lower), ruta_rea=lambda p: p)
    assert r["modulo_de_la_app"] == "X" and r["tipos_de_la_app"] == [{"tipo": "AppDelegate", "clase": "clase"}]
    tool = tmp_path / "tool.zip"
    with zipfile.ZipFile(tool, "w") as f:
        f.writestr("LEEME.txt", "x")
        f.writestr("bin/tool", _thin(0x01000007))
    assert rc.tipos_swift_apple(FakeSwift(), str(tool), ruta_rea=lambda p: p)["ejecutable"] == "bin/tool"
    (tmp_path / "W.ipa").write_bytes(b"PK\x05\x06" + b"\0" * 18)   # zip vacío: sin app
    with pytest.raises(ValueError, match="ejecutable de la app"):
        rc.tipos_swift_apple(FakeSwift(), str(tmp_path / "W.ipa"))


def test_tipos_swift_apple_descifra_los_sin_resolver_con_swift_demangle(tmp_path):
    z = _swift_app_zip(tmp_path)
    asked = []

    def demangle(names):
        asked.append(names)
        return ["static Swift.TaskPriority.userInitiated.getter : Swift.TaskPriority"]

    r = rc.tipos_swift_apple(FakeSwift(), str(z), ruta_rea=lambda p: p, demangle=demangle)
    unresolved = r["nombres_sin_resolver"]
    assert len(asked) == (1 if unresolved else 0)
    if unresolved:   # el falso REA solo deja uno sin resolver si el lector no entiende «Sc…»
        assert r["sin_resolver_descifrados"] == {
            "disponible": True, "pedidos": 1, "descifrados": 1, "por_modulo": {"Swift": 1},
            "muestra": ["static Swift.TaskPriority.userInitiated.getter : Swift.TaskPriority"]}
    names = ["$sX9", "$sY0", "noesswift"]   # nombres que el lector no entiende
    fake = FakeSwift()
    real_call = fake.call

    def call(name, args, limit=None):   # tres nombres que el lector no entiende
        text, ok = real_call(name, args, limit)
        if name == "analyze_swift_types":
            items = [{"address": "0x100002000", "name": n, "mangled_names": [n]} for n in names]
            text = json.dumps({"normalized_result": {"categories": {"other": {"items": items}}}})
        return text, ok

    fake.call = call
    table = {"$sX9": "(extension in Maccy):__C.NSWindow.shake() -> ()", "$sY0": "$sY0", "noesswift": "noesswift"}
    r = rc.tipos_swift_apple(fake, str(z), ruta_rea=lambda p: p, demangle=lambda ns: [table[n] for n in ns])
    d = r["sin_resolver_descifrados"]
    assert r["nombres_sin_resolver"] == 3 and d["disponible"] and d["pedidos"] == 3 and d["descifrados"] == 1
    assert d["por_modulo"] == {rc.SWIFT_OBJC_MODULE: 1}
    r = rc.tipos_swift_apple(fake, str(z), ruta_rea=lambda p: p, demangle=lambda ns: None)
    assert r["sin_resolver_descifrados"] == {"disponible": False}
    assert rc.tipos_swift_apple(fake, str(z), ruta_rea=lambda p: p)["sin_resolver_descifrados"] is None


class FakeNative:
    """REA simulado para inspect_go_binary / inspect_rust_binary con la forma real de REA (gh.exe, sudo-rs)."""

    def __init__(self, result):
        self.result, self.calls = result, []

    def call(self, name, args, limit=None):
        self.calls.append((name, args))
        return json.dumps({"normalized_result": self.result}), True


def _exe(tmp_path, name="x.exe"):
    f = tmp_path / name
    f.write_bytes(b"MZ" + b"\0" * 62)
    return f


def test_binario_go_modulo_dependencias_y_compilacion(tmp_path):
    exe = _exe(tmp_path)
    deps = [{"path": "example.com/a", "version": "v1.2.0", "sum": "h1:x", "replacement": None},
            {"path": "example.com/b", "version": "v0.1.0", "sum": "", "replacement": None},
            {"path": "example.com/c", "version": "v2.0.0", "sum": "", "replacement": {"path": "../c", "version": ""}}]
    fake = FakeNative({"artifact": {"sha256": "aa" * 32, "bytes": 64}, "format": "pe", "architecture": "amd64",
                       "bits": 64, "build_info": {"go_version": "go1.26.8", "module": {
                           "path": "example.com/app/cmd/app", "complete": True, "unparsed_lines": [],
                           "main": {"path": "example.com/app", "version": "v1.0.0"}, "dependencies": deps,
                           "settings": [{"key": "GOOS", "value": "windows"}, {"key": "CGO_ENABLED", "value": "0"},
                                        {"key": "vcs.revision", "value": "abc"}, {"key": "-compiler", "value": "gc"}]}}})
    r = rc.binario_go(fake, str(exe), limite=2)
    assert fake.calls == [("inspect_go_binary", {"path": str(exe)})]
    assert r["es_go"] is True and r["go"] == "go1.26.8" and r["paquete"] == "example.com/app/cmd/app"
    assert r["modulo"] == {"ruta": "example.com/app", "version": "v1.0.0"}
    assert r["dependencias_total"] == 3 and len(r["dependencias"]) == 2
    assert r["reemplazos"] == 1 and r["sin_suma"] == 1
    assert r["compilacion"] == {"GOOS": "windows", "CGO_ENABLED": "0", "vcs.revision": "abc"}
    assert r["otros_ajustes"] == ["-compiler"] and r["completo"] is True and r["sha256"] == "aa" * 32


def test_binario_go_sin_informacion_y_ruta_invalida(tmp_path):
    r = rc.binario_go(FakeNative({"format": "pe", "build_info": None}), str(_exe(tmp_path)))
    assert r["es_go"] is None and "no prueba" in r["aviso"]
    with pytest.raises(ValueError, match="no existe"):
        rc.binario_go(FakeNative({}), str(tmp_path / "nada.exe"))


def test_binario_rust_raiz_dependencias_y_sin_cargo_auditable(tmp_path):
    exe = _exe(tmp_path, "sudo-rs")
    pkgs = [{"name": "glob", "version": "0.3.3", "source": "crates.io", "dependencies": [], "root": False},
            {"name": "libc", "version": "0.2.183", "source": "crates.io", "dependencies": [], "root": False},
            {"name": "sudo-rs", "version": "0.2.13", "source": "local", "dependencies": [0, 1], "root": False}]
    meta = {"format_version": 8, "packages": pkgs, "root_package_index": None, "dependency_edges": [],
            "cyclic_dependency_indices": []}
    r = rc.binario_rust(FakeNative({"artifact": {"sha256": "bb" * 32}, "format": "elf", "auditable_metadata": meta,
                                    "rustc_commit": None}), str(exe))
    assert r["cargo_auditable"] is True and r["raiz"] == {"nombre": "sudo-rs", "version": "0.2.13", "origen": "local"}
    assert r["dependencias_directas"] == ["glob 0.3.3", "libc 0.2.183"]
    assert r["paquetes_total"] == 3 and r["por_origen"] == {"crates.io": 2, "local": 1}
    meta["root_package_index"] = 0
    r = rc.binario_rust(FakeNative({"auditable_metadata": meta}), str(exe))
    assert r["raiz"]["nombre"] == "glob" and r["dependencias_directas"] == []
    r = rc.binario_rust(FakeNative({"format": "pe", "auditable_metadata": None}), str(exe))
    assert r["cargo_auditable"] is False and ".dep-v0" in r["aviso"]


class FakeSigrok:
    """REA simulado: decode_signal_recording en dos páginas (I2C + EDID) e inspect_signal_decoders."""

    LINES = ["139-139 i2c-1: Start", "149-221 i2c-1: Address write: 50", "242-326 i2c-1: Data write: 00",
             "326-400 i2c-1: Data read: 53", "149-326 edid-1: Offset: 0", "400-480 i2c-1: Data read: 0A",
             "480-560 edid-1: Product 0x021b", "basura sin formato"]

    def __init__(self, page=5):
        self.calls, self.page = [], page

    def call(self, name, args, limit=None):
        self.calls.append((name, dict(args)))
        if name == "inspect_signal_decoders":
            if args.get("decoder"):
                out = {"help_lines": [{"line_number": 1, "text": "ID: uart"}, {"line_number": 2, "text": "Name: UART"}],
                       "output_window": {"examined": 81, "matching": 81, "returned": 2, "has_more": False}}
            else:
                out = {"decoders": [{"id": "edid", "name": "Extended Display Identification Data"}],
                       "output_window": {"examined": 111, "matching": 1, "returned": 1, "has_more": False}}
            return json.dumps({"normalized_result": out}), True
        assert name == "decode_signal_recording" and args["line_limit"] == rc.SIGNAL_PAGE
        start = args["line_offset"]
        chunk = self.LINES[start:start + self.page]
        out = {"artifact": {"sha256": "ab" * 32, "bytes": 10}, "annotations_text": "\n".join(chunk),
               "output_window": {"total_lines": len(self.LINES), "returned_lines": len(chunk),
                                 "has_more": start + len(chunk) < len(self.LINES)},
               "tool": {"version_banner": "sigrok-cli 0.7.2\n\nLibraries", "sha256": "cd" * 32},
               "diagnostics": "", "hardware_acquisition": "not-performed"}
        return json.dumps({"normalized_result": out}), True


def test_decodificar_senal_junta_paginas_bytes_y_ultimo_decodificador(tmp_path):
    rec = tmp_path / "edid.sr"
    rec.write_bytes(b"PK\x03\x04")
    fake = FakeSigrok()
    r = rc.decodificar_senal(fake, str(rec), "i2c:scl=scl:sda=sda,edid", ruta_rea=lambda p: "/mnt/x/" + Path(p).name)
    assert [c[1]["line_offset"] for c in fake.calls] == [0, 5]          # dos páginas
    assert fake.calls[0][1]["path"] == "/mnt/x/edid.sr" and fake.calls[0][1]["annotations"] is None
    assert r["lineas"] == 8 and r["lineas_leidas"] == 8 and not r["cortado"] and r["lineas_sin_formato"] == 1
    assert r["por_decodificador"] == {"i2c": 5, "edid": 2}
    assert r["datos"] == {"i2c": {"bytes": 3, "hex": "00 53 0A", "texto": ".S\n"}}
    assert r["superior"] == {"decodificador": "edid", "muestra": ["Offset: 0", "Product 0x021b"]}
    assert r["herramienta"] == {"version": "sigrok-cli 0.7.2", "sha256": "cd" * 32}
    assert r["sha256"] == "ab" * 32 and r["adquisicion_de_hardware"] == "not-performed"


def test_decodificar_senal_valida_antes_de_llamar_a_rea(tmp_path, monkeypatch):
    fake = FakeSigrok()
    with pytest.raises(ValueError, match="no existe"):
        rc.decodificar_senal(fake, str(tmp_path / "nada.sr"), "uart:rx=TX")
    rec = tmp_path / "x.sr"
    rec.write_bytes(b"x")
    with pytest.raises(ValueError, match="pila de decodificadores"):
        rc.decodificar_senal(fake, str(rec), "  ")
    monkeypatch.setattr(rc, "MAX_SIGNAL_FILE", 0)
    with pytest.raises(ValueError, match="mayor de"):
        rc.decodificar_senal(fake, str(rec), "uart:rx=TX")
    assert fake.calls == []


def test_decodificar_senal_respeta_el_maximo_de_lineas(tmp_path, monkeypatch):
    rec = tmp_path / "x.sr"
    rec.write_bytes(b"x")
    monkeypatch.setattr(rc, "MAX_SIGNAL_LINES", 6)
    r = rc.decodificar_senal(FakeSigrok(page=3), str(rec), "i2c:scl=scl:sda=sda,edid")
    assert r["lineas_leidas"] == 6 and r["lineas"] == 8 and r["cortado"]


def test_decodificadores_senal_lista_o_ayuda():
    fake = FakeSigrok()
    assert rc.decodificadores_senal(fake, "edid") == {
        "examinados": 111, "coinciden": 1, "hay_mas": False,
        "decodificadores": {"edid": "Extended Display Identification Data"}}
    assert fake.calls[-1] == ("inspect_signal_decoders", {"limit": 200, "query": "edid"})
    r = rc.decodificadores_senal(fake, decodificador="uart")
    assert r["ayuda"] == ["ID: uart", "Name: UART"] and fake.calls[-1][1] == {"limit": 200, "decoder": "uart"}
