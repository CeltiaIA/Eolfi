# Lo que queda del plan definitivo (18/11/2026)

Fuente: `PLAN_DEFINITIVO.md` en `main` más las ramas de hoy (#85 Go y la de Rust, aún sin fusionar). Un punto
«hecho en local» o «verificado con simulación» no cuenta como verificado en real: se marca aparte.

## Resumen

| Estado | Puntos |
|---|---|
| Hechos | A1–A8, B2, B3, B4, C5, D2 (Go y Rust, pendientes de fusionar), E1, F2 (Eolfi), F4 |
| Parciales | B1, B6, B7, B8, C1, C2, C3, C4, C6, G1, G2, G3, G4, G5, G6 |
| Sin empezar | A9, C7, D3, E4, F3, G7 |
| Sin verificar en real | B5, E2 |

## 1. Lo que puedo hacer sin permisos especiales (orden propuesto)

| # | Qué falta | Por qué en este orden |
|---|---|---|
| B1 | Juez funcional en los destinos de escritorio y móvil (Electron, Tauri, .NET, Expo web). Go ya está (18/11, 3/3 con axe) | Sin juez, la accesibilidad (axe) de esos destinos queda NO VERIFICADA |
| C4 | Despliegue real en un hosting (comentarios en inglés y PWA con Vite hechos el 18/11) | Pide un hosting y permiso para publicar |
| C1 | **Hecho (18/11):** también los avisos de la CLI por stderr (`StderrTraducido` + `AVISOS_EN`, comprobado con AST) | — |
| D1 | **Hecho (18/11):** CLI, API y panel. Falta solo probarlo con un repositorio remoto real (pide red) | — |
| E3 | Exportar el paquete completo de evidencias de REA | **Hecho (18/11):** `--paquete CARPETA` y `comprobar-paquete`; REA real importó el paquete (5 registros) |
| C3 | `eolfi web --render`: interacciones (clics, formularios) | La prueba contra un sitio público sí pide autorización |
| A9 | Voz en el chat `@eolfi` de VS Code y en Fios (reutilizando `/api/voz`) | Probarlo de verdad pide un VS Code real y micrófono |
| C7 | Revisar el panel en el móvil (interfaz Android) con la voz | Necesita un móvil o emulador para verificarlo |
| B8 | Firma automática del registro de acciones (hoy la firma HMAC es a mano) | Cierra el registro encadenado |

## 2. Lo que necesita el modelo real (GPU, minutos u horas de banco)

| # | Qué falta |
|---|---|
| B5 | Los bancos «contador» y «filtro» con un modelo real (los jueces están validados con apps de referencia) |
| B6 | Prueba controlada del bucle generar → juez → reparar con el modelo real |
| B7 | Nueva ronda completa del RSI y más superficies de mejora |
| D3 | Comparar modelos mayores ahora que el banco es reproducible (B2/B3 cerrados hoy: 5/5 pares idénticos) |
| E2 | Probar en vivo la autorización por caso con un modelo |
| G1 | Comprobar que el modelo real elige la herramienta nueva del auditor; layouts K con procedencia demostrable |
| G4/G6 | Banco de calidad sobre la reconstrucción Q4_K_M y ajuste definitivo de memoria y rendimiento |
| — | Examen real de herramientas de un perfil de modelo (GPU + Docker; preguntar antes) |
| G7 | Ajuste fino (LoRA) con los ejemplos verificados: largo plazo, depende del hardware |

## 3. Lo que depende de tu decisión o permiso

| # | Qué falta | Qué hace falta de ti |
|---|---|---|
| F3 | Revisar `REGISTRO_LIMPIEZA.md` (LIM-040 primero; ahora con las secciones de Alejandría) | Decidir qué se retira |
| — | Los 4 ejemplos «filtro» que dejó el banco en `~/.eolfi/assist-verified.jsonl` | OK para borrarlos (o conservarlos) |
| C6 | Retirar opciones según `informes/revision-retirada-y-limpieza-2026-11-12.md` | Decisión por fila |
| C2 | Firma del ejecutable, `pipx` real, `.desktop` en Linux real y macOS, publicar una versión | Certificado de firma y permiso para publicar |
| G2 | Aprobar los hashes de origen de la lista de modelos de confianza (Eolas Base y otros clientes) | Aprobación de hashes |
| G3 | Regla de cortafuegos de salida para el modo sin red | Ejecutarla tú (cambia la seguridad del sistema) |
| G5 | Consulta real de versiones nuevas de modelos y reanudación de descargas | Permiso de red |
| E4 | Npcap, sigrok y Cutter (Npcap instala un controlador) | Permiso por herramienta |
| F1/F2 | CI de CeltiaIA/CeltiaIA sin comprobar y sus PR #6–#13 abiertas | Cambios en CeltIA: tu confirmación |

## 4. Hecho pero sin verificar en real

- Encargos del chat a `@eolfi` en un VS Code real (#79; probado con VS Code simulado).
- Voz con micrófono real (A1–A6).
- `assist` con el idioma del proyecto usando un modelo real (#81; probado con proveedor simulado).
- Proyectos en inglés de react, vue, svelte, next, express, expo, desktop, django y dotnet con sus propias pruebas
  (exigen instalar dependencias); Go y Rust en inglés sí están verificados.
- Unity IL2CPP con un juego real de Android o iOS (#80; probado con las compilaciones de Cpp2IL).
- Go y Rust en macOS y Linux (los cubre el CI generado; verificados en Windows).

## Hoy (18/11)

Fusionados #78 (C4 idioma), #79 (encargos a VS Code), #80 (Unity IL2CPP), #81 (assist con idioma), #82 (banco
B2/B3: 5/5 pares idénticos), #83 (prueba intermitente) y #84 (README y DEPLOYMENT.md en inglés). Abiertos con
fusión automática: #85 (destino Go) y la rama de Rust (`luis/d2-rust`).
