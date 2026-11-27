---
name: "registro-proveedor"
description: "Conocimiento del proceso de registro como proveedor: identificador tributario por país, soportes que piden los clientes y sus estados (vigente, por vencer, vencido, ausente), estados de un campo y formatos de formulario. Úsala cuando haya que preparar o explicar un registro de proveedor."
---

# Conocimiento del proceso: registro como proveedor

Este texto explica el proceso para que usted pueda **contárselo** a la analista. Las decisiones (qué valor va en cada campo, si un soporte está vencido, si el paquete está listo) las toman las herramientas con reglas fijas; usted no las recalcula.

## Qué es un registro como proveedor

Antes de comprarle a la empresa, cada cliente pide que se registre como proveedor: llenar su formulario con los datos de la empresa (razón social, identificador tributario, dirección, contactos, datos bancarios…) y adjuntar documentos de soporte. La analista prepara todo y una persona autorizada lo firma.

Los datos de la empresa salen del **repositorio maestro**, que es la única fuente de valores. Si el maestro no tiene un dato, el campo queda **faltante**: no se inventa. Mejorar el maestro le corresponde a su dueño, no al agente.

## Estados de un campo

| Estado | Qué significa | Qué hacer |
|---|---|---|
| `lleno` | El valor salió del maestro con seguridad. | Nada. |
| `requiere_confirmacion` | Hay un valor propuesto, pero no es seguro. | La analista decide: aceptar o dejar faltante. |
| `faltante` | El maestro no tiene ese dato, o la etiqueta no se reconoció. | Queda vacío y resaltado; aparece en el checklist. |

Un campo por confirmar **bloquea** la firma hasta que la analista decida. Un faltante no la bloquea, pero se avisa.

## Identificador tributario por país

La empresa es colombiana y solo tiene **NIT**. Cada país llama distinto a su identificador:

| País | Nombre | Identificador |
|---|---|---|
| CO | Colombia | NIT |
| EC | Ecuador | RUC |
| PE | Perú | RUC |
| PA | Panamá | RUC |
| HN | Honduras | RTN |

Si el cliente no es de Colombia, el campo se llena con el NIT pero queda **por confirmar**, con la nota "identificador extranjero". La analista decide si el cliente lo acepta.

## Datos bancarios

Se llenan solo si el formulario del cliente los pide. **Nunca** van en el borrador del correo. En el chat se dice solo si quedaron llenos; el número de cuenta se ve enmascarado (como `****2345`).

## Soportes (documentos)

Los documentos que puede exigir un cliente son:

- Cámara de Comercio
- RUT
- Certificación bancaria
- Certificación de parafiscales
- Estados financieros
- Certificado ISO 9001
- Certificado de cumplimiento tributario

**Cada cliente exige solo algunos**, y no todos los mismos. En el checklist aparecen únicamente los que exige ese cliente; los demás documentos del repositorio no se revisan para ese caso.

Cada soporte exigido queda en uno de estos estados, comparando su vigencia con la fecha de ejecución:

| Estado | Qué significa | ¿Bloquea la firma? |
|---|---|---|
| `presente` | La empresa lo tiene y está vigente. | No |
| `por_vencer` | Lo tiene, pero vence en 15 días o menos. | No, pero se avisa |
| `vencido` | Lo tiene, pero ya venció. | Sí: hay que renovarlo |
| `ausente` | El cliente lo exige y la empresa no lo tiene. | Sí: hay que conseguirlo |

## Formatos del formulario

- **Excel** (`xlsx`): se genera un Excel con cada etiqueta y su valor en la hoja y la celda que indica la plantilla del cliente.
- **PDF** (`pdf`): se genera un PDF con cada etiqueta y su valor, en el orden pedido.
- **Portal** (`portal`): el portal web no se llena automáticamente. Se generan los valores listos para copiar (`valores-portal.md`) y la analista los pega en el portal.

Los campos faltantes y por confirmar quedan **vacíos** en el formulario (nunca con un texto de relleno).

## El paquete para firma

`proveedor_armar_paquete` crea la carpeta `out/<caso>/paquete/` con:

- el formulario,
- las copias de los soportes exigidos que existen,
- `checklist.md`: estado de cada soporte y de los campos,
- `borrador-correo.md`: un borrador para el cliente, sin datos bancarios,
- `manifiesto.json`: de dónde salió cada valor, para auditoría.

**Listo para firma** significa: ningún soporte vencido o ausente y ningún campo por confirmar. Si no está listo, la herramienta da los motivos: explíquelos uno por uno y diga qué haría falta.

## Después del paquete: registrar el envío

La analista revisa el paquete y decide. Si el paquete está **listo para firma** y ella pide enviarlo, `proveedor_registrar_envio` (con su aprobación) registra el envío en la constancia `out/<caso>/constancia-envio.md`: destinatario y asunto (los del correo del cliente), los archivos del paquete con su huella y quién lo aprobó. **En modo piloto no se envía nada de verdad:** la entrega al cliente la hace la analista fuera del sistema.

El envío se niega si el paquete no está listo, o si quedó desactualizado: se confirmó un campo después de armarlo, cambió la fecha de ejecución o cambió algún archivo. En ese caso hay que volver a armar el paquete.

## Aprobaciones

Confirmar un campo y registrar el envío necesitan la **aprobación explícita** de la analista con los botones Aprobar / Rechazar. Un "sí" escrito en el chat no aprueba. Si ella escribe otro mensaje sin aprobar, la acción pendiente se cancela. Todo queda registrado en `log.jsonl`: qué se pidió, quién lo aprobó o rechazó, y cuándo.
