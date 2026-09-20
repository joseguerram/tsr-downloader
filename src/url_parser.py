import re
import logging
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
    r"/downloads/download/itemId/(\d+)"     # group(1): descarga directa
    r"|.*?/id/(\d+)"                        # group(2): detalle con cualquier prefijo
    r"|/downloads/(\d+)(?:[/?#]|$)"         # group(3): url corta
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


def is_vip_exclusive(item_id: int) -> bool:
    url = get_details_url(item_id)
    logger.debug(f"[url_parser] is_vip_exclusive: GET {url}")
    try:
        r = requests.get(url, timeout=10)
        logger.debug(f"[url_parser] is_vip_exclusive: status={r.status_code}, length={len(r.text)}")
        result = "VIP Exclusive" in r.text
        logger.debug(f"[url_parser] is_vip_exclusive({item_id}) = {result}")
        return result
    except requests.RequestException as e:
        logger.debug(f"[url_parser] is_vip_exclusive({item_id}) failed: {e}")
        return False


def get_required_items(item_id: int) -> list[int]:
    url = f"https://www.thesimsresource.com/downloads/{item_id}"
    logger.debug(f"[url_parser] get_required_items: GET {url}")
    try:
        r = requests.get(url, timeout=10)
        logger.debug(f"[url_parser] get_required_items: status={r.status_code}, length={len(r.text)}")
        items = [
            int(m)
            for m in re.findall(
                r'(?<=<li class="required-download-item"><a href=")/downloads/(\d+)',
                r.text,
            )
        ]
        logger.debug(f"[url_parser] get_required_items({item_id}) = {items}")
        return items
    except requests.RequestException as e:
        logger.debug(f"[url_parser] get_required_items({item_id}) failed: {e}")
        return []


if __name__ == "__main__":
    CASES = [
        # URL válidas
        ("https://www.thesimsresource.com/downloads/1782277", 1782277),
        ("https://www.thesimsresource.com/downloads/details/id/1782277/", 1782277),
        ("https://www.thesimsresource.com/downloads/details/category/sims4-lots-residential/title/mm-modern-vintage-4/id/1782277/", 1782277),
        ("https://www.thesimsresource.com/downloads/download/itemId/1782277", 1782277),
        ("https://www.thesimsresource.com/downloads/download/itemId/1782277/ticket/tsr123/", 1782277),
        ("https://www.thesimsresource.com/downloads/1782277/some/extra/path", 1782277),
        # URL con prefijo de miembro (autor) que antes fallaba
        ("https://www.thesimsresource.com/members/McLayneSims/downloads/details/category/sims4-clothing-male-teenadultelder-everyday/title/boi-trash-hoodies/id/1497492/", 1497492),
        ("https://www.thesimsresource.com/members/McLayneSims/downloads/details/id/1497492/", 1497492),
        # URL sin www
        ("https://thesimsresource.com/downloads/1782277", None),
        # URL de otro dominio
        ("https://www.google.com/downloads/1782277", None),
        # Texto sin URL
        ("hola mundo", None),
        # Número suelto en otro contexto del mismo dominio
        ("https://www.thesimsresource.com/shop/12345", None),
        # URL de descarga con query string
        ("https://www.thesimsresource.com/downloads/1782277?ref=favorite", 1782277),
    ]

    failures = 0
    for url, expected in CASES:
        got = extract_item_id(url)
        status = "✓" if got == expected else "✗"
        if got != expected:
            failures += 1
        print(f"{status} {url!r} -> got={got}, expected={expected}")

    print()
    if failures:
        print(f"{failures} caso(s) fallido(s)")
        raise SystemExit(1)
    print("Todos los casos pasaron")