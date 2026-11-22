"""Captura enlaces crudos publicados en la oferta académica oficial de una IES.

El extractor conserva el texto y contexto visibles y no declara que cada enlace
sea una carrera vigente. La clasificación de nivel y vigencia se valida después
del perfilado del Hito 2.
"""

import json
import io
import re
from typing import Any, Dict, List
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.scrapers.base_scraper import BaseScraper
from src.utils.helpers import remove_accents


def _normalizar(texto: str) -> str:
    return " ".join(remove_accents((texto or "").lower()).split())


def _inferir_nivel(texto: str) -> tuple[str, str]:
    """Clasifica solo cuando el portal declara explícitamente el nivel."""
    texto = texto or ""
    norma = _normalizar(texto)
    if any(term in norma for term in ("cuarto nivel", "posgrado", "postgrado", "maestria", "doctorado", "especializacion")):
        return "cuarto_nivel", texto.strip()
    if any(term in norma for term in ("tercer nivel", "pregrado", "pre-grado", "grado", "licenciatura")):
        return "tercer_nivel", texto.strip()
    return "no_determinado", ""


def _valor_etiquetado(texto: str, etiqueta: str, alternativas: dict[str, str]) -> tuple[str, str]:
    """Lee valores presentados como campo Etiqueta: valor en la página oficial."""
    lines = [" ".join(line.split()) for line in (texto or "").splitlines() if line.strip()]
    for line in lines:
        norma = _normalizar(line)
        match = re.search(rf"\b(?:{etiqueta})\b\s*[:\-]\s*([^|;]{{1,100}})", norma)
        if not match:
            continue
        valor = match.group(1).strip(" .,:-|")
        for clave, normalizado in alternativas.items():
            if clave in valor:
                return normalizado, line
        return valor, line
    return "no_determinado", ""


def _es_enlace_generico(label: str) -> bool:
    norma = _normalizar(label).strip(" »›… .")
    return norma in {
        "mas informacion", "leer mas", "ver mas", "conocer mas", "mas detalles",
        "ver carrera", "informacion", "mas info",
    }


_CAREER_TERMS = (
    "carrera", "ingenieria", "licenciatura", "medicina", "odontologia", "enfermeria",
    "comunicacion", "arquitectura", "psicologia", "administracion", "contabilidad",
    "economia", "derecho", "educacion", "turismo", "agronomia", "agroindustria",
    "biologia", "quimica", "fisica", "computacion", "software", "sistemas", "marketing",
    "diseno", "matematica", "biotecnologia", "veterinaria", "industrial", "electrica",
    "civil", "ambiental", "gastronomia", "artes", "produccion", "riesgos", "petroleos",
    "mecanica", "mecatronica", "datos", "finanzas", "logistica", "acuicultura",
    "agropecuaria", "cine", "musica", "artes escenicas", "artes visuales", "trabajo social",
    "comercio exterior", "ciencias politicas", "diseno grafico", "educacion inicial",
    "gestion", "tecnologia", "pedagogia", "seguridad", "redes", "comercio", "agro",
    "matematicas", "salud", "finanzas", "logistica", "talento humano", "innovacion",
)
_NON_PROGRAM_LABELS = {
    "inicio", "home", "admisiones", "admisiones", "contacto", "noticias", "investigacion",
    "posgrados", "maestrias", "doctorados", "educacion continua", "conoce mas", "ver mas",
    "leer mas", "matriculas", "inscribete", "postula aqui", "aplicar", "menu", "carrera",
    "carreras", "oferta academica", "oferta de carreras", "carreras de grado",
    "carreras de pregrado", "programas academicos", "programas de grado",
}
_PROGRAM_NAME_TERMS = tuple(term for term in _CAREER_TERMS if term != "carrera")


