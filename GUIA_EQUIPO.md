# Guía para el equipo: cómo probar AgroAnálisis en tu computador

Con esta guía cada integrante puede levantar la plataforma completa en su propio computador con Docker, recorrer la demostración que pide el profe y practicar los retos. El servidor de AWS vive en el laboratorio de Felix y solo está encendido cuando él inicia el lab; para practicar no hace falta.

## 1. Lo que necesitas (una sola vez)

- **Docker Desktop:** https://www.docker.com/products/docker-desktop/ — instálalo, ábrelo y espera a que diga *Engine running*.
- **Python 3** (solo para las pruebas automáticas): https://www.python.org/downloads/ — en Windows marca *Add Python to PATH*.
- El código: descomprime `agroanalisis.zip` o clona `https://github.com/FelixSiachoque/agroanalisis`.

## 2. Levantar la plataforma (unos 5 minutos)

Abre una terminal (PowerShell en Windows, Terminal en Mac/Linux) **dentro de la carpeta `agroanalisis`**.

**a) Crear el archivo de secretos `.env`**

- Windows: `copy .env.example .env` y luego `notepad .env`
- Mac/Linux: `./scripts/generar_env.sh` (genera claves aleatorias y las muestra; salta el paso b)

**b) Editar `.env`** y cambiar los 4 valores que dicen `CAMBIAR_...`:

```
POSTGRES_PASSWORD=ClaveBaseDatos2026
SECRET_KEY=una-frase-larga-cualquiera-1234567890
ADMIN_PASSWORD=Coordinador2026
DEMO_PASSWORD=Demo2026
```
(Son claves solo para tu computador. El archivo `.env` nunca se sube a GitHub.)

**c) Construir y arrancar los 4 contenedores**

```bash
docker compose up -d --build
docker compose ps
```
Los cuatro (`proxy`, `app`, `worker`, `db`) deben salir `running` y `app` y `db` `healthy`. La primera vez tarda 3–5 minutos descargando imágenes.

**d) Crear las cuentas de demostración**

```bash
docker compose exec app flask --app app crear-demo
```

**e) Abrir** http://localhost

| Usuario | Rol | Contraseña |
|---|---|---|
| coordinador | admin | la de `ADMIN_PASSWORD` |
| tecnico1 | operador | la de `DEMO_PASSWORD` |
| agricultor1 | usuario | la de `DEMO_PASSWORD` |
| agricultor2 | usuario | la de `DEMO_PASSWORD` |

> Si el puerto 80 está ocupado: en `docker-compose.yml` cambia `"80:8080"` por `"8080:8080"`, ejecuta `docker compose up -d` y entra a http://localhost:8080

## 3. Recorrido de la demostración (igual al checklist del profe)

Los archivos para subir están en la carpeta `datos_prueba/`. Ve marcando cada punto.

- [ ] **Contenedores:** `docker compose ps` y explicar qué hace cada uno (proxy = única entrada, app = web, worker = procesa, db = datos).
- [ ] **Recursos:** `docker stats --no-stream` — señalar la columna LIMIT del worker (256 MiB) y explicar para qué sirve.
- [ ] **Login con dos roles:** entrar como `agricultor1` y luego como `coordinador`. El menú cambia según el rol.
- [ ] **Permitido / denegado:** como `agricultor1`, escribir a mano `http://localhost/admin/usuarios` → *Error 403*.
- [ ] **Procesamiento:** como `agricultor1`, subir `01_suelos_lote_A.csv`. Ver cómo pasa de *pendiente* → *en_ejecucion* → *completado* (botón actualizar) y descargar el resultado JSON (trae la clasificación de pH).
- [ ] **Archivo inválido:** subir `07_invalido_programa.exe` → rechazado. Subir `06_invalido_columnas.csv` → termina *fallido* con la causa.
- [ ] **Aislamiento:** fijarse en el número del trabajo de `agricultor1` (por ejemplo #1). Entrar como `agricultor2` y abrir `http://localhost/trabajos/1` → *Error 404*.
- [ ] **Regla de negocio (cuota):** como `agricultor2`, subir 4 archivos seguidos. El 4.º se rechaza: "máximo 3 trabajos en cola por agricultor".
- [ ] **Persistencia:** `docker compose restart` (o `docker compose down` y `docker compose up -d`). Volver a entrar: los trabajos siguen ahí.
- [ ] **Recuperación del worker:** `docker compose stop worker`, subir un archivo (queda *pendiente*), `docker compose start worker` y `docker compose logs --tail 20 worker`.
- [ ] **Hardening:** `docker compose exec app id` → `uid=10001(app)`, no root. Mostrar en `docker-compose.yml`: `read_only`, `cap_drop: [ALL]`, `mem_limit`, y que `db` no tiene `ports`.
- [ ] **Auditoría:** como `coordinador`, menú *Auditoría*: filtrar por `agricultor2` y exportar el CSV. Se ven los `acceso_denegado` y `cuota_excedida` en rojo.
- [ ] **Repositorio sin secretos:** mostrar `.gitignore` (incluye `.env`) y que en GitHub no existe `.env`.

## 4. Pruebas automáticas (opcional, 2 minutos)

Windows (PowerShell):
```powershell
pip install requests
python datos_prueba/generar_datos.py
$env:CLAVE_ADMIN="Coordinador2026"; $env:CLAVE_DEMO="Demo2026"
python pruebas/pruebas_funcionales.py http://localhost
```
Mac/Linux:
```bash
pip3 install requests
python3 datos_prueba/generar_datos.py
CLAVE_ADMIN=... CLAVE_DEMO=... python3 pruebas/pruebas_funcionales.py http://localhost
```
Debe terminar en **"27 de 27 pruebas pasaron"**. (Usa tus claves del `.env`. Si ya hiciste el recorrido a mano y algún agricultor tiene 3 trabajos en cola, espera a que terminen antes de correrlas.)

## 5. Practicar los retos sorpresa

Abre `RETOS.md`. Cada reto se hace igual en tu computador que en el servidor; la única diferencia es que en local no usas SSH: los comandos `docker compose ...` se ejecutan directo en la carpeta del proyecto.

Recomendación: que **cada integrante haga los 6 retos al menos una vez** sin mirar la solución, cronometrando 10 minutos. El profe elige al azar quién pasa.

Lo más importante para recordar:
- Cambias un `.py` → `docker compose up -d --build app` (con solo `restart` el cambio NO se aplica).
- Cambias `docker-compose.yml` → `docker compose up -d`.
- Para deshacer un cambio: `git checkout -- archivo` (si clonaste de GitHub) o vuelve a descomprimir el ZIP.

## 6. Apagar y limpiar

```bash
docker compose down        # apaga, conserva los datos
docker compose down -v     # apaga y BORRA los datos (empezar de cero)
```

## 7. El servidor en AWS (solo Felix)

El despliegue real está en el Learner Lab de Felix (instancia `agroanalisis`, apagada para no gastar créditos). Para encenderlo: *Start Lab* → consola AWS → EC2 → seleccionar `agroanalisis` → *Iniciar instancia*. La IP pública cambia en cada encendido; se consulta en EC2 o con el comando que está en `RETOS.md`. Todos los contenedores arrancan solos.

Si alguien quiere desplegar su propia copia en su Learner Lab: abrir CloudShell en su consola y ejecutar
```bash
curl -sO https://raw.githubusercontent.com/FelixSiachoque/agroanalisis/main/infra/crear_infra_aws.sh && bash crear_infra_aws.sh
```
En unos 8 minutos queda todo funcionando en su propia IP.
