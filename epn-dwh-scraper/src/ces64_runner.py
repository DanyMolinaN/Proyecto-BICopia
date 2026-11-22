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
import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import pandas as pd

from src.config import settings
from src.instituciones import load_ces64, InstitucionConfig
from src.scrapers.base_scraper import _RUN_ID
from src.scrapers.noticias_scraper import NoticiasScraper
from src.scrapers.autoridades_scraper import AutoridadesScraper
from src.utils.http_client import HttpClient
from src.utils.logger import setup_logger

logger = setup_logger("ces64_runner")

_BASE_DIR = Path(__file__).resolve().parent.parent
_PORTALES_CSV = _BASE_DIR / "config" / "portales_validados.csv"
_MATRIZ_CSV = _BASE_DIR / "config" / "matriz_fuentes_ies.csv"
_EJECUCION_CSV = _BASE_DIR / "data" / "ejecucion_institucion.csv"

MODULOS_DISPONIBLES = ["ces", "noticias", "autoridades", "facultades", "docentes", "oferta", "todos"]

ESTADOS_VALIDOS = {
    "ok", "parcial", "sin_seccion", "sin_adaptador",
    "bloqueado_robots", "js_requerido", "error_http", "sin_fuente", "no_intentado",
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
# Carga de URLs oficiales y estados de revisión
# ---------------------------------------------------------------------------

def _load_portales() -> Dict[str, Dict[str, str]]:
    """Carga URLs de la matriz de 64 IES y conserva el estado de revisión de cada fuente."""
    legacy: Dict[str, Dict[str, str]] = {}
    if _PORTALES_CSV.exists():
        with _PORTALES_CSV.open(encoding="utf-8-sig", newline="") as f:
            legacy = {r["institucion_id"]: r for r in csv.DictReader(f) if r.get("institucion_id")}

    if not _MATRIZ_CSV.exists():
        logger.warning(f"Matriz de fuentes no encontrada: {_MATRIZ_CSV}")
        return {}

    with _MATRIZ_CSV.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    portales: Dict[str, Dict[str, str]] = {}
    for row in rows:
        code = str(row.get("ces_cod", "")).strip()
        if not code:
            continue
        portal_url = (row.get("portal_url") or "").strip()
        portal_host = (urlparse(portal_url).hostname or "").lower().removeprefix("www.")
        extra_hosts = [
            value.strip().lower().removeprefix("www.").rstrip(".")
            for value in re.split(r"[;\n]+", row.get("dominios_oficiales_adicionales", "") or "")
            if value.strip()
        ]
        official_hosts = list(dict.fromkeys([portal_host, *extra_hosts]))
        portal: Dict[str, str] = {
            "institucion_id": code,
            "portal_url": portal_url,
            "estado": "configurada",
            "robots_permite": legacy.get(code, {}).get("robots_permite", "no_verificado"),
            "es_wordpress": legacy.get(code, {}).get("es_wordpress", "").strip().lower(),
            "dominios_oficiales_adicionales": json.dumps(extra_hosts, ensure_ascii=False),
            "dominios_oficiales_permitidos": json.dumps(official_hosts, ensure_ascii=False),
        }
        for module in ("oferta", "noticias", "autoridades", "facultades", "docentes"):
            raw_urls = row.get(f"url_{module}", "") or ""
            urls = []
            for value in re.split(r"[;\n]+", raw_urls):
                value = value.strip()
                parsed = urlparse(value)
                host = (parsed.hostname or "").lower().removeprefix("www.")
                if parsed.scheme != "https" or not host or not portal_host:
                    continue
                if any(host == official or host.endswith("." + official) for official in official_hosts if official):
                    urls.append(value)
                else:
                    logger.warning(f"[{code}] URL fuera del portal oficial en {module}; se omite: {value}")
            urls = list(dict.fromkeys(urls))
            portal[f"url_{module}_urls"] = json.dumps(urls, ensure_ascii=False)
            portal[f"estado_{module}"] = (row.get(f"estado_{module}") or "").strip()
            portal[f"url_{module}"] = urls[0] if urls else ""
        portales[code] = portal

    if len(portales) != 64:
        logger.warning(f"La matriz contiene {len(portales)} códigos CES únicos; se esperaban 64.")
    return portales


def _urls_for(portal: Optional[Dict[str, str]], module: str) -> List[str]:
    if not portal:
        return []
    raw_urls = portal.get(f"url_{module}_urls")
    if raw_urls:
        try:
            urls = json.loads(raw_urls)
            if isinstance(urls, list) and urls:
                return urls
        except (TypeError, json.JSONDecodeError):
            pass
    single_url = portal.get(f"url_{module}")
    return [single_url] if single_url else []

# ---------------------------------------------------------------------------
# Enriquecimiento de InstitucionConfig con fuentes de la matriz
# ---------------------------------------------------------------------------

def _build_inst_from_portal(
    inst: InstitucionConfig, portal: Optional[Dict[str, str]]
) -> InstitucionConfig:
    """Devuelve una InstitucionConfig enriquecida con las URLs oficiales de la matriz.

    No modifica el objeto original; crea una copia ligera mediante monkey-patch.
    """
    if not portal:
        return inst

    # Enriquecer endpoints con las URLs de la matriz, sin usar endpoints EPN de respaldo.
    new_endpoints = dict(inst.endpoints)
    new_endpoints["dominios_oficiales_adicionales"] = portal.get("dominios_oficiales_adicionales", "[]")
    endpoint_names = {
        "oferta": "oferta_grado",
        "noticias": "noticias_web",
        "autoridades": "autoridades",
        "facultades": "facultades",
        "docentes": "docentes",
    }
    for module in ("oferta", "noticias", "autoridades", "facultades", "docentes"):
        urls = _urls_for(portal, module)
        endpoint = endpoint_names[module]
        if urls:
            new_endpoints[f"{module}_urls"] = json.dumps(urls, ensure_ascii=False)
            new_endpoints[endpoint] = urls[0]
        else:
            new_endpoints.pop(f"{module}_urls", None)
            new_endpoints.pop(endpoint, None)
        new_endpoints[f"estado_{module}"] = portal.get(f"estado_{module}", "")

    news_urls = _urls_for(portal, "noticias")
    news_host_url = news_urls[0] if news_urls else portal.get("portal_url", "")
    news_path = urlparse(news_host_url).path.lower()
    is_wordpress = portal.get("es_wordpress") == "si" or any(
        marker in news_path for marker in ("/category/", "/portalwp/", "/wp-json/")
    )
    if is_wordpress and news_host_url:
        parsed_news_url = urlparse(news_host_url)
        api_base = f"{parsed_news_url.scheme}://{parsed_news_url.netloc}"
        new_endpoints["noticias_api"] = api_base.rstrip("/") + "/wp-json/wp/v2/posts"
    else:
        new_endpoints.pop("noticias_api", None)

    portal_url = portal.get("portal_url", inst.base_url)
    new_endpoints["robots_txt"] = portal_url.rstrip("/") + "/robots.txt"

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
        "adaptador": "wordpress" if is_wordpress else "html",
        "estado_integracion": inst.estado_integracion,
        "observaciones": inst.observaciones,
    })
    return clone


