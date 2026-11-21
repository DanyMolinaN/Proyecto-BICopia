-- ============================================================================
-- TABLA: stg.stg_ejecucion_institucion
-- Trazabilidad de ejecución multi-institución por módulo (Fase 7)
-- ============================================================================

CREATE TABLE IF NOT EXISTS stg.stg_ejecucion_institucion (
    stg_id BIGSERIAL PRIMARY KEY,

    run_id VARCHAR(64) NOT NULL,
    institucion_id VARCHAR(32) NOT NULL,
    modulo VARCHAR(32) NOT NULL,
    estado VARCHAR(32) NOT NULL,
    registros_extraidos INTEGER DEFAULT 0,
    paginas_consultadas INTEGER DEFAULT 0,
    inicio VARCHAR(32),
    fin VARCHAR(32),
    mensaje TEXT,
    fecha_carga TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_stg_ejecucion_inst_run_mod UNIQUE (run_id, institucion_id, modulo)
);

CREATE INDEX IF NOT EXISTS idx_stg_ejecucion_run ON stg.stg_ejecucion_institucion(run_id);
CREATE INDEX IF NOT EXISTS idx_stg_ejecucion_inst ON stg.stg_ejecucion_institucion(institucion_id);
