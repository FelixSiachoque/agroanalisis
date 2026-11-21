#!/usr/bin/env bash
# Crea el archivo .env a partir de .env.example con claves aleatorias.
# Uso: ./scripts/generar_env.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  echo "Ya existe .env; no se sobrescribe. Bórrelo primero si quiere regenerarlo."
  exit 1
fi

aleatorio() { openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c "$1"; }

ADMIN=$(aleatorio 16)
DEMO=$(aleatorio 12)

sed -e "s/CAMBIAR_DB/$(aleatorio 24)/" \
    -e "s/CAMBIAR_APPDB/$(aleatorio 24)/" \
    -e "s/CAMBIAR_WORKERDB/$(aleatorio 24)/" \
    -e "s/CAMBIAR_SECRET/$(aleatorio 48)/" \
    -e "s/CAMBIAR_ADMIN/$ADMIN/" \
    -e "s/CAMBIAR_DEMO/$DEMO/" \
    .env.example > .env

chmod 600 .env     # solo el dueño puede leerlo
echo ".env creado (permisos 600)."
echo "  Admin:  usuario 'coordinador'  contraseña: $ADMIN"
echo "  Demo:   tecnico1 / agricultor1 / agricultor2  contraseña: $DEMO"
echo "Guárdelas en un lugar seguro; también puede verlas con: grep PASSWORD .env"
