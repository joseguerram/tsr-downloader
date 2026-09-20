"""Capa de visualización para la consola de TSR Downloader.

Genera una interfaz con barra de estado superior, mensajes con color y
barras de progreso en vivo. Detecta automáticamente Nerd Fonts y soporte
ANSI; si no están disponibles, degrada a Unicode o a texto plano.
"""

import os
import sys
import time
import shutil
import threading
from collections import deque

# ── Secuencias ANSI ────────────────────────────────────────────────────
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_GRAY = "\033[90m"

# ── Estado global ──────────────────────────────────────────────────────
_COLORS = True
_UI = False          # interfaz con marco (barra de estado + progreso en sitio)
_last_render = 0.0
_mode = "unicode"    # "nerd" | "unicode" | "none"
_plain_cr = False    # en modo texto, la barra terminó con \r (sin salto de línea)

_lock = threading.RLock()

_status = ""
_log: deque = deque(maxlen=200)          # (texto_plano, color_ansi)
_active: dict[int, "_Progress"] = {}

_ICON_SETS = {
    "download": ("\uf019 ", "↓ ", "  "),
    "ok":       ("\uf00c ", "✓ ", "  "),
    "error":    ("\uf00d ", "✗ ", "  "),
    "queue":    ("\uf017 ", "… ", "> "),
    "vip":      ("\uf023 ", "■ ", "! "),
    "dup":      ("\uf0c7 ", "~ ", "- "),
    "new":      ("\uf067 ", "+ ", "+ "),
}
_COLOR_MAP = {
    "green": _GREEN,
    "red": _RED,
    "yellow": _YELLOW,
    "cyan": _CYAN,
    "gray": _GRAY,
}


# ── Detección de Nerd Font ────────────────────────────────────────────

def _nerd_font_windows() -> bool:
    """Detecta Nerd Font en Windows leyendo el nombre de la fuente de consola."""
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

        h = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        info = CONSOLE_FONT_INFOEX()
        info.cbSize = ctypes.sizeof(CONSOLE_FONT_INFOEX)
        if kernel32.GetCurrentConsoleFontEx(h, False, ctypes.byref(info)):
            return "nerd" in info.FaceName.lower()
    except Exception:
        pass
    return False


def _probe_glyph(stdin_fd: int, stdout_fd: int, glyph: str) -> bool:
    """Escribe un glifo y comprueba si el cursor avanza exactamente 1 columna.

    Devuelve True si el glifo se dibuja con ancho 1 (fuente con el glifo).
    """
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
    return col == 2  # salimos de la columna 1 → glifo de 1 celda


def _nerd_font_probe() -> bool:
    """Sonda la terminal: verifica que dos glifos Nerd se dibujan a ancho 1.

    Un glifo Nerd Font ocupa una celda; un glifo de reserva (tofu) también
    suele ocupar una, así que se comprueban dos glifos de familias distintas
    (Powerline y FontAwesome) para reducir falsos positivos.
    """
    if os.name != "posix":
        return False
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    try:
        import termios
        import tty
        stdin_fd = sys.stdin.fileno()
        stdout_fd = sys.stdout.fileno()
        attrs = termios.tcgetattr(stdin_fd)
    except Exception:
        return False

    try:
        tty.setraw(stdin_fd)
        ok = (
            _probe_glyph(stdin_fd, stdout_fd, "\ue0b0")  # Powerline
            and _probe_glyph(stdin_fd, stdout_fd, "\uf019")  # FontAwesome
        )
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
    """Activa el procesamiento de secuencias VT en consolas modernas de Windows."""
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
        for std in (-11, -12):  # stdout, stderr
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
    """Configura colores, interfaz de marco y modo de iconos.

    nerd_requested: si el usuario permite iconos Nerd Font en la config.
    """
    global _COLORS, _UI, _mode

    is_tty = sys.stdout.isatty()

    if not is_tty:
        # Salida redirigida (script, IDE, pipe): texto plano sin colores
        _COLORS = False
        _UI = False
    elif os.name == "nt":
        vt_ok = _enable_windows_vt()
        if vt_ok:
            _UI = True
        else:
            try:
                import colorama  # integración legacy de Windows
                colorama.init()
            except ImportError:
                _COLORS = False
            _UI = False
    else:
        _UI = True

    if nerd_requested:
        if _nerd_font_windows() or _nerd_font_probe():
            _mode = "nerd"
        else:
            _mode = "unicode"
    else:
        _mode = "none"


def icon(name: str) -> str:
    """Devuelve el identificador visual (prefijo) para un contexto."""
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


