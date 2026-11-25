"""El agente: conversa con la analista y decide qué herramienta pedir.

- `llm/`: el adaptador del modelo de lenguaje (Paso 10).
- Más adelante: el ciclo del agente (Paso 12), la confirmación humana (Paso 13) y los
  guardarraíles (Paso 14).

Regla de capas: el agente usa las herramientas (`herramientas/`), y el dominio no sabe
nada del agente.
"""
