# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Código · analizar (línea de log)
# Enunciado: Escribe en Python parsear_log(linea) que reciba líneas como '2026-11-12 03:41:05 [ERROR] fallo de disco en /dev/sda' y devuelva un dict con fecha ('2026-11-12'), hora ('03:41:05'), nivel ('ERROR') y mensaje (el resto del texto). Si la línea no tiene ese formato, devuelve None.
# Motor: gemma (gemma-4-12b-it-q5_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:15:06.201315+00:00
# SHA-256 del código: e2b4f769c2f197233998d474ddd5f40ab09d1fbab85212bfc184fb8210caa80d

import re

def parsear_log(linea):
    # Regex explanation:
    # ^(\d{4}-\d{2}-\d{2}) : Captures YYYY-MM-DD at the start
    # \s(\d{2}:\d{2}:\d{2}) : Captures HH:MM:SS after a space
    # \s\[(\w+)\]           : Captures word inside brackets []
    # \s(.*)$               : Captures everything else as the message
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
    return None
