"""
Pruebas unitarias para los nuevos componentes del Hito 2 / Fase 3:
- CesPerfilScraper (parseo de ficha CES)
- PortalValidator (criterios de validación de portal, robots, WP)
- Ces64Runner (comando único multi-institución, estados, reanudar)
- actualizar_yaml_desde_csv (script reproducible)
"""

import csv
import json
from unittest.mock import MagicMock, patch
import pytest

from src.instituciones import InstitucionConfig, load_ces64, registry
from src.scrapers.ces_perfil_scraper import CesPerfilScraper
from src.scrapers.portal_validator import (
    PortalValidator,
    _is_soft_404,
    _probe_section,
    _check_robots,
)
from src.ces64_runner import Ces64Runner, _estado_modulo, _build_inst_from_portal
from src.scrapers.carreras_scraper import CarrerasScraper
from src.utils.http_client import HttpClient


class TestCes64Components:
    """Verifica la lógica del orquestador CES-64 y validación de portales."""

    def test_institucion_config_smart_lookup(self):
        """El registro debe encontrar tanto por 'EPN' como por '1001'."""
        inst_by_id = registry.get("EPN")
        assert inst_by_id is not None
        assert inst_by_id.sigla == "EPN"

        # Búsqueda por código CES
        inst_by_cod = registry.get("1001")
        assert inst_by_cod is not None
        assert inst_by_cod.nombre == "Escuela Politécnica Nacional"

    def test_ces_perfil_scraper_parse_ficha(self):
        """Verifica la extracción fiel de campos de la ficha CES."""
        sample_html = """
        <html>
            <body>
                <table>
                    <tr><th>Nombre</th><td>ESCUELA POLITÉCNICA NACIONAL</td></tr>
                    <tr><th>Sede</th><td>DISTRITO METROPOLITANO DE QUITO</td></tr>
                    <tr><th>Siglas</th><td>EPN</td></tr>
                    <tr><th>Rector</th><td>Dr. Tarquino Sánchez Almeida</td></tr>
                    <tr><th>Cargo</th><td>RECTOR</td></tr>
                    <tr><th>Inicio de gestión</th><td>2023-12-08</td></tr>
                    <tr><th>Fin de gestión</th><td>2028-12-07</td></tr>
                </table>
            </body>
        </html>
        """
        row = {
            "ces_cod": "1001",
            "ces_codp": "328",
            "tipo_ces": "publica",
            "nombre": "ESCUELA POLITÉCNICA NACIONAL",
            "provincia": "PICHINCHA",
            "canton": "DISTRITO METROPOLITANO DE QUITO",
        }
        scraper = CesPerfilScraper()
        rec = scraper._parse_ficha(sample_html, "https://ces.gob.ec/ficha", row)

        assert rec["nombre_ces"] == "ESCUELA POLITÉCNICA NACIONAL"
        assert rec["rector_nombre"] == "Dr. Tarquino Sánchez Almeida"
        assert rec["fecha_inicio_gestion"] == "2023-12-08"
        assert rec["fecha_fin_gestion"] == "2028-12-07"
        assert rec["discrepancia_nombre"] is False
        assert rec["estado_extraccion"] == "ok"

    def test_ces_perfil_scraper_discrepancia_nombre(self):
        """Registra discrepancia de nombre sin alterar el dato fuente."""
        sample_html = """
        <html><body><table>
            <tr><th>Nombre</th><td>UNIVERSIDAD DISTINTA</td></tr>
            <tr><th>Rector</th><td>Dra. Alguien</td></tr>
        </table></body></html>
        """
        row = {
            "ces_cod": "9999",
            "ces_codp": "328",
            "tipo_ces": "publica",
            "nombre": "UNIVERSIDAD ORIGINAL",
            "provincia": "PICHINCHA",
            "canton": "QUITO",
        }
        scraper = CesPerfilScraper()
        rec = scraper._parse_ficha(sample_html, "https://ces.gob.ec/ficha", row)
        assert rec["discrepancia_nombre"] is True
        assert rec["estado_extraccion"] == "ok"

    def test_portal_validator_criterios_identificacion(self):
        """Valida que una institución sea reconocida por título y contenido."""
        validator = PortalValidator()
        with patch.object(validator.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html><head><title>Escuela Politécnica Nacional - Inicio</title></head><body><h1>EPN</h1><a href='/rectorado'>Rectorado</a></body></html>"
            mock_get.return_value = mock_resp

            with patch("src.scrapers.portal_validator._check_robots", return_value=(True, "si")):
                with patch("src.scrapers.portal_validator._check_wordpress", return_value=True):
                    with patch("src.scrapers.portal_validator._probe_section", return_value="https://www.epn.edu.ec/noticias"):
                        rec = validator.validate_portal(
                            "1001", "ESCUELA POLITÉCNICA NACIONAL", "https://www.epn.edu.ec"
                        )
                        assert rec["estado"] == "validado"
                        assert rec["es_wordpress"] == "si"
                        assert rec["robots_permite"] == "si"
                        assert "https://www.epn.edu.ec/noticias" in rec["url_noticias"]

    def test_estado_modulo_sin_portal_o_bloqueado(self):
        """Evalúa los estados iniciales de los módulos según la validación del portal."""
        inst = InstitucionConfig({
            "id": "1002",
            "nombre": "ESPOCH",
            "sigla": "ESPOCH",
            "base_url": "",
            "endpoints": {},
            "adaptador": "pendiente",
        })

        # Sin portal validado
        assert _estado_modulo(inst, "noticias", None) == "sin_seccion"
        assert _estado_modulo(inst, "autoridades", None) == "sin_seccion"
        # CES siempre se puede intentar
        assert _estado_modulo(inst, "ces", None) == "pendiente"

        # Con robots que bloquea
        portal_bloqueado = {"estado": "validado", "robots_permite": "no", "url_noticias": "https://x/news"}
        assert _estado_modulo(inst, "noticias", portal_bloqueado) == "bloqueado_robots"

    def test_ces64_runner_dry_run(self):
        """Ces64Runner en dry-run no debe fallar ni persistir registros erróneos."""
        runner = Ces64Runner(
            modulos=["ces"],
            institucion_ids=["1001"],
            dry_run=True,
        )
        tabla = runner.run()
        # En dry-run para 1001 y ces, debe registrar la ejecución sin romper
        assert isinstance(tabla, list)

    def test_soft_404_detection(self):
        """Detecta soft 404 por título o redirección a la portada y no la acepta como sección válida."""
        # Caso 1: Redirección a la portada
        assert _is_soft_404("<html><body>Bienvenido</body></html>", "https://ies.edu.ec/", "https://ies.edu.ec") is True
        assert _is_soft_404("<html><body>Bienvenido</body></html>", "https://ies.edu.ec/index.php", "https://ies.edu.ec") is True

        # Caso 2: HTTP 200 pero texto contiene 404 / no encontrada
        html_soft = "<html><head><title>404 Not Found - Universidad</title></head><body><h1>Página no encontrada</h1></body></html>"
        assert _is_soft_404(html_soft, "https://ies.edu.ec/carreras", "https://ies.edu.ec") is True

        # Caso 3: Página válida real
        html_ok = "<html><head><title>Oferta Académica - Universidad</title></head><body><h1>Carreras de Grado</h1><p>Lista de programas</p></body></html>"
        assert _is_soft_404(html_ok, "https://ies.edu.ec/carreras", "https://ies.edu.ec") is False

        # Caso 4: _probe_section descarta respuesta 200 con soft 404
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = "https://ies.edu.ec/noticias"
        mock_resp.text = html_soft
        mock_session.get.return_value = mock_resp

        result = _probe_section(mock_session, "https://ies.edu.ec", ["/noticias"], timeout=5)
        assert result is None

    def test_robots_prohibits(self):
        """Valida que robots.txt prohibitivo marque bloqueado_robots y bloquee el módulo."""
        inst = InstitucionConfig({
            "id": "1005", "nombre": "UCE", "sigla": "UCE",
            "base_url": "https://www.uce.edu.ec",
            "endpoints": {"noticias_web": "https://www.uce.edu.ec/noticias"},
            "adaptador": "wordpress",
        })
        portal = {
            "estado": "validado",
            "robots_permite": "no",
            "url_noticias": "https://www.uce.edu.ec/noticias",
        }
        assert _estado_modulo(inst, "noticias", portal) == "bloqueado_robots"

    def test_estado_modulo_transitions(self):
        """Verifica todas las transiciones de estado de módulo."""
        inst = InstitucionConfig({
            "id": "1018", "nombre": "UAE", "sigla": "UAE",
            "base_url": "https://www.uagraria.edu.ec",
            "endpoints": {},
            "adaptador": "propio",
        })
        # Sin sección
        portal = {"estado": "validado", "robots_permite": "si", "url_noticias": ""}
        assert _estado_modulo(inst, "noticias", portal) == "sin_seccion"

        # Sin adaptador (portal no wordpress para noticias)
        portal["url_noticias"] = "https://www.uagraria.edu.ec/noticias"
        assert _estado_modulo(inst, "noticias", portal) == "sin_adaptador"

        # Listo para ejecutar
        inst_wp = InstitucionConfig({
            "id": "1002", "nombre": "ESPOCH", "sigla": "ESPOCH",
            "base_url": "https://www.espoch.edu.ec",
            "endpoints": {"noticias_web": "https://www.espoch.edu.ec/noticias"},
            "adaptador": "wordpress",
        })
        portal_wp = {"estado": "validado", "robots_permite": "si", "url_noticias": "https://www.espoch.edu.ec/noticias"}
        assert _estado_modulo(inst_wp, "noticias", portal_wp) == "pendiente"

    def test_failure_isolation(self):
        """El fallo en una institución no detiene la ejecución de las demás."""
        runner = Ces64Runner(
            modulos=["ces"],
            institucion_ids=["1001", "1002"],
            dry_run=False,
        )
        # Mockeamos _run_modulo para que la primera falle y la segunda tenga éxito
        with patch("src.ces64_runner._run_modulo") as mock_run_m:
            mock_run_m.side_effect = [
                {"institucion_id": "1001", "modulo": "ces", "estado": "error_http", "registros_extraidos": 0, "paginas_consultadas": 1, "mensaje": "Connection timeout"},
                {"institucion_id": "1002", "modulo": "ces", "estado": "ok", "registros_extraidos": 1, "paginas_consultadas": 1, "mensaje": "Ficha CES ok"},
            ]
            tabla = runner.run()
            assert len(tabla) == 2
            assert tabla[0]["estado"] == "error_http"
            assert tabla[1]["estado"] == "ok"

    def test_reanudar_skips_ok(self):
        """--reanudar omite instituciones/módulos que ya terminaron con ok en el mismo run_id."""
        runner = Ces64Runner(
            modulos=["ces"],
            institucion_ids=["1001"],
            reanudar=True,
        )
        from src.ces64_runner import _RUN_ID
        runner._ejecucion_previa = {(_RUN_ID, "1001", "ces"): "ok"}
        assert runner._skip("1001", "ces") is True

        # Si el estado anterior fue parcial o error, NO se debe omitir
        runner._ejecucion_previa = {(_RUN_ID, "1001", "ces"): "parcial"}
        assert runner._skip("1001", "ces") is False

    def test_ces_perfil_scraper_estructura_distinta(self):
        """Verifica que el parser de CES funcione tanto con formato secuencial h4color/entry-content como con fallback por párrafos clave-valor."""
        # Formato párrafos o divs con etiquetas clave-valor
        html_distinto = """
        <html>
            <div class="entry-content">
                <p>INSTITUCIÓN: UNIVERSIDAD EXPERIMENTAL DEL SUR</p>
                <p>SIGLA: UNESUR</p>
                <p>SEDE: SEDE PRINCIPAL</p>
                <p>DIRECCIÓN: AV. AMAZONAS 123</p>
                <p>FECHA CREACIÓN: 2005-03-15</p>
                <p>RECTOR: Dra. Carmen Rodríguez</p>
                <p>FECHA DE INICIO GESTIÓN: 2022-05-10</p>
                <p>FECHA FIN DE GESTIÓN: 2027-05-10</p>
            </div>
        </html>
        """
        row = {
            "ces_cod": "2050",
            "ces_codp": "328",
            "tipo_ces": "publica",
            "nombre": "UNIVERSIDAD EXPERIMENTAL DEL SUR",
            "provincia": "LOJA",
            "canton": "LOJA",
        }
        scraper = CesPerfilScraper()
        rec = scraper._parse_ficha(html_distinto, "https://ces.gob.ec/ficha", row)
        assert rec["nombre_ces"] == "UNIVERSIDAD EXPERIMENTAL DEL SUR"
        assert rec["rector_nombre"] == "Dra. Carmen Rodríguez"
        assert rec["fecha_inicio_gestion"] == "2022-05-10"
        assert rec["fecha_fin_gestion"] == "2027-05-10"
        assert rec["estado_extraccion"] == "ok"

    def test_epn_baseline_regression(self):
        """Prueba de regresión EPN: verifica que con los endpoints oficiales restaurados se extraen 46 programas (18 de grado y 28 de posgrado)."""
        inst_epn = registry.get("1001")
        assert inst_epn is not None
        # Validar que endpoints sean los correctos
        assert inst_epn.endpoints.get("oferta_grado") == "https://www.epn.edu.ec/oferta-de-grado/"
        assert inst_epn.endpoints.get("oferta_posgrado") == "https://www.epn.edu.ec/oferta-de-posgrado/"

        client = HttpClient(use_cache=True, institucion_id="EPN")
        scraper = CarrerasScraper(http_client=client, institucion_id="EPN", institucion=inst_epn)
        records = scraper.extract()

        # Debe extraer exactamente 46 programas
        assert len(records) == 46, f"Se esperaban 46 programas en línea base, pero se obtuvieron {len(records)}"
        
        # Conteo por nivel
        grados = [r for r in records if r.get("nivel") in ("Grado", "Tecnologia")]
        posgrados = [r for r in records if r.get("nivel") in ("Maestria", "Doctorado")]
        assert len(grados) == 18, f"Se esperaban 18 programas de grado/tecnología, se obtuvieron {len(grados)}"
        assert len(posgrados) == 28, f"Se esperaban 28 programas de posgrado, se obtuvieron {len(posgrados)}"
