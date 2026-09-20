"""Interfaz de terminal de TSR Downloader basada en Textual.

La capa conserva una API sencilla para que la lógica de descargas pueda
actualizar la interfaz desde sus hilos de trabajo.
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from collections import deque

from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Rule, Static
from rich.text import Text


_SPINNERS = ["◜", "◝", "◞", "◟"]
_ICON_SETS = {
    "download": ("↓", "↓", " "),
    "ok": ("✓", "✓", "✓"),
    "error": ("✗", "✗", "✗"),
    "queue": ("…", "…", ">"),
    "vip": ("■", "■", "!"),
    "dup": ("~", "~", "-"),
    "new": ("+", "+", "+"),
}

_STYLES = {"green": "green", "red": "red", "yellow": "yellow", "cyan": "cyan", "gray": "dim"}
_ANSI = {"green": "\033[32m", "red": "\033[31m", "yellow": "\033[33m", "cyan": "\033[36m", "gray": "\033[90m"}
_RESET = "\033[0m"

_UI = False
_COLORS = True
_mode = "unicode"
_app: "TSRApp | None" = None
_app_ready = threading.Event()
_lock = threading.RLock()
_log: deque[tuple[str, str]] = deque(maxlen=3)
_rows: dict[object, "DownloadRow"] = {}
_order: list[object] = []
_status = ""
_member_info = ""
_total_files = 0
_session_ok = 0
_session_failed = 0
_plain_cr = False


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


class DownloadRow(Horizontal):
    """Una fila permanente: solo cambia su contenido, nunca su posición."""

    DEFAULT_CSS = """
    DownloadRow { height: 1; width: 100%; }
    DownloadRow .row-label { width: 1fr; text-wrap: nowrap; text-overflow: ellipsis; }
    DownloadRow .row-state { width: 52; content-align: right middle; text-wrap: nowrap; text-overflow: ellipsis; }
    DownloadRow.done .row-state { width: 0; }
    """

    def __init__(self, key: object, label: str, state: str = "", style: str = "bold", done: bool = False):
        super().__init__()
        self.key = key
        self._label, self._state, self._style = label, state, style
        self._done = done

    def compose(self) -> ComposeResult:
        yield Static(self._label, classes="row-label")
        yield Static(self._state, classes="row-state")

    def on_mount(self) -> None:
        if self._done:
            self.add_class("done")

    def update_row(self, label: str, state: str, style: str = "bold", done: bool = False):
        self._label, self._state, self._style = label, state, style
        self.query_one(".row-label", Static).update(Text(label, style=style))
        state_widget = self.query_one(".row-state", Static)
        state_widget.update(Text(state, style="cyan" if state and not state.startswith("SPINNER:") else "magenta"))
        if done:
            self.add_class("done")
        else:
            self.remove_class("done")


class TSRApp(App[None]):
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
        border-left: solid #553b78;
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
    #separator { height: 1; color: #b638a9; }
    .green { color: #62ff9b; }
    .red { color: #ff5370; }
    .yellow { color: #ffe66d; }
    .cyan { color: #00e5ff; }
    .dim { color: #8892a8; }
    """

    def compose(self) -> ComposeResult:
        yield Static("TSR Downloader", id="identity")
        yield Static("", id="status")
        yield VerticalScroll(id="messages")
        yield Rule(id="separator")
        yield VerticalScroll(id="downloads")

    def on_mount(self) -> None:
        _app_ready.set()
        self.set_interval(0.35, self._tick_spinner)

    def _tick_spinner(self) -> None:
        with _lock:
            pending = [progress for progress in _rows.values()
                       if isinstance(progress, _Progress)
                       and progress.bar_kind == "spinner"]
        glyph = _SPINNERS[int(time.monotonic() * 3) % len(_SPINNERS)]
        for progress in pending:
            row = progress.row
            if row is not None:
                try:
                    row.query_one(".row-state", Static).update(
                        glyph + (f"  {progress.message_text}" if progress.message_text else "")
                    )
                except Exception:
                    pass

    def set_identity(self, text: str) -> None:
        title, separator, member = text.partition(" · ")
        rendered = Text(title, style="#ff4fd8")
        if separator:
            rendered.append(" · ", style="#8d75a8")
            rendered.append(member, style="#00e5ff")
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


def _call(method, *args):
    app = _app
    if app is None:
        return
    if threading.current_thread() is getattr(app, "_thread", None):
        method(*args)
    else:
        try:
            app.call_from_thread(method, *args)
        except RuntimeError:
            # Puede ocurrir durante un cierre muy temprano de la aplicación.
            pass


def init(nerd_requested: bool = True):
    global _UI, _COLORS, _mode, _app
    _COLORS = sys.stdout.isatty()
    _UI = _COLORS
    _mode = "unicode"
    if not _UI:
        return

    _app = TSRApp()


