-- ============================================================================
-- TABLA: stg.stg_ies_ces
-- Fuente Oficial Uniforme: Fichas institucionales de las 64 IES del CES
-- Segunda fuente real del Hito 2
-- ============================================================================

CREATE TABLE IF NOT EXISTS stg.stg_ies_ces (
    stg_id BIGSERIAL PRIMARY KEY,

    -- Metadatos de trazabilidad obligatorios
    run_id VARCHAR(64) NOT NULL,
    fecha_carga TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    institucion_id VARCHAR(32) NOT NULL,
    fuente_url TEXT,
    fecha_extraccion VARCHAR(32),
    hash_registro VARCHAR(64) NOT NULL,

    -- Campos oficiales del catálogo y ficha CES
    ces_cod VARCHAR(16),
    ces_codp VARCHAR(16),
    tipo_ces VARCHAR(64),
    nombre_catalogo TEXT,
    provincia_catalogo TEXT,
    canton_catalogo TEXT,
    ces_url TEXT,
    nombre_ces TEXT,
    sede TEXT,
    siglas_ces TEXT,
    direccion TEXT,
    fecha_creacion TEXT,
    tipo_institucional_ces TEXT,
    rector_nombre TEXT,
    cargo_rector_original TEXT,
    fecha_inicio_gestion TEXT,
    fecha_fin_gestion TEXT,
    discrepancia_nombre BOOLEAN,
    estado_extraccion VARCHAR(32),
    motivo_error TEXT,

    CONSTRAINT uq_stg_ies_ces_run_hash UNIQUE (run_id, hash_registro)
);

CREATE INDEX IF NOT EXISTS idx_stg_ies_ces_inst ON stg.stg_ies_ces(institucion_id);
CREATE INDEX IF NOT EXISTS idx_stg_ies_ces_cod ON stg.stg_ies_ces(ces_cod);
