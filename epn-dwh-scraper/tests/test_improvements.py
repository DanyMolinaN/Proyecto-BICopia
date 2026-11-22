"""
Pruebas de las correcciones de calidad: sin datos inventados, fallo ante extraccion
insuficiente, cache con vencimiento, politica de robots.txt y SCD Tipo 2.
"""

import csv
import hashlib
import json
import os
import time
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.load.to_database import DatabaseLoader
from src.load.to_staging import StagingLoader
from src.scrapers.autoridades_scraper import _detectar_condicion
from src.scrapers.base_scraper import BaseScraper, ExtractionError
from src.scrapers.carreras_scraper import CarrerasScraper
from src.scrapers.facultades_scraper import FacultadesScraper
from src.scrapers.noticias_scraper import NoticiasScraper, _safe_date
from src.transform.cleaning import DataCleaner
from src.transform.scd2 import apply_scd2
from src.transform.validation import DataValidator
from src.utils.helpers import extract_modality, generate_surrogate_key
from src.utils.http_client import HttpClient


@pytest.fixture
def mock_http():
    client = MagicMock(spec=HttpClient)
    client.is_allowed.return_value = True
    return client


class TestSinDatosInventados:
    def test_facultades_sin_urls_no_usa_lista_canonica(self, mock_http):
        mock_http.get.return_value = None
        assert FacultadesScraper(mock_http).extract() == []

    def test_programa_sin_respuesta_se_omite(self, mock_http):
        mock_http.get.return_value = None
        assert CarrerasScraper(mock_http)._parse_program_page("https://x/y/", "Grado") == {}

    def test_ficha_sin_metricas_deja_null(self, mock_http):
        mock_http.get.return_value = "<html><body><h1>Ingenieria en Software</h1></body></html>"
        rec = CarrerasScraper(mock_http)._parse_program_page("https://x/ing/", "Grado")
        assert rec["duracion_periodos"] is None
        assert rec["creditos"] is None
        assert rec["perfil_ingreso"] is None
        assert rec["codigo_resolucion"] is None

    def test_modalidad_desconocida_es_none(self):
        assert extract_modality("texto sin dato") is None
        assert extract_modality("Semipresencial") == "Semipresencial"

    def test_limpieza_no_rellena_metricas_ni_correo(self):
        cleaner = DataCleaner()
        df_fac = cleaner.clean_facultades([{"nombre": "Facultad de Ciencias", "sigla": "FC", "contacto_correo": ""}])
        assert pd.isna(df_fac.iloc[0]["contacto_correo"])

        carreras = [{"nombre": "Carrera X", "facultad_nombre": "Desconocida", "nivel": "Grado",
                     "modalidad": None, "url": "https://x/"}]
        _, _, _, fact = cleaner.clean_carreras(carreras, df_fac)
        row = fact.iloc[0]
        assert pd.isna(row["duracion_periodos"]) and pd.isna(row["creditos_totales"])
        assert pd.isna(row["facultad_key"])  # no se asigna a la primera facultad
        assert pd.isna(row["es_acreditada"])


class TestMinimoDeRegistros:
    def test_run_falla_si_extrae_menos_del_minimo(self, mock_http, monkeypatch):
        class Vacio(BaseScraper):
            def extract(self):
                return [{"a": 1}]

        monkeypatch.setattr("src.scrapers.base_scraper.settings.min_records", {"vacio": 5})
        with pytest.raises(ExtractionError):
            Vacio(mock_http).run()


