-- ============================================================================
-- TABLA: stg.stg_autoridades
-- Pregunta de Negocio 2: Autoridades Universitarias 2026
-- Contiene los registros crudos extraidos de los portales de autoridades y decanatos.
-- ============================================================================

CREATE TABLE IF NOT EXISTS stg.stg_autoridades (
    stg_id BIGSERIAL PRIMARY KEY,
    
    -- Metadatos de trazabilidad y linaje de datos
    run_id VARCHAR(64) NOT NULL,
    fecha_carga TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    institucion_id VARCHAR(32) NOT NULL,
    fuente_url TEXT,
    fecha_extraccion VARCHAR(32),
    hash_registro VARCHAR(64) NOT NULL,
    
    -- Atributos de autoridades universitarias (crudos)
    nombre_completo TEXT,
    titulo_academico TEXT,
    cargo TEXT,
    cargo_original TEXT,
    cargo_normalizado TEXT,
    tipo_cargo TEXT,
    unidad_adscripcion TEXT,
    condicion_designacion TEXT,
    evidencia_condicion TEXT,
    es_titular INTEGER,
    periodo_gestion TEXT,
    correo_contacto TEXT,
    biografia TEXT,
    fecha_observacion TEXT,

    CONSTRAINT uq_stg_autoridades_run_hash UNIQUE (run_id, hash_registro)
);

CREATE INDEX IF NOT EXISTS idx_stg_autoridades_inst ON stg.stg_autoridades(institucion_id);
CREATE INDEX IF NOT EXISTS idx_stg_autoridades_hash ON stg.stg_autoridades(hash_registro);
