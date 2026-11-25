"""Adaptador del modelo de lenguaje (Paso 10).

- `adaptador.py`: nuestros tipos (neutrales, de ningún proveedor) y el contrato
  `AdaptadorLLM`. El resto del agente solo conoce esto.
- `proveedor_anthropic.py`: la implementación con el SDK oficial de Anthropic.
- `falso.py`: un modelo falso con guion, para probar el agente sin clave ni costo.

Cambiar de proveedor = escribir otra implementación de `AdaptadorLLM`. El ciclo del
agente no cambia (decisión D3).
"""
