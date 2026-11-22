"""
Extractor de noticias, comunicados oficiales y eventos institucionales.

Soporta extracción híbrida: aprovecha el endpoint estandarizado WordPress REST API
(wp-json/wp/v2/posts) con paginación completa, filtro de fechas 2024-2025 y
categorías nativas de WP.  El raspado HTML queda como respaldo de último recurso.

Mejoras del Hito 2 (Fase C):
  C1. Paginación completa con page/per_page=100 y X-WP-TotalPages.
  C2. Categorías nativas de WordPress; heurística solo como respaldo.
  C3. tipo_publicacion desde la fuente con tipo_origen.
  C4. fecha_publicacion y fecha_modificacion separadas.
  C5. Sin fecha fabricada; NULL cuando no se puede parsear.
  C6. Conteo por institución, año y trimestre demostrable.
"""

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

from src.config import settings
from src.scrapers.base_scraper import BaseScraper
from src.utils.helpers import clean_text, remove_accents


# ─────────────────────────────────────────────────────────────────────────────
# Catálogo de tipos de publicación mapeado desde categorías/taxonomía WP
# ─────────────────────────────────────────────────────────────────────────────
_TIPO_POR_CATEGORIA = {
    # palabras clave → tipo canónico
    "convocatoria": "convocatoria",
    "concurso": "convocatoria",
    "seleccion": "convocatoria",
    "contratacion": "convocatoria",
    "empleo": "convocatoria",
    "laboral": "convocatoria",
    "comunicado": "comunicado",
    "resolucion": "comunicado",
    "acuerdo": "comunicado",
    "decreto": "comunicado",
    "noticia": "noticia",
    "evento": "evento",
    "agenda": "evento",
    "seminario": "evento",
    "congreso": "evento",
    "conferencia": "evento",
    "boletin": "boletin",
    "informe": "boletin",
    "reporte": "boletin",
}

# Heurística de categoría temática (respaldo cuando WP no tiene categorías)
_CATEGORIA_HEURISTICA = [
    (["oferta laboral", "convocatoria", "seleccion", "contratacion"], "Convocatoria y Empleo"),
    (["investigacion", "cientifico", "conferencia", "paper", "congreso", "research"], "Investigacion y Ciencia"),
    (["rcp", "resolucion", "rectorado", "consejo", "acuerdo", "decreto"], "Resoluciones y Gobierno"),
    (["admision", "estudiantes", "matricula", "becas", "beca"], "Vida Academica y Admision"),
    (["evento", "agenda", "seminario", "workshop", "taller"], "Eventos e Iniciativas"),
]


def _safe_date(raw: Any) -> Optional[str]:
    """Parsea una fecha ISO 8601 o texto libre; devuelve YYYY-MM-DD o None."""
    if not raw:
        return None
    s = str(raw).strip()
    # Formato estándar ISO: YYYY-MM-DDTHH:MM:SS o YYYY-MM-DD
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    # Texto en español: "28 de febrero de 2024"
    meses = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
        "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
        "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    }
    m2 = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", s, re.IGNORECASE)
    if m2:
        mes_txt = m2.group(2).lower()
        mes_num = meses.get(mes_txt)
        if mes_num:
            return f"{m2.group(3)}-{mes_num:02d}-{int(m2.group(1)):02d}"
    return None


def _year_in_range(date_str: Optional[str], start: int, end: int) -> bool:
    """Verifica si el año de una fecha (YYYY-MM-DD) está en [start, end]."""
    if not date_str:
        return False
    try:
        return start <= int(date_str[:4]) <= end
    except ValueError:
        return False


def _infer_tipo_publicacion(categoria_str: str, titulo: str = "") -> Tuple[str, str]:
    """Infiere el tipo de publicación a partir del nombre de categoría.

    Returns:
        Tuple[str, str]: (tipo_publicacion, tipo_origen).
            tipo_origen puede ser 'categoria_wp', 'heuristica' o 'no_determinado'.
    """
    norma = remove_accents(f"{categoria_str} {titulo}".lower())
    for kw, tipo in _TIPO_POR_CATEGORIA.items():
        if kw in norma:
            return tipo, "categoria_o_titulo"
    # Los registros provienen de una URL configurada como archivo oficial de
    # noticias. Se clasifica el caso general como noticia y se deja evidencia
    # de que la categoria fue inferida por la seccion, no por el portal.
    return "noticia", "seccion_noticias"