# ---------------------------------------------------------------------------
# Determinación del estado de módulo
# ---------------------------------------------------------------------------



def _estado_modulo(inst: InstitucionConfig, modulo: str, portal: Optional[Dict]) -> str:
    """Decide el estado inicial de un módulo antes de ejecutarlo."""
    if modulo == "ces":
        return "pendiente"

    if not portal:
        return "sin_seccion"

    # Robots tiene prioridad sobre la disponibilidad de las secciones.
    if portal.get("robots_permite") == "no":
        return "bloqueado_robots"

    if modulo in ("noticias", "autoridades", "oferta", "facultades", "docentes"):
        urls = _urls_for(portal, modulo)

        if not urls:
            if modulo == "noticias" and portal.get("portal_url"):
                return "pendiente"
            return "sin_seccion"

        # Noticias requiere un adaptador WordPress en esta implementación.
        if modulo == "noticias" and inst.adaptador != "wordpress":
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
        "limite_paginas_alcanzado": False,
        "_records": [],
    }

    peticiones_inicio = getattr(http_client, "stats", {}).get("urls_consultadas", 0)
    details_inicio = len(getattr(http_client, "stats", {}).get("detalles", []))
    try:
        records: List[Dict] = []
        scraper = None

        if modulo == "noticias":
            scraper = NoticiasScraper(
                http_client=http_client,
                institucion_id=inst.id,
                max_paginas=max_paginas,
                institucion=inst,
            )
            records = scraper.extract()
            rec_ejec["_urls_descubiertas"] = list(getattr(scraper, "discovered_source_urls", []))

        elif modulo == "autoridades":
            try:
                faculty_urls = json.loads(inst.endpoints.get("facultades_urls", "[]"))
            except (TypeError, json.JSONDecodeError):
                faculty_urls = []
            scraper = AutoridadesScraper(
                http_client=http_client,
                institucion_id=inst.id,
                facultad_urls=[(url, "") for url in faculty_urls],
                institucion=inst,
            )
            records = scraper.extract()

        elif modulo in ("facultades", "docentes"):
            from src.scrapers.directorio_ies_scraper import DirectorioIEScraper
            scraper = DirectorioIEScraper(
                http_client=http_client,
                institucion_id=inst.id,
                institucion=inst,
            )
            if modulo == "facultades":
                records = scraper.extract_faculties(max_pages=max_paginas)
            else:
                records = scraper.extract_teachers(max_pages=max_paginas)

        elif modulo == "oferta":
            from src.scrapers.oferta_enlaces_scraper import OfertaEnlacesScraper
            scraper = OfertaEnlacesScraper(
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

        for record in records:
            record.setdefault("ces_cod", inst.ces_cod or inst.id)
            record.setdefault("nombre_ies", inst.nombre)
            record.setdefault("provincia", inst.provincia)
            record.setdefault("canton", inst.canton)
            record.setdefault("portal_url", inst.base_url)
            record.setdefault("estado_fuente_configurada", inst.endpoints.get(f"estado_{modulo}", ""))

        peticiones_fin = getattr(http_client, "stats", {}).get("urls_consultadas", 0)
        network_details = getattr(http_client, "stats", {}).get("detalles", [])[details_inicio:]
        try:
            source_urls = json.loads(inst.endpoints.get(f"{modulo}_urls", "[]"))
        except (TypeError, json.JSONDecodeError):
            source_urls = [inst.endpoints.get({"oferta": "oferta_grado", "noticias": "noticias_web"}.get(modulo, modulo), "")]
        source_hosts = {
            (urlparse(url).hostname or "").lower().removeprefix("www.")
            for url in source_urls if url
        }
        initial_details = [
            item for item in getattr(http_client, "initial_network_details", [])
            if (urlparse(item.get("url", "")).hostname or "").lower().removeprefix("www.") in source_hosts
        ]
        network_details = initial_details + network_details
        def is_expected_optional_wp_endpoint_404(item: Dict[str, Any]) -> bool:
            path = urlparse(item.get("url", "")).path.lower()
            return modulo == "noticias" and item.get("estado") in ("http_400", "http_404") and any(
                endpoint in path for endpoint in ("/wp-json/wp/v2/posts", "/wp-json/wp/v2/categories")
            )

        failures = [
            item for item in network_details
            if item.get("estado", "") not in ("cache_hit", "descargada_200", "robots_http_404", "robots_http_410")
            and not is_expected_optional_wp_endpoint_404(item)
        ]
        blocked = any("robots" in item.get("estado", "") for item in failures)
        network_problem = bool(failures)
        consultadas = peticiones_fin - peticiones_inicio
        rec_ejec["paginas_consultadas"] = max(1, consultadas) if records else consultadas
        rec_ejec["registros_extraidos"] = len(records)
        rec_ejec["_records"] = records
        rec_ejec["limite_paginas_alcanzado"] = bool(getattr(scraper, "max_pages_reached", False))

        if modulo == "noticias" and rec_ejec["limite_paginas_alcanzado"]:
            rec_ejec["estado"] = "parcial"
            rec_ejec["mensaje"] = f"Se alcanzó max_paginas={max_paginas}; revisar cobertura del archivo histórico."
        elif modulo == "noticias" and records and any(not row.get("fecha_publicacion") for row in records):
            missing_dates = sum(not row.get("fecha_publicacion") for row in records)
            rec_ejec["estado"] = "parcial"
            rec_ejec["mensaje"] = f"{len(records)} noticias extraídas; {missing_dates} no tienen fecha verificable."
        elif modulo == "oferta" and records:
            links = [
                r for r in records
                if r.get("tipo_registro") in (
                    "programa_candidato", "programa_candidato_html", "programa_candidato_pdf",
                    "documento_catalogo_pdf",
                    "enlace_no_clasificado", "enlace_oficial_con_titulo",
                )
            ]
            if links:
                rec_ejec["estado"] = "parcial"
                pdf_only = all(row.get("tipo_registro") == "documento_catalogo_pdf" for row in links)
                rec_ejec["mensaje"] = (
                    f"{len(links)} documentos de oferta encontrados; el texto PDF no se pudo convertir en carreras."
                    if pdf_only else
                    f"{len(links)} candidatos de programa extraídos; falta validar nivel, modalidad y vigencia."
                )
            else:
                rec_ejec["estado"] = "sin_seccion"
                rec_ejec["mensaje"] = "La página oficial respondió, pero no expuso enlaces clasificables."
        elif modulo == "ces" and records:
            st = records[0].get("estado_extraccion", "ok")
            rec_ejec["estado"] = "ok" if st == "ok" else ("parcial" if st == "parcial" else "error_http")
            rec_ejec["mensaje"] = f"Ficha CES: {records[0].get('nombre_ces') or 'sin nombre'}"
        elif modulo == "autoridades" and records:
            ambiguous = sum(
                row.get("cargo_normalizado") == "Otro"
                or row.get("cargo") == "Autoridad Universitaria"
                for row in records
            )
            rec_ejec["estado"] = "parcial" if network_problem or ambiguous else "ok"
            rec_ejec["mensaje"] = f"{len(records)} autoridades extraídas; {ambiguous} cargos requieren revisión."
        elif modulo == "facultades" and records:
            without_dean = sum(not row.get("decano") for row in records)
            rec_ejec["estado"] = "parcial" if network_problem or without_dean else "ok"
            rec_ejec["mensaje"] = f"{len(records)} unidades extraídas; {without_dean} sin decano visible."
        elif modulo == "docentes" and records:
            rec_ejec["estado"] = "parcial"
            rec_ejec["mensaje"] = f"{len(records)} nombres docentes capturados; afiliación y vigencia requieren validación."
        elif records:
            rec_ejec["estado"] = "parcial" if network_problem else "ok"
            rec_ejec["mensaje"] = f"{len(records)} registros extraídos"
            if network_problem:
                rec_ejec["mensaje"] += "; hubo fallos de red en páginas relacionadas"
        elif blocked:
            rec_ejec["estado"] = "bloqueado_robots"
            robot_reasons = list(dict.fromkeys(
                item.get("estado", "") for item in failures
                if "robots" in item.get("estado", "")
            ))
            rec_ejec["mensaje"] = "Acceso detenido por robots.txt" + (
                f" ({', '.join(robot_reasons[:3])})" if robot_reasons else ""
            )
        elif network_problem:
            rec_ejec["estado"] = "error_http"
            rec_ejec["mensaje"] = "No se pudo descargar o interpretar la fuente: " + "; ".join(
                dict.fromkeys(item.get("estado", "error") for item in failures[:3])
            )
        else:
            rec_ejec["estado"] = "sin_seccion"
            rec_ejec["mensaje"] = "La fuente respondió, pero no se reconocieron registros del módulo"

    except Exception as exc:
        msg = str(exc)[:200]
        rec_ejec["estado"] = "error_http" if "HTTP" in msg or "Connection" in msg else "parcial"
        rec_ejec["mensaje"] = msg
        logger.exception(f"[{inst.id}] Error en módulo {modulo}: {msg}")

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
        self.modulos = modulos or ["noticias", "autoridades", "facultades", "docentes", "oferta"]
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

            # HttpClient por IES: usa robots del portal y conserva cada corrida en su propia carpeta.
            http = None
            needs_http = any(
                _urls_for(portal, module)
                for module in self.modulos
                if module in ("oferta", "autoridades", "noticias", "facultades", "docentes")
            )
            needs_http = needs_http or bool(portal and portal.get("portal_url") and "noticias" in self.modulos)
            if not self.dry_run and needs_http:
                http = HttpClient(
                    use_cache=self.use_cache,
                    force_refresh=self.force_refresh,
                    institucion_id=inst.id,
                    run_id=_RUN_ID,
                    per_institution_raw=True,
                    robots_url=(portal.get("portal_url", inst.base_url) if portal else inst.base_url).rstrip("/") + "/robots.txt",
                    official_hosts=json.loads(portal.get("dominios_oficiales_permitidos", "[]")) if portal else None,
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
                    module_urls = _urls_for(portal, modulo)
                    rec_ejec = {
                        "run_id": _RUN_ID,
                        "institucion_id": inst.id,
                        "modulo": modulo,
                        "estado": estado_previo,
                        "registros_extraidos": 0,
                        "paginas_consultadas": 0,
                        "inicio": datetime.now(timezone.utc).isoformat(),
                        "fin": datetime.now(timezone.utc).isoformat(),
                        "fuente_url": "; ".join(module_urls),
                        "estado_fuente_configurada": portal.get(f"estado_{modulo}", "") if portal else "",
                        "mensaje": f"Pre-chequeo: {estado_previo}; {portal.get(f'estado_{modulo}', '') if portal else 'sin matriz para esta IES'}",
                    }
                    tabla_ejecucion.append(rec_ejec)
                    if not self.dry_run:
                        _append_ejecucion(rec_ejec)
                    continue

                if self.dry_run:
                    module_urls = _urls_for(portal, modulo)
                    rec_ejec = {
                        "run_id": _RUN_ID,
                        "institucion_id": inst.id,
                        "modulo": modulo,
                        "estado": "no_intentado",
                        "registros_extraidos": 0,
                        "paginas_consultadas": 0,
                        "inicio": datetime.now(timezone.utc).isoformat(),
                        "fin": datetime.now(timezone.utc).isoformat(),
                        "fuente_url": "; ".join(module_urls),
                        "estado_fuente_configurada": portal.get(f"estado_{modulo}", "") if portal else "",
                        "mensaje": "DRY RUN: URL lista para extraer" if module_urls else "DRY RUN: sin URL oficial configurada",
                    }
                    tabla_ejecucion.append(rec_ejec)
                    logger.info(f"[DRY RUN] {inst.id} / {modulo}: {rec_ejec['mensaje']}")
                    continue

                rec_ejec = _run_modulo(
                    inst_enriquecida, modulo, http, self.max_paginas, self.dry_run
                )
                configured_urls = _urls_for(portal, modulo)
                discovered_urls = rec_ejec.pop("_urls_descubiertas", [])
                rec_ejec["fuente_url"] = "; ".join(configured_urls or discovered_urls)
                rec_ejec["estado_fuente_configurada"] = portal.get(f"estado_{modulo}", "") if portal else ""
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
                if rec_ejec["estado"] in ("ok", "parcial"):
                    key = f"{inst.id}_{modulo}"
                    raw_data_all[key] = rec_ejec.get("_records", [])

            # Rate limit entre instituciones
            if not self.dry_run:
                time.sleep(0.5)

        if not self.dry_run:
            self._save_run_artifacts(tabla_ejecucion)
        self._print_summary(tabla_ejecucion)
        return tabla_ejecucion

    def _save_run_artifacts(self, rows: List[Dict[str, Any]]) -> Path:
        """Guarda los registros parseados y la cobertura en una carpeta por corrida."""
        run_dir = settings.data_raw_dir / "hito2" / _RUN_ID
        run_dir.mkdir(parents=True, exist_ok=True)
        if _MATRIZ_CSV.exists():
            shutil.copy2(_MATRIZ_CSV, run_dir / "matriz_fuentes_ies.csv")

        module_columns = {
            "noticias": ["institucion_id", "fecha_extraccion", "run_id", "fuente_url", "post_id", "fecha_publicacion", "fecha_modificacion", "titulo", "categoria", "categoria_origen", "tipo_publicacion", "tipo_origen", "resumen", "url", "hash_registro"],
            "autoridades": ["institucion_id", "fecha_extraccion", "run_id", "fuente_url", "nombre_completo", "cargo_original", "cargo_normalizado", "unidad_adscripcion", "condicion_designacion", "evidencia_condicion", "es_titular", "periodo_gestion", "fecha_observacion", "hash_registro"],
            "oferta": ["institucion_id", "fecha_extraccion", "run_id", "fuente_url", "url_oferta", "estado_fuente_configurada", "tipo_registro", "nombre_programa_bruto", "url_programa", "texto_contexto_bruto", "titulo_pagina", "area_contenido", "nivel_formacion", "estado_programa", "periodo_consulta", "hash_registro"],
            "facultades": ["institucion_id", "fecha_extraccion", "run_id", "fuente_url", "nombre_facultad", "url_facultad", "decano", "subdecano", "texto_contexto_bruto", "estado_dato", "hash_registro"],
            "docentes": ["institucion_id", "fecha_extraccion", "run_id", "fuente_url", "nombre_completo", "cargo_docente", "unidad_adscripcion", "url_perfil", "texto_contexto_bruto", "estado_dato", "hash_registro"],
        }
        combined: Dict[str, List[Dict[str, Any]]] = {module: [] for module in module_columns}
        coverage = []
        names = {inst.id: inst.nombre for inst in self._registry.all()}
        period = {
            "oferta": "páginas oficiales configuradas; consulta 2026; nivel/vigencia por validar",
            "autoridades": "observación en fecha de extracción de 2026",
            "noticias": "publicaciones del 2024-01-01 al 2025-12-31",
            "facultades": "directorio oficial observado en fecha de extraccion",
            "docentes": "directorio oficial observado en fecha de extraccion; vigencia por confirmar",
        }
        for row in rows:
            module = row.get("modulo", "")
            if module not in combined:
                continue
            combined[module].extend(row.get("_records", []))
            portal = self._portales.get(row.get("institucion_id", ""), {})
            coverage.append({
                "run_id": _RUN_ID,
                "institucion_id": row.get("institucion_id", ""),
                "nombre_ies": names.get(row.get("institucion_id", ""), ""),
                "modulo": module,
                "periodo_objetivo": period[module],
                "url_fuente": row.get("fuente_url", "; ".join(_urls_for(portal, module))),
                "estado_fuente_configurada": row.get("estado_fuente_configurada", portal.get(f"estado_{module}", "")),
                "estado_extraccion": row.get("estado", ""),
                "registros_extraidos": row.get("registros_extraidos", 0),
                "paginas_consultadas": row.get("paginas_consultadas", 0),
                "limite_paginas_alcanzado": row.get("limite_paginas_alcanzado", False),
                "fecha_inicio_utc": row.get("inicio", ""),
                "fecha_fin_utc": row.get("fin", ""),
                "mensaje": row.get("mensaje", ""),
            })

        for module, records in combined.items():
            extra_columns = [key for record in records for key in record if key not in module_columns[module]]
            columns = list(dict.fromkeys(module_columns[module] + extra_columns))
            (run_dir / f"{module}_raw.json").write_text(
                json.dumps(records, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
            pd.DataFrame(records, columns=columns).to_csv(
                run_dir / f"{module}_raw.csv", index=False, encoding="utf-8-sig"
            )

        coverage_df = pd.DataFrame(coverage)
        coverage_df.to_csv(run_dir / "cobertura_extraccion.csv", index=False, encoding="utf-8-sig")
        inventory_columns = {
            "run_id": "run_id",
            "institucion_id": "institucion_id",
            "nombre_ies": "entidad",
            "modulo": "fuente_id",
            "url_fuente": "enlace_exacto",
            "periodo_objetivo": "periodo_cubierto",
            "estado_fuente_configurada": "estado_revision_fuente",
            "registros_extraidos": "numero_filas",
            "fecha_fin_utc": "fecha_descarga_utc",
            "estado_extraccion": "estado_extraccion",
        }
        inventory = coverage_df.rename(columns=inventory_columns)
        inventory["formato_conector"] = "HTML/JSON; web scraping"
        inventory["frecuencia_actualizacion"] = "captura puntual; repetir ejecución para actualizar"
        inventory.to_csv(run_dir / "inventario_fuentes.csv", index=False, encoding="utf-8-sig")
        manifest = {
            "run_id": _RUN_ID,
            "fecha_generacion_utc": datetime.now(timezone.utc).isoformat(),
            "fuente_configuracion": "matriz_fuentes_ies.csv",
            "periodos_objetivo": period,
            "archivos": ["matriz_fuentes_ies.csv", "oferta_raw.csv", "autoridades_raw.csv", "noticias_raw.csv", "facultades_raw.csv", "docentes_raw.csv", "cobertura_extraccion.csv", "inventario_fuentes.csv"],
            "html_y_json_originales": "data/raw/<fecha>/<ces_cod>/<run_id>/ (guardados por HttpClient)",
            "nota": "Los enlaces de oferta se guardan sin afirmar carrera, nivel o vigencia; los datos quedan sin limpieza analítica.",
        }
        (run_dir / "manifiesto.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"Artefactos crudos versionados guardados en: {run_dir}")
        return run_dir

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

        print("\n--- URLs oficiales presentes en la matriz ---")
        for module in ("oferta", "autoridades", "noticias", "facultades", "docentes"):
            configured = sum(bool(_urls_for(portal, module)) for portal in self._portales.values())
            print(f"  {module:25s}: {configured}/{len(self._portales)}")

        # Registros extraídos
        total_regs = df["registros_extraidos"].sum()
        print(f"\n  Total registros extraídos: {total_regs}")
        print("=" * 80 + "\n")
