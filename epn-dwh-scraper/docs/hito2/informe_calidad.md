# Informe de Calidad de Datos — Hito 2
**Proyecto:** EPN DWH Scraper — Multi-institución  
**Ámbito:** línea base histórica EPN en `stg` y adquisición cruda multi-IES (sin carga a `stg`)
**Fecha de verificación:** 2026-11-21  
**Entorno de medición:** Ejecución real controlada sobre el portal EPN (`python -m src.main --all --target stg --max-paginas 2`) y perfilado estadístico ejecutado en `notebooks/hito2_perfilado.ipynb` sobre base de datos SQLite `data/epn_dwh.db`.

> **Alcance de este informe:** las métricas históricas detalladas más abajo corresponden únicamente a la EPN y al flujo `--all` indicado arriba. El perfil multi-IES medido en el lote `f7c0675f-e871-49c5-aab6-2f9560c25658` se resume a continuación. Ese lote contiene archivos crudos locales y no se cargó a PostgreSQL `stg`; el `--dry-run` solo comprueba configuración, sin descargar páginas.

## Perfil de adquisición multi-IES — lote `f7c0675f-e871-49c5-aab6-2f9560c25658`

Fuente del perfil: `data/raw/hito2/f7c0675f-e871-49c5-aab6-2f9560c25658/`. El lote se obtuvo desde los dominios universitarios configurados y conserva URL, hora de extracción y `run_id`. Los conteos representan extracción observada, no validación manual de que cada portal haya publicado la oferta completa.

| Tema / regla | Medición observada | Evaluación para las preguntas de negocio |
|---|---:|---|
| Oferta académica | 1.066 filas para 39 IES; 86 títulos leídos de fichas oficiales; nivel explícito en 429 filas (349 tercer nivel, 80 cuarto nivel), 637 sin determinar | Parcial. Modalidad, financiamiento y vigencia están `no_determinado` en las 1.066 filas; no usar las filas como conteo de carreras vigentes. |
| Autoridades | 109 filas para 19 IES; nombres, cargos y unidad no vacíos; 76 cargos quedaron como `Autoridad Universitaria`; 105/109 condiciones son `no_determinado` y 4 son `encargado` | Parcial. La cobertura no permite calcular la distribución nacional ni la proporción de encargados con confianza. |
| Publicaciones | 297 filas para 17 IES; fecha dentro de 2024–2025 en 232 filas (74 de 2024, 158 de 2025) y procedentes de 3 IES; 65 sin fecha; 7 títulos vacíos; 45 con categoría `Sin categoría`; 193 tipos `no_determinado` | Parcial. Los registros sin fecha no sirven para el indicador trimestral. Las categorías y tipos requieren normalización temática antes de responder P3. |
| Disponibilidad de fuente | Oferta: URL en 63/64 IES; autoridades: 25/64; noticias: 39/64. Estados de ejecución: 39 oferta `parcial`, 19 autoridades `ok`, 17 noticias `ok`; las demás secciones quedaron `sin_seccion` | La URL configurada no garantiza que responda ni que sea exhaustiva. Consultar `cobertura_extraccion.csv` por institución y módulo. |
| Validez temporal de publicaciones | Fechas observadas entre `2024-02-11` y `2025-12-24`; todas las fechas válidas caen en la ventana 2024–2025 | Cumple para las 232 filas fechadas; no clasificar las 65 sin fecha en un trimestre. |
| Unicidad | 0 duplicados por clave compuesta de autoridad y 0 posts duplicados por `(institucion_id, post_id)`; 59 enlaces de oferta se repiten entre páginas fuente | Los enlaces repetidos se conservan porque cada fila mantiene la URL de la página donde se observó. |

**Limitaciones medidas:** el lote no cubre las 64 IES con datos válidos en los tres temas. No responde todavía P1 por modalidad/financiamiento/vigencia, ni P2 por condición de designación en la mayoría de autoridades, ni P3 con fechas para todas las instituciones. Tampoco reemplaza el diccionario, notebook ni carga a `stg` requeridos por los entregables de Hito 2.

