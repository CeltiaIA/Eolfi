# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Nuevo · fusionar intervalos
# Enunciado: Escribe en Python fusionar(intervalos) que reciba una lista de pares [inicio, fin] (enteros, inicio <= fin), sin orden, y devuelva la lista de intervalos fusionados donde se solapan o se tocan, ordenada por inicio, como lista de listas.
# Motor: gemma (gemma-4-12b-it-q5_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:16:25.789577+00:00
# SHA-256 del código: fb6b4abad48f8d1086e9fe12eaa650a303554e1db6f71446c54a312848007ecb

def fusionar(intervalos):
    if not intervalos:
        return []

    # Ordenar los intervalos por el valor de inicio
    intervalos_ordenados = sorted(intervalos, key=lambda x: x[0])
    
    fusionados = []
    # Inicializar con el primer intervalo
    actual = list(intervalos_ordenados[0])
    
    for i in range(1, len(intervalos_ordenados)):
        siguiente = intervalos_ordenados[i]
        
        # Si el inicio del siguiente es <= al fin del actual, se solapan o tocan
        if siguiente[0] <= actual[1]:
            # Fusionar tomando el máximo de los dos finales
            actual[1] = max(actual[1], siguiente[1])
        else:
            # No hay solapamiento, guardar el actual y pasar al siguiente
            fusionados.append(actual)
            actual = list(siguiente)
            
    # Añadir el último intervalo procesado
    fusionados.append(actual)
    
    return fusionados
