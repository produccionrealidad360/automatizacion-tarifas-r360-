"""Actualización automatizada y trazable de tarifas para el template de presupuesto de Realidad 360.

Flujo: extraer (fuentes oficiales) -> conciliar (mapeo con los roles de la planilla y validación)
-> publicar (costo diario, notas de auditoría y pestaña Fuentes_Tarifas) -> alertar.
"""

__version__ = "0.1.0"