---

> [!IMPORTANT]
> **Aclaración Metodológica de Integridad:**  
> En cumplimiento del principio de **no invención de datos**, se eliminó por completo la inyección de registros sintéticos/embebidos en staging (`stg_oferta_sniese`). Todas las métricas presentadas en este informe provienen exclusivamente de ejecuciones reales del pipeline sobre los portales institucionales de la EPN y consultas SQL directas contra las tablas de staging.

---

## Resumen Ejecutivo de Volumetría en Staging

| Tabla Staging | Registros Extraídos | Registros Idempotentes (2da Corrida) | % Completitud General |
|---|---|---|---|
| `stg_facultades` | 9 | 0 nuevos (9 omitidos) | 88.9 % en campos clave |
| `stg_oferta` | 46 | 0 nuevos (46 omitidos) | 100 % nombres, 91.3 % facultad |
| `stg_autoridades` | 10 | 0 nuevos (10 omitidos) | 100 % nombres y cargos |
| `stg_institucional` | 28 | 0 nuevos (28 omitidos) | 96.4 % contenido |
| `stg_publicaciones` | 194 | 0 nuevos (194 omitidos) | 100 % atributos obligatorios |
| `stg_oferta_sniese` | 0 | 0 nuevos (0 omitidos) | 0 % (segunda fuente pendiente) |

---

## 1. Completitud

Basado en `BaseScraper._add_traceability()`, DDLs de staging y perfilado del notebook.

| Regla | Conjunto de Datos | Resultado Medido | Decisión Tomada |
|---|---|---|---|
| `run_id` obligatorio y NOT NULL | Todas las tablas `stg` | ✅ 100 % presente (287/287 registros totales) | Generado automáticamente con `uuid.uuid4()` en `_add_traceability()`. |
| `institucion_id` obligatorio y NOT NULL | Todas las tablas `stg` | ✅ 100 % presente (287/287 = "EPN") | Parametrizado en constructor; propagado consistentemente. |
| `hash_registro` obligatorio y NOT NULL | Todas las tablas `stg` | ✅ 100 % presente (287/287 registros) | SHA-256 de 20 caracteres calculado sobre atributos semánticos. |
| `fecha_extraccion` en formato ISO 8601 UTC | Todas las tablas `stg` | ✅ 100 % presente (287/287 registros) | Timestamp ISO 8601 UTC inyectado en tiempo de extracción. |
| `nombre` del programa no debe ser NULL | `stg_oferta` | ✅ 100 % (46/46 registros) | Campo fundamental para P1; registros sin nombre no se crean. |
| `facultad_nombre` no debe ser NULL | `stg_oferta` | ⚠️ 91.3 % (42/46 con facultad, 4 nulos = 8.7 %) | 4 programas de posgrado/tecnología no detallan facultad explícita en su portada; se admiten como NULL en staging y se resolverán con `dim_facultad` o inferencia en Hito 3. |
| `nombre_completo` de autoridad no debe ser NULL | `stg_autoridades` | ✅ 100 % (10/10 registros) | Todos los registros capturan el nombre oficial de la autoridad. |
| `titulo` de publicación no debe ser NULL | `stg_publicaciones` | ✅ 100 % (194/194 registros) | API REST de WordPress expone `title.rendered` en todas las publicaciones. |
| Campos opcionales sin valor en portal: `correo_contacto`, `biografia`, `periodo_gestion` | `stg_autoridades` | ⚠️ 0 % presente (10/10 nulos) | El portal institucional de autoridades no publica correos ni biografías en la ficha general. Decisión: permitir NULL en staging sin fabricar datos falsos. |
| Campos opcionales sin valor en portal: `creditos`, `campo_ocupacional` | `stg_oferta` | ⚠️ 0 % presente (46/46 nulos) | Las fichas de navegación de programas no exponen créditos ni campos ocupacionales sin descargas de mallas PDF. Permitido como NULL. |
| Segunda fuente SNIESE | `stg_oferta_sniese` | ❌ 0 registros | Retirado el baseline embebido para evitar datos falsos en staging. Criterio marcado como NO CUMPLIDO hasta contar con el CSV oficial. |

