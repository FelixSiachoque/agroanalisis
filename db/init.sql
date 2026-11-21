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
    confidencial    BOOLEAN      NOT NULL DEFAULT FALSE, -- usado por la regla 'trabajos_confidenciales'
    -- migración 004: cadena de custodia del archivo (sello de autenticidad)
    sha256_original  TEXT,                            -- huella del archivo calculada por la app al recibirlo
    sha256_resultado TEXT                             -- huella del JSON de resultado escrito por el worker
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
    origen    VARCHAR(10) NOT NULL DEFAULT 'app',     -- app | worker | cli | sistema
    -- migración 004: cadena de hashes (los llena el trigger auditoria_encadenar, no la app)
    seq           BIGINT NOT NULL,                    -- posición en la cadena (1, 2, 3...)
    hash_anterior TEXT   NOT NULL,                    -- hash del evento anterior
    hash          TEXT   NOT NULL                     -- SHA-256 de este evento
);
CREATE INDEX IF NOT EXISTS idx_auditoria_fecha ON auditoria(fecha);
CREATE INDEX IF NOT EXISTS idx_auditoria_usuario_fecha ON auditoria(usuario, fecha);
CREATE INDEX IF NOT EXISTS idx_auditoria_accion_fecha ON auditoria(accion, fecha);
CREATE INDEX IF NOT EXISTS idx_auditoria_denegados ON auditoria(resultado) WHERE resultado = 'denegado';
CREATE UNIQUE INDEX IF NOT EXISTS idx_auditoria_seq ON auditoria(seq);

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

-- migración 004
-- ===================== SELLO DE AUTENTICIDAD: cadena de custodia de la auditoría =====================
-- Cada evento guarda el hash del evento anterior y su propio hash:
--     hash = SHA-256( seq, hash_anterior, fecha UTC, usuario, rol, accion, recurso, resultado, detalle, ip, origen )
-- Si alguien modifica o borra un evento viejo, la cadena deja de cuadrar desde ese punto
-- (lo detecta /admin/auditoria/verificar o: flask --app app verificar-cadena).
-- Lo calcula PostgreSQL (trigger), no la app: no depende del código y no hay carreras entre procesos.

-- Fila única con el último eslabón. Bloquearla serializa los INSERT simultáneos (Gunicorn x2 + worker).
CREATE TABLE IF NOT EXISTS auditoria_cabeza (
    id          BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),
    seq         BIGINT  NOT NULL,
    ultimo_hash TEXT    NOT NULL
);
INSERT INTO auditoria_cabeza (id, seq, ultimo_hash) VALUES (TRUE, 0, repeat('0', 64)) ON CONFLICT (id) DO NOTHING;

-- Hash canónico de un evento: arreglo JSON (sin ambigüedad entre campos) y fecha siempre en UTC.
CREATE OR REPLACE FUNCTION auditoria_calcular_hash(
    p_seq BIGINT, p_anterior TEXT, p_fecha TIMESTAMPTZ, p_usuario TEXT, p_rol TEXT, p_accion TEXT,
    p_recurso TEXT, p_resultado TEXT, p_detalle TEXT, p_ip TEXT, p_origen TEXT)
RETURNS TEXT LANGUAGE sql STABLE AS $$
    SELECT encode(sha256(convert_to(json_build_array(
        p_seq, p_anterior, to_char(p_fecha AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
        p_usuario, p_rol, p_accion, p_recurso, p_resultado, p_detalle, p_ip, p_origen)::text, 'UTF8')), 'hex')
$$;

-- BEFORE INSERT: asigna seq, enlaza con el evento anterior y calcula el hash.
-- SECURITY DEFINER: corre con permisos del dueño, así agro_web y agro_worker no necesitan tocar la cabeza.
CREATE OR REPLACE FUNCTION auditoria_encadenar() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_catalog AS $$
DECLARE
    v_seq      BIGINT;
    v_anterior TEXT;
BEGIN
    SELECT seq, ultimo_hash INTO v_seq, v_anterior FROM auditoria_cabeza WHERE id FOR UPDATE;
    NEW.seq           := v_seq + 1;
    NEW.hash_anterior := v_anterior;
    NEW.hash := auditoria_calcular_hash(NEW.seq, NEW.hash_anterior, NEW.fecha, NEW.usuario, NEW.rol,
                                        NEW.accion, NEW.recurso, NEW.resultado, NEW.detalle, NEW.ip, NEW.origen);
    UPDATE auditoria_cabeza SET seq = NEW.seq, ultimo_hash = NEW.hash WHERE id;
    RETURN NEW;
END
$$;

-- BEFORE UPDATE / DELETE / TRUNCATE: la auditoría es de solo inserción (incluso para el superusuario,
-- salvo que desactive el trigger a propósito, lo que la verificación de la cadena deja en evidencia).
CREATE OR REPLACE FUNCTION auditoria_solo_insercion() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'La auditoría es de solo inserción: no se permite % sobre la tabla auditoria', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END
$$;

DROP TRIGGER IF EXISTS auditoria_encadenar ON auditoria;
CREATE TRIGGER auditoria_encadenar BEFORE INSERT ON auditoria
    FOR EACH ROW EXECUTE FUNCTION auditoria_encadenar();
DROP TRIGGER IF EXISTS auditoria_solo_insercion ON auditoria;
CREATE TRIGGER auditoria_solo_insercion BEFORE UPDATE OR DELETE ON auditoria
    FOR EACH ROW EXECUTE FUNCTION auditoria_solo_insercion();
DROP TRIGGER IF EXISTS auditoria_sin_truncate ON auditoria;
CREATE TRIGGER auditoria_sin_truncate BEFORE TRUNCATE ON auditoria
    FOR EACH STATEMENT EXECUTE FUNCTION auditoria_solo_insercion();
-- ===================== fin del sello =====================
