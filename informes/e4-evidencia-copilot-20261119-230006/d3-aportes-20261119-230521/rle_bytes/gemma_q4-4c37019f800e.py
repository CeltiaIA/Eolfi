# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Inédito · compresión RLE de bytes
# Enunciado: Escribe en Python rle_bytes(data: bytes) -> bytes que codifique por longitud de racha: por cada racha de un mismo byte emite dos bytes (longitud, valor), con longitud máxima 255 (las rachas más largas se parten). b'' devuelve b''.
# Motor: gemma_q4 (gemma-4-12b-it-q4_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:43:58.007601+00:00
# SHA-256 del código: 4c37019f800e76a7d16ff93b571a5b18ddb4e8d7b04deba389777589d0dc502d

def rle_bytes(data: bytes) -> bytes:
    if not data:
        return b''
    
    result = bytearray()
    i = 0
    n = len(data)
    
    while i < n:
        current_byte = data[i]
        count = 0
        
        # Count consecutive identical bytes
        while i + count < n and data[i + count] == current_byte and count < 255:
            count += 1
        
        result.append(count)
        result.append(current_byte)
        
        i += count
        
    return bytes(result)
