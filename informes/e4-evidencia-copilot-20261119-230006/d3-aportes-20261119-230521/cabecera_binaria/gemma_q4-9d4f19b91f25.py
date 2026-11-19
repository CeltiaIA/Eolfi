# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Código · desempaquetar (cabecera binaria)
# Enunciado: Escribe en Python leer_cabecera(datos) que reciba bytes y desempaquete con el módulo struct una cabecera little-endian de 10 bytes: version (entero sin signo de 2 bytes), tamano (entero sin signo de 4 bytes) y firma (4 bytes ASCII). Devuelve un dict con las claves version, tamano y firma (str). Si datos tiene menos de 10 bytes, lanza ValueError.
# Motor: gemma_q4 (gemma-4-12b-it-q4_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:36:02.681549+00:00
# SHA-256 del código: 9d4f19b91f259a1269f752b28ded87eeea784a1580fe14c1b2c268054253a97c

import struct

def leer_cabecera(datos):
    if len(datos) < 10:
        raise ValueError("Los datos deben tener al menos 10 bytes.")
    
    # Formato: < (little-endian), H (unsigned short, 2 bytes), I (unsigned int, 4 bytes), 4s (4 bytes string)
    version, tamano, firma_bytes = struct.unpack('<HI4s', datos[:10])
    
    return {
        'version': version,
        'tamano': tamano,
        'firma': firma_bytes.decode('ascii')
    }
