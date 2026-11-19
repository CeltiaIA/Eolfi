# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Código · construir (URL)
# Enunciado: Escribe en Python construir_url(base, ruta, params) que una base y ruta con exactamente una barra entre ellas y, si params (dict) no está vacío, añada '?' y la consulta con las claves ordenadas alfabéticamente y codificada como urllib.parse.urlencode. Si params está vacío, sin '?'.
# Motor: gemma (gemma-4-12b-it-q5_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:11:02.383350+00:00
# SHA-256 del código: 9447e42981430b317929b7655e25189c16624bdbd11c62030b95f4a7dbac6a11

import urllib.parse

def construir_url(base, ruta, params):
    # Asegurar que haya exactamente una barra entre base y ruta
    base_stripped = base.rstrip('/')
    ruta_stripped = ruta.lstrip('/')
    url = f"{base_stripped}/{ruta_stripped}"
    
    if params:
        # urlencode con doseq=True y orden alfabético (por defecto en versiones recientes, 
        # pero se puede asegurar ordenando las llaves si es necesario)
        # Para asegurar orden alfabético exacto, extraemos y ordenamos
        sorted_params = sorted(params.items())
        query_string = urllib.parse.urlencode(sorted_params)
        url += f"?{query_string}"
        
    return url
