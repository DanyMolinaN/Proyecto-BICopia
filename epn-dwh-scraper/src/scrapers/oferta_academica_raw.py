"""Descarga conservadora de páginas oficiales de oferta y guarda enlaces crudos.

Las URLs iniciales son datos de configuración proporcionados por el equipo.
Este módulo no infiere programas: registra únicamente los enlaces y etiquetas
que aparecen en el contenido principal de cada página.
"""

import csv
import hashlib
import os
import re
import time
import urllib.robotparser
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from src.config import settings

BASE_DIR = Path(__file__).resolve().parents[2]
MATRIX_CSV = BASE_DIR / "config" / "matriz_fuentes_ies.csv"
CATALOG_CSV = BASE_DIR / "config" / "catalogo_ces.csv"
OUT_CSV = BASE_DIR / "data" / "raw" / "oferta_academica_enlaces_raw.csv"
FIELDS = [
    "run_id", "ces_cod", "nombre_ies", "provincia", "canton", "portal_url",
    "url_oferta", "estado_fuente_configurada", "tipo_registro", "enlace_texto_bruto", "url_enlace",
    "texto_contexto", "fuente_url", "fecha_descarga", "sha256", "estado",
]


def _load_inputs():
    with CATALOG_CSV.open(encoding="utf-8-sig", newline="") as f:
        catalog = {str(r["ces_cod"]): r for r in csv.DictReader(f)}
    with MATRIX_CSV.open(encoding="utf-8-sig", newline="") as f:
        matrix = list(csv.DictReader(f))
    ids = [str(r.get("ces_cod", "")).strip() for r in matrix]
    if len(matrix) != 64 or len(set(ids)) != 64 or set(ids) != set(catalog):
        raise ValueError(
            "config/matriz_fuentes_ies.csv debe contener una fila por cada uno "
            "de los 64 ces_cod de config/catalogo_ces.csv."
        )

    portals = []
    for row in matrix:
        code = str(row["ces_cod"]).strip()
        row["ces_cod"] = code
        row["ies"] = catalog[code]
        row["estado_fuente_configurada"] = (row.get("estado_oferta") or "").strip()

        portal = (row.get("portal_url") or "").strip()
        parsed_portal = urlparse(portal)
        if parsed_portal.scheme != "https" or not parsed_portal.hostname:
            raise ValueError(f"URL oficial inválida para ces_cod={code}: {portal}")
        row["portal_url"] = portal
        extra_hosts = [
            value.strip().lower().removeprefix("www.").rstrip(".")
            for value in re.split(r"[;\n]+", row.get("dominios_oficiales_adicionales", "") or "")
            if value.strip()
        ]
        official_hosts = list(dict.fromkeys([parsed_portal.hostname, *extra_hosts]))
        row["dominios_oficiales_permitidos"] = official_hosts

        offer_urls = []
        for value in re.split(r"[;\n]+", (row.get("url_oferta") or "").strip()):
            value = value.strip()
            if not value or not value.lower().startswith(("https://", "http://")):
                continue
            parsed = urlparse(value)
            if parsed.scheme != "https" or not parsed.hostname:
                raise ValueError(f"URL de oferta inválida para ces_cod={code}: {value}")
            if not _same_site_host(parsed.hostname, official_hosts):
                raise ValueError(
                    f"La URL de oferta no pertenece al sitio oficial configurado "
                    f"para ces_cod={code}: {value}"
                )
            offer_urls.append(value)
        row["offer_urls"] = list(dict.fromkeys(offer_urls))
        portals.append(row)
    return sorted(portals, key=lambda r: int(r["ces_cod"]))