---

## 2. Validez

Basado en `_safe_date()`, `extract_modality()` y validaciones de esquema.

| Regla | Conjunto de Datos | Resultado Medido | Decisión Tomada |
|---|---|---|---|
| `fecha_publicacion` con formato YYYY-MM-DD sin fechas fabricadas | `stg_publicaciones` | ✅ 100 % válido (194/194 registros parseados). Min: `2024-07-29`, Max: `2025-12-24`. | `_safe_date()` valida fechas ISO y español; si no parsea retorna `None`. Cero fechas inventadas. |
| `modalidad` dentro de catálogo: Presencial, Semipresencial, En Linea, Dual, Hibrida, o NULL | `stg_oferta` | ✅ 100 % conforme: 18 'Presencial' (39.1 %), 28 NULL (60.9 %). | `extract_modality()` mapea sólo a valores válidos del catálogo. No se asume modalidad si no está explícita. |
| `anio_referencia` ≥ 2024 | `stg_oferta` | ✅ 100 % (46/46 = 2026) | Asignado como año de vigencia actual del catastro. |
| `post_id` cadena no vacía y numérica | `stg_publicaciones` | ✅ 100 % (194/194 válidos) | Identificadores únicos provistos directamente por la API de WordPress. |
| `tipo_publicacion` dentro de catálogo cerrado | `stg_publicaciones` | ✅ 100 % conforme: 92 'no_determinado' (47.4 %), 60 'comunicado' (30.9 %), 42 'noticia' (21.6 %). | Clasificación mediante `_infer_tipo_publicacion()` contra catálogo de categorías. |

---

## 3. Exactitud

| Regla | Conjunto de Datos | Resultado Medido | Decisión Tomada |
|---|---|---|---|
| Oferta de grado y posgrado coincide con portal oficial EPN | `stg_oferta` | ✅ 46 programas verificados contra el portal `epn.edu.ec/carreras` y `posgrados`. | Scraper extrae directamente las etiquetas `h3` y enlaces canónicos. |
| Identificación de cargos de autoridades | `stg_autoridades` | ✅ 10 autoridades: 7 Decanos, 3 Rectores/Vicerrectores. | Coincide con la estructura directiva expuesta en el portal EPN. |
| Clasificación de categorías desde origen oficial | `stg_publicaciones` | ✅ 100 % con `categoria_origen = "wordpress"`. | Se priorizó el endpoint de taxonomías oficiales `/wp-json/wp/v2/categories`. |

---

## 4. Consistencia

| Regla | Conjunto de Datos | Resultado Medido | Decisión Tomada |
|---|---|---|---|
| Comparaciones insensibles a tildes (`remove_accents()`) | Todas las tablas `stg` | ✅ 100 % — normalización Unicode NFKD aplicada en helpers y scrapers. | Unifica variantes como "Computación" y "Computacion". |
| `cargo_normalizado` cerrado | `stg_autoridades` | ✅ 100 % mapeado al catálogo (7 Decano, 3 Rector). | Previene discrepancias semánticas en consultas analíticas. |
| `condicion_designacion` cerrado | `stg_autoridades` | ✅ 100 % mapeado: 8 'no_determinado', 2 'encargado'. | Sólo se asignó 'encargado' cuando el texto contenía la evidencia explícita `"(e)"`. Sin presunciones de titularidad. |
| `institucion_id` coherente entre tablas | Todas las tablas `stg` | ✅ 100 % registros tienen `institucion_id = 'EPN'`. | Garantiza integridad relacional para cruces futuros. |

---

## 5. Unicidad

