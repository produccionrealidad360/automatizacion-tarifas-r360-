"""Carga y validación de la configuración (config/*.json)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
DIR_CONFIG = RAIZ / "config"

EXTRACTORES_VALIDOS = {"sica_pdf", "sup_pdf_ocr", "cpci_html", "coderhouse_html", "tarifario_js"}
UNIDADES_VALIDAS = {"diario", "semanal", "mensual", "hora"}
MODOS_VALIDOS = {"auto", "revision"}


class ErrorConfiguracion(ValueError):
    pass


@dataclass
class Configuracion:
    fuentes: list[dict[str, Any]]
    mapeo: list[dict[str, Any]]
    calculo: dict[str, Any]
    plantilla: dict[str, Any]

    def fuente(self, fuente_id: str) -> dict[str, Any] | None:
        return next((f for f in self.fuentes if f["id"] == fuente_id), None)


def _leer(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ErrorConfiguracion(f"Falta el archivo de configuración {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ErrorConfiguracion(f"{path.name} no es un JSON válido: {exc}") from exc


def cargar(directorio: Path = DIR_CONFIG) -> Configuracion:
    fuentes = _leer(directorio / "sources.json")["fuentes"]
    mapeo = _leer(directorio / "mapeo_roles.json")["roles"]
    calculo = _leer(directorio / "calculo.json")
    plantilla = _leer(directorio / "plantilla.json")
    cfg = Configuracion(fuentes=fuentes, mapeo=mapeo, calculo=calculo, plantilla=plantilla)
    validar(cfg)
    return cfg


def validar(cfg: Configuracion) -> None:
    errores: list[str] = []
    ids = [f.get("id") for f in cfg.fuentes]
    if len(ids) != len(set(ids)):
        errores.append("sources.json: hay ids de fuente repetidos")
    for f in cfg.fuentes:
        for campo in ("id", "entidad", "nombre", "extractor", "url"):
            if not f.get(campo):
                errores.append(f"sources.json: la fuente {f.get('id', '?')} no tiene '{campo}'")
        if f.get("extractor") not in EXTRACTORES_VALIDOS:
            errores.append(f"sources.json: extractor desconocido '{f.get('extractor')}' en {f.get('id')}")
    for i, m in enumerate(cfg.mapeo, start=1):
        for campo in ("rol", "area", "fuente", "categoria", "unidad"):
            if not m.get(campo):
                errores.append(f"mapeo_roles.json #{i}: falta '{campo}'")
        if m.get("fuente") and m["fuente"] not in ids:
            errores.append(f"mapeo_roles.json #{i} ({m.get('rol')}): la fuente '{m['fuente']}' no existe en sources.json")
        if m.get("unidad") and m["unidad"] not in UNIDADES_VALIDAS:
            errores.append(f"mapeo_roles.json #{i} ({m.get('rol')}): unidad '{m['unidad']}' no válida")
        if m.get("modo", "auto") not in MODOS_VALIDOS:
            errores.append(f"mapeo_roles.json #{i} ({m.get('rol')}): modo '{m.get('modo')}' no válido")
    val = cfg.calculo.get("validacion", {})
    if val.get("variacion_minima", -1) >= val.get("variacion_maxima", 1):
        errores.append("calculo.json: variacion_minima debe ser menor que variacion_maxima")
    if errores:
        raise ErrorConfiguracion("\n".join(errores))
