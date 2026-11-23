# Cómo ejecutar y probar AgroAnálisis Sugamuxi

Guía para alguien que nunca ha visto el proyecto. Todos los comandos se copian y pegan **desde la carpeta del proyecto** (`agroanalisis/`). En Windows, usa **Git Bash**; las alternativas en PowerShell se indican cuando cambian.

---

## 1. Requisitos

| Herramienta | Para qué | Cómo comprobarlo |
|---|---|---|
| Docker Desktop (Windows/Mac) o Docker Engine (Linux), con Compose v2 | levantar los 4 contenedores | `docker version` y `docker compose version` |
| Git (en Windows incluye **Git Bash**, o usa WSL) | clonar y ejecutar los scripts `.sh` | `git --version` |
| Python 3.10+ y `pip install requests` | **solo** para correr las pruebas desde tu computador | `python --version` |

Docker Desktop debe estar abierto y decir *Engine running*. El puerto **80** debe estar libre (ver la sección 7).

## 2. Ejecución local paso a paso

```bash
# 1. Obtener el código
git clone https://github.com/FelixSiachoque/agroanalisis.git
cd agroanalisis

# 2. Crear el archivo de secretos .env (claves aleatorias). Muestra las contraseñas en pantalla.
bash scripts/generar_env.sh

# 3. Construir y levantar los 4 contenedores (la primera vez tarda unos 3–5 minutos)
docker compose up -d --build --wait
docker compose ps            # proxy, app, worker y db deben decir "healthy"

# 4. Crear las cuentas de demostración (tecnico1, agricultor1, agricultor2)
bash scripts/crear_usuarios_demo.sh

# 5. Generar los datos de prueba grandes (los pequeños ya vienen en datos_prueba/)
python datos_prueba/generar_datos.py
```

**Abrir:** http://localhost

| Usuario | Rol | Dónde está su contraseña |
|---|---|---|
| `coordinador` | Coordinador (admin) | `ADMIN_PASSWORD` en el `.env` |
| `tecnico1` | Técnico (operador) | `DEMO_PASSWORD` en el `.env` |
| `agricultor1`, `agricultor2` | Agricultor (usuario) | `DEMO_PASSWORD` en el `.env` |

Para ver las contraseñas: `grep -E "ADMIN_PASSWORD|DEMO_PASSWORD" .env` (en PowerShell: `Select-String "PASSWORD" .env`). No las compartas por chat ni las subas a GitHub: el `.env` está en `.gitignore`.

### Apagar, reiniciar y empezar de cero

```bash
docker compose down                  # apagar. Los datos se CONSERVAN (volúmenes db_data y datos)
docker compose up -d --wait          # volver a encender con todo lo que había
docker compose restart               # reiniciar sin apagar
docker compose down -v               # apagar y BORRAR todos los datos (usuarios, trabajos, auditoría, archivos)
docker compose up -d --build --wait && bash scripts/crear_usuarios_demo.sh   # empezar de cero
```

## 3. Despliegue en AWS EC2 (resumen)

Detalle completo en el `README.md`, sección 4, y en `infra/`.

1. **Crear el servidor:** en la terminal del Learner Lab, ejecutar `curl -fsSO https://raw.githubusercontent.com/FelixSiachoque/agroanalisis/main/infra/crear_infra_aws.sh && bash crear_infra_aws.sh`. Crea el Security Group (22 solo desde tu IP, 80 público) y la EC2. En el primer arranque, `infra/user_data.sh` aplica el hardening y despliega todo. Con `TIPO=t2.micro` delante del `bash` cabe en 1 GB.
2. **Entrar:** `ssh -i ~/agroanalisis-key.pem ubuntu@<IP_PUBLICA>`, luego `sudo -iu plataforma` y `cd /opt/agroanalisis`.
3. **Actualizar un servidor que ya tiene datos:** `git pull && ./scripts/aplicar_migraciones.sh`. Agrega las claves nuevas al `.env`, aplica `db/migraciones/` y `db/roles.sql`, y reconstruye app y worker. Se puede ejecutar dos veces sin error.
4. **Verificar puertos y firewall** (como `ubuntu`): `sudo ss -tlnp` (solo 22 y 80), `sudo ufw status verbose` y `docker compose ps`. Todas las evidencias juntas: `./scripts/evidencias.sh`.

## 4. Cómo correr las pruebas

