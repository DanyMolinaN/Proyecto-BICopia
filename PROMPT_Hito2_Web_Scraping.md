# PROMPT: EVOLUCIÓN DEL WEB SCRAPING PARA EL HITO 2 (ADQUISICIÓN Y CALIDAD DE DATOS)

Instrucciones para un agente de código (por ejemplo Claude Code) que trabajará dentro del repositorio `Proyecto-BI/epn-dwh-scraper`.

Antes de empezar, el equipo debe completar estos campos (búscalos en el texto con los corchetes):

- `[INSTITUCIONES PILOTO]`: universidades adicionales a la EPN para la prueba de cobertura (se recomiendan 2 o 3, con portal WordPress).
- `[CORREO DE CONTACTO DEL EQUIPO]`: correo real del equipo para el User-Agent.

---

## 0. LEE ESTO PRIMERO: CÓMO SE ORGANIZA ESTE DOCUMENTO

1. Secciones 1 a 4: contexto. Explican el curso, qué es cada hito, qué se pide y por qué. No contienen tareas.
2. Sección 5: estado actual del repositorio y qué problemas se encontraron en una auditoría previa.
3. Sección 6: reglas obligatorias para no dañar lo que ya funciona.
4. Sección 7: las tareas, por fases.
5. Secciones 8 a 10: verificación, formato de respuesta y prohibiciones.

Si algo de este documento entra en conflicto con la seguridad del código existente, prevalece la sección 6.

---

## 1. CONTEXTO DEL CURSO Y DEL PROYECTO

### 1.1. Qué es el proyecto

- **Curso:** Business Intelligence (ISWD743), Ingeniería en Computación, 7.º semestre, FIS-EPN.
- **Proyecto Final Integrador:** cada equipo construye durante 16 semanas una solución de BI completa sobre una institución real de un sector. Cada hito alimenta al siguiente y en la semana 16 se defiende ante una audiencia de decisión.
- **Este equipo:** Equipo 6, sector **Universidades**. Unidad de análisis: universidad o escuela politécnica.
- **Alcance definido en el Hito 1:** universidades y escuelas politécnicas del Ecuador, incluyendo públicas, particulares cofinanciadas y particulares autofinanciadas. La idea es analizar el sistema universitario ecuatoriano en su conjunto, no una sola institución.
- **Idea central del proyecto:** perfilar una institución, formular sus preguntas de negocio, construir con sus datos un data warehouse y un tablero que las respondan.

### 1.2. Los seis hitos

| Hito | Semana | Entregable | Peso dentro del bimestre |
|---|---|---|---|
| 1 | 5 | Perfil institucional y preguntas de negocio (documento e inventario de fuentes) | 30 % |
| 2 | 6 | **Adquisición y calidad de datos** (staging, notebook, diccionario) | 30 % |
| 3 | 8 | Modelo dimensional y presentación de avance (DDL, diagrama, exposición) | 40 % |
| 4 | 11 | ETL e implementación del data warehouse (scripts y bitácora de cargas) | 30 % |
| 5 | 13 | Analítica OLAP, tablero Power BI y modelo analítico | 30 % |
| 6 | 16 | Presentación final y defensa | 40 % |

El proyecto vale el 25 % de la nota de cada bimestre. Los hitos 1 a 3 forman el primer bimestre y los hitos 4 a 6 el segundo.

### 1.3. Arquitectura de referencia (obligatoria para todos los equipos)

Todo dato pasa por staging y ETL antes de llegar al data warehouse:

1. **Fuentes:** datos abiertos (INEC, SENESCYT, MINEDUC, SERCOP, Supercias), institucionales autorizados o sintéticos declarados.
2. **Staging en PostgreSQL (esquema `stg`):** copia cruda y versionada de cada fuente, **sin transformar**, con fecha de carga.
3. **ETL en Python y SQL:** limpieza, reglas de calidad, claves sustitutas, SCD tipo 2, bitácora y reconciliación de cargas.
4. **Data warehouse en PostgreSQL (esquema `dw`):** tablas de hechos y dimensiones conformadas en estrella o constelación.
5. **Consumo:** consultas OLAP en SQL, tablero en Power BI y un modelo analítico en Python.

Regla clave: ninguna consulta del tablero lee de staging ni de las fuentes; todo pasa por `dw`. No se puede sustituir PostgreSQL ni Power BI.

