# Guía para el equipo: cómo probar AgroAnálisis en tu computador

Con esta guía cada integrante puede levantar la plataforma completa en su propio computador con Docker, recorrer la demostración que pide el profe y practicar los retos. El servidor de AWS vive en el laboratorio de Felix y solo está encendido cuando él inicia el lab; para practicar no hace falta.

## 1. Lo que necesitas (una sola vez)

- **Docker Desktop:** https://www.docker.com/products/docker-desktop/ — instálalo, ábrelo y espera a que diga *Engine running*.
- **Python 3** (solo para las pruebas automáticas): https://www.python.org/downloads/ — en Windows marca *Add Python to PATH*.
- **Git** (en Windows trae *Git Bash*, que se usa para los scripts `.sh`): https://git-scm.com/downloads
- El código: `git clone https://github.com/FelixSiachoque/agroanalisis`. Si alguien comparte un ZIP, debe generarlo con `git archive -o agroanalisis.zip HEAD`, que **no** incluye el `.env`; nunca comprimiendo la carpeta a mano.

## 2. Levantar la plataforma (unos 5 minutos)

Abre una terminal (PowerShell en Windows, Terminal en Mac/Linux) **dentro de la carpeta `agroanalisis`**.

**a) Crear el archivo de secretos `.env`** (claves aleatorias y permisos 600)

- Windows: abre **Git Bash** en la carpeta y ejecuta `bash scripts/generar_env.sh`
- Mac/Linux: `./scripts/generar_env.sh`

El script muestra las contraseñas de `coordinador` y de las cuentas demo; también se consultan con `grep PASSWORD .env`. El archivo `.env` es solo para tu computador y nunca se sube a GitHub. No uses contraseñas inventadas y compartidas por chat.

**c) Construir y arrancar los 4 contenedores**

```bash
docker compose up -d --build --wait
docker compose ps
```
Los cuatro (`proxy`, `app`, `worker`, `db`) deben salir `healthy`. La primera vez tarda 3–5 minutos descargando imágenes.

> Si ya tenías el proyecto levantado con una versión vieja (sin `APP_DB_PASSWORD` en el `.env`), ejecuta `bash scripts/aplicar_migraciones.sh`: actualiza la base sin borrar datos. O empieza de cero con `docker compose down -v`.

**d) Crear las cuentas de demostración**

```bash
bash scripts/crear_usuarios_demo.sh
```

**e) Abrir** http://localhost

| Usuario | Rol | Contraseña |
|---|---|---|
| coordinador | Coordinador (admin) | la de `ADMIN_PASSWORD` |
| tecnico1 | Técnico (operador) | la de `DEMO_PASSWORD` |
| agricultor1 | Agricultor (usuario) | la de `DEMO_PASSWORD` |
| agricultor2 | Agricultor (usuario) | la de `DEMO_PASSWORD` |

> Si el puerto 80 está ocupado: en `docker-compose.yml` cambia `"80:8080"` por `"8080:8080"`, ejecuta `docker compose up -d` y entra a http://localhost:8080

## 3. Recorrido de la demostración (igual al checklist del profe)

Los archivos para subir están en la carpeta `datos_prueba/`. Ve marcando cada punto.

