"""Tests del bucle del portapapeles ante fallos del sistema."""

import threading
import time

import pyperclip
import pytest

import src.display as display
from src.config import Config
from src.main import AppState


def test_clipboard_loop_survives_missing_clipboard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin mecanismo de portapapeles se avisa una vez y el bucle sigue vivo."""

    def boom() -> str:
        raise pyperclip.PyperclipException("sin mecanismo de portapapeles")

    monkeypatch.setattr(pyperclip, "paste", boom)
    display._ui.log.clear()

    state = AppState(Config())
    thread = threading.Thread(target=state._clipboard_loop, daemon=True)
    thread.start()
    time.sleep(0.3)
    state.stop.set()
    thread.join(timeout=5)
    state.manager.close()

    assert not thread.is_alive()
    messages = [text for text, _color in display._ui.log]
    assert any("Portapapeles" in text for text in messages)
