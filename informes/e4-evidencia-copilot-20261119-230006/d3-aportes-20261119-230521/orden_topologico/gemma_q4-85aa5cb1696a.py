# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Inédito · orden topológico determinista
# Enunciado: Escribe en Python orden_topologico(dependencias: dict[str, list[str]]) -> list[str]. Cada clave es una tarea y su lista, las tareas que deben ir ANTES. Incluye también las tareas que solo aparecen como dependencia. Cuando varias estén disponibles a la vez, elige primero la menor alfabéticamente. Si hay un ciclo, lanza ValueError.
# Motor: gemma_q4 (gemma-4-12b-it-q4_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:44:35.029051+00:00
# SHA-256 del código: 85aa5cb1696a6cd50c65efb3f655ebc379a2e19e34e435b6858b8f603d932b7f

import heapq

def orden_topologico(dependencias: dict[str, list[str]]) -> list[str]:
    # Identificar todos los nodos únicos (claves y dependencias)
    all_nodes = set(dependencias.keys())
    for deps in dependencias.values():
        all_nodes.update(deps)
    
    # Construir el grafo de adyacencia (quién depende de quién)
    # y contar el grado de entrada (cuántas dependencias tiene cada tarea)
    adj = {node: [] for node in all_nodes}
    in_degree = {node: 0 for node in all_nodes}
    
    for task, deps in dependencias.items():
        in_degree[task] = len(deps)
        for dep in deps:
            adj[dep].append(task)
            
    # Usar un heap para asegurar el orden alfabético en caso de empate
    # Las tareas con in_degree 0 están listas para ser procesadas
    ready_queue = [node for node in all_nodes if in_degree[node] == 0]
    heapq.heapify(ready_queue)
    
    result = []
    while ready_queue:
        u = heapq.heappop(ready_queue)
        result.append(u)
        
        for v in adj[u]:
            in_degree[v] -= 1
            if in_degree[v] == 0:
                heapq.heappush(ready_queue, v)
                
    # Si el resultado no contiene todos los nodos, hay un ciclo
    if len(result) != len(all_nodes):
        raise ValueError("Se detectó un ciclo en las dependencias.")
        
    return result
