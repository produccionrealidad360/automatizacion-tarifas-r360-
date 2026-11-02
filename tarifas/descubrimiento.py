"""Descubre la URL vigente de una fuente a partir de su página índice.

Los sindicatos publican un PDF nuevo por período (p. ej. "Salarios Animación 2D Octubre 2026.pdf").
En lugar de editar sources.json cada vez, se busca en la página índice el enlace cuyo texto coincide
con un patrón. Si no se encuentra, se usa la URL fija de la configuración.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)


def enlace_por_texto(html: str, url_base: str, patron: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    regex = re.compile(patron, re.I)
    for a in soup.find_all("a", href=True):
        texto = a.get_text(" ", strip=True)
        if regex.search(texto):
            return urljoin(url_base, a["href"])
    return None


def iframe_que_contiene(html: str, url_base: str, fragmento: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    for iframe in soup.find_all("iframe", src=True):
        if fragmento.lower() in iframe["src"].lower():
            return urljoin(url_base, iframe["src"])
    return None


def descubrir(fuente: dict, cliente) -> tuple[str | None, str | None]:
    """Devuelve (url_descubierta, aviso). Nunca lanza."""
    conf = fuente.get("descubrimiento")
    if not conf:
        return None, None
    pagina = conf.get("pagina")
    try:
        html = cliente.texto(pagina)
    except Exception as exc:  # noqa: BLE001 - el descubrimiento es opcional
        return None, f"No se pudo leer la página índice {pagina}: {exc.__class__.__name__}"
    if conf.get("texto_enlace"):
        url = enlace_por_texto(html, pagina, conf["texto_enlace"])
    elif conf.get("iframe_contiene"):
        url = iframe_que_contiene(html, pagina, conf["iframe_contiene"])
    else:
        url = None
    if not url:
        return None, f"La página índice ya no tiene un enlace que coincida con el patrón configurado ({pagina})"
    return url, None
