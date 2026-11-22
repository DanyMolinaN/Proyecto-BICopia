"""
Extractor para la segunda fuente de datos: Catastro Oficial de Oferta Academica (SNIESE / CES).

SENESCYT a traves del SNIESE (Sistema Nacional de Informacion de Educacion Superior del Ecuador)
y el CES (Consejo de Educacion Superior) publican el catastro de carreras y programas
vigentes y no vigentes a nivel nacional.

Este extractor permite:
1. Ingestar el conjunto de datos abierto oficial (formato CSV/Excel exportado de datosabiertos.gob.ec).
2. Estructurar la informacion para contrastacion con el portal web institucional (P1).
3. Conservar la trazabilidad completa (institucion_id, fecha_extraccion, run_id, hash_registro).
"""

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd

from src.config import settings
from src.scrapers.base_scraper import BaseScraper
from src.utils.helpers import clean_text, remove_accents


class SnieseExtractor(BaseScraper):
    """Extractor y procesador del catastro oficial de oferta academica SNIESE/SENESCYT."""

    FUENTE_OFICIAL = "https://datosabiertos.gob.ec/dataset/oferta-academica-ies"
    FUENTE_CES = "https://appcmi.ces.gob.ec/oferta_vigente/"

    def __init__(
        self,
        http_client=None,
        institucion_id: Optional[str] = "EPN",
        data_file_path: Optional[Path] = None,
    ) -> None:
        """Inicializa el extractor de SNIESE.

        Args:
            http_client: Cliente HTTP.
            institucion_id: IES a filtrar (o None para todas).
            data_file_path: Ruta a archivo local CSV/XLSX de datos abiertos.
        """
        super().__init__(http_client=http_client, institucion_id=institucion_id)
        self.data_file_path = data_file_path

    def extract(self) -> List[Dict[str, Any]]:
        """Extrae el catastro de oferta académica oficial de SNIESE/CES.

        Si se configuró un archivo CSV o Excel local (`data_file_path`) o existe
        en `data/raw/sniese_oferta_academica.csv`, se carga directamente.
        Si no existe archivo descargado comprobable, NO se inyectan datos de
        referencia a staging y se retorna lista vacía conforme a las reglas éticas.
        """
        records: List[Dict[str, Any]] = []

        file_path = self.data_file_path or (settings.data_raw_dir / "sniese_oferta_academica.csv")
        if file_path and Path(file_path).exists():
            self.logger.info(f"Cargando catastro SNIESE desde archivo: {file_path}")
            p = Path(file_path)
            if p.suffix.lower() == ".csv":
                df = pd.read_csv(p)
            else:
                df = pd.read_excel(p)
            for _, row in df.iterrows():
                rec = row.to_dict()
                records.append(rec)
        else:
            self.logger.warning(
                "Segunda fuente SNIESE/CES no disponible localmente: no existe "
                f"'{file_path}'. Conforme a la sección 10 de la guía y V2, los datos "
                "de referencia embebidos no se inyectan a staging sin archivo de origen comprobable."
            )
            return []

        # Filtrar por institución si está configurado
        if self.institucion_id:
            records = [r for r in records if r.get("institucion_id") == self.institucion_id]

        # Añadir trazabilidad a cada registro
        fuente_url = self.FUENTE_CES
        enriched = []
        for r in records:
            r["anio_referencia"] = 2026
            r["fuente_organismo"] = "SENESCYT / CES (SNIESE)"
            enriched.append(self._add_traceability(r, fuente_url=fuente_url))

        self.logger.info(f"[{self.institucion_id}] Obtenidos {len(enriched)} registros del catastro SNIESE/CES.")
        return enriched
