# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Nuevo · descifrar XOR
# Enunciado: Escribe en Python descifrar(datos, clave) que reciba bytes cifrados con XOR repitiendo la clave (bytes) y devuelva los bytes originales. Si la clave está vacía, lanza ValueError.
# Motor: gemma_q4 (gemma-4-12b-it-q4_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:40:16.292346+00:00
# SHA-256 del código: 0bbc7ff1ffba9328fa0e2fad09d31edf68c85edaa67d6bd84f9dcbc186fc5619

def descifrar(datos, clave):
    if not clave:
        raise ValueError("La clave no puede estar vacía.")
    
    resultado = bytearray()
    clave_largo = len(clave)
    
    for i, byte in enumerate(datos):
        resultado.append(byte ^ clave[i % clave_largo])
        
    return bytes(resultado)
