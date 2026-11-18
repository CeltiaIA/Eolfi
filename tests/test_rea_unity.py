"""Unity IL2CPP (plan REA, punto 9): `unity_il2cpp` con REA simulado. En vivo se probó con las compilaciones de prueba
de Cpp2IL (PLAN_REA.md, «Unity IL2CPP»)."""
import json
import zipfile

import pytest

from eolfi import rea_compuestas as rc

IMAGES = [{"name": "mscorlib.dll", "type_start": 0, "type_count": 2, "index": 0},
          {"name": "UnityEngine.CoreModule.dll", "type_start": 2, "type_count": 1, "index": 1},
          {"name": "Assembly-CSharp.dll", "type_start": 3, "type_count": 3, "index": 2},
          {"name": "__Generated", "type_start": 6, "type_count": 1, "index": 3}]
TYPES = [{"name": "<Module>", "namespace": "", "method_start": -1, "method_count": 0, "declaring_type": -1, "index": 0},
         {"name": "String", "namespace": "System", "method_start": 0, "method_count": 2, "declaring_type": -1, "index": 1},
         {"name": "MonoBehaviour", "namespace": "UnityEngine", "method_start": 2, "method_count": 1, "declaring_type": -1,
          "index": 2},
         {"name": "Player", "namespace": "Game", "method_start": 3, "method_count": 3, "declaring_type": -1, "index": 3},
         {"name": "State", "namespace": "", "method_start": 6, "method_count": 1, "declaring_type": 3, "index": 4},
         {"name": "<Module>", "namespace": "", "method_start": -1, "method_count": 0, "declaring_type": -1, "index": 5},
         {"name": "IActivationFactory", "namespace": "", "method_start": 7, "method_count": 1, "declaring_type": -1,
          "index": 6}]
METHODS = [{"name": n, "declaring_type": t, "index": i} for i, (n, t) in enumerate(
    [("Concat", 1), ("Trim", 1), ("Invoke", 2), ("Start", 3), ("Update", 3), (".ctor", 3), ("Next", 4), ("Get", 6)])]
ADDRS = [{"state": "code", "address": hex(0x180001000 + 16 * i), "rva": hex(0x1000 + 16 * i), "index": i}
         for i in range(8)]
# Las filas de REA real dan «no-body» con guion; el resumen, «no_body» (Daggerfall Unity, 18/11).
ADDRS[5] = {"state": "no-body", "address": None, "rva": None, "index": 5}
LITS = [{"value": v, "value_base64": None, "index": i} for i, v in enumerate(["Hola mundo", "ok", "ﭐ︀", "Hola mundo",
                                                                            "https://ejemplo.test/api"])]


class FakeIl2cpp:
    """REA simulado: resumen de inspect_il2cpp_metadata y vistas paginadas con los filtros que usa Eolfi."""

    def __init__(self, page=2):
        self.calls, self.args, self.page = [], None, page

    def call(self, name, args, limit=None):
        self.calls.append(name)
        if name == "inspect_il2cpp_metadata":
            self.args = args
            with open(args["path"], "rb") as fh:
                assert fh.read(4) == b"\xaf\x1b\xb1\xfa"
            binary = None
            if "binary_path" in args:
                binary = {"artifact": {"path": args["binary_path"], "sha256": "b" * 64, "bytes": 99},
                          "format": "pe", "architecture": "amd64"}
            return json.dumps({"normalized_result": {"parent_evidence_id": "ev_padre", "summary": {
                "artifact": {"sha256": "a" * 64, "bytes": 1234}, "metadata_version": 31, "binary": binary,
                "counts": {"images": 4, "types": 7, "methods": 8, "string_literals": len(LITS),
                           "method_address_states": {"code": 7, "no_body": 1, "unknown": 0} if binary else None,
                           "generic_method_instances": None}}}}), True
        assert name == "inspect_analysis_view" and args["source"]["evidence_id"] == "ev_padre"
        v = args["view"]
        rows = {"images": IMAGES, "types": TYPES, "methods": METHODS, "method_addresses": ADDRS,
                "string_literals": LITS}[v["collection"]]
        if "image_indices" in v:
            imgs = [IMAGES[i] for i in v["image_indices"]]
            rows = [t for t in rows if any(im["type_start"] <= t["index"] < im["type_start"] + im["type_count"]
                                           for im in imgs)]
        if "declaring_types" in v:
            rows = [r for r in rows if r["declaring_type"] in v["declaring_types"]]
        if "indices" in v:
            rows = [r for r in rows if r["index"] in v["indices"]]
        if "names" in v:
            rows = [r for r in rows if r["name"] in v["names"]]
        off, lim = v["offset"], min(v["limit"], self.page)
        nxt = off + lim if off + lim < len(rows) else None
        return json.dumps({"normalized_result": {"items": rows[off:off + lim],
                                                 "coverage": {"next_offset": nxt, "total": len(rows)}}}), True


