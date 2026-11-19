#!/usr/bin/env bash
# Crea las cuentas de demostración (tecnico1, agricultor1, agricultor2) con la clave DEMO_PASSWORD del .env
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose exec app flask --app app crear-demo