| Regla | Conjunto de Datos | Resultado Medido | Decisión Tomada |
|---|---|---|---|
| `hash_registro` único por tabla en primera ejecución | Todas las tablas `stg` | ✅ 100 % de unicidad física: `stg_facultades` (9/9), `stg_oferta` (46/46), `stg_autoridades` (10/10), `stg_institucional` (28/28), `stg_publicaciones` (194/194). | Hash determinista SHA-256 de 20 caracteres sobre contenido de negocio. |
| Carga idempotente en segunda ejecución | Todas las tablas `stg` | ✅ 0 registros insertados en 2da corrida; 100 % de registros omitidos por duplicado. | `StagingLoader.load_raw_table()` verifica existencia de hash antes de insertar. |
| Clave lógica de publicaciones `(institucion_id, post_id)` | `stg_publicaciones` | ✅ 194 IDs distintos para 'EPN'. | Clave natural respeta unicidad del CMS de origen. |

---

## 6. Oportunidad

| Regla | Conjunto de Datos | Resultado Medido | Decisión Tomada |
|---|---|---|---|
| Publicaciones estrictamente en ventana 2024-2025 (P3) | `stg_publicaciones` | ✅ 194/194 publicaciones dentro del período: 70 en 2024, 124 en 2025. 0 registros fuera de rango. | Parámetros `after=2024-01-01T00:00:00` y `before=2025-12-31T23:59:59` filtrados en API de WordPress. |
| Distribución temporal por trimestre (P3) | `stg_publicaciones` | • 2024-T3: 40<br>• 2024-T4: 30<br>• 2025-T1: 12<br>• 2025-T2: 15<br>• 2025-T3: 17<br>• 2025-T4: 80 | Datos suficientes y distribuidos en 6 trimestres para análisis de tendencias de publicaciones. |
| Respeto del límite `max_paginas` | `stg_publicaciones` | ✅ Con `--max-paginas 2`, la API recuperó 200 ítems teóricos y 194 registros deduplicados sin saturar el servidor. | Rate limit mínimo de 1.0 s respetado en todas las peticiones. |
| Trazabilidad temporal | Todas las tablas `stg` | ✅ 100 % de registros con timestamp de extracción exacto en formato ISO UTC. | Auditable por lote de ejecución (`run_id`). |

---

## Decisiones de Diseño y Limitaciones Reales

1. **Retiro definitivo de datos sintéticos de SNIESE:**  
   Se eliminó la carga automática de diccionarios hardcodeados. El scraper retorna 0 registros cuando no existe el archivo físico `data/raw/sniese_oferta_academica.csv`. Esto transparenta el estado real del proyecto frente a la cátedra.
2. **Limitación de acceso a catastro abierto:**  
   El endpoint público de `datosabiertos.gob.ec/dataset/oferta-academica-ies` reporta HTTP 404 (eliminado o reestructurado por el portal de gobierno), y la plataforma del CES (`appcmi.ces.gob.ec`) requiere navegación mediante formulario interactivo PHP sin URL estática de descarga.
3. **Incompatibilidad CMS de la USFQ:**  
   La Universidad San Francisco de Quito utiliza Drupal (`/core/*.css`) y no WordPress, por lo que el adaptador `/wp-json/` retorna HTTP 404. Su estado real es **"configurada, no consultada"**.
4. **Disponibilidad temporal en ESPE:**  
   La Universidad de las Fuerzas Armadas (ESPE) tiene API de WordPress activa, pero su paginación pública expone únicamente publicaciones del año 2026, retornando 0 registros para la ventana analítica 2024-2025.


## Actualización posterior de fuentes

El 2026-11-22 se incorporaron URLs oficiales entregadas por el equipo y se regeneró
`docs/secciones_fuentes_pendientes.csv`. La matriz distingue ahora fuentes sin URL
de fuentes localizadas que requieren validar acceso, cobertura o extracción. Esta
revisión cambió la configuración; no ejecutó un nuevo scraping. Los archivos crudos
y los indicadores de calidad de la última corrida siguen describiendo la captura
anterior hasta que se ejecute `python -m src.main --hito2`.