def _is_program_candidate(label: str, href: str, page_title: str, context: str, anchor) -> bool:
    """Keep only visible labels plausibly tied to a degree/program listing."""
    clean_label = " ".join((label or "").split())
    normalized_label = _normalizar(clean_label).strip(" .:-|›»")
    if not 3 <= len(clean_label) <= 130 or normalized_label in _NON_PROGRAM_LABELS:
        return False
    blocked_ancestor = anchor.find_parent(class_=re.compile(
        r"menu|navigation|navbar|breadcrumb|footer|header|social|widget|related|sidebar", re.I
    ))
    if blocked_ancestor:
        return False
    path = _normalizar(urlparse(href).path)
    evidence = _normalizar(" ".join((clean_label, page_title, context, path)))
    href_is_document = path.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx"))
    document_is_offer = href_is_document and any(term in evidence for term in ("oferta", "carrera", "catalogo", "programa"))
    card_signal = bool(anchor.find_parent(class_=re.compile(r"carrera|programa|degree|course|academic|card", re.I)))
    if _es_enlace_generico(clean_label):
        return bool(card_signal or any(term in evidence for term in _CAREER_TERMS))
    career_word = any(term in _normalizar(clean_label) for term in _CAREER_TERMS)
    path_signal = any(term in path for term in ("carrera", "programa", "grado", "pregrado", "catalogo", "oferta"))
    # Catalog pages commonly render one-word degree names (e.g. Acuicultura) as
    # plain links; accept those only when another part of the row confirms them.
    return bool(career_word or card_signal or path_signal or document_is_offer)


