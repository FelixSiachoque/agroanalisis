-- Esquema de AgroAnálisis Sugamuxi (versión final, instalación desde cero)
-- Postgres ejecuta este archivo automáticamente SOLO la primera vez que se crea el volumen db_data.
--
-- IMPORTANTE: si cambia algo aquí, haga el MISMO cambio como migración en db/migraciones/
-- (para el servidor de AWS, que ya tiene datos). La prueba pruebas/test_esquema.sh compara
-- "init.sql desde cero" contra "esquema anterior + migraciones" y falla si no son iguales.
-- Por eso las columnas nuevas van AL FINAL de cada tabla, en el mismo orden que en las migraciones.
--
-- Los permisos de los usuarios de base de datos (agro_web, agro_worker) están en db/roles.sql.

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
    intentos        INTEGER      NOT NULL DEFAULT 0,  -- veces que un worker lo tomó
    creado          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    iniciado        TIMESTAMPTZ,
    terminado       TIMESTAMPTZ,
    -- migración 002: control del worker
    worker          TEXT,                             -- qué worker lo está procesando
    latido          TIMESTAMPTZ,                      -- última señal de vida del worker en este trabajo
    disponible_desde TIMESTAMPTZ NOT NULL DEFAULT now(), -- espera antes de reintentar (backoff)
    reprocesos      INTEGER      NOT NULL DEFAULT 0,  -- veces que un operador lo reenvió a la cola
    confidencial    BOOLEAN      NOT NULL DEFAULT FALSE -- usado por la regla 'trabajos_confidenciales'
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
    ip       VARCHAR(45),
    -- migración 001: más contexto en cada evento
    rol       VARCHAR(20),                            -- rol del usuario en ese momento
    recurso   VARCHAR(100),                           -- sobre qué se actuó (ej. trabajo:15, usuario:3)
    resultado VARCHAR(10) NOT NULL DEFAULT 'permitido'
              CHECK (resultado IN ('permitido', 'denegado', 'error')),
    origen    VARCHAR(10) NOT NULL DEFAULT 'app'      -- app | worker | cli | sistema
);
CREATE INDEX IF NOT EXISTS idx_auditoria_fecha ON auditoria(fecha);
CREATE INDEX IF NOT EXISTS idx_auditoria_usuario_fecha ON auditoria(usuario, fecha);
CREATE INDEX IF NOT EXISTS idx_auditoria_accion_fecha ON auditoria(accion, fecha);
CREATE INDEX IF NOT EXISTS idx_auditoria_denegados ON auditoria(resultado) WHERE resultado = 'denegado';

-- migración 003: latido (heartbeat) de cada worker, para el panel de Recursos y la recuperación segura
CREATE TABLE IF NOT EXISTS workers (
    nombre          TEXT PRIMARY KEY,                 -- worker@<hostname del contenedor>
    pid             INTEGER,
    iniciado        TIMESTAMPTZ NOT NULL DEFAULT now(),
    ultimo_latido   TIMESTAMPTZ NOT NULL DEFAULT now(),
    estado          VARCHAR(20) NOT NULL DEFAULT 'activo',  -- activo | detenido
    trabajo_actual  INTEGER,
    procesados      INTEGER NOT NULL DEFAULT 0,
    memoria_bytes   BIGINT,                           -- leído de /sys/fs/cgroup/memory.current
    memoria_max     BIGINT,                           -- leído de /sys/fs/cgroup/memory.max (NULL = sin límite)
    cpu_limite      NUMERIC(6,2),                     -- CPUs, de /sys/fs/cgroup/cpu.max
    cpu_uso_usec    BIGINT,                           -- de /sys/fs/cgroup/cpu.stat
    pids            INTEGER                           -- de /sys/fs/cgroup/pids.current
);
