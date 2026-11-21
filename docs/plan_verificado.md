# Plan del proyecto y verificación de requisitos (versión verificada contra el código)

> Este documento reemplaza al plan inicial (`plan_de_proyecto_y_verificacion_de_requisitos.txt`, que se conserva aparte sin cambios). Ese plan describía un stack que **no** fue el que se implementó: FastAPI, Redis, JWT, Argon2, UID 1001, organización "AgroData Andes". Aquí cada afirmación coincide con el repositorio e indica dónde se comprueba.

## 1. Contexto y sello de autenticidad

- **Organización ficticia:** AgroAnálisis Sugamuxi, un laboratorio de análisis de suelos de la provincia de Sugamuxi (Boyacá).
- **Necesidad:** recibir resultados de laboratorio (`.csv`) e informes de campo (`.txt`), procesarlos en segundo plano y entregar a cada agricultor solo sus resultados, con aislamiento entre usuarios, control de recursos y trazabilidad completa.

### 1.1 Roles y matriz de permisos (`app/permisos.py`)

| Rol técnico | Rol en el laboratorio | Puede |
|---|---|---|
| `usuario` | Agricultor | subir archivos; ver, descargar y eliminar **sus** trabajos |
| `operador` | Técnico de laboratorio | lo anterior, más ver el estado y los errores de **todos** los trabajos (Operación), el panel de Recursos y reprocesar fallidos. **No** descarga archivos ajenos |
| `admin` | Coordinador | todo: descargar resultados y originales ajenos, eliminar cualquier trabajo, gestionar usuarios, ver, exportar y verificar la auditoría, y ver las reglas |

### 1.2 Regla de negocio

**Activa por defecto:**
- Cada agricultor tiene como máximo **3 trabajos en cola o en proceso** (`cuota_trabajos_activos`).
- Un trabajo **completado o en ejecución solo lo elimina el coordinador** (`bloquear_borrado_finalizados`).

La regla propuesta en el plan inicial **se conserva como alternativa preparada**, lista para activarse con una línea:
- `cabecera_csv_obligatoria`: el CSV debe empezar con la cabecera exacta `lote_id,fecha,medicion` o se rechaza antes de la cola.
- `bloquear_descarga_originales_ajenos`: el original solo lo descarga el dueño o el coordinador; el técnico supervisa pero no descarga originales ajenos.

Hay además otras 5 reglas preparadas: rangos agronómicos, tamaño por rol, ventana de recepción, trabajos confidenciales y límite de reprocesos. Todas viven en `app/reglas_negocio.py` y tienen pruebas en `pruebas/test_reglas_negocio.py`. El docente puede asignar o cambiar la regla, y el cambio es quirúrgico (ver `GUIA_RETOS_SUSTENTACION.md`).

### 1.3 Carga de prueba propia (`datos_prueba/`, generada con `generar_datos.py` y semilla fija)

| Archivo | Tamaño | Resultado esperado |
|---|---|---|
| `01_suelos_lote_A.csv` | 1,2 KB | completado, con clasificación de pH |
| `02_suelos_lote_B.csv` | 91 KB | completado (2 000 muestras) |
| `03_lluvias_2026.csv` | 0,3 KB | completado (sin columna pH) |
| `04_informe_visita_campo.txt` | 0,6 KB | completado (conteo de palabras) |
| `05_bitacora_laboratorio.txt` | 163 KB | completado (3 000 líneas) |
| `06_invalido_columnas.csv` | 50 B | **fallido** (la fila 3 tiene una columna de menos) |
| `07_invalido_programa.exe` | 68 B | **rechazado** (extensión no permitida) |
| `08_invalido_binario.txt` | 512 B | **rechazado** (binario disfrazado) |
| `archivo_grande.txt` | 3 MB | **rechazado** (supera 2 MB) |
| `09_sello_manipular.csv` y `10`–`14` | — | demostración del sello y de cada regla alternativa |

### 1.4 Decisión de arquitectura
**La cola de trabajos es la tabla `trabajos` de PostgreSQL**, que se consume con `SELECT … FOR UPDATE SKIP LOCKED` (`worker/worker.py`), en lugar de Redis.
- Es un componente menos que asegurar.
- La cola es persistente en el volumen de la base de datos.
- Dos workers nunca toman el mismo trabajo. Se verificó con `--scale worker=2`: 15 y 15 trabajos y throughput duplicado.

