import os

# Las pruebas no dependen del .env del usuario (ni leen sus secretos).
os.environ["EOLFI_NO_DOTENV"] = "1"

# 13/11/2026: lanzadas desde un gancho de git (pre-push), heredaban GIT_DIR/GIT_INDEX_FILE apuntando al repositorio
# de Eolfi y las pruebas que crean repositorios temporales escribieron en él. Ninguna prueba ve variables GIT_*.
for _name in [k for k in os.environ if k.upper().startswith("GIT_")]:
    del os.environ[_name]


import pytest


@pytest.fixture(autouse=True)
def _eolas_v2_aislado(tmp_path, monkeypatch):
    """Ninguna prueba lee ni escribe la configuración real de Eolas V2 (ni su clave de API, 12/11/2026)."""
    if "EOLFI_EOLAS_V2_CONFIG" not in os.environ:
        monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(tmp_path / "eolas-v2-prueba.json"))
    monkeypatch.setenv("EOLFI_NO_REA", "1")   # ninguna prueba arranca el REA real del equipo
