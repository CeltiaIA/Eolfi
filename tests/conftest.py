import os

# Las pruebas no dependen del .env del usuario (ni leen sus secretos).
os.environ["EOLFI_NO_DOTENV"] = "1"
