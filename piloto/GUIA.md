# Guía del piloto · Registro como Proveedor

**Qué es:** usar el agente con 7 solicitudes, como lo haría la analista, y compararlo con
el trabajo a mano. Es el Paso 21: al final hay métricas y una lista de ajustes.

**Qué casos:** los 4 de referencia (Colombia, Ecuador, Honduras y Panamá) y **3 nuevos**,
ficticios y más desordenados, como suelen llegar de clientes reales (en `piloto/casos/`):

| Caso | Cliente | Formato | Qué pone a prueba |
|---|---|---|---|
| `co-constructora-andes` | Constructora Andes S.A.S. (Colombia) | PDF | Etiquetas escritas distinto («Nombre / Razón Social», «Tel.», «Cta. bancaria N°») |
| `ec-distribuidora-pacifico` | Distribuidora del Pacífico S.A. (Ecuador) | Portal web | Un soporte vencido y etiquetas parecidas («Teléfono de contacto», «Código SWIFT») |
| `pe-mineria-del-sur` | Minería del Sur S.A.C. (Perú) | Excel | Un país nuevo para el agente: casi todo debería salir bien |

**Costo:** usa la clave de Anthropic de `.env`, unos USD 0.005 por caso (menos de
USD 0.10 en total). Se hace **en el computador**, no en Render: allá los registros se
borran cuando el servidor se apaga.

## 1. Preparar (una vez)

```powershell
uv run python scripts/preparar_piloto.py
```

Arma `piloto/datos-del-piloto/` (los 4 casos de referencia + los 3 nuevos) y lo valida.
Después, en `.env`:

```
CARPETA_DATOS=piloto/datos-del-piloto
FECHA_EJECUCION=
SALIDA_POR_CONVERSACION=false
```

Para empezar con `out/` limpio (sin pruebas anteriores), borre la carpeta `out/` o corra
`uv run python scripts/demo.py` y luego vuelva a borrarla.

## 2. Trabajar los casos

```powershell
uv run uvicorn registro_proveedor.api.app:app
```

En <http://127.0.0.1:8000>, para **cada caso**:

1. Anote la hora de inicio.
2. Escriba como lo haría la analista: «Prepara el caso de Constructora Andes».
3. Revise el resumen: los campos llenos, los faltantes, los por confirmar y los
   soportes. **Descargue el paquete (.zip)** y mire el formulario (vista demo).
4. Para cada campo por confirmar, decida como si fuera real: «Acepto…» o «Déjalo
   vacío», y pulse **Aprobar**. Si el valor propuesto está mal, **rechácelo**.
5. Si el paquete queda listo, pida «Registra el envío» y pulse **Aprobar**.
6. Debajo de cada respuesta, marque **👍 o 👎** y, si algo estuvo mal o confuso, escriba
   un comentario corto.
7. Anote la hora de fin y llene su fila en `piloto/planilla.md`.

Sugerencia: un caso por conversación («Nueva conversación» entre uno y otro).

## 3. Medir

```powershell
uv run python scripts/metricas_piloto.py
```

Escribe `piloto/reporte.md` con:

- **O1:** % de los campos que existen en el maestro que se llenaron solos (casos nuevos).
- **O2:** valores inventados (debe ser 0) y valores puestos en el campo equivocado.
- **O3:** confirmaciones y envíos sin aprobación (debe ser 0).
- **O4:** sus minutos, de la planilla (meta: menos de 15 por solicitud).
- **O5:** soportes vencidos o por vencer señalados (debe ser 100 %).
- La exactitud del mapeo caso por caso (aciertos, no reconocidos, errores), los
  👍 / 👎 con sus comentarios y la planilla.

La "respuesta correcta" de los casos nuevos (qué dato del maestro corresponde a cada
etiqueta) está en `piloto/esperado/`: con ella se miden aciertos y errores.

## 4. Al terminar

1. Avísele a Claude: él lee el reporte y escribe los resultados y la lista de ajustes
   priorizada en `SOLUCION.md` (B11).
2. Deje `.env` como estaba: `CARPETA_DATOS=` vacía.
