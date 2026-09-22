"""Gestión de descargas: cola, activos, historial y contadores.

Toda la mutación de estado compartido ocurre tras ``self._lock``; las
llamadas a la interfaz y las escrituras a disco se hacen fuera del lock
para no bloquear a los demás hilos.
"""

from __future__ import annotations

import copy
import logging
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from . import display
from .config import Config, HistoryEntry, load_history, save_history
from .downloader import TSRDownloader
from .exceptions import ConfigError, DownloadError
from .session import TSRSession
from .url_parser import extract_item_id, fetch_details

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3  # envíos totales por item (1 inicial + 2 reintentos)
RETRY_DELAY_S = 30.0  # espera antes de cada reintento automático


def friendly_error(error: Exception) -> str:
    """Traduce una excepción a un mensaje breve y entendible para la TUI."""
    if isinstance(error, DownloadError):
        return str(error)
    if isinstance(error, requests.Timeout):
        return "TSR no responde (tiempo agotado)"
    if isinstance(error, requests.ConnectionError):
        return "no se pudo contactar con TSR"
    if isinstance(error, requests.HTTPError):
        status = error.response.status_code if error.response is not None else "?"
        return f"TSR respondió con error HTTP {status}"
    if isinstance(error, requests.RequestException):
        return "fallo de red al hablar con TSR"
    return str(error) or type(error).__name__


