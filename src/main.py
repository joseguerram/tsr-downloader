"""Punto de entrada de TSR Downloader.

No tiene efectos secundarios al importarse: la configuración, el logging y
la interfaz se inicializan en :func:`main`.
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

import pyperclip

from . import display
from .config import Config, load_session, save_session
from .exceptions import ConfigError
from .manager import DownloadManager
from .session import TSRSession

_ROOT = Path(__file__).resolve().parent.parent
_LOG_PATH = _ROOT / "logs.log"
_CLIPBOARD_POLL_S = 0.2  # intervalo de lectura del portapapeles

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    """Envía todo el log (DEBUG) a logs.log en la raíz del proyecto."""
    handler = logging.FileHandler(_LOG_PATH)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("[%(levelname)s] [%(name)s] %(message)s"))
    logging.basicConfig(level=logging.DEBUG, handlers=[handler])


class AppState:
    """Estado y ciclo de vida: sesión con TSR y bucle del portapapeles."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.session = TSRSession()
        self.manager = DownloadManager(config, self.session)
        self.stop = threading.Event()

    def setup_session(self) -> None:
        """Restaura o inicia sesión; pide credenciales si faltan.

        Se ejecuta antes de arrancar la TUI: los prompts de ``input()`` usan
        la terminal normal y ``SystemExit`` fija el código de salida.
        """
        saved = load_session()
        if saved and self.session.validate_saved(saved):
            display.ok("Sesión restaurada")
            return

        if self.config.needs_setup():
            display.info("Credenciales no configuradas. Se pedirán a continuación:")
            # interactive_setup muta este mismo objeto en sitio: manager
            # comparte la referencia y ve los valores nuevos sin recargar.
            self.config.interactive_setup()

        if not (self.config.tsr_email and self.config.tsr_password):
            display.fatal("Faltan credenciales en config.json (tsr_email / tsr_password).")
            sys.exit(1)

        error = self.session.login(self.config.tsr_email, self.config.tsr_password)
        if error is not None:
            display.fatal(f"No se pudo iniciar la sesión: {error}")
            display.fatal("Verifica tsr_email y tsr_password en config.json.")
            sys.exit(1)

        save_session(self.session.to_dict())
        display.ok(f"Sesión iniciada como miembro #{self.session.member_id}")

    def _clipboard_loop(self) -> None:
        last_clip = ""
        clipboard_warned = False
        while not self.stop.is_set():
            try:
                clip = pyperclip.paste()
            except pyperclip.PyperclipException as e:
                # Sin portapapeles (p. ej. Wayland sin wl-clipboard): se avisa
                # una sola vez y se reintenta sin tumbar la aplicación.
                if not clipboard_warned:
                    clipboard_warned = True
                    display.err(
                        "Portapapeles no disponible. Instala xclip (X11) o "
                        "wl-clipboard (Wayland) y reinicia la app."
                    )
                    logger.warning(f"pyperclip: {e}")
                self.stop.wait(1.0)
                continue

            changed = clip != last_clip
            last_clip = clip
            for line in clip.splitlines():
                line = line.strip()
                if not line:
                    continue
                # Contenido nuevo → procesar; contenido igual → solo si hay
                # un reintento vencido (mismo enlace que falló antes).
                if changed or self.manager.consume_retry(line) is not None:
                    self.manager.executor.submit(self.manager.process_url, line)

            self.manager.start_ready()
            # pyperclip ejecuta xclip en cada lectura: con 0.1 s el fork/exec
            # dominaba el uso de CPU en modo ocioso.
            self.stop.wait(_CLIPBOARD_POLL_S)

    def run(self) -> None:
        """Bucle principal (corre en el hilo trabajador de display)."""
        downloads = Path(self.config.download_directory)
        downloads.mkdir(parents=True, exist_ok=True)
        try:
            self.manager.load_history()

            # Conteo inicial de archivos en la carpeta de descargas
            try:
                total = sum(
                    1 for f in downloads.iterdir() if f.is_file() and not f.name.endswith(".part")
                )
            except OSError:
                total = 0
            self.manager.initialize(total)

            display.set_session_info(self.session.member_id, self.session.authenticated)
            display.info("TSR Downloader listo — copia enlaces de TSR")
            self.manager.refresh_status()
            self._clipboard_loop()
        except KeyboardInterrupt:
            logger.info("Cerrando…")
        except Exception as e:
            logger.exception("Error inesperado en el bucle principal")
            display.err(f"Error inesperado: {type(e).__name__}: {e}")
        finally:
            self.manager.close()
            display.shutdown(*self.manager.summary())


def main() -> None:
    setup_logging()

    config_error: str | None = None
    try:
        config = Config.load()
    except ConfigError as e:
        config = Config()
        config_error = str(e)

    display.init(nerd_requested=config.use_nerd_icons)
    if config_error is not None:
        display.warn(config_error)

    state = AppState(config)
    try:
        state.setup_session()
    except KeyboardInterrupt:
        sys.exit(130)
    display.run(state.run, stop=state.stop)


if __name__ == "__main__":
    main()
