# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Código · desempaquetar (base64 + zlib)
# Enunciado: Escribe en Python desempaquetar(texto) que reciba una cadena base64 cuyo contenido son datos comprimidos con zlib y devuelva el texto original decodificado como UTF-8.
# Motor: gemma_q4 (gemma-4-12b-it-q4_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:36:28.939916+00:00
# SHA-256 del código: d513cb986e272a73d3921b8bd256b4fb6b254f40cfdf333609795abafe48e580

import base64
import zlib

def desempaquetar(texto):
    # Decodificar la cadena Base64 a bytes
    datos_base64 = base64.b64decode(texto)
    # Descomprimir los bytes usando zlib
    datos_comprimidos = zlib.decompress(datos_base64)
    # Convertir los bytes resultantes a texto UTF-8
    texto_original = datos_comprimidos.decode('utf-8')
    return texto_original
