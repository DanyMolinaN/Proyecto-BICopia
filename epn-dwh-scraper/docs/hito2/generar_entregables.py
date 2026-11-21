"""
generar_entregables.py
======================
Script reproducible para generar los entregables del Hito 2 (Fases H1, H2, H3).

Genera:
  - docs/hito2/inventario_fuentes.xlsx   (H1)
  - docs/hito2/diccionario_datos.xlsx    (H2)
  - docs/hito2/matriz_cobertura.xlsx     (H3)

Uso:
    .venv\Scripts\python.exe docs/hito2/generar_entregables.py
"""

from pathlib import Path
import sys
import os

# ---------------------------------------------------------------------------
# Asegurar que el raíz del proyecto esté en el path para importar src/
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent.parent  # epn-dwh-scraper/
sys.path.insert(0, str(ROOT))

from src.utils.simple_xlsx import create_xlsx  # noqa: E402

OUT_DIR = ROOT / "docs" / "hito2"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FECHA_GENERACION = "2026-11-21"


# ===========================================================================
# H1 — Inventario de fuentes
# ===========================================================================

def generar_inventario_fuentes() -> Path:
    """Genera docs/hito2/inventario_fuentes.xlsx con los metadatos de cada fuente."""

    filas = [
        {
            "Tabla": "stg_publicaciones",
            "Nombre_Fuente": "EPN — Portal WordPress (Noticias API)",
            "Dueno": "Escuela Politécnica Nacional",
            "Formato": "JSON (REST API wp-json/wp/v2/posts)",
            "Periodicidad": "Continua (publicaciones diarias)",
            "Anios_Disponibles": "2024–2026",
            "Licencia": "Acceso público — sin licencia Creative Commons explícita",
            "Enlace_Oficial": "https://www.epn.edu.ec/wp-json/wp/v2/posts",
            "Fecha_Descarga": FECHA_GENERACION,
            "Estado_Acceso": "activo",
            "Notas": "Paginación con X-WP-TotalPages; filtros after/before por fecha. Adaptador wordpress.",
        },
        {
            "Tabla": "stg_oferta",
            "Nombre_Fuente": "EPN — Portal Oferta Académica (Grado y Posgrado)",
            "Dueno": "Escuela Politécnica Nacional",
            "Formato": "HTML (scraping web)",
            "Periodicidad": "Anual (ciclo académico)",
            "Anios_Disponibles": "2026",
            "Licencia": "Acceso público — información institucional",
            "Enlace_Oficial": "https://www.epn.edu.ec/oferta-de-grado/ ; https://www.epn.edu.ec/oferta-de-posgrado/",
            "Fecha_Descarga": FECHA_GENERACION,
            "Estado_Acceso": "activo",
            "Notas": "Extracción HTML de páginas de oferta. Incluye carreras de grado y posgrado.",
        },
        {
            "Tabla": "stg_autoridades",
            "Nombre_Fuente": "EPN — Portal Autoridades",
            "Dueno": "Escuela Politécnica Nacional",
            "Formato": "HTML (scraping web)",
            "Periodicidad": "Anual / por cambio de autoridades",
            "Anios_Disponibles": "2026",
            "Licencia": "Acceso público — información institucional",
            "Enlace_Oficial": "https://www.epn.edu.ec/autoridades/",
            "Fecha_Descarga": FECHA_GENERACION,
            "Estado_Acceso": "activo",
            "Notas": "Incluye detección de condición de designación (titular, encargado, subrogante).",
        },
        {
            "Tabla": "stg_publicaciones",
            "Nombre_Fuente": "ESPE — Portal WordPress (Piloto)",
            "Dueno": "Universidad de las Fuerzas Armadas ESPE",
            "Formato": "JSON (REST API wp-json/wp/v2/posts)",
            "Periodicidad": "Continua (publicaciones diarias)",
            "Anios_Disponibles": "2026 (sin histórico público 2024–2025)",
            "Licencia": "Acceso público — sin licencia explícita",
            "Enlace_Oficial": "https://www.espe.edu.ec/wp-json/wp/v2/posts",
            "Fecha_Descarga": FECHA_GENERACION,
            "Estado_Acceso": "consultada (0 registros en rango 2024-2025)",
            "Notas": "Prueba de red HTTP 200. Endpoint accesible pero publicaciones públicas están fechadas en 2026; 0 registros en ventana 2024-2025.",
        },
        {
            "Tabla": "stg_publicaciones",
            "Nombre_Fuente": "USFQ — Portal Web (Piloto)",
            "Dueno": "Universidad San Francisco de Quito",
            "Formato": "HTML / Drupal (no WordPress)",
            "Periodicidad": "Continua",
            "Anios_Disponibles": "No disponible vía WP API",
            "Licencia": "Acceso público — sin licencia explícita",
            "Enlace_Oficial": "https://www.usfq.edu.ec/wp-json/wp/v2/posts",
            "Fecha_Descarga": FECHA_GENERACION,
            "Estado_Acceso": "consultada (error 404)",
            "Notas": "Prueba de red HTTP 404 en endpoint WP REST API. Auditoría de robots.txt revela estructura Drupal (/core/*.css). Requiere adaptador HTML/Drupal.",
        },
        {
            "Tabla": "stg_oferta_sniese",
            "Nombre_Fuente": "SENESCYT/CES — SNIESE Catastro Oferta Académica",
            "Dueno": "SENESCYT / Consejo de Educación Superior (CES)",
            "Formato": "CSV / Excel (catastro nacional datos abiertos)",
            "Periodicidad": "Anual",
            "Anios_Disponibles": "2026",
            "Licencia": "Datos Abiertos — Gobierno del Ecuador",
            "Enlace_Oficial": "https://datosabiertos.gob.ec/dataset/oferta-academica-ies ; https://appcmi.ces.gob.ec/oferta_vigente/",
            "Fecha_Descarga": "Pendiente de descarga manual por el equipo",
            "Estado_Acceso": "no_disponible (sin archivo local descargado)",
            "Notas": "URL datosabiertos.gob.ec responde HTTP 404. Portal CES oferta_vigente dispone de formulario PHP sin exportación directa. Archivo CSV local ausente; 0 registros en staging. Criterio de 2 fuentes: NO CUMPLIDO.",
        },
    ]

    path = OUT_DIR / "inventario_fuentes.xlsx"
    create_xlsx({"Inventario_Fuentes": filas}, path)
    print(f"[H1] Generado: {path}")
    return path


