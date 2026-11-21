# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Código · desempaquetar (base64 + zlib)
# Enunciado: Escribe en Python desempaquetar(texto) que reciba una cadena base64 cuyo contenido son datos comprimidos con zlib y devuelva el texto original decodificado como UTF-8.
# Motor: gemma (gemma-4-12b-it-q5_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:09:51.839163+00:00
# SHA-256 del código: 8351f94b521fb3998ec12cef56dce0f9da2227f38207c18c779cf0d796c44743

import base64
import zlib

def desempaquetar(texto):
    # Decodificar la cadena Base64 a bytes
    datos_base64 = base64.b64decode(texto)
    # Descomprimir los bytes usando zlib
    datos_descomprimidos = zlib.decompress(datos_base64)
    # Convertir los bytes descomprimidos a texto UTF-8
    texto_original = datos_descomprimidos.decode('utf-8')
    return texto_original
