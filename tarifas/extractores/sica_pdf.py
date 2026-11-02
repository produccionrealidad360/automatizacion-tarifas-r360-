"""SICA-APMA: PDFs de salarios mínimos (Animación 2D, 3D y similares).

Formato de cada renglón de texto:
    [ÁREA EN MAYÚSCULAS] Cargo $ mensual $ semanal $ diario
El área solo aparece en el primer cargo de cada grupo; los siguientes la heredan.
Se valida que la relación diario/mensual sea la misma en todas las filas (detecta lecturas corridas).
"""
from __future__ import annotations

import io
import re
import statistics
from datetime import datetime

import pdfplumber

from ..modelos import Registro, ResultadoFuente
from ..normalizar import monto

FILA = re.compile(r"^(?P<texto>.+?)\s+\$\s*(?P<mensual>[\d.]+)\s+\$\s*(?P<semanal>[\d.]+)\s+\$\s*(?P<diario>[\d.]+)\s*$")
MINIMO_FILAS = 8


def _separar_area(texto: str) -> tuple[str | None, str]:
    """'ANIMACIÓN 2D Arte Conceptual' -> ('ANIMACIÓN 2D', 'Arte Conceptual')."""
    tokens = texto.split()
    area = []
    for tok in tokens:
        if tok.isupper() or re.fullmatch(r"\d+D?", tok):
            area.append(tok)
        else:
            break
    if not area or len(area) == len(tokens):
        return None, texto.strip()
    return " ".join(area), " ".join(tokens[len(area):])


def parsear_texto(texto: str, patron_vigencia: str | None) -> tuple[list[Registro], dict, list[str]]:
    registros: list[Registro] = []
    avisos: list[str] = []
    meta: dict = {}
    if patron_vigencia:
        m = re.search(patron_vigencia, texto, re.I)
        if m:
            meta["desde"] = datetime.strptime(m.group(1), "%d/%m/%Y").date()
            meta["hasta"] = datetime.strptime(m.group(2), "%d/%m/%Y").date()
    titulo = re.search(r"SALARIOS?\s+M[IÍ]NIMOS?\s+[^\n]+", texto, re.I)
    if titulo:
        meta["titulo"] = titulo.group(0).strip()
    area_actual = ""
    for linea in texto.splitlines():
        m = FILA.match(linea.strip())
        if not m:
            continue
        area, cargo = _separar_area(m.group("texto"))
        if area:
            area_actual = area
        valores = {u: monto(m.group(u)) for u in ("mensual", "semanal", "diario")}
        if any(v is None for v in valores.values()):
            avisos.append(f"Fila con montos ilegibles: {linea.strip()[:60]}")
            continue
        registros.append(Registro(area=area_actual, categoria=cargo, valores=valores))
    # Control de consistencia: diario/mensual debería ser casi constante
    if len(registros) >= 3:
        ratios = [r.valores["diario"] / r.valores["mensual"] for r in registros if r.valores["mensual"]]
        mediana = statistics.median(ratios)
        buenos = []
        for r in registros:
            ratio = r.valores["diario"] / r.valores["mensual"]
            if abs(ratio / mediana - 1) > 0.02:
                avisos.append(f"'{r.categoria}': la relación diario/mensual no coincide con el resto; se descarta")
            else:
                buenos.append(r)
        registros = buenos
    return registros, meta, avisos


def extraer(fuente: dict, url: str, cliente, ctx) -> ResultadoFuente:
    res = ResultadoFuente(fuente_id=fuente["id"], entidad=fuente["entidad"], nombre=fuente["nombre"],
                          url_usada=url, fecha_extraccion=ctx.ahora, tipo=fuente.get("tipo", ""))
    contenido = cliente.bytes(url)
    if not contenido.startswith(b"%PDF"):
        res.error = "La URL no devolvió un PDF (¿cambió la ruta o el sitio?)"
        return res
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        texto = "\n".join((p.extract_text() or "") for p in pdf.pages)
    if not texto.strip():
        res.error = "El PDF no tiene texto (¿pasó a ser escaneado?). Hay que cambiar el extractor a OCR."
        return res
    registros, meta, avisos = parsear_texto(texto, fuente.get("patron_vigencia"))
    res.advertencias.extend(avisos)
    res.registros = registros
    res.vigencia_desde, res.vigencia_hasta = meta.get("desde"), meta.get("hasta")
    if res.vigencia_desde:
        res.periodo = f"{res.vigencia_desde:%d/%m/%Y} a {res.vigencia_hasta:%d/%m/%Y}"
    else:
        res.advertencias.append("No se encontró el texto de vigencia en el PDF")
    if len(registros) < MINIMO_FILAS:
        res.error = f"Solo se leyeron {len(registros)} cargos (mínimo {MINIMO_FILAS}): el formato del PDF cambió"
        return res
    if res.vigencia_hasta and res.vigencia_hasta < ctx.hoy:
        res.advertencias.append(f"La escala venció el {res.vigencia_hasta:%d/%m/%Y}: el sindicato todavía no publicó la nueva")
    res.ok = True
    return res
