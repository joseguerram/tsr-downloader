"""Tests de src.url_parser: extracción de ID y consulta de detalle."""

import pytest
import requests

from src.url_parser import extract_item_id, fetch_details, get_details_url

CASES = [
    # URLs válidas
    ("https://www.thesimsresource.com/downloads/1782277", 1782277),
    ("https://www.thesimsresource.com/downloads/details/id/1782277/", 1782277),
    (
        "https://www.thesimsresource.com/downloads/details/category/"
        "sims4-lots-residential/title/mm-modern-vintage-4/id/1782277/",
        1782277,
    ),
    ("https://www.thesimsresource.com/downloads/download/itemId/1782277", 1782277),
    ("https://www.thesimsresource.com/downloads/download/itemId/1782277/ticket/tsr123/", 1782277),
    ("https://www.thesimsresource.com/downloads/1782277/some/extra/path", 1782277),
    # URL con prefijo de miembro (autor)
    (
        "https://www.thesimsresource.com/members/McLayneSims/downloads/details/category/"
        "sims4-clothing-male-teenadultelder-everyday/title/boi-trash-hoodies/id/1497492/",
        1497492,
    ),
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


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_extract_item_id(text: str, expected: int | None) -> None:
    assert extract_item_id(text) == expected


# ── fetch_details ─────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, text: str, status: int = 200) -> None:
        self.text = text
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class _FakeHttp:
    """Registra la petición y devuelve la respuesta fija (sin red)."""

    def __init__(
        self,
        response: _FakeResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._response = response
        self._error = error

    def get(self, url: str, **kwargs: object) -> _FakeResponse:
        self.calls.append((url, dict(kwargs)))
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


HTML_DETAIL = """
<li class="required-download-item"><a href="/downloads/1485197">A</a></li>
<li class="required-download-item"><a href="/downloads/1485329">B</a></li>
<span>VIP Exclusive</span>
"""


def test_fetch_details_single_request_parses_both_signals() -> None:
    http = _FakeHttp(_FakeResponse(HTML_DETAIL))

    is_vip, required = fetch_details(1485254, http)

    assert is_vip
    assert required == [1485197, 1485329]
    # Una sola petición, contra la URL de detalle y con timeout.
    assert len(http.calls) == 1
    url, kwargs = http.calls[0]
    assert url == get_details_url(1485254)
    assert kwargs["timeout"] == 5


def test_fetch_details_plain_item() -> None:
    http = _FakeHttp(_FakeResponse("<html>mod sencillo</html>"))
    assert fetch_details(1, http) == (False, [])


def test_fetch_details_propagates_http_error() -> None:
    http = _FakeHttp(_FakeResponse("no encontrado", status=404))
    with pytest.raises(requests.HTTPError):
        fetch_details(2, http)


def test_fetch_details_propagates_network_error() -> None:
    http = _FakeHttp(error=requests.Timeout("sin respuesta"))
    with pytest.raises(requests.Timeout):
        fetch_details(3, http)
    assert len(http.calls) == 1
