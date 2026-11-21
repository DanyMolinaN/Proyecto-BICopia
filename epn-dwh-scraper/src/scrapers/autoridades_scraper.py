"""
Extractor de autoridades institucionales y directivos academicos.

Mejoras del Hito 2 (Fase D):
  D1. condicion_designacion (titular/encargado/subrogante/no_determinado) + evidencia_condicion.
      es_titular se mantiene derivado solo cuando hay evidencia.
  D2. cargo_original + cargo_normalizado (catálogo).
  D3. Deduplicación por (institucion_id, nombre, cargo, unidad) con log de descartados.
  D4. URLs de facultad desde FacultadesScraper (no lista dura).
  D5. fecha_observacion (fecha de captura) explícita.
  D6. Minimización de datos: sin correo ni bio si no responden P2.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from bs4 import BeautifulSoup

from src.config import settings
from src.scrapers.base_scraper import BaseScraper
from src.utils.helpers import clean_text, extract_email, remove_accents


# ─────────────────────────────────────────────────────────────────────────────
# D2: Catálogo de cargos normalizados
# ─────────────────────────────────────────────────────────────────────────────
_CARGO_CATALOGO = [
    # (keywords, cargo_normalizado)
    (["rector"], "Rector"),
    (["vicerrector"], "Vicerrector"),
    (["decano", "decana"], "Decano"),
    (["subdecano", "subdecana"], "Subdecano"),
    (["director", "directora"], "Director"),
    (["secretario", "secretaria"], "Otro"),
]


def _normalizar_cargo(cargo_texto: str) -> str:
    """Mapea texto libre de cargo a un valor del catálogo."""
    norma = remove_accents(cargo_texto.lower())
    for keywords, normalizado in _CARGO_CATALOGO:
        if any(kw in norma for kw in keywords):
            return normalizado
    return "Otro"


# ─────────────────────────────────────────────────────────────────────────────
# D1: Condición de designación
# ─────────────────────────────────────────────────────────────────────────────
def _detectar_condicion(cargo_texto: str) -> Tuple[str, str]:
    """Detecta la condición de designación a partir del texto del cargo.

    Returns:
        Tuple[str, str]: (condicion, evidencia_condicion).
    """
    texto = cargo_texto.strip()
    norma = remove_accents(texto.lower())

    if re.search(r"\(e\)", texto, re.IGNORECASE) or "encargad" in norma:
        return "encargado", f'Texto fuente contiene indicador de encargo: "{texto}"'
    if "subrogante" in norma:
        return "subrogante", f'Texto fuente contiene "subrogante": "{texto}"'
    if re.search(r"\btitular\b", norma):
        return "titular", f'Texto fuente menciona "titular": "{texto}"'

    # Sin evidencia explícita → no_determinado (D1)
    return "no_determinado", ""


class AutoridadesScraper(BaseScraper):
    """Extrae las autoridades centrales y de unidades academicas de una IES."""

    def __init__(
        self,
        http_client=None,
        institucion_id=None,
        facultad_urls: Optional[List[Tuple[str, str]]] = None,
        institucion=None,
    ) -> None:
        """
        Args:
            facultad_urls: Lista de (url, nombre_facultad) suministrada externamente (D4).
                Si es None, se usa la lista dura de la EPN como respaldo.
            institucion: Configuración inyectada de la institución (regla 2).
        """
        super().__init__(
            http_client=http_client,
            institucion_id=institucion_id,
            institucion=institucion,
        )
        self._facultad_urls = facultad_urls  # D4

    # D5: fecha de captura
    @property
    def _fecha_observacion(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _extract_authorities_from_main_page(self) -> List[Dict[str, Any]]:
        """Extrae las autoridades listadas en la página central de autoridades."""
        from src.config import settings as cfg
        from src.instituciones import registry

        inst = self.institucion or registry.get(self.institucion_id)
        if inst and inst.base_url:
            url = inst.get_endpoint("autoridades") or f"{inst.base_url}/autoridades/"
        elif inst:
            url = inst.get_endpoint("autoridades") or ""
        else:
            url = cfg.endpoints.get("autoridades", f"{cfg.base_url}/autoridades/")

        if not url:
            self.logger.warning(f"[{self.institucion_id}] Sin URL configurada para autoridades.")
            return []

        html_content = self.http_client.get(url)
        if not html_content:
            self.logger.warning(f"[{self.institucion_id}] No se pudo descargar autoridades desde {url}")
            return []

        soup = BeautifulSoup(html_content, "html.parser")
        authorities: List[Dict[str, Any]] = []

        elements = soup.find_all(["h2", "h3", "p"])
        current_name = None
        current_cargo = None
        current_unidad = "Rectorado / Gobierno Central"
        current_bio: List[str] = []
        seen_names = set()

        for el in elements:
            text = clean_text(el.get_text())
            if not text or "ACCESOS" in text or "MAXIMAS" in text.upper():
                continue

            if "DECANOS DE LAS" in text.upper() or "DECANOS" in text.upper():
                current_unidad = "Facultades"
                continue

            is_name_header = bool(
                re.match(r"^(Dr\.|Dra\.|Ing\.|Msc\.|Ph\.D\.|Lic\.)\s+[A-ZÁÉÍÓÚ]", text)
            )

            if el.name in ["h2", "h3"] or is_name_header:
                if is_name_header or (
                    len(text.split()) >= 3
                    and not any(k in text.upper() for k in ["VICERRECTOR", "RECTOR", "DECAN"])
                ):
                    if current_name and current_name not in seen_names and (
                        current_cargo or current_bio
                    ):
                        rec = self._build_record(
                            name=current_name,
                            cargo=current_cargo or "Autoridad Universitaria",
                            unidad=current_unidad,
                            url=url,
                            bio=" ".join(current_bio) if current_bio else None,
                        )
                        authorities.append(rec)
                        seen_names.add(current_name)

                    current_name = text
                    current_cargo = None
                    current_bio = []
                    continue

            if any(
                k in text.upper()
                for k in ["RECTOR", "VICERRECTOR", "VICERRECTORA", "DECANO", "DECANA", "SUBDECANO", "DIRECTOR"]
            ):
                if not current_cargo:
                    current_cargo = text
                    continue

            if "Facultad de" in text or "Escuela de Formación" in text:
                current_unidad = text
                if not current_cargo:
                    current_cargo = f"Decano(a) - {text}"
                continue

            if current_name and len(text) > 30:
                current_bio.append(text)

        if current_name and current_name not in seen_names:
            rec = self._build_record(
                name=current_name,
                cargo=current_cargo or "Autoridad Universitaria",
                unidad=current_unidad,
                url=url,
                bio=" ".join(current_bio) if current_bio else None,
            )
            authorities.append(rec)

        return authorities

    def _build_record(
        self, name: str, cargo: str, unidad: str, url: str, bio: Optional[str] = None
    ) -> Dict[str, Any]:
        """Estructura un registro de autoridad con los campos del Hito 2."""
        # D2: cargo normalizado
        cargo_normalizado = _normalizar_cargo(cargo)
        # D1: condición de designación
        condicion, evidencia = _detectar_condicion(cargo)
        # Mantener es_titular derivado solo con evidencia (D1)
        if condicion == "titular":
            es_titular = 1
        elif condicion in ("encargado", "subrogante"):
            es_titular = 0
        else:
            es_titular = None  # no_determinado → NULL

        prefix_match = re.match(r"^(Dr\.|Dra\.|Ing\.|Msc\.|Ph\.D\.|Lic\.)\s*", name)
        titulo_academico = prefix_match.group(0).strip() if prefix_match else None

        # El correo solo se registra si aparece en la fuente; nunca se infiere
        email_clean = extract_email(bio) if bio else None

        record = {
            "nombre_completo": name,
            "titulo_academico": titulo_academico,
            "cargo": cargo,                               # Compatibilidad hacia atrás
            "cargo_original": cargo,                      # D2
            "cargo_normalizado": cargo_normalizado,        # D2
            "tipo_cargo": (
                "Alta Direccion"
                if any(k in cargo.lower() for k in ["rector", "vicerrector"])
                else "Decanal"
            ),
            "unidad_adscripcion": unidad,
            "condicion_designacion": condicion,            # D1
            "evidencia_condicion": evidencia or None,      # D1
            "es_titular": es_titular,                     # D1 derivado con evidencia
            "periodo_gestion": None,
            "correo_contacto": email_clean,
            "biografia": bio[:800] if bio else None,
            "fecha_observacion": self._fecha_observacion,  # D5
            "fuente_url": url,
        }
        # B2: Trazabilidad
        return self._add_traceability(record, fuente_url=url)

    def _extract_deans_from_faculties(self) -> List[Dict[str, Any]]:
        """Extrae autoridades adicionales reportadas en las páginas de facultades.

        D4: usa las URLs descubiertas por FacultadesScraper si se suministraron;
        de lo contrario cae en la lista dura de la EPN como respaldo.
        """
        if self._facultad_urls is not None:
            # D4: lista provista externamente
            facultades_urls = self._facultad_urls
        elif self.institucion_id == "EPN":
            # Respaldo EPN: lista dura (solo para mantener compatibilidad)
            facultades_urls = [
                ("https://www.epn.edu.ec/facultad-ingenieria-de-sistemas/", "Facultad de Ingenieria de Sistemas"),
                ("https://www.epn.edu.ec/facultad-ciencias/", "Facultad de Ciencias"),
                ("https://www.epn.edu.ec/facultad-ciencias-administrativas/", "Facultad de Ciencias Administrativas"),
                ("https://www.epn.edu.ec/facultad-geologia-petroleos/", "Facultad de Geologia y Petroleos"),
                ("https://www.epn.edu.ec/facultad-ingenieria-civil-ambiental/", "Facultad de Ingenieria Civil y Ambiental"),
                ("https://www.epn.edu.ec/facultad-ingenieria-electrica-electronica/", "Facultad de Ingenieria Electrica y Electronica"),
                ("https://www.epn.edu.ec/facultad-ingenieria-mecanica/", "Facultad de Ingenieria Mecanica"),
                ("https://www.epn.edu.ec/facultad-de-quimica-y-agroindustria/", "Facultad de Quimica y Agroindustria"),
                ("https://www.epn.edu.ec/esfot/", "Escuela de Formacion de Tecnologos"),
            ]
        else:
            facultades_urls = []

        additional: List[Dict[str, Any]] = []

        for url, fac_name in facultades_urls:
            html = self.http_client.get(url)
            if not html:
                continue

            subdecano_m = re.search(
                r"Subdecan[oa]\s*:\s*([^\n\r<.,]+)", html, re.IGNORECASE
            )
            if subdecano_m:
                sub_name = clean_text(subdecano_m.group(1))
                if len(sub_name.split()) >= 2:
                    rec = self._build_record(
                        name=sub_name,
                        cargo="Subdecano(a)",
                        unidad=fac_name,
                        url=url,
                    )
                    additional.append(rec)

        return additional

    def extract(self) -> List[Dict[str, Any]]:
        """Consolida las autoridades centrales y decanales de la institución."""
        central_authorities = self._extract_authorities_from_main_page()
        faculty_authorities = self._extract_deans_from_faculties()

        # D3: deduplicación por (institucion_id, nombre, cargo_original, unidad_adscripcion)
        all_authorities: List[Dict[str, Any]] = []
        seen: Dict[Tuple, int] = {}
        discarded = 0

        for auth in central_authorities + faculty_authorities:
            key = (
                auth.get("institucion_id", ""),
                clean_text(auth.get("nombre_completo", "")).lower(),
                clean_text(auth.get("cargo_original", "")).lower(),
                clean_text(auth.get("unidad_adscripcion", "")).lower(),
            )
            if key in seen:
                discarded += 1
                self.logger.debug(
                    f"[{self.institucion_id}] Autoridad duplicada descartada: "
                    f"{auth.get('nombre_completo')} / {auth.get('cargo_original')}"
                )
            else:
                seen[key] = 1
                all_authorities.append(auth)

        if discarded:
            self.logger.info(
                f"[{self.institucion_id}] {discarded} registros de autoridades descartados por deduplicación (D3)."
            )

        return all_authorities