class TestCacheYRobots:
    def test_cache_vencida_no_es_fresca(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.utils.http_client.settings.cache_ttl_hours", 1)
        client = HttpClient.__new__(HttpClient)
        f = tmp_path / "c.html"
        f.write_text("x")
        assert client._cache_is_fresh(f)
        old = time.time() - 3 * 3600
        os.utime(f, (old, old))
        assert not client._cache_is_fresh(f)

    def test_robots_inalcanzable_bloquea_rastreo(self, monkeypatch):
        def boom(*a, **k):
            raise ConnectionError("sin red")

        monkeypatch.setattr("requests.Session.get", boom)
        assert HttpClient().is_allowed("https://www.epn.edu.ec/facultades/") is False


def _dim(nombre, bio="bio", correo=None, key=None):
    return {"autoridad_key": key or generate_surrogate_key("autoridad", nombre), "nombre_completo": nombre,
            "titulo_academico": "Dr.", "correo_contacto": correo, "biografia": bio, "es_vigente": 1,
            "fecha_inicio_vigencia": "2026-01-01", "fecha_fin_vigencia": "9999-12-31"}


def _fact(dim_row, cargo="Decano"):
    ck = generate_surrogate_key("cargo", cargo)
    return {"designacion_key": generate_surrogate_key("designacion", dim_row["autoridad_key"], ck),
            "autoridad_key": dim_row["autoridad_key"], "cargo_key": ck, "facultad_key": None,
            "es_titular": 1, "tiempo_designacion_key": 20260101}


class TestScd2:
    today = datetime(2026, 10, 27)

    def test_sin_cambios_es_idempotente(self):
        d = _dim("Dr. Ana Perez")
        dim1, fact1 = apply_scd2(pd.DataFrame([d]), pd.DataFrame([_fact(d)]), None, None, self.today)
        dim2, fact2 = apply_scd2(pd.DataFrame([d]), pd.DataFrame([_fact(d)]), dim1, fact1, self.today)
        assert len(dim2) == 1 and len(fact2) == 1
        assert dim2.iloc[0]["es_vigente"] == 1

    def test_cambio_de_atributos_crea_nueva_version(self):
        d = _dim("Dr. Ana Perez", bio="v1")
        dim1, fact1 = apply_scd2(pd.DataFrame([d]), pd.DataFrame([_fact(d)]), None, None, self.today)
        d2 = _dim("Dr. Ana Perez", bio="v2")
        dim2, fact2 = apply_scd2(pd.DataFrame([d2]), pd.DataFrame([_fact(d2)]), dim1, fact1, self.today)
        assert len(dim2) == 2
        vigentes = dim2[dim2["es_vigente"] == 1]
        historicas = dim2[dim2["es_vigente"] == 0]
        assert len(vigentes) == 1 and len(historicas) == 1
        assert historicas.iloc[0]["fecha_fin_vigencia"] == "2026-10-27"
        assert vigentes.iloc[0]["biografia"] == "v2"
        assert vigentes.iloc[0]["autoridad_key"] != historicas.iloc[0]["autoridad_key"]
        assert len(fact2) == 2  # se conserva el hecho historico
        assert set(fact2["autoridad_key"]) == set(dim2["autoridad_key"])

    def test_autoridad_ausente_se_cierra(self):
        a, b = _dim("Dr. Ana Perez"), _dim("Dr. Luis Mora")
        dim1, fact1 = apply_scd2(pd.DataFrame([a, b]), pd.DataFrame([_fact(a), _fact(b)]), None, None, self.today)
        dim2, _ = apply_scd2(pd.DataFrame([a]), pd.DataFrame([_fact(a)]), dim1, fact1, self.today)
        luis = dim2[dim2["nombre_completo"] == "Dr. Luis Mora"].iloc[0]
        assert luis["es_vigente"] == 0 and luis["fecha_fin_vigencia"] == "2026-10-27"

    def test_round_trip_con_base_de_datos(self, tmp_path):
        loader = DatabaseLoader(f"sqlite:///{tmp_path/'t.db'}")
        d = _dim("Dr. Ana Perez", bio="v1")
        dim1, fact1 = apply_scd2(pd.DataFrame([d]), pd.DataFrame([_fact(d)]), None, None, self.today)
        loader.load_all({"dim_autoridad": dim1, "fact_designacion_autoridades": fact1})
        d2 = _dim("Dr. Ana Perez", bio="v2")
        dim2, fact2 = apply_scd2(pd.DataFrame([d2]), pd.DataFrame([_fact(d2)]),
                                 loader.read_table("dim_autoridad"), loader.read_table("fact_designacion_autoridades"), self.today)
        loader.load_all({"dim_autoridad": dim2, "fact_designacion_autoridades": fact2})
        assert loader.get_table_counts()["dim_autoridad"] == 2


class TestValidadorIntegridad:
    def test_fk_nula_se_reporta_como_huerfana(self):
        dim = pd.DataFrame([{"facultad_key": 1}])
        fact = pd.DataFrame([{"oferta_key": 1, "facultad_key": 1}, {"oferta_key": 2, "facultad_key": None}])
        res = DataValidator().profile_dataframe(fact, "f", "oferta_key", ["oferta_key"],
                                                foreign_keys={"facultad_key": (dim, "facultad_key")})
        assert res["estado_calidad"] == "OBSERVACIONES DETECTADAS"
        assert any("sin registro" in o for o in res["observaciones"])

    def test_nulos_aparecen_como_informacion(self):
        df = pd.DataFrame([{"k": 1, "x": None}, {"k": 2, "x": "a"}])
        res = DataValidator().profile_dataframe(df, "t", "k", ["k"])
        assert any(o.startswith("Info: x") for o in res["observaciones"])


class TestEmparejamientoFacultad:
    def test_nombre_facultad_nulo_no_interrumpe_limpieza_de_carreras(self):
        cleaner = DataCleaner()
        df_fac = cleaner.clean_facultades([
            {"nombre": "Facultad de Ciencias", "sigla": "FC"},
        ])
        carreras = [
            {"nombre": "Carrera con facultad", "facultad_nombre": "Facultad de Ciencias", "nivel": "Grado"},
            {"nombre": "Carrera sin facultad", "facultad_nombre": None, "nivel": "Grado"},
        ]

        _, _, _, fact = cleaner.clean_carreras(carreras, df_fac)

        assert fact.iloc[0]["facultad_key"] == df_fac.iloc[0]["facultad_key"]
        assert pd.isna(fact.iloc[1]["facultad_key"])

    def test_ignora_tildes_y_variaciones_de_nombre(self):
        df_fac = DataCleaner().clean_facultades([
            {"nombre": "Facultad de Ingeniería Geología y Petróleos", "sigla": "FIGP"},
            {"nombre": "Escuelas de Formación de Tecnólogos", "sigla": "ESFOT"},
            {"nombre": "Facultad de Ciencias", "sigla": "FC"},
        ])
        carreras = [
            {"nombre": "A", "facultad_nombre": "Facultad de Geologia y Petroleos", "nivel": "Grado", "url": "u1"},
            {"nombre": "B", "facultad_nombre": "Escuela de Formacion de Tecnologos", "nivel": "Grado", "url": "u2"},
            {"nombre": "C", "facultad_nombre": "Facultad Inexistente de Magia", "nivel": "Grado", "url": "u3"},
        ]
        _, _, _, fact = DataCleaner().clean_carreras(carreras, df_fac)
        keys = dict(zip(["A", "B", "C"], fact["facultad_key"]))
        assert not pd.isna(keys["A"]) and not pd.isna(keys["B"])
        assert pd.isna(keys["C"])


class TestTextoPegado:
    def test_decano_y_subdecano_no_se_concatenan(self, mock_http):
        mock_http.get.return_value = (
            "<html><body><h1>Facultad de Ingenieria Civil</h1>"
            "<div><p>Decano: Dr. Jorge Toapaxi</p><p>Subdecano: Dr. Khaled Hamad</p>"
            "<span>decano.civil@epn.edu.ec</span><span>subdecano</span></div></body></html>"
        )
        data = FacultadesScraper(mock_http)._parse_faculty_page("https://www.epn.edu.ec/facultad-civil/")
        assert data["decano"] == "Dr. Jorge Toapaxi"
        assert data["subdecano"] == "Dr. Khaled Hamad"
        assert data["contacto_correo"] == "decano.civil@epn.edu.ec"


class TestPrecisionDeClaves:
    def test_claves_grandes_no_pierden_precision_con_nulos(self):
        cleaner = DataCleaner()
        df_fac = cleaner.clean_facultades([{"nombre": "Facultad de Ciencias", "sigla": "FC"}])
        carreras = [
            {"nombre": "A", "facultad_nombre": "Facultad de Ciencias", "nivel": "Grado", "url": "u1"},
            {"nombre": "B", "facultad_nombre": "Otra", "nivel": "Grado", "url": "u2"},
        ]
        _, _, _, fact = cleaner.clean_carreras(carreras, df_fac)
        assert fact.iloc[0]["facultad_key"] == df_fac.iloc[0]["facultad_key"]
        res = DataValidator().profile_dataframe(
            fact, "f", "oferta_key", ["oferta_key"], foreign_keys={"facultad_key": (df_fac, "facultad_key")})
        assert sum("sin registro" in o for o in res["observaciones"]) == 1
        assert "1 registros con facultad_key" in " ".join(res["observaciones"])


class TestFichaDeCarreraReal:
    """HTML con la estructura real del portal: etiqueta y valor en elementos consecutivos, sin dos puntos."""

    HTML_GRADO = """
    <html><body><h1>Ingeniería en Mecánica</h1>
    <nav><p>Facultad de Ingeniería Civil y Ambiental</p></nav>
    <p>Resolución de aprobación CES:</p><p>RPC-SO-24-No.476-2017</p>
    <h3>INFORMACIÓN DE POSTULACIÓN</h3>
    <h4>Unidad Académica</h4><p>Facultad de Ingeniería Mecánica</p>
    <h4>Título que otorga</h4><p>Ingeniera/o en Mecánica</p>
    <h4>Duración</h4><p>Nueve períodos académicos</p>
    <h4>Modalidad</h4><p>Presencial</p>
    </body></html>
    """

    def test_extrae_campos_publicados(self, mock_http):
        mock_http.get.return_value = self.HTML_GRADO
        rec = CarrerasScraper(mock_http)._parse_program_page("https://x/ingenieria-en-mecanica/", "Grado")
        assert rec["facultad_nombre"] == "Facultad de Ingeniería Mecánica"  # no la del menú
        assert rec["duracion_periodos"] == 9
        assert rec["duracion_anios"] == 4.5
        assert rec["modalidad"] == "Presencial"
        assert rec["titulo_otorga"] == "Ingeniera/o en Mecánica"
        assert rec["codigo_resolucion"] == "RPC-SO-24-No.476-2017"
        assert rec["creditos"] is None  # el portal no publica creditos totales
        assert not rec["campos_inferidos"]

    def test_numero_en_palabras_y_con_digitos(self):
        from src.utils.helpers import extract_duration_periods
        assert extract_duration_periods("Nueve períodos académicos") == 9
        assert extract_duration_periods("Nueve (9) períodos académicos") == 9
        assert extract_duration_periods("Cinco períodos") == 5

    def test_maestria_sin_ficha_infiere_facultad_y_lo_marca(self, mock_http):
        mock_http.get.return_value = "<html><body><h1>Maestría en Computación</h1><p>Perfil de ingreso</p></body></html>"
        rec = CarrerasScraper(mock_http)._parse_program_page("https://x/maestria-en-computacion/", "Maestria")
        assert rec["facultad_nombre"] == "Facultad de Ingenieria de Sistemas"
        assert rec["campos_inferidos"] == "facultad"
        assert rec["duracion_periodos"] is None


class TestPerfilesSinMenu:
    HTML = """
    <html><body><h1>Ingeniería en Software</h1>
    <ul><li>INTRANET</li><li>OFERTA ACADÉMICA</li><li>Nuestros Principios</li></ul>
    <p>Resolución de aprobación CES:</p><p>RPC-SO-33-No.639-2016</p>
    <ul><li>PERFIL DE INGRESO</li><li>OBJETIVOS</li><li>PERFIL DE EGRESO</li><li>MALLA</li><li>CONTACTO</li></ul>
    <p>Los aspirantes deben haber concluido el bachillerato y obtener el puntaje mínimo.</p>
    <p>Conocimientos: computación, matemática e inglés.</p>
    <h3>Objetivos de la Carrera</h3><p>Formar profesionales.</p>
    <h3>Resultados Generales</h3><p>RG1.</p><p>Identificar necesidades de los sectores estratégicos.</p>
    <p>RG2.</p><p>Demostrar hábitos de trabajo efectivos.</p>
    <h3>Resultados Específicos</h3><p>RE1.</p><p>Aplicar teorías.</p>
    </body></html>
    """

    def test_grado_toma_solo_el_contenido(self, mock_http):
        mock_http.get.return_value = self.HTML
        rec = CarrerasScraper(mock_http)._parse_program_page("https://x/ingenieria-en-software/", "Grado")
        assert rec["perfil_ingreso"].startswith("Los aspirantes deben haber concluido")
        assert "Conocimientos: computación" in rec["perfil_ingreso"]
        assert "Formar profesionales" not in rec["perfil_ingreso"]
        assert "INTRANET" not in rec["perfil_ingreso"] and "Resolución" not in rec["perfil_ingreso"]
        assert rec["perfil_egreso"] == "Identificar necesidades de los sectores estratégicos. Demostrar hábitos de trabajo efectivos."
        assert rec["campo_ocupacional"] is None

    def test_sin_pestanas_no_se_inventa_nada(self, mock_http):
        mock_http.get.return_value = "<html><body><h1>Maestría X</h1><p>Perfil de ingreso del menú y mucho texto aquí.</p></body></html>"
        rec = CarrerasScraper(mock_http)._parse_program_page("https://x/maestria-x/", "Maestria")
        assert rec["perfil_ingreso"] is None and rec["perfil_egreso"] is None


class TestBanderasDeCache:
    def test_force_refresh_ignora_cache_vigente(self, tmp_path, monkeypatch):
        monkeypatch.setattr("requests.Session.get", lambda *a, **k: type("R", (), {"status_code": 404, "text": ""})())
        monkeypatch.setattr("src.utils.http_client.settings.data_raw_dir", tmp_path)
        client = HttpClient(force_refresh=True)
        client.raw_dir = tmp_path
        url = "https://www.epn.edu.ec/x/"
        client._get_cache_path(url).write_text("cacheado")
        monkeypatch.setattr("requests.Session.get", lambda *a, **k: type("R", (), {"status_code": 200, "text": "nuevo"})())
        assert client.get(url) == "nuevo"
        assert HttpClient(force_refresh=False).__class__ is HttpClient  # sin bandera usaria la cache

    def test_no_cache_se_propaga(self, monkeypatch):
        monkeypatch.setattr("requests.Session.get", lambda *a, **k: type("R", (), {"status_code": 404, "text": ""})())
        assert HttpClient(use_cache=False).use_cache is False


class TestInstitucionalYNoticiasSinRespaldo:
    def test_noticias_sin_fuentes_devuelve_vacio(self, mock_http):
        from src.scrapers.noticias_scraper import NoticiasScraper
        mock_http.get.return_value = None
        mock_http.get_json.return_value = None
        assert NoticiasScraper(mock_http).extract() == []

    def test_institucional_sin_paginas_devuelve_vacio(self, mock_http):
        from src.scrapers.institucional_scraper import InstitucionalScraper
        mock_http.get.return_value = None
        assert InstitucionalScraper(mock_http).extract() == []

    def test_historia_lee_anio_real_y_no_usa_1869_por_defecto(self, mock_http):
        from src.scrapers.institucional_scraper import InstitucionalScraper
        mock_http.get.return_value = (
            "<html><body><h1>HISTORIA</h1><p>1935</p><p>28 de febrero</p><p>REAPERTURA</p>"
            "<p>El presidente decreta la reapertura de la institucion.</p>"
            "<p>1964</p><p>EPN CAMPUS GIRON</p><p>Se traslada al actual Campus Politecnico.</p>"
            "<p>Dirección: Av. Ladrón de Guevara</p></body></html>"
        )
        hitos = InstitucionalScraper(mock_http)._extract_historia()
        assert [h["anio"] for h in hitos] == [1935, 1964]
        assert hitos[0]["titulo"] == "REAPERTURA"

    def test_mision_y_vision_salen_del_encabezado_no_del_menu(self, mock_http):
        from src.scrapers.institucional_scraper import InstitucionalScraper
        mock_http.get.return_value = (
            "<html><body><nav><p>INICIO LA POLI Nuestros Principios Misión, Visión, Valores</p></nav>"
            "<h2>MISIÓN</h2><p>Somos una institución pública de educación superior.</p>"
            "<h2>VISIÓN</h2><p>Ser una universidad de excelencia.</p></body></html>"
        )
        n = InstitucionalScraper(mock_http)._extract_nosotros()
        assert n["mision"] == "Somos una institución pública de educación superior."
        assert n["vision"] == "Ser una universidad de excelencia."
        assert n["valores"] is None and n["principios"] is None


# ==============================================================================
# Fase I2: Nuevas pruebas (Paginación, Tildes, Fechas, Staging, Manifiesto)
# ==============================================================================
class TestPaginacionYFechas:
    """C1: Paginación completa y filtro de fechas en URL de la API de noticias."""

    def _make_response(self, status_code, headers, json_data):
        """Crea un objeto-respuesta simulado."""
        resp = SimpleNamespace()
        resp.status_code = status_code
        resp.headers = headers
        resp.json = lambda: json_data
        return resp

    def _make_scraper(self, monkeypatch, tmp_path, max_paginas=50):
        """Devuelve un NoticiasScraper con el directorio raw apuntando a tmp_path."""
        monkeypatch.setattr("src.config.settings.data_raw_dir", tmp_path)
        monkeypatch.setattr("src.config.settings.data_interim_dir", tmp_path)
        mock_http = MagicMock()
        mock_http.is_allowed.return_value = True
        mock_http.session = MagicMock()
        scraper = NoticiasScraper(
            http_client=mock_http,
            institucion_id="EPN",
            anio_inicio=2024,
            anio_fin=2025,
            max_paginas=max_paginas,
        )
        return scraper, mock_http

    def test_paginacion_respeta_max_paginas(self, monkeypatch, tmp_path):
        """Si X-WP-TotalPages=5 pero max_paginas=2, solo debe haber 2 requests."""
        scraper, mock_http = self._make_scraper(monkeypatch, tmp_path, max_paginas=2)

        call_count = 0

        def fake_get(url):
            nonlocal call_count
            call_count += 1
            return json.dumps([{
                "id": call_count * 100 + i,
                "date": "2024-05-01T10:00:00",
                "modified": "2024-05-01T10:00:00",
                "title": {"rendered": f"Noticia {call_count}-{i}"},
                "excerpt": {"rendered": ""},
                "link": f"https://epn.edu.ec/n{i}",
                "categories": [],
            } for i in range(100)])

        mock_http.get.side_effect = fake_get
        monkeypatch.setattr("src.config.settings.base_url", "https://www.epn.edu.ec")
        monkeypatch.setattr("src.config.settings.endpoints", {
            "noticias_api": "https://www.epn.edu.ec/wp-json/wp/v2/posts",
        })
        monkeypatch.setattr("src.config.settings.timeout_seconds", 10)
        monkeypatch.setattr("src.config.settings.verify_ssl", True)

        with patch("src.instituciones.registry") as mock_reg:
            mock_reg.get.return_value = None
            mock_http.get_json.return_value = {}
            scraper._wp_categories = {}
            scraper._extract_via_api()

        assert call_count == 2, (
            f"Se esperaban 2 requests (max_paginas=2) pero se hicieron {call_count}"
        )

    def test_filtro_fechas_en_url(self, monkeypatch, tmp_path):
        """La URL construida debe contener after=2024-01-01 y before=2025-12-31."""
        scraper, mock_http = self._make_scraper(monkeypatch, tmp_path)
        captured_urls = []

        def fake_get(url):
            captured_urls.append(url)
            return None

        mock_http.get.side_effect = fake_get
        monkeypatch.setattr("src.config.settings.base_url", "https://www.epn.edu.ec")
        monkeypatch.setattr("src.config.settings.endpoints", {
            "noticias_api": "https://www.epn.edu.ec/wp-json/wp/v2/posts",
        })
        monkeypatch.setattr("src.config.settings.timeout_seconds", 10)
        monkeypatch.setattr("src.config.settings.verify_ssl", True)

        with patch("src.instituciones.registry") as mock_reg:
            mock_reg.get.return_value = None
            scraper._extract_via_api()

        assert captured_urls, "No se realizó ningún request"
        url = captured_urls[0]
        assert "after=2024-01-01" in url, f"after= no encontrado en URL: {url}"
        assert "before=2025-12-31" in url, f"before= no encontrado en URL: {url}"

    def test_pagina_400_detiene_paginacion(self, monkeypatch, tmp_path):
        """Si la página 2 devuelve 400, la paginación debe detenerse."""
        scraper, mock_http = self._make_scraper(monkeypatch, tmp_path, max_paginas=10)

        call_count = 0

        def fake_get(url):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return json.dumps([{
                    "id": i,
                    "date": "2024-06-01T10:00:00",
                    "modified": "2024-06-01T10:00:00",
                    "title": {"rendered": f"Noticia {i}"},
                    "excerpt": {"rendered": ""},
                    "link": f"https://epn.edu.ec/n{i}",
                    "categories": [],
                } for i in range(100)])
            return None

        mock_http.get.side_effect = fake_get
        monkeypatch.setattr("src.config.settings.base_url", "https://www.epn.edu.ec")
        monkeypatch.setattr("src.config.settings.endpoints", {
            "noticias_api": "https://www.epn.edu.ec/wp-json/wp/v2/posts",
        })
        monkeypatch.setattr("src.config.settings.timeout_seconds", 10)
        monkeypatch.setattr("src.config.settings.verify_ssl", True)

        with patch("src.instituciones.registry") as mock_reg:
            mock_reg.get.return_value = None
            scraper._wp_categories = {}
            result = scraper._extract_via_api()

        assert call_count == 2
        assert len(result) == 100


class TestTildesYFechasFabricadas:
    """C5: _safe_date no inventa fechas y parsea formatos reales."""

    def test_safe_date_ninguna_fecha_fabricada(self):
        """Texto sin fecha reconocible -> None, nunca una fecha inventada."""
        result = _safe_date("texto-sin-fecha")
        assert result is None, (
            f"_safe_date no debe fabricar fechas; devolvió '{result}'"
        )

    def test_safe_date_parsea_iso(self):
        """Formato ISO 8601 -> YYYY-MM-DD."""
        assert _safe_date("2024-03-15T10:00:00") == "2024-03-15"

    def test_safe_date_parsea_espanol(self):
        """'15 de marzo de 2024' -> '2024-03-15'."""
        assert _safe_date("15 de marzo de 2024") == "2024-03-15"


class TestCondicionDesignacion:
    """D1: _detectar_condicion identifica encargado/subrogante/no_determinado correctamente."""

    def test_sin_evidencia_es_no_determinado(self):
        """Texto 'Rector' sin indicadores -> condicion='no_determinado', es_titular=None."""
        condicion, evidencia = _detectar_condicion("Rector")
        assert condicion == "no_determinado"
        assert evidencia == ""

        from src.scrapers.autoridades_scraper import AutoridadesScraper
        scraper = AutoridadesScraper(http_client=MagicMock(), institucion_id="EPN")
        rec = scraper._build_record(
            name="Dr. Juan Pez",
            cargo="Rector",
            unidad="Rectorado",
            url="https://epn.edu.ec/autoridades/",
        )
        assert rec["condicion_designacion"] == "no_determinado"
        assert rec["es_titular"] is None

    def test_encargado_detectado(self):
        """'Rector (e)' -> condicion='encargado', es_titular=0."""
        condicion, evidencia = _detectar_condicion("Rector (e)")
        assert condicion == "encargado"
        assert "encargo" in evidencia.lower() or "(e)" in evidencia

        from src.scrapers.autoridades_scraper import AutoridadesScraper
        scraper = AutoridadesScraper(http_client=MagicMock(), institucion_id="EPN")
        rec = scraper._build_record(
            name="Ing. Carlos Lopez",
            cargo="Rector (e)",
            unidad="Rectorado",
            url="https://epn.edu.ec/autoridades/",
        )
        assert rec["condicion_designacion"] == "encargado"
        assert rec["es_titular"] == 0

    def test_subrogante_detectado(self):
        """'Vicerrectora subrogante' -> condicion='subrogante', es_titular=0."""
        condicion, evidencia = _detectar_condicion("Vicerrectora subrogante")
        assert condicion == "subrogante"

        from src.scrapers.autoridades_scraper import AutoridadesScraper
        scraper = AutoridadesScraper(http_client=MagicMock(), institucion_id="EPN")
        rec = scraper._build_record(
            name="Dra. Maria Ruiz",
            cargo="Vicerrectora subrogante",
            unidad="Rectorado",
            url="https://epn.edu.ec/autoridades/",
        )
        assert rec["condicion_designacion"] == "subrogante"
        assert rec["es_titular"] == 0


class TestStagingLoaderIdempotencia:
    """F3: StagingLoader no duplica registros cuando se cargan los mismos datos dos veces."""

    def _make_records(self):
        """Genera 3 registros con hash_registro determinista."""
        records = []
        for i in range(1, 4):
            payload = {"nombre": f"Carrera {i}", "nivel": "Grado", "institucion_id": "EPN",
                       "run_id": "test-run-001", "fuente_url": "https://epn.edu.ec/oferta/",
                       "fecha_extraccion": "2024-01-01T00:00:00Z"}
            payload["hash_registro"] = hashlib.sha256(
                json.dumps({"nombre": f"Carrera {i}", "nivel": "Grado"}, sort_keys=True).encode()
            ).hexdigest()[:20]
            records.append(payload)
        return records

    def test_carga_mismos_registros_twice_no_duplica(self):
        """Carga 3 records, recarga los mismos: primera vez insertados=3, segunda=0."""
        loader = StagingLoader(connection_url="sqlite:///:memory:")
        loader.init_schema()

        records = self._make_records()

        result1 = loader.load_raw_table(records, "stg_oferta")
        assert result1["insertados"] == 3, (
            f"Primera carga debe insertar 3, insertó {result1['insertados']}"
        )

        result2 = loader.load_raw_table(records, "stg_oferta")
        assert result2["insertados"] == 0, (
            f"Segunda carga no debe insertar duplicados, insertó {result2['insertados']}"
        )
        assert result2["duplicados_omitidos"] == 3


class TestManifiesto:
    """G1: HttpClient registra las descargas en manifest.csv con encabezados correctos."""

    def test_manifiesto_se_crea_en_raw_dir(self, monkeypatch, tmp_path):
        """Tras una descarga exitosa debe existir manifest.csv con columnas correctas."""
        from src.utils.http_client import HttpClient

        monkeypatch.setattr("src.config.settings.data_raw_dir", tmp_path)
        monkeypatch.setattr("src.config.settings.use_cache", True)
        monkeypatch.setattr("src.config.settings.cache_ttl_hours", 24)
        monkeypatch.setattr("src.config.settings.rate_limit_seconds", 0)
        monkeypatch.setattr("src.config.settings.max_retries", 1)
        monkeypatch.setattr("src.config.settings.backoff_factor", 0)
        monkeypatch.setattr("src.config.settings.timeout_seconds", 10)
        monkeypatch.setattr("src.config.settings.verify_ssl", False)
        monkeypatch.setattr("src.config.settings.user_agent", "test-agent")

        fake_resp = SimpleNamespace(status_code=404, text="")
        monkeypatch.setattr("requests.Session.get", lambda self, *a, **k: fake_resp)

        client = HttpClient.__new__(HttpClient)
        client.force_refresh = False
        client.institucion_id = "EPN"
        client.run_id = "test-manifest-001"
        client.session = MagicMock()
        client.rate_limit_seconds = 0
        client.last_request_time = 0.0
        client.raw_dir = tmp_path
        client.use_cache = True
        client.today_str = "2024-01-15"
        client.stats = {
            "urls_consultadas": 0, "bloqueadas_robots": 0, "con_error": 0,
            "exitosas": 0, "detalles": [],
        }
        client._robot_parser = None
        client._robots_unreachable = False

        client._record_manifest("https://epn.edu.ec/test/", 200, "<html>contenido</html>")

        manifest_path = tmp_path / "2024-01-15" / "manifest.csv"
        assert manifest_path.exists(), "manifest.csv no fue creado"

        with open(manifest_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)

        expected_headers = ["url", "estado_http", "fecha_descarga", "sha256", "institucion_id", "run_id"]
        assert headers == expected_headers, (
            f"Encabezados incorrectos: {headers} (esperado: {expected_headers})"
        )
