# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Código · analizar (línea de log)
# Enunciado: Escribe en Python parsear_log(linea) que reciba líneas como '2026-11-12 03:41:05 [ERROR] fallo de disco en /dev/sda' y devuelva un dict con fecha ('2026-11-12'), hora ('03:41:05'), nivel ('ERROR') y mensaje (el resto del texto). Si la línea no tiene ese formato, devuelve None.
# Motor: gemma_q4 (gemma-4-12b-it-q4_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:38:52.639798+00:00
# SHA-256 del código: 28f76fae77b4b0170944c9bc672458b097bf6d5aeda2f3e1c99099817c576b2a

import re

def parsear_log(linea):
    # Expresión regular para capturar:
    # 1. Fecha (YYYY-MM-DD)
    # 2. Hora (HH:MM:SS)
    # 3. Nivel (dentro de [])
    # 4. Mensaje (el resto)
    pattern = r'^(\d{4}-\d{2}-\d{2})\s(\d{2}:\d{2}:\d{2})\s\[(\w+)\]\s(.*)$'
    match = re.match(pattern, linea)
    
    if match:
        fecha, hora, nivel, mensaje = match.groups()
        return {
            'fecha': fecha,
            'hora': hora,
            'nivel': nivel,
            'mensaje': mensaje
        }
    else:
        return None
