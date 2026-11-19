# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Nuevo · comparar versiones
# Enunciado: Escribe en Python comparar_versiones(a, b) para cadenas como '1.10.2' y '1.9' (números separados por puntos; faltantes cuentan como 0). Devuelve -1 si a < b, 0 si son iguales y 1 si a > b.
# Motor: gemma (gemma-4-12b-it-q5_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:20:06.003284+00:00
# SHA-256 del código: ce00699d4d0dacf35b9a825936aa8e9f3f420983e2710bf4a4fd270e8f0ce617

def comparar_versiones(a, b):
    # Dividir las cadenas por el punto y convertir a listas de enteros
    # Si la cadena está vacía, el split devuelve [''], por lo que se maneja la conversión
    parts_a = [int(x) for x in a.split('.') if x]
    parts_b = [int(x) for x in b.split('.') if x]
    
    # Determinar la longitud máxima para comparar todos los segmentos
    max_len = max(len(parts_a), len(parts_b))
    
    for i in range(max_len):
        # Obtener el valor del segmento o 0 si no existe
        val_a = parts_a[i] if i < len(parts_a) else 0
        val_b = parts_b[i] if i < len(parts_b) else 0
        
        if val_a > val_b:
            return 1
        elif val_a < val_b:
            return -1
            
    return 0