- [ ] **Contenedores:** `docker compose ps` y explicar qué hace cada uno (proxy = única entrada, app = web, worker = procesa, db = datos).
- [ ] **Recursos:** `docker stats --no-stream` — señalar la columna LIMIT del worker (256 MiB). Luego, como `tecnico1`, abrir **Recursos** y leer la frase de interpretación.
- [ ] **Login con dos roles:** entrar como `agricultor1` y luego como `coordinador`. El menú cambia según el rol.
- [ ] **Permitido / denegado:** como `agricultor1`, escribir a mano `http://localhost/admin/usuarios` → *Error 403*.
- [ ] **Procesamiento:** como `agricultor1`, subir `01_suelos_lote_A.csv`. Ver cómo pasa de *Pendiente* → *En ejecución* → *Completado* sin recargar (la página se actualiza sola) y descargar el resultado JSON (trae la clasificación de pH). En el detalle se ve el **comprobante de custodia** (SHA-256).
- [ ] **Archivo inválido:** subir `07_invalido_programa.exe` → rechazado. Subir `06_invalido_columnas.csv` → termina *fallido* con la causa.
- [ ] **Aislamiento:** fijarse en el número del trabajo de `agricultor1` (por ejemplo #1). Entrar como `agricultor2` y abrir `http://localhost/trabajos/1` → *Error 404*.
- [ ] **Regla de negocio (cuota):** como `agricultor2`, subir 4 archivos seguidos. El 4.º se rechaza: "máximo 3 trabajos en cola por agricultor". Las reglas vigentes se ven en el panel y, como coordinador, en **Reglas**.
- [ ] **Persistencia:** `docker compose restart` (o `docker compose down` y `docker compose up -d`). Volver a entrar: los trabajos siguen ahí.
- [ ] **Recuperación del worker:** `docker compose stop worker`, subir un archivo (queda *pendiente*), `docker compose start worker` y `docker compose logs --tail 20 worker`.
- [ ] **Hardening:** `docker compose exec app id` → `uid=10001(app)`, no root. Mostrar en `docker-compose.yml`: `read_only`, `cap_drop: [ALL]`, `mem_limit`, y que `db` no tiene `ports`.
- [ ] **Auditoría:** como `coordinador`, menú *Auditoría*: filtrar por `agricultor2` y exportar el CSV. Filtrar resultado *denegado*: se ven `acceso_denegado` y `regla_cuota_trabajos_activos`. Pulsar **Verificar cadena** → "Cadena íntegra".
- [ ] **Sello de autenticidad:** `bash scripts/demo_sello.sh alterar 7`, luego `bash scripts/demo_sello.sh verificar` (cadena rota en el #7) y `bash scripts/demo_sello.sh restaurar 7`.
- [ ] **Repositorio sin secretos:** mostrar `.gitignore` (incluye `.env`) y que en GitHub no existe `.env`.

## 4. Pruebas automáticas (opcional, 3 minutos)

En **Git Bash** (Windows) o una terminal (Mac/Linux), dentro de la carpeta:
```bash
pip install requests
python datos_prueba/generar_datos.py
python -m unittest pruebas/test_reglas_negocio.py                 # 26 pruebas, sin Docker
export CLAVE_ADMIN="$(grep '^ADMIN_PASSWORD=' .env | cut -d= -f2-)" CLAVE_DEMO="$(grep '^DEMO_PASSWORD=' .env | cut -d= -f2-)"
python pruebas/pruebas_funcionales.py http://localhost --docker    # debe terminar en "67 de 67 pruebas pasaron"
```
Si una corrida falla con 429, espera un minuto: nginx limita a 10 logins por minuto.

## 5. Practicar los retos sorpresa

Abre `GUIA_RETOS_SUSTENTACION.md`. Cada reto se hace igual en tu computador que en el servidor; la única diferencia es que en local no usas SSH: los comandos `docker compose ...` se ejecutan directo en la carpeta del proyecto.

Recomendación: que **cada integrante haga los 6 retos al menos una vez** sin mirar la solución, cronometrando 10 minutos. El profe elige al azar quién pasa.

Lo más importante para recordar:
- Cambias un `.py` → `docker compose up -d --build app` (con solo `restart` el cambio NO se aplica).
- Cambias `docker-compose.yml` → `docker compose up -d`.
- Para deshacer un cambio: `git checkout -- archivo`.
- Para cambiar la regla de negocio: sección "Cambio de regla de negocio de último minuto" de la guía.

## 6. Apagar y limpiar

```bash
docker compose down        # apaga, conserva los datos
docker compose down -v     # apaga y BORRA los datos (empezar de cero)
```

## 7. El servidor en AWS (solo Felix)

El despliegue real está en el Learner Lab de Felix (instancia `agroanalisis`, apagada para no gastar créditos). Para encenderlo: *Start Lab* → consola AWS → EC2 → seleccionar `agroanalisis` → *Iniciar instancia*. La IP pública cambia en cada encendido; se consulta en EC2 o con el comando que está en `GUIA_RETOS_SUSTENTACION.md`. Si el servidor tenía una versión anterior: `git pull && ./scripts/aplicar_migraciones.sh`. Todos los contenedores arrancan solos.

Si alguien quiere desplegar su propia copia en su Learner Lab: abrir CloudShell en su consola y ejecutar
```bash
curl -fsSO https://raw.githubusercontent.com/FelixSiachoque/agroanalisis/main/infra/crear_infra_aws.sh && bash crear_infra_aws.sh
```
En unos 8 minutos queda todo funcionando en su propia IP.
