# Prueba de independencia: instrucciones para la colaboradora

Gracias por hacer esta prueba. Eolfi necesita una **reconstrucción escrita por una persona independiente** para comprobar que su verificación de comportamiento distingue un programa hecho de forma independiente de uno que se limita a llamar al original.

## Qué tienes que hacer

Escribe en Python un programa que se comporte como el comando `whoami` de Linux y guárdalo en esta carpeta con el nombre **`whoami_externo.py`**.

### Comportamiento esperado (lo único que necesitas saber)

- Si se ejecuta sin argumentos, escribe en la salida estándar el **nombre del usuario efectivo** que lo ejecuta, seguido de un salto de línea, y termina con código de salida **0**.
- No escribe nada más: ni texto adicional ni espacios.

Puedes informarte de cómo funciona `whoami` con su manual (`man whoami`) o ejecutando el comando `whoami` en una terminal. Eso es observar el comportamiento, y está permitido.

### Reglas (son lo que hace válida la prueba)

1. **No mires** ninguna reconstrucción existente: ni `whoami_rec.py` ni otros archivos `whoami_*.py`. Tampoco mires el código fuente de coreutils.
2. **Solo la biblioteca estándar de Python.** Nada de `pip install`.
3. **Prohibido** lanzar otros programas o código dinámico: `subprocess`, `os.system`, `os.popen`, `os.exec*`, `os.spawn*`, `ctypes`, `eval`, `exec`, ni `getattr` con nombres construidos.
4. **No llames a `whoami`** de ninguna forma: el programa tiene que obtener el nombre por sí mismo.
5. Si usas alguna ayuda (documentación de Python, buscadores), anótala abajo. No uses asistentes de IA que puedan haber visto la reconstrucción existente.

### Cuando termines

Rellena esto y avisa al titular:

- Hora de inicio y de fin:
- Fuentes consultadas:
- ¿Has visto alguna reconstrucción existente? (sí/no):

## Registro (14/11/2026)

- `whoami_externo.py` lo pegó el titular en el chat y quedó guardado en esta carpeta (entonces con otro nombre de archivo; el contenido es el mismo). SHA-256: `a8622fab53cdbc22a161a13e53216f6cb9d98a918fb797b41667414f6460e6a9`.
- **Procedencia, pendiente de confirmar:** el texto pegado acaba con «Use code with caution.» y una explicación en el formato típico de un asistente de IA web. Es muy probable que el código lo generase un asistente de IA, no la colaboradora escribiéndolo a mano. Ese asistente no puede haber visto `whoami_rec.py`, porque no está publicado, así que no incumple la regla 5. Aun así, la prueba pasa a ser «reconstrucción independiente asistida por IA», no «escrita por una persona». Falta que la colaboradora rellene los campos de arriba.
- **Revisión estática** (`_static_python` de `D:\Eolfi-wt-comp`, rama `prueba-independencia`, sin ejecutar el archivo): 0 primitivas de proceso o de código dinámico, 0 importaciones fuera de la biblioteca estándar (`os`, `pwd`, `sys`). Literales: `__main__` y `whoami: cannot find name for user ID `; el segundo no cuenta como mención al original según el patrón de Eolfi.
- **Prueba en vivo** (14/11/2026, permiso del titular: «Sí, una vez»). Se usó el código de `D:\Eolfi-wt-comp` (rama `prueba-independencia`, sin commit) a través del REA de WSL. Se aprobaron «una vez» dos ejecuciones: `/usr/bin/whoami` y `/usr/bin/python3 …/informes/<carpeta de la prueba>/<archivo>.py`. Guion y resultado: `vivo_<colaboradora>.py` y `resultado_<colaboradora>.json`, en el scratchpad de la sesión.
  - **Comportamiento según Eolfi:** salida «igual» y terminal «igual». Los dos programas terminan con código 0 y escriben el nombre de la cuenta local.
  - **Independencia:** **«pass»**, ruta al original `none`. Parte estática limpia; en ejecución, 1 proceso muestreado y ninguno es el original.
  - **Cobertura:** sigue «failed», con 3 razones ajenas a esta prueba:
    - `owner-distribution-unknown`: falta declarar cómo se distribuye el módulo.
    - `verifier-failed`: el verificador de REA falla en `exit` por el tiempo de cierre (ya conocido).
    - `verifier-unknown`: en `terminal`.
  - REA ya no pide la prueba de independencia.
  - **Límites:** solo se han comprobado procesos, no red ni servicios. El muestreo de procesos de REA puede no ver hijos de muy corta duración; por eso la parte estática es la que pesa. Sobre la procedencia, ver el punto de arriba.

## Qué pasará después (lo hace Eolfi, con permiso del titular)

1. REA ejecuta el `/usr/bin/whoami` original y tu `whoami_externo.py` en el mismo escenario (en WSL) y compara la salida y el código de salida.
2. La prueba de independencia revisa tu archivo sin ejecutarlo, buscando primitivas para lanzar programas, y examina los procesos que tu programa crea al ejecutarse, por si aparece el original.
3. Resultado esperado: comportamiento «igual» e independencia «pass». Cualquier otro resultado se anota tal cual, sin retocarlo.
