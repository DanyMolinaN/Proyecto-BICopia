"""
Orquestador principal por linea de comandos (CLI) del pipeline ETL institucional.

Coordina la ejecucion modular o integral de las fases de Extraccion (scrapers),
Transformacion (limpieza, normalizacion, perfilamiento) y
Carga (almacenamiento en CSV, SQLite y Staging PostgreSQL).

Soporta multi-institucion (B1-B4), paginacion y filtro de fechas en noticias (C1),
autoridades con evidencia (D1-D6), oferta academica con segunda fuente SNIESE (E1-E5),
staging versionado (F1-F4) y versionado de datos crudos con manifiesto (G1-G2).
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd

from src.config import settings
from src.instituciones import registry
from src.load.to_csv import CsvLoader
from src.load.to_database import DatabaseLoader
from src.load.to_staging import StagingLoader
from src.scrapers.autoridades_scraper import AutoridadesScraper
from src.scrapers.carreras_scraper import CarrerasScraper
from src.scrapers.facultades_scraper import FacultadesScraper
from src.scrapers.institucional_scraper import InstitucionalScraper
from src.scrapers.noticias_scraper import NoticiasScraper
from src.scrapers.sniese_scraper import SnieseExtractor
from src.transform.cleaning import DataCleaner
from src.transform.scd2 import apply_scd2
from src.transform.validation import DataValidator
from src.utils.http_client import HttpClient
from src.utils.logger import setup_logger

logger = setup_logger("orchestrator")


class ETLPipeline:
    """Gestiona el flujo integral de datos desde el portal web hasta el Data Warehouse y Staging."""

    def __init__(
        self,
        use_cache: bool = True,
        force_refresh: bool = False,
        institucion_id: str = "EPN",
        max_paginas: int = 50,
        dry_run: bool = False,
        target: str = "sqlite",
    ) -> None:
        """Inicializa los componentes del pipeline con las directivas de ejecucion.

        Args:
            use_cache: Si es True, utiliza cache local de archivos HTML/JSON.
            force_refresh: Si es True, fuerza descarga de red ignorando cache.
            institucion_id: ID de la IES a procesar (ej: EPN, ESPE, USFQ).
            max_paginas: Límite de páginas a paginar en endpoints REST (C1).
            dry_run: Si es True, extrae muestras pequeñas sin persistir en base de datos.
            target: Destino de carga ('stg', 'sqlite', 'csv', 'all').
        """
        self.use_cache = use_cache
        self.force_refresh = force_refresh
        self.institucion_id = institucion_id
        self.max_paginas = max_paginas
        self.dry_run = dry_run
        self.target = target

        self.http_client = HttpClient(
            use_cache=use_cache,
            force_refresh=force_refresh,
            institucion_id=institucion_id,
        )
        self.cleaner = DataCleaner()
        self.validator = DataValidator()
        self.csv_loader = CsvLoader()
        self.db_loader = DatabaseLoader()
        self.staging_loader = StagingLoader()

    def run_scrapers(self, modules: list[str]) -> Dict[str, list]:
        """Ejecuta los extractores web solicitados y almacena su resultado en data/interim/.

        Args:
            modules (list[str]): Modulos a ejecutar ('facultades', 'carreras', 'sniese', etc.).

        Returns:
            Dict[str, list]: Datos crudos extraidos por cada modulo.
        """
        logger.info(
            f"[{self.institucion_id}] Iniciando fase de extraccion para modulos: {', '.join(modules)}"
        )
        raw_data: Dict[str, list] = {}

        if "facultades" in modules:
            scraper = FacultadesScraper(self.http_client, institucion_id=self.institucion_id)
            raw_data["facultades"] = scraper.run()

        if "carreras" in modules:
            scraper = CarrerasScraper(self.http_client, institucion_id=self.institucion_id)
            raw_data["carreras"] = scraper.run()

        if "autoridades" in modules:
            scraper = AutoridadesScraper(self.http_client, institucion_id=self.institucion_id)
            raw_data["autoridades"] = scraper.run()

        if "institucional" in modules:
            scraper = InstitucionalScraper(self.http_client, institucion_id=self.institucion_id)
            raw_data["institucional"] = scraper.run()

        if "noticias" in modules:
            scraper = NoticiasScraper(
                self.http_client,
                institucion_id=self.institucion_id,
                max_paginas=self.max_paginas,
            )
            raw_data["noticias"] = scraper.run()
            # C6: Reporte de cobertura 2024-2025
            resumen_p3 = NoticiasScraper.resumen_cobertura(raw_data["noticias"])
            logger.info(
                f"[{self.institucion_id}] Resumen cobertura P3 (2024-2025): "
                f"2024={resumen_p3['cobertura_2024']}, 2025={resumen_p3['cobertura_2025']}, "
                f"Total={resumen_p3['total_registros']} publicaciones."
            )

        if "sniese" in modules:
            extractor = SnieseExtractor(
                self.http_client,
                institucion_id=self.institucion_id,
            )
            raw_data["sniese"] = extractor.run()

        # G2: Reportar estadísticas de red de esta ejecución
        self.http_client.report_stats()

        return raw_data

    def load_interim_from_disk(self) -> Dict[str, list]:
        """Carga datos de la etapa intermedia desde disco si la extraccion ya se ejecuto."""
        import json
        raw_data = {}
        for mod in ["facultades", "carreras", "autoridades", "institucional", "noticias", "sniese"]:
            path = settings.data_interim_dir / f"{mod}scraper.json"
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        raw_data[mod] = json.load(f)
                except Exception as exc:
                    logger.warning(f"Error al leer interim para {mod}: {exc}")
        return raw_data

    def transform(self, raw_data: Dict[str, list]) -> Dict[str, pd.DataFrame]:
        """Ejecuta las reglas de limpieza, normalizacion y perfilamiento dimensional."""
        logger.info("Iniciando fase de transformacion y modelado dimensional...")
        tables: Dict[str, pd.DataFrame] = {}

        # 0. Dimension Institucion Conformada (B4 / D-04)
        active_ids = [self.institucion_id] if self.institucion_id else None
        df_dim_inst = self.cleaner.build_dim_institucion(active_ids)
        tables["dim_institucion"] = df_dim_inst
        self.validator.profile_dataframe(
            df_dim_inst, "dim_institucion", "institucion_key",
            ["institucion_key", "institucion_id", "nombre_institucion"]
        )

        # 1. Dimension Tiempo
        df_dim_tiempo = self.cleaner.build_dim_tiempo()
        tables["dim_tiempo"] = df_dim_tiempo
        self.validator.profile_dataframe(df_dim_tiempo, "dim_tiempo", "tiempo_key", ["tiempo_key", "fecha", "anio"])

        # 2. Dimension Facultades
        raw_fac = raw_data.get("facultades", [])
        df_dim_facultad = self.cleaner.clean_facultades(raw_fac)
        tables["dim_facultad"] = df_dim_facultad
        self.validator.profile_dataframe(df_dim_facultad, "dim_facultad", "facultad_key", ["facultad_key", "nombre", "sigla"])

        # 3. Carreras, Niveles, Modalidad y Hechos Oferta Academica (E2 / E3)
        raw_car = raw_data.get("carreras", [])
        df_dim_car, df_dim_niv, df_dim_mod, df_fact_ofe = self.cleaner.clean_carreras(raw_car, df_dim_facultad)
        tables["dim_carrera"] = df_dim_car
        tables["dim_nivel_formacion"] = df_dim_niv
        tables["dim_modalidad"] = df_dim_mod
        tables["fact_oferta_academica"] = df_fact_ofe

        self.validator.profile_dataframe(df_dim_car, "dim_carrera", "carrera_key", ["carrera_key", "nombre_carrera"])
        self.validator.profile_dataframe(df_dim_niv, "dim_nivel_formacion", "nivel_key", ["nivel_key", "nombre_nivel"])
        self.validator.profile_dataframe(df_dim_mod, "dim_modalidad", "modalidad_key", ["modalidad_key", "nombre_modalidad"])
        self.validator.profile_dataframe(
            df_fact_ofe, "fact_oferta_academica", "oferta_key", ["oferta_key", "carrera_key"],
            foreign_keys={"facultad_key": (df_dim_facultad, "facultad_key"), "tiempo_extraccion_key": (df_dim_tiempo, "tiempo_key")},
        )

        # 4. Autoridades, Cargos y Hechos Autoridades (D1-D6)
        raw_aut = raw_data.get("autoridades", [])
        df_dim_aut, df_dim_car_cargo, df_fact_aut = self.cleaner.clean_autoridades(raw_aut, df_dim_facultad)

        # SCD Tipo 2: reconciliar con el historial ya cargado en la base de datos
        existing_aut = self.db_loader.read_table("dim_autoridad")
        existing_fact_aut = self.db_loader.read_table("fact_designacion_autoridades")
        df_dim_aut, df_fact_aut = apply_scd2(df_dim_aut, df_fact_aut, existing_aut, existing_fact_aut)

        tables["dim_autoridad"] = df_dim_aut
        tables["dim_cargo"] = df_dim_car_cargo
        tables["fact_designacion_autoridades"] = df_fact_aut

        self.validator.profile_dataframe(df_dim_aut, "dim_autoridad", "autoridad_key", ["autoridad_key", "nombre_completo"])
        self.validator.profile_dataframe(df_dim_car_cargo, "dim_cargo", "cargo_key", ["cargo_key", "nombre_cargo"])
        self.validator.profile_dataframe(
            df_fact_aut, "fact_designacion_autoridades", "designacion_key", ["designacion_key", "autoridad_key", "cargo_key"],
            foreign_keys={"autoridad_key": (df_dim_aut, "autoridad_key"), "cargo_key": (df_dim_car_cargo, "cargo_key")},
        )

        # 5. Noticias y Hechos Comunicacion (C1-C6)
        raw_not = raw_data.get("noticias", [])
        df_dim_cat, df_fact_not = self.cleaner.clean_noticias(raw_not)
        tables["dim_categoria_noticia"] = df_dim_cat
        tables["fact_comunicacion_institucional"] = df_fact_not

        self.validator.profile_dataframe(df_dim_cat, "dim_categoria_noticia", "categoria_key", ["categoria_key", "nombre_categoria"])
        self.validator.profile_dataframe(
            df_fact_not, "fact_comunicacion_institucional", "noticia_key", ["noticia_key", "categoria_key"],
            foreign_keys={"tiempo_publicacion_key": (df_dim_tiempo, "tiempo_key"), "categoria_key": (df_dim_cat, "categoria_key")},
        )

        # 6. Informacion Institucional General
        raw_inst = raw_data.get("institucional", [])
        if raw_inst:
            df_inst = pd.DataFrame(raw_inst)
            tables["dim_informacion_institucional"] = df_inst

        # Generar reporte de calidad
        report_md = self.validator.generate_markdown_report()
        report_path = settings.logs_dir / "reporte_calidad_datos.md"
        report_path.write_text(report_md, encoding="utf-8")
        logger.info(f"Reporte de calidad y perfilamiento persistido en: {report_path.name}")

        return tables

    def load_data(
        self,
        tables: Dict[str, pd.DataFrame],
        to_csv: bool = True,
        to_db: bool = True,
    ) -> None:
        """Carga las tablas en archivos CSV procesados y base de datos relacional."""
        if self.dry_run:
            logger.info("[DRY RUN] Omitiendo persistencia de tablas en disco/base de datos.")
            return

        if to_csv:
            logger.info("Exportando entidades procesadas a formato CSV...")
            self.csv_loader.load_all(tables)

        if to_db:
            logger.info("Insertando entidades procesadas en la base de datos SQL del Data Warehouse...")
            counts = self.db_loader.load_all(tables)
            for tbl, cnt in counts.items():
                logger.info(f"Base de datos -> Tabla '{tbl}': {cnt} registros cargados.")

    def load_staging(self, raw_data: Dict[str, list]) -> Dict[str, Dict[str, int]]:
        """Carga los datos crudos directamente a staging sin transformar (F3)."""
        if self.dry_run:
            logger.info("[DRY RUN] Omitiendo carga en Staging.")
            return {}

        logger.info("Cargando datos crudos a Staging (esquema stg)...")
        results = self.staging_loader.load_all(raw_data)
        for tbl, res in results.items():
            logger.info(f"Staging -> '{tbl}': {res['insertados']} insertados, {res['duplicados_omitidos']} duplicados omitidos.")
        return results

    def run_all(self) -> None:
        """Ejecuta el ciclo de vida completo de extremo a extremo."""
        logger.info(f"=== INICIANDO PIPELINE ETL [{self.institucion_id}] ===")
        all_modules = ["facultades", "carreras", "autoridades", "institucional", "noticias", "sniese"]
        raw = self.run_scrapers(all_modules)

        # Carga a Staging si el target es 'stg' o 'all'
        if self.target in ("stg", "all"):
            self.load_staging(raw)

        # Transformación y carga regular (CSV y SQLite por defecto)
        if self.target in ("sqlite", "csv", "all"):
            tables = self.transform(raw)
            self.load_data(
                tables,
                to_csv=(self.target in ("csv", "all")),
                to_db=(self.target in ("sqlite", "all")),
            )

        logger.info(f"=== PIPELINE ETL [{self.institucion_id}] FINALIZADO EXITOSAMENTE ===")


def main() -> None:
    """Punto de entrada de linea de comandos para el orquestador."""
    parser = argparse.ArgumentParser(
        description="Orquestador ETL para extraccion, transformacion y carga de datos de educacion superior (Hito 2).",
        epilog="Proyecto academico de Business Intelligence - Ingenieria de Datos FIS-EPN."
    )

    parser.add_argument("--all", action="store_true", help="Ejecutar el pipeline ETL completo de extremo a extremo.")
    parser.add_argument("--facultades", action="store_true", help="Ejecutar unicamente el extractor de facultades.")
    parser.add_argument("--carreras", action="store_true", help="Ejecutar unicamente el extractor de carreras.")
    parser.add_argument("--autoridades", action="store_true", help="Ejecutar unicamente el extractor de autoridades.")
    parser.add_argument("--institucional", action="store_true", help="Ejecutar unicamente el extractor institucional.")
    parser.add_argument("--noticias", action="store_true", help="Ejecutar unicamente el extractor de noticias.")
    parser.add_argument("--sniese", action="store_true", help="Ejecutar el extractor de segunda fuente SNIESE/CES.")
    parser.add_argument("--transform", action="store_true", help="Ejecutar fase de transformacion y validacion sobre datos interim.")
    parser.add_argument("--load-csv", action="store_true", help="Cargar datos procesados unicamente a archivos CSV.")
    parser.add_argument("--load-db", action="store_true", help="Cargar datos procesados a la base de datos SQL.")
    parser.add_argument("--load-stg", action="store_true", help="Cargar datos crudos a Staging (esquema stg).")
    parser.add_argument("--no-cache", action="store_true", help="Desactivar uso de cache local (forzar solicitudes de red).")
    parser.add_argument("--force-refresh", action="store_true", help="Reescribir archivos en cache local con nuevas descargas.")
    
    # Nuevas banderas del Hito 2 (Regla 7 y F4)
    parser.add_argument("--institucion", type=str, default="EPN", help="ID de la institucion a procesar (ej: EPN, ESPE, USFQ o código CES).")
    parser.add_argument("--max-paginas", type=int, default=50, help="Maximo de paginas a recorrer en endpoints paginados.")
    parser.add_argument("--dry-run", action="store_true", help="Ejecutar en modo prueba sin escribir en BD ni persistir masivamente.")
    parser.add_argument("--target", choices=["stg", "sqlite", "csv", "all"], default="sqlite", help="Destino de persistencia (defecto: sqlite).")

    # Comando único CES-64 (Fase 7 y Ola multi-institución)
    parser.add_argument("--ces64", action="store_true", help="Ejecutar orquestador multi-institución para el catálogo de las 64 IES del CES.")
    parser.add_argument("--tipo", type=str, choices=["publica", "particular_autofinanciada", "particular_cofinanciada"], default=None, help="Filtrar IES por tipo de financiamiento CES.")
    parser.add_argument("--lote", type=int, default=None, help="Número máximo de instituciones a procesar en el lote.")
    parser.add_argument("--modulo", type=str, choices=["ces", "noticias", "autoridades", "oferta", "todos"], default="todos", help="Módulo a ejecutar (ces, noticias, autoridades, oferta, todos).")
    parser.add_argument("--reanudar", action="store_true", help="Omitir instituciones y módulos ya extraídos con éxito en la ejecución actual.")

    args = parser.parse_args()

    # Flujo comando único --ces64
    if args.ces64:
        from src.ces64_runner import Ces64Runner
        modulos_list = ["ces", "noticias", "autoridades", "oferta"] if args.modulo == "todos" else [args.modulo]
        # Determinar si se pasó institución específica (distinta del default EPN si el usuario no la especificó)
        # Para detectar si el usuario pasó --institucion explícitamente:
        inst_especifica = [x.strip() for x in args.institucion.split(",")] if "--institucion" in sys.argv else None
        
        runner = Ces64Runner(
            modulos=modulos_list,
            tipo=args.tipo,
            institucion_ids=inst_especifica,
            lote=args.lote,
            max_paginas=args.max_paginas,
            dry_run=args.dry_run,
            reanudar=args.reanudar,
            use_cache=not args.no_cache,
            force_refresh=args.force_refresh,
            target="stg" if args.load_stg else args.target,
        )
        runner.run()
        return

    pipeline = ETLPipeline(
        use_cache=not args.no_cache,
        force_refresh=args.force_refresh,
        institucion_id=args.institucion,
        max_paginas=args.max_paginas,
        dry_run=args.dry_run,
        target="stg" if args.load_stg else args.target,
    )

    # Si no se pasan argumentos o se pasa --all, ejecutar todo el pipeline
    if args.all or not any([
        args.facultades, args.carreras, args.autoridades,
        args.institucional, args.noticias, args.sniese, args.transform,
        args.load_csv, args.load_db, args.load_stg
    ]):
        pipeline.run_all()
        return

    # Ejecucion modular de scrapers
    selected_modules = []
    if args.facultades:
        selected_modules.append("facultades")
    if args.carreras:
        selected_modules.append("carreras")
    if args.autoridades:
        selected_modules.append("autoridades")
    if args.institucional:
        selected_modules.append("institucional")
    if args.noticias:
        selected_modules.append("noticias")
    if args.sniese:
        selected_modules.append("sniese")

    raw_data = {}
    if selected_modules:
        raw_data = pipeline.run_scrapers(selected_modules)
    else:
        raw_data = pipeline.load_interim_from_disk()

    # Si se solicito carga a staging
    if args.load_stg or args.target == "stg":
        pipeline.load_staging(raw_data)

    # Si se solicito transformacion o carga tradicional
    if args.transform or args.load_csv or args.load_db or args.target in ("sqlite", "csv", "all"):
        if not raw_data:
            raw_data = pipeline.load_interim_from_disk()
        tables = pipeline.transform(raw_data)

        if args.load_csv or args.load_db or args.target in ("sqlite", "csv", "all"):
            pipeline.load_data(
                tables,
                to_csv=args.load_csv or args.target in ("csv", "all"),
                to_db=args.load_db or args.target in ("sqlite", "all"),
            )


if __name__ == "__main__":
    main()
