"""SUP: escala de Agencias de Publicidad (PDF escaneado, se lee con OCR).

La tabla tiene una columna por tramo del acuerdo (p. ej. DIC-2025 +4%, FEB-2026 +8%, JUL-2026 +8%,
NOV-2026 +4%). Como cada tramo es el anterior más un porcentaje publicado, cada fila se valida
recalculando esa cadena: si el OCR leyó mal un dígito, la cuenta no cierra y la fila se descarta.
Se usa el tramo vigente a la fecha de ejecución.
"""
from __future__ import annotations

import calendar
import io
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta

import pdfplumber

from ..modelos import Registro, ResultadoFuente
from ..normalizar import clave, monto

log = logging.getLogger(__name__)

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
         "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}
# Un monto: miles con separador y 2 decimales. Se buscan DENTRO de cada caja porque, según la versión
# del motor de OCR, varias celdas pueden venir pegadas en una sola caja ("$1,303,128.64$1,407,378.93").
MONTO_EN_TEXTO = re.compile(r"[S$]?\d{1,3}(?:[.,]\d{3})+[.,]\d{2}(?!\d)")
MINIMO_FILAS_VALIDAS = 30
_MOTOR = None


@dataclass
class Caja:
    x: float
    y: float
    texto: str


def _motor_ocr():
    global _MOTOR
    if _MOTOR is None:
        from rapidocr_onnxruntime import RapidOCR  # import diferido: es pesado

        _MOTOR = RapidOCR()
    return _MOTOR


def ocr_pagina(imagen) -> list[Caja]:
    import numpy as np

    resultado, _ = _motor_ocr()(np.array(imagen.convert("RGB")))
    return [Caja(x=b[0][0][0], y=b[0][0][1], texto=str(b[1]).strip()) for b in (resultado or [])]


def agrupar_renglones(cajas: list[Caja], tolerancia: float = 12) -> list[list[Caja]]:
    renglones: list[list[Caja]] = []
    actual: list[Caja] = []
    y_ref = None
    for c in sorted(cajas, key=lambda c: (c.y, c.x)):
        if y_ref is None or abs(c.y - y_ref) < tolerancia:
            actual.append(c)
            y_ref = c.y if y_ref is None else (y_ref + c.y) / 2
        else:
            renglones.append(sorted(actual, key=lambda c: c.x))
            actual, y_ref = [c], c.y
    if actual:
        renglones.append(sorted(actual, key=lambda c: c.x))
    return renglones


def detectar_tramos(cajas: list[Caja]) -> list[dict]:
    """Lee el encabezado: meses, años y porcentajes, cada uno ordenado de izquierda a derecha."""
    meses = sorted((c for c in cajas if clave(c.texto) in MESES), key=lambda c: c.x)
    anios = sorted((c for c in cajas if re.fullmatch(r"20\d{2}", c.texto)), key=lambda c: c.x)
    pcts = sorted((c for c in cajas if re.fullmatch(r"\d{1,2}\s*%", c.texto)), key=lambda c: c.x)
    if not meses or not (len(meses) == len(anios) == len(pcts)):
        return []
    return [{"desde": date(int(a.texto), MESES[clave(m.texto)], 1), "porcentaje": float(p.texto.rstrip("% "))}
            for m, a, p in zip(meses, anios, pcts)]


def parsear_renglones(renglones: list[list[Caja]], tramos: list[dict], tolerancia: float):
    """Devuelve (filas_validas, filas_invalidas). Cada fila: (seccion, etiqueta, valores)."""
    validas, invalidas = [], []
    seccion = ""
    for renglon in renglones:
        valores, partes = [], []
        for c in renglon:
            compacto = c.texto.replace(" ", "")
            valores += [monto(m) for m in MONTO_EN_TEXTO.findall(compacto)]
            resto = MONTO_EN_TEXTO.sub(" ", compacto).strip(" |")
            if resto:
                partes.append(c.texto if resto == compacto else resto)
        etiqueta = " ".join(partes).strip()
        if not valores:
            if clave(etiqueta).startswith("area"):
                seccion = etiqueta
            continue
        fila = (seccion, etiqueta, valores)
        if len(valores) != len(tramos) or not cadena_valida(valores, tramos, tolerancia):
            invalidas.append(fila)
        else:
            validas.append(fila)
    return validas, invalidas


