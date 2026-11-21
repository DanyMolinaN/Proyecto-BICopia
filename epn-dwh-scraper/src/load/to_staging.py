"""
Cargador para la capa de Staging (esquema `stg`).

Implementa la carga de datos crudos, versionados y sin transformar hacia
la base de datos relacional (PostgreSQL en produccion o SQLite en entorno local).
Aplica append versionado por run_id e idempotencia garantizada por hash_registro (F3).
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from src.config import settings
from src.utils.logger import setup_logger

logger = setup_logger("load_staging")

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
_SQL_STG_DIR = _BASE_DIR / "sql" / "stg"


class StagingLoader:
    """Gestiona la inicializacion del esquema stg y la carga cruda versionada."""

    TABLE_MAPPING = {
        "carreras": "stg_oferta",
        "oferta": "stg_oferta",
        "autoridades": "stg_autoridades",
        "noticias": "stg_publicaciones",
        "publicaciones": "stg_publicaciones",
        "sniese": "stg_oferta_sniese",
        "oferta_sniese": "stg_oferta_sniese",
    }

    def __init__(self, connection_url: Optional[str] = None) -> None:
        """Inicializa el cargador de staging.

        Args:
            connection_url: URI SQLAlchemy (ej: postgresql://... o sqlite:///...).
        """
        self.connection_url = connection_url or settings.database_url
        self.engine: Engine = create_engine(self.connection_url, echo=False)
        self.is_sqlite: bool = self.engine.url.drivername.startswith("sqlite")
        self.schema_name = None if self.is_sqlite else "stg"
        logger.info(f"StagingLoader conectado a: {self.engine.url.drivername} (esquema: {self.schema_name})")

    def execute_sql_file(self, sql_file_path: Path) -> None:
        """Ejecuta un script SQL adaptando sintaxis PostgreSQL a SQLite si corresponde."""
        if not sql_file_path.exists():
            logger.warning(f"Archivo DDL de staging no encontrado: {sql_file_path}")
            return

        content = sql_file_path.read_text(encoding="utf-8")
        if self.is_sqlite:
            # Adaptación para SQLite: omitir CREATE SCHEMA y ajustar tipos
            lines = []
            for line in content.splitlines():
                if "CREATE SCHEMA" in line.upper():
                    continue
                # En SQLite no hay stg.tabla
                line = re_replace_schema = line.replace("stg.", "")
                line = line.replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
                line = line.replace("TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP", "TEXT DEFAULT CURRENT_TIMESTAMP")
                lines.append(line)
            content = "\n".join(lines)

        statements = [s.strip() for s in content.split(";") if s.strip()]
        with self.engine.begin() as conn:
            for stmt in statements:
                clean_lines = [l for l in stmt.splitlines() if not l.strip().startswith("--")]
                clean = "\n".join(clean_lines).strip()
                if clean:
                    conn.execute(text(clean))

        logger.debug(f"Ejecutado DDL de staging: {sql_file_path.name}")

    def init_schema(self) -> None:
        """Ejecuta todos los scripts DDL de la carpeta sql/stg/."""
        if not _SQL_STG_DIR.exists():
            logger.warning(f"Directorio sql/stg no existe: {_SQL_STG_DIR}")
            return

        ddl_files = sorted(_SQL_STG_DIR.glob("*.sql"))
        for ddl in ddl_files:
            try:
                self.execute_sql_file(ddl)
            except Exception as exc:
                logger.warning(f"Error al ejecutar DDL {ddl.name}: {exc}")

        logger.info("Esquema stg inicializado satisfactoriamente.")

    def load_raw_table(
        self,
        records: List[Dict[str, Any]],
        table_name: str,
    ) -> Dict[str, int]:
        """Carga registros crudos con append versionado e idempotencia por hash_registro.

        Args:
            records: Lista de diccionarios crudos con metadatos.
            table_name: Nombre de la tabla destino (sin prefijo de esquema).

        Returns:
            Dict[str, int]: {'insertados': N, 'duplicados_omitidos': M, 'total': T}
        """
        if not records:
            return {"insertados": 0, "duplicados_omitidos": 0, "total": 0}

        df = pd.DataFrame(records)

        # Metadatos obligatorios por si faltan
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if "fecha_carga" not in df.columns:
            df["fecha_carga"] = now_iso

        # Verificar tabla existente y aplicar idempotencia por hash_registro
        actual_table = table_name if self.is_sqlite else table_name
        existing_hashes = set()

        try:
            inspector = inspect(self.engine)
            tables = inspector.get_table_names(schema=self.schema_name)
            if table_name in tables:
                with self.engine.connect() as conn:
                    tbl_ref = f"{self.schema_name}.{table_name}" if self.schema_name else table_name
                    rows = conn.execute(text(f"SELECT hash_registro FROM {tbl_ref}")).fetchall()
                    existing_hashes = {r[0] for r in rows if r[0]}
        except Exception as exc:
            logger.debug(f"No se pudieron leer hashes existentes de {table_name}: {exc}")

        # Filtrar registros ya existentes (idempotencia)
        if "hash_registro" in df.columns and existing_hashes:
            mask_new = ~df["hash_registro"].isin(existing_hashes)
            df_to_insert = df[mask_new].copy()
            duplicados = int((~mask_new).sum())
        else:
            df_to_insert = df.copy()
            duplicados = 0

        insertados = len(df_to_insert)

        if insertados > 0:
            # Append versionado: nunca 'replace' (F3)
            df_to_insert.to_sql(
                name=table_name,
                con=self.engine,
                schema=self.schema_name,
                if_exists="append",
                index=False,
            )
            logger.info(
                f"[stg.{table_name}] Insertados {insertados} registros crudos "
                f"({duplicados} omitidos por idempotencia)."
            )
        else:
            logger.info(
                f"[stg.{table_name}] Todos los {len(df)} registros ya existen en staging "
                "(idempotencia completa)."
            )

        return {
            "insertados": insertados,
            "duplicados_omitidos": duplicados,
            "total": len(records),
        }

    def load_all(self, raw_data_dict: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, int]]:
        """Carga todas las fuentes crudas a sus tablas stg correspondientes.

        Args:
            raw_data_dict: Diccionario {modulo: lista_de_registros_crudos}.

        Returns:
            Dict con los resultados de carga por tabla.
        """
        self.init_schema()
        results = {}

        for mod_key, records in raw_data_dict.items():
            stg_tbl = self.TABLE_MAPPING.get(mod_key, f"stg_{mod_key}")
            res = self.load_raw_table(records, stg_tbl)
            results[stg_tbl] = res

        return results
