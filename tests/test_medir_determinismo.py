"""B2: el medidor de determinismo agrupa por huella y alterna frío/caliente (sin motor real)."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("medir_determinismo",
                                              Path(__file__).parents[1] / "tools" / "medir_determinismo.py")
md = importlib.util.module_from_spec(spec)
spec.loader.exec_module(md)


def test_todas_iguales_es_determinista_y_enfria_antes_de_las_impares():
    enfriadas = []
    r = md.medir(lambda: "mismo", 5, enfriar=lambda: enfriadas.append(1))
    assert r["determinista"] and r["distintas"] == 1 and r["identicas"] == 5
    assert [c["estado"] for c in r["corridas"]] == ["frío", "caliente", "frío", "caliente", "frío"]
    assert len(enfriadas) == 3


def test_una_salida_distinta_rompe_el_determinismo():
    textos = iter(["a", "a", "b", "a"])
    r = md.medir(lambda: next(textos), 4)
    assert not r["determinista"] and r["distintas"] == 2 and r["identicas"] == 3
    assert all(c["estado"] == "caliente" for c in r["corridas"])
