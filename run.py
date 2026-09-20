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

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(ROOT, ".venv")
PYTHON = (
    os.path.join(VENV_DIR, "Scripts", "python.exe")
    if sys.platform == "win32"
    else os.path.join(VENV_DIR, "bin", "python")
)


def _run(cmd):
    print("  » " + " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def setup():
    print("==> Entorno virtual: .venv")
    if not os.path.exists(PYTHON):
        _run([sys.executable, "-m", "venv", ".venv"])
    else:
        print("    -> .venv ya existe")

    print("==> Instalando dependencias...")
    _run([PYTHON, "-m", "pip", "install", "--upgrade", "pip", "-q"])
    _run([PYTHON, "-m", "pip", "install", "-r", "requirements.txt"])

    print("==> Configuración...")
    cfg = os.path.join(ROOT, "config.json")
    example = os.path.join(ROOT, "config.json.example")
    if not os.path.exists(cfg):
        if os.path.exists(example):
            shutil.copyfile(example, cfg)
            print("    -> config.json generado desde config.json.example")
        else:
            print("    -> config.json.example no encontrado; crea config.json a mano")
    else:
        print("    -> config.json ya existe, sin cambios")

    print()
    print("Instalación completa. Edita config.json y ejecuta 'python run.py run'.")


def run():
    if not os.path.exists(PYTHON):
        print("Entorno no preparado. Ejecutando setup automático...")
        setup()
    print("==> TSR Downloader")
    try:
        proc = subprocess.run([PYTHON, "-m", "src.main"], cwd=ROOT)
    except KeyboardInterrupt:
        # Ctrl+C: la aplicación ya imprime su resumen de cierre.
        sys.exit(130)
    sys.exit(proc.returncode)


def clean():
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


def help_():
    print(__doc__)


COMMANDS = {
    "setup": setup,
    "run": run,
    "start": run,
    "clean": clean,
    "help": help_,
}


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command not in COMMANDS:
        print(f"Comando desconocido: {command}\n")
        help_()
        sys.exit(1)
    COMMANDS[command]()


if __name__ == "__main__":
    main()