-- ============================================================================
-- TABLA: stg.stg_oferta
-- Pregunta de Negocio 1: Oferta Academica Vigente 2026
-- Contiene los registros crudos extraidos de los portales de oferta de grado y posgrado.
-- ============================================================================

CREATE TABLE IF NOT EXISTS stg.stg_oferta (
    stg_id BIGSERIAL PRIMARY KEY,
    
    -- Metadatos de trazabilidad y linaje de datos
    run_id VARCHAR(64) NOT NULL,
    fecha_carga TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    institucion_id VARCHAR(32) NOT NULL,
    fuente_url TEXT,
    fecha_extraccion VARCHAR(32),
    hash_registro VARCHAR(64) NOT NULL,
    
    -- Atributos de oferta academica (crudos)
    nombre TEXT,
    facultad_nombre TEXT,
    nivel TEXT,
    nivel_detalle TEXT,
    nivel_macro TEXT,
    modalidad TEXT,
    financiamiento TEXT,
    estado_programa TEXT,
    evidencia_estado TEXT,
    anio_referencia INTEGER DEFAULT 2026,
    duracion_periodos TEXT,
    duracion_anios TEXT,
    creditos TEXT,
    titulo_otorga TEXT,
    codigo_resolucion TEXT,
    perfil_ingreso TEXT,
    perfil_egreso TEXT,
    campo_ocupacional TEXT,
    malla_curricular_url TEXT,
    url TEXT,
    campos_inferidos TEXT,

    CONSTRAINT uq_stg_oferta_run_hash UNIQUE (run_id, hash_registro)
);

CREATE INDEX IF NOT EXISTS idx_stg_oferta_inst ON stg.stg_oferta(institucion_id);
CREATE INDEX IF NOT EXISTS idx_stg_oferta_hash ON stg.stg_oferta(hash_registro);