def _fit(text: str, width: int) -> str:
    if width <= 3:
        return text[: max(0, width)]
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def format_bytes(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def format_speed(bps: float) -> str:
    return format_bytes(bps) + "/s"


def format_eta(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60}s"


def build_bar(pct: float, width: int = 24) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = int(round(width * pct / 100.0))
    return "█" * filled + "░" * (width - filled)


# ── Salida ────────────────────────────────────────────────────────────

def _emit(text: str, end: str = "\n"):
    sys.stdout.write(text + end)
    sys.stdout.flush()


def _build_frame() -> list:
    w = shutil.get_terminal_size().columns
    h = shutil.get_terminal_size().lines

    lines: list[str] = []
    if _status:
        lines.append(_paint(_fit(_status, w - 1), _BOLD))

    reserved = 1 + 2 * len(_active)  # barra de estado + 2 líneas por descarga
    space = max(0, h - reserved - 1)
    for text, color in list(_log)[-space:]:
        lines.append(_paint(_fit(text, w - 1), color))

    for p in list(_active.values()):
        lines.append(_paint(_fit(p.label, w - 1), _CYAN))
        bar_color = _COLOR_MAP.get(p.bar_color, _CYAN)
        lines.append(_paint(_fit(p.bar, w - 1), bar_color) if p.bar else "")

    return lines


def _render(force: bool = False):
    global _last_render
    if not _UI:
        return
    now = time.monotonic()
    if not force and now - _last_render < 0.1:
        return
    with _lock:
        _last_render = now
        try:
            lines = _build_frame()
            sys.stdout.write("\033[H" + "\n".join(lines) + "\033[J")
            sys.stdout.flush()
        except Exception:
            pass


# ── Mensajes ──────────────────────────────────────────────────────────

def _log_msg(text: str, color: str):
    if _UI:
        with _lock:
            _log.append((text, color))
        _render(force=True)
    else:
        _emit(_paint(text, color) if color else text)


def info(msg: str):
    _log_msg(msg, _CYAN)


def ok(msg: str):
    _log_msg(msg, _GREEN)


def err(msg: str):
    _log_msg(msg, _RED)


def warn(msg: str):
    _log_msg(msg, _YELLOW)


def note(msg: str):
    _log_msg(msg, "")


# ── Barra de estado ───────────────────────────────────────────────────

def update_status(*, total: int | None = None, active: int | None = None,
                  queue: int | None = None, last: str | None = None):
    global _status
    parts = ["TSR Downloader"]
    if total is not None:
        parts.append(f"Total: {total}")
    if active is not None:
        parts.append(f"Descargando: {active}")
    if queue is not None:
        parts.append(f"Cola: {queue}")
    if last:
        parts.append(f"Último: {last}")
    _status = " | ".join(parts)
    _render(force=True)


# ── Progreso de descargas ─────────────────────────────────────────────

class _Progress:
    def __init__(self, item_id: int, label: str):
        self.item_id = item_id
        self.label = label
        self.bar = ""
        self.bar_color = "cyan"

    def set_label(self, label: str):
        with _lock:
            self.label = label
        self._show()

    def message(self, text: str):
        with _lock:
            self.bar = text
            self.bar_color = "gray"
            if not _UI:
                self._emit_plain(f"{self.label} — {text}")
        _render()

    def update(self, pct: float, downloaded: float, total: float,
               speed: float, eta: float):
        bar = f"{build_bar(pct)} {pct:3.0f}%  {format_bytes(downloaded)}/{format_bytes(total)}  {format_speed(speed)}  ETA {format_eta(eta)}"
        with _lock:
            self.bar = bar
            self.bar_color = "cyan"
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


def start_progress(item_id: int, label: str) -> _Progress:
    p = _Progress(item_id, label)
    with _lock:
        _active[item_id] = p
    _render(force=True)
    return p


def finish_progress(item_id: int, text: str, color: str = "green"):
    """Finaliza (y elimina) una descarga activa, dejando su línea de resultado."""
    global _plain_cr
    with _lock:
        _active.pop(item_id, None)
        c = _COLOR_MAP.get(color, _GREEN)
        if _UI:
            _log.append((text, c))
        else:
            if _plain_cr:
                _plain_cr = False
                _emit("")
            _emit(_paint(text, c) if c else text)
    _render(force=True)


# ── Cierre ────────────────────────────────────────────────────────────

def shutdown(success: int, failed: int, last: str):
    """Desactiva el marco y muestra el resumen final en la terminal."""
    global _UI
    _UI = False
    w = shutil.get_terminal_size().columns
    sep = "─" * max(1, min(w - 2, 62))
    _emit("")
    _emit(_paint(sep, _GRAY))
    _emit(f"Resumen — descargados: {success} | fallidos: {failed}")
    if last:
        _emit(f"Último archivo: {last}")
    _emit(_paint(sep, _GRAY))