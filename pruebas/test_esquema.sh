#!/usr/bin/env bash
# Comprueba que el esquema final es IDÉNTICO por los dos caminos:
#   A) instalación desde cero:   db/init.sql + db/roles.sql
#   B) servidor existente:       pruebas/esquema_base_v0.sql (esquema viejo) + db/migraciones/*.sql + db/roles.sql
# Además aplica las migraciones DOS veces en B para comprobar que son idempotentes.
#
# Usa dos contenedores temporales de PostgreSQL (se borran al terminar). Uso:
#   bash pruebas/test_esquema.sh
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGEN=postgres:16-alpine
A=esquema_prueba_a_$$
B=esquema_prueba_b_$$
TMP=$(mktemp -d)
trap 'docker rm -f "$A" "$B" >/dev/null 2>&1; rm -rf "$TMP"' EXIT

for c in "$A" "$B"; do
  docker run -d --rm --name "$c" -e POSTGRES_USER=agro_admin -e POSTGRES_PASSWORD=prueba \
         -e POSTGRES_DB=agroanalisis "$IMAGEN" >/dev/null
done
for c in "$A" "$B"; do
  until docker exec "$c" pg_isready -U agro_admin -d agroanalisis -q 2>/dev/null \
        && docker exec "$c" psql -U agro_admin -d agroanalisis -qtc "SELECT 1" >/dev/null 2>&1; do sleep 1; done
done

psql_en() { docker exec -i -e PGOPTIONS="-c client_min_messages=warning" "$1" psql -v ON_ERROR_STOP=1 -q -U agro_admin -d agroanalisis -v app_pw=x -v wk_pw=y; }

echo "== A: init.sql desde cero"
psql_en "$A" < db/init.sql
psql_en "$A" < db/roles.sql

echo "== B: esquema anterior + migraciones (dos veces)"
psql_en "$B" < pruebas/esquema_base_v0.sql
# datos de ejemplo en el esquema viejo, para que las migraciones trabajen sobre filas reales
psql_en "$B" <<'SQL'
INSERT INTO usuarios (usuario, clave_hash, rol) VALUES ('viejo', 'x', 'usuario');
INSERT INTO trabajos (usuario_id, nombre_original, ruta_archivo, tipo, tamano_bytes) VALUES (1, 'a.csv', '/data/a', 'csv', 1);
INSERT INTO auditoria (usuario, accion, detalle) VALUES ('viejo', 'login_ok', ''), ('worker@x', 'procesar_ok', '');
SQL
for vuelta in 1 2; do
  for f in db/migraciones/[0-9][0-9][0-9]_*.sql; do psql_en "$B" < "$f"; done
  psql_en "$B" < db/roles.sql
done

# Los eventos viejos deben quedar encadenados y la cabeza apuntando al último
malos=$(docker exec "$B" psql -U agro_admin -d agroanalisis -Atc "
  SELECT count(*) FROM auditoria a
   WHERE a.hash <> auditoria_calcular_hash(a.seq, a.hash_anterior, a.fecha, a.usuario, a.rol, a.accion,
                                           a.recurso, a.resultado, a.detalle, a.ip, a.origen)
      OR a.hash_anterior <> coalesce((SELECT p.hash FROM auditoria p WHERE p.seq = a.seq - 1), repeat('0', 64));
  ")
cabeza=$(docker exec "$B" psql -U agro_admin -d agroanalisis -Atc \
  "SELECT (SELECT seq FROM auditoria_cabeza) = (SELECT max(seq) FROM auditoria)")
if [ "$malos" != "0" ] || [ "$cabeza" != "t" ]; then
  echo "FALLA: la migración no encadenó bien los eventos existentes (malos=$malos cabeza=$cabeza)"; exit 1
fi
echo "OK: eventos existentes encadenados por la migración"

volcar() { docker exec "$1" pg_dump -U agro_admin -d agroanalisis --schema-only --no-owner | grep -v -E '^--|^$|^SET |^SELECT pg_catalog|^.(un)?restrict '; }   # \restrict: token aleatorio de pg_dump
volcar "$A" > "$TMP/a.sql"
volcar "$B" > "$TMP/b.sql"

# Los permisos también deben coincidir
permisos() { docker exec "$1" psql -U agro_admin -d agroanalisis -Atc \
  "SELECT grantee||' '||table_name||' '||privilege_type FROM information_schema.role_table_grants WHERE grantee IN ('agro_web', 'agro_worker') ORDER BY 1;
   SELECT grantee||' '||table_name||'.'||column_name||' '||privilege_type FROM information_schema.column_privileges WHERE grantee IN ('agro_web', 'agro_worker') ORDER BY 1;"; }
permisos "$A" > "$TMP/pa.txt"
permisos "$B" > "$TMP/pb.txt"

if diff -u "$TMP/a.sql" "$TMP/b.sql" && diff -u "$TMP/pa.txt" "$TMP/pb.txt"; then
  echo "OK: el esquema y los permisos son idénticos por ambos caminos ($(wc -l < "$TMP/a.sql") líneas de esquema, $(wc -l < "$TMP/pa.txt") permisos)"
else
  echo "FALLA: init.sql y las migraciones producen esquemas distintos (ver diferencias arriba)"
  exit 1
fi
