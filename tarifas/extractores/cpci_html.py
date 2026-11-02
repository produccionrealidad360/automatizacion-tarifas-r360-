"""CPCI Córdoba: honorarios recomendados (tabla HTML dentro de un iframe).

Columnas: Agrupamiento | Perfil/Rol/Cargo | $ Remuneración mensual | $ Hora a demanda | Unid. actualización.
La fecha sale de "Actualización al: MM-AAAA".
"""
from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup

from ..modelos import Registro, ResultadoFuente
from ..normalizar import monto

MINIMO_FILAS = 10


def parsear_html(html: str) -> tuple[list[Registro], date | None]:
    soup = BeautifulSoup(html, "lxml")
    registros = []
    for tr in soup.find_all("tr"):
        celdas = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(celdas) < 4:
            continue
        agrupamiento, cargo, mensual, hora = celdas[:4]
        valores = {}
        if (v := monto(mensual)) and v > 0:
            valores["mensual"] = v
        if (v := monto(hora)) and v > 0:
            valores["hora"] = v
        if cargo and valores:
            extra = {"actualizacion": celdas[4]} if len(celdas) > 4 else {}
            registros.append(Registro(area=agrupamiento, categoria=cargo, valores=valores, extra=extra))
    m = re.search(r"Actualizaci\S*n al:\s*(\d{2})-(\d{4})", soup.get_text(" "), re.I)
    desde = date(int(m.group(2)), int(m.group(1)), 1) if m else None
    return registros, desde


def extraer(fuente: dict, url: str, cliente, ctx) -> ResultadoFuente:
    res = ResultadoFuente(fuente_id=fuente["id"], entidad=fuente["entidad"], nombre=fuente["nombre"],
                          url_usada=url, fecha_extraccion=ctx.ahora, tipo=fuente.get("tipo", ""))
    html = cliente.texto(url, referer=fuente.get("pagina_publica"), ca_adicional=fuente.get("ca_adicional"))
    registros, desde = parsear_html(html)
    res.registros = registros
    res.vigencia_desde = desde
    if desde:
        res.periodo = f"Actualización {desde:%m/%Y} (ajuste por índice IPIM)"
    else:
        res.advertencias.append("No se encontró la fecha de actualización")
    if len(registros) < MINIMO_FILAS:
        res.error = f"Solo se leyeron {len(registros)} perfiles (mínimo {MINIMO_FILAS}): la tabla cambió de formato"
        return res
    res.ok = True
    return res
