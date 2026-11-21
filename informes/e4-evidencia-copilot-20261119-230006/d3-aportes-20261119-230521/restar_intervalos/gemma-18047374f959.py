# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Inédito · diferencia de intervalos
# Enunciado: Escribe restar_intervalos(base, cortes) en Python. Cada argumento es una lista desordenada de pares enteros (a,b) con a <= b que representan intervalos [a,b). Devuelve la unión de base menos la unión de cortes, en pares ordenados, sin vacíos y fusionando adyacentes. Conserva las entradas.
# Motor: gemma (gemma-4-12b-it-q5_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:23:46.832088+00:00
# SHA-256 del código: 18047374f959435a8d44ac3ba2f3dab978065752ec84aa89c56db0b23291cb46

def restar_intervalos(base, cortes):
    def fusionar(intervalos):
        if not intervalos:
            return []
        # Ordenar por el inicio del intervalo
        sorted_intervals = sorted(intervalos)
        fusionados = []
        curr_start, curr_end = sorted_intervals[0]
        
        for i in range(1, len(sorted_intervals)):
            next_start, next_end = sorted_intervals[i]
            if next_start <= curr_end:
                curr_end = max(curr_end, next_end)
            else:
                if curr_start < curr_end:
                    fusionados.append((curr_start, curr_end))
                curr_start, curr_end = next_start, next_end
        
        if curr_start < curr_end:
            fusionados.append((curr_start, curr_end))
        return fusionados

    # 1. Obtener la unión de base y cortes
    union_base = fusionar(base)
    union_cortes = fusionar(cortes)
    
    # 2. Restar cortes de base
    # Para cada intervalo en la unión de base, restamos todos los cortes
    resultado = []
    for b_start, b_end in union_base:
        segmentos_a_procesar = [(b_start, b_end)]
        
        for c_start, c_end in union_cortes:
            nuevos_segmentos = []
            for s_start, s_end in segmentos_a_procesar:
                # Si no hay intersección, mantener el segmento
                if c_end <= s_start or c_start >= s_end:
                    nuevos_segmentos.append((s_start, s_end))
                else:
                    # Hay intersección, crear fragmentos restantes
                    if c_start > s_start:
                        nuevos_segmentos.append((s_start, c_start))
                    if c_end < s_end:
                        nuevos_segmentos.append((c_end, s_end))
            segmentos_a_procesar = nuevos_segmentos
        
        resultado.extend(segmentos_a_procesar)
    
    # 3. Fusionar resultados finales (por si acaso, aunque la lógica anterior 
    # ya debería devolver segmentos disjuntos y ordenados)
    return fusionar(resultado)
