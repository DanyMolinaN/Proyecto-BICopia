"""
CesPerfilScraper: extrae la ficha institucional del CES para cada IES.

Fase 2 del prompt PROMPT_Extraccion_64_IES_CES.md.

Por cada fila del catálogo (config/catalogo_ces.csv) descarga la ficha en
https://www.ces.gob.ec/?page_id=25&cod={ces_cod}&codp={ces_codp}
y extrae: nombre, sede, siglas, dirección, fecha de creación, tipo,
rector/a, fecha_inicio_gestion, fecha_fin_gestion y el label crudo del cargo.

Reglas:
- 64 peticiones máximo (una por IES), con caché, 1 s de pausa mínima.
- El nombre extraído se valida contra el catálogo (normalización de tildes).
  Las discrepancias se registran como campo discrepancia_nombre=True; NO se corrigen.
- Registra cada URL en manifest.csv del HttpClient.
- Staging: tabla stg_ies_ces sin transformar, con metadatos estándar.
- Si la ficha cambia de estructura, el registro queda estado_extraccion='parcial'/'error'.
"""

import csv
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from src.config import settings
from src.scrapers.base_scraper import BaseScraper
from src.utils.http_client import HttpClient
from src.utils.logger import setup_logger

logger = setup_logger("ces_perfil_scraper")

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
_CATALOGO_PATH = _BASE_DIR / "config" / "catalogo_ces.csv"

CES_FICHA_URL = "https://www.ces.gob.ec/?page_id=25&cod={ces_cod}&codp={ces_codp}"


def _normalize(text: str) -> str:
    """Elimina tildes y convierte a mayúsculas para comparación."""
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).upper().strip()


