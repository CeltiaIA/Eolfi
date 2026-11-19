# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Nuevo · descifrar XOR
# Enunciado: Escribe en Python descifrar(datos, clave) que reciba bytes cifrados con XOR repitiendo la clave (bytes) y devuelva los bytes originales. Si la clave está vacía, lanza ValueError.
# Motor: gemma (gemma-4-12b-it-q5_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:18:47.333283+00:00
# SHA-256 del código: afc39e7a3b812233e2dd7ff705952df1b9f3ed00eb79300703edd5fb2faba64c

def descifrar(datos, clave):
    if not clave:
        raise ValueError("La clave no puede estar vacía.")
    
    resultado = bytearray()
    for i in range(len(datos)):
        resultado.append(datos[i] ^ clave[i % len(clave)])
    
    return bytes(resultado)