### 1.4. Requisitos mínimos generales del proyecto (sección 4 de la guía)

| Requisito | Mínimo aceptable |
|---|---|
| Preguntas | Entre 5 y 8 preguntas de negocio concretas, respondibles con los datos disponibles |
| Fuentes | Al menos 2 fuentes integrables y 3 periodos de datos |
| Volumen | Orientativo: al menos 10.000 filas en la tabla de hechos principal |
| Modelo | 1 tabla de hechos, dimensión tiempo, 3 dimensiones conformadas y una con SCD tipo 2 |
| ETL | Scripts Python/SQL que reconstruyen el DW desde cero con un solo comando |
| Tablero | Power BI con al menos 2 páginas |

Implicación para el scraping: el volumen de datos extraídos condiciona si el proyecto alcanzará esos mínimos. Más instituciones y más años de publicaciones (P3) ayudan a llegar al orden de 10.000 filas.

### 1.5. Reglas de ética y uso de datos (sección 10 de la guía)

- Toda fuente se cita con enlace, fecha de descarga y licencia; **un dato sin fuente no entra al DW**.
- Los datos personales se anonimizan antes de cargar a staging, conforme a la Ley Orgánica de Protección de Datos Personales (LOPDP).
- Los datos sintéticos se marcan como tales en el diccionario y en el tablero, con el script que los genera.
- El repositorio Git tiene commits de todo el equipo; el historial es evidencia de la coevaluación.
- El uso de IA se declara en el informe (qué se pidió y cómo se verificó). El equipo responde por cada línea y cada cifra.
- Entregas tardías: -10 % por día hábil, hasta 3 días.

Marco normativo mencionado en el Hito 1: LOTAIP (transparencia y acceso a la información pública) y LOPDP.

---

## 2. LAS TRES PREGUNTAS DE NEGOCIO DEL HITO 1 (NO SE SUSTITUYEN)

El Hito 1 fijó las preguntas que el tablero final debe responder. Los datos extraídos deben permitir calcularlas. Si el scraper no entrega un campo de los listados abajo, esa pregunta no se podrá responder en el tablero.

### P1. Oferta académica (analítica descriptiva)

**Pregunta:** ¿Cómo se distribuye la oferta académica vigente de grado y posgrado de las universidades y escuelas politécnicas del Ecuador durante 2026, según el nivel de formación, modalidad de estudio y tipo de financiamiento?

- **Indicadores:** total de programas académicos vigentes; participación por modalidad (%).
- **Dimensiones:** universidad, año, nivel de formación, modalidad, financiamiento, estado del programa.
- **Fuentes candidatas:** Consejo de Educación Superior (CES) y Secretaría de Educación Superior, Ciencia, Tecnología e Innovación (SENESCYT; su sistema de datos abiertos es el SNIESE).

### P2. Autoridades universitarias (analítica diagnóstica)

**Pregunta:** ¿Cómo se distribuyen las autoridades rectorales y decanales de las universidades y escuelas politécnicas del Ecuador durante 2026, según el cargo, la institución y la condición de titularidad o encargo?

- **Indicadores:** total de autoridades identificadas; porcentaje de autoridades encargadas.
- **Dimensiones:** universidad, fecha de observación, cargo, facultad, condición de designación.
- **Fuentes candidatas:** portales web oficiales de las universidades (secciones de autoridades, rectorados, decanatos).

### P3. Comunicación institucional (analítica descriptiva)

**Pregunta:** ¿Cómo evolucionó el volumen de publicaciones institucionales de las universidades y escuelas politécnicas del Ecuador entre 2024 y 2025, según su categoría temática y trimestre de publicación?

- **Indicadores:** total de publicaciones; variación interanual (%).
- **Dimensiones:** universidad, año, trimestre, categoría temática, tipo de publicación.
- **Fuentes candidatas:** portales oficiales (noticias, comunicados, convocatorias y otras publicaciones institucionales).

---

## 3. QUÉ PIDE EL HITO 2 (ADQUISICIÓN Y CALIDAD DE DATOS)

### 3.1. Descripción oficial

El equipo descarga o recibe sus datos, los carga **sin transformar** a staging y mide su calidad. Es trabajo poco vistoso, pero decide la confiabilidad de todo lo que viene después. Se entrega en la semana 6.

### 3.2. Qué se entrega

