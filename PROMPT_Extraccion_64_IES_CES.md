# PROMPT: EXTRACCIÓN DE LAS 64 UNIVERSIDADES Y ESCUELAS POLITÉCNICAS DEL CES (SIN DAÑAR EL PROYECTO)

Instrucciones para un agente de código (por ejemplo Claude Code) que trabaja dentro del repositorio del Equipo 6 (`Proyecto-BICopia`, carpeta `epn-dwh-scraper/`).

Complementa a `PROMPT_Hito2_Web_Scraping.md`. Si ese archivo existe en el repositorio, léelo primero: sus secciones 1 a 4 explican el curso, los 6 hitos, las 3 preguntas de negocio y qué exige el Hito 2. Aquí no se repiten completas.

---

## 0. ADVERTENCIAS ANTES DE EMPEZAR

1. **Este prompt se escribió sin poder abrir el repositorio `Proyecto-BICopia`** (no era accesible públicamente). Se apoya en: (a) el código del repositorio original `Proyecto-BI` (rama `main`, commit `bf5a689`), (b) el reporte que tú mismo entregaste tras las fases del Hito 2 y (c) una lectura directa de la página del CES.
2. Por eso la **Fase 0 es obligatoria**: confirma cada supuesto contra el código real antes de modificar nada. Si algo difiere, adapta el plan y repórtalo; no fuerces el código para que coincida con este documento.
3. No se verificó ningún portal universitario. Todas las URLs de portales deben **descubrirse y validarse** en la Fase 3 con evidencia.

---

## 1. ROL Y OBJETIVO

Actúa como ingeniero de datos senior (web scraping, ETL, PostgreSQL, calidad de datos) con criterio de auditor.

**Objetivo:** ampliar el scraper, que hoy funciona para la EPN, para que obtenga los datos de P1, P2 y P3 de las **64 IES del catálogo del CES** (sección 4), de forma **gradual, medible, respetuosa con los sitios y sin romper lo que ya funciona**, y dejar los entregables del Hito 2 con cifras reales.

Principio rector: **la cobertura se mide, no se supone.** Si una institución no se puede extraer, queda registrada como tal. Jamás se rellena con datos inventados o embebidos.

---

## 2. LAS TRES PREGUNTAS (RESUMEN; NO SE SUSTITUYEN)

| Pregunta | Qué necesita | Campos clave |
|---|---|---|
| P1 Oferta académica 2026 | Distribución de programas vigentes de grado y posgrado por nivel, modalidad y financiamiento | universidad, programa, nivel, modalidad, financiamiento, estado, año de referencia, URL |
| P2 Autoridades 2026 | Rectores y decanos por cargo, institución y condición (titular o encargado) | universidad, autoridad, cargo, facultad, condición de designación, fecha de observación, URL |
| P3 Publicaciones 2024-2025 | Evolución del volumen por categoría temática y trimestre | universidad, título, fecha de publicación, año, trimestre, categoría, tipo de publicación, URL |

Hito 2 exige: al menos 2 fuentes integrables, 3 periodos, staging PostgreSQL (`stg`) sin transformar, diccionario en Excel, notebook de perfilado ejecutado, informe de calidad con resultado medido y decisión tomada, inventario de fuentes y matriz de cobertura. **Se diagnostica la calidad; la corrección es del Hito 3.**

---

## 3. HALLAZGOS VERIFICADOS SOBRE LA FUENTE DEL CES

Se leyó la ficha de la EPN en `https://www.ces.gob.ec/?page_id=25&cod=1001&codp=328`. Datos verificados:

- La ficha muestra: tipo de IES (por ejemplo "PÚBLICA"), nombre, sede, siglas, dirección, fecha de creación, **rector/a (nombre)**, **fecha de inicio de gestión** y **fecha fin de gestión**.
- **No** muestra sitio web de la universidad ni oferta académica.
- El menú del CES confirma el significado del parámetro `codp`:
  - `codp=328` = Públicas nacionales.
  - `codp=1540` = Particulares autofinanciadas.
  - `codp=5398` = Particular cofinanciada.
- El menú del CES incluye también "Estadísticas IES" (`page_id=5248`), "Boletines Académicos" y "CES APROBÓ". **No se evaluaron**; revísalos como candidatos para P1 en la Fase 6 y reporta qué contienen.
- El sitio muestra un aviso de aceptación de la política de datos personales. Solo se consume el HTML público; no hagas clic automático en avisos ni uses sesiones.

