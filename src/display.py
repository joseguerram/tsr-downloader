"""Interfaz de terminal de TSR Downloader.

Expone una API de módulo (``display.info``, ``display.start_progress``…)
que delega en el backend activo:

- :class:`TUIBackend` — interfaz TUI basada en Textual (stdout es terminal).
- :class:`PlainBackend` — salida plana por stdout (redirecciones, CI, tests).
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from collections import deque
from collections.abc import Callable

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Static

_SPINNERS = ["◜", "◝", "◞", "◟"]
# (Nerd Font / Font Awesome, Unicode, ASCII). El primer slot solo se usa
# en modo nerd (use_nerd_icons en config.json).
_ICON_SETS = {
    "download": ("", "↓", " "),
    "ok": ("", "✓", "✓"),
    "error": ("", "✗", "✗"),
    "queue": ("", "…", ">"),
    "vip": ("", "■", "!"),
    "dup": ("", "~", "-"),
    "new": ("", "+", "+"),
}
_TEXT_STYLES = {
    "green": "#62ff9b",
    "red": "#ff5370",
    "yellow": "#ffe66d",
    "cyan": "#00e5ff",
    "gray": "#8892a8",
}
_ANSI = {
    "green": "\033[32m",
    "red": "\033[31m",
    "yellow": "\033[33m",
    "cyan": "\033[36m",
    "gray": "\033[90m",
}
_RESET = "\033[0m"

# Símbolo por severidad: la lectura no depende del color (daltonismo,
# terminales monocromas, capturas de pantalla en blanco y negro).
_LEVEL_SYMBOLS = {"red": "✗", "yellow": "⚠", "green": "✓", "cyan": "•"}

_LOG_LEN = 3
# Intervalo mínimo entre volcados de barra a la TUI (la barra se actualiza
# mucho más rápido y cada volcado es un viaje al hilo de la TUI).
_BAR_SYNC_MIN_INTERVAL = 0.1
_mode = "unicode"
_colors = True


# ── Helpers ───────────────────────────────────────────────────────────


def icon(name: str) -> str:
    return _ICON_SETS[name][0 if _mode == "nerd" else 1 if _mode == "unicode" else 2]


def format_bytes(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def format_speed(bps: float) -> str:
    return format_bytes(bps) + "/s"


def format_eta(seconds: float | None) -> str:
    if seconds is None:
        return ""
    seconds = int(seconds)
    return f"{seconds}s" if seconds < 60 else f"{seconds // 60}m {seconds % 60}s"


def build_bar(pct: float, width: int = 24) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = int(round(width * pct / 100.0))
    return "█" * filled + "░" * (width - filled)


def _emit(text: str, end: str = "\n") -> None:
    sys.stdout.write(text + end)
    sys.stdout.flush()


def _paint(text: str, color: str) -> str:
    return f"{_ANSI.get(color, '')}{text}{_RESET}" if _colors and color else text


def _print_summary(success: int, failed: int, last: str) -> None:
    width = shutil.get_terminal_size().columns
    sep = "─" * max(1, min(width - 2, 62))
    _emit("")
    _emit(_paint(sep, "gray"))
    _emit(f"Resumen — descargados: {success} | fallidos: {failed}")
    if last:
        _emit(f"Último archivo: {last}")
    _emit(_paint(sep, "gray"))


# ── Widgets TUI ───────────────────────────────────────────────────────


class DownloadRow(Horizontal):
    """Una fila permanente: solo cambia su contenido, nunca su posición."""

    DEFAULT_CSS = """
    DownloadRow { height: 1; width: 100%; }
    DownloadRow .row-label { width: 1fr; text-wrap: nowrap; text-overflow: ellipsis; }
    DownloadRow .row-state {
        width: 52;
        content-align: right middle;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    DownloadRow.done .row-state { width: 0; }
    """

    def __init__(
        self,
        label: str,
        state: str = "",
        state_style: str = "magenta",
        done: bool = False,
    ) -> None:
        super().__init__()
        self._label = label
        self._state = state
        self._state_style = state_style
        self._done = done

    def compose(self) -> ComposeResult:
        yield Static(self._label, classes="row-label")
        yield Static(self._state, classes="row-state")

    def on_mount(self) -> None:
        if self._done:
            self.add_class("done")

    def update_row(
        self,
        label: str,
        state: str = "",
        *,
        label_style: str = "bold",
        state_style: str = "cyan",
        done: bool = False,
    ) -> None:
        self.query_one(".row-label", Static).update(Text(label, style=label_style))
        self.query_one(".row-state", Static).update(Text(state, style=state_style))
        if done:
            self.add_class("done")
        else:
            self.remove_class("done")

    def update_state(self, state: str, state_style: str = "magenta") -> None:
        self.query_one(".row-state", Static).update(Text(state, style=state_style))


class TSRApp(App[None]):
    TITLE = "TSR Downloader"
    BINDINGS = [("q", "quit", "Cerrar"), ("ctrl+c", "quit", "Cerrar")]
    CSS = """
    Screen { background: #080b16; color: #c8d0e0; }
    #identity {
        height: 1;
        background: #130b24;
        color: #ff4fd8;
        text-style: bold;
        padding: 0 1;
    }
    #status {
        height: 1;
        background: #091b2a;
        color: #00e5ff;
        text-style: bold;
        padding: 0 1;
    }
    #messages {
        height: auto;
        max-height: 4;
        color: #8792aa;
        padding: 0 1;
    }
    #downloads {
        height: 1fr;
        width: 100%;
        padding: 0 1;
        border: round #263b5c;
        scrollbar-size: 1 1;
        scrollbar-color: #2d7890;
        scrollbar-background: #0b1222;
    }
    .green { color: #62ff9b; }
    .red { color: #ff5370; }
    .yellow { color: #ffe66d; }
    .cyan { color: #00e5ff; }
    .dim { color: #8892a8; }
    """

    def __init__(self, backend: TUIBackend) -> None:
        super().__init__()
        self._backend = backend

    def compose(self) -> ComposeResult:
        yield Static("TSR Downloader", id="identity")
        yield Static("", id="status")
        yield VerticalScroll(id="messages")
        yield VerticalScroll(id="downloads")

    def on_mount(self) -> None:
        self._backend.mounted(self)
        self.set_interval(0.35, self._backend.tick_spinner)

    def set_identity(self, text: str) -> None:
        title, separator, member = text.partition(" · ")
        rendered = Text(title, style="#ff4fd8")
        if separator:
            rendered.append(" · ", style="#8d75a8")
            rendered.append(member, style="#ff4fd8")
        self.query_one("#identity", Static).update(rendered)

    def set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def set_messages(self, messages: list[tuple[str, str]]) -> None:
        box = self.query_one("#messages", VerticalScroll)
        box.remove_children()
        for text, style in messages:
            box.mount(Static(text, classes=style or "dim"))

    def add_row(self, row: DownloadRow) -> None:
        self.query_one("#downloads", VerticalScroll).mount(row)


# ── Progreso ──────────────────────────────────────────────────────────


class Progress:
    """Progreso de una descarga; el backend decide cómo renderizarlo."""

    def __init__(self, item_id: int, backend: PlainBackend, label: str | None = None) -> None:
        self.item_id = item_id
        self.label = label
        self.backend = backend
        self.bar_kind = "spinner"
        self.message_text = ""
        self.bar = ""
        self.row: DownloadRow | None = None
        # Última instantánea para poder anunciar el progreso sin TUI.
        self.pct = 0.0
        self.downloaded = 0.0
        self.total = 0.0
        self.speed = 0.0
        self.eta = 0.0
        self.announced = 0  # último cuartil anunciado en modo plano
        self._last_sync = 0.0  # instante del último volcado de barra (throttle)

    def set_label(self, label: str | None) -> None:
        self.label = label
        self.backend.sync_progress(self)

    def message(self, text: str) -> None:
        self.message_text = text
        self.bar_kind = "spinner"
        self.backend.sync_progress(self)

    def update(self, pct: float, downloaded: float, total: float, speed: float, eta: float) -> None:
        self.pct = pct
        self.downloaded = downloaded
        self.total = total
        self.speed = speed
        self.eta = eta
        self.bar = (
            f"{build_bar(pct)} {pct:3.0f}%  {format_bytes(downloaded)}/"
            f"{format_bytes(total)}  {format_speed(speed)}  ETA {format_eta(eta)}"
        )
        self.bar_kind = "bar"
        self.message_text = ""
        self.backend.sync_progress(self)


# ── Backends ──────────────────────────────────────────────────────────


class PlainBackend:
    """Salida plana por stdout; define además la API común de los backends."""

    def __init__(self) -> None:
        self.log: deque[tuple[str, str]] = deque(maxlen=_LOG_LEN)
        self.status = ""
        self.member_info = ""
        self.total_files = 0

    # -- Mensajes ---------------------------------------------------------

    def log_msg(self, text: str, color: str) -> None:
        # Símbolo por nivel: la severidad se lee sin depender del color.
        symbol = _LEVEL_SYMBOLS.get(color, "")
        if symbol and not text.lstrip().startswith(symbol):
            text = f"{symbol} {text}"
        self.log.append((text, color))
        self.render_log(text, color)

    def info(self, msg: str) -> None:
        self.log_msg(msg, "cyan")

    def ok(self, msg: str) -> None:
        self.log_msg(msg, "green")

    def err(self, msg: str) -> None:
        self.log_msg(msg, "red")

    def warn(self, msg: str) -> None:
        self.log_msg(msg, "yellow")

    def note(self, msg: str) -> None:
        self.log_msg(msg, "")

    def render_log(self, text: str, color: str) -> None:
        _emit(_paint(text, color))

    def render_identity(self) -> None:
        """El modo plano no muestra la cabecera de identidad."""

    def render_status(self) -> None:
        """El modo plano no muestra la barra de estado."""

    # -- Sesión y contadores ---------------------------------------------

    def set_session_info(self, member_id: str = "", authenticated: bool = True) -> None:
        self.member_info = f"Miembro #{member_id}" if authenticated and member_id else "Anónimo"
        self.render_identity()

    def update_status(
        self,
        *,
        total: int | None = None,
        active: int | None = None,
        queue: int | None = None,
        ok_count: int | None = None,
        failed: int | None = None,
    ) -> None:
        if total is not None:
            self.total_files = total
        values = [f"Total: {self.total_files}"]
        if ok_count is not None:
            values.append(f"Descargados: {ok_count}")
        if failed is not None:
            values.append(f"Fallaron: {failed}")
        if active is not None:
            values.append(f"Descargando: {active}")
        if queue is not None:
            values.append(f"Cola: {queue}")
        self.status = " | ".join(values)
        self.render_status()

    # -- Progreso ---------------------------------------------------------

    def start_progress(self, item_id: int, label: str | None = None) -> Progress:
        return Progress(item_id, self, label)

    def sync_progress(self, progress: Progress) -> None:
        """Anuncia el progreso en texto cada 25 % (sin barra de bloques)."""
        if progress.bar_kind != "bar":
            return
        quarter = int(progress.pct // 25)
        if not 1 <= quarter <= 3 or quarter <= progress.announced:
            return
        progress.announced = quarter
        detail = (
            f"{progress.pct:3.0f}%  {format_bytes(progress.downloaded)}/"
            f"{format_bytes(progress.total)}  {format_speed(progress.speed)}  "
            f"ETA {format_eta(progress.eta)}"
        )
        label = progress.label or f"Item #{progress.item_id}"
        _emit(f"{label}: {detail}")

    def finish_progress(self, item_id: int, name: str, color: str = "green") -> None:
        mark = icon("error" if color == "red" else "ok")
        word = "Error:" if color == "red" else "Guardado:"
        _emit(_paint(f"{mark} {word} {name}", color))

    def finish_duplicate(self, item_id: int, name: str) -> None:
        _emit(_paint(f"{icon('dup')} {name}", "gray"))

    # -- Ciclo de vida ----------------------------------------------------

    def shutdown(self, success: int, failed: int, last: str) -> None:
        _print_summary(success, failed, last)

    def run(self, worker: Callable[[], None], stop: threading.Event) -> None:
        # El modo plano no tiene señal de cierre: se detiene con Ctrl+C.
        worker()


class TUIBackend(PlainBackend):
    """Interfaz TUI basada en Textual."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.RLock()
        self._progress: dict[int, Progress] = {}
        self._app = TSRApp(self)
        self._app_thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._pending_summary: tuple[int, int, str] | None = None

    # -- Puente con el hilo de la TUI -------------------------------------
    # Regla: nunca llamar a _call() mientras se sostiene self._lock; la TUI
    # toma ese lock en tick_spinner y se produciría un bloqueo cruzado.

    def _call(
        self,
        method: Callable[..., None],
        *args: object,
        **kwargs: object,
    ) -> None:
        if threading.current_thread() is self._app_thread:
            method(*args, **kwargs)
            return
        if not self._ready.is_set():
            # Mounted() vuelca el estado bufferizado al abrir la pantalla.
            return
        try:
            self._app.call_from_thread(method, *args, **kwargs)
        except RuntimeError:
            # Puede ocurrir durante un cierre muy temprano de la aplicación.
            pass

    def mounted(self, app: TSRApp) -> None:
        """Se ejecuta en el hilo de la TUI al montar la pantalla."""
        self._ready.set()
        if self.member_info:
            app.set_identity(f"TSR Downloader · {self.member_info}")
        if self.status:
            app.set_status(self.status)
        app.set_messages(list(self.log))

    def tick_spinner(self) -> None:
        """Animación de los spinners (se ejecuta en el hilo de la TUI)."""
        with self._lock:
            pending = [p for p in self._progress.values() if p.bar_kind == "spinner"]
        glyph = _SPINNERS[int(time.monotonic() * 3) % len(_SPINNERS)]
        for progress in pending:
            row = progress.row
            if row is None:
                continue
            state = glyph + (f"  {progress.message_text}" if progress.message_text else "")
            try:
                row.update_state(state)
            except Exception:
                pass

    # -- Render ------------------------------------------------------------

    def render_log(self, text: str, color: str) -> None:
        self._call(self._app.set_messages, list(self.log))

    def render_identity(self) -> None:
        self._call(self._app.set_identity, f"TSR Downloader · {self.member_info}")

    def render_status(self) -> None:
        self._call(self._app.set_status, self.status)

    # -- Progreso ----------------------------------------------------------

    def start_progress(self, item_id: int, label: str | None = None) -> Progress:
        row: DownloadRow | None = None
        with self._lock:
            progress = self._progress.get(item_id)
            if progress is None:
                progress = Progress(item_id, self, label)
                row = DownloadRow(label or " ", _SPINNERS[0])
                progress.row = row
                self._progress[item_id] = progress
        if row is not None:
            self._call(self._app.add_row, row)  # fuera del lock
        elif label is not None:
            progress.set_label(label)  # fuera del lock
        return progress

    def sync_progress(self, progress: Progress) -> None:
        row = progress.row
        if row is None:
            return
        label = progress.label or " "
        if progress.bar_kind == "bar":
            # Throttle: la barra cambia a cientos de Hz y cada volcado es un
            # viaje a la TUI; el estado final lo garantiza finish_progress.
            now = time.monotonic()
            if now - progress._last_sync < _BAR_SYNC_MIN_INTERVAL:
                return
            progress._last_sync = now
            self._call(row.update_row, label, progress.bar, state_style="cyan")
        else:
            glyph = _SPINNERS[int(time.monotonic() * 3) % len(_SPINNERS)]
            state = glyph + (f"  {progress.message_text}" if progress.message_text else "")
            self._call(row.update_row, label, state, state_style="magenta")

    def finish_progress(self, item_id: int, name: str, color: str = "green") -> None:
        with self._lock:
            progress = self._progress.get(item_id)
        row = progress.row if progress is not None else None
        if row is None:
            return
        mark = icon("error" if color == "red" else "ok")
        self._call(
            row.update_row,
            f"{mark} {name}",
            "",
            label_style=_TEXT_STYLES.get(color, "#62ff9b"),
            done=True,
        )

    def finish_duplicate(self, item_id: int, name: str) -> None:
        row = DownloadRow(f"{icon('dup')} {name}", "", done=True)
        self._call(self._app.add_row, row)

    # -- Ciclo de vida -----------------------------------------------------

    def shutdown(self, success: int, failed: int, last: str) -> None:
        # Se imprime cuando la TUI ya devolvió el terminal (ver run()).
        self._pending_summary = (success, failed, last)

    def run(self, worker: Callable[[], None], stop: threading.Event) -> None:
        self._app_thread = threading.current_thread()

        def run_worker() -> None:
            try:
                worker()
            finally:
                try:
                    self._app.exit()
                except Exception:
                    pass

        thread = threading.Thread(target=run_worker, name="downloader-worker", daemon=True)
        thread.start()
        self._app.run()
        # El usuario cerró la TUI: pide la parada y da 2 s para el resumen.
        stop.set()
        thread.join(timeout=2)
        if self._pending_summary is not None:
            _print_summary(*self._pending_summary)
            self._pending_summary = None


# ── Estado y API de módulo ────────────────────────────────────────────

_ui: PlainBackend = PlainBackend()


def init(nerd_requested: bool = True) -> None:
    """Elige el backend y el juego de iconos según la terminal."""
    global _ui, _colors, _mode
    # NO_COLOR (no-color.org) o TERM=dumb: modo plano y sin ANSI.
    ansi_ok = not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"
    _colors = sys.stdout.isatty() and ansi_ok
    # La terminal no informa de la fuente que usas: se respeta config.json.
    _mode = "nerd" if _colors and nerd_requested else "unicode"
    _ui = TUIBackend() if _colors else PlainBackend()


def run(worker: Callable[[], None], stop: threading.Event) -> None:
    """Ejecuta el backend con ``worker`` (TUI en su propio hilo)."""
    global _ui
    _ui.run(worker, stop)
    if isinstance(_ui, TUIBackend):
        # Tras cerrar la TUI, cualquier mensaje tardío va en modo plano.
        _ui = PlainBackend()


def info(msg: str) -> None:
    _ui.info(msg)


def ok(msg: str) -> None:
    _ui.ok(msg)


def err(msg: str) -> None:
    _ui.err(msg)


def warn(msg: str) -> None:
    _ui.warn(msg)


def note(msg: str) -> None:
    _ui.note(msg)


def fatal(msg: str) -> None:
    """Error para la terminal real, antes de abrir o tras cerrar la TUI."""
    _emit(_paint(msg, "red"))


def set_session_info(member_id: str = "", authenticated: bool = True) -> None:
    _ui.set_session_info(member_id, authenticated)


def update_status(
    *,
    total: int | None = None,
    active: int | None = None,
    queue: int | None = None,
    ok_count: int | None = None,
    failed: int | None = None,
) -> None:
    _ui.update_status(total=total, active=active, queue=queue, ok_count=ok_count, failed=failed)


def start_progress(item_id: int, label: str | None = None) -> Progress:
    return _ui.start_progress(item_id, label)


def finish_progress(item_id: int, name: str, color: str = "green") -> None:
    _ui.finish_progress(item_id, name, color)


def finish_duplicate(item_id: int, name: str) -> None:
    _ui.finish_duplicate(item_id, name)


def shutdown(success: int, failed: int, last: str) -> None:
    _ui.shutdown(success, failed, last)
