-- Migración 004: SELLO DE AUTENTICIDAD (cadena de custodia).
--   - trabajos: huella SHA-256 del archivo original (al recibirlo) y del resultado (al producirlo)
--   - auditoria: cada evento encadenado al anterior con SHA-256 + tabla de solo inserción
-- Idempotente y en UNA transacción: si algo falla, no queda nada a medias.
BEGIN;

ALTER TABLE trabajos  ADD COLUMN IF NOT EXISTS sha256_original  TEXT;
ALTER TABLE trabajos  ADD COLUMN IF NOT EXISTS sha256_resultado TEXT;
ALTER TABLE auditoria ADD COLUMN IF NOT EXISTS seq           BIGINT;
ALTER TABLE auditoria ADD COLUMN IF NOT EXISTS hash_anterior TEXT;
ALTER TABLE auditoria ADD COLUMN IF NOT EXISTS hash          TEXT;

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

-- Encadenar los eventos que ya existían (solo la primera vez). El trigger de solo inserción se
-- desactiva ÚNICAMENTE dentro de esta transacción, para poder escribir seq/hash en las filas viejas.
DO $$
DECLARE
    r        RECORD;
    v_ant    TEXT   := repeat('0', 64);
    v_seq    BIGINT := 0;
    v_hash   TEXT;
BEGIN
    IF EXISTS (SELECT 1 FROM auditoria WHERE hash IS NULL) THEN
        ALTER TABLE auditoria DISABLE TRIGGER auditoria_solo_insercion;
        FOR r IN SELECT * FROM auditoria ORDER BY id LOOP
            v_seq  := v_seq + 1;
            v_hash := auditoria_calcular_hash(v_seq, v_ant, r.fecha, r.usuario, r.rol, r.accion,
                                              r.recurso, r.resultado, r.detalle, r.ip, r.origen);
            UPDATE auditoria SET seq = v_seq, hash_anterior = v_ant, hash = v_hash WHERE id = r.id;
            v_ant := v_hash;
        END LOOP;
        ALTER TABLE auditoria ENABLE TRIGGER auditoria_solo_insercion;
        UPDATE auditoria_cabeza SET seq = v_seq, ultimo_hash = v_ant WHERE id;
        RAISE NOTICE 'Encadenados % eventos existentes', v_seq;
    END IF;
END
$$;

ALTER TABLE auditoria ALTER COLUMN seq           SET NOT NULL;
ALTER TABLE auditoria ALTER COLUMN hash_anterior SET NOT NULL;
ALTER TABLE auditoria ALTER COLUMN hash          SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_auditoria_seq ON auditoria(seq);

COMMIT;
