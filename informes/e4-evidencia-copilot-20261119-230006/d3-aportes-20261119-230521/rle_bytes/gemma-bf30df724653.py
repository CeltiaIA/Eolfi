# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Inédito · compresión RLE de bytes
# Enunciado: Escribe en Python rle_bytes(data: bytes) -> bytes que codifique por longitud de racha: por cada racha de un mismo byte emite dos bytes (longitud, valor), con longitud máxima 255 (las rachas más largas se parten). b'' devuelve b''.
# Motor: gemma (gemma-4-12b-it-q5_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:28:37.058552+00:00
# SHA-256 del código: bf30df7246535c7fcd599b47a020568787a6c3b6f202e92b4525a681c99d7ab7

def rle_bytes(data: bytes) -> bytes:
    if not data:
        return b''
    
    result = bytearray()
    i = 0
    n = len(data)
    
    while i < n:
        current_byte = data[i]
        count = 0
        
        # Contar la racha actual
        while i + count < n and data[i + count] == current_byte:
            count += 1
        
        # Dividir la racha si supera 255
        while count > 0:
            chunk_size = min(count, 255)
            result.append(chunk_size)
            result.append(current_byte)
            count -= chunk_size
            
        i += (count + (count - count)) # Avanzar al siguiente byte distinto o final
        # El incremento correcto es simplemente la longitud total de la racha detectada
        # pero como el while interno ya contó 'count', simplemente sumamos ese count.
        # Re-ajustando la lógica para evitar errores de índice:
        # i += (original_count)
    
    # Re-implementación limpia para evitar errores de lógica en el avance del índice
    return _rle_bytes_clean(data)

def _rle_bytes_clean(data: bytes) -> bytes:
    if not data:
        return b''
    
    result = bytearray()
    i = 0
    n = len(data)
    
    while i < n:
        current_byte = data[i]
        start_index = i
        while i < n and data[i] == current_byte:
            i += 1
        
        total_count = i - start_index
        
        while total_count > 0:
            chunk_size = min(total_count, 255)
            result.append(chunk_size)
            result.append(current_byte)
            total_count -= chunk_size
            
    return bytes(result)

# Sobrescribiendo la función principal con la lógica limpia
def rle_bytes(data: bytes) -> bytes:
    if not data:
        return b''
    
    result = bytearray()
    i = 0
    n = len(data)
    
    while i < n:
        current_byte = data[i]
        start_index = i
        while i < n and data[i] == current_byte:
            i += 1
        
        total_count = i - start_index
        
        while total_count > 0:
            chunk_size = min(total_count, 255)
            result.append(chunk_size)
            result.append(current_byte)
            total_count -= chunk_size
            
    return bytes(result)