class OfertaEnlacesScraper(BaseScraper):
    """Extrae enlaces de páginas de oferta configuradas para una universidad."""

    @staticmethod
    def _content_root(soup):
        return (
            soup.find("main")
            or soup.find(attrs={"role": "main"})
            or soup.find("article")
            or soup.find(class_="entry-content")
            or soup.find(class_="page-content")
        )

    def _configured_urls(self) -> List[str]:
        endpoints = self.institucion.endpoints if self.institucion else {}
        value = endpoints.get("oferta_urls", "[]")
        try:
            urls = json.loads(value) if isinstance(value, str) else value
        except json.JSONDecodeError:
            urls = []
        if not urls and endpoints.get("oferta_grado"):
            urls = [endpoints["oferta_grado"]]
        return [url for url in urls if isinstance(url, str) and url.startswith("https://")]

    def _is_official_link(self, href: str) -> bool:
        if not self.institucion:
            return False
        parsed = urlparse(href)
        if parsed.scheme != "https" or not parsed.hostname:
            return False
        official = urlparse(self.institucion.base_url).hostname or ""
        candidate = parsed.hostname
        official = official.lower().removeprefix("www.")
        candidate = candidate.lower().removeprefix("www.")
        endpoints = self.institucion.endpoints if self.institucion else {}
        value = endpoints.get("dominios_oficiales_adicionales", "[]")
        try:
            extra_hosts = json.loads(value) if isinstance(value, str) else value
        except json.JSONDecodeError:
            extra_hosts = []
        official_hosts = [official, *[
            str(host).strip().lower().removeprefix("www.").rstrip(".")
            for host in extra_hosts or []
        ]]
        return any(
            candidate == host or candidate.endswith("." + host)
            for host in official_hosts if host
        )

    @staticmethod
    def _name_looks_like_program(name: str) -> bool:
        normalized = _normalizar(name)
        return (
            3 <= len(name.strip()) <= 130
            and normalized not in _NON_PROGRAM_LABELS
            and any(term in normalized for term in _PROGRAM_NAME_TERMS)
        )

    def _extract_text_candidates(self, content, page_url: str, page_title: str) -> List[Dict[str, Any]]:
        """Read program names from cards, headings and tables that have no links."""
        if content is None:
            return []
        candidates: Dict[str, tuple[str, str]] = {}
        card_nodes = content.find_all(
            ["article", "li", "div", "section"],
            class_=re.compile(r"carrera|programa|degree|course|academic|card", re.I),
        )
        for node in card_nodes:
            heading = node.find(["h2", "h3", "h4", "h5", "strong"])
            if not heading:
                continue
            name = " ".join(heading.get_text(" ", strip=True).split())
            context = " ".join(node.get_text(" ", strip=True).split())
            if self._name_looks_like_program(name):
                candidates.setdefault(_normalizar(name), (name, context))

        for row in content.find_all("tr"):
            cells = [" ".join(cell.get_text(" ", strip=True).split()) for cell in row.find_all(["th", "td"])]
            if not cells:
                continue
            name = cells[0]
            context = " | ".join(cells)
            if self._name_looks_like_program(name):
                candidates.setdefault(_normalizar(name), (name, context))

        for heading in content.find_all(["h2", "h3", "h4", "h5"]):
            name = " ".join(heading.get_text(" ", strip=True).split())
            if self._name_looks_like_program(name):
                candidates.setdefault(_normalizar(name), (name, name))

        page_level, level_evidence = _inferir_nivel(page_title)
        output = []
        for name, context in candidates.values():
            output.append({
                "url_oferta": page_url,
                "estado_fuente_configurada": (self.institucion.endpoints or {}).get("estado_oferta", "") if self.institucion else "",
                "tipo_registro": "programa_candidato_html",
                "nombre_programa_bruto": name,
                "texto_enlace_bruto": "",
                "origen_nombre_programa": "titulo_visible_sin_enlace",
                "url_programa": page_url,
                "texto_contexto_bruto": context[:700],
                "titulo_pagina": page_title,
                "titulo_detalle": "",
                "area_contenido": "contenedor_principal",
                "nivel_formacion": page_level,
                "evidencia_nivel_formacion": level_evidence,
                "modalidad": "no_determinado",
                "evidencia_modalidad": "",
                "financiamiento": "no_determinado",
                "evidencia_financiamiento": "",
                "estado_programa": "no_determinado",
                "evidencia_estado": "",
                "periodo_consulta": "2026",
            })
        return output

    def _extract_pdf_candidates(
        self, page_url: str, pdf_url: str, page_title: str, context: str, configured_state: str
    ) -> List[Dict[str, Any]]:
        """Extract visible career names from an official PDF catalog."""
        pdf_bytes = self.http_client.get_bytes(pdf_url)
        if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
            return []
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(pdf_bytes))
            pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages[:60])
        except Exception as exc:
            self.logger.warning(f"No se pudo leer el catalogo PDF {pdf_url}: {exc}")
            return []

        found: Dict[str, tuple[str, str]] = {}
        for raw_line in pdf_text.splitlines():
            line = " ".join(raw_line.replace("\t", "  ").split())
            line = re.sub(r"^[\s\d.\-–•]+", "", line).strip()
            parts = [part.strip(" |:-") for part in re.split(r"\s{2,}|\s*\|\s*", line) if part.strip(" |:-")]
            for part in (parts or [line]):
                if self._name_looks_like_program(part):
                    found.setdefault(_normalizar(part), (part, line))

        nivel, evidencia_nivel = _inferir_nivel(f"{page_title} {pdf_text[:3000]}")
        output = []
        for name, evidence in found.values():
            normalized_evidence = _normalizar(evidence)
            modality = next((
                value for key, value in (
                    ("presencial", "Presencial"), ("semipresencial", "Semipresencial"),
                    ("en linea", "En Linea"), ("virtual", "En Linea"),
                    ("hibrida", "Hibrida"), ("a distancia", "A Distancia"),
                ) if key in normalized_evidence
            ), "no_determinado")
            output.append({
                "url_oferta": page_url,
                "estado_fuente_configurada": configured_state,
                "tipo_registro": "programa_candidato_pdf",
                "nombre_programa_bruto": name,
                "texto_enlace_bruto": context,
                "origen_nombre_programa": "texto_pdf_oficial",
                "url_programa": pdf_url,
                "texto_contexto_bruto": evidence[:700],
                "titulo_pagina": page_title,
                "titulo_detalle": "",
                "area_contenido": "pdf_oficial",
                "nivel_formacion": nivel,
                "evidencia_nivel_formacion": evidencia_nivel,
                "modalidad": modality,
                "evidencia_modalidad": evidence if modality != "no_determinado" else "",
                "financiamiento": "no_determinado",
                "evidencia_financiamiento": "",
                "estado_programa": "no_determinado",
                "evidencia_estado": "",
                "periodo_consulta": "2026",
                "fuente_url": pdf_url,
            })
        if not output:
            output.append({
                "url_oferta": page_url,
                "estado_fuente_configurada": configured_state,
                "tipo_registro": "documento_catalogo_pdf",
                "nombre_programa_bruto": "",
                "texto_enlace_bruto": context,
                "origen_nombre_programa": "",
                "url_programa": pdf_url,
                "texto_contexto_bruto": pdf_text[:700],
                "titulo_pagina": page_title,
                "titulo_detalle": "",
                "area_contenido": "pdf_oficial",
                "nivel_formacion": nivel,
                "evidencia_nivel_formacion": evidencia_nivel,
                "modalidad": "no_determinado",
                "evidencia_modalidad": "",
                "financiamiento": "no_determinado",
                "evidencia_financiamiento": "",
                "estado_programa": "no_determinado",
                "evidencia_estado": "",
                "periodo_consulta": "2026",
                "fuente_url": pdf_url,
            })
        return output

    def extract(self) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        endpoints = self.institucion.endpoints if self.institucion else {}
        configured_state = endpoints.get("estado_oferta", "")
        detail_cache: Dict[str, tuple[str, str]] = {}
        detail_pages = 0
        max_detail_pages = 10

        for page_url in self._configured_urls():
            html = self.http_client.get(page_url)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            content = self._content_root(soup)
            fallback = False
            if content is None:
                content = soup.body
                fallback = True

            page_title = ""
            heading = soup.find("h1") or soup.title
            if heading:
                page_title = " ".join(heading.get_text(" ", strip=True).split())

            page_level, page_level_evidence = _inferir_nivel(page_title)

            page_records = []
            if content is not None:
                for anchor in content.find_all("a", href=True):
                    if anchor.find_parent(["nav", "header", "footer"]):
                        continue
                    label = " ".join(anchor.get_text(" ", strip=True).split())
                    raw_href = anchor.get("href")
                    if not isinstance(raw_href, str) or not raw_href.strip():
                        continue
                    href = urljoin(page_url, raw_href.strip())
                    parsed = urlparse(href)
                    if not label or parsed.scheme != "https":
                        continue
                    if not self._is_official_link(href):
                        continue
                    if href.split("#", 1)[0].rstrip("/") == page_url.split("#", 1)[0].rstrip("/"):
                        continue

                    parent = anchor.parent
                    context = " ".join(parent.get_text(" ", strip=True).split()) if parent else label
                    if not _is_program_candidate(label, href, page_title, context, anchor):
                        continue
                    if parsed.path.lower().endswith(".pdf"):
                        page_records.extend(self._extract_pdf_candidates(
                            page_url, href, page_title, label, configured_state
                        ))
                        continue
                    detail_title = ""
                    detail_text = ""
                    if (
                        _es_enlace_generico(label)
                        and not parsed.path.lower().endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx"))
                        and detail_pages < max_detail_pages
                    ):
                        if href not in detail_cache:
                            detail_html = self.http_client.get(href)
                            detail_pages += 1
                            if detail_html:
                                detail_soup = BeautifulSoup(detail_html, "html.parser")
                                detail_heading = detail_soup.find("h1") or detail_soup.title
                                detail_title = (
                                    " ".join(detail_heading.get_text(" ", strip=True).split())
                                    if detail_heading else ""
                                )
                                detail_root = self._content_root(detail_soup) or detail_soup.body
                                detail_text = (
                                    "\n".join(detail_root.stripped_strings)[:12000]
                                    if detail_root else ""
                                )
                                detail_cache[href] = (detail_title, detail_text)
                            else:
                                detail_cache[href] = ("", "")
                        detail_title, detail_text = detail_cache[href]

                    program_name = detail_title or label
                    program_name_origin = "pagina_detalle_h1" if detail_title else "texto_enlace"
                    level, level_evidence = _inferir_nivel(" ".join((page_title, detail_title)))
                    if level == "no_determinado":
                        level, level_evidence = page_level, page_level_evidence
                    modality, modality_evidence = _valor_etiquetado(
                        detail_text or context,
                        "modalidad(?: de estudio)?",
                        {
                            "presencial": "Presencial",
                            "semipresencial": "Semipresencial",
                            "en linea": "En Linea",
                            "virtual": "En Linea",
                            "a distancia": "A Distancia",
                            "dual": "Dual",
                            "hibrida": "Hibrida",
                        },
                    )
                    financing, financing_evidence = _valor_etiquetado(
                        detail_text,
                        "financiamiento|financiacion",
                        {},
                    )
                    program_status, status_evidence = _valor_etiquetado(
                        detail_text,
                        "estado del programa|estado de la carrera|estado de la oferta|"
                        "vigencia del programa|vigencia de la carrera|vigencia de la oferta",
                        {
                            "inactivo": "inactivo",
                            "cerrado": "inactivo",
                            "vigente": "vigente",
                            "activo": "vigente",
                        },
                    )
                    if program_status not in ("vigente", "inactivo"):
                        program_status, status_evidence = "no_determinado", ""
                    page_records.append({
                        "url_oferta": page_url,
                        "estado_fuente_configurada": configured_state,
                        "tipo_registro": "programa_candidato",
                        "nombre_programa_bruto": program_name,
                        "texto_enlace_bruto": label,
                        "origen_nombre_programa": program_name_origin,
                        "url_programa": href,
                        "texto_contexto_bruto": context[:700],
                        "titulo_pagina": page_title,
                        "titulo_detalle": detail_title,
                        "area_contenido": "body_fallback" if fallback else "contenedor_principal",
                        "nivel_formacion": level,
                        "evidencia_nivel_formacion": level_evidence,
                        "modalidad": modality,
                        "evidencia_modalidad": modality_evidence,
                        "financiamiento": financing,
                        "evidencia_financiamiento": financing_evidence,
                        "estado_programa": program_status,
                        "evidencia_estado": status_evidence,
                        "periodo_consulta": "2026",
                    })

            existing_names = {_normalizar(record.get("nombre_programa_bruto", "")) for record in page_records}
            page_records.extend(
                record for record in self._extract_text_candidates(content, page_url, page_title)
                if _normalizar(record.get("nombre_programa_bruto", "")) not in existing_names
            )

            if not page_records:
                page_records = [{
                    "url_oferta": page_url,
                    "estado_fuente_configurada": configured_state,
                    "tipo_registro": "pagina_sin_enlaces_clasificables",
                    "nombre_programa_bruto": "",
                    "texto_enlace_bruto": "",
                    "origen_nombre_programa": "",
                    "url_programa": "",
                    "texto_contexto_bruto": "",
                    "titulo_pagina": page_title,
                    "titulo_detalle": "",
                    "area_contenido": "body_fallback" if fallback else "contenedor_principal",
                    "nivel_formacion": page_level,
                    "evidencia_nivel_formacion": page_level_evidence,
                    "modalidad": "no_determinado",
                    "evidencia_modalidad": "",
                    "financiamiento": "no_determinado",
                    "evidencia_financiamiento": "",
                    "estado_programa": "no_determinado",
                    "evidencia_estado": "",
                    "periodo_consulta": "2026",
                }]

            for record in page_records:
                records.append(self._add_traceability(record, fuente_url=page_url))

        unique: Dict[tuple, Dict[str, Any]] = {}
        for row in records:
            key = (row.get("url_oferta"), row.get("url_programa"), row.get("nombre_programa_bruto"))
            unique.setdefault(key, row)
        return list(unique.values())
