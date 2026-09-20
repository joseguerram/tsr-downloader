"""Capa de visualización para la consola de TSR Downloader (Rich).

Renderiza un marco vivo con Rich (Live + Table): barra de estado superior,
descargas activas con el nombre fijo a la izquierda y barra de progreso /
spinner / icono de resultado a la derecha, y los completados al pie con su
icono alineado a la derecha.

El ancho del área derecha es permanente: solo cambia su contenido
(spinner → barra → ✓/✗). En terminales sin TTY degrada a texto plano.
"""

import os
import sys
import time
import shutil
import threading
from collections import deque

from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

# ── Secuencias ANSI (modo texto plano, sin TTY) ────────────────────────
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_GRAY = "\033[90m"

# ── Estilos para Rich (nombres → estilos declarativos) ─────────────────
_STYLES = {
    "green": "green",
    "red": "red",
    "yellow": "yellow",
    "cyan": "cyan",
    "gray": "dim",
}
_ANSI = {
    "green": _GREEN,
    "red": _RED,
    "yellow": _YELLOW,
    "cyan": _CYAN,
    "gray": _GRAY,
}

# ── Animación spinner (giratorio, distinto a la barra) ─────────────────
_SPINNERS = ["◜", "◝", "◞", "◟"]

# ── Estado global ──────────────────────────────────────────────────────
_UI = False
_COLORS = True
_mode = "unicode"
_console: Console | None = None
_live: Live | None = None
_live_active = False

_lock = threading.RLock()

_status = ""
_log: deque = deque(maxlen=200)
_active: dict[int, "_Progress"] = {}
_completed: list[tuple[str, str, str]] = []   # (icono, nombre, estilo)
_session_ok = 0
_session_failed = 0
_member_info = ""
_total_files = 0
_plain_cr = False                          # modo plano: barra impresa con \r

_ICON_SETS = {
    "download": ("\uf019", "↓", " "),
    "ok":       ("\uf00c", "✓", "✓"),
    "error":    ("\uf00d", "✗", "✗"),
    "queue":    ("\uf017", "…", ">"),
    "vip":      ("\uf023", "■", "!"),
    "dup":      ("\uf0c7", "~", "-"),
    "new":      ("\uf067", "+", "+"),
}


# ── Detección de Nerd Font ────────────────────────────────────────────

def _nerd_font_windows() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32

        class COORD(ctypes.Structure):
            _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]

        class CONSOLE_FONT_INFOEX(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.ULONG),
                ("nFont", wintypes.ULONG),
                ("dwFontSize", COORD),
                ("FontFamily", wintypes.UINT),
                ("FontWeight", wintypes.UINT),
                ("FaceName", wintypes.WCHAR * 32),
            ]

        kernel32.GetCurrentConsoleFontEx.argtypes = [
            wintypes.HANDLE, wintypes.BOOL,
            ctypes.POINTER(CONSOLE_FONT_INFOEX),
        ]
        kernel32.GetCurrentConsoleFontEx.restype = wintypes.BOOL

        h = kernel32.GetStdHandle(-11)
        info = CONSOLE_FONT_INFOEX()
        info.cbSize = ctypes.sizeof(CONSOLE_FONT_INFOEX)
        if kernel32.GetCurrentConsoleFontEx(h, False, ctypes.byref(info)):
            return "nerd" in info.FaceName.lower()
    except Exception:
        pass
    return False


def _probe_glyph(stdin_fd: int, stdout_fd: int, glyph: str) -> bool:
    import select
    os.write(stdout_fd, b"\033[s")
    os.write(stdout_fd, b"\033[1G")
    os.write(stdout_fd, glyph.encode("utf-8", "replace"))
    os.write(stdout_fd, b"\033[6n")

    resp = b""
    while len(resp) < 32:
        ready, _, _ = select.select([stdin_fd], [], [], 0.3)
        if not ready:
            return False
        chunk = os.read(stdin_fd, 1)
        if not chunk:
            return False
        resp += chunk
        if resp.endswith(b"R"):
            break

    text = resp.decode("ascii", "ignore")
    if "[" not in text or ";" not in text:
        return False
    try:
        col = int(text.split("[")[-1].rstrip("R").split(";")[1])
    except ValueError:
        return False
    return col == 2


