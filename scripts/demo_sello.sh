#!/usr/bin/env bash
# Demostración del SELLO DE AUTENTICIDAD (cadena de custodia). Ver README, sección "Sello de autenticidad".
#
#   ./scripts/demo_sello.sh verificar              -> verifica la cadena de auditoría (íntegra / rota en #id)
#   ./scripts/demo_sello.sh intentar-modificar     -> 1) la app no puede alterar la auditoría; el superusuario tampoco (trigger)
#   ./scripts/demo_sello.sh alterar <id_evento>    -> 2) como superusuario: desactiva el trigger, altera un evento y lo reactiva
#   ./scripts/demo_sello.sh restaurar <id_evento>  ->    deshace la alteración del paso 2 (la cadena vuelve a estar íntegra)
#   ./scripts/demo_sello.sh manipular <id_trabajo> -> 3) cambia un byte del archivo subido dentro del volumen /data
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1   # solo afecta a Git Bash en Windows: no convertir /data/... en C:/...

como_superusuario() {   # psql dentro del contenedor db con el superusuario (lee usuario y base de su entorno)
  docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' psql "$@"
}
como_app() {            # psql con el usuario de la aplicación (agro_web), el mismo que usa Flask
  docker compose exec -T db sh -c 'PGPASSWORD="$APP_DB_PASSWORD" psql -h 127.0.0.1 -U agro_web -d "$POSTGRES_DB" "$@"' psql "$@"
}
entero() { [[ "${1:-}" =~ ^[0-9]+$ ]] || { echo "Falta un número de id"; exit 1; }; }

case "${1:-}" in
  verificar)
    docker compose exec -T app flask --app app verificar-cadena
    ;;
  intentar-modificar)
    echo "== Con el usuario de la app (agro_web): no tiene permiso UPDATE/DELETE sobre auditoria"
    como_app -c "UPDATE auditoria SET detalle = 'borrado' WHERE id = 1" 2>&1 || true
    como_app -c "DELETE FROM auditoria" 2>&1 || true
    echo "== Con el superusuario: el trigger de solo inserción también lo impide"
    como_superusuario -c "UPDATE auditoria SET detalle = 'borrado' WHERE id = 1" 2>&1 || true
    como_superusuario -c "TRUNCATE auditoria" 2>&1 || true
    ;;
  alterar)
    entero "${2:-}"
    echo "== Superusuario malintencionado: desactiva el trigger, cambia el evento #$2 y vuelve a activarlo"
    como_superusuario -c "BEGIN;
      ALTER TABLE auditoria DISABLE TRIGGER auditoria_solo_insercion;
      UPDATE auditoria SET detalle = coalesce(detalle, '') || ' [ALTERADO]' WHERE id = $2;
      ALTER TABLE auditoria ENABLE TRIGGER auditoria_solo_insercion;
      COMMIT;"
    echo "Ahora verifique: ./scripts/demo_sello.sh verificar   (o /admin/auditoria/verificar)"
    ;;
  restaurar)
    entero "${2:-}"
    como_superusuario -c "BEGIN;
      ALTER TABLE auditoria DISABLE TRIGGER auditoria_solo_insercion;
      UPDATE auditoria SET detalle = left(detalle, length(detalle) - length(' [ALTERADO]'))
       WHERE id = $2 AND detalle LIKE '% [ALTERADO]';
      ALTER TABLE auditoria ENABLE TRIGGER auditoria_solo_insercion;
      COMMIT;"
    echo "Evento #$2 restaurado."
    ;;
  manipular)
    entero "${2:-}"
    ruta=$(como_superusuario -Atc "SELECT ruta_archivo FROM trabajos WHERE id = $2")
    [ -n "$ruta" ] || { echo "No existe el trabajo #$2"; exit 1; }
    echo "== Cambiando un byte de $ruta (dentro del volumen /data)"
    docker compose exec -T app python -c "
import sys
ruta = sys.argv[1]
datos = bytearray(open(ruta, 'rb').read())
datos[-2] = ord('9') if datos[-2] != ord('9') else ord('8')
open(ruta, 'wb').write(bytes(datos))
print('Archivo modificado:', len(datos), 'bytes')" "$ruta"
    ;;
  *)
    sed -n '2,9p' "$0"; exit 1
    ;;
esac
