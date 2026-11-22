"""
Extractor de carreras y programas academicos de grado, tecnologias y posgrado.

Extrae programas desde las secciones oficiales 'oferta-de-grado' y 'oferta-de-posgrado',
ingresando a las fichas individuales de cada carrera para obtener atributos curriculares,
resoluciones CES, perfiles de ingreso/egreso y modalidades de ensenanza.

Mejoras del Hito 2 (Fase E):
  E1. Integración con segunda fuente (SNIESE/CES).
  E2. Nuevos campos: financiamiento (del registro), estado_programa ('vigente', 'no_vigente', 'no_determinado'),
      evidencia_estado, anio_referencia = 2026, nivel y nivel_detalle.
  E3. Deduplicación por (institucion_id, nombre, nivel, modalidad) con registro de descartes.
  E4. Corrección de comparación de tildes en inferencia de facultad.
  E5. Filtro de descubrimiento revisado y documentado.
  B2. Trazabilidad completa en registros crudos.
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from bs4 import BeautifulSoup

from src.config import settings
from src.instituciones import registry
from src.scrapers.base_scraper import BaseScraper
from src.utils.helpers import (
    clean_text,
    extract_degree_level,
    extract_duration_periods,
    extract_labeled_value,
    extract_modality,
    page_lines,
    remove_accents,
)


class CarrerasScraper(BaseScraper):
    """Extrae informacion dimensional y descriptiva de las carreras ofrecidas por la institucion."""

    def __init__(
        self,
        http_client=None,
        institucion_id=None,
        institucion=None,
    ) -> None:
        super().__init__(
            http_client=http_client,
            institucion_id=institucion_id,
            institucion=institucion,
        )
        inst = self.institucion
        self._financiamiento = inst.financiamiento if inst else "pública"
        self._base_url = inst.base_url if inst and inst.base_url else settings.base_url
        self._endpoints = inst.endpoints if inst and inst.endpoints else settings.endpoints

    def _discover_program_urls(self) -> List[Tuple[str, str]]:
        """Descubre las URLs de programas de grado y posgrado en los portales oficiales.

        E5: Evalúa prefijos comunes de carreras en portales universitarios.
        Para la EPN incluye: ingenieria, licenciatura, tecnologia, carrera.
        """
        urls: List[Tuple[str, str]] = []
        seen: Set[str] = set()

        # 1. Oferta de Grado
        grado_url = self._endpoints.get("oferta_grado", f"{self._base_url}/oferta-de-grado/")
        html_grado = self.http_client.get(grado_url)
        if html_grado:
            soup = BeautifulSoup(html_grado, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href in seen:
                    continue
                # Prefijos soportados: ingenieria, licenciatura, tecnologia, carrera
                if any(href.startswith(f"{self._base_url}/{p}") for p in ["ingenieria", "licenciatura", "tecnologia", "carrera"]):
                    if "oferta-de-grado" not in href:
                        level = "Tecnologia" if "tecnologia" in href else "Grado"
                        urls.append((href, level))
                        seen.add(href)

        # 2. Oferta de Posgrado
        posgrado_url = self._endpoints.get("oferta_posgrado", f"{self._base_url}/oferta-de-posgrado/")
        html_posgrado = self.http_client.get(posgrado_url)
        if html_posgrado:
            soup = BeautifulSoup(html_posgrado, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href in seen:
                    continue
                if any(k in href for k in ["maestria-", "doctorado-", "/doctorados/"]) and self._base_url in href:
                    if not any(k in href for k in ["admision", "oferta-de-posgrado"]):
                        level = "Doctorado" if "doctorado" in href else "Maestria"
                        urls.append((href, level))
                        seen.add(href)

        self.logger.info(f"[{self.institucion_id}] Identificados {len(urls)} programas academicos para analisis detallado.")
        return urls

    TAB_LABELS = {
        "perfil de ingreso", "objetivos", "perfil de egreso", "perfil profesional", "malla",
        "requisitos", "horarios", "graduacion", "contacto",
    }
    SECTION_STOPS = (
        "objetivos de la carrera", "resultados generales", "resultados especificos", "requisitos de graduacion",
        "coordinador", "personal administrativo", "unidad academica", "horario de atencion",
    )
    MAX_PROFILE_CHARS = 1000

    @staticmethod
    def _norm(line: str) -> str:
        return remove_accents(line).lower().strip().rstrip(":")

    def _content_lines(self, lines: List[str]) -> List[str]:
        """Devuelve las lineas posteriores al bloque de pestanas (PERFIL DE INGRESO ... CONTACTO)."""
        for i, line in enumerate(lines):
            if self._norm(line) == "perfil de ingreso" and i + 1 < len(lines) and self._norm(lines[i + 1]) in self.TAB_LABELS:
                j = i
                while j < len(lines) and self._norm(lines[j]) in self.TAB_LABELS:
                    j += 1
                return lines[j:]
        return []

    def _join(self, parts: List[str]) -> Any:
        text = clean_text(" ".join(p.lstrip("* ").strip() for p in parts))
        return text[: self.MAX_PROFILE_CHARS] or None

    def _extract_profiles(self, lines: List[str]) -> Tuple[Any, Any, Any]:
        """Extrae perfil de ingreso, perfil de egreso y campo ocupacional."""
        content = self._content_lines(lines)
        if not content:
            return None, None, None

        ingreso: List[str] = []
        k = 0
        while k < len(content):
            n = self._norm(content[k])
            if content[k].startswith("*") or any(n.startswith(st) for st in self.SECTION_STOPS):
                break
            ingreso.append(content[k])
            k += 1

        egreso: List[str] = []
        norms = [self._norm(c) for c in content]
        if "resultados generales" in norms:
            start = norms.index("resultados generales") + 1
            for line, n in zip(content[start:], norms[start:]):
                if n.startswith("resultados especificos") or n.startswith("requisitos de graduacion"):
                    break
                if re.fullmatch(r"rg\d+\.?", n):
                    continue
                egreso.append(line)

        campo: List[str] = []
        for i, n in enumerate(norms):
            if n in ("campo ocupacional", "campo laboral", "ambito laboral", "ocupacion profesional"):
                for line, nn in zip(content[i + 1:], norms[i + 1:]):
                    if any(nn.startswith(st) for st in self.SECTION_STOPS):
                        break
                    campo.append(line)
                break

        return self._join(ingreso), self._join(egreso), self._join(campo)

    def _parse_program_page(self, url: str, suggested_level: str) -> Dict[str, Any]:
        """Parsea los datos de la ficha tecnica de un programa academico.

        Args:
            url (str): URL de la carrera o maestria.
            suggested_level (str): Nivel formativo sugerido ('Grado', 'Posgrado', etc.).

        Returns:
            Dict[str, Any]: Registro de carrera con atributos curriculares y campos de Hito 2.
        """
        html_content = self.http_client.get(url)
        if not html_content:
            self.logger.warning(f"Programa omitido: no se pudo obtener {url}")
            return {}

        soup = BeautifulSoup(html_content, "html.parser")
        lines = page_lines(BeautifulSoup(html_content, "html.parser"))

        # Nombre de la carrera
        nombre = ""
        h1 = soup.find("h1")
        if h1:
            nombre = clean_text(h1.get_text())
        if not nombre:
            title = soup.title.get_text() if soup.title else ""
            nombre = clean_text(title.replace("EPN", "").replace("-", "").strip())
        if not nombre:
            nombre = url.strip("/").split("/")[-1].replace("-", " ").title()

        # Facultad de pertenencia
        campos_inferidos: List[str] = []
        facultad_nombre = extract_labeled_value(lines, "Unidad Academica")

        # E4: Si la ficha no lo publica, inferencia por nombre normalizado (sin tildes)
        if not facultad_nombre:
            campos_inferidos.append("facultad")
            nombre_norm = remove_accents(nombre).lower()
            if any(k in nombre_norm for k in ["software", "computacion", "sistemas de informacion"]):
                facultad_nombre = "Facultad de Ingenieria de Sistemas"
            elif any(k in nombre_norm for k in ["civil", "ambiental", "hidraulica", "recursos hidricos"]):
                facultad_nombre = "Facultad de Ingenieria Civil y Ambiental"
            elif any(k in nombre_norm for k in ["electricidad", "electronica", "telecomunicacion", "ciberseguridad"]):
                facultad_nombre = "Facultad de Ingenieria Electrica y Electronica"
            elif any(k in nombre_norm for k in ["mecanica", "mecatronica", "automotriz", "produccion", "materiales", "diseno"]):
                facultad_nombre = "Facultad de Ingenieria Mecanica"
            elif any(k in nombre_norm for k in ["quimica", "agroindustria", "biociencias"]):
                facultad_nombre = "Facultad de Ingenieria Quimica y Agroindustria"
            elif any(k in nombre_norm for k in ["geologia", "petroleos", "metalurgia"]):
                facultad_nombre = "Facultad de Geologia y Petroleos"
            elif any(k in nombre_norm for k in ["administracion", "gerencia", "gestion integrados", "seguridad industrial"]):
                facultad_nombre = "Facultad de Ciencias Administrativas"
            elif any(k in nombre_norm for k in ["economia", "matematica", "estadistica", "fisica"]):
                facultad_nombre = "Facultad de Ciencias"
            elif "tecnologia" in nombre_norm:
                facultad_nombre = "Escuela de Formacion de Tecnologos"
            else:
                facultad_nombre = None  # No determinable: queda sin asignar en lugar de adivinar

        # Nivel de formacion y detalle (E2)
        nivel_detalle = extract_degree_level(nombre, suggested_level)
        # Nivel general para compatibilidad
        nivel = nivel_detalle
        nivel_macro = "Grado" if nivel_detalle in ("Grado", "Tecnologia") else "Posgrado"

        # Modalidad, duracion, titulo y resolucion
        modalidad = extract_modality(extract_labeled_value(lines, "Modalidad"))

        periodos = extract_duration_periods(extract_labeled_value(lines, "Duracion"))
        anios = round(periodos / 2.0, 1) if periodos is not None else None

        titulo_otorga = clean_text(extract_labeled_value(lines, "Titulo que otorga")) or None
        codigo_resolucion = extract_labeled_value(lines, "Resolucion de aprobacion CES")

        # E2: Estado de vigencia (una URL publicada no prueba vigencia)
        if codigo_resolucion:
            estado_programa = "vigente"
            evidencia_estado = f"Resolución CES publicada en portal: {codigo_resolucion}"
        else:
            estado_programa = "no_determinado"
            evidencia_estado = "Portal web institucional; requiere verificación en catastro SNIESE/CES"

        # Perfiles y campo ocupacional
        perfil_ingreso, perfil_egreso, campo_ocupacional = self._extract_profiles(lines)

        # Malla curricular URL
        malla_url = url
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "malla" in href.lower() or href.endswith(".pdf"):
                malla_url = href if href.startswith("http") else f"{self._base_url}{href}"
                break

        record = {
            "nombre": nombre,
            "facultad_nombre": facultad_nombre,
            "nivel": nivel,                              # Compatibilidad
            "nivel_detalle": nivel_detalle,              # E2
            "nivel_macro": nivel_macro,                  # E2
            "modalidad": modalidad,
            "financiamiento": self._financiamiento,      # E2 (desde instituciones.yaml)
            "estado_programa": estado_programa,          # E2
            "evidencia_estado": evidencia_estado,        # E2
            "anio_referencia": 2026,                     # E2
            "duracion_periodos": periodos,
            "duracion_anios": anios,
            "creditos": None,
            "titulo_otorga": titulo_otorga,
            "codigo_resolucion": codigo_resolucion,
            "perfil_ingreso": perfil_ingreso,
            "perfil_egreso": perfil_egreso,
            "campo_ocupacional": campo_ocupacional,
            "malla_curricular_url": malla_url,
            "url": url,
            "campos_inferidos": ",".join(campos_inferidos) or None,
        }
        # B2: Trazabilidad
        return self._add_traceability(record, fuente_url=url)

    def extract(self) -> List[Dict[str, Any]]:
        """Extrae el catalogo unificado de carreras y posgrados de la institucion.

        E3: Deduplica por (institucion_id, nombre, nivel, modalidad) y registra los descartados.
        """
        urls_with_level = self._discover_program_urls()
        programs_raw = []

        for url, suggested_level in urls_with_level:
            self.logger.info(f"[{self.institucion_id}] Parseando programa: {url}")
            data = self._parse_program_page(url, suggested_level)
            if data:
                programs_raw.append(data)

        # E3: Deduplicación por (institucion_id, nombre, nivel, modalidad)
        unique_programs: List[Dict[str, Any]] = []
        seen: Dict[Tuple, int] = {}
        discarded = 0

        for prog in programs_raw:
            key = (
                prog.get("institucion_id", ""),
                clean_text(prog.get("nombre", "")).lower(),
                str(prog.get("nivel", "")).lower(),
                str(prog.get("modalidad", "")).lower(),
            )
            if key in seen:
                discarded += 1
                self.logger.debug(
                    f"[{self.institucion_id}] Carrera duplicada descartada: {prog.get('nombre')} ({prog.get('nivel')})"
                )
            else:
                seen[key] = 1
                unique_programs.append(prog)

        if discarded:
            self.logger.info(
                f"[{self.institucion_id}] {discarded} registros de carreras descartados por deduplicación (E3)."
            )

        return unique_programs
