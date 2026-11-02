"""Estructuras de datos compartidas por extractores, conciliación y publicación."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass
class Registro:
    """Una categoría/rol tal como figura en la fuente."""

    area: str  # agrupamiento de la fuente (p. ej. "ANIMACIÓN 2D", "AREA CREATIVA")
    categoria: str  # nombre del cargo en la fuente
    valores: dict[str, float]  # unidad -> monto. Unidades: diario, semanal, mensual, hora, mensual_usd, precio_usd
    moneda: str = "ARS"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResultadoFuente:
    """Resultado de extraer una fuente. Nunca lanza: los errores quedan en `error` y `advertencias`."""

    fuente_id: str
    entidad: str
    nombre: str
    url_usada: str
    fecha_extraccion: datetime
    ok: bool = False
    periodo: str = ""  # texto legible del período de vigencia
    vigencia_desde: date | None = None
    vigencia_hasta: date | None = None
    registros: list[Registro] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)
    error: str | None = None
    tipo: str = "escala_sindical"

    def buscar(self, categoria_norm: str, area_norm: str | None = None) -> Registro | None:
        from .normalizar import clave

        candidatos = [r for r in self.registros if clave(r.categoria) == categoria_norm]
        if area_norm:
            candidatos = [r for r in candidatos if clave(r.area) == area_norm] or []
        return candidatos[0] if candidatos else None


@dataclass
class FilaRol:
    """Un rol de la planilla (pestaña COSTOS X HORAS FACTURABLES)."""

    fila: int
    area: str
    rol: str
    valor_actual: float | None  # costo diario vigente (columna C)
    es_formula: bool = False


@dataclass
class Propuesta:
    """Decisión sobre un rol: qué valor corresponde, de dónde sale y qué se hace."""

    fila: int | None
    area_plantilla: str
    rol: str
    valor_actual: float | None
    valor_nuevo: float | None
    estado: str  # aplicar | sin_cambios | revision | rechazado | fuente_con_error | sin_fuente | no_encontrado
    motivo: str = ""
    fuente_id: str = ""
    entidad: str = ""
    documento: str = ""
    url: str = ""
    periodo: str = ""
    fecha_extraccion: datetime | None = None
    area_fuente: str = ""
    categoria_fuente: str = ""
    unidad: str = ""
    valor_fuente: float | None = None
    moneda: str = "ARS"
    detalle_calculo: str = ""
    hora_facturable: float | None = None
    modo: str = "auto"

    @property
    def variacion(self) -> float | None:
        if self.valor_actual in (None, 0) or self.valor_nuevo is None:
            return None
        return self.valor_nuevo / self.valor_actual - 1

    def clave_aprobacion(self) -> str:
        """Identifica una propuesta para poder aprobarla desde la planilla en la ejecución siguiente."""
        nuevo = "" if self.valor_nuevo is None else f"{self.valor_nuevo:.2f}"
        return f"{self.area_plantilla}|{self.rol}|{nuevo}|{self.periodo}"
