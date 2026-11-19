# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Nuevo · comparar versiones
# Enunciado: Escribe en Python comparar_versiones(a, b) para cadenas como '1.10.2' y '1.9' (números separados por puntos; faltantes cuentan como 0). Devuelve -1 si a < b, 0 si son iguales y 1 si a > b.
# Motor: gemma_q4 (gemma-4-12b-it-q4_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:40:43.974657+00:00
# SHA-256 del código: dc5815c75f52f8559b6118070d69ac0fe991ca3afd1d4e489467522c96b8b6a4

from itertools import zip_longest

def comparar_versiones(a, b):
    # Convertir las cadenas en listas de enteros
    parts_a = [int(x) for x in a.split('.')]
    parts_b = [int(x) for x in b.split('.')]
    
    # Iterar sobre ambas listas rellenando con 0 los segmentos faltantes
    for val_a, val_b in zip_longest(parts_a, parts_b, fillvalue=0):
        if val_a > val_b:
            return 1
        if val_a < val_b:
            return -1
            
    return 0