def _same_site_host(host, official_host):
    """Acepta el dominio oficial y sus subdominios (por ejemplo admision.ies.edu.ec)."""
    host = (host or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if isinstance(official_host, str):
        official_hosts = [official_host]
    else:
        official_hosts = list(official_host or [])
    normalized_hosts = []
    for value in official_hosts:
        value = (value or "").lower().rstrip(".")
        if value.startswith("www."):
            value = value[4:]
        if value:
            normalized_hosts.append(value)
    return bool(host and any(host == allowed or host.endswith("." + allowed) for allowed in normalized_hosts))


class _PoliteReader:
    def __init__(self):
        contact = os.getenv("SCRAPER_CONTACT_EMAIL", "").strip()
        contact_part = f" (contacto: {contact})" if contact else ""
        self.agent = f"Equipo6-BI/1.0{contact_part}"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.agent, "Accept-Language": "es-EC,es;q=0.9"})
        self.robots = {}
        self.last = {}

    def get(self, url, allowed_hosts=None):
        host = (urlparse(url).hostname or "").lower()
        if host not in self.robots:
            robots_url = f"{urlparse(url).scheme}://{host}/robots.txt"
            self._pace(host)
            response = self._request(robots_url)
            if response.status_code != 200:
                raise RuntimeError(f"robots.txt no disponible (HTTP {response.status_code}); se detiene por precaución")
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(response.text.splitlines())
            self.robots[host] = parser
        if not self.robots[host].can_fetch(self.agent, url):
            raise PermissionError("bloqueado_robots")
        self._pace(host)
        response = self._request(url)
        if response.status_code != 200:
            raise RuntimeError(f"error_http_{response.status_code}")
        if not _same_site_host(urlparse(response.url).hostname, allowed_hosts or [host]):
            raise RuntimeError("redirección fuera del dominio oficial configurado")
        return response.content, response.url

    def _request(self, url):
        response = None
        for attempt in range(3):
            try:
                response = self.session.get(url, timeout=settings.timeout_seconds, allow_redirects=True)
                if response.status_code < 500 or attempt == 2:
                    return response
            except requests.RequestException:
                if attempt == 2:
                    raise
            time.sleep(2 ** attempt)
            self._pace(urlparse(url).netloc.lower())
        return response

    def _pace(self, host):
        elapsed = time.monotonic() - self.last.get(host, 0)
        if elapsed < max(1.0, settings.rate_limit_seconds):
            time.sleep(max(1.0, settings.rate_limit_seconds) - elapsed)
        self.last[host] = time.monotonic()


def _content_root(soup):
    return soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find("article") or soup.find(class_=re.compile(r"entry-content|content-area|page-content", re.I))


def _raw_rows(item, content, final_url, digest, timestamp, run_id):
    soup = BeautifulSoup(content, "html.parser")
    root = _content_root(soup)
    base = {
        "run_id": run_id,
        "ces_cod": item["ces_cod"],
        "nombre_ies": item["ies"]["nombre"],
        "provincia": item["ies"]["provincia"],
        "canton": item["ies"]["canton"],
        "portal_url": item["portal_url"],
        "url_oferta": item["url_oferta"],
        "estado_fuente_configurada": item["estado_fuente_configurada"],
        "fuente_url": final_url,
        "fecha_descarga": timestamp,
        "sha256": digest,
        "estado": "ok",
    }
    if root is None:
        return [{**base, "tipo_registro": "sin_clasificar", "enlace_texto_bruto": "", "url_enlace": "", "texto_contexto": "", "estado": "sin_contenedor_principal"}]
    rows = []
    for anchor in root.find_all("a", href=True):
        label = " ".join(anchor.get_text(" ", strip=True).split())
        href = urljoin(final_url, anchor["href"].strip())
        if not label or urlparse(href).scheme not in ("http", "https"):
            continue
        parent = anchor.parent
        context = " ".join(parent.get_text(" ", strip=True).split()) if parent else label
        rows.append({**base, "tipo_registro": "enlace_no_clasificado", "enlace_texto_bruto": label, "url_enlace": href, "texto_contexto": context})
    if not rows:
        rows.append({**base, "tipo_registro": "sin_clasificar", "enlace_texto_bruto": "", "url_enlace": "", "texto_contexto": "", "estado": "sin_enlaces_en_contenido"})
    return rows