Consecuencias de diseño:

1. Las fichas del CES son una **fuente oficial uniforme** para los 64 registros (rector, fechas de gestión, tipo). Son la **segunda fuente real** del Hito 2 y alimentan la dimensión institución con `tipo_institucional` y `financiamiento`.
2. Los decanos, las publicaciones y la oferta por programa dependen de cada portal universitario, que hay que descubrir y validar.
3. Compara siempre lo del CES con lo del portal (por ejemplo, el rector). Las discrepancias se **registran**, no se resuelven automáticamente.

---

## 4. CATÁLOGO DE LAS 64 IES

Atención: en la lista original que entregó el equipo, **el número que aparece debajo de cada institución pertenece a la institución siguiente**. El identificador válido de cada IES es el parámetro `cod` de su URL. Usa la tabla de abajo.

Crea `config/catalogo_ces.csv` exactamente con estos datos (UTF-8). La URL del CES se construye como `https://www.ces.gob.ec/?page_id=25&cod={ces_cod}&codp={ces_codp}`.

```csv
ces_cod,ces_codp,tipo_ces,nombre,provincia,canton
1001,328,publica,ESCUELA POLITÉCNICA NACIONAL,PICHINCHA,DISTRITO METROPOLITANO DE QUITO
1003,328,publica,ESCUELA SUPERIOR POLITÉCNICA AGROPECUARIA DE MANABÍ MANUEL FÉLIX LÓPEZ - ESPAM MFL,MANABÍ,BOLÍVAR
1002,328,publica,ESCUELA SUPERIOR POLITÉCNICA DE CHIMBORAZO,CHIMBORAZO,RIOBAMBA
1021,328,publica,ESCUELA SUPERIOR POLITÉCNICA DEL LITORAL (ESPOL),GUAYAS,GUAYAQUIL
1026,328,publica,"FACULTAD LATINOAMERICANA DE CIENCIAS SOCIALES, FLACSO",PICHINCHA,DISTRITO METROPOLITANO DE QUITO
1057,328,publica,INSTITUTO DE ALTOS ESTUDIOS NACIONALES - IAEN,PICHINCHA,DISTRITO METROPOLITANO DE QUITO
1018,328,publica,UNIVERSIDAD AGRARIA DEL ECUADOR,GUAYAS,GUAYAQUIL
1022,328,publica,UNIVERSIDAD ANDINA SIMÓN BOLÍVAR,PICHINCHA,DISTRITO METROPOLITANO DE QUITO
1005,328,publica,UNIVERSIDAD CENTRAL DEL ECUADOR,PICHINCHA,DISTRITO METROPOLITANO DE QUITO
1007,328,publica,UNIVERSIDAD DE CUENCA,AZUAY,CUENCA
1006,328,publica,UNIVERSIDAD DE GUAYAQUIL,GUAYAS,GUAYAQUIL
1081,328,publica,UNIVERSIDAD DE INVESTIGACIÓN DE TECNOLOGÍA EXPERIMENTAL YACHAY,IMBABURA,SAN MIGUEL DE URCUQUÍ
1082,328,publica,UNIVERSIDAD DE LAS ARTES (UARTES),GUAYAS,GUAYAQUIL
1079,328,publica,UNIVERSIDAD DE LAS FUERZAS ARMADAS-ESPE,PICHINCHA,RUMIÑAHUI
3068,328,publica,UNIVERSIDAD DE SEGURIDAD CIUDADANA Y CIENCIAS POLICIALES - USECIPOL,PICHINCHA,DISTRITO METROPOLITANO DE QUITO
1058,328,publica,UNIVERSIDAD ESTATAL AMAZÓNICA,PASTAZA,PASTAZA
1017,328,publica,UNIVERSIDAD ESTATAL DE BOLÍVAR,BOLÍVAR,GUARANDA
1024,328,publica,UNIVERSIDAD ESTATAL DE MILAGRO,GUAYAS,MILAGRO
1025,328,publica,UNIVERSIDAD ESTATAL DEL SUR DE MANABÍ,MANABÍ,JIPIJAPA
1023,328,publica,UNIVERSIDAD ESTATAL PENÍNSULA DE SANTA ELENA - UPSE,SANTA ELENA,LA LIBERTAD
1068,328,publica,UNIVERSIDAD INTERCULTURAL DE LAS NACIONALIDADES Y PUEBLOS INDÍGENAS AMAWTAY WASI,PICHINCHA,DISTRITO METROPOLITANO DE QUITO
1016,328,publica,"UNIVERSIDAD LAICA ""ELOY ALFARO"" DE MANABÍ",MANABÍ,MANTA
1019,328,publica,UNIVERSIDAD NACIONAL DE CHIMBORAZO,CHIMBORAZO,RIOBAMBA
1083,328,publica,UNIVERSIDAD NACIONAL DE EDUCACIÓN,CAÑAR,AZOGUES
1008,328,publica,UNIVERSIDAD NACIONAL DE LOJA,LOJA,LOJA
1074,328,publica,UNIVERSIDAD POLITÉCNICA ESTATAL DEL CARCHI,CARCHI,TULCÁN
3069,328,publica,UNIVERSIDAD PÚBLICA DE SANTO DOMINGO DE LOS TSÁCHILAS,SANTO DOMINGO DE LOS TSÁCHILAS,SANTO DOMINGO
1080,328,publica,UNIVERSIDAD REGIONAL AMAZÓNICA IKIAM,NAPO,TENA
1012,328,publica,"UNIVERSIDAD TÉCNICA ""LUIS VARGAS TORRES"" DE ESMERALDAS (UTLVTE)",ESMERALDAS,ESMERALDAS
1010,328,publica,UNIVERSIDAD TÉCNICA DE AMBATO,TUNGURAHUA,AMBATO
1013,328,publica,UNIVERSIDAD TÉCNICA DE BABAHOYO,LOS RÍOS,BABAHOYO
1020,328,publica,UNIVERSIDAD TÉCNICA DE COTOPAXI,COTOPAXI,LATACUNGA
1011,328,publica,UNIVERSIDAD TÉCNICA DE MACHALA,EL ORO,MACHALA
1009,328,publica,UNIVERSIDAD TÉCNICA DE MANABÍ,MANABÍ,PORTOVIEJO
1015,328,publica,UNIVERSIDAD TÉCNICA DEL NORTE,IMBABURA,IBARRA
1014,328,publica,UNIVERSIDAD TÉCNICA ESTATAL DE QUEVEDO,LOS RÍOS,QUEVEDO
3027,1540,particular_autofinanciada,UNIVERSIDAD BOLIVARIANA DEL ECUADOR,GUAYAS,DURÁN
1049,1540,particular_autofinanciada,UNIVERSIDAD CASA GRANDE,GUAYAS,GUAYAQUIL
1037,1540,particular_autofinanciada,UNIVERSIDAD DE ESPECIALIDADES ESPÍRITU SANTO - UEES,GUAYAS,SAMBORONDÓN
1053,1540,particular_autofinanciada,UNIVERSIDAD DE ESPECIALIDADES TURÍSTICAS,PICHINCHA,DISTRITO METROPOLITANO DE QUITO
1040,1540,particular_autofinanciada,UNIVERSIDAD DE LAS AMÉRICAS,PICHINCHA,DISTRITO METROPOLITANO DE QUITO
1070,1540,particular_autofinanciada,UNIVERSIDAD DE LOS HEMISFERIOS,PICHINCHA,DISTRITO METROPOLITANO DE QUITO
1059,1540,particular_autofinanciada,UNIVERSIDAD DE OTAVALO,IMBABURA,OTAVALO
1044,1540,particular_autofinanciada,UNIVERSIDAD DEL PACÍFICO-ESCUELA DE NEGOCIOS,GUAYAS,GUAYAQUIL
3013,1540,particular_autofinanciada,UNIVERSIDAD DEL RÍO-UDR,GUAYAS,GUAYAQUIL
1073,1540,particular_autofinanciada,UNIVERSIDAD IBEROAMERICANA DEL ECUADOR,PICHINCHA,DISTRITO METROPOLITANO DE QUITO
1041,1540,particular_autofinanciada,UNIVERSIDAD INTERNACIONAL DEL ECUADOR (UIDE),PICHINCHA,DISTRITO METROPOLITANO DE QUITO
1056,1540,particular_autofinanciada,UNIVERSIDAD METROPOLITANA,GUAYAS,GUAYAQUIL
1036,1540,particular_autofinanciada,UNIVERSIDAD PARTICULAR INTERNACIONAL SEK,PICHINCHA,DISTRITO METROPOLITANO DE QUITO
1042,1540,particular_autofinanciada,"UNIVERSIDAD REGIONAL AUTÓNOMA DE LOS ANDES ""UNIANDES""",TUNGURAHUA,AMBATO
1038,1540,particular_autofinanciada,UNIVERSIDAD SAN FRANCISCO DE QUITO USFQ,PICHINCHA,DISTRITO METROPOLITANO DE QUITO
1060,1540,particular_autofinanciada,UNIVERSIDAD SAN GREGORIO DE PORTOVIEJO,MANABÍ,PORTOVIEJO
1077,1540,particular_autofinanciada,UNIVERSIDAD TECNOLÓGICA ECOTEC,GUAYAS,SAMBORONDÓN
1050,1540,particular_autofinanciada,UNIVERSIDAD TECNOLÓGICA EMPRESARIAL DE GUAYAQUIL,GUAYAS,GUAYAQUIL
1045,1540,particular_autofinanciada,UNIVERSIDAD TECNOLÓGICA INDOAMÉRICA,TUNGURAHUA,AMBATO
1051,1540,particular_autofinanciada,UNIVERSIDAD TECNOLÓGICA ISRAEL,PICHINCHA,DISTRITO METROPOLITANO DE QUITO
1027,5398,particular_cofinanciada,PONTIFICIA UNIVERSIDAD CATÓLICA DEL ECUADOR,PICHINCHA,DISTRITO METROPOLITANO DE QUITO
1029,5398,particular_cofinanciada,UNIVERSIDAD CATÓLICA DE CUENCA,AZUAY,CUENCA
1028,5398,particular_cofinanciada,UNIVERSIDAD CATÓLICA DE SANTIAGO DE GUAYAQUIL (UCSG),GUAYAS,GUAYAQUIL
1033,5398,particular_cofinanciada,UNIVERSIDAD DEL AZUAY,AZUAY,CUENCA
1030,5398,particular_cofinanciada,UNIVERSIDAD LAICA VICENTE ROCAFUERTE DE GUAYAQUIL,GUAYAS,GUAYAQUIL
1034,5398,particular_cofinanciada,UNIVERSIDAD POLITÉCNICA SALESIANA - UPS,AZUAY,CUENCA
1031,5398,particular_cofinanciada,UNIVERSIDAD TÉCNICA PARTICULAR DE LOJA,LOJA,LOJA
1032,5398,particular_cofinanciada,UNIVERSIDAD UTE,PICHINCHA,DISTRITO METROPOLITANO DE QUITO
```