El worker procesa en un proceso hijo con límite de tiempo, dentro de un contenedor con límites de cgroups.

### 1.5 Prueba de rendimiento (`pruebas/prueba_carga.py`)
Se envían N trabajos (por defecto 30, rotando los 5 archivos válidos, unos 1,5 MB en total) con concurrencia C (por defecto 4 hilos). La prueba mide el tiempo total, el procesamiento promedio por trabajo y el throughput, y guarda un informe `.md` y `.csv` en `resultados/`. Mientras corre, se mide el consumo con `docker stats` o el panel **Recursos**.

### 1.6 Elemento de auditoría
- La tabla `auditoria` registra fecha, usuario, rol, acción, recurso, resultado (permitido, denegado o error), detalle, IP y origen.
- La vista `/admin/auditoria` tiene filtros por usuario, acción, resultado y fechas.
- Se puede exportar a CSV, con protección contra *CSV injection*.
- Cada evento está **encadenado con SHA-256** por un trigger de PostgreSQL y la tabla es de solo inserción. Esto se verifica en `/admin/auditoria/verificar`.

Algunas acciones registradas: `login_ok`, `login_fallido`, `subir`, `archivo_rechazado`, `regla_<nombre>`, `procesar_ok`, `procesar_error`, `integridad_comprometida`, `descargar`, `cambiar_rol`, `acceso_denegado` y `verificar_cadena`.

## 2. Arquitectura y stack real

- **Nube y modelo:** AWS Academy, EC2, Ubuntu Server **24.04 LTS** (IaaS, porque se administran usuarios del SO, SSH, firewall, servicios y cgroups).
- **4 contenedores** con Docker Compose:
  1. `proxy`: nginx sin root (UID 101). Única entrada, solo el **puerto 80**. CSP, cabeceras de seguridad y límite de 10 intentos de login por minuto.
  2. `app`: **Flask 3.1 + Gunicorn** (2 procesos), UID 10001. Sesión con **cookie firmada** (HttpOnly, SameSite=Lax), contraseñas con **scrypt**, token CSRF, roles y auditoría.
  3. `worker`: Python, UID 10001. Procesa la cola, verifica la cadena de custodia y envía un latido.
  4. `db`: PostgreSQL 16. Usuarios, trabajos (cola) y auditoría. Sin puertos publicados.
- **Redes:** `edge` (solo el proxy, con salida), `frontend` (proxy ↔ app, `internal`) y `backend` (app ↔ worker ↔ db, `internal`).
- **Volúmenes:** `db_data` (PostgreSQL) y `datos` (`/data/uploads/<id_usuario>/` y `/data/results/<id_usuario>/`).

## 3. Verificación de requisitos técnicos (guía 2.1–2.5)

**2.1 Nube, arquitectura y contenedores**
- AWS Academy EC2 con modelo IaaS justificado (README, sección 1).
- 4 contenedores y una red interna. Solo el proxy publica el puerto 80; la db no tiene `ports`.
- Persistencia con 2 volúmenes. Diagrama en Mermaid en el README.

**2.2 Usuarios, autenticación y autorización**
- Credenciales individuales y 3 roles.
- Control en el servidor: `@requiere(...)` en cada ruta (`app/seguridad.py`), con el rol recargado de la BD en cada petición.
- **Aislamiento:** `obtener_trabajo_autorizado()` en las 6 rutas que reciben un id. Responde 404 y lo audita. Además, hay carpetas separadas por usuario y nombres de archivo UUID.
- Hash **scrypt**. Los secretos solo están en `.env` (permisos 600, en `.gitignore` y `.dockerignore`), y app y worker no reciben la contraseña del superusuario de la BD.

