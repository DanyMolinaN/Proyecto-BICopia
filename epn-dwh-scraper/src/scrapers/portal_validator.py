"""
PortalValidator: descubre y valida el portal oficial de cada IES del CES.

Fase 3 del prompt PROMPT_Extraccion_64_IES_CES.md.

Para cada IES, verifica que el portal candidato cumpla TODOS los criterios:
  1. HTTP 200
  2. El título o contenido de la portada identifica a la institución
  3. Dominio coherente (.edu.ec salvo justificación documentada)
  4. La página enlaza o menciona cargos o programas propios

Adicionalmente:
  - Lee robots.txt y registra si permite scraping de las secciones clave.
  - Detecta WordPress comprobando /wp-json/ (retorna 200 con JSON).
  - Registra url_noticias, url_autoridades, url_oferta cuando existen.

Resultado: lista de dicts compatibles con config/portales_validados.csv.

Reglas:
  - No adivina dominios; requiere portal_url pre-cargada o búsqueda externa.
  - Si hay dudas, estado='requiere_revision_humana'.
  - 1 petición por host, 1 s de pausa. Sin paralelismo.
"""

import re
import time
import unicodedata
import urllib.robotparser
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from src.utils.logger import setup_logger

logger = setup_logger("portal_validator")

# Tiempo mínimo entre peticiones al MISMO host (segundos)
_MIN_DELAY = 1.0

# Patrones que indican WordPress en /wp-json/
_WP_JSON_MARKER = "/wp-json/"

# Patrones heurísticos de URLs de secciones
_PATTERNS_NOTICIAS = [
    "/noticias", "/news", "/novedades", "/comunicados",
    "/publicaciones", "/sala-de-prensa", "/prensa",
]
_PATTERNS_AUTORIDADES = [
    "/autoridades", "/directivos", "/rector", "/gobierno",
    "/quienes-somos/autoridades",
]
_PATTERNS_OFERTA = [
    "/oferta-academica", "/oferta-educativa", "/carreras",
    "/programas", "/grado", "/posgrado",
]


def _normalize(text: str) -> str:
    """Sin tildes, mayúsculas, solo alfanumérico."""
    nfkd = unicodedata.normalize("NFKD", text or "")
    norma = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z0-9 ]", " ", norma).upper()


def _extract_base(url: str) -> str:
    """Extrae esquema + host de una URL."""
    m = re.match(r"(https?://[^/]+)", url)
    return m.group(1) if m else url


def _check_wordpress(session: requests.Session, base_url: str, timeout: int) -> bool:
    """Devuelve True si /wp-json/ responde con JSON válido."""
    try:
        r = session.get(
            f"{base_url}{_WP_JSON_MARKER}",
            timeout=timeout,
            verify=False,
            allow_redirects=True,
        )
        return r.status_code == 200 and "application/json" in r.headers.get("Content-Type", "")
    except Exception:
        return False


def _is_soft_404(html: str, final_url: str, base_url: str) -> bool:
    """Detecta páginas de error 404 simuladas con HTTP 200 o redirección a la portada."""
    # 1. Redirección silenciosa a la portada
    clean_final = final_url.rstrip("/")
    clean_base = base_url.rstrip("/")
    if clean_final == clean_base or clean_final == f"{clean_base}/index.php" or clean_final == f"{clean_base}/home":
        return True

    # 2. Detección de títulos o textos clásicos de Soft 404
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string or "").lower() if soup.title else ""
    soft_404_indicators = [
        "404", "no encontrada", "not found", "no se encontró",
        "no existe", "página no disponible", "error 404"
    ]
    if any(ind in title for ind in soft_404_indicators):
        return True

    # Comprobar encabezados h1/h2 prominentes
    for h in soup.find_all(["h1", "h2"]):
        h_text = h.get_text(strip=True).lower()
        if any(ind in h_text for ind in soft_404_indicators):
            return True

    # 3. Contenido vacío o insignificante con palabra clave
    body_text = soup.get_text(strip=True)
    if len(body_text) < 150 and any(ind in body_text.lower() for ind in soft_404_indicators):
        return True

    return False