Control de integridad al crear el catálogo: 64 filas, `ces_cod` únicos, 36 públicas, 20 autofinanciadas y 8 cofinanciadas. Si no cuadra, detente y reporta.

---

## 5. REGLAS PARA NO DAÑAR EL PROYECTO (OBLIGATORIAS)

1. Trabaja en una rama nueva (`ies-ces-64`) creada desde la rama actual de trabajo. No hagas push ni merge a `main`.
2. Antes de cambiar nada: `pytest` completo en verde (el reporte previo indicaba 60 pruebas) y registro de los conteos actuales de la EPN como línea base de regresión.
3. Un commit por tarea, con `pytest` en verde antes de cada commit.
4. No elimines ni renombres módulos, funciones, pruebas o columnas existentes. Extiende. Si algo debe cambiar de contrato, mantén compatibilidad o actualiza referencias y pruebas en el mismo commit.
5. El flujo actual de la EPN (`python -m src.main --all` y sus salidas) debe seguir dando los mismos resultados cuando no se pasan banderas nuevas.
6. `HttpClient` conserva robots.txt, límite de frecuencia (mínimo 1 s por host), reintentos y backoff. **Nunca** elude autenticación, captchas, WAF, bloqueos de IP ni restricciones técnicas. Si un sitio bloquea, se registra `bloqueado` y se sigue.
7. **No inventes ni embebas datos.** Quedan prohibidos los diccionarios o listas con instituciones, programas, autoridades o noticias escritos en el código como si fueran datos extraídos. Si existen (el reporte previo menciona "datos de referencia del CES incorporados" en `SnieseExtractor`), debes localizarlos, retirarlos del flujo de staging o marcarlos claramente como referencia no fuente, y reportarlo.
8. Un dato que el portal no publica queda `NULL` o `no_determinado`, con su evidencia. Prohibidos los valores por defecto plausibles.
9. Carga de red mínima: un solo hilo por host, caché, topes de páginas por institución y ejecución por lotes (sección 8). No lances los 64 portales a la vez.
10. El fallo de una institución no detiene a las demás. Cada una termina con un estado explícito (sección 7, Fase 7).
11. Datos personales: minimización. De las autoridades se conserva nombre, cargo, unidad y URL de la fuente. No guardes correos personales, teléfonos ni fotografías.
12. No declares cobertura nacional. Se declara la que la matriz demuestre con conteos.

