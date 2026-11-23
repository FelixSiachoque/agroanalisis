#!/usr/bin/env bash
# Aplica las migraciones de db/migraciones/ a una base que YA tiene datos (servidor de AWS)
# sin borrar nada. Es idempotente: se puede ejecutar dos veces seguidas sin error.
#
# Uso (en la raíz del proyecto, con el contenedor db encendido):
#   ./scripts/aplicar_migraciones.sh
#
# Qué hace:
#   1. Si al .env le faltan APP_DB_PASSWORD / WORKER_DB_PASSWORD, las genera (aleatorias).
#   2. Recrea el contenedor db para que reciba esas variables (los datos están en el volumen).
#   3. Ejecuta cada db/migraciones/NNN_*.sql en orden, como superusuario.
#   4. Ejecuta db/roles.sql (usuarios agro_web y agro_worker con mínimo privilegio).
#   5. Reinicia app y worker para que se conecten con sus nuevos usuarios.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "No existe .env (ejecute ./scripts/generar_env.sh)"; exit 1; }

aleatorio() { openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c "$1"; }
for var in APP_DB_PASSWORD WORKER_DB_PASSWORD; do
  if ! grep -q "^${var}=" .env; then
    echo "${var}=$(aleatorio 24)" >> .env
    echo "Agregada ${var} al .env (aleatoria)"
  fi
done
chmod 600 .env

echo "== Asegurando que db esté encendida con las variables nuevas"
docker compose up -d --wait db

psql_db() {   # psql como superusuario DENTRO del contenedor db (lee usuario y base de su entorno)
  docker compose exec -T -e PGOPTIONS="-c client_min_messages=warning" db sh -c 'psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' psql "$@"
}

for f in db/migraciones/[0-9][0-9][0-9]_*.sql; do
  echo "== Aplicando $f"
  psql_db < "$f"
done

echo "== Aplicando db/roles.sql"
docker compose exec -T db sh -c \
  'PGOPTIONS="-c client_min_messages=warning" psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v app_pw="$APP_DB_PASSWORD" -v wk_pw="$WORKER_DB_PASSWORD"' \
  < db/roles.sql

./scripts/detectar_entorno.sh

echo "== Reiniciando app y worker"
docker compose up -d --build app worker
echo "Migraciones aplicadas correctamente."
