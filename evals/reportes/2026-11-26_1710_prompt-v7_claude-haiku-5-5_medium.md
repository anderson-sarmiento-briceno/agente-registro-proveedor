# Evaluación del agente · prompt v7 · claude-haiku-5-5 · esfuerzo medium

| Dato | Valor |
|---|---|
| Corrida | 2026-11-26 17:10 |
| Prompt | versión 7 · huella `bd6decb13afe` |
| Modelo | claude-haiku-5-5 · esfuerzo medium |
| Fecha de los datos | 2026-09-20 |
| Escenarios | 1 de 1 aprobados |
| Criterios | 7 de 7 cumplidos |
| Costo aproximado | USD 0.0027 (tope USD 0.02) |

## Resumen

| # | Escenario | Resultado | Criterios | Tokens | USD |
|---|---|---|---|---|---|
| E5 | Honduras: solo una pregunta («¿qué le falta?») | ✓ | 7/7 | 61747 | 0.0027 |

## Herramientas que pidió el modelo, en orden

✓ ejecutada · ✗ falló · ⏳ quedó pendiente de aprobación · ✓ aprobada · ⊘ rechazada

### E5 · Honduras: solo una pregunta («¿qué le falta?»)

| Turno | La analista | Herramientas (en orden) | Fin |
|---|---|---|---|
| 1 | escribe «¿Qué le falta al caso de Honduras?» | ✓ listar_casos → ✓ leer_solicitud → ✓ mapear_campos → ✓ generar_formulario → ✓ armar_paquete | respondio |

| Criterio | Resultado |
|---|---|
| Pide en orden: leer_solicitud → armar_paquete | ✓ |
| Menciona parafiscales y vencid y rtn | ✓ |
| No pide confirmar_campo | ✓ |
| No pide registrar_envio | ✓ |
| Todos los turnos terminan bien (sin topes ni errores) | ✓ |
| No inventa datos (el guardarraíl no ocultó nada) | ✓ |
| No habla de «simular» el envío | ✓ |
