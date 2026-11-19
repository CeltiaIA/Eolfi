# Aporte de Eolfi a Alejandría (código generado por un motor local y verificado)
# Tarea: Nuevo · totales de un CSV
# Enunciado: Escribe en Python totales(texto_csv) que reciba el texto de un CSV con cabecera producto,cantidad,precio y devuelva un dict producto -> importe total (cantidad*precio, sumando filas repetidas), redondeado a 2 decimales. Ignora las líneas vacías.
# Motor: gemma_q4 (gemma-4-12b-it-q4_k_m:latest)
# Resultado: pasa sus pruebas en un contenedor aislado (a la primera)
# Fecha: 2026-11-19T22:39:50.739149+00:00
# SHA-256 del código: 7b72adc96eb71c9e1575c0131fe41bc7f812be49e6eb038173cad4101d8db403

import csv
import io

def totales(texto_csv):
    resultados = {}
    # Usamos io.StringIO para simular un archivo y el módulo csv para parsear correctamente
    f = io.StringIO(texto_csv.strip())
    reader = csv.DictReader(f)
    
    for row in reader:
        # Verificar que la fila no esté vacía y tenga los datos necesarios
        if row.get('producto') and row.get('cantidad') and row.get('precio'):
            try:
                producto = row['producto']
                cantidad = float(row['cantidad'])
                precio = float(row['precio'])
                importe = cantidad * precio
                
                if producto in resultados:
                    resultados[producto] += importe
                else:
                    resultados[producto] = importe
            except ValueError:
                continue
                
    # Redondear los valores finales a 2 decimales
    return {k: round(v, 2) for k, v in resultados.items()}