class DownloadManager:
    """Centraliza el estado compartido de las descargas tras un único lock."""

    def __init__(self, config: Config, session: TSRSession) -> None:
        self.config = config
        self.session = session
        self.executor = ThreadPoolExecutor(max_workers=config.max_concurrent + 2)
        self._lock = threading.Lock()
        self.active: set[int] = set()
        self.queue: deque[int] = deque()
        self.history: list[HistoryEntry] = []
        self._notified: set[int] = set()
        self.total_files = 0
        self.session_ok = 0
        self.session_failed = 0
        self.last_file = ""
        self._attempts: dict[int, int] = {}  # intentos de envío por item
        self._retry_at: dict[int, float] = {}  # instante del próximo reintento

    # -- Ciclo de vida -----------------------------------------------------

    def load_history(self) -> None:
        try:
            history = load_history()
        except ConfigError as e:
            display.warn(str(e))
            history = []
        with self._lock:
            self.history = history

    def initialize(self, total_files: int) -> None:
        """Fija los contadores iniciales antes de arrancar el bucle."""
        with self._lock:
            self.total_files = total_files
            self.last_file = self.history[0].get("filename", "") if self.history else ""

    def close(self) -> None:
        """Cancela la cola pendiente; las descargas en curso terminan solas."""
        self.executor.shutdown(wait=False, cancel_futures=True)

    def summary(self) -> tuple[int, int, str]:
        with self._lock:
            return self.session_ok, self.session_failed, self.last_file

    # -- Consultas ---------------------------------------------------------

    def history_entry(self, item_id: int) -> HistoryEntry | None:
        with self._lock:
            return next((e for e in self.history if e["item_id"] == item_id), None)

    def refresh_status(self) -> None:
        with self._lock:
            total = self.total_files
            active = len(self.active)
            queued = len(self.queue)
            ok = self.session_ok
            failed = self.session_failed
        display.update_status(
            total=total,
            active=active,
            queue=queued,
            ok_count=ok,
            failed=failed,
        )

    # -- Descargas ---------------------------------------------------------

    def _create_worker_session(self) -> requests.Session:
        worker = requests.Session()
        worker.headers.update(self.session.http.headers)
        worker.cookies = copy.deepcopy(self.session.http.cookies)
        return worker

    def _do_download(self, item_id: int) -> None:
        try:
            dl = TSRDownloader(
                session=self._create_worker_session(),
                item_id=item_id,
                authenticated=self.session.authenticated,
                member_id=self.session.member_id,
                login_key=self.session.login_key,
            )
            dl.init()
            filename = dl.download(Path(self.config.download_directory))
            self.on_download_done(item_id, filename, None)
        except Exception as e:
            logger.error(f"Item {item_id}: {type(e).__name__}: {e}")
            self.on_download_done(item_id, "", e)

    def on_download_done(self, item_id: int, filename: str, error: Exception | None) -> None:
        if error is not None:
            with self._lock:
                self.active.discard(item_id)
                self.session_failed += 1
                attempts = self._attempts.get(item_id, 0)
                will_retry = attempts < MAX_ATTEMPTS
                if will_retry:
                    self._retry_at[item_id] = time.monotonic() + RETRY_DELAY_S
            display.finish_progress(item_id, f"Item {item_id} — {friendly_error(error)}", "red")
            if will_retry:
                display.note(
                    f"{display.icon('queue')} Item {item_id}: reintento "
                    f"{attempts + 1}/{MAX_ATTEMPTS} en {RETRY_DELAY_S:.0f}s"
                )
            else:
                display.note(
                    f"{display.icon('error')} Item {item_id}: agotados "
                    f"{MAX_ATTEMPTS} intentos — copia el enlace de nuevo para reintentar"
                )
        else:
            entry = HistoryEntry(
                item_id=item_id,
                filename=filename,
                timestamp=time.time(),
            )
            with self._lock:
                self.active.discard(item_id)
                self._attempts.pop(item_id, None)
                self._retry_at.pop(item_id, None)
                self.session_ok += 1
                self.total_files += 1
                self.last_file = filename
                self.history.insert(0, entry)
                while len(self.history) > self.config.history_size:
                    self.history.pop()
                snapshot = list(self.history)
            save_history(snapshot)  # fuera del lock: E/S de disco
            display.finish_progress(item_id, filename)
        self.refresh_status()

    def enqueue_items(self, item_id: int, requirements: list[int]) -> None:
        """Encola item y dependencias. Recopila bajo el lock, lanza fuera."""
        to_start: list[int] = []
        queued: list[tuple[int, int]] = []
        with self._lock:
            items = [item_id] + [
                r for r in requirements if r not in self.active and r not in self.queue
            ]
            for iid in items:
                if iid in self.active or iid in self.queue:
                    continue
                self._attempts[iid] = self._attempts.get(iid, 0) + 1
                self._retry_at.pop(iid, None)
                if len(self.active) < self.config.max_concurrent:
                    to_start.append(iid)
                    self.active.add(iid)
                else:
                    self.queue.append(iid)
                    queued.append((iid, len(self.queue)))
        # Avisos fuera del lock: display puede bloquear esperando a la TUI.
        for iid, position in queued:
            display.note(f"{display.icon('queue')} En cola: item {iid} (posición #{position})")
        for iid in to_start:
            self.executor.submit(self._do_download, iid)
        self.refresh_status()

    def start_ready(self) -> None:
        """Lanza de la cola los items que caben en el límite de concurrencia."""
        to_start: list[int] = []
        with self._lock:
            while self.queue and len(self.active) < self.config.max_concurrent:
                iid = self.queue.popleft()
                self.active.add(iid)
                to_start.append(iid)
        for iid in to_start:
            self.executor.submit(self._do_download, iid)

    def consume_retry(self, text: str, now: float | None = None) -> int | None:
        """Consume el reintento pendiente de ``text`` si su plazo ya venció.

        El bucle del portapapeles lo llama en cada pasada para reintentar
        enlaces que fallaron aunque el contenido no haya cambiado.
        """
        item_id = extract_item_id(text)
        if item_id is None:
            return None
        deadline = time.monotonic() if now is None else now
        with self._lock:
            due = self._retry_at.get(item_id)
            if due is None or deadline < due:
                return None
            self._retry_at.pop(item_id, None)
            return item_id

    def process_url(self, text: str) -> None:
        progress_started = False
        item_id: int | None = None
        try:
            item_id = extract_item_id(text)
            if item_id is None:
                return

            # Ya se está descargando o ya está en la cola (aviso único).
            notify: str | None = None
            with self._lock:
                if item_id in self.active or item_id in self.queue:
                    if item_id not in self._notified:
                        self._notified.add(item_id)
                        notify = "active" if item_id in self.active else "queue"
            if notify == "active":
                display.note(f"{display.icon('dup')} Item {item_id} ya se está descargando")
                return
            if notify == "queue":
                display.note(f"{display.icon('queue')} Item {item_id} ya está en la cola")
                return

            # Ya fue descargado anteriormente
            entry = self.history_entry(item_id)
            if entry is not None:
                name = entry.get("filename", f"Item {item_id}")
                display.finish_duplicate(
                    item_id,
                    f"{name} — ya fue descargado anteriormente",
                )
                return

            # Crear la fila inmediatamente. Las comprobaciones de VIP y
            # dependencias pueden tardar; el usuario debe ver el item desde ya.
            display.start_progress(
                item_id,
                f"{display.icon('download')} Item #{item_id}",
            )
            progress_started = True

            # Comprobación de VIP y dependencias en una sola petición
            try:
                is_vip, requirements = fetch_details(item_id, self.session.http)
            except Exception as e:
                logger.warning(f"Item {item_id}: no se pudo consultar el detalle ({e})")
                display.warn(
                    f"No se pudo verificar VIP ni dependencias del item {item_id}; se continúa"
                )
                is_vip, requirements = False, []

            if is_vip:
                display.finish_progress(
                    item_id,
                    f"Item {item_id} — exclusivo VIP",
                    "red",
                )
                return

            self.enqueue_items(item_id, requirements)

        except Exception as e:
            if progress_started and item_id is not None:
                display.finish_progress(
                    item_id,
                    f"Item {item_id} — {friendly_error(e)}",
                    "red",
                )
            display.err(f"Error al procesar la URL: {friendly_error(e)}")
