# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Código · generar (palíndromo)
# Enunciado: Escribe en Python la función es_palindromo(texto) que devuelva True si el texto es un palíndromo ignorando mayúsculas, espacios, signos de puntuación y tildes (á→a, ü→u…), y False si no.
# Motor: gemma (gemma-4-12b-it-q5_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:07:34.913914+00:00
# SHA-256 del código: 705afbd8d77f82731ceae856930c20c3c191cdf864a415dc7cb6e203c41e41d2

import unicodedata
import string

def es_palindromo(texto):
    # Normalizar para separar tildes de las letras base
    # Ejemplo: 'á' se convierte en 'a' + acento
    texto_normalizado = unicodedata.normalize('NFD', texto)
    
    # Filtrar caracteres:
    # 1. Mantener solo caracteres que no sean marcas de acentuación (Mn)
    # 2. Convertir a minúsculas
    # 3. Eliminar espacios y signos de puntuación
    limpio = ""
    for char in texto_normalizado:
        if unicodedata.category(char) != 'Mn':
            if char.isalnum():
                limpio += char.lower()
    
    # Comparar con su versión invertida
    return limpio == limpio[::-1]
