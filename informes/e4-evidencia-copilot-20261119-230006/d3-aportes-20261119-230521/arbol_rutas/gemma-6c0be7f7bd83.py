# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Código · construir (árbol de rutas)
# Enunciado: Escribe en Python construir_arbol(rutas) que reciba una lista de rutas como 'a/b/c' y devuelva un diccionario anidado en el que cada parte de la ruta es una clave y las hojas son diccionarios vacíos.
# Motor: gemma (gemma-4-12b-it-q5_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:11:58.190463+00:00
# SHA-256 del código: 6c0be7f7bd83e5f1554c293195b1d0a90c76ba1932f9307b1a3243e9e79f32d0

def construir_arbol(rutas):
    arbol = {}
    for ruta in rutas:
        segmentos = ruta.split('/')
        nodo_actual = arbol
        for segmento in segmentos:
            if segmento not in nodo_actual:
                nodo_actual[segmento] = {}
            nodo_actual = nodo_actual[segmento]
    return arbol
