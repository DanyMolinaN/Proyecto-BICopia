"""
conftest.py – configuración global de pytest para el proyecto.

Redirige el archivo de log a un directorio temporal durante las pruebas,
evitando errores de permisos cuando el archivo principal está abierto.
"""

import tempfile
import logging
from pathlib import Path
import pytest


def pytest_configure(config):
    """Redirige el log de scraper a un archivo temporal durante las pruebas."""
    import src.config as cfg_module
    tmp_log = Path(tempfile.gettempdir()) / "epn_scraper_test.log"
    cfg_module.settings.log_file = tmp_log
    cfg_module.settings.log_file.parent.mkdir(parents=True, exist_ok=True)
