"""Tests de reintentos acotados y mensajes de error del DownloadManager."""

import pytest
import requests

from src import display
from src import manager as manager_mod
from src.config import Config
from src.exceptions import DownloadError
from src.manager import MAX_ATTEMPTS, DownloadManager, friendly_error
from src.session import TSRSession

URL = "https://www.thesimsresource.com/downloads/123456"


class _FakeExecutor:
    """Executor que solo registra los envíos (nada de hilos ni red)."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, tuple[int, ...]]] = []

    def submit(self, fn: object, *args: int) -> None:
        self.calls.append((fn, args))

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        """Compatibilidad con DownloadManager.close(); no hay hilos que parar."""


def _make_manager(monkeypatch: pytest.MonkeyPatch) -> DownloadManager:
    # Que el test nunca reescriba el history.json real del proyecto.
    monkeypatch.setattr(manager_mod, "save_history", lambda history: None)
    mgr = DownloadManager(Config(), TSRSession())
    mgr.executor = _FakeExecutor()  # type: ignore[assignment]
    return mgr


def test_failed_download_schedules_bounded_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = _make_manager(monkeypatch)

    # 1er intento: se encola y, al fallar, programa el reintento.
    mgr.enqueue_items(123456, [])
    assert mgr._attempts[123456] == 1
    mgr.on_download_done(123456, "", DownloadError("fallo"))
    assert mgr.consume_retry(URL) is None  # aún no vencido
    assert mgr.consume_retry(URL, now=1e12) == 123456  # vencido: se consume
    assert mgr.consume_retry(URL, now=1e12) is None  # solo una vez

    # 2º intento.
    mgr.enqueue_items(123456, [])
    assert mgr._attempts[123456] == 2
    mgr.on_download_done(123456, "", DownloadError("fallo"))
    assert mgr.consume_retry(URL, now=1e12) == 123456

    # 3er intento: se agotan los reintentos automáticos.
    mgr.enqueue_items(123456, [])
    assert mgr._attempts[123456] == MAX_ATTEMPTS
    mgr.on_download_done(123456, "", DownloadError("fallo"))
    assert mgr.consume_retry(URL, now=1e12) is None

    # Un éxito limpia los contadores del item.
    mgr.enqueue_items(123456, [])
    mgr.on_download_done(123456, "f.zip", None)
    assert 123456 not in mgr._attempts
    assert 123456 not in mgr._retry_at


def test_consume_retry_ignores_non_urls() -> None:
    mgr = DownloadManager(Config(), TSRSession())
    mgr.executor = _FakeExecutor()  # type: ignore[assignment]
    assert mgr.consume_retry("hola mundo", now=1e12) is None
    assert mgr.consume_retry("https://example.com/1", now=1e12) is None


def test_process_url_vip_aborts_without_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    display.init(nerd_requested=True)  # backend plano determinista en tests
    mgr = _make_manager(monkeypatch)
    monkeypatch.setattr(manager_mod, "fetch_details", lambda iid, http: (True, [777]))

    mgr.process_url(URL)

    assert mgr.executor.calls == []
    assert 123456 not in mgr.active
    assert 123456 not in mgr.queue


def test_process_url_enqueues_item_and_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = _make_manager(monkeypatch)
    monkeypatch.setattr(manager_mod, "fetch_details", lambda iid, http: (False, [777, 888]))

    mgr.process_url(URL)

    assert [args for _fn, args in mgr.executor.calls] == [(123456,), (777,), (888,)]


def test_process_url_continues_when_detail_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    display.init(nerd_requested=True)
    mgr = _make_manager(monkeypatch)

    def boom(iid: int, http: object) -> tuple[bool, list[int]]:
        raise requests.Timeout("sin respuesta")

    monkeypatch.setattr(manager_mod, "fetch_details", boom)

    mgr.process_url(URL)

    # Sin verificar VIP ni dependencias, el item principal sigue encolado.
    assert [args for _fn, args in mgr.executor.calls] == [(123456,)]
    texts = [text for text, _color in display._ui.log]
    assert any("No se pudo verificar" in text for text in texts)
    mgr.close()


def test_friendly_error_messages() -> None:
    assert friendly_error(DownloadError("TSR no devolvió ticket")) == "TSR no devolvió ticket"
    assert friendly_error(requests.ConnectTimeout()) == "TSR no responde (tiempo agotado)"
    assert friendly_error(requests.ConnectionError()) == "no se pudo contactar con TSR"
    response = requests.Response()
    response.status_code = 403
    http_error = requests.HTTPError(response=response)
    assert friendly_error(http_error) == "TSR respondió con error HTTP 403"
    assert friendly_error(ValueError("algo raro")) == "algo raro"
