"""Coderhouse: notas de sueldos (texto corrido). Referencia de mercado en USD, no escala sindical.

Los patrones por nivel están en sources.json (opciones.niveles). Si un patrón captura dos números
se toma el rango y su punto medio; si captura uno, se usa ese valor (mediana publicada).
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..modelos import Registro, ResultadoFuente
from ..normalizar import monto


def texto_plano(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")
    titulo = soup.title.get_text(strip=True) if soup.title else ""
    for t in soup(["script", "style", "noscript", "svg"]):
        t.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)), titulo


def parsear(texto: str, niveles: dict[str, str]) -> tuple[list[Registro], list[str]]:
    registros, faltantes = [], []
    for nivel, patron in niveles.items():
        m = re.search(patron, texto, re.I)
        if not m:
            faltantes.append(nivel)
            continue
        numeros = [monto(g) for g in m.groups() if g]
        numeros = [n for n in numeros if n]
        if not numeros:
            faltantes.append(nivel)
            continue
        extra = {"texto": m.group(0)[:160]}
        if len(numeros) >= 2:
            extra.update(minimo=numeros[0], maximo=numeros[1])
            valor = (numeros[0] + numeros[1]) / 2
        else:
            valor = numeros[0]
        registros.append(Registro(area="AI Automation", categoria=nivel, valores={"mensual_usd": valor},
                                  moneda="USD", extra=extra))
    return registros, faltantes


def extraer(fuente: dict, url: str, cliente, ctx) -> ResultadoFuente:
    res = ResultadoFuente(fuente_id=fuente["id"], entidad=fuente["entidad"], nombre=fuente["nombre"],
                          url_usada=url, fecha_extraccion=ctx.ahora, tipo=fuente.get("tipo", ""))
    texto, titulo = texto_plano(cliente.texto(url))
    opciones = fuente.get("opciones", {})
    registros, faltantes = parsear(texto, opciones.get("niveles", {}))
    res.registros = registros
    publicado = re.search(r"Publicado el\s+(\d{1,2} de [a-záéíóú]+ de \d{4})", texto, re.I)
    anio = re.search(r"\b(20\d{2})\b", titulo)
    res.periodo = (f"Publicado el {publicado.group(1)}" if publicado else (f"Año {anio.group(1)}" if anio else ""))
    if opciones.get("contexto"):
        res.advertencias.append(f"Contexto de la fuente: {opciones['contexto']}")
    if faltantes:
        res.advertencias.append(f"No se encontraron los niveles: {', '.join(faltantes)} (¿cambió el texto de la nota?)")
    if not registros:
        res.error = "No se encontró ningún rango salarial con los patrones configurados"
        return res
    res.ok = True
    return res
