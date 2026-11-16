"""Tamaño de los tensores K: se acepta solo si los desplazamientos del propio archivo lo confirman (17/11/2026).

El identificador de tipo no distingue los formatos históricos de las cuantizaciones K, así que el auditor no los da
por buenos. Pero un tensor con sucesor es testigo: su tamaño estándar, alineado, tiene que acabar justo donde empieza
el siguiente. Estas pruebas fijan cuándo ese testigo basta y cuándo no."""
import struct

import pytest

from eolfi import modelos

Q4_K, Q6_K, F32 = 12, 14, 0


def _cadena(texto):
    raw = texto.encode()
    return struct.pack("<Q", len(raw)) + raw


def gguf(path, tensores, *, cola=b""):
    """``tensores``: lista de (nombre, dims, tipo, bytes reales). Se colocan seguidos, alineados a 32."""
    meta = [("general.architecture", "gemma")]
    cab = b"GGUF" + struct.pack("<IQQ", 3, len(tensores), len(meta))
    for clave, valor in meta:
        cab += _cadena(clave) + struct.pack("<I", 8) + _cadena(valor)
    datos = b""
    for nombre, dims, tipo, tam in tensores:
        datos += b"\0" * (-len(datos) % 32)
        cab += _cadena(nombre) + struct.pack("<I", len(dims)) + b"".join(struct.pack("<Q", d) for d in dims)
        cab += struct.pack("<IQ", tipo, len(datos))
        datos += b"\0" * tam
    path.write_bytes(cab + b"\0" * (-len(cab) % 32) + datos + cola)
    return path


def k(nombre, tipo=Q4_K, filas=256, columnas=2, tam=None):
    """Tensor K de ``filas`` × ``columnas``; por defecto con su tamaño estándar (superbloque de 256)."""
    estandar = filas * columnas // 256 * modelos.K_STANDARD[tipo][1]
    return (nombre, [filas, columnas], tipo, estandar if tam is None else tam)


def test_los_testigos_confirman_el_tamano_y_el_archivo_queda_verificado(tmp_path):
    r = modelos.audit(gguf(tmp_path / "m.gguf", [k("a"), k("b"), ("norma", [8], F32, 32), k("c")]))
    assert r["estado"] == "estructura_verificada", r
    assert r["bytes_sobrantes"] == 0 and r["tipos_no_cubiertos"] == {} and r["incognitas"] == []
    assert r["tamanos_k"]["testigos_por_tipo"] == {"12": 2}            # «c» es el último: no es testigo
    assert any("desplazamientos" in limite for limite in r["limites"])


def test_con_el_tamano_confirmado_los_bytes_pegados_al_final_se_detectan(tmp_path):
    r = modelos.audit(gguf(tmp_path / "m.gguf", [k("a"), k("b")], cola=b"MZ" + b"x" * 62))
    assert r["estado"] == "fallido" and r["bytes_sobrantes"] == 64
    assert "Bytes sobrantes tras los tensores" in r["errores"]


def test_un_archivo_truncado_en_el_ultimo_tensor_k_se_detecta(tmp_path):
    p = gguf(tmp_path / "m.gguf", [k("a"), k("b")])
    p.write_bytes(p.read_bytes()[:-40])
    r = modelos.audit(p)
    assert r["estado"] == "fallido" and "Datos de tensor truncados" in r["errores"]


def test_otro_formato_no_se_adivina(tmp_path):
    # Los mismos tipos con bloques de otro tamaño (un formato histórico): los huecos no cuadran con el estándar.
    r = modelos.audit(gguf(tmp_path / "m.gguf", [k("a", tam=2 * 160), k("b", tam=2 * 160), ("norma", [8], F32, 32)]))
    assert r["estado"] == "NO VERIFICADO" and "bytes_sobrantes" not in r and "tamanos_k" not in r
    assert r["tipos_no_cubiertos"] == {"12": 2}


def test_un_solo_testigo_que_discrepa_anula_todo_el_tipo(tmp_path):
    r = modelos.audit(gguf(tmp_path / "m.gguf", [k("a"), k("b", tam=2 * 160), k("c"), ("norma", [8], F32, 32)]))
    assert r["estado"] == "NO VERIFICADO" and r["tipos_no_cubiertos"] == {"12": 3}


def test_cada_tipo_necesita_su_propio_testigo(tmp_path):
    # Q4_K tiene testigo; el único tensor Q6_K es el último y nadie confirma su tamaño.
    r = modelos.audit(gguf(tmp_path / "m.gguf", [k("a"), k("b"), k("z", tipo=Q6_K)]))
    assert r["estado"] == "NO VERIFICADO" and "bytes_sobrantes" not in r
    assert r["tipos_no_cubiertos"] == {"14": 1} and r["tamanos_k"]["testigos_por_tipo"] == {"12": 2}


def test_un_bloque_incompleto_impide_confirmar_el_tipo(tmp_path):
    r = modelos.audit(gguf(tmp_path / "m.gguf", [k("a"), ("raro", [100, 2], Q4_K, 200), ("norma", [8], F32, 32)]))
    assert r["estado"] == "NO VERIFICADO" and r["tipos_no_cubiertos"] == {"12": 2}


@pytest.mark.parametrize("tipo", sorted(modelos.K_STANDARD))
def test_un_tensor_k_solo_sigue_sin_verificarse(tmp_path, tipo):
    r = modelos.audit(gguf(tmp_path / "m.gguf", [k("a", tipo=tipo)]))
    assert r["estado"] == "NO VERIFICADO" and r["tipos_no_cubiertos"] == {str(tipo): 1}


def test_q8_1_nunca_se_confirma(tmp_path):
    r = modelos.audit(gguf(tmp_path / "m.gguf", [("a", [32], 9, 36), ("b", [32], 9, 36), ("norma", [8], F32, 32)]))
    assert r["estado"] == "NO VERIFICADO" and r["tipos_no_cubiertos"] == {"9": 2}
