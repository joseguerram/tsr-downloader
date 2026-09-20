import os
import sys
import time
import logging
import copy
import threading
from concurrent.futures import ThreadPoolExecutor

import pyperclip
import requests

# Permite ejecutar desde la raíz del proyecto ('python run.py', 'python -m src.main')
# resolviendo los módulos internos que viven dentro de esta carpeta.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import display
from config import Config, load_history, save_history, load_session, save_session
from session import TSRSession
from downloader import TSRDownloader
from url_parser import extract_item_id, is_vip_exclusive, get_required_items

# ── Logging ───────────────────────────────────────────────────────────
# La consola la gestiona display (marco con color); el archivo lleva DEBUG.

_file = logging.FileHandler("logs.log")
_file.setLevel(logging.DEBUG)
_file.setFormatter(logging.Formatter("[%(levelname)s] [%(name)s] %(message)s"))

logging.basicConfig(level=logging.DEBUG, handlers=[_file])
logger = logging.getLogger(__name__)

# ── Globals ───────────────────────────────────────────────────────────

config = Config.load()
display.init(nerd_requested=config.use_nerd_icons)

session = TSRSession()
executor = ThreadPoolExecutor(max_workers=config.max_concurrent + 2)

active: set[int] = set()
queue: list[int] = []
history: list[dict] = []
last_clip = ""
_lock = threading.Lock()

# IDs ya notificados en esta sesión para no repetir mensajes
_notified: set[int] = set()

_total_files = 0
_session_ok = 0
_session_failed = 0
_last_file = ""


def _history_ids() -> set[int]:
    """IDs de elementos ya descargados según el historial."""
    with _lock:
        return {entry["item_id"] for entry in history}


# ── Session Setup ─────────────────────────────────────────────────────

def setup_session():
    global session
    saved = load_session()
    if saved and session.validate_saved(saved):
        display.ok(f"{display.icon('ok')} Sesión restaurada")
        return

    if config.tsr_email and config.tsr_password:
        if session.login(config.tsr_email, config.tsr_password):
            save_session(session.to_dict())
            display.ok(f"{display.icon('ok')} Sesión iniciada como miembro #{session.member_id}")
            return

    display.err(
        "No se pudo iniciar la sesión. Añade tsr_email y tsr_password "
        "en config.json para el inicio de sesión automático."
    )
    sys.exit(1)


def _create_worker_session() -> requests.Session:
    worker = requests.Session()
    worker.headers.update(session.http.headers)
    worker.cookies = copy.deepcopy(session.http.cookies)
    return worker


# ── Download Management ──────────────────────────────────────────────

def _refresh_status():
    display.update_status(
        total=_total_files,
        active=len(active),
        queue=len(queue),
        ok_count=_session_ok,
        failed=_session_failed,
    )


def on_download_done(item_id: int, filename: str, error: Exception | None):
    global _session_ok, _session_failed, _total_files, _last_file
    with _lock:
        active.discard(item_id)

    if error:
        _session_failed += 1
        display.finish_progress(
            item_id,
            f"item {item_id} ({type(error).__name__})",
            "red",
        )
    else:
        _session_ok += 1
        _total_files += 1
        _last_file = filename
        with _lock:
            history.insert(0, {
                "item_id": item_id,
                "filename": filename,
                "timestamp": time.time(),
            })
            while len(history) > config.history_size:
                history.pop()
            save_history(history)
        display.finish_progress(item_id, filename)

    _refresh_status()


def _do_download(item_id: int):
    try:
        worker_session = _create_worker_session()
        dl = TSRDownloader(
            session=worker_session,
            item_id=item_id,
            authenticated=session.authenticated,
            member_id=session.member_id,
            login_key=session.login_key,
        )
        dl.init()
        filename = dl.download(config.download_directory)
        on_download_done(item_id, filename, None)
    except Exception as e:
        logger.error(f"Item {item_id}: {type(e).__name__}: {e}")
        on_download_done(item_id, "", e)


