# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Código · corregir (búsqueda binaria)
# Enunciado: Esta búsqueda binaria en Python tiene un fallo: def buscar(xs, x): lo, hi = 0, len(xs) while lo < hi: mid = (lo + hi) // 2 if xs[mid] < x: lo = mid else: hi = mid return lo if lo < len(xs) and xs[lo] == x else -1 Corrígela: debe devolver el índice de x en la lista ordenada xs, o -1 si no está. Mantén el nombre buscar(xs, x).
# Motor: gemma_q4 (gemma-4-12b-it-q4_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:38:22.949007+00:00
# SHA-256 del código: cf8244dd62aea4e09c06debba02a4ec4e76a1790d00907b669033d036692db1a

def buscar(xs, x):
    lo, hi = 0, len(xs)
    while lo < hi:
        mid = (lo + hi) // 2
        if xs[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    
    if lo < len(xs) and xs[lo] == x:
        return lo
    return -1