def cadena_valida(valores: list[float], tramos: list[dict], tolerancia: float) -> bool:
    for i in range(1, len(valores)):
        esperado = valores[i - 1] * (1 + tramos[i]["porcentaje"] / 100)
        if abs(valores[i] - esperado) > tolerancia:
            return False
    return True


def tramo_vigente(tramos: list[dict], hoy: date) -> int:
    vigentes = [i for i, t in enumerate(tramos) if t["desde"] <= hoy]
    return vigentes[-1] if vigentes else 0


def extraer(fuente: dict, url: str, cliente, ctx) -> ResultadoFuente:
    opciones = fuente.get("opciones", {})
    res = ResultadoFuente(fuente_id=fuente["id"], entidad=fuente["entidad"], nombre=fuente["nombre"],
                          url_usada=url, fecha_extraccion=ctx.ahora, tipo=fuente.get("tipo", ""))
    contenido = cliente.bytes(url)
    if not contenido.startswith(b"%PDF"):
        res.error = "La URL no devolvió un PDF (¿cambió la ruta?)"
        return res

    cajas_por_pagina: list[list[Caja]] = []
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        for pagina in pdf.pages:
            imagen = pagina.to_image(resolution=opciones.get("resolucion_ocr", 220)).original
            cajas_por_pagina.append(ocr_pagina(imagen))

    tramos = detectar_tramos(cajas_por_pagina[0]) if cajas_por_pagina else []
    if not tramos:
        respaldo = opciones.get("tramos_respaldo") or []
        tramos = [{"desde": date.fromisoformat(t["desde"]), "porcentaje": float(t["porcentaje"])} for t in respaldo]
        res.advertencias.append("No se pudo leer el encabezado de tramos; se usan los tramos de respaldo de sources.json")
    if not tramos:
        res.error = "No hay tramos (ni leídos ni de respaldo)"
        return res

    tolerancia = float(opciones.get("tolerancia_tramo_pesos", 2.0))
    validas, invalidas = [], []
    for cajas in cajas_por_pagina:
        v, inv = parsear_renglones(agrupar_renglones(cajas), tramos, tolerancia)
        validas += v
        invalidas += inv
    for seccion, etiqueta, valores in invalidas:
        res.advertencias.append(f"Fila descartada (la cadena de aumentos no cierra o falta un monto): {etiqueta[:50]}")

    i = tramo_vigente(tramos, ctx.hoy)
    for seccion, etiqueta, valores in validas:
        res.registros.append(Registro(
            area=seccion, categoria=etiqueta, valores={"mensual": valores[i]},
            extra={"tramos": {t["desde"].isoformat(): v for t, v in zip(tramos, valores)}},
        ))
    tramo = tramos[i]
    ultimo = tramos[-1]["desde"]
    fin_acuerdo = date(ultimo.year, ultimo.month, calendar.monthrange(ultimo.year, ultimo.month)[1])
    res.vigencia_desde = tramo["desde"]
    res.vigencia_hasta = (tramos[i + 1]["desde"] - timedelta(days=1)) if i + 1 < len(tramos) else fin_acuerdo
    res.periodo = (f"Tramo desde {tramo['desde']:%d/%m/%Y} (+{tramo['porcentaje']:g}%) · acuerdo "
                   f"{tramos[0]['desde']:%m/%Y} a {fin_acuerdo:%m/%Y}")
    if ctx.hoy > fin_acuerdo:
        res.advertencias.append(f"El acuerdo terminó el {fin_acuerdo:%d/%m/%Y}: hay que cargar la URL del acuerdo nuevo")
    if len(validas) < MINIMO_FILAS_VALIDAS:
        res.error = f"Solo {len(validas)} filas pasaron la validación (mínimo {MINIMO_FILAS_VALIDAS})"
        return res
    res.ok = True
    return res
