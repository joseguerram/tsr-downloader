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

        # Pedir credenciales si el template tiene placeholders
        try:
            _prompt_credentials(cfg)
        except SystemExit:
            return
    else:
        print("    -> config.json ya existe, sin cambios")

    print()
    print("Instalación completa. Ejecuta 'python run.py run'.")


def _prompt_credentials(cfg_path):
    """Pide email y contraseña si están vacíos o son placeholder."""
    import json as _json
    with open(cfg_path) as f:
        data = _json.load(f)

    placeholders = {"tu_correo", "tu_contraseña", "tu_email", ""}
    email = data.get("tsr_email", "").strip()
    password = data.get("tsr_password", "").strip()

    if email not in placeholders and password not in placeholders:
        return

    print()
    print("  Configuración de TSR Downloader")
    print("  Se necesitan el email y la contraseña de tu cuenta en TSR.")
    print()

    if email in placeholders:
        data["tsr_email"] = input("  Email de tu cuenta TSR: ").strip()
    else:
        print(f"  Email: {email} (ya configurado)")

    if password in placeholders:
        data["tsr_password"] = input("  Contraseña de tu cuenta TSR: ").strip()
    else:
        print("  Contraseña: ****** (ya configurada)")

    if not data["tsr_email"] or not data["tsr_password"]:
        print()
        print("  ✗ Email y contraseña son obligatorios.")
        print("  Edita config.json manualmente y vuelve a intentar.")
        raise SystemExit(1)

    with open(cfg_path, "w") as f:
        _json.dump(data, f, indent=4)
    print()
    print(f"  ✓ Configuración guardada en config.json")


def run():
    if not os.path.exists(PYTHON):
        print("Entorno no preparado. Ejecutando setup automático...")
        setup()
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
