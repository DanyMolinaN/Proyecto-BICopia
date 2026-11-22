"""
Cliente HTTP con soporte para politicas eticas de web scraping y versionado de datos crudos.

Incluye cumplimiento de robots.txt, gestion de rate limiting, almacenamiento
en cache versionado por fecha (data/raw/<AAAA-MM-DD>/), manifiesto de descargas (manifest.csv),
reintentos con retroceso exponencial (backoff), metricas de ejecucion (G2) y
cabeceras identificables para fines academicos.
"""

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import urllib.robotparser
import requests
import urllib3

from src.config import settings
from src.utils.logger import setup_logger

if not settings.verify_ssl:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = setup_logger("http_client")


class HttpClient:
    """Gestiona las peticiones web respetando directivas eticas y tecnicas."""

    def __init__(
        self,
        use_cache: Optional[bool] = None,
        force_refresh: bool = False,
        institucion_id: str = "EPN",
        run_id: Optional[str] = None,
        per_institution_raw: bool = False,
        robots_url: Optional[str] = None,
        official_hosts: Optional[List[str]] = None,
    ) -> None:
        """Inicializa la sesion HTTP, el parser de robots.txt y el control de frecuencia.

        Args:
            use_cache (Optional[bool]): Sobrescribe el uso de cache (--no-cache).
            force_refresh (bool): Si es True, ignora la cache existente (--force-refresh).
            institucion_id (str): IES activa para trazabilidad en manifiesto.
            run_id (Optional[str]): Identificador único de ejecución.
        per_institution_raw (bool): Si es True, versiona en data/raw/<fecha>/<institucion_id>/<run_id>/.
        """
        self.force_refresh = force_refresh
        self.institucion_id = institucion_id
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        self.per_institution_raw = per_institution_raw
        self.robots_url = robots_url
        configured_robots_url = robots_url or settings.endpoints.get("robots_txt", f"{settings.base_url}/robots.txt")
        self.official_host = (urlparse(configured_robots_url).hostname or "").lower().removeprefix("www.")
        extra_hosts = [self._normalize_host(host) for host in (official_hosts or [])]
        self.official_hosts = list(dict.fromkeys([self.official_host, *[host for host in extra_hosts if host]]))
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
            "Accept-Language": "es-EC,es;q=0.9,en;q=0.8",
        })
        self.rate_limit_seconds = settings.rate_limit_seconds
        self.last_request_time = 0.0
        self.raw_dir = settings.data_raw_dir
        self.use_cache = settings.use_cache if use_cache is None else use_cache
        self.today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # G2: Estadísticas de ejecución
        self.stats: Dict[str, Any] = {
            "urls_consultadas": 0,
            "bloqueadas_robots": 0,
            "con_error": 0,
            "exitosas": 0,
            "detalles": [],
        }

        # Parser de robots.txt
        self._robot_parser: Optional[urllib.robotparser.RobotFileParser] = None
        self._robots_unreachable = False
        self._robot_parsers: Dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}
        self._robots_unreachable_hosts = set()
        self._robots_checked_hosts = set()
        self._init_robots_txt(robots_url)
        self.initial_network_details = list(self.stats.get("detalles", []))

    @property
    def dated_raw_dir(self) -> Path:
        """G1: Directorio de almacenamiento crudo versionado por fecha."""
        p = self.raw_dir / self.today_str
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _init_robots_txt(self, robots_url: Optional[str] = None) -> None:
        """Load the robots policy for the institution's primary host."""
        robots_url = robots_url or settings.endpoints.get("robots_txt", f"{settings.base_url}/robots.txt")
        self._load_robots_for_host(robots_url)

    @staticmethod
    def _normalize_host(host: str) -> str:
        host = (host or "").lower().rstrip(".")
        return host[4:] if host.startswith("www.") else host

    def _is_official_host(self, host: str) -> bool:
        candidate = self._normalize_host(host)
        return bool(candidate and any(
            candidate == root or candidate.endswith("." + root)
            for root in self.official_hosts if root
        ))

    def _load_robots_for_host(self, robots_url: str) -> None:
        """Load the policy from the same host as the requested page."""
        parsed_url = urlparse(robots_url)
        host_key = self._normalize_host(parsed_url.hostname or "")
        if not host_key:
            self._robots_unreachable = True
            return
        try:
            if self.last_request_time:
                self._apply_rate_limit()
            response = self.session.get(
                robots_url,
                timeout=settings.timeout_seconds,
                verify=settings.verify_ssl,
            )
            response_host = self._normalize_host(urlparse(getattr(response, "url", robots_url)).hostname or "")
            if not self._is_official_host(response_host):
                self._robots_unreachable_hosts.add(host_key)
                logger.error("robots.txt redirected outside the configured official hosts")
            elif response.status_code == 200:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(response.text.splitlines())
                self._robot_parsers[host_key] = parser
                logger.info(f"robots.txt loaded from: {robots_url}")
            elif response.status_code in (404, 410):
                logger.info(f"robots.txt not found (HTTP {response.status_code}); no rules were published")
                self._robot_parsers[host_key] = None
                self.stats["detalles"].append({
                    "url": robots_url, "estado": f"robots_http_{response.status_code}"
                })
            elif response.status_code in (401, 403):
                self._robots_unreachable_hosts.add(host_key)
                logger.warning(f"robots.txt denied access (HTTP {response.status_code}); stopping requests for this host")
                self.stats["detalles"].append({
                    "url": robots_url, "estado": f"robots_denegado_{response.status_code}"
                })
            elif 400 <= response.status_code < 500:
                self._robots_unreachable_hosts.add(host_key)
                logger.warning(f"robots.txt returned HTTP {response.status_code}; stopping requests for this host")
                self.stats["detalles"].append({
                    "url": robots_url, "estado": f"robots_http_{response.status_code}"
                })
            else:
                self._robots_unreachable_hosts.add(host_key)
                logger.error(f"robots.txt returned HTTP {response.status_code}; stopping requests for this host")
                self.stats["detalles"].append({
                    "url": robots_url, "estado": f"robots_http_{response.status_code}"
                })
        except Exception as exc:
            self._robots_unreachable_hosts.add(host_key)
            logger.error(f"Could not read robots.txt ({exc}); stopping requests for this host")
            self.stats["detalles"].append({
                "url": robots_url,
                "estado": f"robots_error_{type(exc).__name__.lower()}",
                "detalle": str(exc)[:180],
            })
        finally:
            self._robots_checked_hosts.add(host_key)
            if host_key == self._normalize_host(self.official_host):
                self._robot_parser = self._robot_parsers.get(host_key)
                self._robots_unreachable = host_key in self._robots_unreachable_hosts

    def is_allowed(self, url: str) -> bool:
        """Check the robots policy belonging to the URL's own host."""
        parsed = urlparse(url)
        if parsed.scheme != "https":
            return False
        host_key = self._normalize_host(parsed.hostname or "")
        if not self._is_official_host(host_key):
            return False
        if host_key not in self._robots_checked_hosts:
            self._load_robots_for_host(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
        if host_key in self._robots_unreachable_hosts:
            return False
        if host_key == self._normalize_host(self.official_host) and getattr(self, "_robots_unreachable", False):
            return False
        parser = self._robot_parsers.get(host_key)
        if host_key == self._normalize_host(self.official_host) and getattr(self, "_robot_parser", None) is not None:
            parser = self._robot_parser
        if parser is None:
            return True
        return parser.can_fetch(settings.user_agent, url)

    def _apply_rate_limit(self) -> None:
        """Aplica una pausa forzada entre solicitudes sucesivas para proteger el servidor."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_seconds:
            sleep_time = self.rate_limit_seconds - elapsed
            time.sleep(sleep_time)
        self.last_request_time = time.time()

    def _get_cache_path(self, url: str, extension: str = "html") -> Path:
        """Calcula la ruta del archivo de cache a partir del hash de la URL."""
        slug = re.sub(r"[^a-zA-Z0-9_-]", "_", url.replace("https://", "").replace("http://", ""))
        slug = slug[:50]
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
        filename = f"{slug}_{url_hash}.{extension}"

        # 0. Cada corrida conserva su propia copia cruda para no reemplazar versiones anteriores.
        if getattr(self, "per_institution_raw", False) and getattr(self, "institucion_id", None):
            try:
                inst_dir = self.dated_raw_dir / str(self.institucion_id) / str(self.run_id)
                inst_dir.mkdir(parents=True, exist_ok=True)
                inst_path = inst_dir / filename
                if inst_path.exists():
                    return inst_path
                return inst_path
            except Exception:
                pass

        # 1. Si existe en el directorio versionado, devolverlo
        try:
            dated_path = self.dated_raw_dir / filename
            if dated_path.exists():
                return dated_path
        except Exception:
            pass

        # 2. Si existe en raw_dir raíz, devolverlo
        legacy_path = self.raw_dir / filename
        if legacy_path.exists():
            return legacy_path

        # 3. Retornar ruta en dated_raw_dir si está disponible, si no legacy_path
        try:
            return self.dated_raw_dir / filename
        except Exception:
            return legacy_path

    def _cache_is_fresh(self, cache_path: Path) -> bool:
        """Indica si existe una entrada de cache cuya antiguedad no supera el TTL configurado."""
        if not cache_path.exists():
            return False
        ttl_hours = settings.cache_ttl_hours
        if ttl_hours <= 0:
            return True
        age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
        return age_hours <= ttl_hours

    def _record_manifest(self, url: str, status_code: int, content: Any) -> None:
        """G1: Registra la descarga en el archivo manifest.csv versionado."""
        try:
            payload = content if isinstance(content, bytes) else str(content).encode("utf-8", errors="ignore")
            sha256 = hashlib.sha256(payload).hexdigest()
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            # 1. Manifiesto en dated_raw_dir (compatibilidad con tests existentes)
            manifest_path = self.dated_raw_dir / "manifest.csv"
            write_header = not manifest_path.exists()
            with open(manifest_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if write_header:
                    writer.writerow(["url", "estado_http", "fecha_descarga", "sha256", "institucion_id", "run_id"])
                writer.writerow([url, status_code, now_iso, sha256, self.institucion_id, self.run_id])

            # 2. Registrar también dentro del directorio crudo versionado de esta IES/corrida.
            if getattr(self, "per_institution_raw", False) and getattr(self, "institucion_id", None):
                inst_dir = self.dated_raw_dir / str(self.institucion_id) / str(self.run_id)
                inst_dir.mkdir(parents=True, exist_ok=True)
                inst_manifest_path = inst_dir / "manifest.csv"
                write_inst_header = not inst_manifest_path.exists()
                with open(inst_manifest_path, "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    if write_inst_header:
                        writer.writerow(["url", "estado_http", "fecha_descarga", "sha256", "institucion_id", "run_id"])
                    writer.writerow([url, status_code, now_iso, sha256, self.institucion_id, self.run_id])
        except Exception as exc:
            logger.warning(f"No se pudo escribir en manifest.csv: {exc}")

    def get(self, url: str, use_cache: Optional[bool] = None, force_refresh: bool = False) -> Optional[str]:
        """Realiza una peticion GET retornando el texto de la respuesta con manejo de cache y reintentos."""
        if not hasattr(self, "stats"):
            self.stats = {"urls_consultadas": 0, "bloqueadas_robots": 0, "con_error": 0, "exitosas": 0, "detalles": []}
        if not hasattr(self, "institucion_id"):
            self.institucion_id = "EPN"
        if not hasattr(self, "run_id"):
            self.run_id = "default"
        if not hasattr(self, "today_str"):
            self.today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        self.stats["urls_consultadas"] += 1

        if urlparse(url).scheme != "https":
            self.stats["con_error"] += 1
            self.stats["detalles"].append({"url": url, "estado": "url_no_https"})
            return None
        if not self.is_allowed(url):
            logger.warning(f"Extraccion rechazada por politica de robots.txt para URL: {url}")
            self.stats["bloqueadas_robots"] += 1
            self.stats["detalles"].append({"url": url, "estado": "bloqueada_robots"})
            return None

        should_cache = self.use_cache if use_cache is None else use_cache
        url_path = urlparse(url).path.lower()
        cache_extension = "json" if "/wp-json/" in url_path or url_path.endswith(".json") else "html"
        cache_path = self._get_cache_path(url, extension=cache_extension)

        if should_cache and not (force_refresh or getattr(self, "force_refresh", False)) and self._cache_is_fresh(cache_path):
            logger.debug(f"Cargando recurso desde cache local: {cache_path.name}")
            try:
                self.stats["exitosas"] += 1
                self.stats["detalles"].append({"url": url, "estado": "cache_hit"})
                return cache_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as read_err:
                logger.warning(f"Error al leer cache local {cache_path}: {read_err}. Se intentara via red.")

        retries = settings.max_retries
        backoff = settings.backoff_factor

        last_network_error = None
        last_http_status = None
        for attempt in range(1, retries + 1):
            self._apply_rate_limit()
            try:
                logger.debug(f"Solicitando URL (Intento {attempt}/{retries}): {url}")
                response = self.session.get(
                    url,
                    timeout=settings.timeout_seconds,
                    verify=settings.verify_ssl,
                )

                final_url = getattr(response, "url", url)
                final_host = (urlparse(final_url).hostname or "").lower().removeprefix("www.")
                if not self._is_official_host(final_host):
                    logger.warning(f"Redirección fuera del portal oficial; se omite: {url} -> {final_url}")
                    self.stats["con_error"] += 1
                    self.stats["detalles"].append({"url": url, "estado": "redireccion_fuera_sitio_oficial"})
                    return None

                if response.status_code == 200:
                    content = response.text
                    if should_cache:
                        try:
                            cache_path.parent.mkdir(parents=True, exist_ok=True)
                            cache_path.write_text(content, encoding="utf-8", errors="ignore")
                            self._record_manifest(url, response.status_code, content)
                        except Exception as write_err:
                            logger.warning(f"No fue posible escribir en cache {cache_path}: {write_err}")
                    self.stats["exitosas"] += 1
                    self.stats["detalles"].append({"url": url, "estado": "descargada_200"})
                    return content

                if response.status_code in [404, 410]:
                    logger.warning(f"Recurso no encontrado (HTTP {response.status_code}) en {url}")
                    self.stats["con_error"] += 1
                    self.stats["detalles"].append({"url": url, "estado": f"http_{response.status_code}"})
                    return None

                if response.status_code in [429, 500, 502, 503, 504]:
                    last_http_status = response.status_code
                    wait_time = backoff ** attempt
                    logger.warning(f"HTTP {response.status_code} en {url}. Reintentando en {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    continue

                logger.warning(f"Codigo de respuesta inesperado {response.status_code} para {url}")
                self.stats["con_error"] += 1
                self.stats["detalles"].append({"url": url, "estado": f"http_{response.status_code}"})
                return None

            except requests.exceptions.RequestException as req_err:
                last_network_error = req_err
                wait_time = backoff ** attempt
                logger.warning(f"Error de conexion en {url} ({req_err}). Reintentando en {wait_time:.1f}s...")
                time.sleep(wait_time)

        logger.error(f"Se agotaron los {retries} reintentos para la URL: {url}")
        self.stats["con_error"] += 1
        if last_network_error is not None:
            error_name = type(last_network_error).__name__.lower()
            state = "error_ssl" if "ssl" in error_name or "certificate" in str(last_network_error).lower() else f"error_red_{error_name}"
            detail = str(last_network_error)[:180]
        elif last_http_status is not None:
            state = f"http_{last_http_status}"
            detail = "Se agotaron los reintentos tras una respuesta HTTP temporal."
        else:
            state = "error_red_desconocido"
            detail = "Se agotaron los reintentos sin respuesta HTTP."
        self.stats["detalles"].append({"url": url, "estado": state, "detalle": detail})
        return None

    def get_bytes(self, url: str, use_cache: Optional[bool] = None, force_refresh: bool = False) -> Optional[bytes]:
        """Download bytes from an allowed official URL (for PDFs and documents)."""
        if not hasattr(self, "stats"):
            self.stats = {"urls_consultadas": 0, "bloqueadas_robots": 0, "con_error": 0, "exitosas": 0, "detalles": []}
        self.stats["urls_consultadas"] += 1
        if urlparse(url).scheme != "https":
            self.stats["con_error"] += 1
            self.stats["detalles"].append({"url": url, "estado": "url_no_https"})
            return None
        if not self.is_allowed(url):
            self.stats["bloqueadas_robots"] += 1
            self.stats["detalles"].append({"url": url, "estado": "bloqueada_robots"})
            return None

        should_cache = self.use_cache if use_cache is None else use_cache
        cache_path = self._get_cache_path(url, extension="bin")
        if should_cache and not (force_refresh or getattr(self, "force_refresh", False)) and self._cache_is_fresh(cache_path):
            try:
                content = cache_path.read_bytes()
                self.stats["exitosas"] += 1
                self.stats["detalles"].append({"url": url, "estado": "cache_hit"})
                return content
            except OSError:
                pass

        retries = settings.max_retries
        backoff = settings.backoff_factor
        last_error = None
        last_status = None
        for attempt in range(1, retries + 1):
            self._apply_rate_limit()
            try:
                response = self.session.get(url, timeout=settings.timeout_seconds, verify=settings.verify_ssl)
                final_host = self._normalize_host(urlparse(getattr(response, "url", url)).hostname or "")
                if not self._is_official_host(final_host):
                    self.stats["con_error"] += 1
                    self.stats["detalles"].append({"url": url, "estado": "redireccion_fuera_sitio_oficial"})
                    return None
                if response.status_code == 200:
                    content = response.content
                    if should_cache:
                        try:
                            cache_path.parent.mkdir(parents=True, exist_ok=True)
                            cache_path.write_bytes(content)
                            self._record_manifest(url, response.status_code, content)
                        except OSError as exc:
                            logger.warning(f"No fue posible guardar contenido binario: {exc}")
                    self.stats["exitosas"] += 1
                    self.stats["detalles"].append({"url": url, "estado": "descargada_200"})
                    return content
                if response.status_code in (404, 410):
                    self.stats["con_error"] += 1
                    self.stats["detalles"].append({"url": url, "estado": f"http_{response.status_code}"})
                    return None
                if response.status_code in (429, 500, 502, 503, 504):
                    last_status = response.status_code
                    time.sleep(backoff ** attempt)
                    continue
                self.stats["con_error"] += 1
                self.stats["detalles"].append({"url": url, "estado": f"http_{response.status_code}"})
                return None
            except requests.exceptions.RequestException as exc:
                last_error = exc
                time.sleep(backoff ** attempt)

        self.stats["con_error"] += 1
        if last_error is not None:
            err_name = type(last_error).__name__.lower()
            status = "error_ssl" if "ssl" in err_name or "certificate" in str(last_error).lower() else f"error_red_{err_name}"
            detail = str(last_error)[:180]
        elif last_status is not None:
            status, detail = f"http_{last_status}", "Reintentos agotados tras respuesta HTTP temporal."
        else:
            status, detail = "error_red_desconocido", "Reintentos agotados sin respuesta."
        self.stats["detalles"].append({"url": url, "estado": status, "detalle": detail})
        return None

    def get_json(self, url: str, use_cache: Optional[bool] = None) -> Optional[dict]:
        """Obtiene y decodifica un payload JSON con soporte de cache local."""
        should_cache = self.use_cache if use_cache is None else use_cache
        cache_path = self._get_cache_path(url, extension="json")

        if should_cache and not getattr(self, "force_refresh", False) and self._cache_is_fresh(cache_path):
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        text = self.get(url, use_cache=False, force_refresh=True)
        if text:
            try:
                data = json.loads(text)
                if should_cache:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                return data
            except json.JSONDecodeError as json_err:
                logger.error(f"Fallo al decodificar JSON desde {url}: {json_err}")
        return None

    def report_stats(self) -> Dict[str, Any]:
        """G2: Informa el reporte de URLs consultadas, bloqueadas, con error y exitosas."""
        summary = {
            "institucion_id": getattr(self, "institucion_id", "EPN"),
            "run_id": getattr(self, "run_id", "default"),
            "fecha": getattr(self, "today_str", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
            "urls_consultadas": self.stats.get("urls_consultadas", 0),
            "exitosas": self.stats.get("exitosas", 0),
            "bloqueadas_robots": self.stats.get("bloqueadas_robots", 0),
            "con_error": self.stats.get("con_error", 0),
        }
        logger.info(
            f"=== Resumen de Red [{summary['institucion_id']}] ===\n"
            f"  Total URLs consultadas: {summary['urls_consultadas']}\n"
            f"  Exitosas (descarga/cache): {summary['exitosas']}\n"
            f"  Bloqueadas por robots.txt: {summary['bloqueadas_robots']}\n"
            f"  Con error de conexion/HTTP: {summary['con_error']}"
        )
        return summary
