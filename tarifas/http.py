"""Cliente HTTP con reintentos y timeouts. Todas las fuentes se descargan por acá."""
from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)
RAIZ = Path(__file__).resolve().parent.parent

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36 automatizacion-tarifas-r360"
)


class ClienteHttp:
    def __init__(self, timeout: float = 60, reintentos: int = 3):
        self.timeout = timeout
        self.sesion = requests.Session()
        self.sesion.headers["User-Agent"] = USER_AGENT
        retry = Retry(total=reintentos, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=("GET",))
        adaptador = HTTPAdapter(max_retries=retry)
        self.sesion.mount("https://", adaptador)
        self.sesion.mount("http://", adaptador)
        self._bundles: dict[str, str] = {}

    def _bundle_con(self, ca_adicional: str) -> str:
        """Bundle de certifi + un certificado intermedio que el servidor no envía.

        Se usa para sitios mal configurados (p. ej. www.ceni.com.ar no manda el intermedio de GoDaddy).
        La verificación TLS sigue activa: solo se agrega a la lista de confianza ese intermedio público.
        """
        if ca_adicional not in self._bundles:
            import certifi

            ruta_extra = Path(ca_adicional)
            if not ruta_extra.is_absolute():
                ruta_extra = RAIZ / ruta_extra
            destino = Path(tempfile.gettempdir()) / f"tarifas-ca-{ruta_extra.stem}.pem"
            destino.write_text(Path(certifi.where()).read_text(encoding="utf-8") + "\n"
                               + ruta_extra.read_text(encoding="utf-8"), encoding="utf-8")
            self._bundles[ca_adicional] = str(destino)
        return self._bundles[ca_adicional]

    def get(self, url: str, referer: str | None = None, ca_adicional: str | None = None) -> requests.Response:
        headers = {"Referer": referer} if referer else None
        verify = self._bundle_con(ca_adicional) if ca_adicional else True
        resp = self.sesion.get(url, timeout=self.timeout, headers=headers, verify=verify)
        resp.raise_for_status()
        return resp

    def bytes(self, url: str, referer: str | None = None, ca_adicional: str | None = None) -> bytes:
        return self.get(url, referer, ca_adicional).content

    def texto(self, url: str, referer: str | None = None, ca_adicional: str | None = None) -> str:
        """Devuelve el HTML decodificado. Algunas páginas dicen UTF-8 pero mandan Windows-1252."""
        return decodificar(self.get(url, referer, ca_adicional).content)


def decodificar(contenido: bytes) -> str:
    """UTF-8 si el contenido es (casi) todo UTF-8 válido; si no, Windows-1252.

    Una página UTF-8 con un solo byte suelto no debe pasar a Windows-1252: eso rompe todos los acentos
    y guiones ("–" -> "â€“") y los patrones de extracción dejan de coincidir.
    """
    try:
        return contenido.decode("utf-8")
    except UnicodeDecodeError:
        como_cp1252 = contenido.decode("cp1252", errors="replace")
        # Si el contenido en realidad es UTF-8, leerlo como Windows-1252 deja secuencias típicas
        # ("Ã³", "â€“"). Si no aparecen, es un documento Windows-1252 genuino.
        if re.search(r"Ã[\x80-\xbf¡-ÿ]|â€", como_cp1252):
            return contenido.decode("utf-8", errors="replace")
        return como_cp1252
