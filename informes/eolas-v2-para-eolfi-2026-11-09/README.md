# Entrega REA: Gemma 4 12B Q5_K_M

- `INFORME-REA.md`: resultados, límites, evidencia y notas para RTX 3060 Ti.
- `rea-evidence.json`: bundle REA portátil con observaciones.
- `tensor-inventory.csv`: inventario por tensor (nombres, formas, tipos y campos disponibles).
- `run-gemma4-3060ti.ps1`: lanzador PowerShell configurable para llama.cpp.
- `run-gemma4-3060ti.cmd`: envoltorio para abrir el lanzador desde CMD/Explorer.

El modelo no se ha ejecutado. La integración con el runtime instalado requiere verificación en el equipo.
Perfil predeterminado del lanzador: 8 capas GPU, contexto 32,000; carga y health check verificados, generación no probada.
