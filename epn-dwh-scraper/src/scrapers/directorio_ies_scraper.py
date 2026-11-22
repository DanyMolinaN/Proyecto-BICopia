"""Extractores genericos para facultades y personal docente de las IES.

Solo visitan URLs declaradas en la matriz oficial. Los registros conservan el
texto observado y la fuente; el extractor no inventa cargo, afiliacion ni
vigencia cuando el portal no los publica de forma explicita.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from src.scrapers.base_scraper import BaseScraper
from src.utils.helpers import clean_text, remove_accents


_GENERIC_LABELS = {
    "inicio", "home", "ver mas", "leer mas", "mas informacion", "contacto",
    "admisiones", "oferta academica", "facultades", "docentes", "profesores",
    "personal academico", "personal docente", "autoridades", "noticias",
}
_ROLE_WORDS = (
    "docente", "profesor", "profesora", "investigador", "investigadora",
    "rector", "vicerrector", "decano", "subdecano", "director", "coordinador",
    "titular", "docencia", "investigacion", "facultad", "escuela", "departamento",
)


def _norm(value: str) -> str:
    return remove_accents(clean_text(value).lower())


def _source_urls(institution: Any, key: str) -> List[str]:
    endpoints = getattr(institution, "endpoints", {}) or {}
    raw = endpoints.get(f"{key}_urls", "[]")
    try:
        values = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        values = []
    if not values and endpoints.get(key):
        values = [endpoints[key]]
    return list(dict.fromkeys(
        value.strip() for value in values or []
        if isinstance(value, str) and value.strip().startswith("https://")
    ))


def _content_root(soup: BeautifulSoup) -> Tag:
    return (
        soup.find("main")
        or soup.find(attrs={"role": "main"})
        or soup.find("article")
        or soup.find(class_=re.compile(r"entry-content|page-content|content-area", re.I))
        or soup.body
        or soup
    )


def _inside_page(source_url: str, target_url: str) -> bool:
    source_host = (urlparse(source_url).hostname or "").lower().removeprefix("www.")
    target_host = (urlparse(target_url).hostname or "").lower().removeprefix("www.")
    return bool(source_host and target_host and (
        source_host == target_host or source_host.endswith("." + target_host)
        or target_host.endswith("." + source_host)
    ))


def _unit_candidate(name: str, evidence: str = "") -> bool:
    normalized = _norm(name)
    if not 3 <= len(normalized) <= 180 or normalized in _GENERIC_LABELS:
        return False
    return bool(re.search(
        r"\b(facultad|facultades|escuela|instituto|departamento|unidad academica|uac)\b",
        normalized + " " + _norm(evidence),
    ))


class DirectorioIEScraper(BaseScraper):
    """Lee directorios configurados de facultades y perfiles docentes."""

    def extract(self) -> List[Dict[str, Any]]:
        """Cumple el contrato BaseScraper y devuelve ambos tipos de directorio."""
        return self.extract_faculties() + self.extract_teachers()

    def extract_faculties(self, max_pages: int = 50) -> List[Dict[str, Any]]:
        sources = _source_urls(self.institucion, "facultades")
        if not sources:
            return []

        queue: List[Tuple[str, str]] = [(url, "") for url in sources]
        visited = set()
        records: Dict[Tuple[str, str], Dict[str, Any]] = {}

        while queue and len(visited) < max_pages:
            page_url, linked_name = queue.pop(0)
            if page_url in visited:
                continue
            visited.add(page_url)
            html = self.http_client.get(page_url)
            if not html:
                continue

            soup = BeautifulSoup(html, "html.parser")
            root = _content_root(soup)
            page_text = "\n".join(root.stripped_strings)
            page_path = urlparse(page_url).path.lower()
            direct_unit_page = bool(re.search(r"/(facultad|escuela|instituto|uac)[^/]*", page_path))
            title_tag = soup.find("h1") or soup.title
            page_title = clean_text(title_tag.get_text(" ", strip=True)) if title_tag else ""
            card_nodes = root.find_all(
                ["article", "li", "div", "section"],
                class_=re.compile(r"facult|unidad|decan|escuela|academic|uac", re.I),
            )

            candidates: List[Tuple[str, str, str]] = []
            if _unit_candidate(page_title) and direct_unit_page:
                candidates.append((page_title, page_url, page_text[:1200]))
            if _unit_candidate(linked_name) and linked_name:
                candidates.append((linked_name, page_url, page_text[:1200]))

            for card in card_nodes:
                heading = card.find(["h2", "h3", "h4", "h5"])
                anchor = card.find("a", href=True)
                label = clean_text((heading or anchor or card).get_text(" ", strip=True))
                if not _unit_candidate(label, " ".join(card.get("class", []))):
                    continue
                href = urljoin(page_url, anchor["href"].strip()) if anchor else page_url
                candidates.append((label, href, clean_text(card.get_text(" ", strip=True))[:1200]))

            for heading in root.find_all(["h2", "h3", "h4"]):
                name = clean_text(heading.get_text(" ", strip=True))
                if _unit_candidate(name):
                    anchor = heading.find("a", href=True) or heading.find_parent("a", href=True)
                    href = urljoin(page_url, anchor["href"].strip()) if anchor else page_url
                    candidates.append((name, href, name))

            for name, href, evidence in candidates:
                if not _inside_page(page_url, href):
                    continue
                if not _unit_candidate(name, evidence):
                    continue
                unit_text = evidence or (page_text if href == page_url else "")
                decano = self._extract_labeled_person(unit_text, r"decan[oa]")
                subdecano = self._extract_labeled_person(unit_text, r"subdecan[oa]")
                key = (_norm(name), href.split("#", 1)[0].rstrip("/"))
                row = {
                    "nombre_facultad": name,
                    "url_facultad": href,
                    "decano": decano,
                    "subdecano": subdecano,
                    "texto_contexto_bruto": evidence,
                    "fuente_url": page_url,
                    "estado_dato": "extraido; vigencia por confirmar",
                }
                records.setdefault(key, self._add_traceability(row, fuente_url=page_url))

            # Seguir solo enlaces que parecen unidades academicas y permanecen
            # bajo el dominio institucional ya permitido por HttpClient.
            for anchor in root.find_all("a", href=True):
                label = clean_text(anchor.get_text(" ", strip=True))
                href = urljoin(page_url, anchor["href"].strip())
                path = urlparse(href).path.lower()
                if (
                    href.startswith("https://") and _inside_page(page_url, href)
                    and href not in visited and _unit_candidate(label, path)
                    and not path.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx"))
                ):
                    queue.append((href, label))

            # Si una URL de facultades es un directorio pero sus unidades no
            # llevan nombres de facultad en el enlace, no inferimos unidades.
            if not candidates and direct_unit_page and _unit_candidate(page_title):
                decano = self._extract_labeled_person(page_text, r"decan[oa]")
                subdecano = self._extract_labeled_person(page_text, r"subdecan[oa]")
                row = {
                    "nombre_facultad": page_title,
                    "url_facultad": page_url,
                    "decano": decano,
                    "subdecano": subdecano,
                    "texto_contexto_bruto": page_text[:1200],
                    "fuente_url": page_url,
                    "estado_dato": "extraido; vigencia por confirmar",
                }
                key = (_norm(page_title), page_url.rstrip("/"))
                records.setdefault(key, self._add_traceability(row, fuente_url=page_url))

        return list(records.values())

    @staticmethod
    def _extract_labeled_person(text: str, label_pattern: str) -> Optional[str]:
        match = re.search(
            rf"\b{label_pattern}\s*[:\-]\s*(.{3,100}?)(?=\bsubdecan[oa]\b|[\n|;]|$)",
            text or "", re.IGNORECASE,
        )
        if not match:
            return None
        value = clean_text(match.group(1)).strip(" .,:;-|")
        return value or None

    @staticmethod
    def _is_person_name(value: str) -> bool:
        normalized = _norm(value)
        words = re.findall(r"[a-z]+", normalized)
        visible_words = re.findall(r"[^\W\d_]+", clean_text(value), flags=re.UNICODE)
        capitalized_words = sum(
            word[:1].isupper() or word.isupper()
            for word in visible_words
            if _norm(word) not in {"de", "del", "la", "las", "los", "y"}
        )
        return (
            2 <= len(words) <= 7
            and len(normalized) <= 100
            and capitalized_words >= 2
            and not re.search(r"\d", value)
            and not any(term in normalized for term in _ROLE_WORDS)
            and normalized not in _GENERIC_LABELS
        )

    def extract_teachers(self, max_pages: int = 30) -> List[Dict[str, Any]]:
        sources = _source_urls(self.institucion, "docentes")
        if not sources:
            return []

        records: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for page_url in sources[:max_pages]:
            html = self.http_client.get(page_url)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            root = _content_root(soup)
            cards = root.find_all(
                ["article", "li", "div", "section"],
                class_=re.compile(r"docente|profesor|teacher|personal|faculty|person|team|profile|member", re.I),
            )
            page_heading = soup.find("h1") or soup.title
            heading_text = clean_text(page_heading.get_text(" ", strip=True)) if page_heading else ""
            page_text = clean_text(root.get_text(" ", strip=True))[:8000]
            page_signal = bool(re.search(
                r"docente|profesor|personal academico|personal docente|planta docente|faculty|our team",
                _norm(page_url + " " + heading_text + " " + page_text),
            ))
            if not cards and page_signal:
                cards = root.find_all(["article", "li"])
            if not cards and not page_signal:
                continue

            for card in cards:
                heading = card.find(["h2", "h3", "h4", "h5", "strong", "b"])
                image = card.find("img", alt=True)
                name = clean_text(heading.get_text(" ", strip=True)) if heading else ""
                if not self._is_person_name(name) and image:
                    name = clean_text(image.get("alt", ""))
                if not self._is_person_name(name):
                    continue

                card_text = clean_text(card.get_text(" ", strip=True))
                normalized_name = _norm(name)
                remainder = re.sub(re.escape(name), " ", card_text, flags=re.IGNORECASE)
                remainder = clean_text(remainder)
                link = card.find("a", href=True)
                profile_url = urljoin(page_url, link["href"].strip()) if link else ""
                if profile_url and (
                    not profile_url.startswith("https://") or not _inside_page(page_url, profile_url)
                ):
                    profile_url = ""
                role = ""
                for candidate in card.find_all(["p", "span", "small", "div"]):
                    value = clean_text(candidate.get_text(" ", strip=True))
                    norm_value = _norm(value)
                    if value and any(term in norm_value for term in _ROLE_WORDS):
                        role = value[:180]
                        break
                key = (normalized_name, profile_url or page_url)
                row = {
                    "nombre_completo": name,
                    "cargo_docente": role or None,
                    "unidad_adscripcion": None,
                    "url_perfil": profile_url or None,
                    "texto_contexto_bruto": remainder[:1000],
                    "fuente_url": page_url,
                    "estado_dato": "nombre extraido; afiliacion y vigencia por confirmar",
                }
                records.setdefault(key, self._add_traceability(row, fuente_url=page_url))

        return list(records.values())