META = b"\xaf\x1b\xb1\xfa" + b"\0" * 60


def _windows_build(tmp_path):
    root = tmp_path / "Juego"
    md = root / "Juego_Data" / "il2cpp_data" / "Metadata"
    md.mkdir(parents=True)
    (md / "global-metadata.dat").write_bytes(META)
    (root / "GameAssembly.dll").write_bytes(b"MZ" + b"\0" * 62)
    return root


def test_carpeta_de_windows_separa_juego_y_plataforma(tmp_path):
    fake = FakeIl2cpp()
    r = rc.unity_il2cpp(fake, str(_windows_build(tmp_path)), limite=10)
    assert fake.args["binary_path"].endswith("GameAssembly.dll") and "binary_architecture" not in fake.args
    assert r["origen"] == "carpeta" and r["metadatos"]["version"] == 31
    assert r["binario"]["formato"] == "pe" and r["binario"]["nombre"] == "GameAssembly.dll"
    assert r["ensamblados_del_juego"] == [{"nombre": "Assembly-CSharp.dll", "tipos": 3}]
    assert r["ensamblados_de_la_plataforma"] == {"total": 3, "unity": 1, "net": 1}
    # El anidado lleva el nombre del que lo declara; <Module> no cuenta.
    assert r["tipos_del_juego"] == [{"tipo": "Game.Player", "metodos": 3}, {"tipo": "Game.Player+State", "metodos": 1}]
    assert r["tipos_del_juego_total"] == 2 and r["tipos_completos"]
    assert r["metodos_del_juego"] == {"total": 4, "con_codigo": 3, "sin_cuerpo": 1, "desconocidos": 0,
                                      "completo": True}
    # Cadenas legibles y sin repetir; las páginas de 2 en 2 se recorren enteras.
    assert r["cadenas"] == {"total": 5, "leidas": 5, "muestra": ["Hola mundo", "https://ejemplo.test/api"]}
    assert "detalle_tipo" not in r and "no se ejecutó" in r["aviso"]


def test_detalle_de_un_tipo_con_rva(tmp_path):
    root = _windows_build(tmp_path)
    r = rc.unity_il2cpp(FakeIl2cpp(), str(root), tipo="Player")
    assert r["detalle_tipo"] == {"tipo": "Player", "encontrado": True, "coincidencias": 1,
                                 "ensamblado": "Assembly-CSharp.dll",
                                 "metodos": [{"metodo": "Start", "rva": "0x1030", "estado": "code"},
                                             {"metodo": "Update", "rva": "0x1040", "estado": "code"},
                                             {"metodo": ".ctor", "rva": None, "estado": "no_body"}]}
    assert rc.unity_il2cpp(FakeIl2cpp(), str(root), tipo="NoExiste")["detalle_tipo"] == {
        "tipo": "NoExiste", "encontrado": False}


def test_detalle_acepta_el_nombre_completo_de_la_lista(tmp_path):
    """En vivo (Daggerfall Unity, 18/11): la lista da «DaggerfallWorkshop.Game.GameManager» y --tipo con ese nombre
    salía «no encontrado» porque REA filtra por el nombre corto."""
    root = _windows_build(tmp_path)
    r = rc.unity_il2cpp(FakeIl2cpp(), str(root), tipo="Game.Player")["detalle_tipo"]
    assert r["encontrado"] and r["coincidencias"] == 1 and [m["metodo"] for m in r["metodos"]] == [
        "Start", "Update", ".ctor"]
    r = rc.unity_il2cpp(FakeIl2cpp(), str(root), tipo="Game.Player+State")["detalle_tipo"]
    assert r["encontrado"] and [m["metodo"] for m in r["metodos"]] == ["Next"]
    assert rc.unity_il2cpp(FakeIl2cpp(), str(root), tipo="Otro.Player")["detalle_tipo"] == {
        "tipo": "Otro.Player", "encontrado": False}


