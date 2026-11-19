# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Nuevo · aplanar listas anidadas
# Enunciado: Escribe en Python aplanar(datos) que reciba una lista con elementos o listas anidadas a cualquier profundidad y devuelva una lista plana con los elementos en el mismo orden (las cadenas no se descomponen).
# Motor: gemma (gemma-4-12b-it-q5_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:21:01.193057+00:00
# SHA-256 del código: 6da05dd6e5f268ad6704b5d751c1ff6fa92edc005c210362ed9cd0429bfbc31b

def aplanar(datos):
    resultado = []
    for elemento in datos:
        if isinstance(elemento, list):
            resultado.extend(aplanar(elemento))
        else:
            resultado.append(elemento)
    return resultado
