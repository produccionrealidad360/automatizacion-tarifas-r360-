"""Descubre la URL vigente de una fuente.

Los sindicatos publican un PDF nuevo por período (p. ej. "Salarios Animación 2D Octubre 2026.pdf").
Dos métodos, en este orden:
  1. Página índice: buscar el enlace cuyo texto coincide con un patrón (o un iframe).
  2. Patrón de nombre: probar la URL armada con el mes y el año (desde el mes próximo hacia atrás).
     Sirve cuando la página índice bloquea a los servidores de GitHub (pasa con sicacine.org.ar).
Si nada funciona, se usa la URL fija de la configuración.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre",
         "Noviembre", "Diciembre"]


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


def _sumar_meses(d: date, n: int) -> date:
    total = d.year * 12 + (d.month - 1) + n
    return date(total // 12, total % 12 + 1, 1)


def candidatas_por_patron(patron: str, hoy: date, adelante: int = 1, atras: int = 3) -> list[str]:
    """URLs posibles, de la más nueva a la más vieja. El patrón usa {mes} y {anio}."""
    urls = []
    for n in range(adelante, -atras - 1, -1):
        d = _sumar_meses(hoy, n)
        urls.append(patron.format(mes=MESES[d.month - 1], anio=d.year))
    return urls


def _es_pdf_publicado(cliente, url: str) -> bool:
    try:
        resp = cliente.sesion.get(url, timeout=cliente.timeout, stream=True)
        try:
            return resp.status_code == 200 and resp.raw.read(5) == b"%PDF-"
        finally:
            resp.close()
    except requests.RequestException:
        return False


def _motivo(exc: Exception) -> str:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return f"HTTP {exc.response.status_code}"
    return exc.__class__.__name__


def descubrir(fuente: dict, cliente, hoy: date | None = None) -> tuple[str | None, str | None]:
    """Devuelve (url_descubierta, aviso). Nunca lanza."""
    conf = fuente.get("descubrimiento")
    if not conf:
        return None, None
    avisos = []
    pagina = conf.get("pagina")
    if pagina:
        try:
            html = cliente.texto(pagina)
            if conf.get("texto_enlace"):
                url = enlace_por_texto(html, pagina, conf["texto_enlace"])
            elif conf.get("iframe_contiene"):
                url = iframe_que_contiene(html, pagina, conf["iframe_contiene"])
            else:
                url = None
            if url:
                return url, None
            avisos.append(f"La página índice ya no tiene un enlace que coincida con el patrón ({pagina})")
        except Exception as exc:  # noqa: BLE001 - el descubrimiento es opcional
            avisos.append(f"No se pudo leer la página índice {pagina} ({_motivo(exc)})")
    if conf.get("patron_url"):
        for url in candidatas_por_patron(conf["patron_url"], hoy or date.today(),
                                         conf.get("meses_adelante", 1), conf.get("meses_atras", 3)):
            if _es_pdf_publicado(cliente, url):
                return url, None
        avisos.append("Tampoco se encontró un PDF probando el patrón de nombre por mes")
    return None, "; ".join(avisos) or None
