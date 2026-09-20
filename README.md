# TSR Downloader

Descarga contenido de The Sims Resource copiando enlaces. La aplicación supervisa tu portapapeles y descarga automáticamente en segundo plano.

## Características

- **Descarga por portapapeles** — copia un enlace y se descarga solo.
- **Inicio de sesión automático** — sin captcha, sin esperas de 15 segundos.
- **Cinco descargas simultáneas** — descarga varios archivos a la vez.
- **Historial** — guarda las diez últimas descargas.
- **Reanudación** — retoma las descargas interrumpidas desde donde quedaron.
- **Dependencias** — descarga automáticamente los archivos requeridos.

## Requisitos

- Solo **Python 3.10 o superior**. No necesitas `make` ni nada más.
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

Si tu sistema tiene `make`, puedes usar los atajos equivalentes (llaman al mismo `run.py`):

```sh
make setup
make run
make clean
make help
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

**Iconos (Nerd Font):** la aplicación detecta automáticamente si tu terminal usa una fuente Nerd Font (p. ej. JetBrainsMono Nerd Font). Si la encuentra, muestra iconos de esa fuente; si no, usa símbolos Unicode estándar (↓, ✓, ✗). Pon `use_nerd_icons` en `false` para desactivar los iconos por completo.

## Uso

1. Ejecuta `python run.py` (o `make run`).
2. Abre The Sims Resource en el navegador.
3. Copia enlaces de descarga.
4. Los archivos se descargan solos.

Se guardan en la carpeta configurada (por defecto, `./downloads/`).

## Estructura del proyecto

```
tsr-downloader/
├── src/
│   ├── main.py          ← Punto de entrada y bucle del portapapeles
│   ├── session.py       ← Inicio de sesión GraphQL (sin captcha)
│   ├── downloader.py    ← Descarga con reanudación y grupo de hilos
│   ├── url_parser.py    ← Análisis y validación de URL
│   ├── config.py        ← Rutas y carga de la configuración
│   └── display.py       ← Interfaz de consola (colores y progreso)
├── run.py               ← Entrada universal (setup / run / clean / help) — no requiere make
├── Makefile             ← Atajo opcional para quienes tengan make
├── config.json.example  ← Plantilla de configuración (se sube a Git)
├── .gitignore
├── .venv/
├── requirements.txt
└── README.md
```

> `config.json`, `session.json`, `history.json` y `logs.log` se generan en la raíz y no se suben a Git.