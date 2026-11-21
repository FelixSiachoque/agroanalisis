-- COPIA CONGELADA del esquema original (el que ya está en el servidor de AWS antes de las migraciones).
-- La usa pruebas/test_esquema.sh. NO editar.
-- Esquema de AgroAnálisis Sugamuxi
-- Postgres ejecuta este archivo automáticamente SOLO la primera vez que se crea el volumen db_data.

CREATE TABLE IF NOT EXISTS usuarios (
    id          SERIAL PRIMARY KEY,
    usuario     VARCHAR(50)  UNIQUE NOT NULL,
    clave_hash  TEXT         NOT NULL,              -- hash scrypt (werkzeug), nunca texto plano
    rol         VARCHAR(20)  NOT NULL CHECK (rol IN ('admin', 'operador', 'usuario')),
    activo      BOOLEAN      NOT NULL DEFAULT TRUE,
    creado      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trabajos (
    id              SERIAL PRIMARY KEY,
    usuario_id      INTEGER      NOT NULL REFERENCES usuarios(id),
    nombre_original TEXT         NOT NULL,
    ruta_archivo    TEXT         NOT NULL,
    tipo            VARCHAR(10)  NOT NULL,           -- txt | csv
    tamano_bytes    INTEGER      NOT NULL,
    estado          VARCHAR(20)  NOT NULL DEFAULT 'pendiente'
                    CHECK (estado IN ('pendiente', 'en_ejecucion', 'completado', 'fallido')),
    ruta_resultado  TEXT,
    error           TEXT,
    intentos        INTEGER      NOT NULL DEFAULT 0,
    creado          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    iniciado        TIMESTAMPTZ,
    terminado       TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_trabajos_estado  ON trabajos(estado);
CREATE INDEX IF NOT EXISTS idx_trabajos_usuario ON trabajos(usuario_id);

-- Auditoría: quién hizo qué y cuándo. No tiene llave foránea a propósito:
-- si se borra un usuario o un trabajo, su rastro se conserva.
CREATE TABLE IF NOT EXISTS auditoria (
    id       BIGSERIAL    PRIMARY KEY,
    fecha    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    usuario  VARCHAR(50)  NOT NULL,
    accion   VARCHAR(50)  NOT NULL,
    detalle  TEXT,
    ip       VARCHAR(45)
);
CREATE INDEX IF NOT EXISTS idx_auditoria_fecha ON auditoria(fecha);
