# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Inédito · números romanos
# Enunciado: Escribe en Python romano(n) que devuelva el número romano (mayúsculas) de un entero 1 ≤ n ≤ 3999 con las restas canónicas (IV, IX, XL, XC, CD, CM). Si n está fuera de rango, lanza ValueError.
# Motor: gemma_q4 (gemma-4-12b-it-q4_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:43:29.556199+00:00
# SHA-256 del código: 2e9ec39b76c51d938fe92cd110f4a6ecc6c6feda047e7a4c6df7a426adc9d958

def romano(n):
    if not (1 <= n <= 3999):
        raise ValueError("El número debe estar en el rango 1 <= n <= 3999.")
    
    # Lista de tuplas (valor, símbolo) en orden descendente
    # Incluye las restas canónicas para facilitar la conversión
    mapping = [
        (1000, 'M'),
        (900, 'CM'),
        (500, 'D'),
        (400, 'CD'),
        (100, 'C'),
        (90, 'XC'),
        (50, 'L'),
        (40, 'XL'),
        (10, 'X'),
        (9, 'IX'),
        (5, 'V'),
        (4, 'IV'),
        (1, 'I')
    ]
    
    result = []
    for value, symbol in mapping:
        while n >= value:
            result.append(symbol)
            n -= value
            
    return "".join(result)
