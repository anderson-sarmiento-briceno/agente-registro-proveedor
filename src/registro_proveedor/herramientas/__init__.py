"""Herramientas: envuelven el dominio con un contrato estable que usan el agente y demo.py.

Cada herramienta recibe argumentos validados y un `Contexto`, y devuelve siempre un
`Resultado` (`ok=True` con datos, u `ok=False` con un mensaje claro). Nunca lanza
excepciones. Ver `base.py`.
"""