1. Datos crudos versionados (o el script que los descarga) y el esquema `stg` en PostgreSQL.
2. Diccionario de datos en Excel con las columnas: Tabla, Campo, Tipo, Descripción, Unidad, Ejemplo, Notas.
3. Notebook de perfilado en Python: nulos, duplicados, rangos, tipos y valores atípicos.
4. Informe de calidad: regla, resultado medido y decisión tomada.

### 3.3. Criterios de aceptación

- Hay al menos 2 fuentes integrables y 3 periodos de datos cargados en staging.
- El diccionario documenta todos los campos que se usarán, con unidades de medida.
- Cada regla de calidad tiene su resultado **medido**, no solo su descripción.
- Las claves que unirán las fuentes están identificadas.

### 3.4. Consejos y errores comunes que indica la guía

- Documentar las unidades (dólares, estudiantes, porcentaje).
- Si un campo se llama distinto en dos fuentes pero significa lo mismo, anotarlo ya.
- Guardar la fecha de descarga de cada archivo.
- **Error:** limpiar datos a mano en Excel (se pierde la trazabilidad).
- **Error:** cargar todas las columnas "por si acaso"; solo las que responden a las preguntas.

### 3.5. Las seis dimensiones de calidad que se diagnostican

| Dimensión | Pregunta que responde | Ejemplos en este proyecto |
|---|---|---|
| Completitud | ¿Se obtienen todos los campos necesarios? | Programas sin modalidad, publicaciones sin fecha |
| Validez | ¿Los valores respetan el formato y los criterios? | Fechas inválidas, años fuera de 2024-2025 |
| Exactitud | ¿Reflejan lo que publica la institución? | Registro frente a la página de origen |
| Consistencia | ¿Se representan de forma uniforme? | Una universidad escrita de varias maneras, cargos equivalentes con nombres distintos |
| Unicidad | ¿Hay registros repetidos? | URLs repetidas por paginación, programas duplicados |
| Oportunidad | ¿Corresponde al período requerido? | Oferta 2026, autoridades 2026, publicaciones 2024-2025 |

### 3.6. Alcance de este hito: diagnosticar, no corregir

El Hito 2 **mide** la calidad. La corrección de los problemas encontrados, la limpieza y el modelado dimensional corresponden al Hito 3 y al Hito 4. Por eso:

- No limpies ni corrijas datos en staging.
- No construyas el data warehouse, las dimensiones ni el SCD2 como parte de esta tarea. Lo que ya existe en el repositorio de transformación se conserva tal cual.
- El perfilado estadístico dentro de Power Query y el archivo Power BI no son responsabilidad del scraper. El scraper debe entregar datos **trazables y estructurados**.

### 3.7. Interpretación de "3 periodos" (a confirmar con el docente)

Se propone cubrir 2024 y 2025 (P3, publicaciones) y el corte 2026 (P1 y P2, oferta y autoridades). Si el docente define otra interpretación, ajustar sin cambiar el resto.

### 3.8. Cómo se evalúa cada hito (rúbrica genérica, 20 puntos)

| Criterio | Qué se evalúa | Puntos |
|---|---|---|
| Cumplimiento | Entrega todos los componentes pedidos en el formato solicitado | 6 |
| Calidad técnica | Las decisiones técnicas son correctas y están bien aplicadas | 6 |
| Documentación | Explica con claridad qué se hizo y por qué | 4 |
| Conexión con el caso | Aporta a responder las preguntas de negocio | 4 |

---

## 4. LO QUE VIENE DESPUÉS (PARA NO ADELANTARSE NI ROMPER NADA)

- **Hito 3 (semana 8):** matriz de bus, esquema estrella o constelación con la granularidad declarada, DDL del esquema `dw`. Aquí se corrigen los problemas que el Hito 2 diagnostique. **Criterio:** cada pregunta del Hito 1 debe poder responderse con el modelo.
- **Hito 4 (semana 11):** ETL reproducible con un solo comando, SCD tipo 2 en una dimensión, bitácora de cargas y reconciliación fuente frente a DW.
- **Hito 5 (semana 13):** consultas OLAP, tablero Power BI y modelo analítico (clustering, regresión o series).
- **Hito 6 (semana 16):** presentación y defensa final.

Consecuencia para este trabajo: los campos que el scraper no extraiga ahora (universidad, financiamiento, estado, tipo de publicación, condición de designación) no podrán aparecer después en el modelo ni en el tablero.

### 4.1. Glosario mínimo

