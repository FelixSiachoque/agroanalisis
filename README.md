# AgroAnálisis Sugamuxi · Plataforma segura de procesamiento de archivos

Proyecto final de Sistemas Operativos (UPTC 2026).

AgroAnálisis Sugamuxi es un **laboratorio ficticio de análisis de suelos**. Los agricultores suben los resultados de laboratorio (`.csv`) o informes de campo (`.txt`), un trabajador en segundo plano los procesa (estadísticas, clasificación de pH y hash SHA-256) y cada agricultor descarga **solo sus** resultados.

## Arquitectura

```
Internet ──► AWS EC2 · Ubuntu 24.04 (Security Group + UFW: solo 22 desde mi IP y 80)
              └── Docker Compose
                  red "frontend"            red "backend" (internal: sin Internet)
                  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
   puerto 80 ──►  │  proxy   │──►│   app    │──►│    db    │◄──│  worker  │
                  │  nginx   │   │  Flask   │   │ Postgres │   │  Python  │
                  └──────────┘   └────┬─────┘   └──────────┘   └────┬─────┘
                                      └──────── volumen "datos" ────┘
                                     /data/uploads/<id_usuario>/  /data/results/<id_usuario>/
```

| Contenedor | Función | Puerto publicado | Usuario |
|---|---|---|---|
| `proxy` | nginx: única entrada, cabeceras de seguridad, límite de intentos de login | 80 → 8080 | nginx (101) |
| `app` | Web/API: login, roles, subida, descarga, auditoría | ninguno | app (10001) |
| `worker` | Procesa la cola: pendiente → en_ejecucion → completado/fallido | ninguno | app (10001) |
| `db` | PostgreSQL: usuarios, trabajos (la cola) y auditoría | **ninguno** | postgres |

La cola de trabajos es la propia tabla `trabajos` de PostgreSQL. El worker toma cada trabajo con `SELECT … FOR UPDATE SKIP LOCKED`, así que no hace falta Redis ni RabbitMQ y se puede escalar con `docker compose up -d --scale worker=2`.

## Estructura

```
app/            Aplicación Flask (app.py, permisos.py ← MATRIZ DE ROLES, db.py, templates/)
worker/         Trabajador (worker.py, procesadores.py)
nginx/          Configuración del proxy inverso
db/init.sql     Esquema de la base de datos
infra/          bootstrap_ec2.sh: instala Docker y aplica el hardening en el servidor
scripts/        generar_env.sh, crear_usuarios_demo.sh, evidencias.sh
pruebas/        pruebas_funcionales.py (27 pruebas), prueba_carga.py
datos_prueba/   Carga de prueba propia (5 válidos + 4 inválidos)
RETOS.md        Guía para resolver los retos sorpresa
```

## Subir el código a GitHub (una vez)

```bash
cd agroanalisis
git init && git add . && git commit -m "Plataforma AgroAnálisis Sugamuxi"
git branch -M main
git remote add origin https://github.com/<usuario>/agroanalisis.git
git push -u origin main
```
Antes del push, revisa con `git status` que **no** aparezca `.env`.

## Despliegue automático en AWS Academy (recomendado)

En el Learner Lab, con el laboratorio encendido (*Start Lab*, punto verde), se abre la terminal de la misma página y se ejecuta:
```bash
curl -sO https://raw.githubusercontent.com/FelixSiachoque/agroanalisis/main/infra/crear_infra_aws.sh
bash crear_infra_aws.sh
```
El script crea el par de llaves, el security group y la instancia EC2. La instancia se configura sola en su primer arranque con `infra/user_data.sh`, que aplica el hardening, despliega la app y crea las cuentas. Las contraseñas generadas quedan en `/home/plataforma/credenciales.txt` (permisos 600).

## Despliegue manual en AWS Academy (desde cero)

