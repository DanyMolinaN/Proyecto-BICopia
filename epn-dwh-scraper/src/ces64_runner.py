"""
Orquestador CES-64: ejecuta scrapers sobre las 64 IES del catálogo del CES.

Implementa el comportamiento de --ces64 descrito en el prompt:

- Recorre el catálogo instituciones_ces64.yaml o portales_validados.csv.
- Por cada IES usa SUS endpoints validados (nunca los de la EPN por defecto).
- Registra cada módulo con estado: ok | parcial | sin_seccion | sin_adaptador |
  bloqueado_robots | js_requerido | error_http | no_intentado.
- El fallo de una institución no detiene a las demás.
- Soporta --reanudar (omite instituciones + módulo ya con estado=ok en el run_id).
- Un solo hilo por host, 1 s mínimo, caché, tope de páginas.
- Guarda ejecucion_institucion en staging y CSV.
- Imprime tabla resumen al final.
"""

import csv
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from src.config import settings
from src.instituciones import load_ces64, InstitucionConfig
from src.scrapers.base_scraper import _RUN_ID
from src.scrapers.noticias_scraper import NoticiasScraper
from src.scrapers.autoridades_scraper import AutoridadesScraper
from src.scrapers.carreras_scraper import CarrerasScraper
from src.utils.http_client import HttpClient
from src.utils.logger import setup_logger

logger = setup_logger("ces64_runner")

_BASE_DIR = Path(__file__).resolve().parent.parent
_PORTALES_CSV = _BASE_DIR / "config" / "portales_validados.csv"
_EJECUCION_CSV = _BASE_DIR / "data" / "ejecucion_institucion.csv"

MODULOS_DISPONIBLES = ["ces", "noticias", "autoridades", "oferta", "todos"]

ESTADOS_VALIDOS = {
    "ok", "parcial", "sin_seccion", "sin_adaptador",
    "bloqueado_robots", "js_requerido", "error_http", "no_intentado",
}


# ---------------------------------------------------------------------------
# Tabla de ejecución
# ---------------------------------------------------------------------------

def _load_ejecucion_csv() -> Dict[tuple, str]:
    """Carga ejecucion_institucion.csv y devuelve {(run_id, iid, modulo): estado}."""
    result = {}
    if not _EJECUCION_CSV.exists():
        return result
    with open(_EJECUCION_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row.get("run_id", ""), row.get("institucion_id", ""), row.get("modulo", ""))
            result[key] = row.get("estado", "")
    return result