- **IES:** institución de educación superior (universidades y escuelas politécnicas).
- **CES:** Consejo de Educación Superior. **SENESCYT / SNIESE:** secretaría y sistema nacional de información de educación superior. **CACES:** organismo de evaluación y acreditación.
- **Staging (`stg`):** zona de aterrizaje de datos crudos, sin transformar, con fecha de carga.
- **Grano (granularidad):** lo que representa una fila de una tabla (por ejemplo, una publicación, o un programa por institución).
- **Dimensión conformada:** dimensión compartida por varios hechos (por ejemplo, institución o tiempo).
- **SCD tipo 2:** técnica para conservar el historial de cambios con fechas de vigencia.
- **Perfilado:** medición del estado de los datos (nulos, duplicados, rangos, tipos, atípicos).
- **Trazabilidad:** poder decir de qué página, cuándo y en qué ejecución salió cada dato.

---

## 5. ESTADO ACTUAL DEL REPOSITORIO (VERIFICADO EN UNA AUDITORÍA PREVIA)

### 5.1. Qué es

`epn-dwh-scraper/` es un **prototipo que ya funciona** y se construyó como prueba con una sola universidad, la EPN. No es un error de diseño: es la base sobre la que se debe construir.

### 5.2. Estructura y flujo

```
config/settings.yaml  (base_url y 11 endpoints de la EPN)
        |
src/main.py  (CLI: --all, --facultades, --carreras, --autoridades, --noticias,
              --institucional, --transform, --load-csv, --load-db, --no-cache, --force-refresh)
        |
src/utils/http_client.py  (robots.txt, 1 s entre peticiones, 4 reintentos, caché 24 h)
        |   -> data/raw/*.html|json
src/scrapers/  (base_scraper + facultades, carreras, autoridades, institucional, noticias)
        |   -> data/interim/*.json|csv
src/transform/  (cleaning.py, validation.py, scd2.py)
        |
src/load/  (to_csv.py -> data/processed/*.csv ; to_database.py -> SQLite con to_sql replace)
```

- Pruebas: `tests/` (49 pruebas, pasan; usan HTML sintético).
- Los scripts de `sql/` (DDL y consultas) **no se ejecutan** desde el pipeline: `execute_sql_file` existe pero nunca se invoca.
- Resultados de la EPN según el reporte del propio equipo: 9 facultades, 46 programas, 10 autoridades, 30 noticias.
- El repositorio no versiona datos (`data/` está en `.gitignore`).

### 5.3. Fortalezas que se deben conservar

`HttpClient` (robots, límite de frecuencia, reintentos), el contrato de `BaseScraper` con el mínimo de registros (`min_records`), la política de no inventar datos, las claves sustitutas deterministas, el validador y la suite de pruebas.

### 5.4. Problemas detectados que motivan las tareas

| ID | Severidad | Problema | Dónde |
|---|---|---|---|
| D-01 | Crítico | Solo existe la EPN; no hay registro de instituciones | `settings.yaml`, `config.py` |
| D-02 | Crítico | Noticias: solo 30 posts, sin paginación ni filtro de fechas (no llega a 2024-2025) | `noticias_scraper._extract_via_api` |
| D-03 | Crítico | Oferta: solo portal de la EPN; no existe financiamiento ni estado/vigencia | `carreras_scraper.py` |
| D-04 | Alto | Ninguna tabla tiene institución | `cleaning.py`, `to_database.py` |
| D-05 | Alto | Autoridades: titularidad se asume por defecto (1) sin evidencia; cargos como texto libre (un cargo por persona); deduplica solo por nombre | `autoridades_scraper._build_record`, `cleaning.py` |
| D-06 | Alto | No hay PostgreSQL ni esquema `stg`; DDL no ejecutado; `AUTOINCREMENT` e `INSERT OR REPLACE` son solo SQLite | `to_database.py`, `sql/` |
| D-07 | Alto | Faltan inventario de fuentes, matriz de cobertura y diccionario en Excel | repositorio |
| D-08 | Medio | Fecha fabricada `"2026-10-01"` en el respaldo HTML de noticias | `noticias_scraper.py` (~línea 101) |
| D-09 | Medio | Palabras clave sin tilde se comparan con texto con tilde (categorías de noticias e inferencia de facultad) | `noticias_scraper.py`, `carreras_scraper.py` |
| D-10 | Medio | Deduplicación silenciosa por nombre | `cleaning.py` |
| D-11 | Medio | Caché que vence en 24 h y se sobrescribe; sin `fecha_extraccion`; hechos con `replace` | `http_client.py`, `to_database.py` |
| D-12 | Medio | Consulta 1 usa INNER JOIN y excluye programas sin facultad (16 de 46) | `sql/04_consultas_bi.sql` |
| D-13 | Medio | Tres User-Agent distintos; la documentación cita un correo `@epn.edu.ec` que no es del equipo | `settings.yaml`, `.env.example`, `docs/consideraciones_eticas.md` |
| D-14 | Bajo | Documentación desactualizada (47 vs 49 pruebas, "nada subido a GitHub") | `docs/` |
| D-15 | Bajo | `sql/03_carga_ejemplo.sql` mezcla datos sintéticos con nombres de personas reales | `sql/03_carga_ejemplo.sql` |

