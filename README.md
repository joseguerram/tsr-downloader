# TSR Downloader

Descarga contenido de The Sims Resource copiando enlaces. La aplicación supervisa tu portapapeles y descarga automáticamente en segundo plano.

## Características

- **Descarga por portapapeles** — copia un enlace y se descarga solo.
- **Inicio de sesión automático** — sin captcha, sin esperas de 15 segundos.
- **Cinco descargas simultáneas** — descarga varios archivos a la vez.
- **Historial** — guarda las diez últimas descargas.
- **Reanudación** — retoma las descargas interrumpidas desde donde quedaron.
- **Dependencias** — descarga automáticamente los archivos requeridos.

## Configuración

Copia la plantilla y edita el archivo resultante:

```sh
cp config.json.example config.json
```

En Windows:

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

## Instalación

```sh
make setup    # crea el venv, instala dependencias y genera config.json si falta
```

`make setup` crea `config.json` a partir de `config.json.example` automáticamente si no existe. Después edítalo con tu cuenta y ejecuta:

```sh
make run      # ejecuta la aplicación
```

En Windows nativo usa **Git Bash** o **WSL** para que `make` esté disponible.

## Uso

1. Ejecuta `make run`.
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
├── Makefile             ← make setup / make run / make clean / make help
├── config.json.example  ← Plantilla de configuración (se sube a Git)
├── .gitignore
├── .venv/
├── requirements.txt
└── README.md
```

> `config.json`, `session.json`, `history.json` y `logs.log` se generan en la raíz y no se suben a Git.

## Requisitos

- Python 3.10 o superior.
- Cuenta gratuita en The Sims Resource.
