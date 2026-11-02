"""Interfaz común de la planilla. La lógica de lectura de roles vive acá para que ambos backends
(Google Sheets y .xlsx) se comporten igual."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..modelos import FilaRol

VERDADEROS = {"true", "verdadero", "1", "si", "sí", "x"}


def _numero(valor) -> float | None:
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    return None


class HojaDeCalculo(ABC):
    def __init__(self, plantilla: dict):
        self.cfg = plantilla

    # --- lectura -------------------------------------------------------------------------------
    @abstractmethod
    def _leer_bloque_roles(self) -> tuple[list[list], list]:
        """Devuelve (filas con valores de las columnas A..C, fórmulas de la columna C)."""

    @abstractmethod
    def leer_overhead(self, nombre_rango: str) -> float | None:
        ...

    @abstractmethod
    def _leer_trazabilidad(self) -> list[list]:
        """Valores sin formato de la pestaña de trazabilidad (vacío si no existe)."""

    def leer_roles(self) -> list[FilaRol]:
        valores, formulas = self._leer_bloque_roles()
        desde = self.cfg["fila_desde"]
        filas, area = [], ""
        for i, fila in enumerate(valores):
            fila = list(fila) + [None] * (3 - len(fila))
            a, b, c = fila[:3]
            if a not in (None, ""):
                area = str(a).strip()
            if b in (None, "") or not str(b).strip():
                continue
            formula = formulas[i] if i < len(formulas) else None
            filas.append(FilaRol(fila=desde + i, area=area, rol=str(b).strip(), valor_actual=_numero(c),
                                 es_formula=isinstance(formula, str) and formula.startswith("=")))
        return filas

    def leer_aprobaciones(self) -> set[str]:
        datos = self._leer_trazabilidad()
        if not datos:
            return set()
        encabezado = [str(x).strip() for x in datos[0]]
        if "Aprobar" not in encabezado or "Clave" not in encabezado:
            return set()
        i_ap, i_cl = encabezado.index("Aprobar"), encabezado.index("Clave")
        aprobadas = set()
        for fila in datos[1:]:
            fila = list(fila) + [None] * (len(encabezado) - len(fila))
            marcado = fila[i_ap] is True or str(fila[i_ap]).strip().lower() in VERDADEROS
            if marcado and fila[i_cl]:
                aprobadas.add(str(fila[i_cl]))
        return aprobadas

    # --- escritura -----------------------------------------------------------------------------
    @abstractmethod
    def escribir_costos(self, cambios: list[tuple[int, float, str | None]]) -> None:
        """cambios: (fila, costo_diario, nota_de_auditoria) sobre la columna de costo diario."""

    @abstractmethod
    def escribir_texto(self, celda: str, texto: str) -> None:
        ...

    @abstractmethod
    def escribir_trazabilidad(self, encabezados: list[str], filas: list[list]) -> None:
        ...

    def guardar(self) -> None:
        """Los backends que escriben en lote (xlsx) guardan acá. Google escribe en el momento."""