---

## 6. FASE 0: RECONOCIMIENTO (SOLO LECTURA)

No modifiques nada. Verifica y reporta, con comandos y salidas:

1. `git status`, `git log --oneline -10`, ramas existentes y rama actual.
2. `pytest -q` y número de pruebas por archivo.
3. Existencia y contenido de: `config/instituciones.yaml`, `src/scrapers/sniese_scraper.py`, `src/load/` (¿`StagingLoader`?), `sql/stg/`, `docker-compose.yml`, `manifest.csv`, `docs/hito2/`, `notebooks/hito2_perfilado.ipynb`.
4. Cómo se propagan hoy `institucion_id`, `run_id`, `fecha_extraccion`, `fuente_url` y `hash_registro` desde `BaseScraper` hasta `stg` y las tablas procesadas.
5. Si `NoticiasScraper` ya pagina con `page`, `after` y `before`, y si usa categorías nativas de WordPress.
6. Si las autoridades usan `condicion_designacion` con evidencia o siguen asumiendo titular.
7. En `SnieseExtractor`, qué datos vienen de archivo descargado y cuáles están incrustados en el código (regla 7).
8. Las 3 preguntas del Hito 1 frente a lo que hoy produce el pipeline: ¿qué campos faltan?

Entrega una tabla "supuesto, verificado sí/no, evidencia" y una lista de diferencias con este documento. Si hay diferencias graves, **detente y consulta** antes de seguir.

