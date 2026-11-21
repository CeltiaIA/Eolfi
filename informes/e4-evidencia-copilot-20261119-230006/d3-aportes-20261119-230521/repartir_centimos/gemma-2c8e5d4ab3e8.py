# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Inédito · reparto exacto por restos
# Enunciado: Escribe repartir_centimos(total, pesos). total es un entero no negativo. pesos es una lista de enteros no negativos con suma positiva. Reparte el total en proporción al peso: asigna primero la parte entera de cada cuota y reparte los céntimos sobrantes por resto descendente. Desempata por índice ascendente. Devuelve una lista de enteros exactos incluso con totales superiores a 2**53.
# Motor: gemma (gemma-4-12b-it-q5_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:25:20.852902+00:00
# SHA-256 del código: 2c8e5d4ab3e8bdbb159edb92ee9691523b0c8b9819836a2e6aafbc2fa00b29a2

from fractions import Fraction

def repartir_centimos(total, pesos):
    suma_pesos = sum(pesos)
    # Calculamos la cuota exacta usando Fraction para evitar errores de punto flotante
    # y manejar números mayores a 2^53.
    cuotas_exactas = [Fraction(total * p, suma_pesos) for p in pesos]
    
    # Asignamos la parte entera inicial
    resultados = [int(c.numerator // c.denominator) for c in cuotas_exactas]
    
    # Calculamos el sobrante
    sobrante = total - sum(resultados)
    
    # Calculamos los restos (fracciones decimales)
    # El resto es la parte decimal de la cuota exacta.
    restos = [c - int(c) for c in cuotas_exactas]
    
    # Para repartir el sobrante, necesitamos ordenar por:
    # 1. Resto descendente (mayor a menor)
    # 2. Índice ascendente (en caso de empate en el resto)
    # Creamos una lista de índices para mantener la referencia original
    indices = list(range(len(pesos)))
    
    # Ordenamos los índices:
    # El criterio de ordenación es el valor del resto. 
    # Como queremos descendente para el resto y ascendente para el índice,
    # usamos una tupla donde el resto es negativo para que el orden natural sea correcto.
    indices.sort(key=lambda i: (-restos[i], i))
    
    # Repartimos el sobrante unidad por unidad a los mejores índices
    for i in range(int(sobrante)):
        resultados[indices[i]] += 1
        
    return resultados
