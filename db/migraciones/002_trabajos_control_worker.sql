-- Migración 002: columnas para que varios workers trabajen sin pisarse y con reintentos limitados.
-- Idempotente.
ALTER TABLE trabajos ADD COLUMN IF NOT EXISTS worker           TEXT;
ALTER TABLE trabajos ADD COLUMN IF NOT EXISTS latido           TIMESTAMPTZ;
ALTER TABLE trabajos ADD COLUMN IF NOT EXISTS disponible_desde TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE trabajos ADD COLUMN IF NOT EXISTS reprocesos       INTEGER     NOT NULL DEFAULT 0;
ALTER TABLE trabajos ADD COLUMN IF NOT EXISTS confidencial     BOOLEAN     NOT NULL DEFAULT FALSE;
