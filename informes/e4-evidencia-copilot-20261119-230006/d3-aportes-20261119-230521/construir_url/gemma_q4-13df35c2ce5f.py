# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Código · construir (URL)
# Enunciado: Escribe en Python construir_url(base, ruta, params) que una base y ruta con exactamente una barra entre ellas y, si params (dict) no está vacío, añada '?' y la consulta con las claves ordenadas alfabéticamente y codificada como urllib.parse.urlencode. Si params está vacío, sin '?'.
# Motor: gemma_q4 (gemma-4-12b-it-q4_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:36:56.869634+00:00
# SHA-256 del código: 13df35c2ce5fb11b0d2b98c4e2693e7f6a8c990c39841ab321a8955f55b9c185

import urllib.parse

def construir_url(base, ruta, params):
    # Asegurar que haya exactamente una barra entre base y ruta
    base_stripped = base.rstrip('/')
    ruta_stripped = ruta.lstrip('/')
    url = f"{base_stripped}/{ruta_stripped}"
    
    if not params:
        return url
    
    # Ordenar las claves alfabéticamente
    sorted_params = {k: params[k] for k in sorted(params.keys())}
    
    # Codificar los parámetros
    query_string = urllib.parse.urlencode(sorted_params)
    
    return f"{url}?{query_string}"
