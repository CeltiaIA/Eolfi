# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Inédito · diferencia de intervalos
# Enunciado: Escribe restar_intervalos(base, cortes) en Python. Cada argumento es una lista desordenada de pares enteros (a,b) con a <= b que representan intervalos [a,b). Devuelve la unión de base menos la unión de cortes, en pares ordenados, sin vacíos y fusionando adyacentes. Conserva las entradas.
# Motor: gemma_q4 (gemma-4-12b-it-q4_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:42:19.842251+00:00
# SHA-256 del código: 5f171078f7dd4a2163445b0c03670a69d73f902852159df3c0cc189df47bc310

def restar_intervalos(base, cortes):
    def merge_intervals(intervals):
        if not intervals:
            return []
        # Sort by start point
        sorted_intervals = sorted(intervals)
        merged = []
        curr_start, curr_end = sorted_intervals[0]
        
        for next_start, next_end in sorted_intervals[1:]:
            if next_start <= curr_end:
                curr_end = max(curr_end, next_end)
            else:
                merged.append((curr_start, curr_end))
                curr_start, curr_end = next_start, next_end
        merged.append((curr_start, curr_end))
        return merged

    # Get unions
    base_union = merge_intervals(base)
    cuts_union = merge_intervals(cortes)
    
    result = []
    for b_start, b_end in base_union:
        current_segments = [(b_start, b_end)]
        
        for c_start, c_end in cuts_union:
            new_segments = []
            for s_start, s_end in current_segments:
                # No overlap
                if c_end <= s_start or c_start >= s_end:
                    new_segments.append((s_start, s_end))
                else:
                    # Left part
                    if c_start > s_start:
                        new_segments.append((s_start, c_start))
                    # Right part
                    if c_end < s_end:
                        new_segments.append((c_end, s_end))
            current_segments = new_segments
        
        result.extend(current_segments)
    
    # Final merge to handle adjacent intervals like (1,2) and (2,3)
    # and remove empty intervals (a == b)
    final_merged = []
    if not result:
        return []
        
    # Sort to ensure we can merge adjacent
    result.sort()
    
    temp_merged = []
    for start, end in result:
        if start == end:
            continue
        if not temp_merged:
            temp_merged.append([start, end])
        else:
            last_start, last_end = temp_merged[-1]
            if start <= last_end:
                temp_merged[-1][1] = max(last_end, end)
            else:
                temp_merged.append([start, end])
                
    return [tuple(interval) for interval in temp_merged]
