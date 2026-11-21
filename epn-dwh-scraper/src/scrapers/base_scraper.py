"""
Clase base abstracta para los modulos extractores (scrapers).

Define el contrato comun de ejecucion, inyeccion del cliente HTTP,
gestion de logs y persistencia intermedia de datos sin limpiar.
Incluye trazabilidad obligatoria: institucion_id, fecha_extraccion,
run_id, fuente_url y hash_registro en cada registro crudo (B2).
"""

from abc import ABC, abstractmethod
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd

from src.config import settings
from src.utils.http_client import HttpClient
from src.utils.logger import setup_logger


class ExtractionError(RuntimeError):
    """Se lanza cuando un extractor obtiene menos registros de los esperados."""


# Identificador de ejecución único por proceso (compartido por todos los scrapers)
_RUN_ID: str = str(uuid.uuid4())


def _compute_hash(record: Dict[str, Any]) -> str:
    """Genera un hash SHA-256 sobre el contenido semántico del registro."""
    # Se excluyen los metadatos de trazabilidad para que el hash sea estable
    skip = {"institucion_id", "fecha_extraccion", "run_id", "fuente_url", "hash_registro"}
    payload = json.dumps(
        {k: v for k, v in sorted(record.items()) if k not in skip},
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


class BaseScraper(ABC):
    """Contrato base y operaciones comunes para todos los scrapers del proyecto."""

    # ID de la institución por defecto (EPN, compatibilidad hacia atrás)
    _DEFAULT_INSTITUCION_ID = "EPN"

    def __init__(
        self,
        http_client: Optional[HttpClient] = None,
        institucion_id: Optional[str] = None,
        institucion: Optional[Any] = None,
    ) -> None:
        """Inicializa el extractor con cliente HTTP y logger especializado.

        Args:
            http_client (Optional[HttpClient]): Instancia inyectable del cliente HTTP.
            institucion_id (Optional[str]): ID de la institución a extraer.
                Si se omite, se usa la EPN (compatibilidad hacia atrás).
            institucion (Optional[Any]): Instancia de InstitucionConfig con
                base_url, endpoints y adaptador inyectados directamente.
        """
        self.http_client = http_client or HttpClient()
        self.logger = setup_logger(self.__class__.__name__)
        self.interim_dir = settings.data_interim_dir
        
        # Resolver configuración de institución (regla 2: no depender solo de config global)
        from src.instituciones import registry
        self.institucion = institucion
        if self.institucion:
            self.institucion_id = self.institucion.id
        else:
            self.institucion_id = institucion_id or self._DEFAULT_INSTITUCION_ID
            self.institucion = registry.get(self.institucion_id)

        self._run_id: str = _RUN_ID

    @abstractmethod
    def extract(self) -> List[Dict[str, Any]]:
        """Metodo abstracto que implementa la logica especifica de extraccion.

        Returns:
            List[Dict[str, Any]]: Lista de diccionarios con los registros parseados.
        """
        pass

    def _add_traceability(
        self,
        record: Dict[str, Any],
        fuente_url: str = "",
    ) -> Dict[str, Any]:
        """Añade campos de trazabilidad obligatorios a un registro crudo (B2).

        Los campos agregados son:
            - institucion_id: identificador de la IES.
            - fecha_extraccion: timestamp ISO 8601 UTC del momento de captura.
            - run_id: UUID único de esta ejecución del pipeline.
            - fuente_url: URL de la página o endpoint de origen.
            - hash_registro: hash SHA-256 (20 hex) del contenido semántico.

        Args:
            record (Dict[str, Any]): Registro crudo a enriquecer.
            fuente_url (str): URL de la fuente del registro.

        Returns:
            Dict[str, Any]: Registro enriquecido con trazabilidad.
        """
        trace = {
            "institucion_id": self.institucion_id,
            "fecha_extraccion": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "run_id": self._run_id,
            "fuente_url": fuente_url or record.get("fuente_url", ""),
        }
        # Merge: los campos del registro original prevalecen si colisionan
        merged = {**trace, **record}
        # El hash se calcula sobre el merged (sin hash previo)
        merged["hash_registro"] = _compute_hash(merged)
        return merged

    def save_interim(self, data: List[Dict[str, Any]], filename: str) -> Path:
        """Almacena los datos extraidos en la capa intermedia (interim) en JSON y CSV.

        Args:
            data (List[Dict[str, Any]]): Conjunto de registros crudos.
            filename (str): Nombre base del archivo sin extension.

        Returns:
            Path: Ruta del archivo JSON guardado.
        """
        if not data:
            self.logger.warning(f"No hay datos para persistir en la etapa interim para {filename}")
            return self.interim_dir / f"{filename}.json"

        # Guardar en formato JSON (fiel a la jerarquia parseada)
        json_path = self.interim_dir / f"{filename}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # Guardar tambien una version preliminar en CSV para inspeccion rapida
        csv_path = self.interim_dir / f"{filename}.csv"
        df = pd.DataFrame(data)
        df.to_csv(csv_path, index=False, encoding="utf-8")

        self.logger.info(f"Persistidos {len(data)} registros en capa interim: {json_path.name}")
        return json_path

    def run(self) -> List[Dict[str, Any]]:
        """Ejecuta el ciclo de vida completo de extraccion y persistencia intermedia.

        Returns:
            List[Dict[str, Any]]: Datos parseados en bruto.
        """
        self.logger.info(f"Iniciando ejecucion de extractor: {self.__class__.__name__}")
        try:
            records = self.extract()
            key = self.__class__.__name__.lower().replace("scraper", "").replace("extractor", "")
            minimum = settings.min_records.get(key, 1)
            if len(records) < minimum:
                raise ExtractionError(
                    f"{self.__class__.__name__} extrajo {len(records)} registros (minimo esperado: {minimum}). "
                    "Posible cambio en el sitio, bloqueo o falla de red; no se persistieron datos."
                )
            self.logger.info(f"Extraccion completada con {len(records)} registros.")
            self.save_interim(records, self.__class__.__name__.lower())
            return records
        except Exception as exc:
            self.logger.error(f"Error critico durante ejecucion de {self.__class__.__name__}: {exc}", exc_info=True)
            raise
