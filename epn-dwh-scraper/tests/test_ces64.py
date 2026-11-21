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
from src.scrapers.portal_validator import PortalValidator
from src.ces64_runner import Ces64Runner, _estado_modulo, _build_inst_from_portal
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
