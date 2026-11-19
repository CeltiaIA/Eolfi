# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Herramientas · reimplementar lo que hay en Alejandría
# Enunciado: Lee en Alejandría cómo normaliza Eolfi el texto en la búsqueda de su biblioteca (función _normal del archivo library.py de Eolfi) y escribe en Python una función normalizar(texto) que haga exactamente lo mismo. Pruébala con ejecutar_python antes de responder. Responde SOLO con el código final en un bloque ```python```.
# Motor: gemma_q4 (gemma-4-12b-it-q4_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:47:15.891943+00:00
# SHA-256 del código: f0169fc36a25081efda19ae18bea737195fc4f99ae066d727b3ce71ffe3701d5

import unicodedata

def normalizar(texto):
    texto_normalizado = unicodedata.normalize('NFKD', texto.casefold())
    return ''.join(c for c in texto_normalizado if not unicodedata.combining(c))
