-- ============================================================================
-- TABLA: stg.stg_oferta_sniese
-- Segunda Fuente: Catastro Oficial SNIESE / SENESCYT / CES
-- Contiene los registros de oferta academica provenientes de datos abiertos oficiales.
-- ============================================================================

CREATE TABLE IF NOT EXISTS stg.stg_oferta_sniese (
    stg_id BIGSERIAL PRIMARY KEY,
    
    -- Metadatos de trazabilidad y linaje de datos
    run_id VARCHAR(64) NOT NULL,
    fecha_carga TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    institucion_id VARCHAR(32) NOT NULL,
    fuente_url TEXT,
    fecha_extraccion VARCHAR(32),
    hash_registro VARCHAR(64) NOT NULL,
    
    -- Atributos oficiales SNIESE / CES (crudos)
    institucion_nombre TEXT,
    carrera_programa TEXT,
    nivel_formacion TEXT,
    nivel_detalle TEXT,
    modalidad TEXT,
    resolucion_ces TEXT,
    estado_vigencia TEXT,
    campo_amplio TEXT,
    fuente_organismo TEXT,
    anio_referencia INTEGER DEFAULT 2026,

    CONSTRAINT uq_stg_sniese_run_hash UNIQUE (run_id, hash_registro)
);

CREATE INDEX IF NOT EXISTS idx_stg_sniese_inst ON stg.stg_oferta_sniese(institucion_id);
CREATE INDEX IF NOT EXISTS idx_stg_sniese_hash ON stg.stg_oferta_sniese(hash_registro);
