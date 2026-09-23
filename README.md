# TSR Downloader

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

Descarga contenido de The Sims Resource copiando enlaces. La aplicación supervisa tu portapapeles y descarga automáticamente en segundo plano.

## Características

- **Descarga por portapapeles** — copia un enlace y se descarga solo.
- **Inicio de sesión automático** — sin captcha, sin esperas de 15 segundos.
- **Cinco descargas simultáneas** — descarga varios archivos a la vez.
- **Historial** — guarda las diez últimas descargas.
- **Reanudación** — retoma las descargas interrumpidas desde donde quedaron.
- **Dependencias** — descarga automáticamente los archivos requeridos.

## Requisitos

- **Python 3.10 o superior**.
- Cuenta gratuita en The Sims Resource.

## Instalación y uso

La entrada universal es `run.py` — funciona en Linux, macOS y Windows, solo con Python:

```sh
python run.py setup    # crea .venv, instala dependencias y genera config.json si falta
python run.py          # ejecuta la aplicación (hace setup automático si falta todo)
```

`python run.py` basta en una máquina nueva: se autoprepara la primera vez. Otros comandos:

```sh
python run.py run      # igual que 'python run.py'
python run.py clean    # elimina .venv y archivos temporales (no toca config.json ni descargas)
python run.py help     # muestra la ayuda
```

> **Si mueves el repositorio a otra máquina:** el `.venv` es específico de cada equipo (contiene rutas absolutas). Ejecuta `python run.py` o `python run.py setup` una vez en la máquina nueva; se recreará todo el entorno. `config.json` se regenera desde la plantilla si falta.

## Configuración

La primera vez que ejecutes `python run.py setup` se genera `config.json` a partir de `config.json.example` automáticamente. Si lo prefieres, cópialo a mano:

```sh
cp config.json.example config.json
```

En Windows (cmd):

```bat
copy config.json.example config.json
```

Luego edita `config.json` (en la raíz del proyecto):

```json
{
    "download_directory": "./downloads",
    "max_concurrent": 5,
    "history_size": 10,
    "tsr_email": "tu_correo",
    "tsr_password": "tu_contraseña",
    "use_nerd_icons": true
}
```

**Importante:** añade tu correo y contraseña de TSR para el inicio de sesión automático. Sin ello, la aplicación no funciona.

**Privacidad:** `config.json`, `session.json` e `history.json` no se suben a Git (están en `.gitignore`). Solo se publica la plantilla `config.json.example`.

**Iconos (Nerd Font):** la terminal no puede informar de la fuente que usas, así que decide la configuración: con `use_nerd_icons: true` se usan iconos de Nerd Font (instala antes una fuente parcheada, p. ej. JetBrainsMono Nerd Font); con `false`, los símbolos Unicode estándar (↓, ✓, ✗).

## Uso

1. Ejecuta `python run.py`.
2. Abre The Sims Resource en el navegador.
3. Copia enlaces de descarga.
4. Los archivos se descargan solos.

Se guardan en la carpeta configurada (por defecto, `./downloads/`).

Si una descarga falla, se reintenta automáticamente a los 30 s (hasta 3 intentos).

## Interfaz

La aplicación usa una interfaz TUI basada en Textual con tema cyberpunk:

- **TSR Downloader** en magenta/rosado en la primera línea.
- Contadores en cian sobre fondo azul oscuro.
- Cada descarga ocupa una fila permanente con barra de progreso en cian.
- Spinners animados durante la descarga.
- Bordes sutiles que separan las secciones de avisos y descargas.
- Cada aviso lleva un símbolo de nivel (✗ error, ⚠ aviso, ✓ correcto, • info): la severidad se lee sin depender del color.

### Atajos de teclado

| Tecla | Acción |
|-------|--------|
| `q` | Cerrar la aplicación |
| `Ctrl+C` | Cerrar la aplicación |

Al cerrar se muestra un resumen con el número de descargas completadas y fallidas.
La cola pendiente se cancela al salir; las descargas en curso terminan solas.

Si la salida no es una terminal, o defines `NO_COLOR=1` (también `TERM=dumb`), se usa el modo plano: sin colores ANSI y con el progreso anunciado en texto cada 25 %.

## Estructura del proyecto

```
tsr-downloader/
├── src/
│   ├── main.py          ← Punto de entrada: main() y bucle del portapapeles
│   ├── manager.py       ← DownloadManager: cola, activos, historial, contadores
│   ├── session.py       ← Inicio de sesión GraphQL (sin captcha)
│   ├── downloader.py    ← Descarga con reanudación y progreso en vivo
│   ├── url_parser.py    ← Análisis y validación de URL
│   ├── config.py        ← Configuración y persistencia (config/historial/sesión)
│   ├── exceptions.py    ← Excepciones de dominio
│   └── display.py       ← Backends de UI: TUI (Textual) y modo plano
├── tests/
│   ├── test_url_parser.py
│   └── test_display.py
├── run.py               ← Entrada universal: setup, run, clean, help
├── pyproject.toml       ← Configuración de ruff, mypy y pytest
├── requirements.txt     ← Dependencias de ejecución
├── requirements-dev.txt ← Herramientas de desarrollo
├── config.json.example  ← Plantilla de configuración (se sube a Git)
├── .gitignore
├── .venv/
└── README.md
```

> `config.json`, `session.json`, `history.json` y `logs.log` se generan en la raíz y no se suben a Git.

## Créditos y licencia

Basado en [The-Sims-Resource-Downloader](https://github.com/Xientraa/The-Sims-Resource-Downloader)
de **Xientraa**, publicado bajo licencia MIT — `Copyright (c) 2023 Xientraa`.
De ahí proceden el flujo de descarga por ticket y la detección de dependencias;
el resto (inicio de sesión GraphQL, TUI, cola con reintentos y tests) es original
de este repositorio.

Este proyecto está bajo la [licencia MIT](LICENSE) — `Copyright (c) 2026 joseguerram`.

**Aviso:** no estoy afiliado a Electronic Arts, Maxis ni The Sims Resource. Esta
herramienta es un proyecto personal no oficial; úsala bajo tu propia
responsabilidad y respeta los términos de servicio de TSR.

## Desarrollo

Herramientas de calidad (opcionales), con el entorno virtual activado:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest                       # tests
python -m ruff check src tests run.py  # linter
python -m ruff format src tests run.py # formateador
python -m mypy src                     # comprobación de tipos
```