---

## 7. FASES DE IMPLEMENTACIÓN (REPORTA AL TERMINAR CADA UNA)

### Fase 1. Catálogo en la configuración

- Crea `config/catalogo_ces.csv` (sección 4) y valida su integridad.
- Extiende `config/instituciones.yaml` (o su equivalente) para que **cada una de las 64** tenga: `institucion_id` (usa `ces_cod`), `nombre`, `sigla` (solo si el CES o el portal la publican; si no, vacío), `tipo_institucional`, `financiamiento`, `provincia`, `canton`, `ces_url`, `portal_url` (vacío hasta validar), `estado_integracion` (`pendiente`, `portal_validado`, `piloto`, `habilitada`) y `observaciones`.
- La EPN mantiene su configuración funcional actual. Solo se le añaden los campos nuevos.
- Prueba: el catálogo carga, no hay `ces_cod` duplicados y la EPN sigue pasando sus pruebas.

### Fase 2. Fichas institucionales del CES (fuente oficial uniforme)

- Nuevo scraper `CesPerfilScraper` (hereda de `BaseScraper`) que, para cada fila del catálogo, descarga la ficha del CES y extrae: nombre, sede, siglas, dirección, fecha de creación, tipo, **rector/a**, `fecha_inicio_gestion`, `fecha_fin_gestion`, y la etiqueta cruda del cargo tal como aparece.
- Valida que el nombre extraído coincida con el del catálogo (normaliza tildes y mayúsculas). Las discrepancias se registran, no se corrigen.
- 64 peticiones máximo, con caché, 1 s de pausa. Registro en `manifest.csv` (url, estado HTTP, fecha de descarga, sha256, `institucion_id`, `run_id`).
- Staging: tabla `stg_ies_ces` sin transformar, con los metadatos estándar. Esta tabla es la **segunda fuente real** del Hito 2.
- Si la ficha de alguna IES cambia de estructura, ese registro queda `parcial` o `error` con el motivo; no se asume nada.

### Fase 3. Descubrimiento y validación de portales oficiales

El CES no publica el sitio web. Para cada IES:

1. Busca el portal oficial (búsqueda web con el nombre y la sigla). Acepta un candidato solo si cumple **todos** estos criterios: HTTP 200, el título o el contenido de la portada identifica a la institución, el dominio es coherente (se espera `.edu.ec`; si no lo es, justifica), y la página enlaza o menciona cargos o programas propios.
2. Registra para cada una en `config/portales_validados.csv`: `institucion_id`, `portal_url`, `metodo_descubrimiento`, `evidencia` (título de la página y fecha), `fecha_validacion`, `robots_permite` (sí/no/no_aplica), `es_wordpress` (sí/no, comprobando `/wp-json/`), `url_noticias`, `url_autoridades`, `url_oferta` (cada una solo si la encontraste y existe).
3. Si hay dudas, deja `portal_url` vacío y `estado = requiere_revision_humana`. **No adivines dominios.**
4. Lee `robots.txt` de cada portal. Si prohíbe la sección que necesitas, esa sección queda `bloqueado_robots` y no se consulta.
5. Hazlo en lotes de 10 instituciones y entrega el CSV para revisión del equipo antes de extraer contenido.

### Fase 4. P3: publicaciones 2024-2025 a escala

- Reutiliza el adaptador de noticias paginado por `page`, `after=2024-01-01` y `before=2025-12-31` para portales WordPress (`es_wordpress = sí`), con categorías nativas, `fecha_publicacion` y `fecha_modificacion` separadas, y sin fechas por defecto.
- Para portales no WordPress, un adaptador HTML **conservador**: solo se usa si la sección de noticias tiene paginación identificable y fechas parseables. Si no, `estado = sin_adaptador` (no se improvisa).
- Contenido que requiere JavaScript: `estado = js_requerido`. No lances navegadores automatizados en esta fase.
- Tope de páginas por institución y por ejecución (`--max-paginas`). Corte al llegar a publicaciones anteriores a 2024.
- Salida con `institucion_id` en cada fila y un conteo por institución, año y trimestre.

### Fase 5. P2: autoridades

- **Rector/a:** viene del CES para las 64 (Fase 2). Si el portal también lo publica, guarda ambas fuentes y marca `coincide` o `discrepa`.
- **Decanos y demás autoridades:** adaptador por portal, solo cuando `url_autoridades` fue validada. Cada registro con `cargo_original`, `cargo_normalizado` (catálogo: Rector, Vicerrector, Decano, Subdecano, Director, Otro), `facultad` (solo si el portal la indica), `fuente_url` y `fecha_observacion`.
- `condicion_designacion` ∈ {`titular`, `encargado`, `subrogante`, `no_determinado`} con `evidencia_condicion` (texto exacto del portal). Sin evidencia explícita, `no_determinado`. La fecha de gestión del CES **no** convierte a nadie en titular.
- Deduplica por `(institucion_id, nombre, cargo, unidad)` y registra los descartes.
- Reporta qué fracción de IES tiene decanos extraídos. Se espera cobertura parcial; la cifra real la da la matriz.

### Fase 6. P1: oferta académica

- Investiga y reporta (sin inventar) estas fuentes: datos abiertos de SENESCYT/SNIESE en `datosabiertos.gob.ec`, y las secciones "Estadísticas IES", "Boletines Académicos" y "CES APROBÓ" del CES. Para cada una: formato, acceso, periodicidad, licencia y si sirve para oferta vigente por institución y programa.
- Si hay un archivo descargable (CSV o XLSX), impleméntalo como extractor propio, con URL, fecha de descarga, licencia y sha256 en el manifiesto. Si requiere descarga manual, **detente** y dile al equipo exactamente qué archivo bajar y en qué ruta colocarlo.
- Campos: `institucion_id`, `programa`, `nivel` (grado o posgrado), `nivel_detalle`, `modalidad`, `financiamiento` (desde el catálogo), `estado_programa` (`vigente`, `no_vigente`, `no_determinado` con `evidencia_estado`), `anio_referencia = 2026`, `fuente_url`.
- Complemento por portal solo si `url_oferta` fue validada y el patrón de extracción es confiable. Una URL publicada **no** prueba vigencia.
- Deduplica por `(institucion_id, programa, nivel, modalidad)` y registra los descartes.

### Fase 7. Orquestación y control de ejecución

