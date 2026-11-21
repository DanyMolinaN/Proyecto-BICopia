-- ============================================================================
-- TABLA: stg.stg_publicaciones
-- Pregunta de Negocio 3: Comunicacion Institucional (Publicaciones 2024-2025)
-- Contiene las noticias, comunicados y convocatorias crudas extraidas de WP API / Web.
-- ============================================================================

CREATE TABLE IF NOT EXISTS stg.stg_publicaciones (
    stg_id BIGSERIAL PRIMARY KEY,
    
    -- Metadatos de trazabilidad y linaje de datos
    run_id VARCHAR(64) NOT NULL,
    fecha_carga TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    institucion_id VARCHAR(32) NOT NULL,
    fuente_url TEXT,
    fecha_extraccion VARCHAR(32),
    hash_registro VARCHAR(64) NOT NULL,
    
    -- Atributos de comunicados y noticias (crudos)
    post_id TEXT,
    fecha_publicacion TEXT,
    fecha_modificacion TEXT,
    titulo TEXT,
    categoria TEXT,
    categoria_origen TEXT,
    tipo_publicacion TEXT,
    tipo_origen TEXT,
    resumen TEXT,
    url TEXT,

    CONSTRAINT uq_stg_publicaciones_run_hash UNIQUE (run_id, hash_registro)
);

CREATE INDEX IF NOT EXISTS idx_stg_publicaciones_inst ON stg.stg_publicaciones(institucion_id);
CREATE INDEX IF NOT EXISTS idx_stg_publicaciones_fecha ON stg.stg_publicaciones(fecha_publicacion);
CREATE INDEX IF NOT EXISTS idx_stg_publicaciones_hash ON stg.stg_publicaciones(hash_registro);
