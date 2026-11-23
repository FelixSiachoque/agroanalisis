#!/usr/bin/env bash
# Detecta dónde corre la plataforma y lo guarda en .env como ENTORNO=...
# En EC2 consulta el servicio de metadatos (IMDSv2); en cualquier otro equipo escribe "Local".
# La app lo muestra en el pie de página (checklist: "se identifica el entorno").
# Uso: ./scripts/detectar_entorno.sh   (lo llaman generar_env.sh y aplicar_migraciones.sh)
set -euo pipefail
cd "$(dirname "$0")/.."

MD=http://169.254.169.254/latest
c() { curl -sf -m 2 --noproxy "*" "$@"; }
TOKEN=$(c -X PUT "$MD/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null || true)
ID=""
if [ -n "$TOKEN" ]; then
  dato() { c -H "X-aws-ec2-metadata-token: $TOKEN" "$MD/meta-data/$1" 2>/dev/null || true; }
  ID=$(dato instance-id)
fi
if [[ "$ID" =~ ^i-[0-9a-f]+$ ]]; then
  SO=$(. /etc/os-release && echo "$NAME $VERSION_ID")
  ENTORNO="AWS EC2 · $ID · $(dato instance-type) · $(dato placement/region) · $SO"
else
  ENTORNO="Local · $(hostname)"
fi

[ -f .env ] || { echo "No existe .env"; exit 1; }
grep -v '^ENTORNO=' .env > .env.tmp || true
echo "ENTORNO=$ENTORNO" >> .env.tmp
mv .env.tmp .env
chmod 600 .env
echo "Entorno detectado: $ENTORNO"
