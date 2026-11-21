-- USUARIOS DE BASE DE DATOS CON MÍNIMO PRIVILEGIO
--
-- POSTGRES_USER (del .env) es el superusuario: dueño de las tablas. Solo se usa para crear el
-- esquema, aplicar migraciones y hacer mantenimiento. La app y el worker NO lo usan.
--
--   agro_web    -> la aplicación web (contenedor app)
--   agro_worker -> el procesador (contenedor worker)
--
-- Ninguno es SUPERUSER ni dueño de las tablas, así que no pueden desactivar triggers,
-- hacer TRUNCATE ni modificar/borrar la auditoría.
--
-- Se ejecuta con psql pasando las contraseñas como variables (nunca escritas aquí):
--   psql -v app_pw="$APP_DB_PASSWORD" -v wk_pw="$WORKER_DB_PASSWORD" -f db/roles.sql
-- Es idempotente: se puede ejecutar muchas veces.

\set ON_ERROR_STOP on

-- 1. Crear los roles si no existen (sin privilegios especiales)
SELECT 'CREATE ROLE agro_web LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT'
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agro_web') \gexec
SELECT 'CREATE ROLE agro_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT'
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agro_worker') \gexec

ALTER ROLE agro_web    WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_pw';
ALTER ROLE agro_worker WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'wk_pw';

-- 2. Partir de cero: quitar cualquier permiso previo sobre las tablas
REVOKE ALL ON ALL TABLES    IN SCHEMA public FROM agro_web, agro_worker;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM agro_web, agro_worker;
GRANT USAGE ON SCHEMA public TO agro_web, agro_worker;

-- 3. Aplicación web
GRANT SELECT, INSERT                 ON usuarios  TO agro_web;
GRANT UPDATE (rol, activo)           ON usuarios  TO agro_web;   -- no puede cambiar hashes ni nombres
GRANT SELECT, INSERT, DELETE         ON trabajos  TO agro_web;
GRANT UPDATE (estado, error, intentos, disponible_desde, reprocesos, worker, latido, iniciado, terminado)
                                     ON trabajos  TO agro_web;   -- solo lo necesario para reprocesar
GRANT SELECT, INSERT                 ON auditoria TO agro_web;   -- SIN UPDATE / DELETE / TRUNCATE
GRANT SELECT                         ON workers   TO agro_web;   -- panel de Recursos
GRANT USAGE ON SEQUENCE usuarios_id_seq, trabajos_id_seq, auditoria_id_seq TO agro_web;

-- 4. Worker: no toca la tabla de usuarios
GRANT SELECT                         ON trabajos  TO agro_worker;
GRANT UPDATE (estado, iniciado, terminado, intentos, ruta_resultado, error,
              worker, latido, disponible_desde)
                                     ON trabajos  TO agro_worker; -- FOR UPDATE necesita privilegio UPDATE
GRANT INSERT                         ON auditoria TO agro_worker; -- SIN SELECT / UPDATE / DELETE
GRANT SELECT, INSERT, UPDATE         ON workers   TO agro_worker;
GRANT USAGE ON SEQUENCE auditoria_id_seq TO agro_worker;
