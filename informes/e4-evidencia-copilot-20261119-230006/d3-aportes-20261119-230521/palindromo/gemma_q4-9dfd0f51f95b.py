# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Código · generar (palíndromo)
# Enunciado: Escribe en Python la función es_palindromo(texto) que devuelva True si el texto es un palíndromo ignorando mayúsculas, espacios, signos de puntuación y tildes (á→a, ü→u…), y False si no.
# Motor: gemma_q4 (gemma-4-12b-it-q4_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:35:35.281736+00:00
# SHA-256 del código: 9dfd0f51f95b9dc9254d328863bfebb82b585527d7a0bf6b5c2570e04f915b8b

import unicodedata
import string

def es_palindromo(texto):
    # Normalizar para eliminar tildes y diéresis
    # NFKD separa el carácter de su acento (ej. 'á' -> 'a' + '´')
    texto_normalizado = unicodedata.normalize('NFKD', texto)
    
    # Filtrar: mantener solo caracteres alfabéricos, convertir a minúsculas
    # y eliminar espacios y puntuación
    resultado = []
    for char in texto_normalizado:
        # unicodedata.category(char) devuelve 'Mn' para marcas de acento
        if unicodedata.category(char) != 'Mn':
            if char.isalnum():
                resultado.append(char.lower())
    
    texto_final = "".join(resultado)
    
    # Comparar con su inverso
    return texto_final == texto_final[::-1]