def _append_ejecucion(record: Dict[str, Any]) -> None:
    """Agrega una fila a ejecucion_institucion.csv (append, con cabecera si nuevo)."""
    _EJECUCION_CSV.parent.mkdir(parents=True, exist_ok=True)
    write_header = not _EJECUCION_CSV.exists()
    with open(_EJECUCION_CSV, "a", newline="", encoding="utf-8") as f:
        fieldnames = [
            "run_id", "institucion_id", "modulo", "estado",
            "registros_extraidos", "paginas_consultadas",
            "inicio", "fin", "mensaje",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(record)


# ---------------------------------------------------------------------------
# Carga de portales validados
# ---------------------------------------------------------------------------

def _load_portales() -> Dict[str, Dict[str, str]]:
    """Carga portales_validados.csv como {institucion_id: row_dict}."""
    portales: Dict[str, Dict[str, str]] = {}
    if not _PORTALES_CSV.exists():
        logger.warning(f"portales_validados.csv no encontrado en {_PORTALES_CSV}. Solo EPN tendrá URLs.")
        return portales
    with open(_PORTALES_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            portales[row["institucion_id"]] = row
    return portales


# ---------------------------------------------------------------------------
# Enriquecimiento de InstitucionConfig con portales validados
# ---------------------------------------------------------------------------

def _build_inst_from_portal(
    inst: InstitucionConfig, portal: Optional[Dict[str, str]]
) -> InstitucionConfig:
    """Devuelve una InstitucionConfig enriquecida con los datos del portal validado.

    No modifica el objeto original; crea una copia ligera mediante monkey-patch.
    """
    if not portal:
        return inst

    # Enriquecer endpoints con URLs descubiertas
    new_endpoints = dict(inst.endpoints)
    if portal.get("url_noticias"):
        new_endpoints["noticias_web"] = portal["url_noticias"]
        new_endpoints["noticias_api"] = portal["url_noticias"].rstrip("/").replace(
            "/noticias", "/wp-json/wp/v2/posts"
        ) if portal.get("es_wordpress") == "si" else new_endpoints.get("noticias_api", "")
    if portal.get("url_autoridades"):
        new_endpoints["autoridades"] = portal["url_autoridades"]
    if portal.get("url_oferta"):
        new_endpoints["oferta_grado"] = portal["url_oferta"]

    portal_url = portal.get("portal_url", inst.base_url)
    new_endpoints.setdefault("robots_txt", portal_url.rstrip("/") + "/robots.txt")

    # Clonar con sobrescritura
    clone = InstitucionConfig({
        "id": inst.id,
        "nombre": inst.nombre,
        "sigla": inst.sigla,
        "ces_cod": inst.ces_cod,
        "ces_codp": inst.ces_codp,
        "tipo_institucional": inst.tipo_institucional,
        "financiamiento": inst.financiamiento,
        "provincia": inst.provincia,
        "canton": inst.canton,
        "ces_url": inst.ces_url,
        "base_url": portal_url,
        "portal_url": portal_url,
        "endpoints": new_endpoints,
        "adaptador": "wordpress" if portal.get("es_wordpress") == "si" else inst.adaptador,
        "estado_integracion": inst.estado_integracion,
        "observaciones": inst.observaciones,
    })
    return clone


# ---------------------------------------------------------------------------
# Determinación del estado de módulo
# ---------------------------------------------------------------------------

def _estado_modulo(inst: InstitucionConfig, modulo: str, portal: Optional[Dict]) -> str:
    """Decide el estado inicial de un módulo antes de ejecutarlo."""
    # Sin portal validado → sin_seccion para todo menos 'ces'
    if modulo == "ces":
        return "pendiente"

    if not portal or portal.get("estado", "") not in ("validado",):
        return "sin_seccion"

    robots = portal.get("robots_permite", "si")
    if robots == "no":
        return "bloqueado_robots"

    # Verificar si hay URL para el módulo
    if modulo == "noticias" and not portal.get("url_noticias"):
        return "sin_seccion"
    if modulo == "autoridades" and not portal.get("url_autoridades"):
        return "sin_seccion"
    if modulo == "oferta" and not portal.get("url_oferta"):
        return "sin_seccion"

    # WordPress check para noticias
    if modulo == "noticias" and inst.adaptador not in ("wordpress", "pendiente"):
        return "sin_adaptador"

    return "pendiente"


# ---------------------------------------------------------------------------
# Ejecución por módulo
# ---------------------------------------------------------------------------

def _run_modulo(
    inst: InstitucionConfig,
    modulo: str,
    http_client: HttpClient,
    max_paginas: int,
    dry_run: bool,
) -> Dict[str, Any]:
    """Ejecuta un módulo para una institución y devuelve el registro de ejecución."""
    inicio = datetime.now(timezone.utc).isoformat()
    rec_ejec: Dict[str, Any] = {
        "run_id": _RUN_ID,
        "institucion_id": inst.id,
        "modulo": modulo,
        "estado": "no_intentado",
        "registros_extraidos": 0,
        "paginas_consultadas": 0,
        "inicio": inicio,
        "fin": inicio,
        "mensaje": "",
        "_records": [],
    }

    try:
        records: List[Dict] = []

        if modulo == "noticias":
            scraper = NoticiasScraper(
                http_client=http_client,
                institucion_id=inst.id,
                max_paginas=max_paginas,
                institucion=inst,
            )
            records = scraper.extract()

        elif modulo == "autoridades":
            scraper = AutoridadesScraper(
                http_client=http_client,
                institucion_id=inst.id,
                institucion=inst,
            )
            records = scraper.extract()

        elif modulo == "oferta":
            scraper = CarrerasScraper(
                http_client=http_client,
                institucion_id=inst.id,
                institucion=inst,
            )
            records = scraper.extract()

        elif modulo == "ces":
            from src.scrapers.ces_perfil_scraper import CesPerfilScraper
            scraper = CesPerfilScraper(
                http_client=http_client,
                institucion_ids=[inst.id],
            )
            records = scraper.extract()

        rec_ejec["registros_extraidos"] = len(records)
        rec_ejec["_records"] = records
        rec_ejec["estado"] = "ok" if records else "sin_seccion"
        rec_ejec["mensaje"] = f"{len(records)} registros extraídos"

    except Exception as exc:
        msg = str(exc)[:200]
        rec_ejec["estado"] = "error_http" if "HTTP" in msg or "Connection" in msg else "parcial"
        rec_ejec["mensaje"] = msg
        logger.warning(f"[{inst.id}] Error en módulo {modulo}: {msg}")

    finally:
        rec_ejec["fin"] = datetime.now(timezone.utc).isoformat()

    return rec_ejec


# ---------------------------------------------------------------------------
# Runner principal
# ---------------------------------------------------------------------------

class Ces64Runner:
    """Orquestador principal para el modo --ces64."""

    def __init__(
        self,
        modulos: Optional[List[str]] = None,
        tipo: Optional[str] = None,
        institucion_ids: Optional[List[str]] = None,
        lote: Optional[int] = None,
        max_paginas: int = 50,
        dry_run: bool = False,
        reanudar: bool = False,
        use_cache: bool = True,
        force_refresh: bool = False,
        target: str = "sqlite",
    ) -> None:
        self.modulos = modulos or ["noticias", "autoridades", "oferta"]
        self.tipo = tipo
        self.institucion_ids = set(institucion_ids) if institucion_ids else None
        self.lote = lote
        self.max_paginas = max_paginas
        self.dry_run = dry_run
        self.reanudar = reanudar
        self.use_cache = use_cache
        self.force_refresh = force_refresh
        self.target = target

        self._registry = load_ces64()
        self._portales = _load_portales()
        self._ejecucion_previa: Dict[tuple, str] = _load_ejecucion_csv() if reanudar else {}

    def _get_instituciones(self) -> List[InstitucionConfig]:
        """Filtra las instituciones según tipo, ids y lote."""
        insts = self._registry.all()

        if self.tipo:
            insts = [i for i in insts if i.tipo_institucional == self.tipo]
        if self.institucion_ids:
            insts = [i for i in insts if i.id in self.institucion_ids]
        if self.lote:
            insts = insts[: self.lote]

        return insts

    def _skip(self, inst_id: str, modulo: str) -> bool:
        """True si se debe omitir (--reanudar y ya ok en este run_id)."""
        if not self.reanudar:
            return False
        estado = self._ejecucion_previa.get((_RUN_ID, inst_id, modulo), "")
        return estado == "ok"

    def run(self) -> List[Dict[str, Any]]:
        """Ejecuta el pipeline CES-64 y devuelve la tabla de ejecución."""
        instituciones = self._get_instituciones()
        logger.info(
            f"[ces64] Iniciando con {len(instituciones)} instituciones, "
            f"módulos={self.modulos}, lote={self.lote}, dry_run={self.dry_run}"
        )

        tabla_ejecucion: List[Dict[str, Any]] = []
        raw_data_all: Dict[str, List] = {}

        for inst in instituciones:
            portal = self._portales.get(inst.id)
            inst_enriquecida = _build_inst_from_portal(inst, portal)

            # HttpClient por institución (respeta rate-limit por host y versionado en data/raw/<fecha>/<iid>/)
            http = HttpClient(
                use_cache=self.use_cache,
                force_refresh=self.force_refresh,
                institucion_id=inst.id,
                run_id=_RUN_ID,
                per_institution_raw=True,
            )

            for modulo in self.modulos:
                if modulo == "todos":
                    continue

                if self._skip(inst.id, modulo):
                    logger.info(f"[{inst.id}] Módulo {modulo}: omitido (--reanudar, ya ok)")
                    continue

                # Pre-chequeo de estado
                estado_previo = _estado_modulo(inst_enriquecida, modulo, portal)
                if estado_previo not in ("pendiente",):
                    rec_ejec = {
                        "run_id": _RUN_ID,
                        "institucion_id": inst.id,
                        "modulo": modulo,
                        "estado": estado_previo,
                        "registros_extraidos": 0,
                        "paginas_consultadas": 0,
                        "inicio": datetime.now(timezone.utc).isoformat(),
                        "fin": datetime.now(timezone.utc).isoformat(),
                        "mensaje": f"Pre-chequeo: {estado_previo}",
                    }
                    tabla_ejecucion.append(rec_ejec)
                    if not self.dry_run:
                        _append_ejecucion(rec_ejec)
                    continue

                if self.dry_run:
                    logger.info(f"[DRY RUN] {inst.id} / {modulo}: pendiente")
                    continue

                rec_ejec = _run_modulo(
                    inst_enriquecida, modulo, http, self.max_paginas, self.dry_run
                )
                tabla_ejecucion.append(rec_ejec)
                _append_ejecucion(rec_ejec)

                # Cargar a Staging si corresponde
                if not self.dry_run and self.target in ("stg", "all"):
                    try:
                        from src.load.to_staging import StagingLoader
                        stg = StagingLoader()
                        stg.load_raw_table([rec_ejec], "stg_ejecucion_institucion")
                        records = rec_ejec.get("_records", [])
                        if records:
                            stg_tbl = {"noticias": "stg_publicaciones", "autoridades": "stg_autoridades", "oferta": "stg_oferta", "ces": "stg_ies_ces"}.get(modulo)
                            if stg_tbl:
                                stg.load_raw_table(records, stg_tbl)
                    except Exception as stg_err:
                        logger.warning(f"Error al cargar a staging para {inst.id}/{modulo}: {stg_err}")

                # Acumular datos para staging
                if rec_ejec["estado"] == "ok":
                    key = f"{inst.id}_{modulo}"
                    raw_data_all[key] = rec_ejec.get("_records", [])

            # Rate limit entre instituciones
            time.sleep(0.5)

        self._print_summary(tabla_ejecucion)
        return tabla_ejecucion

    def _print_summary(self, tabla: List[Dict[str, Any]]) -> None:
        """Imprime tabla resumen por institución y módulo."""
        if not tabla:
            print("\n[ces64] Sin registros de ejecución.\n")
            return

        df = pd.DataFrame(tabla)
        print("\n" + "=" * 80)
        print("RESUMEN CES-64 — Tabla de ejecución por institución y módulo")
        print("=" * 80)

        pivot = df.pivot_table(
            index="institucion_id",
            columns="modulo",
            values="estado",
            aggfunc="first",
        ).fillna("—")

        print(pivot.to_string())

        # Conteos por estado
        print("\n--- Conteo global por estado ---")
        counts = df["estado"].value_counts()
        for estado, cnt in counts.items():
            print(f"  {estado:25s}: {cnt}")

        # Registros extraídos
        total_regs = df["registros_extraidos"].sum()
        print(f"\n  Total registros extraídos: {total_regs}")
        print("=" * 80 + "\n")