---

## 6. REGLAS PARA NO DAÑAR LO QUE FUNCIONA (OBLIGATORIAS)

1. **Línea base primero.** Crea la rama `hito2-multiinstitucion`, ejecuta `pytest` (deben pasar las 49 pruebas) y registra los conteos actuales de la EPN como referencia de regresión.
2. **Cambios incrementales.** Una tarea por commit, con `pytest` en verde antes de cada commit.
3. **No eliminar.** No borres módulos, funciones ni pruebas existentes: extiéndelos. Si cambias un contrato (firma de función o columnas), mantén compatibilidad o actualiza todas las referencias y pruebas en el mismo commit.
4. **El flujo actual sigue funcionando.** `python -m src.main --all` para la EPN, con salida a CSV y SQLite, debe seguir operando sin parámetros nuevos. Todo lo nuevo se activa por configuración o por banderas opcionales.
5. **No debilitar `HttpClient`.** Se mantienen robots.txt, límite de frecuencia mínimo de 1 s, reintentos y backoff. No uses técnicas para eludir autenticación, captchas ni bloqueos.
6. **No inventar datos.** Si un dato no está publicado, queda `NULL` o `no_determinado` con su evidencia. Están prohibidos los valores por defecto plausibles (fechas, condiciones, categorías, correos).
7. **Poca carga de red.** Añade las banderas `--institucion`, `--max-paginas` y `--dry-run`. Prueba con muestras pequeñas y usa el caché. No ejecutes extracciones masivas.
8. **No tocar los datos originales.** El caché crudo se versiona por fecha y no se sobrescribe.
9. **Fuente inaccesible = reportar.** Si CES, SENESCYT o el portal de una universidad no es accesible, o su licencia o robots.txt lo impide, detente en esa fuente, documenta el hecho y sigue con las demás. No simules datos.
10. **No declarar cobertura nacional.** La cobertura real es la que figure en la matriz, con conteos verificados.

---

## 7. TAREAS (EN ESTE ORDEN; REPORTA AL TERMINAR CADA FASE)

### FASE A. Línea base (solo lectura)

Ejecuta `pytest`, inventaría los archivos y confirma el estado inicial. No modifiques código.

### FASE B. Registro de instituciones y trazabilidad base (resuelve D-01, D-04)

- **B1.** Crea `config/instituciones.yaml` con: `id`, `nombre`, `sigla`, `tipo_institucional` (pública, particular cofinanciada, particular autofinanciada), `financiamiento`, `base_url`, `endpoints` por pregunta, `adaptador`, `estado_integracion` (habilitada, piloto, pendiente) y `observaciones`. Registra la EPN como habilitada. Piloto adicional: `[INSTITUCIONES PILOTO]`. Las demás del alcance quedan "pendiente", sin inventar URLs.
- **B2.** Haz que `BaseScraper` agregue a cada registro crudo: `institucion_id`, `fecha_extraccion` (ISO 8601), `run_id`, `fuente_url` y `hash_registro`, sin romper las columnas existentes.
- **B3.** Que los scrapers reciban la institución desde el registro (la EPN sigue como valor por defecto). Patrón de adaptadores: parsers específicos por portal y un adaptador genérico para portales WordPress (API REST `wp-json`).
- **B4.** Propaga `institucion_id` hasta las tablas procesadas (dimensión institución conformada).

### FASE C. P3: publicaciones 2024-2025 (prioridad más alta; resuelve D-02, D-08, D-09)

