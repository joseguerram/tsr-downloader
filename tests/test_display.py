"""Tests de las funciones de formato de src.display."""

import time

import pytest

import src.display as display
from src.display import build_bar, format_bytes, format_eta, format_speed, icon


def test_format_bytes() -> None:
    assert format_bytes(0) == "0 B"
    assert format_bytes(1023) == "1023 B"
    assert format_bytes(1024) == "1.0 KB"
    assert format_bytes(1536) == "1.5 KB"
    assert format_bytes(1024**2) == "1.0 MB"


def test_format_speed() -> None:
    assert format_speed(1024) == "1.0 KB/s"


def test_format_eta() -> None:
    assert format_eta(None) == ""
    assert format_eta(45) == "45s"
    assert format_eta(75) == "1m 15s"


def test_build_bar() -> None:
    assert build_bar(50, width=4) == "██░░"
    assert build_bar(0, width=4) == "░░░░"
    assert build_bar(100, width=4) == "████"
    # Valores fuera de rango se recortan
    assert build_bar(-10, width=4) == "░░░░"
    assert build_bar(200, width=4) == "████"


def test_icon_unicode() -> None:
    assert icon("ok") == "✓"
    assert icon("error") == "✗"
    assert icon("download") == "↓"


def test_icon_unicode_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(display, "_mode", "unicode")
    assert display.icon("vip") == "■"


def test_icon_nerd_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(display, "_mode", "nerd")
    assert display.icon("download") == "\uf019"  # fa-download
    assert display.icon("ok") == "\uf058"  # fa-check_circle
    assert display.icon("error") == "\uf057"  # fa-times_circle
    assert display.icon("queue") == "\uf252"  # fa-hourglass-half
    assert display.icon("vip") == "\uf005"  # fa-star


def test_init_uses_unicode_when_not_a_tty() -> None:
    # stdout en pytest no es TTY: modo plano con iconos unicode, aunque
    # se pida Nerd Font.
    display.init(nerd_requested=True)
    assert display._mode == "unicode"


def test_log_symbols_do_not_depend_on_color() -> None:
    backend = display.PlainBackend()
    backend.warn("aviso")
    backend.err("fallo")
    backend.info("dato")
    # El log es un deque(maxlen=3): cabe exactamente un mensaje por color.
    texts = [text for text, _color in backend.log]
    assert texts[0].startswith("⚠ ")
    assert texts[1].startswith("✗ ")
    assert texts[2].startswith("• ")

    backend.log.clear()
    backend.note("nota")
    assert [text for text, _color in backend.log] == ["nota"]

    # La guarda evita símbolos duplicados si un llamador ya prefija.
    backend.warn("⚠ ya viene prefijado")
    assert backend.log[-1][0].count("⚠") == 1


def test_plain_progress_announces_quarters(capsys: pytest.CaptureFixture[str]) -> None:
    backend = display.PlainBackend()
    progress = backend.start_progress(7, "file.zip")

    progress.update(10, 1, 10, 100.0, 9.0)
    assert capsys.readouterr().out == ""  # sin anuncio antes del 25 %

    progress.update(30, 3, 10, 100.0, 7.0)
    first = capsys.readouterr().out
    assert "file.zip" in first and "30%" in first

    progress.update(35, 4, 10, 100.0, 6.0)
    assert capsys.readouterr().out == ""  # mismo cuartil: sin spam

    progress.update(80, 8, 10, 100.0, 2.0)
    assert "80%" in capsys.readouterr().out

    progress.message("esperando")  # spinner: no se anuncia en plano
    assert capsys.readouterr().out == ""


def test_init_respects_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    display.init(nerd_requested=True)
    assert display._colors is False
    assert isinstance(display._ui, display.PlainBackend)


def test_tui_bar_sync_throttles_bursts(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = display.TUIBackend()
    progress = backend.start_progress(1, "file.zip")
    calls: list[object] = []
    monkeypatch.setattr(backend, "_call", lambda fn, *a, **k: calls.append(fn))

    # Volcada hace un instante: el siguiente update se suprime.
    progress._last_sync = time.monotonic()
    progress.update(50, 5, 10, 100.0, 5.0)
    assert calls == []

    # Pasado el intervalo: vuelve a volcarse.
    progress._last_sync = time.monotonic() - display._BAR_SYNC_MIN_INTERVAL - 0.01
    progress.update(60, 6, 10, 100.0, 4.0)
    assert len(calls) == 1

    # Los mensajes (spinner) nunca se limitan.
    progress.message("esperando")
    progress.message("esperando aún")
    assert len(calls) == 3
