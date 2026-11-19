# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Nuevo · corregir una media móvil
# Enunciado: Esta función en Python tiene un fallo: def media_movil(xs, n): return [sum(xs[i:i + n]) / n for i in range(len(xs))] Corrígela: debe devolver la media de cada ventana COMPLETA de n elementos consecutivos (len(xs)-n+1 valores) y una lista vacía si n > len(xs). Mantén el nombre media_movil(xs, n).
# Motor: gemma_q4 (gemma-4-12b-it-q4_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:41:33.846930+00:00
# SHA-256 del código: 09e93aed25626893099ca5200235c34d964e350338a791406fe5075991245c41

def media_movil(xs, n):
    if n > len(xs) or n <= 0:
        return []
    
    return [sum(xs[i:i + n]) / n for i in range(len(xs) - n + 1)]