- **C1.** En `NoticiasScraper` elimina el límite fijo de 30: pagina con `page` y `per_page=100`, filtra con `after=2024-01-01T00:00:00` y `before=2025-12-31T23:59:59`, y corta con el encabezado `X-WP-TotalPages`. Añade tope `--max-paginas` y respeta el rate limit.
- **C2.** Categoría temática: usa las categorías nativas de WordPress (consulta `/wp-json/wp/v2/categories` y resuelve los ids). La heurística por palabras clave queda solo como respaldo, marcada con `categoria_origen = "heuristica"`. Corrige el defecto de tildes con `remove_accents` antes de comparar.
- **C3.** `tipo_publicacion`: desde la fuente (categoría, tipo de post o sección: noticia, comunicado, convocatoria) con `tipo_origen`; si no se puede, `no_determinado`.
- **C4.** Guarda `fecha_publicacion` (campo `date`) y `fecha_modificacion` (`modified`) por separado.
- **C5.** Elimina la fecha fabricada `"2026-10-01"` del respaldo HTML. Si la fecha no se puede parsear, `NULL`. Parsea fechas textuales en español.
- **C6.** Genera un conteo por institución, año y trimestre para demostrar que 2024 y 2025 están cubiertos. Si el portal no tiene histórico, regístralo como limitación.

### FASE D. P2: autoridades (resuelve D-05, D-10)

- **D1.** Reemplaza `es_titular` (1 por defecto) por `condicion_designacion` con valores `titular`, `encargado`, `subrogante` o `no_determinado`, más `evidencia_condicion` (el texto que la sustenta). Sin evidencia explícita, `no_determinado`. Mantén `es_titular` derivado solo cuando haya evidencia, para no romper consultas.
- **D2.** Normaliza el cargo: `cargo_original` (texto) y `cargo_normalizado` (catálogo: Rector, Vicerrector, Decano, Subdecano, Director, Otro). No generes un cargo por persona. Sin equivalencia, "Otro" con el original conservado.
- **D3.** Deduplica por `(institucion_id, nombre, cargo, unidad)` y registra cuántas filas se descartan y por qué.
- **D4.** Usa las URLs de facultad que descubre `FacultadesScraper` en lugar de la lista escrita a mano en `_extract_deans_from_faculties`.
- **D5.** `fecha_observacion` explícita (fecha de captura) en el hecho, separada de cualquier fecha de designación (que sigue `NULL` si el portal no la publica).
- **D6.** Minimización de datos: conserva nombre, cargo, unidad y URL. Si correo y biografía no responden a P2, no los cargues.

### FASE E. P1: oferta académica (resuelve D-03, D-09, D-10, D-12)

- **E1.** Investiga CES y SENESCYT (SNIESE) para la oferta vigente: formato, acceso, periodicidad y licencia. Si hay datos abiertos descargables, impleméntalos como **segunda fuente** con su propio extractor y su registro en el inventario. Si no, repórtalo y no inventes.
- **E2.** Campos nuevos: `financiamiento` (desde el registro de instituciones), `estado_programa` (`vigente`, `no_vigente`, `no_determinado`) con `evidencia_estado` (de qué fuente sale; una URL publicada **no** prueba vigencia), `anio_referencia = 2026`, `nivel` (grado, posgrado) y `nivel_detalle` (tecnología, grado, especialización, maestría, doctorado).
- **E3.** Deduplica por `(institucion_id, nombre, nivel, modalidad)` y registra las filas descartadas.
- **E4.** Corrige la comparación con tildes en la inferencia de facultad y revisa por qué 16 de 46 programas quedan sin facultad. No cambies a INNER JOIN consultas que excluyan esos programas.
- **E5.** Revisa el filtro de descubrimiento de enlaces (prefijos `ingenieria`, `licenciatura`, `tecnologia`, `carrera`) y reporta qué programas podrían quedar fuera.

### FASE F. Staging PostgreSQL, esquema `stg` (resuelve D-06, D-11)