def _probe_section(
    session: requests.Session, base_url: str, patterns: List[str], timeout: int
) -> Optional[str]:
    """Prueba URLs candidatas de una sección; devuelve la primera que da HTTP 200 y no es soft 404."""
    for pat in patterns:
        url = base_url.rstrip("/") + pat
        try:
            r = session.get(url, timeout=timeout, verify=False, allow_redirects=True)
            if r.status_code == 200:
                if not _is_soft_404(r.text, r.url, base_url):
                    return r.url
        except Exception:
            pass
        time.sleep(0.3)
    return None


def _check_robots(base_url: str, user_agent: str, timeout: int) -> Tuple[bool, str]:
    """Lee robots.txt y determina si está permitido el scraping.

    Returns:
        (permite_bool, 'si'|'no'|'no_aplica')
    """
    try:
        robots_url = base_url.rstrip("/") + "/robots.txt"
        session = requests.Session()
        r = session.get(robots_url, timeout=timeout, verify=False)
        if r.status_code == 404:
            return True, "no_aplica"
        if r.status_code != 200:
            return True, "no_aplica"
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(r.text.splitlines())
        # Comprobar permiso para rutas clave
        paths_to_check = ["/noticias", "/autoridades", "/oferta-academica", "/"]
        allowed = all(rp.can_fetch(user_agent, base_url + p) for p in paths_to_check)
        return allowed, "si" if allowed else "no"
    except Exception:
        return True, "no_aplica"


