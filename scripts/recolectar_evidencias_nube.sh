#!/usr/bin/env bash
# Corre en el SERVIDOR todas las pruebas y demostraciones y guarda cada salida en evidencias/nube/.
# Es la fuente del "Anexo de evidencias" (entregables 4 y 5). Tarda unos 10 minutos.
# Uso (como plataforma, en /opt/agroanalisis):  ./scripts/recolectar_evidencias_nube.sh
# Requiere python3-requests en el host:  sudo apt-get install -y python3-requests
set -uo pipefail
cd "$(dirname "$0")/.."
D=evidencias/nube
mkdir -p "$D"
export CLAVE_ADMIN=$(grep '^ADMIN_PASSWORD=' .env | cut -d= -f2-)
export CLAVE_DEMO=$(grep '^DEMO_PASSWORD=' .env | cut -d= -f2-)
URL=http://localhost
paso() { echo; echo "######## $1  ($(date '+%Y-%m-%d %H:%M:%S'))"; }
sql() { docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "$1"' sh "$1"; }

python3 datos_prueba/generar_datos.py > /dev/null

paso "1. Evidencias del sistema (scripts/evidencias.sh)"
./scripts/evidencias.sh > /dev/null 2>&1
cp "$(ls -t evidencias/evidencias_*.txt | head -1)" "$D/01_evidencias_sistema.txt"
tail -3 "$D/01_evidencias_sistema.txt"

paso "2. Pruebas funcionales y de seguridad (incluye matar y recuperar el worker)"
python3 pruebas/pruebas_funcionales.py "$URL" --docker > "$D/02_pruebas_funcionales.txt" 2>&1
tail -2 "$D/02_pruebas_funcionales.txt"

paso "3. Pruebas unitarias de reglas de negocio (dentro de la imagen de la app)"
docker compose run --rm --no-deps -T -v "$PWD/pruebas:/pruebas:ro" app \
  python /pruebas/test_reglas_negocio.py > "$D/03_pruebas_unitarias.txt" 2>&1
tail -3 "$D/03_pruebas_unitarias.txt"

paso "4. Equivalencia del esquema (instalación nueva = servidor migrado)"
bash pruebas/test_esquema.sh > "$D/04_test_esquema.txt" 2>&1
tail -3 "$D/04_test_esquema.txt"

paso "5. Sello de autenticidad: cadena de custodia"
{
  echo "== Verificación inicial"; ./scripts/demo_sello.sh verificar
  echo; echo "== Intento de modificar la auditoría (app y superusuario)"; ./scripts/demo_sello.sh intentar-modificar
  ID=$(sql "SELECT max(id) - 3 FROM auditoria")
  echo; echo "== Alteración directa del evento #$ID como superusuario (desactivando el trigger)"; ./scripts/demo_sello.sh alterar "$ID"
  echo; echo "== Verificación: debe señalar el evento alterado"; ./scripts/demo_sello.sh verificar || true
  echo; echo "== Restauración del evento #$ID"; ./scripts/demo_sello.sh restaurar "$ID"
  echo; echo "== Verificación final"; ./scripts/demo_sello.sh verificar
} > "$D/05_sello_custodia.txt" 2>&1
grep -iE "íntegra|rota" "$D/05_sello_custodia.txt" | head -5

paso "6. Prueba de carga con 1 worker"
python3 pruebas/prueba_carga.py "$URL" --trabajos 30 --concurrencia 4 --salida "$D/carga_1_worker" > "$D/06_carga_1_worker.txt" 2>&1
tail -8 "$D/06_carga_1_worker.txt"
{ echo "== docker stats al terminar la carga"; docker stats --no-stream; } >> "$D/06_carga_1_worker.txt"

paso "7. Prueba de carga con 2 workers (docker compose up -d --scale worker=2)"
docker compose up -d --scale worker=2 --wait > /dev/null 2>&1
python3 pruebas/prueba_carga.py "$URL" --trabajos 30 --concurrencia 4 --salida "$D/carga_2_workers" > "$D/07_carga_2_workers.txt" 2>&1
tail -8 "$D/07_carga_2_workers.txt"
docker compose up -d --scale worker=1 --wait > /dev/null 2>&1

paso "8. Persistencia: bajar y subir todo el stack"
{
  echo "ANTES:   trabajos=$(sql 'SELECT count(*) FROM trabajos')  usuarios=$(sql 'SELECT count(*) FROM usuarios')  auditoria=$(sql 'SELECT count(*) FROM auditoria')"
  docker compose down
  docker compose up -d --wait
  echo "DESPUÉS: trabajos=$(sql 'SELECT count(*) FROM trabajos')  usuarios=$(sql 'SELECT count(*) FROM usuarios')  auditoria=$(sql 'SELECT count(*) FROM auditoria')"
  echo "Archivos en el volumen: $(docker compose exec -T app sh -c 'find /data -type f | wc -l')"
  docker compose ps
} > "$D/08_persistencia.txt" 2>&1
head -2 "$D/08_persistencia.txt"

paso "Listo: evidencias en $D"
ls -la "$D"
