# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Nuevo · corregir una media móvil
# Enunciado: Esta función en Python tiene un fallo: def media_movil(xs, n): return [sum(xs[i:i + n]) / n for i in range(len(xs))] Corrígela: debe devolver la media de cada ventana COMPLETA de n elementos consecutivos (len(xs)-n+1 valores) y una lista vacía si n > len(xs). Mantén el nombre media_movil(xs, n).
# Motor: gemma (gemma-4-12b-it-q5_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:21:56.725177+00:00
# SHA-256 del código: 6ebf0f9163750b404792dbe2a16c4136f81b5e4eee26723900455ab2a7d4e14f

def media_movil(xs, n):
    if n > len(xs) or n <= 0:
        return []
    return [sum(xs[i:i + n]) / n for i in range(len(xs) - n + 1)]