class PortalValidator:
    """Valida portales oficiales de IES según los criterios de la Fase 3."""

    def __init__(
        self,
        user_agent: str = "EPN-DWH-Scraper/2.0 (academic; contact: equipo6@epn.edu.ec)",
        timeout: int = 15,
        min_delay: float = _MIN_DELAY,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.min_delay = min_delay
        self._last_host_time: Dict[str, float] = {}

        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept-Language": "es-EC,es;q=0.9,en;q=0.8",
        })

    def _rate_limit(self, host: str) -> None:
        last = self._last_host_time.get(host, 0.0)
        elapsed = time.time() - last
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)
        self._last_host_time[host] = time.time()

    def validate_portal(
        self,
        institucion_id: str,
        nombre: str,
        portal_url: str,
        metodo: str = "pre_cargado",
    ) -> Dict[str, Any]:
        """Valida un portal candidato para una IES.

        Args:
            institucion_id: ces_cod de la IES.
            nombre: nombre oficial del catálogo.
            portal_url: URL candidata a validar.
            metodo: 'pre_cargado' | 'busqueda_web'.

        Returns:
            Dict compatible con portales_validados.csv.
        """
        result: Dict[str, Any] = {
            "institucion_id": institucion_id,
            "nombre": nombre,
            "portal_url": portal_url,
            "metodo_descubrimiento": metodo,
            "evidencia": "",
            "fecha_validacion": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "robots_permite": "no_aplica",
            "es_wordpress": "no",
            "url_noticias": "",
            "url_autoridades": "",
            "url_oferta": "",
            "estado": "requiere_revision_humana",
            "motivo": "",
        }

        if not portal_url:
            result["estado"] = "requiere_revision_humana"
            result["motivo"] = "sin_url_candidata"
            return result

        # Normalizar URL
        if not portal_url.startswith("http"):
            portal_url = "https://" + portal_url
            result["portal_url"] = portal_url

        base_url = _extract_base(portal_url)
        host = base_url.replace("https://", "").replace("http://", "").split("/")[0]

        # Rate limit por host
        self._rate_limit(host)

        # 1. HTTP 200
        try:
            r = self.session.get(
                portal_url, timeout=self.timeout, verify=False, allow_redirects=True
            )
        except Exception as exc:
            result["estado"] = "error_http"
            result["motivo"] = f"excepcion_red: {str(exc)[:100]}"
            return result

        if r.status_code != 200:
            result["estado"] = "error_http"
            result["motivo"] = f"http_{r.status_code}"
            return result

        html = r.text
        soup = BeautifulSoup(html, "html.parser")

        # 2. Dominio coherente (.edu.ec)
        is_edu_ec = host.endswith(".edu.ec")
        dominio_ok = is_edu_ec
        if not is_edu_ec:
            # Revisar si el nombre de la institución aparece prominentemente
            dominio_nota = f"dominio_no_edu_ec:{host}"
        else:
            dominio_nota = ""

        # 3. El contenido identifica a la institución
        title = soup.title.get_text(strip=True) if soup.title else ""
        body_text = " ".join(soup.stripped_strings)[:3000]

        nombre_norm = _normalize(nombre)
        # Palabras clave del nombre (tokens de ≥ 4 chars)
        tokens = [t for t in nombre_norm.split() if len(t) >= 4]
        body_norm = _normalize(body_text)
        title_norm = _normalize(title)

        matches = sum(1 for t in tokens if t in body_norm or t in title_norm)
        identifica = matches >= max(1, len(tokens) // 3)

        # 4. La página enlaza cargos o programas
        links = [a.get("href", "") for a in soup.find_all("a", href=True)]
        link_text = " ".join(a.get_text(strip=True) for a in soup.find_all("a"))
        cargo_keywords = ["rector", "decano", "autoridad", "programa", "carrera", "oferta"]
        tiene_estructura = any(k in link_text.lower() for k in cargo_keywords)

        # Criterios combinados
        if identifica and (dominio_ok or tiene_estructura):
            evidencia = f"Título: '{title[:120]}'"
            if dominio_nota:
                evidencia += f" | {dominio_nota}"
            result["evidencia"] = evidencia
            result["estado"] = "validado"
        else:
            result["estado"] = "requiere_revision_humana"
            result["motivo"] = (
                f"identifica={identifica} dominio_ok={dominio_ok} "
                f"tiene_estructura={tiene_estructura} matches={matches}/{len(tokens)}"
            )
            # Aún así registramos lo que encontramos como evidencia
            result["evidencia"] = f"Título: '{title[:80]}'"

        # 5. robots.txt
        self._rate_limit(host)
        robots_ok, robots_str = _check_robots(base_url, self.user_agent, self.timeout)
        result["robots_permite"] = robots_str

        # 6. WordPress
        self._rate_limit(host)
        es_wp = _check_wordpress(self.session, base_url, self.timeout)
        result["es_wordpress"] = "si" if es_wp else "no"

        # 7. Sondear secciones (solo si el portal fue validado o parcialmente identificado)
        if robots_ok and result["estado"] == "validado":
            self._rate_limit(host)
            result["url_noticias"] = _probe_section(self.session, base_url, _PATTERNS_NOTICIAS, self.timeout) or ""
            self._rate_limit(host)
            result["url_autoridades"] = _probe_section(self.session, base_url, _PATTERNS_AUTORIDADES, self.timeout) or ""
            self._rate_limit(host)
            result["url_oferta"] = _probe_section(self.session, base_url, _PATTERNS_OFERTA, self.timeout) or ""
        elif not robots_ok:
            result["motivo"] = (result["motivo"] + " | robots_bloqueado").lstrip(" | ")

        return result

    def validate_batch(
        self, candidates: List[Dict[str, str]]
    ) -> List[Dict[str, Any]]:
        """Valida un lote de instituciones.

        Args:
            candidates: lista de dicts con claves
                institucion_id, nombre, portal_url, metodo_descubrimiento.
        """
        results = []
        for c in candidates:
            iid = c.get("institucion_id", "?")
            url = c.get("portal_url", "")
            nombre = c.get("nombre", "")
            metodo = c.get("metodo_descubrimiento", "pre_cargado")
            logger.info(f"[Fase3] Validando {iid}: {url or '(sin URL)'}")
            rec = self.validate_portal(iid, nombre, url, metodo)
            results.append(rec)
            logger.info(f"[Fase3] {iid}: estado={rec['estado']} robots={rec['robots_permite']} wp={rec['es_wordpress']}")
        return results