def extraer_oferta_bruta():
    """Procesa URLs oficiales configuradas y anexa resultados crudos al CSV."""
    portals = _load_inputs()
    reader = _PoliteReader()
    run_id = str(uuid.uuid4())
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    write_header = not OUT_CSV.exists() or OUT_CSV.stat().st_size == 0
    with OUT_CSV.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        for item in portals:
            urls = item["offer_urls"]
            if not urls:
                timestamp = datetime.now(timezone.utc).isoformat()
                rows = [{
                    "run_id": run_id, "ces_cod": item["ces_cod"], "nombre_ies": item["ies"]["nombre"],
                    "provincia": item["ies"]["provincia"], "canton": item["ies"]["canton"],
                    "portal_url": item["portal_url"], "url_oferta": "",
                    "estado_fuente_configurada": item["estado_fuente_configurada"],
                    "fuente_url": item["portal_url"], "fecha_descarga": timestamp,
                    "sha256": "", "estado": "sin_url_oferta_configurada",
                    "tipo_registro": "sin_clasificar", "enlace_texto_bruto": "", "url_enlace": "", "texto_contexto": "",
                }]
                writer.writerows(rows)
                f.flush()
                print(f"{item['ces_cod']}: sin_url_oferta_configurada (0 páginas)")
                continue

            all_rows = []
            for offer_url in urls:
                timestamp = datetime.now(timezone.utc).isoformat()
                item["url_oferta"] = offer_url
                try:
                    content, final_url = reader.get(offer_url, item["dominios_oficiales_permitidos"])
                    digest = hashlib.sha256(content).hexdigest()
                    day_dir = settings.data_raw_dir / datetime.now(timezone.utc).strftime("%Y-%m-%d") / item["ces_cod"]
                    day_dir.mkdir(parents=True, exist_ok=True)
                    (day_dir / f"oferta_{digest[:16]}.html").write_bytes(content)
                    rows = _raw_rows(item, content, final_url, digest, timestamp, run_id)
                except Exception as exc:
                    state = "bloqueado_robots" if isinstance(exc, PermissionError) else "error_extraccion"
                    rows = [{
                        "run_id": run_id, "ces_cod": item["ces_cod"], "nombre_ies": item["ies"]["nombre"],
                        "provincia": item["ies"]["provincia"], "canton": item["ies"]["canton"],
                        "portal_url": item["portal_url"], "url_oferta": offer_url,
                        "estado_fuente_configurada": item["estado_fuente_configurada"],
                        "fuente_url": offer_url, "fecha_descarga": timestamp,
                        "sha256": "", "estado": f"{state}: {str(exc)[:180]}",
                        "tipo_registro": "sin_clasificar", "enlace_texto_bruto": "", "url_enlace": "", "texto_contexto": "",
                    }]
                all_rows.extend(rows)
            writer.writerows(all_rows)
            f.flush()
            print(f"{item['ces_cod']}: {len(urls)} páginas, {len(all_rows)} filas")
    print(f"CSV crudo incremental: {OUT_CSV}")


def plan_oferta_bruta():
    """Muestra la cobertura configurada sin consultar la red."""
    portals = _load_inputs()
    total_urls = sum(len(item["offer_urls"]) for item in portals)
    with_urls = sum(bool(item["offer_urls"]) for item in portals)
    print(f"Instituciones en matriz: {len(portals)}")
    print(f"Instituciones con URL de oferta: {with_urls}; sin URL: {len(portals) - with_urls}")
    print(f"Páginas de oferta configuradas: {total_urls}")
    print("Peticiones previstas: hasta 2 por página (robots.txt y oferta); secuenciales por host.")
    for item in portals:
        urls = "; ".join(item["offer_urls"]) or "SIN URL"
        print(f"{item['ces_cod']} | {item['ies']['nombre']} | {item['estado_fuente_configurada']} | {urls}")

