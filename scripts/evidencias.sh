#!/usr/bin/env bash
# Recolecta las evidencias del checklist docente en un solo archivo.
# Uso (en el servidor, desde /opt/agroanalisis):  ./scripts/evidencias.sh
#   Las secciones que necesitan sudo (UFW, sshd) se intentan con "sudo -n": como usuario 'plataforma'
#   (sin sudo) salen como "requiere sudo"; ejecútelo como 'ubuntu' para verlas completas.
#   A propósito NO usa "set -e": si un comando falla, se registra y sigue con el resto.
# Resultado: evidencias/evidencias_AAAAMMDD_HHMM.txt
cd "$(dirname "$0")/.."
mkdir -p evidencias
SALIDA="evidencias/evidencias_$(date +%Y%m%d_%H%M).txt"

seccion() { echo; echo "=================================================="; echo "== $1"; echo "=================================================="; }

{
seccion "1. ENTORNO: sistema operativo y servidor"
date
hostnamectl 2>/dev/null || cat /etc/os-release
uname -r
curl -s -m 2 -H "X-aws-ec2-metadata-token: $(curl -s -m 2 -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')" \
  http://169.254.169.254/latest/meta-data/instance-type 2>/dev/null && echo "  <- tipo de instancia EC2"

seccion "2. CONTENEDORES activos"
docker compose ps

seccion "3. RECURSOS: CPU / memoria por contenedor y del servidor"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.PIDs}}"
free -h
df -h /
docker system df

seccion "4. HARDENING de contenedores (usuario, solo lectura, capacidades, límites)"
for c in $(docker compose ps -q); do
  docker inspect --format '{{.Name}}  user={{.Config.User}}  read_only={{.HostConfig.ReadonlyRootfs}}  cap_drop={{.HostConfig.CapDrop}}  mem={{.HostConfig.Memory}}  cpus(nano)={{.HostConfig.NanoCpus}}  pids={{.HostConfig.PidsLimit}}  sec={{.HostConfig.SecurityOpt}}' "$c"
done
echo "-- Usuario con que corre la app y el worker:"
docker compose exec -T app id
docker compose exec -T worker id
echo "-- Procesos dentro de los contenedores:"
docker compose top app worker

echo "-- Límites vistos DESDE DENTRO de cada contenedor (cgroups v2):"
for s in app worker; do
  echo "   $s: memory.max=$(docker compose exec -T $s cat /sys/fs/cgroup/memory.max)  memory.current=$(docker compose exec -T $s cat /sys/fs/cgroup/memory.current)  cpu.max=$(docker compose exec -T $s cat /sys/fs/cgroup/cpu.max)  pids=$(docker compose exec -T $s cat /sys/fs/cgroup/pids.current)/$(docker compose exec -T $s cat /sys/fs/cgroup/pids.max)"
done

seccion "5. PERMISOS de archivos de configuración y datos"
ls -l .env docker-compose.yml
docker compose exec -T app ls -la /data /data/uploads /data/results 2>/dev/null

seccion "6. RED: puertos en escucha y firewall"
sudo -n ss -tulpn 2>/dev/null || ss -tuln
sudo -n ufw status verbose 2>/dev/null || echo '(UFW: requiere sudo)'
docker network ls --filter name=agroanalisis
echo "-- ¿La base de datos tiene puertos publicados? (debe salir vacío)"
docker compose port db 5432 2>&1 || true

seccion "7. SSH y servicios del sistema"
sudo -n sshd -T 2>/dev/null | grep -Ei '^(permitrootlogin|passwordauthentication|maxauthtries)' || echo '(sshd: requiere sudo)'
systemctl --no-pager --type=service --state=running | head -40

seccion "8. ACTUALIZACIONES"
apt list --upgradable 2>/dev/null | tail -n +2 | wc -l | xargs echo "Paquetes pendientes por actualizar:"
cat /etc/apt/apt.conf.d/20auto-upgrades 2>/dev/null

seccion "9. AUDITORÍA: últimos 20 eventos (usuario, acción, fecha)"
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT seq, fecha, usuario, rol, accion, recurso, resultado FROM auditoria ORDER BY seq DESC LIMIT 20"'
echo "-- Sello: verificación de la cadena de auditoría"
docker compose exec -T app flask --app app verificar-cadena

seccion "10. TRABAJOS por estado"
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT estado, count(*) FROM trabajos GROUP BY estado"'

seccion "11. LOGS recientes de app y worker"
docker compose logs --tail 15 app worker
echo "-- Usuarios de base de datos (agro_web y agro_worker NO deben ser superusuarios):"
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT rolname, rolsuper FROM pg_roles WHERE rolname LIKE '"'"'agro%'"'"'"'

seccion "12. REPOSITORIO: ¿hay secretos versionados? (debe salir vacío)"
git -c safe.directory='*' ls-files | grep -E '(^|/)\.env$|\.pem$|\.key$' || echo "OK: ningún archivo de secretos en git"
} 2>&1 | tee "$SALIDA"

echo; echo "Evidencias guardadas en $SALIDA"
