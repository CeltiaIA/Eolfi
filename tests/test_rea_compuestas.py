"""Herramientas compuestas sobre REA: revisar modelo, explicar binario y reimplementar función (13/11/2026)."""
import json
import os

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
