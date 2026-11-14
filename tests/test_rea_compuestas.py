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