def run(worker):
    """Ejecuta Textual en el hilo principal y ``worker`` en segundo plano."""
    if not _UI or _app is None:
        worker()
        return

    _app._thread = threading.current_thread()
    def run_worker():
        try:
            worker()
        finally:
            try:
                _app.exit()
            except Exception:
                pass

    thread = threading.Thread(target=run_worker, name="downloader-worker", daemon=True)
    thread.start()
    _app.run()
    thread.join(timeout=2)


def _paint(text: str, color: str) -> str:
    return f"{_ANSI.get(color, '')}{text}{_RESET}" if _COLORS and color else text


def _emit(text: str, end: str = "\n"):
    sys.stdout.write(text + end)
    sys.stdout.flush()


def _refresh_messages() -> None:
    _call(_app.set_messages, list(_log)) if _app else None


def _log_msg(text: str, color: str):
    with _lock:
        _log.append((text, color))
    if not _UI:
        _emit(_paint(text, color))
    else:
        _refresh_messages()


def info(msg: str): _log_msg(msg, "cyan")
def ok(msg: str): _log_msg(msg, "green")
def err(msg: str): _log_msg(msg, "red")
def warn(msg: str): _log_msg(msg, "yellow")
def note(msg: str): _log_msg(msg, "")


def set_session_info(member_id: str = "", authenticated: bool = True):
    global _member_info
    _member_info = f"Miembro #{member_id}" if authenticated and member_id else "Anónimo"
    if _app:
        _call(_app.set_identity, f"TSR Downloader · {_member_info}")


def update_status(*, total: int | None = None, active: int | None = None,
                  queue: int | None = None, ok_count: int | None = None,
                  failed: int | None = None):
    global _status, _total_files
    if total is not None:
        _total_files = total
    values = [f"Total: {_total_files}"]
    if ok_count is not None: values.append(f"Descargados: {ok_count}")
    if failed is not None: values.append(f"Fallaron: {failed}")
    if active is not None: values.append(f"Descargando: {active}")
    if queue is not None: values.append(f"Cola: {queue}")
    _status = " | ".join(values)
    if _app: _call(_app.set_status, _status)


class _Progress:
    def __init__(self, item_id: int, row_key: object):
        self.item_id, self.row_key = item_id, row_key
        self.label = None
        self.bar_kind = "spinner"
        self.message_text = ""
        self.bar = ""
        self.row: DownloadRow | None = None

    def set_label(self, label: str | None = None):
        self.label = label
        _update_active_row(self)

    def message(self, text: str):
        self.message_text, self.bar_kind = text, "spinner"
        _update_active_row(self)

    def update(self, pct: float, downloaded: float, total: float, speed: float, eta: float):
        self.bar = (f"{build_bar(pct)} {pct:3.0f}%  {format_bytes(downloaded)}/"
                    f"{format_bytes(total)}  {format_speed(speed)}  ETA {format_eta(eta)}")
        self.bar_kind, self.message_text = "bar", ""
        _update_active_row(self)


def _update_active_row(progress: _Progress):
    state = progress.bar if progress.bar_kind == "bar" else "SPINNER:" + (f"  {progress.message_text}" if progress.message_text else "")
    row = progress.row
    if row:
        _call(row.update_row, progress.label or " ", state, "bold")


def start_progress(item_id: int, label: str | None = None) -> _Progress:
    with _lock:
        existing = next((p for key, p in _rows.items() if key == item_id and isinstance(p, _Progress)), None)
        if existing:
            if label is not None: existing.set_label(label)
            return existing
        progress = _Progress(item_id, item_id)
        progress.label = label
        _rows[item_id] = progress
        _order.append(item_id)
    row = DownloadRow(item_id, label or " ", "SPINNER:", "bold")
    progress.row = row
    _rows[item_id] = progress
    _call(_app.add_row, row) if _app else None
    return progress


def finish_progress(item_id: int, name: str, color: str = "green"):
    with _lock:
        progress = _rows.get(item_id)
    row = progress.row if isinstance(progress, _Progress) else None
    if row is not None:
        label = f"{icon('error' if color == 'red' else 'ok')} {name}"
        _call(row.update_row, label, "", _STYLES.get(color, "green"), True)
    if not _UI:
        _emit(_paint(f"{icon('error' if color == 'red' else 'ok')} {'Error:' if color == 'red' else 'Guardado:'} {name}", color))


def finish_duplicate(item_id: int, name: str):
    row_key = ("duplicate", item_id, time.monotonic_ns())
    row = DownloadRow(row_key, f"{icon('dup')} {name}", "", "dim", done=True)
    with _lock:
        _rows[row_key] = row
        _order.append(row_key)
    if _app: _call(_app.add_row, row)
    elif not _UI: _emit(_paint(f"{icon('dup')} {name}", "gray"))


def shutdown(success: int, failed: int, last: str):
    global _UI
    _UI = False
    width = shutil.get_terminal_size().columns
    sep = "─" * max(1, min(width - 2, 62))
    _emit("")
    _emit(_paint(sep, "gray"))
    _emit(f"Resumen — descargados: {success} | fallidos: {failed}")
    if last: _emit(f"Último archivo: {last}")
    _emit(_paint(sep, "gray"))
