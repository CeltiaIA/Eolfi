# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Inédito · leer una duración
# Enunciado: Escribe en Python duracion(texto: str) -> int que convierta duraciones como '1h30m', '45s', '2h' o '1h0m5s' a segundos. Las unidades van en orden h, m, s, cada una como mucho una vez, y al menos una. Cualquier otro formato (vacío, unidades repetidas o desordenadas, números negativos) lanza ValueError.
# Motor: gemma (gemma-4-12b-it-q5_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:31:38.604050+00:00
# SHA-256 del código: a44690a80abbab524e7c8f16458a8ac114b591c96223147b8ff0ad58a40689a9

import re

def duracion(texto: str) -> int:
    if not texto:
        raise ValueError("Input vacío")
    
    # Regex para encontrar bloques de números seguidos de h, m o s
    # El patrón busca (número)(unidad)
    matches = list(re.finditer(r'(\d+)([hms])', texto))
    
    # Validar que el texto solo contenga los bloques encontrados y nada más
    # Esto evita caracteres extraños o espacios
    reconstructed = "".join(m.group(0) for m in matches)
    if reconstructed != texto:
        raise ValueError("Formato inválido")
    
    if not matches:
        raise ValueError("No hay unidades válidas")
    
    total_seconds = 0
    seen_units = set()
    last_unit_index = -1
    
    # Orden esperado de índices: h=0, m=1, s=2
    unit_order = {'h': 0, 'm': 1, 's': 2}
    
    for i, m in enumerate(matches):
        value_str, unit = m.groups()
        value = int(value_str)
        
        # Validar que no haya números negativos (el regex \d+ ya asegura positivos)
        # Pero si el input fuera "-1h", el regex no lo capturaría y reconstructed != texto
        
        # Validar que la unidad no se repita
        if unit in seen_units:
            raise ValueError("Unidad repetida")
        seen_units.add(unit)
        
        # Validar orden: el índice de la unidad actual debe ser mayor al anterior
        current_unit_idx = unit_order[unit]
        if current_unit_idx <= last_unit_index:
            raise ValueError("Unidades desordenadas")
        last_unit_index = current_unit_idx
        
        # Calcular segundos
        if unit == 'h':
            total_seconds += value * 3600
        elif unit == 'm':
            total_seconds += value * 60
        elif unit == 's':
            total_seconds += value
            
    return total_seconds