def test_nombre_corto_repetido_avisa_de_los_demas(tmp_path):
    extra = {"name": "Player", "namespace": "Red", "method_start": -1, "method_count": 0, "declaring_type": -1,
             "index": 5}
    # El índice 5 (un <Module>) ya cae en Assembly-CSharp; se cambia por otro «Player» de otro espacio de nombres.
    original = TYPES[5]
    TYPES[5] = extra
    try:
        r = rc.unity_il2cpp(FakeIl2cpp(), str(_windows_build(tmp_path)), tipo="Player")["detalle_tipo"]
    finally:
        TYPES[5] = original
    assert r["coincidencias"] == 2 and r["otras"] == ["Red.Player"]


def test_apk_extrae_solo_metadatos_y_binario_de_64_bits(tmp_path):
    apk = tmp_path / "juego.apk"
    with zipfile.ZipFile(apk, "w") as z:
        z.writestr("assets/bin/Data/Managed/Metadata/global-metadata.dat", META)
        z.writestr("lib/armeabi-v7a/libil2cpp.so", b"\x7fELF32")
        z.writestr("lib/arm64-v8a/libil2cpp.so", b"\x7fELF64")
        z.writestr("classes.dex", b"dex")
    fake = FakeIl2cpp()
    r = rc.unity_il2cpp(fake, str(apk))
    assert r["origen"] == "apk" and fake.args["binary_path"].endswith("libil2cpp.so")
    assert r["notas"] == ["metadatos: assets/bin/Data/Managed/Metadata/global-metadata.dat",
                          "binario: lib/arm64-v8a/libil2cpp.so"]
    assert not (tmp_path / "global-metadata.dat").exists()   # se extrae a un temporal que se borra


def test_apk_de_32_bits_y_dat_suelto_dan_nombres_sin_direcciones(tmp_path):
    apk = tmp_path / "viejo.apk"
    with zipfile.ZipFile(apk, "w") as z:
        z.writestr("assets/bin/Data/Managed/Metadata/global-metadata.dat", META)
        z.writestr("lib/armeabi-v7a/libil2cpp.so", b"\x7fELF32")
    fake = FakeIl2cpp()
    r = rc.unity_il2cpp(fake, str(apk))
    assert "binary_path" not in fake.args and r["binario"] is None
    assert any("32 bits" in n for n in r["notas"])
    assert r["metodos_del_juego"] == {"total": 4}   # sin binario no se piden direcciones
    dat = tmp_path / "global-metadata.dat"
    dat.write_bytes(META)
    fake = FakeIl2cpp()
    r = rc.unity_il2cpp(fake, str(dat))
    assert r["origen"] == "metadatos" and r["binario"] is None and r["direcciones"] is None


def test_mach_o_universal_pide_la_porcion_arm64(tmp_path):
    dat = tmp_path / "global-metadata.dat"
    dat.write_bytes(META)
    fw = tmp_path / "UnityFramework"
    fw.write_bytes(b"\xca\xfe\xba\xbe" + b"\0" * 60)
    fake = FakeIl2cpp()
    rc.unity_il2cpp(fake, str(dat), binario=str(fw))
    assert fake.args["binary_architecture"] == "arm64"


@pytest.mark.parametrize("contenido, error", [
    (None, "no existe"),
    ("sin_metadatos", "no hay global-metadata.dat"),
])
def test_errores_de_entrada(tmp_path, contenido, error):
    ruta = tmp_path / "x"
    if contenido:
        ruta.mkdir()
    with pytest.raises(ValueError, match=error):
        rc.unity_il2cpp(FakeIl2cpp(), str(ruta))


def test_apk_sin_il2cpp(tmp_path):
    apk = tmp_path / "mono.apk"
    with zipfile.ZipFile(apk, "w") as z:
        z.writestr("assets/bin/Data/Managed/Assembly-CSharp.dll", b"MZ")
    with pytest.raises(ValueError, match="usa Mono"):
        rc.unity_il2cpp(FakeIl2cpp(), str(apk))
