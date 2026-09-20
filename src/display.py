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

# ── Animación spinner (giratorio, distinto a la barra) ─────────────────
_SPINNERS = ["◜", "◝", "◞", "◟"]
_spin_idx = 0

# ── Estado global ──────────────────────────────────────────────────────
_COLORS = True
_UI = False
_last_render = 0.0
_mode = "unicode"
_plain_cr = False
_tick_timer: threading.Timer | None = None

_lock = threading.RLock()

_status = ""
_log: deque = deque(maxlen=200)
_active: dict[int, "_Progress"] = {}
_session_ok = 0
_session_failed = 0
_member_info = ""
_total_files = 0

_ICON_SETS = {
    "download": ("\uf019 ", "↓ ", "  "),
    "ok":       ("\uf00c ", "✓ ", "✓ "),
    "error":    ("\uf00d ", "✗ ", "✗ "),
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
    global _COLORS, _UI, _mode

    is_tty = sys.stdout.isatty()

    if not is_tty:
        _COLORS = False
        _UI = False
    elif os.name == "nt":
        vt_ok = _enable_windows_vt()
        if vt_ok:
            _UI = True
        else:
            try:
                import colorama
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


# ── Animación spinner ─────────────────────────────────────────────────

def _start_tick():
    """Arranca el temporizador que anima los spinners (si no corre ya)."""
    global _tick_timer
    if _tick_timer is not None:
        return

    def _do_tick():
        global _tick_timer, _spin_idx
        _spin_idx += 1
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


# ── Salida ────────────────────────────────────────────────────────────

def _emit(text: str, end: str = "\n"):
    sys.stdout.write(text + end)
    sys.stdout.flush()


# ── Marco ─────────────────────────────────────────────────────────────

def _get_bar_text(p: "_Progress", width: int) -> str:
    """Texto de barra/spinner de un progreso activo (sin contar el label)."""
    if p.bar_kind == "bar":
        return p.bar

    spin = _SPINNERS[_spin_idx % len(_SPINNERS)]

    if p.message_text:
        msg = p.message_text
        if _COLORS:
            return f"{spin}  {_DIM}{msg}{_RESET}"
        return f"{spin}  {msg}"

    return spin


def _build_frame() -> list:
    w = shutil.get_terminal_size().columns
    h = shutil.get_terminal_size().lines
    active_items = list(_active.values())
    lines: list[str] = []

    # ── 1. Barra de estado (siempre arriba) ──────────────────────────
    if _status:
        txt = _status
        if len(txt) > w - 1:
            txt = txt[: w - 1] + "…"
        lines.append(_paint(txt, _BOLD))

    # ── 1b. Aviso temporal ───────────────────────────────────────────
    if _flash and time.monotonic() < _flash_until:
        lines.append(_paint(_fit(_flash, w - 1), _COLOR_MAP.get(_flash_color, _GREEN)))

    # ── 2. Separador (si hay activos) ───────────────────────────────
    if active_items:
        lines.append(_paint("━" * max(1, min(w - 1, 62)), _GRAY))

    # ── 4. Descargas activas ────────────────────────────────────────
    for p in active_items:
        suffix = _get_bar_text(p, w)

        if p.bar_kind == "spinner":
            # Una sola línea: spinner giratorio (sin números ni %) al lado del nombre
            if p.label:
                lines.append(_paint(_fit(f"{p.label}  {suffix}", w - 1), _CYAN))
            else:
                lines.append(_paint(_fit(f"   {suffix}", w - 1), _CYAN))
        else:
            # Nombre + barra de progreso (2 líneas)
            lines.append(_paint(_fit(p.label or "", w - 1), _CYAN))
            bar_color = _COLOR_MAP.get(p.bar_color, _CYAN)
            lines.append(_paint(_fit(suffix, w - 1), bar_color))

    if len(lines) > h - 1:
        lines = lines[: h - 1]

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
    with _lock:
        _log.append((text, color))
    if not _UI:
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


# ── Aviso temporal ────────────────────────────────────────────────────

_flash = ""
_flash_until = 0.0
_flash_color = "green"


def flash(msg: str, seconds: float = 6.0, color: str = "green"):
    global _flash, _flash_until, _flash_color
    with _lock:
        _flash = msg
        _flash_until = time.monotonic() + seconds
        _flash_color = color
        if not _UI:
            c = _COLOR_MAP.get(color)
            _emit(_paint(msg, c) if c else msg)
    _render(force=True)
    t = threading.Timer(seconds, _clear_flash)
    t.daemon = True
    t.start()


def _clear_flash():
    global _flash
    with _lock:
        if _flash:
            _flash = ""
    _render(force=True)


# ── Barra de estado ───────────────────────────────────────────────────

def set_session_info(member_id: str = "", authenticated: bool = True):
    global _member_info
    if authenticated and member_id:
        _member_info = f"Miembro #{member_id}"
    else:
        _member_info = "Anónimo"
    _render(force=True)


def update_status(*, total: int | None = None, active: int | None = None,
                  queue: int | None = None, last: str | None = None,
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
    if last:
        parts.append(f"Último: {last}")
    _status = " | ".join(parts)
    _render(force=True)


# ── Progreso de descargas ─────────────────────────────────────────────

class _Progress:
    def __init__(self, item_id: int):
        self.item_id = item_id
        self.label: str | None = None       # None = "preparando descarga"
        self.bar: str = ""
        self.bar_color: str = "cyan"
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
            self.bar_color = "gray"
            if not _UI:
                self._emit_plain(f"{self.label or ''} — {text}")
        _start_tick()
        _render()

    def update(self, pct: float, downloaded: float, total: float,
               speed: float, eta: float):
        bar = f"{build_bar(pct)} {pct:3.0f}%  {format_bytes(downloaded)}/{format_bytes(total)}  {format_speed(speed)}  ETA {format_eta(eta)}"
        with _lock:
            self.bar = bar
            self.bar_color = "cyan"
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
    _render(force=True)
    return p


def finish_progress(item_id: int, name: str, color: str = "green"):
    global _plain_cr
    with _lock:
        _active.pop(item_id, None)
        c = _COLOR_MAP.get(color, _GREEN)
        ic = icon("error") if color == "red" else icon("ok")

        if not _UI:
            if _plain_cr:
                _plain_cr = False
                _emit("")
            verb = "Error:" if color == "red" else "Guardado:"
            text = f"{ic}{verb} {name}"
            _emit(_paint(text, c) if c else text)

    if not any(p.bar_kind == "spinner" for p in _active.values()):
        _stop_tick()
    _render(force=True)


# ── Cierre ────────────────────────────────────────────────────────────

def shutdown(success: int, failed: int, last: str):
    global _UI
    _stop_tick()
    _UI = False
    w = shutil.get_terminal_size().columns
    sep = "─" * max(1, min(w - 2, 62))
    _emit("")
    _emit(_paint(sep, _GRAY))
    _emit(f"Resumen — descargados: {success} | fallidos: {failed}")
    if last:
        _emit(f"Último archivo: {last}")
    _emit(_paint(sep, _GRAY))