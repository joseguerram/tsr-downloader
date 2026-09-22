import json
import os
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Los archivos de configuración y estado viven en la raíz del proyecto
# (fuera de src/) para separarlos del código y poder ignorarlos en Git.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(_ROOT, "config.json")
CONFIG_EXAMPLE_PATH = os.path.join(_ROOT, "config.json.example")
HISTORY_PATH = os.path.join(_ROOT, "history.json")
SESSION_PATH = os.path.join(_ROOT, "session.json")


def _ensure_config():
    """Crea config.json a partir de la plantilla si no existe."""
    if os.path.exists(CONFIG_PATH):
        return
    if os.path.exists(CONFIG_EXAMPLE_PATH):
        with open(CONFIG_EXAMPLE_PATH) as src, open(CONFIG_PATH, "w") as dst:
            dst.write(src.read())
        logger.info("Creado config.json a partir de config.json.example")


_PLACEHOLDERS = {"tu_correo", "tu_contraseña", "tu_email", ""}


@dataclass
class Config:
    download_directory: str = "./downloads"
    max_concurrent: int = 5
    history_size: int = 10
    tsr_email: str = ""
    tsr_password: str = ""
    use_nerd_icons: bool = True

    @classmethod
    def load(cls) -> "Config":
        _ensure_config()
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH) as f:
                data = json.load(f)
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        return cls()

    def needs_setup(self) -> bool:
        """Indica si faltan credenciales obligatorias."""
        return (
            self.tsr_email.strip() in _PLACEHOLDERS
            or self.tsr_password.strip() in _PLACEHOLDERS
        )

    def interactive_setup(self) -> None:
        """Pide al usuario las credenciales que faltan y guarda el archivo."""
        print()
        print("Configuración de TSR Downloader")
        print("  Se necesitan el email y la contraseña de tu cuenta en TSR.")
        print()

        if self.tsr_email.strip() in _PLACEHOLDERS:
            self.tsr_email = input("  Email de tu cuenta TSR: ").strip()
        else:
            print(f"  Email: {self.tsr_email} (ya configurado)")

        if self.tsr_password.strip() in _PLACEHOLDERS:
            self.tsr_password = input("  Contraseña de tu cuenta TSR: ").strip()
        else:
            print("  Contraseña: ****** (ya configurada)")

        if not self.tsr_email or not self.tsr_password:
            print()
            print("  ✗ Email y contraseña son obligatorios.")
            print("  Edita config.json manualmente y vuelve a intentar.")
            raise SystemExit(1)

        self.save()
        print()
        print(f"  ✓ Configuración guardada en {os.path.basename(CONFIG_PATH)}")

    def save(self):
        with open(CONFIG_PATH, "w") as f:
            json.dump(self.__dict__, f, indent=4)


def load_history() -> list[dict]:
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH) as f:
            return json.load(f)
    return []


def save_history(history: list[dict]):
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)


def load_session() -> dict | None:
    if os.path.exists(SESSION_PATH):
        try:
            with open(SESSION_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, KeyError):
            pass
    return None


def save_session(data: dict):
    with open(SESSION_PATH, "w") as f:
        json.dump(data, f)
