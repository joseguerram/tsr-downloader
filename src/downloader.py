import os
import re
import time
import logging
import requests

import display

logger = logging.getLogger(__name__)


def _clean_filename(name: str) -> str:
    return re.sub(r'[\\<>/:"|?*]', "", name)


class TSRDownloader:
    def __init__(self, session: requests.Session, item_id: int, authenticated: bool,
                 member_id: str = "", login_key: str = ""):
        self.session = session
        self.item_id = item_id
        self.authenticated = authenticated
        self.member_id = member_id
        self.login_key = login_key
        self.ticket = ""
        self.ticket_time = 0.0
        self.progress = None

    def init(self):
        """Obtiene el ticket de descarga. Siempre es necesario, incluso para usuarios autenticados."""
        url = "https://www.thesimsresource.com/ajax.php"
        params = {
            "c": "downloads", "a": "initDownload",
            "itemid": self.item_id, "format": "zip",
        }
        logger.debug(f"  [DL] GET {url} params={params}")
        r = self.session.get(url, params=params)
        logger.debug(f"  [DL] initDownload: status={r.status_code}, body={r.text[:200]}")
        data = r.json()
        self.ticket = data["ticket"]
        self.ticket_time = time.time() * 1000
        logger.info(f"  [DL] Ticket obtenido para item {self.item_id}")

        if self.authenticated and self.login_key:
            self.session.cookies.set(
                "tsrdlsession", self.login_key, domain=".thesimsresource.com"
            )
            logger.debug(f"  [DL] Cookie tsrdlsession establecida para miembro {self.member_id}")

    def get_url(self) -> str:
        """Obtiene la URL real de descarga a partir del ticket."""
        url = "https://www.thesimsresource.com/ajax.php"
        params = {
            "c": "downloads", "a": "getdownloadurl", "ajax": "1",
            "itemid": self.item_id, "mid": self.member_id or "0",
            "lk": self.login_key or "0", "ticket": self.ticket,
        }
        logger.debug(f"  [DL] GET {url} params={params}")
        r = self.session.get(url, params=params)
        logger.debug(f"  [DL] getdownloadurl: status={r.status_code}, body={r.text[:300]}")
        data = r.json()

        if data.get("error"):
            raise RuntimeError(f"Error de descarga: {data['error']}")

        return data["url"]

    def download(self, dest_dir: str) -> str:
        """Descarga el archivo mostrando progreso en vivo. Devuelve el nombre del archivo."""
        progress = display.start_progress(self.item_id)  # spinner sin nombre
        try:
            if not self.authenticated:
                elapsed = time.time() * 1000 - self.ticket_time
                wait = (15000 - elapsed) / 1000
                if wait > 0:
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
            filepath = os.path.join(dest_dir, filename)
            total = int(head.headers.get("Content-Length") or 0)
            logger.debug(f"  [DL] Nombre de archivo: {filename}, tamaño: {total} bytes")

            existing_size = os.path.getsize(filepath + ".part") if os.path.exists(filepath + ".part") else 0
            headers = {"Range": f"bytes={existing_size}-"} if existing_size else {}
            logger.debug(f"  [DL] Archivo parcial: {existing_size} bytes")

            progress.set_label(f"{display.icon('download')} {filename}")
            r = self.session.get(url, stream=True, headers=headers, timeout=30)
            r.raise_for_status()
            mode = "ab" if existing_size else "wb"

            start = time.monotonic()
            downloaded = existing_size
            with open(filepath + ".part", mode) as f:
                for chunk in r.iter_content(chunk_size=128 * 1024):
                    f.write(chunk)
                    downloaded += len(chunk)
                    elapsed = time.monotonic() - start
                    speed = downloaded / elapsed if elapsed > 0 else 0.0
                    pct = (downloaded / total * 100.0) if total else 0.0
                    eta = (total - downloaded) / speed if total and speed > 0 else 0.0
                    progress.update(pct, downloaded, total, speed, eta)

            if os.path.exists(filepath):
                os.replace(filepath + ".part", filepath)
            else:
                os.rename(filepath + ".part", filepath)

            logger.info(f"  [DL] Descargado: {filename}")
            return filename
        except Exception:
            raise