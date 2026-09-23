"""Tests de tolerancia a archivos de estado corruptos."""

import json
import re
from pathlib import Path

import pytest

from src import config as config_mod
from src.config import Config, load_history, load_session
from src.exceptions import ConfigError


def test_load_history_missing_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config_mod, "HISTORY_PATH", tmp_path / "history.json")
    assert load_history() == []


def test_load_history_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hist = tmp_path / "history.json"
    hist.write_text('[{"item_id": 1, "filename": "a.zip", "timestamp": 0}]', encoding="utf-8")
    monkeypatch.setattr(config_mod, "HISTORY_PATH", hist)
    history = load_history()
    assert len(history) == 1
    assert history[0]["item_id"] == 1


def test_load_history_corrupt_backs_up_and_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hist = tmp_path / "history.json"
    hist.write_text("{esto no es json", encoding="utf-8")
    monkeypatch.setattr(config_mod, "HISTORY_PATH", hist)

    with pytest.raises(ConfigError):
        load_history()

    assert not hist.exists()
    assert (tmp_path / "history.json.bak").exists()


def test_config_corrupt_backs_up_and_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text("no es json", encoding="utf-8")
    monkeypatch.setattr(config_mod, "CONFIG_PATH", cfg)
    monkeypatch.setattr(config_mod, "CONFIG_EXAMPLE_PATH", tmp_path / "no_existe.example")

    with pytest.raises(ConfigError):
        Config.load()

    assert (tmp_path / "config.json.bak").exists()


def test_load_session_corrupt_backs_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sess = tmp_path / "session.json"
    sess.write_text("{corrupto", encoding="utf-8")
    monkeypatch.setattr(config_mod, "SESSION_PATH", sess)

    assert load_session() is None
    assert (tmp_path / "session.json.bak").exists()


def test_example_credentials_are_treated_as_placeholders() -> None:
    """La plantilla en blanco debe seguir pidiendo credenciales.

    Si "" sale de _PLACEHOLDERS, la plantilla parecería "ya configurada".
    """
    example = json.loads(config_mod.CONFIG_EXAMPLE_PATH.read_text(encoding="utf-8"))
    cfg = Config(**example)
    assert cfg.needs_setup()


def test_readme_example_credentials_are_placeholders() -> None:
    """El ejemplo del README, si se pega tal cual, también pide credenciales.

    Si alguien cambia el ejemplo del README sin añadir los valores a
    _PLACEHOLDERS, la app intentaría iniciar sesión con ellos en vez de
    pedir los reales.
    """
    readme = (config_mod.CONFIG_EXAMPLE_PATH.parent / "README.md").read_text(encoding="utf-8")
    match = re.search(r'"tsr_email":\s*"([^"]*)"\s*,\s*"tsr_password":\s*"([^"]*)"', readme)
    assert match, "falta el bloque de ejemplo de config.json en README.md"
    cfg = Config(tsr_email=match.group(1), tsr_password=match.group(2))
    assert cfg.needs_setup()


def test_interactive_setup_masks_password(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """La contraseña se pide con getpass (oculta) y se guarda en config.json."""
    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "config.json")
    getpass_prompts: list[str] = []

    def fake_input(prompt: str = "") -> str:
        return "user@example.com"

    def fake_getpass(prompt: str = "") -> str:
        getpass_prompts.append(prompt)
        return "secreto-secreto"

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(config_mod.getpass, "getpass", fake_getpass)

    cfg = Config()
    cfg.interactive_setup()

    assert cfg.tsr_password == "secreto-secreto"
    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert saved["tsr_password"] == "secreto-secreto"
    assert any("Contraseña" in p for p in getpass_prompts)
