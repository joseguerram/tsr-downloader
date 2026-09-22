"""Análisis y validación de URL de The Sims Resource."""

from __future__ import annotations

import logging
import re

import requests

logger = logging.getLogger(__name__)

DETAILS_URL = "https://www.thesimsresource.com/downloads/details/id/"

# Patrón genérico: acepta cualquier URL de TSR que contenga el ID del item,
# sin importar los prefijos (categorías, autor, versiones...):
#   /downloads/download/itemId/123            -> descarga directa
#   /members/<autor>/downloads/details/.../id/123  -> detalle con prefijo arbitrario
#   /downloads/details/.../id/123             -> detalle clásico
#   /downloads/123 o /downloads/123?ref=...   -> URL corta
_PATTERN = re.compile(
    r"www\.thesimsresource\.com"
    r"(?:"
    r"/downloads/download/itemId/(\d+)"  # group(1): descarga directa
    r"|.*?/id/(\d+)"  # group(2): detalle con cualquier prefijo
    r"|/downloads/(\d+)(?:[/?#]|$)"  # group(3): url corta
    r")",
    re.IGNORECASE,
)


def extract_item_id(text: str) -> int | None:
    """Extrae el ID de un item de una URL de The Sims Resource."""
    logger.debug(f"[url_parser] extract_item_id input: {text!r}")
    match = _PATTERN.search(text)
    if not match:
        logger.debug("[url_parser] no pattern matched")
        return None
    item_id = int(next(g for g in match.groups() if g is not None))
    logger.debug(f"[url_parser] matched -> item_id={item_id}")
    return item_id


def get_details_url(item_id: int) -> str:
    return f"{DETAILS_URL}{item_id}"


# Las dependencias se marcan con esta clase en el HTML de detalle; verificado
# en vivo que aparece igual en la URL de detalle y en la de descarga corta.
REQUIRED_PATTERN = re.compile(r'(?<=<li class="required-download-item"><a href=")/downloads/(\d+)')


def fetch_details(item_id: int, http: requests.Session) -> tuple[bool, list[int]]:
    """Una sola petición al detalle: devuelve (es_vip, dependencias).

    La URL de detalle contiene tanto el marcador «VIP Exclusive» como la lista
    de ``required-download-item``, así que no hace falta una petición extra
    por comprobación. Propaga el error si TSR no responde bien.
    """
    url = get_details_url(item_id)
    logger.debug(f"[url_parser] fetch_details: GET {url}")
    r = http.get(url, timeout=5)
    logger.debug(f"[url_parser] fetch_details: status={r.status_code}, length={len(r.text)}")
    r.raise_for_status()
    is_vip = "VIP Exclusive" in r.text
    required = [int(m) for m in REQUIRED_PATTERN.findall(r.text)]
    logger.debug(f"[url_parser] fetch_details({item_id}) = vip={is_vip}, required={required}")
    return is_vip, required
