#!/usr/bin/env python3
"""Lanzador multiplataforma de TSR Downloader.

Uso:
    python run.py setup   → crea .venv, instala dependencias y configuración
    python run.py run     → ejecuta la aplicación (setup automático si falta)
    python run.py clean   → elimina el entorno y los archivos temporales
    python run.py help    → muestra esta ayuda

No requiere ninguna herramienta externa: solo Python 3.10+.
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable

from src.config import CONFIG_EXAMPLE_PATH, CONFIG_PATH, Config
from src.exceptions import ConfigError

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(ROOT, ".venv")
PYTHON = (
    os.path.join(VENV_DIR, "Scripts", "python.exe")
    if sys.platform == "win32"
    else os.path.join(VENV_DIR, "bin", "python")
)


def _run(cmd: list[str]) -> None:
    print("  » " + " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def setup() -> None:
    print("==> Entorno virtual: .venv")
    if not os.path.exists(PYTHON):
        _run([sys.executable, "-m", "venv", ".venv"])
    else:
        print("    -> .venv ya existe")

    print("==> Instalando dependencias...")
    _run([PYTHON, "-m", "pip", "install", "--upgrade", "pip", "-q"])
    _run([PYTHON, "-m", "pip", "install", "-r", "requirements.txt"])

    print("==> Configuración...")
    if not CONFIG_PATH.exists():
        if CONFIG_EXAMPLE_PATH.exists():
            shutil.copyfile(CONFIG_EXAMPLE_PATH, CONFIG_PATH)
            print("    -> config.json generado desde config.json.example")
        else:
            print("    -> config.json.example no encontrado; crea config.json a mano")
    else:
        print("    -> config.json ya existe, sin cambios")

    # Pide credenciales si siguen vacías o con valores de ejemplo.
    # Un SystemExit(1) de interactive_setup se propaga con su código de salida.
    try:
        config = Config.load()
    except ConfigError as e:
        print(f"  ⚠ {e}")
        config = Config()
    if config.needs_setup():
        config.interactive_setup()

    print()
    print("Instalación completa. Ejecuta 'python run.py run'.")


def run() -> None:
    if not os.path.exists(PYTHON):
        print("Entorno no preparado. Ejecutando setup automático...")
        setup()
    try:
        proc = subprocess.run([PYTHON, "-m", "src.main"], cwd=ROOT)
    except KeyboardInterrupt:
        # Ctrl+C: la aplicación ya imprime su resumen de cierre.
        sys.exit(130)
    sys.exit(proc.returncode)


def clean() -> None:
    print("==> Eliminando .venv...")
    shutil.rmtree(VENV_DIR, ignore_errors=True)

    print("==> Eliminando cachés...")
    for dirpath, dirnames, _ in os.walk(ROOT):
        if "__pycache__" in dirnames:
            shutil.rmtree(os.path.join(dirpath, "__pycache__"), ignore_errors=True)

    log = os.path.join(ROOT, "logs.log")
    if os.path.exists(log):
        os.remove(log)

    print("Listo. No se tocaron config.json ni la carpeta de descargas.")


def help_() -> None:
    print(__doc__)


COMMANDS: dict[str, Callable[[], None]] = {
    "setup": setup,
    "run": run,
    "start": run,
    "clean": clean,
    "help": help_,
}


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command not in COMMANDS:
        print(f"Comando desconocido: {command}\n")
        help_()
        sys.exit(1)
    COMMANDS[command]()


if __name__ == "__main__":
    main()
