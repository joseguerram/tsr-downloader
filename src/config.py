"""Carga y persistencia de la configuración, el historial y la sesión."""

from __future__ import annotations

import getpass
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from .exceptions import ConfigError

logger = logging.getLogger(__name__)

# Los archivos de configuración y estado viven en la raíz del proyecto
# (fuera de src/) para separarlos del código y poder ignorarlos en Git.
_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = _ROOT / "config.json"
CONFIG_EXAMPLE_PATH = _ROOT / "config.json.example"
HISTORY_PATH = _ROOT / "history.json"
SESSION_PATH = _ROOT / "session.json"

_PLACEHOLDERS = {"tu_correo", "tu_contraseña", "tu_email", ""}


class HistoryEntry(TypedDict):
    """Una entrada del historial de descargas."""

    item_id: int
    filename: str
    timestamp: float


def _ensure_config() -> None:
    """Crea config.json a partir de la plantilla si no existe."""
    if CONFIG_PATH.exists() or not CONFIG_EXAMPLE_PATH.exists():
        return
    CONFIG_PATH.write_text(CONFIG_EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    logger.info("Creado config.json a partir de config.json.example")


def _write_json(path: Path, data: Any, indent: int | None = None) -> None:
    """Escribe JSON de forma atómica (archivo temporal + renombrado)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=indent), encoding="utf-8")
    tmp.replace(path)


def _backup_corrupt(path: Path, error: object) -> Path | None:
    """Aparta un archivo de estado ilegible para no perder su rastro."""
    backup = path.with_name(path.name + ".bak")
    try:
        path.replace(backup)
    except OSError as e:
        logger.warning(f"No se pudo apartar {path.name}: {e}")
        return None
    logger.warning(f"{path.name} ilegible ({error}); copia en {backup.name}")
    return backup


@dataclass
class Config:
    download_directory: str = "./downloads"
    max_concurrent: int = 5
    history_size: int = 10
    tsr_email: str = ""
    tsr_password: str = ""
    use_nerd_icons: bool = True

    @classmethod
    def load(cls) -> Config:
        _ensure_config()
        if not CONFIG_PATH.exists():
            return cls()
        try:
            with CONFIG_PATH.open(encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("el contenido no es un objeto JSON")
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (ValueError, TypeError, OSError) as e:
            _backup_corrupt(CONFIG_PATH, e)
            raise ConfigError(
                "config.json estaba corrupto; se usan los valores por defecto "
                "y se volverá a pedir la configuración."
            ) from e

    def needs_setup(self) -> bool:
        """Indica si faltan credenciales obligatorias."""
        return self.tsr_email.strip() in _PLACEHOLDERS or self.tsr_password.strip() in _PLACEHOLDERS

    def interactive_setup(self) -> None:
        """Pide al usuario las credenciales que faltan y guarda el archivo."""
        print()
        print("  Configuración de TSR Downloader")
        print("  Se necesitan el email y la contraseña de tu cuenta en TSR.")
        print()

        if self.tsr_email.strip() in _PLACEHOLDERS:
            self.tsr_email = input("  Email de tu cuenta TSR: ").strip()
        else:
            print(f"  Email: {self.tsr_email} (ya configurado)")

        if self.tsr_password.strip() in _PLACEHOLDERS:
            self.tsr_password = getpass.getpass("  Contraseña de tu cuenta TSR: ").strip()
        else:
            print("  Contraseña: ****** (ya configurada)")

        if not self.tsr_email or not self.tsr_password:
            print()
            print("  ✗ Email y contraseña son obligatorios.")
            print("  Edita config.json manualmente y vuelve a intentar.")
            raise SystemExit(1)

        self.save()
        print()
        print(f"  ✓ Configuración guardada en {CONFIG_PATH.name}")

    def save(self) -> None:
        _write_json(CONFIG_PATH, self.__dict__, indent=4)


def load_history() -> list[HistoryEntry]:
    if not HISTORY_PATH.exists():
        return []
    try:
        with HISTORY_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("el contenido no es una lista")
        return data
    except (ValueError, OSError) as e:
        backup = _backup_corrupt(HISTORY_PATH, e)
        detail = f"; copia en {backup.name}" if backup else ""
        raise ConfigError(
            f"history.json estaba corrupto{detail}; el historial empieza vacío."
        ) from e


def save_history(history: list[HistoryEntry]) -> None:
    _write_json(HISTORY_PATH, history, indent=2)


def load_session() -> dict[str, Any] | None:
    if not SESSION_PATH.exists():
        return None
    try:
        with SESSION_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (ValueError, OSError) as e:
        # La sesión se regenera sola al volver a iniciar sesión.
        _backup_corrupt(SESSION_PATH, e)
        return None


def save_session(data: dict[str, Any]) -> None:
    _write_json(SESSION_PATH, data)
