"""Excepciones de dominio de TSR Downloader.

Todas heredan de :class:`TSRError` para que la capa de presentación pueda
distinguir los errores esperados de la aplicación de los fallos reales.
"""

from __future__ import annotations


class TSRError(Exception):
    """Error base de la aplicación."""


class ConfigError(TSRError):
    """Problema al cargar o guardar la configuración."""


class SessionError(TSRError):
    """Error al iniciar o validar la sesión con TSR."""


class DownloadError(TSRError):
    """Error durante la descarga de un item."""


class VIPRequiredError(DownloadError):
    """El item es exclusivo para miembros VIP."""


class ClipboardError(TSRError):
    """No hay ningún portapapeles disponible en el sistema."""
