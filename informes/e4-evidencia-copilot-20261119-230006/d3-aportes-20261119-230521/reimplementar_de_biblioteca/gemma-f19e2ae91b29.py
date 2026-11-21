# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Herramientas · reimplementar lo que hay en Alejandría
# Enunciado: Lee en Alejandría cómo normaliza Eolfi el texto en la búsqueda de su biblioteca (función _normal del archivo library.py de Eolfi) y escribe en Python una función normalizar(texto) que haga exactamente lo mismo. Pruébala con ejecutar_python antes de responder. Responde SOLO con el código final en un bloque ```python```.
# Motor: gemma (gemma-4-12b-it-q5_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:33:35.742438+00:00
# SHA-256 del código: f19e2ae91b29697b5597e81067ded0fd585034ceddf63b49464eb9a350f5e1c5

import unicodedata

def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in texto if not unicodedata.combining(c))
