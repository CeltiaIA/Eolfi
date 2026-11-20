# Pendientes vigentes — 20/11/2026

Este inventario distingue el trabajo ejecutable del estado histórico acumulado en PLAN_DEFINITIVO. No convierte los límites externos en tareas terminadas. No autoriza activar confianza, cambiar cortafuegos, publicar versiones ni retirar candidatos a limpieza.

## Correcciones locales en validación

- Encargos del chat: no aceptar una consulta correcta como prueba de proyecto creado; exigir identidad, último estado terminado y verificación. Pruebas focales: 185 aprobadas antes de la siguiente corrección.
- MCP: validar tipos, campos requeridos/desconocidos, enumeraciones y rangos de los esquemas planos publicados antes de ejecutar; rechazar parámetros de protocolo y argumentos de tipo incorrecto. Prueba MCP final: 33 aprobadas. Conjunto ampliado anterior a los diez controles de borde finales: 208 aprobadas.
- Cierre de las cuatro suites sobre el conjunto acumulado: EN CURSO, `.pytest-tmp-tableta-historial/cierre-cascada-global.log`. No reutilizar el cierre del commit anterior como validación de este árbol.
- Revisión y publicación: pendientes sobre la tanda final; registrar hash, rama y resultado de las comprobaciones al cerrar. Sin commit/push en esta continuación.

## Estados antiguos que ya no son el bloqueo vigente

- **C7:** el navegador Android 4.1 falló, pero se implementó la app nativa. Se contrastaron directamente por `GET http://127.0.0.1:8777/api/jobs?id=…` los trabajos `519fe2ae7a6ee451` y `d7dd50667b5148b4`: estado `done`, texto y herramienta correcta. El identificador `2e4d9ec720c7f409`, citado en ESTADO para una prueba anterior del Redmi, devuelve 404 en la API activa y no aparece en la base predeterminada consultada: esa evidencia no se recuperó. Esto no invalida los otros dos trabajos ni demuestra por sí solo un defecto de persistencia. **Causa (20/11 20:25, Claude):** `server.py` guarda en `job_history` solo los 4 trabajos más recientes (`HISTORY_KEEP = 4`) y borra el resto con sus resultados; a las 20:25 ya tampoco estaba `519fe2ae7a6ee451`. Los identificadores citados en ESTADO solo se pueden contrastar mientras sigan entre los 4 últimos. Ampliar ese límite o exportar las evidencias es una decisión pendiente; no se ha cambiado.
- **G6:** el final de la fila recoge los exámenes posteriores, admisión y activación del reconstruido. Las propuestas iniciales de igualar el perfil y el examen aislado no son el estado final; no hay que aplicar esos cambios otra vez.
- **B6:** ya hay ejecución real con varias rondas y conservación de una ronda parcial; sigue pendiente el escenario distinto de restauración completa sin ronda parcial. No repetir la petición antigua genérica de «más de una ronda» como si no se hubiera ejecutado.
- **E4:** Cutter portátil y su Rizin incluido se detectan. Sigue sin acreditar el puente hacia una sesión viva de Cutter; instalarlo otra vez no resuelve esa comprobación.

## Trabajo que necesita entorno o evidencia adicional

| Punto | Qué falta | Requisito para cerrarlo |
|---|---|---|
| A9 | Dictado real de VS Code/Fios grabando del PC | Micrófono funcional o adaptador adecuado; hablar y contrastar texto sin envío involuntario. |
| B6 | Restauración completa real cuando ninguna ronda es parcial ni verde | Escenario autorizado con modelo y criterios, comprobar archivos/hash originales y ausencia de incorporación a memoria. |
| B7 | Ampliar perfiles, dificultad y superficies RSI | Seleccionar modelos disponibles o autorizar descargas, ejecutar banco comparable; no confundir el examen con una mejora demostrada. |
| C2 | Firma y publicación real, pipx y otros sistemas | Certificado/SignTool, versión concreta autorizada y entornos Linux/macOS. |
| B1/C4/D2 | Expo real, dependencias/frontend, despliegue y ejecución nativa/multiplataforma | SDK/dependencias y destinos correspondientes; Chrome no prueba el puente nativo. |
| C5 | Mapa de app con artefacto real y navegación dinámica | Muestra autorizada y entorno de ejecución apropiado; estático no acredita navegación. |
| C7 | ~~Dictado nuevo de extremo a extremo y prueba por datos móviles~~ Hecho 20/11 20:21 | Redmi con SIM, WiFi apagada, Tailscale (relé DERP de Madrid): dictado → `POST /api/voz/transcribir` 200 → chat `b93059a1f53c2bee` con `eolfi_evidencias` ok (70,7 s) → `POST /api/voz/hablar` 200, todo desde 100.112.119.31. Antes, `GET /api/tableta/trabajos` 200 por datos con conexión directa desde una IP pública distinta de la del PC. Quedan ACL de Tailscale y cortafuegos, decisión del titular. |
| E4 | Sesión viva de Cutter con REA | Proveedor de conexión soportado y prueba de operación contra la sesión, sin sustituirla por mera detección del ejecutable. |
| G1/G4 | Proveedores de sockets en Linux/macOS y procedencia de herramientas/modelos | Ejecución en esos sistemas y referencia independiente de procedencia; estructura y hash locales no acreditan origen. |
| G5 | Consulta/descarga remota y adopción real | Versión concreta y permiso de red/descarga; conservar commit, SHA-256 y comparación completa antes de adoptar. |
| G7 | Entrenamiento LoRA | Datos verificados suficientes (el plan registra dos peticiones frente a veinte mínimas), dependencias y hardware; no entrenar con datos inventados para marcarlo cerrado. |

## Decisiones reservadas al titular

- **G2:** aprobar hashes y activar la política de confianza. La auditoría estructural no decide procedencia por el titular.
- **G3 y acceso remoto:** aplicar/verificar reglas de cortafuegos y ACL Tailscale concretas. Conservar la conexión actual hasta disponer de una decisión y un cambio revisable.
- **F3/C6:** revisar candidatos del REGISTRO_LIMPIEZA y opciones que se propone retirar. Mantener copias, credenciales y cambios sin confirmar; no borrar ni mover para aparentar cierre.
- **F1/F2 fuera de Eolfi:** comprobar facturación/CI y PR de CeltiaIA en su repositorio antes de afirmar que quedan resueltas. El estado de Eolfi no lo demuestra.

## Evidencia y límites de esta revisión

Comprobación actual de requisitos, sin entrenamiento ni instalación: `.pytest-tmp-tableta-historial/requisitos_pendientes.py` detecta `pipx` ausente tanto como módulo del Python usado como ejecutable en PATH, y `signtool` ausente en PATH. El exportador real `dataset_memoria_verificada` rechaza preparar el dataset con «2 ejemplos; mínimo 20». `load_config(create=False)` confirma `gemma4_recon_q4` como perfil activo. Son comprobaciones de disponibilidad en este entorno; no prueban ausencia de herramientas en cualquier otra instalación o sistema.

La lectura de API fue de solo lectura y no repitió inferencia ni manejó la pantalla de los dispositivos. Registros de contraste privados en `.pytest-tmp-tableta-historial/consultar_panel.json` y `verificar_dispositivos.py` (LIM-067); el segundo intento señaló evidencia ausente, no éxito. La lista no demuestra ausencia de defectos fuera de lo revisado ni cierra puntos de hardware, red, permisos o decisiones sin ejecutar su comprobación.
