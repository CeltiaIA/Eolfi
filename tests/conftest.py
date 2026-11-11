import os

# Las pruebas no dependen del .env del usuario (ni leen sus secretos).
os.environ["EOLFI_NO_DOTENV"] = "1"

# Ninguna prueba debe crear ni migrar la base de evidencias real del usuario (~/.eolfi/eolfi.db).
os.environ.setdefault("EOLFI_DB", os.path.join(__import__("tempfile").mkdtemp(prefix="eolfi-pruebas-"), "eolfi.db"))