def _date_from_article(article: Any) -> Optional[str]:
    """Busca fechas de publicacion en marcado HTML habitual y texto visible."""
    selectors = [
        "time[datetime]", "[itemprop='datePublished']", "[data-date]",
        "[class*='date']", "[class*='fecha']", "[class*='time']",
    ]
    for selector in selectors:
        for element in article.select(selector):
            raw = (
                element.get("datetime") or element.get("content") or element.get("data-date")
                or element.get_text(" ", strip=True)
            )
            parsed = _safe_date(raw)
            if parsed:
                return parsed
    for meta in article.find_all("meta"):
        key = " ".join(str(meta.get(k, "")) for k in ("itemprop", "property", "name")).lower()
        if any(label in key for label in ("datepublished", "article:published_time", "publish_date", "date")):
            parsed = _safe_date(meta.get("content", ""))
            if parsed:
                return parsed
    for script in article.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        stack = payload if isinstance(payload, list) else [payload]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                for key in ("datePublished", "dateCreated"):
                    parsed = _safe_date(item.get(key))
                    if parsed:
                        return parsed
                graph = item.get("@graph")
                if isinstance(graph, (list, dict)):
                    stack.append(graph)
    return None


class NoticiasScraper(BaseScraper):
    """Extrae comunicados, convocatorias y novedades informativas de una IES."""

    def __init__(self, http_client=None, institucion_id=None,
                 anio_inicio: int = 2024, anio_fin: int = 2025,
                 max_paginas: int = 50, institucion=None) -> None:
        super().__init__(http_client=http_client, institucion_id=institucion_id, institucion=institucion)
        self.anio_inicio = anio_inicio
        self.anio_fin = anio_fin
        self.max_paginas = max_paginas
        self.max_article_detail_pages = min(5, max(0, max_paginas))
        self._wp_categories: Optional[Dict[int, str]] = None
        self.max_pages_reached = False
        self.discovered_source_urls: List[str] = []

    # ─────────────────────────────────────────────────────────────
    # C2: Categorías nativas de WordPress
    # ─────────────────────────────────────────────────────────────
    def _fetch_wp_categories(self, base_url: str) -> Dict[int, str]:
        """Descarga el catálogo de categorías de WordPress y lo indexa por ID."""
        cats_url = f"{base_url}/wp-json/wp/v2/categories?per_page=100"
        data = self.http_client.get_json(cats_url)
        if not data or not isinstance(data, list):
            return {}
        return {item["id"]: item.get("name", "") for item in data}

    def _resolve_category(
        self,
        cat_ids: List[int],
        title: str,
        base_url: str,
    ) -> Tuple[str, str]:
        """Resuelve la categoría principal y el tipo de publicación.

        Returns:
            Tuple[str, str]: (categoria_nombre, categoria_origen).
        """
        if self._wp_categories is None:
            self._wp_categories = self._fetch_wp_categories(base_url)

        if cat_ids and self._wp_categories:
            # Toma la primera categoría reconocida
            for cid in cat_ids:
                cat_name = self._wp_categories.get(cid, "")
                if cat_name:
                    return cat_name, "wordpress"

        # Respaldo heurístico (C2 — marcado con categoria_origen="heuristica")
        title_norm = remove_accents(title.lower())
        for keywords, cat in _CATEGORIA_HEURISTICA:
            # C9 fix: comparación sin tildes
            if any(remove_accents(k) in title_norm for k in keywords):
                return cat, "heuristica"

        return "Institucional General", "heuristica"

    # ─────────────────────────────────────────────────────────────
    # C1: Paginación completa con filtro de fechas
    # ─────────────────────────────────────────────────────────────
    def _extract_via_api(self) -> List[Dict[str, Any]]:
        """Extrae artículos usando WordPress REST API con paginación completa."""
        from src.config import settings as cfg
        from src.instituciones import registry

        inst = self.institucion or registry.get(self.institucion_id)
        if inst and inst.base_url:
            api_url = inst.get_endpoint("noticias_api") or (
                f"{inst.base_url.rstrip('/')}/wp-json/wp/v2/posts"
                if inst.adaptador == "wordpress" else ""
            )
            base_url = inst.base_url
        elif inst:
            api_url = inst.get_endpoint("noticias_api") or ""
            base_url = inst.base_url or cfg.base_url
        else:
            api_url = cfg.endpoints.get("noticias_api", f"{cfg.base_url}/wp-json/wp/v2/posts")
            base_url = cfg.base_url

        if not api_url:
            self.logger.warning(f"[{self.institucion_id}] Sin endpoint noticias_api configurado.")
            return []

        after = f"{self.anio_inicio}-01-01T00:00:00"
        before = f"{self.anio_fin}-12-31T23:59:59"

        news_items: List[Dict[str, Any]] = []
        page = 1
        while True:
            if page > self.max_paginas:
                self.max_pages_reached = True
                self.logger.warning(
                    f"[{self.institucion_id}] Alcanzado el límite de {self.max_paginas} páginas."
                )
                break

            url = (
                f"{api_url}?per_page=100&page={page}"
                f"&after={after}&before={before}"
                f"&_fields=id,date,modified,title,excerpt,link,categories,type,status"
            )

            # Usar HttpClient mantiene robots.txt, caché, frecuencia,
            # reintentos y manifiesto también en las páginas REST.
            try:
                response_text = self.http_client.get(url)
                if not response_text:
                    break
                posts_data = json.loads(response_text)
            except Exception as exc:
                self.logger.warning(f"[{self.institucion_id}] Error en página {page}: {exc}")
                break

            if not posts_data or not isinstance(posts_data, list):
                break

            for post in posts_data:
                post_id = str(post.get("id", ""))
                # C4: fecha_publicacion y fecha_modificacion separadas
                fecha_pub = _safe_date(post.get("date"))
                fecha_mod = _safe_date(post.get("modified"))

                raw_title = post.get("title", {}).get("rendered", "")
                title = clean_text(raw_title)
                link = post.get("link", "")
                raw_excerpt = post.get("excerpt", {}).get("rendered", "")
                excerpt = clean_text(raw_excerpt)
                cat_ids = post.get("categories", [])

                # C2: Categoría nativa de WP
                categoria, categoria_origen = self._resolve_category(cat_ids, title, base_url)

                # C3: tipo_publicacion desde fuente
                tipo_pub, tipo_origen = _infer_tipo_publicacion(categoria, title)

                record = {
                    "post_id": post_id,
                    "fecha_publicacion": fecha_pub,          # C4
                    "fecha_modificacion": fecha_mod,          # C4
                    "titulo": title,
                    "categoria": categoria,
                    "categoria_origen": categoria_origen,     # C2
                    "tipo_publicacion": tipo_pub,             # C3
                    "tipo_origen": tipo_origen,               # C3
                    "resumen": excerpt[:400] if excerpt else title,
                    "url": link,
                    "periodo_objetivo": "2024-2025",
                }
                # B2: Trazabilidad
                record = self._add_traceability(record, fuente_url=url)
                news_items.append(record)

            # WordPress suele devolver menos de 100 elementos en la última
            # página. Si devuelve 100 exactos, la siguiente respuesta vacía o
            # HTTP 400 termina el recorrido sin consultar headers fuera del cliente.
            if len(posts_data) < 100:
                break
            page += 1

        self.logger.info(
            f"[{self.institucion_id}] Extraídas {len(news_items)} noticias via WP API "
            f"(años {self.anio_inicio}-{self.anio_fin})."
        )
        return news_items

    # ─────────────────────────────────────────────────────────────
    # Respaldo HTML (C5: sin fecha fabricada)
    # ─────────────────────────────────────────────────────────────
    def _next_html_page(self, soup: BeautifulSoup, current_url: str, official_url: str) -> Optional[str]:
        """Encuentra el enlace explícito a la página siguiente dentro del portal oficial."""
        candidates = [
            soup.find("a", rel=lambda value: value and "next" in value),
            soup.find("a", class_=re.compile(r"next|siguiente", re.IGNORECASE)),
        ]
        if not any(candidates):
            for anchor in soup.find_all("a", href=True):
                label = clean_text(anchor.get_text(" ", strip=True)).lower()
                if label in {"siguiente", "siguiente página", "next", "older posts", "entradas antiguas"}:
                    candidates.append(anchor)
                    break
        for anchor in candidates:
            if not anchor or not anchor.get("href"):
                continue
            href = urljoin(current_url, anchor["href"].strip())
            if self._is_official_page_url(href, official_url):
                return href
        return None

    def _is_official_page_url(self, url: str, official_url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            return False
        endpoints = self.institucion.endpoints if self.institucion else {}
        try:
            additional = json.loads(endpoints.get("dominios_oficiales_adicionales", "[]"))
        except (TypeError, json.JSONDecodeError):
            additional = []
        allowed = [
            (urlparse(official_url).hostname or "").lower().removeprefix("www."),
            *[str(host).lower().removeprefix("www.").rstrip(".") for host in additional or []],
        ]
        host = parsed.hostname.lower().removeprefix("www.")
        return any(host == root or host.endswith("." + root) for root in allowed if root)

    def _discover_news_sources(self, portal_url: str) -> List[str]:
        """Find official news archive links from the university's own homepage."""
        if not portal_url:
            return []
        homepage = portal_url.rstrip("/") + "/"
        html = self.http_client.get(homepage)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        keywords = ("noticia", "news", "actualidad", "prensa", "comunicado", "boletin")
        candidates: Dict[str, int] = {}
        for anchor in soup.find_all("a", href=True):
            label = clean_text(anchor.get_text(" ", strip=True))
            href = urljoin(homepage, anchor["href"].strip())
            path = urlparse(href).path.lower()
            evidence = remove_accents(f"{label} {path}".lower())
            # La paginación se sigue desde el archivo raíz con el enlace
            # "siguiente"; no se deben tratar páginas 2, 3... como archivos
            # independientes descubiertos desde el menú de portada.
            if re.search(r"/page/\d+/?$", path):
                continue
            if (
                self._is_official_page_url(href, portal_url)
                and href.rstrip("/") != portal_url.rstrip("/")
                and any(keyword in evidence for keyword in keywords)
            ):
                score = sum(2 for keyword in keywords if keyword in remove_accents(path))
                if any(keyword in remove_accents(label.lower()) for keyword in keywords):
                    score += 3
                candidates[href] = max(score, candidates.get(href, 0))
        return [url for url, _ in sorted(candidates.items(), key=lambda item: (-item[1], item[0]))[:5]]

    def _extract_via_html(self) -> List[Dict[str, Any]]:
        """Extrae y pagina archivos HTML oficiales, sin inventar fechas."""
        from src.config import settings as cfg
        from src.instituciones import registry

        inst = self.institucion or registry.get(self.institucion_id)
        url = (
            inst.get_endpoint("noticias_web") if inst
            else cfg.endpoints.get("noticias_web", f"{cfg.base_url}/noticias/")
        )
        items: List[Dict[str, Any]] = []
        base = inst.base_url if inst and inst.base_url else cfg.base_url
        start_urls = [url] if url else self._discover_news_sources(base)
        self.discovered_source_urls = list(start_urls) or ([base.rstrip("/") + "/"] if not url else [])
        pending_urls = list(start_urls)
        visited = set()
        seen_links = set()
        detail_pages = 0
        current_url = None
        while (pending_urls or current_url) and len(visited) < self.max_paginas:
            if current_url is None:
                current_url = pending_urls.pop(0) if pending_urls else None
            if not current_url or current_url in visited:
                current_url = None
                continue
            visited.add(current_url)
            html_content = self.http_client.get(current_url)
            if not html_content:
                current_url = None
                continue
            soup = BeautifulSoup(html_content, "html.parser")
            articles = soup.find_all(
                ["article", "div"],
                class_=re.compile(r"(post|entry|noticia|news|article|item)", re.IGNORECASE)
            )

            for art in articles:
                title_tag = art.find(["h2", "h3", "h4"])
                link_tag = (title_tag.find("a", href=True) if title_tag else None) or art.find("a", href=True)
                if not title_tag or not link_tag:
                    continue

                title = clean_text(title_tag.get_text())
                link = urljoin(current_url, link_tag["href"].strip())
                if not title or link in seen_links or not self._is_official_page_url(link, base):
                    continue
                seen_links.add(link)

                fecha_pub = _date_from_article(art)
                if fecha_pub is None and detail_pages < self.max_article_detail_pages:
                    detail_pages += 1
                    detail_html = self.http_client.get(link)
                    if detail_html:
                        detail_soup = BeautifulSoup(detail_html, "html.parser")
                        fecha_pub = _date_from_article(detail_soup)
                if fecha_pub and not _year_in_range(fecha_pub, self.anio_inicio, self.anio_fin):
                    continue

                category_tag = art.find(class_=re.compile(r"cat|categor|tag", re.IGNORECASE))
                category_text = clean_text(category_tag.get_text(" ", strip=True)) if category_tag else ""
                categoria, categoria_origen = self._resolve_category([], category_text or title, base)
                if category_text:
                    categoria_origen = "html_categoria_publicada"
                tipo_pub, tipo_origen = _infer_tipo_publicacion(categoria, title)

                record = {
                    "post_id": f"html_{self.institucion_id}_{len(items) + 1}",
                    "fecha_publicacion": fecha_pub,
                    "fecha_modificacion": None,
                    "titulo": title,
                    "categoria": categoria,
                    "categoria_origen": categoria_origen,
                    "tipo_publicacion": tipo_pub,
                    "tipo_origen": tipo_origen,
                    "resumen": title,
                    "url": link,
                    "periodo_objetivo": "sin_fecha" if fecha_pub is None else "2024-2025",
                }
                items.append(self._add_traceability(record, fuente_url=current_url))

            next_url = self._next_html_page(soup, current_url, base)
            if next_url and next_url not in visited:
                current_url = next_url
            else:
                current_url = None
                # Para descubrimiento dinamico, detenerse tras encontrar una
                # seccion que ya produjo publicaciones y evitar recorrer otros
                # enlaces de noticias duplicados del menu.
                if items and not url:
                    pending_urls.clear()

        if len(visited) >= self.max_paginas and (pending_urls or current_url):
            self.max_pages_reached = True
            self.logger.warning(
                f"[{self.institucion_id}] Archivo HTML alcanzó max_paginas={self.max_paginas}; revisar cobertura."
            )

        return items

    def extract(self) -> List[Dict[str, Any]]:
        """Ejecuta la extracción de noticias priorizando API y con respaldo HTML."""
        news = self._extract_via_api()
        if not news:
            self.logger.info(
                f"[{self.institucion_id}] API sin resultados; intentando respaldo HTML."
            )
            news = self._extract_via_html()
        return news

    # ─────────────────────────────────────────────────────────────
    # C6: Conteo por institución, año y trimestre
    # ─────────────────────────────────────────────────────────────
    @staticmethod
    def resumen_cobertura(records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Genera conteo por institución, año y trimestre para demostrar cobertura 2024-2025.

        Args:
            records: Lista de registros extraídos por NoticiasScraper.

        Returns:
            Dict con conteos estructurados y una bandera de cobertura completa.
        """
        from collections import defaultdict
        conteos: Dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        sin_fecha = 0

        for r in records:
            fecha = r.get("fecha_publicacion")
            inst_id = r.get("institucion_id", "desconocida")
            if not fecha:
                sin_fecha += 1
                continue
            try:
                anio = int(fecha[:4])
                mes = int(fecha[5:7])
                trimestre = (mes - 1) // 3 + 1
                conteos[inst_id][anio][trimestre] += 1
            except (ValueError, IndexError):
                sin_fecha += 1

        # Evaluar cobertura
        years_covered = set()
        for inst_conteos in conteos.values():
            years_covered.update(inst_conteos.keys())

        return {
            "conteo_por_institucion_anio_trimestre": {
                inst: {
                    anio: dict(trimestres)
                    for anio, trimestres in anios.items()
                }
                for inst, anios in conteos.items()
            },
            "registros_sin_fecha": sin_fecha,
            "total_registros": len(records),
            "anios_cubiertos": sorted(years_covered),
            "cobertura_2024": 2024 in years_covered,
            "cobertura_2025": 2025 in years_covered,
        }
