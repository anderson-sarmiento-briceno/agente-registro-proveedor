# Reporte tras los ajustes del piloto (sin modelo, los 7 casos)

Generado el 2026-11-27 15:43 con `scripts/metricas_piloto.py`. Casos trabajados: **7**.

## Objetivos del plan

| Objetivo | Meta | Resultado | |
|---|---|---|---|
| O1 · Llenar sin transcribir (casos nuevos) | 100 % | 57% (21 de 37 campos que existen en el maestro) | ⚠️ |
| O2 · Ningún valor inventado | 0 | 0 | ✅ |
| O2 · Ningún valor en el campo equivocado (casos nuevos) | 0 | 0 | ✅ |
| O3 · Ninguna acción sin aprobación | 0 | 0 de 0 acciones | ✅ |
| O4 · Minutos de trabajo por solicitud (planilla) | < 15 | — en promedio (0 casos anotados) | falta anotar |
| O5 · Soportes vencidos o por vencer señalados | 100 % | 2 de 2 | ✅ |

## Caso por caso

| Caso | Campos | Llenos | Faltantes | Por confirmar | Decisiones | O1 | Listo | Errores de herramientas | Minutos | USD |
|---|---|---|---|---|---|---|---|---|---|---|
| co-constructora-andes | 15 | 4 | 11 | 0 | 0 aceptados · 0 vacíos | 29% | No | 0 | 0.0 | 0.0000 |
| co-industrias-delta | 17 | 17 | 0 | 0 | 0 aceptados · 0 vacíos | — | Sí | 0 | 0.0 | 0.0000 |
| ec-corp-andina | 15 | 13 | 1 | 1 | 0 aceptados · 0 vacíos | — | No | 0 | 0.0 | 0.0000 |
| ec-distribuidora-pacifico | 10 | 6 | 2 | 2 | 0 aceptados · 0 vacíos | 60% | No | 0 | 0.0 | 0.0000 |
| hn-agroexport-sula | 11 | 9 | 1 | 1 | 0 aceptados · 0 vacíos | — | No | 0 | 0.0 | 0.0000 |
| pa-logistica-istmo | 9 | 8 | 0 | 1 | 0 aceptados · 0 vacíos | — | No | 0 | 0.0 | 0.0000 |
| pe-mineria-del-sur | 13 | 11 | 1 | 1 | 0 aceptados · 0 vacíos | 85% | No | 0 | 0.0 | 0.0000 |

## Exactitud del mapeo (casos nuevos, contra la respuesta correcta)

| Caso | Aciertos | Por confirmar (dato correcto) | No reconocidos | Llenados en el campo equivocado | Propuestas equivocadas | Faltantes reales |
|---|---|---|---|---|---|---|
| co-constructora-andes | 4 | 0 | 10 | 0 | 0 | 1 |
| ec-distribuidora-pacifico | 6 | 1 | 2 | 0 | 1 | 0 |
| pe-mineria-del-sur | 11 | 1 | 1 | 0 | 0 | 0 |

- ⚠️ **ec-distribuidora-pacifico** · propuesta equivocada (por confirmar): Nombre del contacto comercial (usó contacto_comercial.telefono, era contacto_comercial.nombre)

**Etiquetas que existían en el maestro y no se reconocieron** (candidatas al glosario, con la aprobación del dueño del dato):

| Etiqueta del cliente | Dato del maestro |
|---|---|
| C.C. Representante Legal | `representante_legal.identificacion` |
| Cta. bancaria N° | `banco.numero_cuenta` |
| Código SWIFT | `banco.swift` |
| DV | `digito_verificacion` |
| Dirección principal | `direccion` |
| E-mail corporativo | `contacto_comercial.email` |
| Moneda de la cuenta | `banco.moneda` |
| NIT (sin dígito de verificación) | `nit` |
| Nombre / Razón Social | `razon_social` |
| Número de trabajadores | `numero_empleados` |
| Representante Legal (nombre completo) | `representante_legal.nombre` |
| Tel. | `telefono` |
| Teléfono de contacto | `telefono` |

## Opiniones en el chat (👍 / 👎)

Todavía no hay opiniones registradas.

## Planilla (lo que anotó quien hizo el piloto)

La planilla `piloto/planilla.md` todavía está vacía.
