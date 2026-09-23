"""Descarga de items de TSR con reanudación y progreso en vivo."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import requests

from . import display
from .exceptions import DownloadError

logger = logging.getLogger(__name__)


def _clean_filename(name: str) -> str:
    return re.sub(r'[\\<>/:"|?*]', "", name)


class TSRDownloader:
    def __init__(
        self,
        session: requests.Session,
        item_id: int,
        authenticated: bool,
        member_id: str = "",
        login_key: str = "",
    ) -> None:
        self.session = session
        self.item_id = item_id
        self.authenticated = authenticated
        self.member_id = member_id
        self.login_key = login_key
        self.ticket = ""
        self.ticket_time = 0.0

    def init(self) -> None:
        """Obtiene el ticket de descarga (necesario también para usuarios autenticados)."""
        url = "https://www.thesimsresource.com/ajax.php"
        params: dict[str, str | int] = {
            "c": "downloads",
            "a": "initDownload",
            "itemid": self.item_id,
            "format": "zip",
        }
        logger.debug(f"  [DL] GET {url} params={params}")
        r = self.session.get(url, params=params, timeout=(5, 30))
        logger.debug(f"  [DL] initDownload: status={r.status_code}, body={r.text[:200]}")
        try:
            data = r.json()
        except ValueError as e:
            raise DownloadError("Respuesta no válida de TSR (posible bloqueo).") from e
        ticket = data.get("ticket") if isinstance(data, dict) else None
        if not ticket:
            raise DownloadError("TSR no devolvió ticket de descarga; inténtalo más tarde.")
        self.ticket = ticket
        self.ticket_time = time.time() * 1000
        logger.info(f"  [DL] Ticket obtenido para item {self.item_id}")

        if self.authenticated and self.login_key:
            self.session.cookies.set("tsrdlsession", self.login_key, domain=".thesimsresource.com")
            logger.debug(f"  [DL] Cookie tsrdlsession establecida para miembro {self.member_id}")

    def get_url(self) -> str:
        """Obtiene la URL real de descarga a partir del ticket."""
        url = "https://www.thesimsresource.com/ajax.php"
        params: dict[str, str | int] = {
            "c": "downloads",
            "a": "getdownloadurl",
            "ajax": "1",
            "itemid": self.item_id,
            "mid": self.member_id or "0",
            "lk": self.login_key or "0",
            "ticket": self.ticket,
        }
        logger.debug(f"  [DL] GET {url} params={params}")
        r = self.session.get(url, params=params, timeout=(5, 30))
        logger.debug(f"  [DL] getdownloadurl: status={r.status_code}, body={r.text[:300]}")
        try:
            data = r.json()
        except ValueError as e:
            raise DownloadError("Respuesta no válida de TSR (posible bloqueo).") from e
        if not isinstance(data, dict):
            raise DownloadError("Respuesta inesperada de TSR.")

        if data.get("error"):
            raise DownloadError(f"Error de descarga: {data['error']}")

        download_url = data.get("url")
        if not download_url:
            raise DownloadError("TSR no devolvió la URL de descarga.")
        return str(download_url)

    def download(self, dest_dir: Path) -> str:
        """Descarga el archivo mostrando progreso en vivo. Devuelve el nombre del archivo."""
        progress = display.start_progress(self.item_id)  # spinner mientras se resuelve el nombre

        if not self.authenticated:
            elapsed = time.time() * 1000 - self.ticket_time
            wait = (15000 - elapsed) / 1000
            while wait > 0:
                progress.message(f"Esperando {wait:.0f}s por el temporizador de TSR…")
                time.sleep(min(1.0, wait))
                wait -= 1.0

        url = self.get_url()
        logger.debug(f"  [DL] URL de descarga: {url[:80]}…")

        logger.debug(f"  [DL] HEAD {url[:80]}…")
        head = self.session.head(url, stream=True, timeout=10)
        disposition = head.headers.get("Content-Disposition", "")
        match = re.search(r'filename="?([^";\n]+)"?', disposition)
        filename = _clean_filename(match.group(1)) if match else f"tsr_{self.item_id}.zip"
        filepath = dest_dir / filename
        part = filepath.with_name(filepath.name + ".part")
        total = int(head.headers.get("Content-Length") or 0)
        logger.debug(f"  [DL] Nombre de archivo: {filename}, tamaño: {total} bytes")

        existing_size = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={existing_size}-"} if existing_size else {}
        logger.debug(f"  [DL] Archivo parcial: {existing_size} bytes")

        progress.set_label(f"{display.icon('download')} {filename}")
        r = self.session.get(url, stream=True, headers=headers, timeout=30)
        r.raise_for_status()

        # Si el servidor ignora el Range (200 en vez de 206), el archivo
        # parcial no sirve: se reescribe desde cero para no corromperlo.
        if existing_size and r.status_code != 206:
            logger.debug("  [DL] Servidor ignoró el Range; reiniciando la descarga")
            existing_size = 0
        mode = "ab" if existing_size else "wb"

        start = time.monotonic()
        downloaded = existing_size  # bytes totales del archivo en disco
        already_had = existing_size  # bytes tenidos antes de medir
        with part.open(mode) as f:
            for chunk in r.iter_content(chunk_size=128 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                elapsed = time.monotonic() - start
                # La velocidad mide solo lo nuevo: no cuenta los bytes
                # reanudados, que se descargaron en una sesión anterior.
                speed = (downloaded - already_had) / elapsed if elapsed > 0 else 0.0
                pct = (downloaded / total * 100.0) if total else 0.0
                eta = (total - downloaded) / speed if total and speed > 0 else 0.0
                progress.update(pct, downloaded, total, speed, eta)

        part.replace(filepath)

        logger.info(f"  [DL] Descargado: {filename}")
        return filename