- **F1.** `docker-compose` opcional con PostgreSQL y variable `DATABASE_URL` (`.env.example`).
- **F2.** `sql/stg/*.sql` en sintaxis PostgreSQL pura (sin `AUTOINCREMENT` ni `INSERT OR REPLACE`). Tablas: `stg_oferta`, `stg_autoridades`, `stg_publicaciones` y las de la segunda fuente. Columnas crudas más metadatos: `run_id`, `fecha_carga`, `institucion_id`, `fuente_url`, `fecha_extraccion`, `hash_registro`.
- **F3.** `StagingLoader` nuevo: ejecuta el DDL (`execute_sql_file`) y carga **sin transformar**. Carga con append versionado por `run_id` (nunca `replace`) e idempotente por `hash_registro`.
- **F4.** Bandera `--target {stg, sqlite, csv}`. El comportamiento actual (CSV y SQLite) sigue siendo el valor por defecto.

### FASE G. Versionado del dato crudo (resuelve D-11)

- **G1.** `data/raw/<AAAA-MM-DD>/...` con `manifest.csv` (url, estado HTTP, fecha_descarga, sha256, institucion_id, run_id). El caché no sobrescribe versiones anteriores.
- **G2.** En cada ejecución reporta las URLs consultadas, bloqueadas por robots, con error y exitosas.

### FASE H. Entregables del Hito 2 (generados por script reproducible, no a mano)

- **H1.** `docs/hito2/inventario_fuentes.xlsx` (nombre, dueño, formato, periodicidad, años disponibles, licencia, enlace, fecha de descarga), desde el registro y el manifiesto.
- **H2.** `docs/hito2/diccionario_datos.xlsx` con Tabla, Campo, Tipo, Descripción, Unidad, Ejemplo, Notas, solo para las tablas `stg` y las columnas usadas. Marca explícitamente los datos sintéticos (como los de `sql/03_carga_ejemplo.sql`) si se conservan.
- **H3.** `docs/hito2/matriz_cobertura.xlsx`: institución por P1/P2/P3, con "configurada", "consultada" y "con registros" (conteos reales).
- **H4.** `notebooks/hito2_perfilado.ipynb` sobre `stg`, **ejecutado con salidas**: nulos, duplicados, rangos, tipos, atípicos y conteos por año y trimestre (P3).
- **H5.** `docs/hito2/informe_calidad.md`: tabla regla, resultado medido y decisión tomada para las seis dimensiones, por conjunto de datos. Solo diagnóstico.
- **H6.** Lista de claves de unión entre fuentes (`institucion_id`, claves de programa, etc.).

### FASE I. Ética, pruebas y documentación (resuelve D-13, D-14, D-15)

- **I1.** Unifica el User-Agent (`settings.yaml` y `.env.example`) con un contacto real leído desde variable de entorno: `[CORREO DE CONTACTO DEL EQUIPO]`. No uses correos inventados ni de dominios ajenos.
- **I2.** Pruebas nuevas: paginación y filtro de fechas con respuestas simuladas, defecto de tildes, ausencia de fechas fabricadas, `condicion_designacion` sin evidencia, `StagingLoader` (idempotencia) y manifiesto. Añade 2 o 3 fixtures de HTML real por institución.
- **I3.** Actualiza README, `docs/modulos/` y el árbol de carpetas. Corrige las cifras desactualizadas. Marca `sql/03_carga_ejemplo.sql` como sintético.

---

## 8. VERIFICACIÓN FINAL

- `pytest` en verde (las 49 originales más las nuevas).
- `python -m src.main --all` para la EPN produce los conteos de línea base, o las diferencias están explicadas.
- P3 con cobertura 2024-2025 demostrada con el conteo por año y trimestre.
- Carga a `stg` verificada con `SELECT COUNT(*)` por tabla y `run_id`.
- Informe final con una tabla de criterios de aceptación del Hito 2 (cumplido, parcial, no cumplido o no verificable), cada uno con evidencia (ruta de archivo o cifra medida).

## 9. FORMATO DE RESPUESTA

Al terminar cada fase informa: qué cambiaste (archivos y funciones), resultado de `pytest`, hallazgos y decisiones que requieren al equipo. Al final entrega el informe de la sección 8 y la lista de limitaciones reales: fuentes no accesibles, instituciones pendientes y datos no disponibles. Declara el uso de IA en `docs/hito2/declaracion_ia.md` (qué se pidió y cómo se verificó).

## 10. PROHIBIDO

- Inventar datos, fuentes o cobertura.
- Marcar como hecho algo que no verificaste.
- Reemplazar módulos que funcionan.
- Ejecutar extracciones masivas.
- Eludir restricciones de acceso.
- Limpiar o corregir datos en staging.
- Hacer push a `main` sin que el equipo revise la rama.
