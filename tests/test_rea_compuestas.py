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
