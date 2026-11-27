# Reporte del piloto · Registro como Proveedor

Generado el 2026-11-27 15:43 con `scripts/metricas_piloto.py`. Casos trabajados: **1**.

## Objetivos del plan

| Objetivo | Meta | Resultado | |
|---|---|---|---|
| O1 · Llenar sin transcribir (casos nuevos) | 100 % | 29% (4 de 14 campos que existen en el maestro) | ⚠️ |
| O2 · Ningún valor inventado | 0 | 0 | ✅ |
| O2 · Ningún valor en el campo equivocado (casos nuevos) | 0 | 2 | ⚠️ |
| O3 · Ninguna acción sin aprobación | 0 | 0 de 2 acciones | ✅ |
| O4 · Minutos de trabajo por solicitud (planilla) | < 15 | — en promedio (0 casos anotados) | falta anotar |
| O5 · Soportes vencidos o por vencer señalados | 100 % | 0 de 0 | ✅ |

## Caso por caso

| Caso | Campos | Llenos | Faltantes | Por confirmar | Decisiones | O1 | Listo | Errores de herramientas | Minutos | USD |
|---|---|---|---|---|---|---|---|---|---|---|
| co-constructora-andes | 15 | 6 | 9 | 0 | 1 aceptados · 0 vacíos | 29% | Sí | 0 | 2.9 | 0.0055 |

## Exactitud del mapeo (casos nuevos, contra la respuesta correcta)

| Caso | Aciertos | Por confirmar (dato correcto) | No reconocidos | Llenados en el campo equivocado | Propuestas equivocadas | Faltantes reales |
|---|---|---|---|---|---|---|
| co-constructora-andes | 4 | 0 | 8 | 2 | 0 | 1 |

- ⛔ **co-constructora-andes** · llenado en el campo equivocado: NIT (sin dígito de verificación) (usó digito_verificacion, era nit)
- ⛔ **co-constructora-andes** · llenado en el campo equivocado: C.C. Representante Legal (usó representante_legal.nombre, era representante_legal.identificacion)

**Etiquetas que existían en el maestro y no se reconocieron** (candidatas al glosario, con la aprobación del dueño del dato):

| Etiqueta del cliente | Dato del maestro |
|---|---|
| Cta. bancaria N° | `banco.numero_cuenta` |
| DV | `digito_verificacion` |
| Dirección principal | `direccion` |
| E-mail corporativo | `contacto_comercial.email` |
| Nombre / Razón Social | `razon_social` |
| Número de trabajadores | `numero_empleados` |
| Representante Legal (nombre completo) | `representante_legal.nombre` |
| Tel. | `telefono` |

## Opiniones en el chat (👍 / 👎)

Todavía no hay opiniones registradas.

## Planilla (lo que anotó quien hizo el piloto)

La planilla `piloto/planilla.md` todavía está vacía.
