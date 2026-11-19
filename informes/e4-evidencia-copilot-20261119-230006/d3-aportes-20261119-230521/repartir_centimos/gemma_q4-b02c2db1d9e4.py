# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Inédito · reparto exacto por restos
# Enunciado: Escribe repartir_centimos(total, pesos). total es un entero no negativo. pesos es una lista de enteros no negativos con suma positiva. Reparte el total en proporción al peso: asigna primero la parte entera de cada cuota y reparte los céntimos sobrantes por resto descendente. Desempata por índice ascendente. Devuelve una lista de enteros exactos incluso con totales superiores a 2**53.
# Motor: gemma_q4 (gemma-4-12b-it-q4_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:42:57.490027+00:00
# SHA-256 del código: b02c2db1d9e4709bb601395825d61baf870586918e67c6facc44b397c0385893

from fractions import Fraction

def repartir_centimos(total, pesos):
    suma_pesos = sum(pesos)
    n = len(pesos)
    
    # Calcular la parte entera de cada cuota usando fracciones para evitar errores de punto flotante
    cuotas_enteras = []
    restos = []
    
    for i in range(n):
        # Cuota teórica: (total * pesos[i]) / suma_pesos
        fraccion = Fraction(total * pesos[i], suma_pesos)
        cuotas_enteras.append(fraccion.numerator // fraccion.denominator)
        # El resto es la parte decimal de la fracción
        restos.append(fraccion - fraccion.numerator // fraccion.denominator)
    
    total_asignado = sum(cuotas_enteras)
    sobrante = total - total_asignado
    
    # Ordenar los índices para repartir el sobrante:
    # 1. Por resto descendente (restos[i] mayor primero)
    # 2. Por índice ascendente (en caso de empate en el resto)
    # Usamos una lista de tuplas (resto, -indice) para ordenar de forma natural
    # o simplemente una función de ordenamiento personalizada.
    
    indices = list(range(n))
    # Ordenamos: primero por resto (descendente), luego por índice (ascendente)
    indices.sort(key=lambda i: (-restos[i], i))
    
    # Repartir el sobrante unidad por unidad a los primeros índices de la lista ordenada
    for i in range(int(sobrante)):
        cuotas_enteras[indices[i]] += 1
        
    return cuotas_enteras
