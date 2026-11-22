# Pipeline ETL EPN y Adquisición Multi-IES de Ecuador

## Informacion General
- **Proyecto**: ETL y Data Warehouse dimensional para la línea base institucional de la EPN, con un flujo separado de adquisición cruda multi-IES para Hito 2.
- **Alcance multi-IES**: catálogo de 64 instituciones; contenidos de oferta académica, autoridades y publicaciones obtenidos desde sitios oficiales universitarios.
- **Materia**: Business Intelligence / Ingenieria de Datos.
- **Nivel**: Superior Universitario / Pregrado y Posgrado.

---

## 1. Descripcion del Proyecto
El flujo ETL original automatiza la extracción, limpieza, validación, modelado y carga de información pública de la Escuela Politécnica Nacional (https://www.epn.edu.ec y sus facultades). Para Hito 2, `--hito2` es un flujo separado que adquiere datos crudos desde páginas oficiales de las IES configuradas; sus resultados multi-IES aún deben ejecutarse, perfilarse y validarse antes de considerarlos completos.

El objetivo principal es poblar un Data Warehouse con un esquema de Constelacion de Hechos (Fact Constellation Schema) que soporte analisis OLAP, construccion de indicadores de gestion y reporteria estrategica para la toma de decisiones academicas y directivas en la universidad.

---

## 2. Objetivos
1. **Extraccion Etica y Modular**: Desarrollar extractores en Python que descubran y capturen informacion sobre unidades academicas, oferta de grado y posgrado, directivos, comunicacion institucional e investigacion, respetando robots.txt, politicas de retardo (rate limiting) y almacenamiento en cache local.
2. **Transformacion y Normalizacion Rigurosa**: Implementar reglas de limpieza textual, resolucion de codificacion de caracteres, eliminacion de duplicados y generacion determinista de claves sustitutas (Surrogate Keys).
3. **Aseguramiento de Calidad de Datos (Data Quality Profiling)**: Auditar la integridad referencial, verificar formatos de correo electronico, detectar valores atipicos y generar reportes de calidad reproducibles.
4. **Diseño Dimensional Justificado**: Construir un esquema de hechos y dimensiones que modele la oferta academica, la gobernanza institucional (con soporte SCD Tipo 2) y la divulgacion de eventos.
5. **Carga Idempotente y Consultas Analiticas**: Persistir los datos tanto en archivos planos normalizados (CSV) como en una base de datos relacional (SQLite por defecto, compatible con PostgreSQL), incluyendo consultas SQL analiticas orientadas a negocio.

---

## 3. Arquitectura General del Flujo de Datos

```
[ Fuentes Web EPN ]
  ├── /facultades/
  ├── /oferta-de-grado/
  ├── /oferta-de-posgrado/
  ├── /autoridades/
  ├── /nosotros/ & /historia/
  └── /wp-json/wp/v2/posts & /noticias/
          │
          ▼ (HTTP Client: Rate Limit 1.0s, Reintentos, Robots.txt)
[ Capa Raw: data/raw/ ] (Cache local de HTML y JSON)
          │
          ▼ (Scrapers especializados: BeautifulSoup, lxml, JSON parser)
[ Capa Interim: data/interim/ ] (Datos parseados en JSON y CSV preliminar)
          │
          ▼ (DataCleaner & DataValidator: Normalizacion, Deduplicacion, Hashing)
[ Capa Processed: data/processed/ ] (Archivos CSV limpios y Reporte de Calidad)
          │
          ├──► CsvLoader (data/processed/*.csv)
          └──► DatabaseLoader (SQLAlchemy -> data/epn_dwh.db o PostgreSQL)
                    │
                    ▼
          [ Modelo Dimensional OLAP ]
          (Consultas SQL BI, Power BI, Metabase, Notebooks)
```

---

## 4. Estructura del Repositorio

```
epn-dwh-scraper/
├── README.md                      # Documentacion integral del proyecto
├── requirements.txt               # Dependencias de Python fijadas
├── .env.example                   # Plantilla de variables de entorno
├── .gitignore                     # Exclusion de binarios, bases de datos y cache
├── config/
│   └── settings.yaml              # Parametros de red, rutas y endpoints oficiales
├── data/
│   ├── raw/                       # HTML y JSON cacheados de las solicitudes web
│   ├── interim/                   # Datos parseados estructurados antes de limpieza
│   └── processed/                 # CSV limpios modelados dimensionalmente
├── docs/
│   ├── diccionario_datos.md       # Catalogo detallado de atributos y tipos
│   ├── modelo_dimensional.md      # Justificacion academica del esquema estrella
│   ├── diagrama_modelo.md         # Diagrama de relaciones de entidad Mermaid
│   └── consideraciones_eticas.md  # Marco legal ecuatoriano (LOES, LOPDP, COIP)
├── logs/
│   ├── scraper_execution.log      # Trazabilidad completa de ejecucion
│   └── reporte_calidad_datos.md   # Auditoria cuantitativa de validacion
├── sql/
│   ├── 01_ddl_dimensiones.sql     # DDL de tablas dimensionales
│   ├── 02_ddl_hechos.sql          # DDL de tablas de hechos e indices
│   ├── 03_carga_ejemplo.sql       # Inserciones sinteticas de prueba
│   └── 04_consultas_bi.sql        # 8 consultas analiticas para soporte decisional
├── src/
│   ├── __init__.py
│   ├── main.py                    # Orquestador CLI con interfaz argparse
│   ├── config.py                  # Cargador de configuracion centralizada
│   ├── utils/
│   │   ├── http_client.py         # Cliente con rate limiting y politicas robots.txt
│   │   ├── logger.py              # Configuracion de logging a consola y disco
│   │   └── helpers.py             # Utilidades de texto, expresiones regulares y hash
│   ├── scrapers/
│   │   ├── base_scraper.py        # Clase base abstracta
│   │   ├── facultades_scraper.py  # Extractor de facultades y unidades
│   │   ├── carreras_scraper.py    # Extractor de carreras y posgrados
│   │   ├── autoridades_scraper.py # Extractor de directivos y decanos
│   │   ├── institucional_scraper.py # Extractor de mision, historia y laboratorios
│   │   └── noticias_scraper.py    # Extractor de notas de prensa y eventos
│   ├── transform/
│   │   ├── cleaning.py            # Normalizacion dimensional y resolucion de FKs
│   │   └── validation.py          # Reglas de negocio y perfilamiento de datos
│   └── load/
│       ├── to_csv.py              # Exportador idempotente a CSV
│       └── to_database.py         # Cargador relacional con SQLAlchemy
├── tests/
│   ├── test_scrapers.py           # Pruebas unitarias de parsing
│   ├── test_cleaning.py           # Pruebas de limpieza y generacion de claves
│   └── test_validation.py         # Pruebas de reglas de validacion
└── notebooks/
    └── exploracion_datos.ipynb    # Perfilamiento interactivo y graficos BI
```

---

## 5. Requisitos del Sistema e Instalacion

### 5.1 Requisitos Previos
- Python 3.10 o superior (verificado con Python 3.10 y Python 3.12).
- Gestor de paquetes pip.
- Conectividad a Internet (para la fase inicial de extraccion; las fases posteriores operan con cache local).

### 5.2 Instalacion Paso a Paso
1. Clonar o posicionarse en el directorio del proyecto:
   ```bash
   cd epn-dwh-scraper
   ```

2. Crear y activar un entorno virtual:
   - En Windows (PowerShell):
     ```powershell
     python -m venv venv
     .\venv\Scripts\Activate.ps1
     ```
   - En Linux o macOS:
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     ```

3. Instalar las dependencias requeridas:
   ```bash
   pip install -r requirements.txt
   ```

4. Configurar el archivo de entorno:
   ```bash
   cp .env.example .env
   ```

---

## 6. Modo de Ejecucion

El orquestador central (`src/main.py`) cuenta con una interfaz por linea de comandos (CLI) que permite ejecutar el pipeline de forma completa o por etapas especificas.

### 6.1 Ejecucion Integral (Extraccion, Transformacion y Carga)
Descarga la informacion institucional, limpia, valida, exporta a CSV e inserta en la base de datos SQLite:
```bash
python -m src.main --all
```

### 6.2 Ejecucion Modular por Extractor
- Solo facultades y decanatos:
  ```bash
  python -m src.main --facultades
  ```
- Solo carreras y posgrados:
  ```bash
  python -m src.main --carreras
  ```
- Solo autoridades universitarias:
  ```bash
  python -m src.main --autoridades
  ```
- Solo historia, principios y centros de investigacion:
  ```bash
  python -m src.main --institucional
  ```
- Solo noticias y eventos:
  ```bash
  python -m src.main --noticias
  ```

### 6.3 Ejecucion de Transformacion y Carga desde Datos Intermedios
Si los datos ya fueron extraidos a `data/interim/`, es posible reejecutar la transformacion y carga sin realizar peticiones web adicionales:
```bash
python -m src.main --transform --load-csv --load-db
```

### 6.4 Forzar Actualizacion Remota (Ignorar Cache)
Para omitir la cache local de `data/raw/` y consultar nuevamente el portal web en vivo:
```bash
python -m src.main --all --force-refresh
```

---

## 7. Diseño del Modelo Dimensional

El modelo analitico adopta un esquema de Constelacion de Hechos con dimensiones conformadas:

### 7.1 Tablas de Dimensiones
- `dim_facultad`: Codigo sustituto, nombre de la unidad, sigla institucional (FIS, FICA, FCA, FIEE, etc.), autoridades de decanato, correo, telefono y ubicacion fisica.
- `dim_nivel_formacion`: Tecnologia, Grado, Maestria, Doctorado, y ciclo academico LOES.
- `dim_modalidad`: Presencial, Dual, En Linea, Semipresencial.
- `dim_carrera`: Título de la carrera, titulo otorgado, codigo de resolucion CES, perfil de ingreso y perfil de egreso.
- `dim_cargo`: Rector, Vicerrector/a, Decano/a, Subdecano/a, clasificado por nivel de gobierno central o de facultad.
- `dim_autoridad`: SCD Tipo 2 con fecha de inicio, fecha de fin y bandera de vigencia para seguimiento de relevos directivos.
- `dim_tiempo`: Calendario continuo con fecha, año, mes, nombre de mes, trimestre, semestre y clasificacion laboral.
- `dim_categoria_noticia`: Temas de comunicacion (Investigacion, Resoluciones, Convocatorias).

### 7.2 Tablas de Hechos
- `fact_oferta_academica`: Métricas de duracion en semestres, duracion en años, creditaje acumulado y acreditacion.
- `fact_designacion_autoridades`: Nombramientos directivos con indicador de titularidad frente a encargo temporal "(E)".
- `fact_comunicacion_institucional`: Conteo de noticias, volumen textual en caracteres y palabras publicadas.

---

## 8. Ejecucion de Pruebas Unitarias
El proyecto incluye una suite de pruebas automatizadas con pytest que valida selectores, normalizaciones, generacion determinista de claves, idempotencia de staging, paginacion y reglas de auditoria de calidad:
```bash
# Ejecutar suite completa (60 pruebas unitarias)
pytest -v
```

---

## 8.1 Hito 2 — Estado de Avance y Novedades Multi-Institución

El alcance de las preguntas de negocio de Hito 1/H1Barros es: P1 oferta académica, P2 autoridades y P3 publicaciones institucionales. El flujo `--hito2` obtiene datos de las páginas oficiales configuradas para oferta, autoridades, facultades, personal docente disponible y noticias. No utiliza GitHub ni el CES como fuente de carreras, autoridades o noticias; el catálogo CES solo aporta códigos y datos de identificación institucional.

El modelo analitico principal conserva las tres preguntas P1-P3 del documento H1Barros. El lote tambien guarda directorios de facultades y, como datos complementarios cuando hay una fuente nominal configurada, personal docente; estos CSV brutos no se convierten en una tabla de hechos del DWH.

**Estado de la extracción multi-IES:** la configuración local contiene 64 instituciones y, en el último prechequeo (`--dry-run`), tenía URL de oferta para 63, autoridades para 25 y noticias para 39. Esos números significan que hay URLs configuradas; no certifican que las páginas respondan, que sean exhaustivas ni que sus datos se hayan descargado. El modo de prueba no hace solicitudes web y no crea un lote de datos.

La oferta guarda candidatos visibles en enlaces, tarjetas, encabezados y tablas; cada fila conserva tipo de registro y evidencia para no tratar automaticamente una etiqueta como carrera vigente. Para tipo, nivel, modalidad y vigencia hay que revisar la evidencia en `oferta_raw.csv` y `cobertura_extraccion.csv`. El nivel se infiere solo cuando lo declara el título de la página; modalidad, financiamiento y vigencia quedan `no_determinado` si la ficha no los publica con una etiqueta explícita. Por tanto, el lote bruto aún no permite responder P1 con todas sus dimensiones; hay que revisar fichas y cobertura por institución mediante `cobertura_extraccion.csv`.

Los documentos existentes en `docs/hito2/` son artefactos de trabajo: en particular, `informe_calidad.md` y `notebooks/hito2_perfilado.ipynb` describen la línea base EPN, no un perfil medido de las 64 IES. No deben citarse como medición de cobertura/calidad multi-IES hasta ejecutar y perfilar ese lote. La integración de SNIESE/CES no forma parte de esta extracción de contenido institucional.

### Nuevas Banderas CLI del Orquestador
```bash
# Ejecutar pipeline cargando datos crudos a Staging PostgreSQL
python -m src.main --all --target stg

# Ejecutar extractor para una institucion especifica (EPN, ESPE, USFQ)
python -m src.main --all --institucion ESPE --max-paginas 10

# Modo de prueba ligero sin escrituras pesadas
python -m src.main --all --dry-run
```

---

## 9. Consideraciones Eticas y Legales
El software respeta escrupulosamente el ordenamiento juridico ecuatoriano:
- **robots.txt**: Valida que no se acceda a rutas restringidas (`/wp-admin/`).
- **LOTAIP y LOES**: Procesa unicamente informacion de caracter publico garantizada por la legislacion de transparencia en educacion superior.
- **LOPDP**: Excluye datos personales sensibles de cualquier tipo, limitando los registros personales a autoridades de alta direccion en el ejercicio de sus funciones publicas.
- **COIP**: No vulnera mecanismos de autenticacion ni ejecuta tecnicas intrusivas de denegacion de servicio, aplicando rate limiting estricto de 1 segundo por peticion.

---

## 10. Limitaciones Conocidas y Lineas Futuras
1. **Contenido Dinamico Ocasional**: Ciertas mallas curriculares se ofrecen mediante enlaces externos a visores PDF de resoluciones CES en lugar de tablas HTML nativas. El pipeline captura el enlace URL canónico al documento.
2. **Evolucion Tecnologica**:
   - Integracion de orquestacion programada mediante Apache Airflow o Prefect.
   - Conexion directa con tableros interactivos en Power BI, Tableau o Apache Superset.
   - Incorporacion de transformaciones analiticas con dbt (data build tool).

---

## 11. Autores y Licencia
- **Desarrollador**: Proyecto academico de Business Intelligence, Escuela Politecnica Nacional.
- **Licencia**: MIT License - Uso academico, educativo y de investigacion cientifica abierta.
# Extracción inicial de oferta académica desde portales oficiales

La primera etapa guarda enlaces observados en las páginas de oferta, sin
normalizar ni completar nombres. La configuración `config/matriz_fuentes_ies.csv`
contiene las URLs y los estados de revisión de la matriz de 64 IES. Los códigos,
nombres, provincia y cantón se cotejan con `config/catalogo_ces.csv`. Las celdas
pueden contener varias URLs separadas por punto y coma; se omiten las marcadas
como pendientes y quedan registradas las instituciones sin URL de oferta.

```powershell
# Revisar las 64 instituciones y URLs configuradas sin conectarse a Internet
python -m src.main --oferta-bruta --dry-run

# Extraer en la máquina del equipo (el contacto es opcional)
python -m src.main --oferta-bruta
```

La salida incremental queda en `data/raw/oferta_academica_enlaces_raw.csv`.
Incluye el código canónico, institución, provincia/cantón, portal, URL de oferta,
estado de revisión de esa URL, texto y enlace publicados sin afirmar que cada
enlace sea una carrera, contexto, URL final, fecha, hash, corrida y estado. El CSV anterior
`oferta_academica_raw.csv` se conserva como resultado histórico de la primera
versión del extractor.
Las respuestas HTML se guardan por institución bajo `data/raw/<fecha>/<ces_cod>/`.
El extractor trabaja secuencialmente, exige `robots.txt`, espera al menos un
segundo entre solicitudes al mismo host y continúa registrando el estado si un
portal falla. Los enlaces de programas son texto crudo del contenido principal:
no representan por sí solos una oferta completa ni vigencia académica.

## Adquisición para Hito 2

El flujo `--hito2` toma las URLs por categoría de `config/matriz_fuentes_ies.csv`
y procesa oferta, autoridades y noticias con fechas de publicación entre 2024 y
2025. La oferta se conserva como enlaces sin clasificar, y la cobertura marca
qué URLs faltan o qué datos no se pudieron extraer. El modo no ejecuta las
transformaciones analíticas del Hito 3.

```powershell
# Revisar URLs y cobertura local sin hacer solicitudes web
python -m src.main --hito2 --dry-run

# Extraer y guardar archivos locales crudos versionados por corrida
python -m src.main --hito2

# Si PostgreSQL de staging ya está configurado, cargar además a stg
python -m src.main --hito2 --target stg
```

Cada corrida crea `data/raw/hito2/<run_id>/` con CSV y JSON por módulo, una copia
de la matriz utilizada, `cobertura_extraccion.csv` y `manifiesto.json`. Las
respuestas HTML/JSON originales que consulta `HttpClient` quedan en
`data/raw/<fecha>/<ces_cod>/<run_id>/`. El resumen histórico de estados continúa en
`data/ejecucion_institucion.csv`. Estos archivos permiten conectar y perfilar
los datos en Power BI; el inventario completo, diccionario, diagnóstico y matriz
de cobertura del Hito 2 todavía se documentan aparte.

## Actualización de fuentes para P1–P3

La columna opcional `dominios_oficiales_adicionales` autoriza dominios oficiales
externos enlazados desde el portal institucional. Cada excepción debe verificarse
en el sitio oficial antes de agregarla; actualmente se usa para el catálogo de
grados de UNIANDES en `admisionuniandes.edu.ec`.

El cliente HTTP consulta el `robots.txt` del host de cada fuente autorizada; no hereda las reglas del portal principal.

Cuando una IES no tiene URL de noticias en la matriz, el extractor consulta su portada oficial solo para descubrir enlaces internos de noticias/actualidad; no clasifica publicaciones desde la portada. La URL descubierta queda registrada en `cobertura_extraccion.csv` para revisar si conviene incorporarla a la matriz.

El modo `--hito2` genera CSV y JSON crudos de oferta, autoridades, facultades, docentes configurados y noticias dentro de `data/raw/hito2/<run_id>/`. Los fallos de red se registran como `error_http` o `bloqueado_robots`; `sin_fuente` indica que no existe URL configurada.

Para regenerar `docs/secciones_fuentes_pendientes.csv` después de cambiar la matriz:

```powershell
python scripts/generar_secciones_fuentes_pendientes.py
```

El archivo separa secciones sin URL (`SIN_FUENTE`) de fuentes localizadas que aun
requieren validar acceso, cobertura o extraccion (`VALIDAR_FUENTE_O_EXTRACCION`), e incluye facultades y directorios docentes complementarios.
Incluye tambien directorios docentes como dato complementario cuando la matriz tiene URL oficial; la falta de directorio no afecta la definicion de P1-P3.
