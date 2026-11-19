# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Código · ingeniería inversa (función ofuscada)
# Enunciado: Esta función está ofuscada: f = lambda n: sum(i*i for i in range(n) if not i % 3). Escribe en Python una función legible equivalente llamada equivalente(n), con un bucle normal, que devuelva exactamente lo mismo para todo entero n >= 0.
# Motor: gemma_q4 (gemma-4-12b-it-q4_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (tras corregir con el error real)
# Fecha: 2026-11-19T22:37:55.838654+00:00
# SHA-256 del código: 6657f1abba1c8a834c03f69fb19f234ffd8fb15a687b5c108f595ef84b7f0fdb

def equivalente(n):
    suma = 0
    for i in range(n):
        if i % 3 == 0:
            suma += i * i
    return suma
