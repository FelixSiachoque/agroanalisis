#!/bin/sh
# Se ejecuta automáticamente SOLO al crear el volumen db_data (después de 01_init.sql).
# Crea los usuarios agro_web y agro_worker con mínimo privilegio (ver db/roles.sql).
# Las contraseñas llegan por variables de entorno desde .env; nunca se escriben en archivos.
set -eu
: "${APP_DB_PASSWORD:?Falta APP_DB_PASSWORD en .env}"
: "${WORKER_DB_PASSWORD:?Falta WORKER_DB_PASSWORD en .env}"
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
     -v app_pw="$APP_DB_PASSWORD" -v wk_pw="$WORKER_DB_PASSWORD" \
     -f /srv/db/roles.sql
echo "Usuarios de base de datos agro_web y agro_worker listos"