def _nerd_font_probe() -> bool:
    if os.name != "posix":
        return False
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    try:
        import termios, tty
        stdin_fd = sys.stdin.fileno()
        stdout_fd = sys.stdout.fileno()
        attrs = termios.tcgetattr(stdin_fd)
    except Exception:
        return False

    try:
        tty.setraw(stdin_fd)
        ok = (_probe_glyph(stdin_fd, stdout_fd, "\ue0b0")
              and _probe_glyph(stdin_fd, stdout_fd, "\uf019"))
        return ok
    except Exception:
        return False
    finally:
        try:
            os.write(sys.stdout.fileno(), b"\033[u\033[K")
        except Exception:
            pass
        try:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, attrs)
        except Exception:
            pass


# ── Soporte de color en Windows ───────────────────────────────────────

def _enable_windows_vt() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetConsoleMode.restype = wintypes.BOOL
        kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.SetConsoleMode.restype = wintypes.BOOL

        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        ok = True
        for std in (-11, -12):
            h = kernel32.GetStdHandle(std)
            mode = wintypes.DWORD()
            if kernel32.GetConsoleMode(h, ctypes.byref(mode)):
                if not (mode.value & ENABLE_VIRTUAL_TERMINAL_PROCESSING):
                    kernel32.SetConsoleMode(h, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
            else:
                ok = False
        return ok
    except Exception:
        return False


# ── Inicialización ────────────────────────────────────────────────────

def init(nerd_requested: bool = True):
    global _UI, _COLORS, _mode, _console, _live

    is_tty = sys.stdout.isatty()
    _COLORS = is_tty
    if is_tty:
        if os.name == "nt":
            _enable_windows_vt()
        _UI = True
    else:
        _UI = False

    if nerd_requested:
        if _nerd_font_windows() or _nerd_font_probe():
            _mode = "nerd"
        else:
            _mode = "unicode"
    else:
        _mode = "none"

    _console = Console(highlight=False)
    if _UI:
        _live = Live(
            console=_console,
            screen=False,
            auto_refresh=False,
            vertical_overflow="visible",
        )


def icon(name: str) -> str:
    nerd, uni, none = _ICON_SETS[name]
    if _mode == "nerd":
        return nerd
    if _mode == "unicode":
        return uni
    return none


# ── Utilidades de texto ───────────────────────────────────────────────

def _paint(text: str, color: str) -> str:
    if not _COLORS or not color:
        return text
    return f"{color}{text}{_RESET}"


def _emit(text: str, end: str = "\n"):
    sys.stdout.write(text + end)
    sys.stdout.flush()


def _spin_glyph() -> str:
    """Glifo del spinner según el tiempo (anima sin temporizador por frame)."""
    return _SPINNERS[int(time.monotonic() * 3) % len(_SPINNERS)]


def format_bytes(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def format_speed(bps: float) -> str:
    return format_bytes(bps) + "/s"


def format_eta(seconds: float | None) -> str:
    if seconds is None:
        return ""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60}s"


def build_bar(pct: float, width: int = 24) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = int(round(width * pct / 100.0))
    return "█" * filled + "░" * (width - filled)


# ── Animación spinner (temporizador solo mientras haya spinners) ──────

_tick_timer: threading.Timer | None = None


def _start_tick():
    """Arranca el temporizador que re-renderiza mientras haya spinners."""
    global _tick_timer
    if _tick_timer is not None:
        return

    def _do_tick():
        global _tick_timer
        if any(p.bar_kind == "spinner" for p in _active.values()):
            _render(force=True)
            _tick_timer = threading.Timer(0.35, _do_tick)
            _tick_timer.daemon = True
            _tick_timer.start()
        else:
            _tick_timer = None

    _tick_timer = threading.Timer(0.35, _do_tick)
    _tick_timer.daemon = True
    _tick_timer.start()


def _stop_tick():
    global _tick_timer
    _tick_timer = None


# ── Marco ─────────────────────────────────────────────────────────────

_last_render = 0.0


def _fit(text: str, width: int) -> str:
    """Recorta un texto añadiendo '…' si excede el ancho (ancho fijo)."""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def _build_renderable():
    """Compone el marco completo: estado, separador, activos, completados y
    avisos recientes al pie.

    Estado y separador van a ancho completo; los activos/completados viven
    en una tabla de dos columnas (nombre a la izquierda, barra o icono a la
    derecha). Los avisos se reservan espacio abajo para dar feedback
    inmediato al copiar una URL. Devuelve algo renderizable (Group/Text).
    """
    w = _console.width if _console is not None else 80
    h = _console.height if _console is not None else 24

    msgs = list(_log)[-3:] if _log else []
    parts = []

    # ── 1. Barra de estado (siempre arriba, ancho completo) ──────────
    if _status:
        parts.append(Text(_fit(_status, w - 1), style="bold cyan"))

    # ── 2. Tabla con separador, activos y completados ────────────────
    if _active or _completed or msgs:
        parts.append(Text("━" * min(w - 4, 62), style="dim"))

        t = Table(
            show_header=False,
            show_edge=False,
            box=None,
            padding=(0, 1),
            expand=True,
        )
        t.add_column(ratio=1, justify="left", overflow="ellipsis", no_wrap=True)
        t.add_column(justify="right", overflow="ellipsis", no_wrap=True)

        # Los avisos se reservan abajo: el feedback gana a los completados
        remaining = h - 1 - len(parts) - len(msgs)
        if remaining > 0:
            for p in list(_active.values()):
                if remaining <= 0:
                    break
                label = Text(p.label or " ", style="bold")
                if p.bar_kind == "spinner":
                    right = Text(_spin_glyph(), style="bold magenta")
                    if p.message_text:
                        right.append(f"  {p.message_text}", style="dim")
                else:
                    right = Text(p.bar, style="cyan")
                t.add_row(label, right)
                remaining -= 1

            for ic, name, style in _completed:
                if remaining <= 0:
                    break
                # Completado: icono a la izquierda reemplaza al de descarga
                t.add_row(Text(f"{ic} {name}", style=style), "")
                remaining -= 1

        parts.append(t)

    # ── 3. Avisos recientes (feedback al pie, atenuado) ──────────────
    for text, color in msgs:
        parts.append(Text(_fit(text, w - 1), style=(_STYLES.get(color) or "dim")))

    if not parts:
        return Text("")
    return Group(*parts)


def _render(force: bool = False):
    """Actualiza el marco en pantalla (con throttle salvo en forcings)."""
    if not _UI:
        return
    global _live_active, _last_render
    now = time.monotonic()
    if not force and now - _last_render < 0.1:
        return
    _last_render = now
    with _lock:
        try:
            if _live is None:
                return
            if not _live_active:
                _live.start()
                _live_active = True
            # Rich no pinta con solo update(): hay que forzar el refresh.
            _live.update(_build_renderable(), refresh=True)
        except Exception:
            pass


# ── Mensajes ──────────────────────────────────────────────────────────

def _log_msg(text: str, color: str):
    with _lock:
        _log.append((text, color))
    if not _UI:
        _emit(_paint(text, _ANSI.get(color, "")) if color else text)


def info(msg: str):
    _log_msg(msg, "cyan")

def ok(msg: str):
    _log_msg(msg, "green")

def err(msg: str):
    _log_msg(msg, "red")

def warn(msg: str):
    _log_msg(msg, "yellow")

def note(msg: str):
    _log_msg(msg, "")


# ── Barra de estado ───────────────────────────────────────────────────

def set_session_info(member_id: str = "", authenticated: bool = True):
    global _member_info
    if authenticated and member_id:
        _member_info = f"Miembro #{member_id}"
    else:
        _member_info = "Anónimo"
    _render(force=True)


def update_status(*, total: int | None = None, active: int | None = None,
                  queue: int | None = None,
                  ok_count: int | None = None, failed: int | None = None):
    global _status, _total_files
    if total is not None:
        _total_files = total

    parts = ["TSR Downloader"]
    if _member_info:
        parts.append(_member_info)
    parts.append(f"Total: {_total_files}")
    if ok_count is not None:
        parts.append(f"OK: {ok_count}")
    if failed is not None:
        parts.append(f"Fail: {failed}")
    if active is not None:
        parts.append(f"Descargando: {active}")
    if queue is not None:
        parts.append(f"Cola: {queue}")
    _status = " | ".join(parts)
    _render(force=True)


# ── Progreso de descargas ─────────────────────────────────────────────

class _Progress:
    def __init__(self, item_id: int):
        self.item_id = item_id
        self.label: str | None = None       # None = "preparando descarga"
        self.bar: str = ""
        self.bar_kind: str = "spinner"      # "spinner" | "bar"
        self.message_text: str = ""

    def set_label(self, label: str | None = None):
        with _lock:
            self.label = label
        self._show()

    def message(self, text: str):
        """Mensaje de espera (temporizador TSR) junto al spinner."""
        with _lock:
            self.message_text = text
            self.bar_kind = "spinner"
            if not _UI:
                self._emit_plain(f"{self.label or ''} — {text}")
        _start_tick()
        _render()

    def update(self, pct: float, downloaded: float, total: float,
               speed: float, eta: float):
        bar = (f"{build_bar(pct)} {pct:3.0f}%  "
               f"{format_bytes(downloaded)}/{format_bytes(total)}  "
               f"{format_speed(speed)}  ETA {format_eta(eta)}")
        with _lock:
            self.bar = bar
            self.bar_kind = "bar"
            self.message_text = ""
            if not _UI:
                global _plain_cr
                _plain_cr = True
                self._emit_plain(bar, end="\r")
        _render()

    def _show(self):
        _render()

    @staticmethod
    def _emit_plain(text: str, end: str = "\n"):
        _emit(text, end)


def start_progress(item_id: int, label: str | None = None) -> _Progress:
    p = _Progress(item_id)
    p.label = label                          # None = spinner "preparando" sin nombre
    with _lock:
        _active[item_id] = p
    _start_tick()
    _render(force=True)
    return p


def finish_progress(item_id: int, name: str, color: str = "green"):
    global _plain_cr
    with _lock:
        _active.pop(item_id, None)
        style = _STYLES.get(color, "green")
        ic = icon("error") if color == "red" else icon("ok")
        _completed.insert(0, (ic, name, style))

        if not _UI:
            if _plain_cr:
                _plain_cr = False
                _emit("")
            verb = "Error:" if color == "red" else "Guardado:"
            _emit(_paint(f"{ic} {verb} {name}", _ANSI.get(color, "")))

    if not any(p.bar_kind == "spinner" for p in _active.values()):
        _stop_tick()
    _render(force=True)


# ── Cierre ────────────────────────────────────────────────────────────

def shutdown(success: int, failed: int, last: str):
    global _UI, _live_active
    _stop_tick()
    if _UI and _live is not None and _live_active:
        try:
            _live.stop()
        except Exception:
            pass
        _live_active = False
    _UI = False

    w = _console.width if _console is not None else shutil.get_terminal_size().columns
    sep = "─" * max(1, min(w - 2, 62))
    _emit("")
    _emit(_paint(sep, _GRAY))
    _emit(f"Resumen — descargados: {success} | fallidos: {failed}")
    if last:
        _emit(f"Último archivo: {last}")
    _emit(_paint(sep, _GRAY))