- Nuevas banderas, todas opcionales: `--institucion <ces_cod>`, `--tipo {publica, particular_autofinanciada, particular_cofinanciada}`, `--lote <n>`, `--modulo {ces, noticias, autoridades, oferta}`, `--max-paginas`, `--dry-run` y `--reanudar`.
- Tabla `ejecucion_institucion` (en staging y en CSV): `run_id`, `institucion_id`, `modulo`, `estado` ∈ {`ok`, `parcial`, `sin_seccion`, `sin_adaptador`, `bloqueado_robots`, `js_requerido`, `error_http`, `no_intentado`}, `registros_extraidos`, `paginas_consultadas`, `inicio`, `fin` y `mensaje`.
- Aislamiento: la excepción de una institución se captura, se registra y se continúa. `--reanudar` omite lo ya extraído con éxito en el mismo `run_id`.
- Un solo hilo por host. Pausa mínima de 1 s. Sin paralelismo entre peticiones al mismo dominio.

### Fase 8. Staging, calidad y entregables del Hito 2 con datos reales

- Todas las tablas `stg_*` llevan `institucion_id`, `run_id`, `fecha_carga`, `fecha_extraccion`, `fuente_url` y `hash_registro`. Carga **sin transformar**, append versionado por `run_id`, idempotente.
- Regenera, por script (no a mano): `inventario_fuentes.xlsx` (CES, SNIESE si aplica y cada portal validado), `matriz_cobertura.xlsx` (64 filas por P1/P2/P3 con "configurada", "portal validado", "consultada" y "con registros", más conteos reales), `diccionario_datos.xlsx`, el notebook `hito2_perfilado.ipynb` **ejecutado con salidas** e `informe_calidad.md` con "regla, resultado medido y decisión tomada" para las seis dimensiones.
- Cada cifra del informe sale de una consulta o celda concreta. Solo diagnóstico; no se corrige nada.
- Verifica la carga con `SELECT COUNT(*)` por tabla y `run_id`, y la idempotencia con una segunda ejecución. Si no hay PostgreSQL disponible, dilo y marca el punto "no verificado".

### Fase 9. Pruebas y documentación

- Pruebas nuevas con respuestas simuladas y fixtures reales mínimos: parseo de la ficha del CES, validación de nombre, paginación y filtro de fechas, estados por institución, aislamiento de fallos, `--reanudar`, condición de designación sin evidencia y catálogo íntegro.
- Actualiza README, `docs/modulos/` y la declaración de uso de IA (`docs/hito2/declaracion_ia.md`) con lo que realmente se hizo.

---

## 8. DESPLIEGUE POR OLAS (DETENTE Y REPORTA AL FINAL DE CADA OLA)

| Ola | Alcance | Criterio para continuar |
|---|---|---|
| 0 | Regresión de la EPN con el código nuevo | Conteos de línea base iguales o diferencias explicadas; `pytest` en verde |
| 1 | `CesPerfilScraper` sobre las 64 fichas | 64 intentos registrados; discrepancias de nombre reportadas |
| 2 | Descubrimiento de portales (lotes de 10) | CSV de portales revisado por el equipo |
| 3 | Piloto de P3, P2 y P1 en 3 instituciones con portal validado y robots permitido (EPN y dos más) | Conteos por año y trimestre; estados correctos |
| 4 | Lotes de 10 instituciones con `--max-paginas` | Matriz de cobertura actualizada tras cada lote |

No pases a la siguiente ola sin la confirmación del equipo.

---

## 9. VERIFICACIÓN Y ENTREGA

- `pytest` en verde (las existentes más las nuevas).
- La EPN produce los conteos de línea base con el flujo original.
- `matriz_cobertura.xlsx` con conteos reales para las 64 IES.
- Tabla de criterios del Hito 2 con estados Cumplido, Parcial, No cumplido o No verificado, cada uno con ruta de archivo, consulta o salida como evidencia.
- Informe final con: lo implementado, los comandos y salidas, lo que no se pudo ejecutar y por qué, las discrepancias CES frente a portales, las instituciones por estado y las tareas manuales para el equipo.
- No hagas push ni merge sin revisión del equipo.

## 10. PROHIBIDO

Inventar datos, URLs, autoridades o cobertura. Embeber datasets en el código. Adivinar dominios de portales. Eludir robots, bloqueos, autenticación o captchas. Paralelizar contra un mismo host. Extracciones masivas fuera del esquema por olas. Limpiar o corregir datos en staging. Borrar funcionalidad existente. Dar por cumplido lo que no se ejecutó y verificó.
