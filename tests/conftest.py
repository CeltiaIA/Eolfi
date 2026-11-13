import os

# Las pruebas no dependen del .env del usuario (ni leen sus secretos).
os.environ["EOLFI_NO_DOTENV"] = "1"

# Ninguna prueba debe crear ni migrar la base de evidencias real del usuario (~/.eolfi/eolfi.db).
_TMP = __import__("tempfile").mkdtemp(prefix="eolfi-pruebas-")
os.environ.setdefault("EOLFI_DB", os.path.join(_TMP, "eolfi.db"))

# Ni la configuración, ni el estado de ejecución, ni las valoraciones de Eolas V2 del usuario
# (~/.eolfi/eolas-v2*) cambian el resultado de las pruebas ni se escriben desde ellas.
os.environ.setdefault("EOLFI_EOLAS_V2_CONFIG", os.path.join(_TMP, "eolas-v2.json"))
os.environ.setdefault("EOLFI_EOLAS_V2_FEEDBACK", os.path.join(_TMP, "eolas-v2-feedback.jsonl"))

import pytest


@pytest.fixture(autouse=True)
def _eolas_v2_aislado(tmp_path, monkeypatch):
    """Cada prueba con su propia configuración de Eolas V2 (ni la real ni la de otra prueba: perfiles retirados,
    clave de API…) y sin arrancar el REA real del equipo (12/11/2026)."""
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(tmp_path / "eolas-v2-prueba.json"))
    monkeypatch.setenv("EOLFI_NO_REA", "1")
