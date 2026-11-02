"""Tarifario.ar: la página es una app de JavaScript (Next.js) y los precios vienen dentro de los
archivos .js. Se buscan en cada ejecución los .js que carga la página (sus nombres cambian con cada
versión del sitio) y se leen los objetos {category:"servicios-3d", title:..., priceUSD:..., priceType:...}.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..modelos import Registro, ResultadoFuente


def scripts_de_la_pagina(html: str, url_base: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    urls = [urljoin(url_base, s["src"]) for s in soup.find_all("script", src=True)]
    urls += [urljoin(url_base, l["href"]) for l in soup.find_all("link", href=True) if l["href"].endswith(".js")]
    return [u for u in dict.fromkeys(urls) if "/_next/" in u or u.endswith(".js")]


def parsear_js(js: str, categoria: str) -> list[Registro]:
    registros = []
    patron_obj = re.compile(r"\{[^{}]*?category:\"" + re.escape(categoria) + r"\"[^{}]*\}")
    for obj in patron_obj.finditer(js):
        texto = obj.group(0)
        titulo = re.search(r'title:"((?:[^"\\]|\\.)*)"', texto)
        precio = re.search(r"priceUSD:([\d.]+)", texto)
        tipo = re.search(r'priceType:"([^"]+)"', texto)
        if not (titulo and precio):
            continue
        registros.append(Registro(
            area="Servicios 3D", categoria=titulo.group(1).encode().decode("unicode_escape", errors="ignore")
            if "\\u" in titulo.group(1) else titulo.group(1),
            valores={"precio_usd": float(precio.group(1))}, moneda="USD",
            extra={"tipo_precio": tipo.group(1) if tipo else ""},
        ))
    return registros


def extraer(fuente: dict, url: str, cliente, ctx) -> ResultadoFuente:
    res = ResultadoFuente(fuente_id=fuente["id"], entidad=fuente["entidad"], nombre=fuente["nombre"],
                          url_usada=url, fecha_extraccion=ctx.ahora, tipo=fuente.get("tipo", ""))
    categoria = fuente.get("opciones", {}).get("categoria", "servicios-3d")
    html = cliente.texto(url)
    titulo = BeautifulSoup(html, "lxml").title
    anio = re.search(r"\b(20\d{2})\b", titulo.get_text() if titulo else "")
    res.periodo = f"Tarifario {anio.group(1)}" if anio else ""
    vistos = set()
    for js_url in scripts_de_la_pagina(html, url):
        try:
            js = cliente.texto(js_url)
        except Exception as exc:  # noqa: BLE001 - un .js caído no invalida los demás
            res.advertencias.append(f"No se pudo leer {js_url.rsplit('/', 1)[-1]}: {exc.__class__.__name__}")
            continue
        for reg in parsear_js(js, categoria):
            if reg.categoria not in vistos:
                vistos.add(reg.categoria)
                res.registros.append(reg)
    if not res.registros:
        res.error = f"No se encontraron precios de '{categoria}' en los scripts del sitio (cambió la web)"
        return res
    res.ok = True
    return res
