"""Normalización de nombres y montos para comparar textos de distintas fuentes (PDF, OCR, HTML)."""
from __future__ import annotations

import re
import unicodedata


def sin_acentos(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c))


def clave(texto: str | None) -> str:
    """Clave de comparación: minúsculas, sin acentos, sin espacios ni signos.

    El OCR a veces pega las palabras ("DIRECTORCREATIVO"), así que se descartan los espacios.
    """
    return re.sub(r"[^a-z0-9]", "", sin_acentos(str(texto or "")).lower())


def monto(texto: str) -> float | None:
    """Convierte montos con separadores argentinos o ingleses: "$ 3.727.974", "1,235,138.98", "2.324.329,63"."""
    if texto is None:
        return None
    s = re.sub(r"[^\d.,]", "", str(texto))
    if not s or not re.search(r"\d", s):
        return None
    # Solo separadores de miles (1.200 / 3.727.974 / 1,200)
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):
        return float(re.sub(r"[.,]", "", s))
    # Último separador seguido de 1 o 2 dígitos = decimales
    m = re.fullmatch(r"(\d{1,3}(?:[.,]?\d{3})*)[.,](\d{1,2})", s)
    if m:
        return float(re.sub(r"[.,]", "", m.group(1)) + "." + m.group(2))
    if re.fullmatch(r"\d+", s):
        return float(s)
    return None


def formato_ars(valor: float | None, decimales: int = 2) -> str:
    if valor is None:
        return ""
    texto = f"{valor:,.{decimales}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")
