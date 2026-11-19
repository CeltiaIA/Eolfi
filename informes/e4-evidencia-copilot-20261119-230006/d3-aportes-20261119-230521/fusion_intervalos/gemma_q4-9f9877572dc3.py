# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Nuevo · fusionar intervalos
# Enunciado: Escribe en Python fusionar(intervalos) que reciba una lista de pares [inicio, fin] (enteros, inicio <= fin), sin orden, y devuelva la lista de intervalos fusionados donde se solapan o se tocan, ordenada por inicio, como lista de listas.
# Motor: gemma_q4 (gemma-4-12b-it-q4_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:39:21.072664+00:00
# SHA-256 del código: 9f9877572dc3cf136cf11e1739023302f6847c0450279cd62e3218c5eac8da37

def fusionar(intervalos):
    if not intervalos:
        return []

    # Ordenar los intervalos por el valor de inicio
    intervalos_ordenados = sorted(intervalos, key=lambda x: x[0])
    
    fusionados = []
    
    for intervalo in intervalos_ordenados:
        # Si la lista fusionados está vacía o el intervalo actual no se solapa/toca con el último
        if not fusionados or intervalo[0] > fusionados[-1][1]:
            fusionados.append(list(intervalo))
        else:
            # Existe solapamiento o se tocan, actualizamos el fin del último intervalo
            fusionados[-1][1] = max(fusionados[-1][1], intervalo[1])
            
    return fusionados
