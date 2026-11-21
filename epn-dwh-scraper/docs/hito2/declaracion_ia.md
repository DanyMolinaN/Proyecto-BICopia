# Declaración de Uso de Inteligencia Artificial — Hito 2

**Proyecto:** Business Intelligence (ISWD743) — Sector Universidades (Equipo 6, FIS-EPN)  
**Entrega:** Hito 2 — Adquisición y Calidad de Datos  
**Fecha:** 2026-11-21  
**Marco de referencia:** Guía oficial del proyecto integrador (Sección 10: Ética y Uso de Datos)

---

## 1. Declaración Obligatoria

En estricto cumplimiento con las normas éticas del curso y la política de integridad académica de la Escuela Politécnica Nacional, se declara que para el desarrollo y auditoría técnica del Hito 2 se utilizaron herramientas de Inteligencia Artificial asistida para programación, auditoría de código y diseño arquitectónico bajo supervisión directa del equipo de estudiantes.

El equipo humano asume plena y total responsabilidad por cada línea de código, script SQL, prueba unitaria, análisis de calidad y decisión metodológica documentada en este repositorio.

---

## 2. Herramientas de IA Empleadas

| Herramienta / Modelo | Ámbito de Uso | Modo de Interacción |
|---|---|---|
| **Claude Sonnet 4.6 / Gemini 3.8 Flash** | Asistencia en refactorización arquitectónica, redacción de DDLs PostgreSQL, diseño y ejecución de 60 pruebas unitarias automatizadas, generación de scripts de entregables reproducibles y redacción técnica de reportes de calidad. | Agente de ingeniería y auditoría de software con ejecución de comandos en entorno local. |

---

## 3. Registro de Tareas Asistidas y Decisiones de Auditoría

### 3.1. Qué se solicitó a la IA
1. **Auditoría metodológica de prototipo Hito 1 a Hito 2:** Detección de brechas frente a las preguntas de negocio P1, P2 y P3 (ausencia de paginación en WordPress REST API, suposición infundada de titularidad en autoridades, falta de normalización de cargos, ausencia de esquemas DDL estándar).
2. **Diseño de DDLs de Staging (`sql/stg/*.sql`):** Generación de esquemas PostgreSQL con tipos nativos, hashes SHA-256 de idempotencia (`hash_registro`), linaje (`run_id`, `institucion_id`, `fecha_extraccion`) y restricciones de integridad.
3. **Módulo Multi-institución:** Creación de `config/instituciones.yaml`, `src/instituciones.py` y configuración de adaptadores piloto (`ESPE`, `USFQ`).
4. **Cargador idempotente (`StagingLoader`):** Sustitución del método destructivo `if_exists="replace"` por inserción incremental verificando hashes existentes.
5. **Generador reproducible de entregables (`scripts/generar_entregables.py`):** Automatización de la creación de `inventario_fuentes.xlsx`, `diccionario_datos.xlsx` y `matriz_cobertura.xlsx` a partir de metadatos del código.
6. **Auditoría de integridad de datos y segunda fuente:** Inspección de `src/scrapers/sniese_scraper.py`, detección de listas de referencia embebidas y desmantelamiento de su inserción en staging para erradicar cualquier dato sintético.

---

## 4. Métodos de Verificación y Validación Humana

Ningún código ni resultado generado por IA fue aceptado de forma pasiva; se aplicaron estrictos filtros de verificación técnica:

1. **Ejecución y suite de pruebas unitarias (`pytest`):**
   - Ejecución completa de la suite alcanzando **60 pruebas unitarias pasando al 100%** en 2.05 s.
   - 12 pruebas de limpieza (`test_cleaning.py`), 40 de mejoras de arquitectura y adaptadores (`test_improvements.py`), 3 de scrapers (`test_scrapers.py`) y 5 de validación de esquemas (`test_validation.py`).
2. **Verificación de ejecución real controlada:**
   - Ejecución real del pipeline contra el portal EPN con parámetros controlados (`--max-paginas 2 --target stg`).
   - Verificación de inserción en SQLite (`data/epn_dwh.db`): 9 facultades, 46 carreras, 10 autoridades, 28 páginas institucionales y 194 noticias reales del período 2024-2025.
   - Demostración de idempotencia: segunda corrida inmediata resultó en **0 inserciones nuevas y 287 registros duplicados omitidos**.
3. **Auditoría ética de scraping y políticas de red:**
   - Verificación en código de retardo mínimo de 1.0 s por petición (`time.sleep(1.0)`).
   - Verificación de `robots.txt` para EPN, ESPE y USFQ antes de cualquier solicitud.
   - Confirmación de User-Agent con identificación académica transparente.
   - No evasión de captchas, proxies ni mecanismos de seguridad.
4. **Eliminación de datos sintéticos y sinceramiento de limitaciones:**
   - La IA propuso inicialmente usar catálogos de referencia embebidos para SNIESE. La auditoría rechazó esta práctica: el código fue modificado para retornar 0 registros si no existe el archivo CSV descargado, marcando el criterio formalmente como **NO CUMPLIDO**.
   - Se documentó que la USFQ no usa WordPress (utiliza Drupal) y que la ESPE expone sólo noticias de 2026 en su API pública, dejándolas en estado verificado **"configurada, no consultada"**.
