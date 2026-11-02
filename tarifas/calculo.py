"""Conversión configurable de la escala de una fuente al costo diario y a la hora facturable.

    costo_diario          = base_diaria x factor_rol x (1 + cargas_sociales) x factor_multiplicador
    base_diaria           = diario | semanal / dias_semana | mensual / dias_mes | hora x horas_jornada
    costo_hora_facturable = costo_diario x (1 + overhead) / horas_jornada

La columna C de la planilla guarda el costo diario; la columna S calcula la hora con
=C*(1+Factor_Overhead)/8, que es la misma fórmula de costo_hora_facturable.
"""
from __future__ import annotations

from .normalizar import formato_ars


class ErrorCalculo(ValueError):
    pass


def base_diaria(valores: dict[str, float], unidad: str, calc: dict) -> tuple[float, str]:
    if unidad not in valores:
        raise ErrorCalculo(f"la fuente no informa el valor '{unidad}' (tiene: {', '.join(valores)})")
    v = valores[unidad]
    if unidad == "diario":
        return v, f"{formato_ars(v)} diario"
    if unidad == "semanal":
        d = calc.get("dias_laborables_semana", 5)
        return v / d, f"{formato_ars(v)} semanal ÷ {d} días"
    if unidad == "mensual":
        d = calc.get("dias_laborables_mes", 21)
        return v / d, f"{formato_ars(v)} mensual ÷ {d} días"
    if unidad == "hora":
        h = calc.get("horas_jornada", 8)
        return v * h, f"{formato_ars(v)} por hora × {h} h"
    raise ErrorCalculo(f"unidad desconocida: {unidad}")


def costo_diario(valores: dict[str, float], unidad: str, calc: dict, factor_rol: float = 1.0) -> tuple[float, str]:
    base, detalle = base_diaria(valores, unidad, calc)
    cargas = float(calc.get("cargas_sociales", 0) or 0)
    multiplicador = float(calc.get("factor_multiplicador", 1) or 1)
    valor = base * factor_rol * (1 + cargas) * multiplicador
    if factor_rol != 1:
        detalle += f" × {str(factor_rol).replace('.', ',')} (factor del rol)"
    if cargas:
        detalle += f" × (1 + {cargas:.0%} cargas sociales)"
    if multiplicador != 1:
        detalle += f" × {str(multiplicador).replace('.', ',')} (multiplicador)"
    if unidad == "diario" and factor_rol == 1 and not cargas and multiplicador == 1:
        return round(valor, 2), f"{formato_ars(valor)} diario, tomado tal cual de la escala"
    return round(valor, 2), f"{detalle} = {formato_ars(valor)} diario"


def hora_facturable(costo_diario_valor: float | None, overhead: float, calc: dict) -> float | None:
    if costo_diario_valor is None:
        return None
    return round(costo_diario_valor * (1 + overhead) / calc.get("horas_jornada", 8), 2)
