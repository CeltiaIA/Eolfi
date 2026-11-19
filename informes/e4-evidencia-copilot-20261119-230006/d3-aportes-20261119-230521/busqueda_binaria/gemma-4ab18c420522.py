# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Código · corregir (búsqueda binaria)
# Enunciado: Esta búsqueda binaria en Python tiene un fallo: def buscar(xs, x): lo, hi = 0, len(xs) while lo < hi: mid = (lo + hi) // 2 if xs[mid] < x: lo = mid else: hi = mid return lo if lo < len(xs) and xs[lo] == x else -1 Corrígela: debe devolver el índice de x en la lista ordenada xs, o -1 si no está. Mantén el nombre buscar(xs, x).
# Motor: gemma (gemma-4-12b-it-q5_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:13:50.708297+00:00
# SHA-256 del código: 4ab18c420522c74094a5f368c161455c7a2b64b497b6fc9a94f01ad1c53a1889

def buscar(xs, x):
    lo, hi = 0, len(xs) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if xs[mid] == x:
            return mid
        elif xs[mid] < x:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
