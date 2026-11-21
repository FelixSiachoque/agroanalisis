-- Migración 001: más contexto en la auditoría (rol, recurso, resultado, origen) e índices para filtrar.
-- Idempotente: se puede ejecutar varias veces sin error ni duplicados.
ALTER TABLE auditoria ADD COLUMN IF NOT EXISTS rol       VARCHAR(20);
ALTER TABLE auditoria ADD COLUMN IF NOT EXISTS recurso   VARCHAR(100);
ALTER TABLE auditoria ADD COLUMN IF NOT EXISTS resultado VARCHAR(10) NOT NULL DEFAULT 'permitido'
    CHECK (resultado IN ('permitido', 'denegado', 'error'));
ALTER TABLE auditoria ADD COLUMN IF NOT EXISTS origen    VARCHAR(10) NOT NULL DEFAULT 'app';

CREATE INDEX IF NOT EXISTS idx_auditoria_usuario_fecha ON auditoria(usuario, fecha);
CREATE INDEX IF NOT EXISTS idx_auditoria_accion_fecha ON auditoria(accion, fecha);
CREATE INDEX IF NOT EXISTS idx_auditoria_denegados ON auditoria(resultado) WHERE resultado = 'denegado';

-- Eventos viejos: los del worker y del CLI se marcan con su origen real.
UPDATE auditoria SET origen = 'worker' WHERE origen = 'app' AND usuario LIKE 'worker@%';
UPDATE auditoria SET origen = 'cli'    WHERE origen = 'app' AND usuario IN ('cli', 'sistema');
UPDATE auditoria SET resultado = 'denegado'
 WHERE resultado = 'permitido' AND accion IN ('acceso_denegado', 'login_fallido', 'cuota_excedida', 'archivo_rechazado');