Primero carga las contraseñas en variables de entorno.

Git Bash o Linux:
```bash
export CLAVE_ADMIN="$(grep '^ADMIN_PASSWORD=' .env | cut -d= -f2-)" CLAVE_DEMO="$(grep '^DEMO_PASSWORD=' .env | cut -d= -f2-)"
```
PowerShell:
```powershell
$env:CLAVE_ADMIN = ((Select-String '^ADMIN_PASSWORD=' .env).Line -split '=',2)[1]
$env:CLAVE_DEMO  = ((Select-String '^DEMO_PASSWORD=' .env).Line -split '=',2)[1]
```

| Prueba | Comando | Qué debes ver |
|---|---|---|
| Unitarias de reglas de negocio (sin Docker) | `python -m unittest pruebas/test_reglas_negocio.py` | `Ran 26 tests ... OK` |
| Las mismas, dentro del contenedor | `docker compose exec -T app python - < pruebas/test_reglas_negocio.py` | `OK` |
| Funcionales y de seguridad | `python pruebas/pruebas_funcionales.py http://localhost` | `Resultado: 55 de 55 pruebas pasaron` |
| Lo mismo, más reinicio del worker y demo del sello (en la máquina del stack) | `python pruebas/pruebas_funcionales.py http://localhost --docker` | `Resultado: 67 de 67 pruebas pasaron` |
| Equivalencia del esquema (init.sql vs. migraciones) | `bash pruebas/test_esquema.sh` | `OK: el esquema y los permisos son idénticos...` |
| Carga | `python pruebas/prueba_carga.py http://localhost --trabajos 20 --concurrencia 4` | 20/20 completados, unos 18 trabajos/min con 1 worker; informe en `resultados/` |

Mientras corre la carga, en otra terminal: `docker stats`. El número de pruebas funcionales cambia si activas reglas alternativas, porque se adaptan a `/api/reglas`. Lo importante es que no aparezca ninguna `[FALLA]`.

## 5. Guion de demo de 10 minutos (los 14 puntos del checklist)

Prepara tres ventanas: navegador en http://localhost (o la IP), una terminal en la carpeta del proyecto y este guion.