### 1. Crear la instancia
1. AWS Academy → *Start Lab* → consola de AWS → **EC2** → *Launch instance*.
2. Nombre `agroanalisis`, imagen **Ubuntu Server 24.04 LTS**, tipo **t3.small** (o t2.micro), par de llaves `vockey` (o uno propio).
3. **Security group** nuevo con solo dos reglas de entrada:
   - SSH (22), origen **My IP**
   - HTTP (80), origen 0.0.0.0/0
4. Almacenamiento de 20 GB. Lanzar.

### 2. Preparar el servidor (una sola vez)
```bash
ssh -i labsuser.pem ubuntu@IP_PUBLICA
git clone <URL_DE_ESTE_REPO> /tmp/agro
sudo bash /tmp/agro/infra/bootstrap_ec2.sh
```
El script actualiza el sistema, instala Docker, crea la cuenta sin privilegios `plataforma`, endurece SSH, activa UFW, fail2ban y las actualizaciones automáticas, y deshabilita servicios que no se usan.

### 3. Desplegar la aplicación (como usuario `plataforma`)
```bash
sudo -iu plataforma
git clone <URL_DE_ESTE_REPO> /opt/agroanalisis
cd /opt/agroanalisis
./scripts/generar_env.sh            # crea .env con claves aleatorias (permisos 600) y las muestra
docker compose up -d --build        # construye y levanta los 4 contenedores
docker compose ps                   # todos deben estar "running"/"healthy"
./scripts/crear_usuarios_demo.sh    # crea tecnico1, agricultor1, agricultor2
```
Abrir `http://IP_PUBLICA` en el navegador.

### Cuentas

| Usuario | Rol | Contraseña |
|---|---|---|
| coordinador | admin | `ADMIN_PASSWORD` del `.env` |
| tecnico1 | operador | `DEMO_PASSWORD` del `.env` |
| agricultor1, agricultor2 | usuario | `DEMO_PASSWORD` del `.env` |

## Operación diaria

```bash
docker compose ps                     # estado de los contenedores
docker compose logs -f app worker     # logs en vivo
docker stats                          # CPU y memoria
docker compose restart worker         # reiniciar un servicio
docker compose down                   # detener (los datos quedan en los volúmenes)
docker compose up -d                  # volver a levantar
git pull && docker compose up -d --build   # actualizar el código
```
**Reinicio total del servidor:** `sudo reboot`. Los contenedores tienen `restart: unless-stopped`, así que vuelven a levantarse solos.

**Borrar todo, incluidos los datos (cuidado):** `docker compose down -v`

## Pruebas

Se corren desde el portátil o desde el servidor:
```bash
pip install requests
python3 datos_prueba/generar_datos.py                 # crea también el archivo de 3 MB
export CLAVE_ADMIN='...' CLAVE_DEMO='...'             # las del .env
python3 pruebas/pruebas_funcionales.py http://IP_PUBLICA   # 27 pruebas: roles, aislamiento, cuota, archivos…
python3 pruebas/prueba_carga.py http://IP_PUBLICA 30       # mientras tanto, en el servidor: docker stats
```

Para reunir todas las evidencias del checklist en un archivo, entrar como `ubuntu` y correr:
```bash
cd /opt/agroanalisis && sudo ./scripts/evidencias.sh
```

## Seguridad (resumen)

- Las contraseñas se guardan como hash **scrypt** (werkzeug). Los secretos solo viven en `.env`, que no se versiona y tiene permisos 600.
- El control de acceso se hace **en el servidor**, con el decorador `@requiere(...)` y la función `obtener_trabajo_autorizado(...)`.
- Los contenedores corren sin root, con sistema de archivos de solo lectura, `cap_drop: ALL`, `no-new-privileges` y límites de memoria y CPU.
- La red `backend` es interna: la base de datos y el worker no son alcanzables desde Internet.
- El servidor tiene SSH solo con llave y sin root, UFW + Security Group (22 y 80), fail2ban y actualizaciones automáticas.

## Limpieza al terminar el curso
AWS Academy → EC2 → *Terminate instance* y borrar el security group, para no consumir créditos.
