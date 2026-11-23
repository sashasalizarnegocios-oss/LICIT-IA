CREATE TABLE IF NOT EXISTS convocatorias (
    origen TEXT NOT NULL CHECK (origen IN ('demo', 'oece')),
    ocid TEXT NOT NULL,
    titulo TEXT NOT NULL,
    entidad TEXT,
    region TEXT,
    objeto TEXT,
    estado TEXT,
    fecha TEXT,
    cierre TEXT,
    descripcion TEXT,
    referencia REAL,
    moneda TEXT,
    enlace TEXT,
    actualizado TEXT NOT NULL,
    PRIMARY KEY (origen, ocid)
);
CREATE TABLE IF NOT EXISTS adjudicaciones (
    origen TEXT NOT NULL,
    ocid TEXT NOT NULL,
    award_id TEXT NOT NULL,
    proveedores TEXT,
    estado TEXT,
    monto REAL,
    moneda TEXT,
    fecha TEXT,
    enlace TEXT,
    PRIMARY KEY (origen, ocid, award_id),
    FOREIGN KEY (origen, ocid) REFERENCES convocatorias (origen, ocid)
);
CREATE INDEX IF NOT EXISTS convocatorias_filtros
    ON convocatorias (origen, objeto, region, estado);

CREATE TABLE IF NOT EXISTS solicitudes (
 codigo TEXT PRIMARY KEY, correo TEXT NOT NULL, frecuencia TEXT NOT NULL,
 origen TEXT NOT NULL, filtros TEXT NOT NULL, creada TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS suscripciones (
 token TEXT PRIMARY KEY, correo TEXT NOT NULL, frecuencia TEXT NOT NULL,
 origen TEXT NOT NULL, filtros TEXT NOT NULL, proxima TEXT NOT NULL,
 UNIQUE(correo, origen, filtros)
);
CREATE INDEX IF NOT EXISTS suscripciones_proxima ON suscripciones(proxima);
