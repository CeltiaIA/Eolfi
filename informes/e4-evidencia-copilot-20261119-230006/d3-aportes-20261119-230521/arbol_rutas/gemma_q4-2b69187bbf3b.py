# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Código · construir (árbol de rutas)
# Enunciado: Escribe en Python construir_arbol(rutas) que reciba una lista de rutas como 'a/b/c' y devuelva un diccionario anidado en el que cada parte de la ruta es una clave y las hojas son diccionarios vacíos.
# Motor: gemma_q4 (gemma-4-12b-it-q4_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:37:24.003783+00:00
# SHA-256 del código: 2b69187bbf3b1068f1cba2268d2409c0d62ec9f38a357cf438dfd06273f67ab6

def construir_arbol(rutas):
    arbol = {}
    for ruta in rutas:
        partes = ruta.split('/')
        nodo_actual = arbol
        for parte in partes:
            if parte not in nodo_actual:
                nodo_actual[parte] = {}
            nodo_actual = nodo_actual[parte]
    return arbol