def _load_catalogo() -> List[Dict[str, str]]:
    """Carga config/catalogo_ces.csv y devuelve lista de dicts."""
    if not _CATALOGO_PATH.exists():
        raise FileNotFoundError(f"Catálogo CES no encontrado: {_CATALOGO_PATH}")
    rows = []
    with open(_CATALOGO_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


class CesPerfilScraper(BaseScraper):
    """Extrae las fichas institucionales del Consejo de Educación Superior (CES)."""

    CES_BASE = "https://www.ces.gob.ec"

    def __init__(
        self,
        http_client: Optional[HttpClient] = None,
        institucion_ids: Optional[List[str]] = None,
    ) -> None:
        """
        Args:
            http_client: cliente HTTP ya inicializado.
            institucion_ids: lista de ces_cod (str) a procesar. None = todas las 64.
        """
        # BaseScraper con institucion_id genérico; cada registro lleva el suyo
        super().__init__(http_client=http_client, institucion_id="CES")
        self._target_ids = set(institucion_ids) if institucion_ids else None

    # ------------------------------------------------------------------
    # Parseo de la ficha del CES
    # ------------------------------------------------------------------
    def _parse_ficha(self, html: str, url: str, row: Dict[str, str]) -> Dict[str, Any]:
        """Extrae los campos de una ficha institucional del CES.

        Returns un dict con estado_extraccion in {ok, parcial, error}.
        """
        rec: Dict[str, Any] = {
            "ces_cod": row["ces_cod"],
            "ces_codp": row["ces_codp"],
            "tipo_ces": row["tipo_ces"],
            "nombre_catalogo": row["nombre"],
            "provincia_catalogo": row["provincia"],
            "canton_catalogo": row["canton"],
            "ces_url": url,
            # Campos extraídos (NULL hasta confirmar)
            "nombre_ces": None,
            "sede": None,
            "siglas_ces": None,
            "direccion": None,
            "fecha_creacion": None,
            "tipo_institucional_ces": None,
            "rector_nombre": None,
            "cargo_rector_original": None,
            "fecha_inicio_gestion": None,
            "fecha_fin_gestion": None,
            "discrepancia_nombre": False,
            "estado_extraccion": "error",
            "motivo_error": None,
        }

        try:
            soup = BeautifulSoup(html, "html.parser")

            # El CES usa una tabla o sección con etiquetas label: valor
            # Intentamos múltiples estrategias de extracción

            # Estrategia 1: Tablas con th/td
            tables = soup.find_all("table")
            kv: Dict[str, str] = {}
            for tbl in tables:
                for tr in tbl.find_all("tr"):
                    cells = tr.find_all(["th", "td"])
                    if len(cells) >= 2:
                        key = cells[0].get_text(strip=True).lower()
                        val = cells[1].get_text(separator=" ", strip=True)
                        kv[key] = val

            # Estrategia 2: divs con etiqueta label + span/div valor
            for div in soup.find_all("div", class_=re.compile(r"field|info|dato", re.I)):
                label_tag = div.find(class_=re.compile(r"label|title|key", re.I))
                val_tag = div.find(class_=re.compile(r"value|content|data", re.I))
                if label_tag and val_tag:
                    key = label_tag.get_text(strip=True).lower()
                    val = val_tag.get_text(separator=" ", strip=True)
                    kv[key] = val

            # Estrategia 3: párrafos con patrón "Clave: Valor"
            for p in soup.find_all(["p", "div", "span", "li"]):
                text = p.get_text(separator="|", strip=True)
                m = re.match(r"^([^:|]{3,40})[:|]\s*(.+)$", text)
                if m:
                    key = m.group(1).strip().lower()
                    val = m.group(2).strip()
                    if key not in kv:
                        kv[key] = val

            # Mapeo de claves comunes del CES
            def _get(*keys: str) -> Optional[str]:
                for k in keys:
                    for stored_k, v in kv.items():
                        if k in stored_k:
                            return v.strip() or None
                return None

            rec["nombre_ces"] = _get("nombre", "institución", "institucion")
            rec["sede"] = _get("sede", "ciudad", "cantón", "canton")
            rec["siglas_ces"] = _get("sigla", "abreviatura", "acrónimo", "acronimo")
            rec["direccion"] = _get("dirección", "direccion", "domicilio")
            rec["fecha_creacion"] = _get("creación", "creacion", "fundación", "fundacion")
            rec["tipo_institucional_ces"] = _get("tipo", "financiamiento", "categoría", "categoria")
            rec["rector_nombre"] = _get("rector", "representante legal", "autoridad")
            rec["cargo_rector_original"] = _get("cargo", "denominación", "denominacion")
            rec["fecha_inicio_gestion"] = _get("inicio de gestión", "inicio gestión", "inicio gestion", "fecha inicio")
            rec["fecha_fin_gestion"] = _get("fin de gestión", "fin gestión", "fin gestion", "fecha fin")

            # Validación de nombre (normalización de tildes y mayúsculas)
            if rec["nombre_ces"]:
                norm_ces = _normalize(rec["nombre_ces"])
                norm_cat = _normalize(row["nombre"])
                rec["discrepancia_nombre"] = norm_ces != norm_cat
                rec["estado_extraccion"] = "ok"
            else:
                # Contenido parcial: se obtuvo HTML pero no el nombre
                campos_ok = sum(1 for f in [
                    rec["sede"], rec["rector_nombre"],
                    rec["fecha_inicio_gestion"]
                ] if f)
                rec["estado_extraccion"] = "parcial" if campos_ok > 0 else "error"
                rec["motivo_error"] = "nombre_no_extraido"

        except Exception as exc:
            rec["estado_extraccion"] = "error"
            rec["motivo_error"] = str(exc)[:200]

        return rec

    # ------------------------------------------------------------------
    # extract()
    # ------------------------------------------------------------------
    def extract(self) -> List[Dict[str, Any]]:
        """Descarga y parsea las fichas CES de las IES configuradas."""
        catalogo = _load_catalogo()
        if self._target_ids:
            catalogo = [r for r in catalogo if r["ces_cod"] in self._target_ids]

        results: List[Dict[str, Any]] = []

        for row in catalogo:
            ces_cod = row["ces_cod"]
            ces_codp = row["ces_codp"]
            url = CES_FICHA_URL.format(ces_cod=ces_cod, ces_codp=ces_codp)

            self.logger.info(f"[CES] Descargando ficha cod={ces_cod}: {row['nombre'][:50]}")

            html = self.http_client.get(url)
            if html is None:
                rec = {
                    "ces_cod": ces_cod,
                    "ces_codp": ces_codp,
                    "tipo_ces": row["tipo_ces"],
                    "nombre_catalogo": row["nombre"],
                    "provincia_catalogo": row["provincia"],
                    "canton_catalogo": row["canton"],
                    "ces_url": url,
                    "estado_extraccion": "error_http",
                    "motivo_error": "HTTP no 200 o bloqueado",
                    "nombre_ces": None,
                    "rector_nombre": None,
                    "fecha_inicio_gestion": None,
                    "fecha_fin_gestion": None,
                    "discrepancia_nombre": False,
                }
            else:
                rec = self._parse_ficha(html, url, row)

            # Metadatos de trazabilidad (institucion_id = ces_cod para esta fuente)
            rec["fecha_extraccion"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            rec["run_id"] = self._run_id
            rec = self._add_traceability(rec, fuente_url=url)
            # Sobreescribir institucion_id con el ces_cod de esta IES
            rec["institucion_id"] = str(ces_cod)
            results.append(rec)

            # Logging de discrepancias
            if rec.get("discrepancia_nombre"):
                self.logger.warning(
                    f"[CES cod={ces_cod}] Discrepancia de nombre: "
                    f"catálogo='{row['nombre']}' | CES='{rec.get('nombre_ces')}'"
                )

        ok = sum(1 for r in results if r.get("estado_extraccion") == "ok")
        parcial = sum(1 for r in results if r.get("estado_extraccion") == "parcial")
        error = sum(1 for r in results if "error" in str(r.get("estado_extraccion", "")))
        self.logger.info(
            f"[CES] Fichas procesadas: {len(results)} total | {ok} ok | {parcial} parcial | {error} error"
        )
        return results
