# Modelos: auditoría e identidad local

`python -m eolfi modelos auditar ARCHIVO.gguf` lee el GGUF sin cargarlo ni ejecutar su plantilla.
Devuelve JSON con SHA-256 completo, dimensiones, arquitectura, hash de la plantilla y metadatos del
planificador. No inicia ningún servidor ni abre la base de evidencias.

Estados: `estructura_verificada` (salida 0), `NO VERIFICADO` o `fallido` (salida 2).
El primer estado se refiere exclusivamente a las comprobaciones estructurales implementadas. No acredita
la seguridad de los pesos, la calidad, la compatibilidad del motor ni la procedencia del modelo.

Los tipos GGML Q8_1 y K (IDs 9–15), y cualquier tipo desconocido, conservan tamaño y bytes sobrantes como
desconocidos: existen layouts históricos que no se pueden distinguir solo por el identificador. El auditor
no adivina cuál se usó. Excepción con evidencia: en los tipos K (10–15), un tensor con sucesor es testigo de su tamaño,
porque con el formato actual (superbloque de 256), una vez alineado, debe acabar justo donde empieza el siguiente.
Si todos los testigos de un tipo coinciden, ese tipo queda confirmado, `tamanos_k` indica cuántos testigos hubo y
los bytes sobrantes se calculan. Si uno solo discrepa, o el tipo no tiene ningún testigo, sigue como desconocido.
Q8_1 (ID 9) nunca se confirma. Medido el 17/11/2026 con Gemma 4 12B Q3_K_M, Q4_K_M, Q5_K_M y Q6_K: 329 tensores K
confirmados en cada uno y 0 bytes sobrantes. Las palabras del vocabulario y de las reglas BPE no se clasifican como órdenes.
Las URL y otras cadenas del resto de metadatos se muestran para revisión; no son defectos demostrados.

## Manifiesto explícito

Un manifiesto autorizado tiene esta forma (sustituir ruta y hash por valores revisados):

```json
{
  "schema": "eolfi.modelos.confianza/v1",
  "modelos": [
    {
      "archivo": "D:\\modelos\\modelo.gguf",
      "sha256": "SHA256_COMPLETO_DE_64_CARACTERES_HEXADECIMALES"
    }
  ]
}
```

`python -m eolfi modelos comprobar ARCHIVO.gguf --manifiesto RUTA.json` vuelve a calcular el hash y lo
contrasta. No modifica el manifiesto ni adopta ningún modelo. Copiar al manifiesto el hash calculado
localmente solo fija una identidad; no verifica el origen ni demuestra seguridad.

Para un modelo dividido, la entrada del primer shard incluye `partes`, una lista de objetos con `archivo`
y `sha256` de cada shard. Se exigen todas las partes, rutas absolutas y hashes individuales válidos.
No se admiten entradas principales duplicadas ni partes duplicadas.

Establecer `EOLFI_MODELOS_CONFIANZA` con la ruta del manifiesto activa la comprobación en los arranques
Python de Eolas V2 y del proveedor antiguo llama.cpp. Si el manifiesto falta, el archivo no está autorizado
o algún hash difiere, se aborta antes de consultar el servidor o lanzar procesos. Con esta política no se
admiten `extra_args` en V2: podrían sustituir el modelo que se acaba de comprobar.

La política no se activa automáticamente. Este cambio no escribe configuración del usuario ni modifica
procesos que ya estén ejecutándose. No protege clientes que lancen llama.cpp directamente, Eolas Base,
la extensión cuando usa un servidor por su cuenta ni un administrador que modifique el manifiesto.
Comprueba los bytes en disco; no certifica los pesos de un proceso ya cargado. No elimina la posibilidad
de una sustitución del archivo entre la comprobación y su apertura por el motor.

## Conexiones del motor y uso desde el chat

En Windows, `python -m eolfi modelos conexiones --pid PID` consulta TCP/UDP IPv4 e IPv6 mediante IP Helper,
sin lanzar ni detener el proceso. `modelos auditar ARCHIVO --pid PID` añade la misma instantánea al informe.
La consulta incompleta devuelve `NO VERIFICADO` y código 2; los sockets consultados se conservan.

El resultado cuenta remotos TCP y escuchas fuera de loopback, incluidos enlaces a interfaces privadas.
No distingue entrada/salida, no conoce destinos UDP ni historia, ni vincula el GGUF con los pesos cargados.
Las tablas se leen una tras otra. Si no hay filas del PID, solo se sabe que no se observaron sockets de ese
PID; no acredita que el proceso esté vivo. Una escucha no tiene extremo remoto definido. IPv4 mapeada en
IPv6 se clasifica por su dirección IPv4; los identificadores de ámbito IPv6 se convierten de orden de red.
En Linux/macOS este proveedor sigue **NO VERIFICADO**, sin fingir una tabla vacía satisfactoria.

El chat y los clientes MCP tienen `eolfi_modelos_auditar` (solo lectura, argumento `ruta`). Respeta las
raíces configuradas y sirve para los adjuntos `.bin` cuyo contenido sea GGUF. No inicia el motor ni cambia
la lista de confianza. Los resultados se marcan como datos del objetivo, no instrucciones. Para adjuntos
nombrados `.gguf` y rutas locales `.gguf`, el contexto indica usar este auditor sin ejecutar plantillas;
el tipo real se valida por la cabecera. La elección efectiva de herramienta por un modelo real sigue
**NO VERIFICADA**; las pruebas del bucle sustituyen solo su respuesta y ejecutan el auditor real.

## Pendientes del bloque G

La preparación y ejecución explícita de cuantizaciones se describen en [Reconstrucción de modelos](modelos-reconstruccion.md).
No adopta un modelo ni añade sus hashes al manifiesto de confianza.

G1 conserva pendientes los layouts ambiguos y los proveedores de conexiones Linux/macOS. G2 requiere extender y activar la política en todas
las rutas de carga y aprobar una lista con procedencia contrastada. G3–G7 conservan su estado pendiente
o parcial en `PLAN_DEFINITIVO.md`: aislamiento, reconstrucciones reales, actualizaciones, compatibilidad y LoRA.
