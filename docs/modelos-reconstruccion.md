# Reconstrucción por cuantización: receta y ejecución local

`modelos reconstruir` prepara una receta para convertir un GGUF flotante monolítico con un cuantizador
local ya instalado. Se admiten entradas F32, F16 y BF16 y los presets Q4_0, Q3_K_M, Q4_K_M, Q5_K_M, Q6_K y Q8_0.
Se rechazan pesos ya cuantizados, entradas divididas (también renombradas) y cantidades de capas inválidas.
La compatibilidad semántica completa del modelo con el SDK sigue requiriendo una ejecución y un smoke.

## Preparar

```powershell
python -m eolfi modelos reconstruir 'D:\AI\Hydra\gguf\gemma-4-12b-it-BF16.gguf' --out 'D:\Eolfi\generated\modelos\gemma4-q4_k_m-2026-11-16' --cuantizador 'D:\EOLAS-BASE\llama\llama-quantize.exe' --tipo Q4_K_M
```

Por defecto no ejecuta el cuantizador ni crea la carpeta de salida: imprime JSON con `estado: preparado`
y `ejecutado: false`, código 0. Lee el archivo completo para calcular su SHA-256. La receta contiene el
hash de entrada, nombres/formas de tensores, metadatos del planificador, plantilla, argumentos, límites
y la identidad del ejecutable y sus bibliotecas locales. No descarga herramientas ni modelos.

`herramienta.bundle_sha256` identifica el ejecutable más los nombres/hashes de las DLL, SO o dylib de su
carpeta. Fijar solo el hash del pequeño ejecutable lanzador no identifica su implementación en DLL.
El hash del paquete no demuestra procedencia, seguridad ni qué bibliotecas del sistema se cargarán.

## Ejecutar una receta revisada

Se usa la misma orden, añadiendo `--ejecutar`, `--sha256-entrada HASH` y `--sha256-paquete HASH`, con los
valores revisados de la preparación. `--sha256-cuantizador HASH` permite fijar también el ejecutable de
forma explícita. La CLI vuelve a preparar/verificar los datos; no ejecuta argumentos de un JSON arbitrario.

Parámetros: `--hilos` (1–64, predeterminado 4), `--memoria-mib` (16–4096, predeterminado 256) y `--timeout`
(hasta 86400 s, predeterminado 1800). La memoria es el buffer que acepta el cuantizador, **no un límite de
RAM del sistema**. El timeout acota el proceso de cuantización; la lectura previa y los hashes/auditorías
posteriores pueden tardar más. Se exige espacio libre conservador: tamaño de entrada más 64 MiB.

La carpeta de salida debe ser nueva. Contiene `modelo.gguf`, `cuantizador.log` y `receta.json` actualizada
durante el trabajo y al acabar. Se comprueban código de salida, estructura, arquitectura, plantilla,
metadatos del planificador y nombres/formas de tensores; después se vuelve a hashear el original.
`declaraciones_tensores_sha256` resume nombres/formas, no los valores de los pesos ni su equivalencia funcional.
El límite de registro es 16 MiB y el de salida, tamaño de entrada más 64 MiB.

Los fallos conservan el registro y los archivos parciales, sin sobrescribir un destino previo. Ctrl+C intenta
cerrar solo el proceso de esta cuantización y deja `interrumpido`; si se interrumpe el hash final, este queda
NO VERIFICADO. Un cierre forzado externo puede dejar el último estado `en_ejecucion`: hay que revisar PID y
artefactos, no asumir finalización. Si no se puede confirmar el cierre del proceso, se registra el límite.

## Resultado y siguientes comprobaciones

Incluso con código 0 del cuantizador, la CLI devuelve **2** y `estado: NO VERIFICADO`: faltan inferencia y
banco. Para distinguir una conversión terminada de un fallo, revisar `conversion.exit`, `conversion.error`,
`auditoria_salida`, `sha256_entrada_despues` y `verificacion`. Una salida del SDK distinta de cero o una
discrepancia de integridad da `fallido`. La versión que imprime el SDK se conserva como declaración del
programa, no como verificación de la release oficial.

Los presets pueden mezclar tipos: en la muestra probada, Q4_0 también genera un tensor Q6_K. Los tamaños K
con layout ambiguo permanecen NO VERIFICADOS. La cuantización no cambia perfiles ni autoriza hashes en la
lista de confianza; la adopción y el smoke corresponden a G6. Los indicadores offline del proceso no
sustituyen el cortafuegos ni implementan por sí solos el modo sin red de G3.

El proceso recibe solo variables de sistema, rutas y configuración regional necesarias. No hereda claves
del cliente, proxies ni direcciones privadas de registros pip/npm. Esto reduce la información entregada
al cuantizador, pero no demuestra que el ejecutable sea seguro ni le impide acceder a archivos o a la red.

## Pruebas nativas optativas

```powershell
$env:EOLFI_TEST_QUANTIZER = 'D:\EOLAS-BASE\llama\llama-quantize.exe'
$env:EOLFI_TEST_QUANTIZER_SHA256 = 'SHA256_REVISADO_DEL_EJECUTABLE'
python -m pytest -q tests/test_modelos_reconstruir.py
```

Sin esas variables, las seis conversiones nativas se omiten explícitamente; las pruebas de control siguen
ejecutándose. Con ellas, se cuantiza un BF16 sintético propio de una capa, se comprueban los seis presets y
se decodifica Q8 para comprobar error numérico menor de 0,003 en la matriz de referencia. Esa prueba no
demuestra la calidad de un modelo real. Las evidencias locales están en
`informes/modelos-g-2026-11-16/avance-g4-reconstruccion.md`.