def _enqueue_items(item_id: int, requirements: list[int]):
    """Encola item y dependencias. Recopila bajo el lock, lanza fuera para evitar deadlock."""
    to_start: list[int] = []
    with _lock:
        items = [item_id] + [r for r in requirements if r not in active and r not in queue]
        for iid in items:
            if iid in active or iid in queue:
                continue
            if len(active) < config.max_concurrent:
                to_start.append(iid)
                active.add(iid)
            else:
                queue.append(iid)
                display.note(f"{display.icon('queue')} En cola: item {iid} (posición #{len(queue)})")

    for iid in to_start:
        executor.submit(_do_download, iid)
    _refresh_status()


def process_url(text: str):
    progress_started = False
    try:
        item_id = extract_item_id(text)
        if item_id is None:
            return

        with _lock:
            # Ya se está descargando
            if item_id in active:
                if item_id not in _notified:
                    _notified.add(item_id)
                    display.note(f"{display.icon('dup')} Item {item_id} ya se está descargando")
                return
            # Ya está en la cola
            if item_id in queue:
                if item_id not in _notified:
                    _notified.add(item_id)
                    display.note(f"{display.icon('queue')} Item {item_id} ya está en la cola")
                return

        # Ya fue descargado anteriormente
        if item_id in _history_ids():
            entry = next(
                (item for item in history if item["item_id"] == item_id),
                None,
            )
            name = entry.get("filename", f"Item {item_id}") if entry else f"Item {item_id}"
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

        # Comprobación de VIP
        try:
            if is_vip_exclusive(item_id):
                display.finish_progress(
                    item_id,
                    f"Item {item_id} — exclusivo VIP",
                    "red",
                )
                return
        except Exception as e:
            logger.warning(f"Item {item_id}: no se pudo verificar VIP ({e})")

        # Comprobación de dependencias
        try:
            requirements = get_required_items(item_id)
        except Exception as e:
            logger.warning(f"Item {item_id}: no se pudieron verificar dependencias ({e})")
            requirements = []

        _enqueue_items(item_id, requirements)

    except Exception as e:
        if progress_started:
            display.finish_progress(
                item_id,
                f"item {item_id} ({type(e).__name__})",
                "red",
            )
        display.err(f"Error al procesar la URL: {type(e).__name__}: {e}")


# ── Main Loop ─────────────────────────────────────────────────────────

def _run_worker():
    global history, last_clip, _total_files, _last_file

    os.makedirs(config.download_directory, exist_ok=True)
    setup_session()
    history = load_history()

    # Conteo inicial de archivos en la carpeta de descargas
    try:
        _total_files = sum(
            1
            for f in os.listdir(config.download_directory)
            if os.path.isfile(os.path.join(config.download_directory, f))
            and not f.endswith(".part")
        )
    except OSError:
        _total_files = 0

    if history:
        _last_file = history[0].get("filename", "")

    display.set_session_info(session.member_id, session.authenticated)
    display.info(f"{display.icon('new')} TSR Downloader listo — copia enlaces de TSR")
    _refresh_status()

    try:
        while True:
            clip = pyperclip.paste()
            if clip != last_clip:
                last_clip = clip
                for line in clip.split("\n"):
                    line = line.strip()
                    if line:
                        executor.submit(process_url, line)

            # Procesar cola
            to_start: list[int] = []
            with _lock:
                while queue and len(active) < config.max_concurrent:
                    iid = queue.pop(0)
                    active.add(iid)
                    to_start.append(iid)
            for iid in to_start:
                executor.submit(_do_download, iid)

            time.sleep(0.1)
    except KeyboardInterrupt:
        logger.info("Cerrando…")
    finally:
        executor.shutdown(wait=False)
        display.shutdown(_session_ok, _session_failed, _last_file)


def main():
    display.run(_run_worker)


if __name__ == "__main__":
    main()
