"""Registro de extractores y ejecución tolerante a fallos.

Cada extractor recibe (fuente, url, cliente, contexto) y devuelve un ResultadoFuente.
`ejecutar_fuente` agrega: descubrimiento de URL, reintento con la URL de respaldo y captura de
cualquier excepción, para que una fuente rota no frene al resto.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from typing import Callable

from ..descubrimiento import descubrir
from ..modelos import ResultadoFuente
from . import coderhouse_html, cpci_html, sica_pdf, sup_pdf_ocr, tarifario_js

log = logging.getLogger(__name__)

ZONA_AR = timezone(timedelta(hours=-3))

REGISTRO: dict[str, Callable] = {
    "sica_pdf": sica_pdf.extraer,
    "sup_pdf_ocr": sup_pdf_ocr.extraer,
    "cpci_html": cpci_html.extraer,
    "coderhouse_html": coderhouse_html.extraer,
    "tarifario_js": tarifario_js.extraer,
}


@dataclass
class Contexto:
    hoy: date
    ahora: datetime

    @classmethod
    def actual(cls) -> "Contexto":
        ahora = datetime.now(ZONA_AR).replace(microsecond=0)
        return cls(hoy=ahora.date(), ahora=ahora)


def _resultado_vacio(fuente: dict, url: str, ctx: Contexto) -> ResultadoFuente:
    return ResultadoFuente(fuente_id=fuente["id"], entidad=fuente["entidad"], nombre=fuente["nombre"],
                           url_usada=url, fecha_extraccion=ctx.ahora, tipo=fuente.get("tipo", ""))


def ejecutar_fuente(fuente: dict, cliente, ctx: Contexto) -> ResultadoFuente:
    extractor = REGISTRO[fuente["extractor"]]
    url_config = fuente["url"]
    url_descubierta, aviso = descubrir(fuente, cliente)
    avisos = [aviso] if aviso else []
    candidatas = []
    if url_descubierta and url_descubierta != url_config:
        avisos.append(f"Se encontró una URL más nueva en la página índice: {url_descubierta}")
        candidatas.append(url_descubierta)
    candidatas.append(url_config)

    ultimo: ResultadoFuente | None = None
    for url in candidatas:
        try:
            res = extractor(fuente, url, cliente, ctx)
        except Exception as exc:  # noqa: BLE001 - se registra y se sigue con la próxima URL/fuente
            log.warning("Fuente %s: falló la extracción desde %s (%s: %s)", fuente["id"], url,
                        exc.__class__.__name__, exc)
            res = _resultado_vacio(fuente, url, ctx)
            res.error = f"{exc.__class__.__name__}: {exc}"
        res.advertencias = avisos + res.advertencias
        if res.ok:
            return res
        ultimo = res
        avisos.append(f"Falló {url}: {res.error}")
    assert ultimo is not None
    return ultimo


def ejecutar_todas(fuentes: list[dict], cliente, ctx: Contexto, solo: set[str] | None = None) -> list[ResultadoFuente]:
    resultados = []
    for fuente in fuentes:
        if solo and fuente["id"] not in solo:
            continue
        if not fuente.get("habilitada", True):
            log.info("Fuente %s deshabilitada en sources.json: se omite", fuente["id"])
            continue
        log.info("Extrayendo %s", fuente["id"])
        res = ejecutar_fuente(fuente, cliente, ctx)
        if res.ok:
            log.info("  %s: %d registros, vigencia %s", fuente["id"], len(res.registros), res.periodo or "?")
        else:
            log.error("  %s: SIN DATOS (%s)", fuente["id"], res.error)
        for adv in res.advertencias:
            log.warning("  %s: %s", fuente["id"], adv)
        resultados.append(res)
    return resultados
