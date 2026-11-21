# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Inédito · orden topológico determinista
# Enunciado: Escribe en Python orden_topologico(dependencias: dict[str, list[str]]) -> list[str]. Cada clave es una tarea y su lista, las tareas que deben ir ANTES. Incluye también las tareas que solo aparecen como dependencia. Cuando varias estén disponibles a la vez, elige primero la menor alfabéticamente. Si hay un ciclo, lanza ValueError.
# Motor: gemma (gemma-4-12b-it-q5_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:30:03.516865+00:00
# SHA-256 del código: 4734ad2b90da75d35856d6a023228ec4f6191dac89fc0aa1e69504086ad3cd2c

import heapq

def orden_topologico(dependencias: dict[str, list[str]]) -> list[str]:
    # Identificar todos los nodos únicos (claves y dependencias)
    all_nodes = set(dependencias.keys())
    for deps in dependencias.values():
        for d in deps:
            all_nodes.add(d)
    
    # Construir el grafo de adyacencia (quién depende de quién)
    # y contar el grado de entrada (cuántas dependencias tiene cada tarea)
    adj = {node: [] for node in all_nodes}
    in_degree = {node: 0 for node in all_nodes}
    
    for task, deps in dependencias.items():
        # El input dice que deps son las tareas que deben ir ANTES
        # Por lo tanto, la flecha va de d -> task
        in_degree[task] = len(deps)
        for d in deps:
            adj[d].append(task)
            
    # Usar un min-heap para asegurar el orden lexicográfico
    # entre tareas con grado de entrada 0
    queue = [node for node in all_nodes if in_degree[node] == 0]
    heapq.heapify(queue)
    
    result = []
    
    while queue:
        u = heapq.heappop(queue)
        result.append(u)
        
        for v in adj[u]:
            in_degree[v] -= 1
            if in_degree[v] == 0:
                heapq.heappush(queue, v)
                
    if len(result) != len(all_nodes):
        raise ValueError("Ciclo detectado en las dependencias")
        
    return result