# ===========================================================================
# H2 — Diccionario de datos
# ===========================================================================

def generar_diccionario_datos() -> Path:
    """Genera docs/hito2/diccionario_datos.xlsx con la descripción de cada campo STG."""

    filas = []

    # ---- stg_oferta --------------------------------------------------------
    stg_oferta_campos = [
        ("stg_id",             "BIGSERIAL",  "Clave primaria autoincremental",                              "",        "1",                       ""),
        ("run_id",             "VARCHAR(64)","Identificador único de la ejecución del scraper (UUID)",      "",        "a1b2c3d4-...",            "Obligatorio"),
        ("fecha_carga",        "TIMESTAMP",  "Marca de tiempo en que el registro fue insertado en STG",     "",        "2026-11-21 10:00:00+00",  ""),
        ("institucion_id",     "VARCHAR(32)","Código de la institución de origen (ej. EPN, ESPE)",          "",        "EPN",                     "Obligatorio"),
        ("fuente_url",         "TEXT",       "URL exacta de la página de oferta scrapeada",                 "",        "https://www.epn.edu.ec/oferta-de-grado/", ""),
        ("fecha_extraccion",   "VARCHAR(32)","Fecha en que se realizó la extracción (ISO 8601)",            "",        "2026-11-21",              ""),
        ("hash_registro",      "VARCHAR(64)","SHA-256 del contenido del registro para deduplicación",       "",        "7f83b1657...",            "Obligatorio"),
        ("nombre",             "TEXT",       "Nombre de la carrera o programa académico",                   "",        "Ingeniería en Sistemas",  ""),
        ("facultad_nombre",    "TEXT",       "Nombre de la facultad o unidad académica",                    "",        "Facultad de Ingeniería en Sistemas",  ""),
        ("nivel",              "TEXT",       "Nivel académico general (grado, posgrado)",                   "",        "grado",                   ""),
        ("nivel_detalle",      "TEXT",       "Nivel académico específico (tecnología, licenciatura, etc.)", "",        "Ingeniería",              ""),
        ("nivel_macro",        "TEXT",       "Agrupación macro del nivel (Grado / Posgrado)",               "",        "Grado",                   ""),
        ("modalidad",          "TEXT",       "Modalidad de estudio (presencial, semipresencial, en línea)", "",        "presencial",              "Inferido con extract_modality()"),
        ("financiamiento",     "TEXT",       "Tipo de financiamiento (pública, particular)",                "",        "pública",                 ""),
        ("estado_programa",    "TEXT",       "Estado de vigencia del programa (activo, etc.)",              "",        "activo",                  ""),
        ("evidencia_estado",   "TEXT",       "Texto literal del portal que indica el estado",               "",        "Programa vigente",        ""),
        ("anio_referencia",    "INTEGER",    "Año de referencia de la oferta extraída",                     "año",     "2026",                    "Default 2026"),
        ("duracion_periodos",  "TEXT",       "Duración expresada en periodos académicos",                   "periodos","10",                       ""),
        ("duracion_anios",     "TEXT",       "Duración expresada en años",                                  "años",    "5",                       ""),
        ("creditos",           "TEXT",       "Número de créditos del programa",                             "créditos","240",                      ""),
        ("titulo_otorga",      "TEXT",       "Título o grado académico que otorga el programa",             "",        "Ingeniero en Sistemas",   ""),
        ("codigo_resolucion",  "TEXT",       "Código de resolución CES que aprueba el programa",            "",        "RPC-SO-14-No.173-2019",   ""),
        ("perfil_ingreso",     "TEXT",       "Requisitos o perfil de ingreso al programa",                  "",        "Bachillerato completo",   ""),
        ("perfil_egreso",      "TEXT",       "Competencias y habilidades del graduado",                     "",        "Capaz de diseñar sistemas", ""),
        ("campo_ocupacional",  "TEXT",       "Ámbito laboral del graduado según el portal",                 "",        "Desarrollo de software",  ""),
        ("malla_curricular_url","TEXT",      "URL del documento de malla curricular",                       "",        "https://www.epn.edu.ec/malla.pdf", ""),
        ("url",                "TEXT",       "URL de la página individual de la carrera",                   "",        "https://www.epn.edu.ec/sistemas/", ""),
        ("campos_inferidos",   "TEXT",       "Lista de campos completados por inferencia (JSON array)",     "",        '["modalidad"]',           "Dato sintético: indica qué campos fueron inferidos"),
    ]
    for campo, tipo, desc, unidad, ejemplo, notas in stg_oferta_campos:
        filas.append({
            "Tabla":      "stg_oferta",
            "Campo":      campo,
            "Tipo_SQL":   tipo,
            "Descripcion": desc,
            "Unidad":     unidad,
            "Ejemplo":    ejemplo,
            "Notas":      notas,
        })

    # ---- stg_autoridades ---------------------------------------------------
    stg_autoridades_campos = [
        ("stg_id",               "BIGSERIAL",  "Clave primaria autoincremental",                              "",   "1",                          ""),
        ("run_id",               "VARCHAR(64)","Identificador único de la ejecución del scraper (UUID)",      "",   "a1b2c3d4-...",               "Obligatorio"),
        ("fecha_carga",          "TIMESTAMP",  "Marca de tiempo en que el registro fue insertado en STG",     "",   "2026-11-21 10:00:00+00",     ""),
        ("institucion_id",       "VARCHAR(32)","Código de la institución de origen",                          "",   "EPN",                        "Obligatorio"),
        ("fuente_url",           "TEXT",       "URL exacta de la página de autoridades scrapeada",            "",   "https://www.epn.edu.ec/autoridades/", ""),
        ("fecha_extraccion",     "VARCHAR(32)","Fecha en que se realizó la extracción (ISO 8601)",            "",   "2026-11-21",                 ""),
        ("hash_registro",        "VARCHAR(64)","SHA-256 del contenido del registro para deduplicación",       "",   "7f83b1657...",               "Obligatorio"),
        ("nombre_completo",      "TEXT",       "Nombre completo de la autoridad universitaria",               "",   "Juan Pérez López",           ""),
        ("titulo_academico",     "TEXT",       "Título académico o grado de la autoridad (PhD, MSc, etc.)",   "",   "PhD en Ingeniería",          ""),
        ("cargo",                "TEXT",       "Cargo limpio de la autoridad",                                "",   "Rector",                     ""),
        ("cargo_original",       "TEXT",       "Texto literal del cargo tal como aparece en el portal",       "",   "Rector (e)",                 ""),
        ("cargo_normalizado",    "TEXT",       "Cargo estandarizado sin tildes en minúsculas",                "",   "rector",                     ""),
        ("tipo_cargo",           "TEXT",       "Clasificación del cargo (rectoral, decanal, etc.)",           "",   "rectoral",                   ""),
        ("unidad_adscripcion",   "TEXT",       "Facultad o unidad a la que pertenece la autoridad",           "",   "Rectorado",                  ""),
        ("condicion_designacion","TEXT",       "Condición de la designación: titular, encargado, subrogante o no_determinado", "", "encargado", ""),
        ("evidencia_condicion",  "TEXT",       "Fragmento textual que sustenta la condición de designación",  "",   "(e)",                        ""),
        ("es_titular",           "INTEGER",    "Bandera: 1=titular, 0=encargado/subrogante, NULL=no determinado", "", "0",                       ""),
        ("periodo_gestion",      "TEXT",       "Periodo de gestión de la autoridad",                          "",   "2024–2027",                  ""),
        ("correo_contacto",      "TEXT",       "Correo electrónico institucional de la autoridad",            "",   "rector@epn.edu.ec",          ""),
        ("biografia",            "TEXT",       "Breve biografía institucional de la autoridad",               "",   "Doctor en Ciencias con 20 años...", ""),
        ("fecha_observacion",    "TEXT",       "Fecha en que se observó el estado actual en el portal",       "",   "2026-11-21",                 ""),
    ]
    for campo, tipo, desc, unidad, ejemplo, notas in stg_autoridades_campos:
        filas.append({
            "Tabla":      "stg_autoridades",
            "Campo":      campo,
            "Tipo_SQL":   tipo,
            "Descripcion": desc,
            "Unidad":     unidad,
            "Ejemplo":    ejemplo,
            "Notas":      notas,
        })

    # ---- stg_publicaciones -------------------------------------------------
    stg_publicaciones_campos = [
        ("stg_id",             "BIGSERIAL",  "Clave primaria autoincremental",                              "",   "1",                          ""),
        ("run_id",             "VARCHAR(64)","Identificador único de la ejecución del scraper (UUID)",      "",   "a1b2c3d4-...",               "Obligatorio"),
        ("fecha_carga",        "TIMESTAMP",  "Marca de tiempo de inserción en STG",                         "",   "2026-11-21 10:00:00+00",     ""),
        ("institucion_id",     "VARCHAR(32)","Código de la institución de origen",                          "",   "EPN",                        "Obligatorio"),
        ("fuente_url",         "TEXT",       "URL del endpoint API o web de donde se obtuvo la noticia",    "",   "https://www.epn.edu.ec/wp-json/wp/v2/posts", ""),
        ("fecha_extraccion",   "VARCHAR(32)","Fecha en que se realizó la extracción (ISO 8601)",            "",   "2026-11-21",                 ""),
        ("hash_registro",      "VARCHAR(64)","SHA-256 del contenido del registro para deduplicación",       "",   "7f83b1657...",               "Obligatorio"),
        ("post_id",            "TEXT",       "Identificador de la publicación en la API de WordPress",      "",   "12345",                      ""),
        ("fecha_publicacion",  "TEXT",       "Fecha de publicación original de la noticia (ISO 8601)",      "",   "2024-01-15",                 ""),
        ("fecha_modificacion", "TEXT",       "Fecha de última modificación del post (ISO 8601)",            "",   "2024-01-16",                 ""),
        ("titulo",             "TEXT",       "Título de la publicación (texto plano, sin HTML)",            "",   "EPN presenta nuevo laboratorio", ""),
        ("categoria",          "TEXT",       "Categoría normalizada de la publicación",                     "",   "noticias",                   ""),
        ("categoria_origen",   "TEXT",       "Categoría original tal como aparece en el API",               "",   "Noticias Institucionales",   ""),
        ("tipo_publicacion",   "TEXT",       "Tipo de publicación inferido (noticia, convocatoria, etc.)",  "",   "noticia",                    ""),
        ("tipo_origen",        "TEXT",       "Tipo original proporcionado por el API (post, page, etc.)",   "",   "post",                       ""),
        ("resumen",            "TEXT",       "Extracto o resumen de la publicación (texto plano)",          "",   "La EPN inauguró un laboratorio de IA...", ""),
        ("url",                "TEXT",       "URL permanente (permalink) de la publicación en el portal",   "",   "https://www.epn.edu.ec/laboratorio-ia/", ""),
    ]
    for campo, tipo, desc, unidad, ejemplo, notas in stg_publicaciones_campos:
        filas.append({
            "Tabla":      "stg_publicaciones",
            "Campo":      campo,
            "Tipo_SQL":   tipo,
            "Descripcion": desc,
            "Unidad":     unidad,
            "Ejemplo":    ejemplo,
            "Notas":      notas,
        })

    # ---- stg_oferta_sniese -------------------------------------------------
    stg_sniese_campos = [
        ("stg_id",             "BIGSERIAL",  "Clave primaria autoincremental",                              "",   "1",                          ""),
        ("run_id",             "VARCHAR(64)","Identificador único de la ejecución del scraper (UUID)",      "",   "a1b2c3d4-...",               "Obligatorio"),
        ("fecha_carga",        "TIMESTAMP",  "Marca de tiempo de inserción en STG",                         "",   "2026-11-21 10:00:00+00",     ""),
        ("institucion_id",     "VARCHAR(32)","Código de la institución de origen o 'SNIESE' si es global",  "",   "EPN",                        "Obligatorio"),
        ("fuente_url",         "TEXT",       "URL del dataset de datos abiertos del gobierno",              "",   "https://datosabiertos.gob.ec/dataset/oferta-academica-ies", ""),
        ("fecha_extraccion",   "VARCHAR(32)","Fecha en que se descargó el archivo CSV",                     "",   "2026-11-21",                 ""),
        ("hash_registro",      "VARCHAR(64)","SHA-256 del contenido del registro para deduplicación",       "",   "7f83b1657...",               "Obligatorio"),
        ("institucion_nombre", "TEXT",       "Nombre de la institución tal como aparece en el catastro CES","",   "Escuela Politécnica Nacional",""),
        ("carrera_programa",   "TEXT",       "Nombre de la carrera o programa en el catastro oficial",      "",   "Ingeniería en Sistemas",     ""),
        ("nivel_formacion",    "TEXT",       "Nivel de formación según clasificación CES",                  "",   "Tercer Nivel",               ""),
        ("nivel_detalle",      "TEXT",       "Detalle del nivel (tecnología, licenciatura, ingeniería…)",   "",   "Ingeniería",                 ""),
        ("modalidad",          "TEXT",       "Modalidad de estudio según el catastro CES",                  "",   "Presencial",                 ""),
        ("resolucion_ces",     "TEXT",       "Número de resolución CES que habilita el programa",           "",   "RPC-SO-14-No.173-2019",      ""),
        ("estado_vigencia",    "TEXT",       "Estado de vigencia del programa en el catastro CES",          "",   "Vigente",                    ""),
        ("campo_amplio",       "TEXT",       "Campo amplio de conocimiento según clasificación CINE-UNESCO","",   "Ingeniería, industria y construcción", ""),
        ("fuente_organismo",   "TEXT",       "Organismo responsable de la publicación del catastro",        "",   "CES / SENESCYT",             ""),
        ("anio_referencia",    "INTEGER",    "Año al que corresponde el catastro descargado",               "año","2026",                       "Default 2026"),
    ]
    for campo, tipo, desc, unidad, ejemplo, notas in stg_sniese_campos:
        filas.append({
            "Tabla":      "stg_oferta_sniese",
            "Campo":      campo,
            "Tipo_SQL":   tipo,
            "Descripcion": desc,
            "Unidad":     unidad,
            "Ejemplo":    ejemplo,
            "Notas":      notas,
        })

    path = OUT_DIR / "diccionario_datos.xlsx"
    create_xlsx({"Diccionario_Datos": filas}, path)
    print(f"[H2] Generado: {path}")
    return path


