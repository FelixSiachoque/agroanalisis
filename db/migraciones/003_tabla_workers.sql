-- Migración 003: latido (heartbeat) de cada worker. Idempotente.
CREATE TABLE IF NOT EXISTS workers (
    nombre          TEXT PRIMARY KEY,
    pid             INTEGER,
    iniciado        TIMESTAMPTZ NOT NULL DEFAULT now(),
    ultimo_latido   TIMESTAMPTZ NOT NULL DEFAULT now(),
    estado          VARCHAR(20) NOT NULL DEFAULT 'activo',
    trabajo_actual  INTEGER,
    procesados      INTEGER NOT NULL DEFAULT 0,
    memoria_bytes   BIGINT,
    memoria_max     BIGINT,
    cpu_limite      NUMERIC(6,2),
    cpu_uso_usec    BIGINT,
    pids            INTEGER
);