**2.3 Sistema operativo y hardening**
- **Contenedores:** usuario no root (UID 10001 en app y worker, 101 en el proxy, 70 en la db), raíz de solo lectura, `cap_drop: ALL` (la db conserva solo 5 capacidades) y `no-new-privileges`.
- **Archivos:** `/data` con permisos 700 y archivos con 600 (`umask 077`).
- **Host:** cuenta de servicio `plataforma`, SSH solo con llave y sin root, UFW + Security Group (22 desde la IP de administración, 80 público), fail2ban, `unattended-upgrades` y servicios innecesarios deshabilitados (cups, avahi, bluetooth, ModemManager).
- **Base de datos:** usuarios `agro_web` y `agro_worker` sin superusuario y con GRANT mínimos.

**2.4 Procesos, recursos y observabilidad**
- `docker compose ps/top`, `docker stats` y el panel **Recursos**, que lee cgroups v2 (memoria, CPU y procesos frente al límite) e incluye una frase de interpretación.
- Límites en los 4 servicios, que suman 832 MB.
- Healthchecks en los 4, incluido el latido del worker.
- **Recuperación:** `restart: unless-stopped` y recuperación segura de trabajos interrumpidos con `MAX_INTENTOS` y backoff.

**2.5 Procesamiento y almacenamiento**
- Procesamiento asíncrono: la respuesta es inmediata y el estado se actualiza en vivo cada 2 s.
- El resultado se guarda en JSON e incluye el SHA-256.
- **Validación:** solo `.csv` y `.txt`, **2 MB** como máximo, UTF-8 sin bytes nulos, y hasta 50 000 filas y 100 columnas. La cabecera obligatoria es una regla alternativa, no la validación por defecto.
- Ciclo de estados `pendiente → en_ejecucion → completado | fallido`.

## 4. Preparación de los retos sorpresa

| Reto | Dónde se resuelve |
|---|---|
| 1 · Nuevo usuario | **Usuarios** (coordinador) o `flask --app app crear-usuario`; 403 en las rutas de administración |
| 2 · Cambio de permisos | una línea en `app/permisos.py` |
| 3 · Aislamiento | `obtener_trabajo_autorizado()` en `app/seguridad.py` |
| 4 · Recursos | `mem_limit` / `memswap_limit` / `cpus` en `docker-compose.yml` (no `deploy.resources`) |
| 5 · Recuperación | los trabajos quedan en PostgreSQL (no en Redis); al reiniciar, el worker los recupera y lo registra en logs y auditoría |
| 6 · Auditoría | función única `auditar()` en `app/auditoria.py` |

## 5. Correcciones respecto al plan inicial

| El plan inicial decía | Lo implementado |
|---|---|
| AgroData Andes, estaciones climáticas | AgroAnálisis Sugamuxi, laboratorio de suelos |
| Técnico de campo / Supervisor / Infraestructura | Agricultor / Técnico de laboratorio / Coordinador |
| FastAPI, JWT, Bcrypt/Argon2 | Flask + Gunicorn, cookie de sesión firmada, scrypt |
| Redis como cola, 5 contenedores, red `app_net` | PostgreSQL como cola, 4 contenedores, redes edge/frontend/backend |
| Puertos 80/443 | solo 80 (sin HTTPS, limitación documentada) |
| UID 1001, `appuser`, directorios 750 | UID 10001 (`app`), `/data` 700, archivos 600 |
| `permissions.py`, `log_audit_event()`, `owner_id` | `permisos.py`, `auditar()`, `usuario_id` |
| Tabla `audit_logs`, ruta `/admin/audit`, acciones en mayúsculas | tabla `auditoria`, ruta `/admin/auditoria`, acciones en minúsculas, con cadena de hashes |
| 5 MB y cabecera obligatoria | 2 MB, UTF-8; la cabecera es una regla alternativa |
| `deploy.resources.limits` | `mem_limit`, `memswap_limit`, `cpus` y `pids_limit` en todos los servicios |
| 20 trabajos de 1 MB concurrentes | `prueba_carga.py` parametrizable (`--trabajos`, `--concurrencia`, `--archivos`) |
| El admin descarga originales ajenos (sin ruta implementada) | ruta `/trabajos/<id>/original` protegida por permiso, aislamiento y regla opcional |
| snapd/cups | cups, avahi-daemon, bluetooth y ModemManager |
| Diagrama "se incluirá" | diagrama Mermaid en el README |