# ===========================================================================
# H3 — Matriz de cobertura
# ===========================================================================

def generar_matriz_cobertura() -> Path:
    """Genera docs/hito2/matriz_cobertura.xlsx con los tres niveles reales: configurada, consultada, con registros."""

    instituciones = [
        {
            "Institucion_ID":               "EPN",
            "Nombre":                       "Escuela Politécnica Nacional",
            "Estado_Integracion":           "habilitada",
            "Configurada":                  "si",
            "Consultada":                   "si",
            "Con_Registros":                "si",
            "P1_Oferta_Registros":          "46 registros",
            "P2_Autoridades_Registros":     "10 registros",
            "P3_Publicaciones_Registros":   "194 registros (2024: 70, 2025: 124)",
            "Notas": "Prototipo base y evolución Hito 2 en producción. Staging poblado: 46 carreras, 10 autoridades, 194 noticias con cobertura demostrada 2024-2025.",
        },
        {
            "Institucion_ID":               "ESPE",
            "Nombre":                       "Universidad de las Fuerzas Armadas ESPE",
            "Estado_Integracion":           "piloto",
            "Configurada":                  "si",
            "Consultada":                   "si (prueba de red ejecutada)",
            "Con_Registros":                "no (0 registros)",
            "P1_Oferta_Registros":          "0 registros (endpoint no configurado)",
            "P2_Autoridades_Registros":     "0 registros (pendiente de extracción)",
            "P3_Publicaciones_Registros":   "0 registros en rango 2024-2025 (API WP responde 200, pero publicaciones públicas en portal están fechadas en 2026)",
            "Notas": "Auditoría de red: robots.txt permite /wp-json/wp/v2/posts (HTTP 200). Sin embargo, el endpoint no expone histórico en ventana 2024-2025.",
        },
        {
            "Institucion_ID":               "USFQ",
            "Nombre":                       "Universidad San Francisco de Quito",
            "Estado_Integracion":           "piloto",
            "Configurada":                  "si",
            "Consultada":                   "si (prueba de red ejecutada)",
            "Con_Registros":                "no (0 registros)",
            "P1_Oferta_Registros":          "0 registros (pendiente)",
            "P2_Autoridades_Registros":     "0 registros (pendiente)",
            "P3_Publicaciones_Registros":   "0 registros (HTTP 404 en endpoint WordPress)",
            "Notas": "Auditoría de red: robots.txt revela CMS Drupal (/core/*.css). Endpoint /wp-json/wp/v2/posts retorna HTTP 404. Requiere adaptador Drupal/HTML.",
        },
        {
            "Institucion_ID":               "UCE",
            "Nombre":                       "Universidad Central del Ecuador",
            "Estado_Integracion":           "pendiente",
            "Configurada":                  "no",
            "Consultada":                   "no",
            "Con_Registros":                "no (0 registros)",
            "P1_Oferta_Registros":          "0 registros",
            "P2_Autoridades_Registros":     "0 registros",
            "P3_Publicaciones_Registros":   "0 registros",
            "Notas": "Alcance nacional pendiente. Endpoints no auditados; pendiente para Hito 3/4.",
        },
        {
            "Institucion_ID":               "UTPL",
            "Nombre":                       "Universidad Técnica Particular de Loja",
            "Estado_Integracion":           "pendiente",
            "Configurada":                  "no",
            "Consultada":                   "no",
            "Con_Registros":                "no (0 registros)",
            "P1_Oferta_Registros":          "0 registros",
            "P2_Autoridades_Registros":     "0 registros",
            "P3_Publicaciones_Registros":   "0 registros",
            "Notas": "Alcance nacional pendiente. Particular cofinanciada.",
        },
        {
            "Institucion_ID":               "PUCE",
            "Nombre":                       "Pontificia Universidad Católica del Ecuador",
            "Estado_Integracion":           "pendiente",
            "Configurada":                  "no",
            "Consultada":                   "no",
            "Con_Registros":                "no (0 registros)",
            "P1_Oferta_Registros":          "0 registros",
            "P2_Autoridades_Registros":     "0 registros",
            "P3_Publicaciones_Registros":   "0 registros",
            "Notas": "Alcance nacional pendiente. Particular cofinanciada.",
        },
        {
            "Institucion_ID":               "UG",
            "Nombre":                       "Universidad de Guayaquil",
            "Estado_Integracion":           "pendiente",
            "Configurada":                  "no",
            "Consultada":                   "no",
            "Con_Registros":                "no (0 registros)",
            "P1_Oferta_Registros":          "0 registros",
            "P2_Autoridades_Registros":     "0 registros",
            "P3_Publicaciones_Registros":   "0 registros",
            "Notas": "Alcance nacional pendiente. Pública.",
        },
        {
            "Institucion_ID":               "ESPOL",
            "Nombre":                       "Escuela Superior Politécnica del Litoral",
            "Estado_Integracion":           "pendiente",
            "Configurada":                  "no",
            "Consultada":                   "no",
            "Con_Registros":                "no (0 registros)",
            "P1_Oferta_Registros":          "0 registros",
            "P2_Autoridades_Registros":     "0 registros",
            "P3_Publicaciones_Registros":   "0 registros",
            "Notas": "Alcance nacional pendiente. Pública.",
        },
        {
            "Institucion_ID":               "ESPOCH",
            "Nombre":                       "Escuela Superior Politécnica de Chimborazo",
            "Estado_Integracion":           "pendiente",
            "Configurada":                  "no",
            "Consultada":                   "no",
            "Con_Registros":                "no (0 registros)",
            "P1_Oferta_Registros":          "0 registros",
            "P2_Autoridades_Registros":     "0 registros",
            "P3_Publicaciones_Registros":   "0 registros",
            "Notas": "Alcance nacional pendiente. Pública.",
        },
        {
            "Institucion_ID":               "UTN",
            "Nombre":                       "Universidad Técnica del Norte",
            "Estado_Integracion":           "pendiente",
            "Configurada":                  "no",
            "Consultada":                   "no",
            "Con_Registros":                "no (0 registros)",
            "P1_Oferta_Registros":          "0 registros",
            "P2_Autoridades_Registros":     "0 registros",
            "P3_Publicaciones_Registros":   "0 registros",
            "Notas": "Alcance nacional pendiente. Pública.",
        },
    ]

    path = OUT_DIR / "matriz_cobertura.xlsx"
    create_xlsx({"Matriz_Cobertura": instituciones}, path)
    print(f"[H3] Generado: {path}")
    return path


# ===========================================================================
# Main
# ===========================================================================

if __name__ == "__main__":
    print(f"Generando entregables Hito 2 en: {OUT_DIR}\n")

    p1 = generar_inventario_fuentes()
    p2 = generar_diccionario_datos()
    p3 = generar_matriz_cobertura()

    print("\n=== RESUMEN ===")
    for p in (p1, p2, p3):
        size = Path(p).stat().st_size
        print(f"  {p.name}  ({size:,} bytes)")
    print("\nListo.")
