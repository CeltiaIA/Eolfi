# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Nuevo · totales de un CSV
# Enunciado: Escribe en Python totales(texto_csv) que reciba el texto de un CSV con cabecera producto,cantidad,precio y devuelva un dict producto -> importe total (cantidad*precio, sumando filas repetidas), redondeado a 2 decimales. Ignora las líneas vacías.
# Motor: gemma (gemma-4-12b-it-q5_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:17:45.847452+00:00
# SHA-256 del código: cfaa8cf01942330ca4ea51087c9335e6c82d6edbe14a6ef92b0c0e95f9d59b1c

import csv
import io

def totales(texto_csv):
    resultados = {}
    # Usamos io.StringIO para que el módulo csv pueda leer la cadena como un archivo
    f = io.StringIO(texto_csv.strip())
    reader = csv.DictReader(f)
    
    for row in reader:
        # Ignorar filas que no tengan datos en la columna producto (líneas vacías o mal formadas)
        if not row.get('producto'):
            continue
            
        try:
            producto = row['producto']
            cantidad = float(row['cantidad'])
            precio = float(row['precio'])
            importe = cantidad * precio
            
            if producto in resultados:
                resultados[producto] += importe
            else:
                resultados[producto] = importe
        except (ValueError, TypeError):
            # Ignorar filas con datos no numéricos en cantidad o precio
            continue
            
    # Redondear todos los valores a 2 decimales
    return {k: round(v, 2) for k, v in resultados.items()}
