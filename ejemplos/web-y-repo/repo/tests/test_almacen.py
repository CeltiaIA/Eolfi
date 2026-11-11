import pytest

from notas import Almacen


def test_anadir_y_listar(tmp_path):
    a = Almacen(tmp_path / "n.json")
    assert a.anadir("pan") == 1 and a.todas() == ["pan"]


def test_nota_vacia(tmp_path):
    with pytest.raises(ValueError):
        Almacen(tmp_path / "n.json").anadir("  ")