| Min | # | Punto | Qué hacer o mostrar |
|---|---|---|---|
| 0:00 | 1 | Despliegue en la nube | Consola de AWS → EC2 → instancia `agroanalisis` (Ubuntu 24.04) y `http://<IP>` en el navegador. En local: http://localhost |
| 0:40 | 2 | Contenedores | `docker compose ps`: los 4 *healthy*. Explicar: proxy = única entrada, app = web, worker = procesa, db = datos |
| 1:20 | 3 | Linux y procesos | `docker compose exec app id` → `uid=10001(app)`; `docker compose top app worker` → gunicorn ×3 y `worker.py` |
| 2:00 | 4 | Recursos | `docker stats --no-stream` y, como `tecnico1`, la pantalla **Recursos**: leer la frase "El worker usa 26 MB de 256 MB (10 %): margen suficiente…" |
| 2:40 | 5 | Dos cuentas con roles distintos | Entrar como `agricultor1` (menú: solo *Mis trabajos*) y como `coordinador` (menú completo) |
| 3:10 | 6 | Operación permitida y denegada | Como `agricultor1`, abrir `http://localhost/admin/usuarios` → **Acceso denegado (403)** |
| 3:40 | 8 | Procesamiento | Como `agricultor1`, subir `datos_prueba/01_suelos_lote_A.csv`: el detalle pasa solo de *Pendiente* a *En ejecución* y *Completado*; descargar el JSON. Subir `07_invalido_programa.exe` → rechazado; `06_invalido_columnas.csv` → *Fallido* con el motivo |
| 5:00 | 7 | Aislamiento | Anotar el n.º del trabajo; como `agricultor2`, abrir `http://localhost/trabajos/<n.º>` → **No encontrado (404)** |
| 5:40 | 13 | Autenticidad (regla y sello) | Como `agricultor2`, subir 4 archivos seguidos: el 4.º se rechaza por la cuota. Coordinador → **Reglas**. Terminal: `./scripts/demo_sello.sh alterar 7`, luego `./scripts/demo_sello.sh verificar` (→ *Cadena ROTA en el evento #7*) y `./scripts/demo_sello.sh restaurar 7` |
| 7:00 | 12 | Auditoría | Coordinador → **Auditoría** → resultado *denegado*: usuario, rol, acción, recurso, fecha e IP. **Verificar cadena** → íntegra. **Exportar CSV** |
| 7:40 | 9 | Persistencia | `docker compose down && docker compose up -d --wait`, volver a entrar: trabajos y auditoría siguen ahí |
| 8:30 | 10 | Hardening | `grep -n "read_only\|cap_drop\|no-new-privileges\|mem_limit" docker-compose.yml`; `docker compose exec app touch /srv/x` → *Read-only file system*; en EC2: `sudo ufw status`, `sudo sshd -T \| grep -E "passwordauthentication\|permitrootlogin"`, `stat -c '%a' .env` → 600 |
| 9:10 | 11 | Red y puertos | `docker compose ps` (solo `0.0.0.0:80->8080`); `docker compose exec worker python -c "import socket; socket.create_connection(('1.1.1.1',443),3)"` → *Network is unreachable*; en EC2: `sudo ss -tlnp` → solo 22 y 80 |
| 9:40 | 14 | Repositorio sin secretos | `git ls-files \| grep -c "^.env$"` → 0; `cat .gitignore` |

Para practicar los retos sorpresa, ver `GUIA_RETOS_SUSTENTACION.md`.

## 6. Qué tocar si el profesor pide un cambio

| Pedido | Archivo |
|---|---|
| Permisos de un rol | `app/permisos.py` |
| Aislamiento entre usuarios | `app/seguridad.py` → `obtener_trabajo_autorizado()` |
| Nuevo evento de auditoría | `auditar(...)` en la ruta de `app/rutas.py` |
| Regla de negocio | `app/reglas_negocio.py` o `REGLA_<NOMBRE>=1` en `.env` |
| Límite de RAM/CPU | `docker-compose.yml` (`mem_limit` + `memswap_limit` iguales, `cpus`) |

Después de cambiar un `.py`: `docker compose up -d --build app` (o `worker`). Después de cambiar `docker-compose.yml` o el `.env`: `docker compose up -d <servicio>`.

## 7. Solución de problemas frecuentes

| Problema | Causa | Solución |
|---|---|---|
| `Bind for 0.0.0.0:80 failed: port is already allocated` | otro programa usa el puerto 80 (IIS, Skype, otro contenedor) | cerrar ese programa, o en `docker-compose.yml` cambiar `"80:8080"` por `"8080:8080"` y entrar a http://localhost:8080 (las pruebas: `python pruebas/pruebas_funcionales.py http://localhost:8080`) |
| `required variable APP_DB_PASSWORD is missing a value` | falta el `.env` o es de una versión anterior | sin `.env`: `bash scripts/generar_env.sh`. Con un `.env` viejo: `bash scripts/aplicar_migraciones.sh` (agrega las claves que faltan) |
| `docker compose ps` muestra `unhealthy` o `restarting` | error en el código o la base de datos no arrancó | `docker compose logs --tail 40 app` (o `worker`, `db`), corregir y `docker compose up -d --build` |
| `$'\r': command not found` al ejecutar un `.sh` | el archivo quedó con finales de línea de Windows (CRLF) | el repositorio fuerza LF con `.gitattributes`; si un editor lo cambió: `git checkout -- scripts/` o `sed -i 's/\r$//' scripts/*.sh` |
| Cambié un `.py` y no pasa nada | usé `restart`: el código se copia dentro de la imagen | `docker compose up -d --build app` |
| 400 "El formulario expiró" | la app se reinició con la página vieja abierta | recargar la página (F5) |
| 429 "Demasiados intentos de ingreso" | más de 10 inicios de sesión por minuto desde la misma IP (protección contra fuerza bruta) | esperar un minuto |
| El trabajo se queda en *Pendiente* | el worker está detenido | `docker compose start worker`; en **Recursos** debe aparecer "activo" |
| `./scripts/x.sh: Permission denied` | el archivo perdió el permiso de ejecución | `bash scripts/x.sh` o `chmod +x scripts/*.sh` |
| En Windows, `stat .env` muestra 644 | NTFS no aplica permisos Unix | es normal en Windows; en el servidor Linux queda 600 |
| Algo responde en el puerto 5432 del computador | es un PostgreSQL instalado en Windows, no el del proyecto: el contenedor `db` no publica puertos | nada que hacer; `docker compose ps` muestra `5432/tcp` sin `0.0.0.0` |
