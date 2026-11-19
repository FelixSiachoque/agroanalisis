# Guía de retos sorpresa

Cada reto dura 5 a 10 minutos y lo hace **un solo integrante**. Todo se hace en el servidor, dentro de `/opt/agroanalisis`, como usuario `plataforma`:

```bash
ssh -i labsuser.pem ubuntu@IP_PUBLICA
sudo -iu plataforma
cd /opt/agroanalisis
```

## Regla de oro: ¿qué hay que reiniciar después de un cambio?

| Si cambias… | Ejecuta |
|---|---|
| Código Python (`app/*.py`, `app/templates/*`) | `docker compose up -d --build app` |
| Código del worker (`worker/*.py`) | `docker compose up -d --build worker` |
| `docker-compose.yml` (límites, puertos, variables) | `docker compose up -d` |
| `.env` | `docker compose up -d` (recrea los contenedores que lo usan) |
| `nginx/nginx.conf` | `docker compose restart proxy` |

El código se copia **dentro** de la imagen. Por eso, si solo haces `restart` después de editar un `.py`, el cambio **no** se aplica: hay que usar `--build`.

Para editar archivos usa `nano archivo`. Se guarda con `Ctrl+O` y Enter y se sale con `Ctrl+X`.

## Los 3 archivos que tienes que conocer de memoria

1. **`app/permisos.py`**: el diccionario `PERMISOS` dice qué puede hacer cada rol. Casi todos los retos de permisos se resuelven aquí, cambiando una línea.
2. **`app/app.py`**:
   - `@requiere("permiso")`, encima de cada ruta, revisa el permiso en el servidor.
   - `obtener_trabajo_autorizado(id, permiso_global)` es la comprobación de aislamiento: deja pasar si eres el dueño **o** si tu rol tiene el permiso global.
   - `auditar(usuario, accion, detalle, ip())` escribe un evento de auditoría.
3. **`docker-compose.yml`**: aquí están los límites (`mem_limit`, `cpus`), los puertos, las redes y los volúmenes.

---

## Reto 1 · Nuevo usuario sin acceso administrativo

**Opción A (navegador):**
1. Entra como `coordinador`, ve a **Usuarios** y crea `prueba1`, con contraseña `Prueba2026` y rol **usuario**.
2. Cierra sesión y entra como `prueba1`.
3. Escribe a mano en la barra del navegador `http://IP/admin/usuarios`. Debe salir **Error 403**.

**Opción B (terminal):**
```bash
docker compose exec app flask --app app crear-usuario prueba1 usuario
# pide la contraseña dos veces
```

**Cómo verificarlo:**
- Como `prueba1`, abre `/admin/usuarios` → 403, y `/operacion` → 403.
- Como `coordinador`, ve a **Auditoría** y filtra por usuario `prueba1`: aparecen `crear_usuario`, `login_ok` y `acceso_denegado` con su fecha.

**Qué decir:** "El menú se oculta en la interfaz, pero la protección real es el decorador `@requiere("gestionar_usuarios")` en el servidor. Por eso, aunque escriba la URL a mano, responde 403. El rol se lee de la base de datos en cada petición."

---

## Reto 2 · Dar una operación al Operador sin dársela al Usuario

El cambio es **una línea en `app/permisos.py`**.

**Ejemplo típico:** "que el operador pueda descargar resultados de cualquier agricultor".
```bash
nano app/permisos.py
```
Agrega `"descargar_todos",` dentro del bloque de `"operador"`:
```python
    "operador": {
        "subir",
        "ver_propios",
        "ver_todos",
        "reprocesar",
        "descargar_todos",      # ← NUEVO
    },
```
```bash
docker compose up -d --build app
```

**Cómo verificarlo:**
- **Prueba positiva:** como `tecnico1`, ve a **Operación**, abre un trabajo completado de `agricultor1` y descárgalo. Funciona (antes daba 404).
- **Prueba negativa:** como `agricultor2`, abre `http://IP/trabajos/<id_de_agricultor1>/descargar`. Sigue dando 404.

**Otros ejemplos con la misma receta (agregar el permiso al bloque `"operador"`):**

| Lo que pida el profe | Permiso que agregas al operador |
|---|---|
| Ver la auditoría | `"ver_auditoria"` |
| Eliminar trabajos de cualquiera | `"eliminar_cualquiera"` |
| Descargar resultados ajenos | `"descargar_todos"` |

**Si piden una operación que no existe**, por ejemplo "el operador puede exportar la auditoría, pero no verla":
1. Inventa un permiso nuevo, por ejemplo `"exportar_auditoria"`, y agrégalo a `admin` y a `operador` en `permisos.py`.
2. En `app.py`, cambia el decorador de esa ruta:
   ```python
   @app.get("/admin/auditoria.csv")
   @requiere("exportar_auditoria")      # antes: ver_auditoria
   ```
3. Ejecuta `docker compose up -d --build app`.

**Qué decir:** "Toda la matriz está en un solo diccionario. Hice un cambio mínimo: solo el rol operador recibe el permiso, el rol usuario queda igual. Lo probé positiva y negativamente."

---

## Reto 3 · Corregir el aislamiento (archivo de otro usuario)

Lo más probable es que el profe **dañe** la comprobación y te pida arreglarla. Todo está en una sola función de `app/app.py`:

```bash
grep -n "def obtener_trabajo_autorizado" -A 14 app/app.py
```

Así debe quedar (versión correcta):
```python
def obtener_trabajo_autorizado(trabajo_id, permiso_global):
    t = consulta("SELECT t.*, u.usuario AS dueno FROM trabajos t JOIN usuarios u ON u.id = t.usuario_id "
                 "WHERE t.id = %s", (trabajo_id,), uno=True)
    es_dueno = t is not None and t["usuario_id"] == g.usuario["id"]
    if t is None or not (es_dueno or puede(g.usuario["rol"], permiso_global)):
        auditar(g.usuario["usuario"], "acceso_denegado", f"trabajo={trabajo_id} ruta={request.path}", ip())
        abort(404)
    return t
```

**Cosas que revisar si alguien la dañó:**
- Que `es_dueno` compare `t["usuario_id"]` con `g.usuario["id"]` (no con el id del trabajo ni con `True`).
- Que el `if` tenga el `not (...)` y que llame a `abort(404)`.
- Que cada ruta (`detalle`, `descargar`, `eliminar`, `api_trabajo`) **use** esta función y no haga su propio `consulta(... WHERE id = %s)` sin revisar el dueño.
- Con `grep -n "obtener_trabajo_autorizado" app/app.py` ves en qué rutas se usa.

Si te piden **agregar** la comprobación a una ruta nueva, reemplaza la consulta directa por:
```python
t = obtener_trabajo_autorizado(trabajo_id, "ver_todos")
```

Aplica con `docker compose up -d --build app`.

**Cómo verificarlo:** entra como `agricultor2` y abre `http://IP/api/trabajos/<id_de_agricultor1>` → 404. Luego, en **Auditoría**, aparece `acceso_denegado` de `agricultor2`.

**Qué decir:** "La validación se hace en el servidor con el id del usuario de la sesión, no con algo que mande el navegador. Respondo 404 en lugar de 403 para no revelar que el trabajo existe."

---

## Reto 4 · Cambiar el límite de memoria o CPU

```bash
nano docker-compose.yml
```
En el servicio `worker`, cambia por ejemplo:
```yaml
    mem_limit: 128m        # antes 256m
    cpus: 0.25             # antes 0.5
```
```bash
docker compose up -d worker          # recrea solo el worker con la nueva configuración
```

**Cómo verificarlo:**
```bash
docker inspect agroanalisis-worker-1 --format 'Memoria={{.HostConfig.Memory}} bytes  CPU={{.HostConfig.NanoCpus}}'
docker stats --no-stream             # la columna "LIMIT" muestra 128MiB
```
128 MB equivale a 134217728 bytes, y 0.25 CPU a 250000000 NanoCpus.

**Qué decir:** "El límite evita que un trabajo pesado o un error consuma toda la RAM del servidor y tumbe la app y la base de datos. Si el proceso supera el límite, el kernel (cgroups) lo mata solo a él (OOM) y Docker lo reinicia por `restart: unless-stopped`."

---

## Reto 5 · Detener y recuperar el worker

```bash
docker compose stop worker
```
1. En el navegador, sube un archivo: queda en **pendiente** y no avanza, porque no hay quien lo procese.
2. Inicia de nuevo el worker:
   ```bash
   docker compose start worker
   docker compose logs --tail 20 worker
   ```
3. En los logs aparece `Worker iniciado`, luego `Trabajo N: inicia` y `Trabajo N: completado`. En el navegador el trabajo pasa a **completado**.

**Variante "caída brusca"** (para mostrar la recuperación de trabajos interrumpidos):
```bash
docker compose kill worker           # lo mata a la fuerza mientras procesa
docker compose start worker
docker compose logs --tail 20 worker # "Recuperados 1 trabajos interrumpidos: [N]"
```

**Qué decir:** "Los trabajos están en PostgreSQL, no en la memoria del worker, así que no se pierden. Con `stop` el worker recibe SIGTERM y termina el trabajo actual antes de salir. Si muere de golpe, al arrancar devuelve a la cola los trabajos que quedaron `en_ejecucion`."

---

## Reto 6 · Agregar un registro de auditoría

**Ya se auditan:** login_ok, login_fallido, logout, subir, archivo_rechazado, cuota_excedida, descargar, eliminar, reprocesar, crear_usuario, cambiar_rol, activar, desactivar, acceso_denegado, exportar_auditoria, procesar_ok, procesar_error y recuperar_trabajos.

Si piden una acción nueva, por ejemplo "registrar cuando alguien **ve el detalle** de un trabajo", es una línea en `app/app.py`:
```python
@app.get("/trabajos/<int:trabajo_id>")
@requiere("ver_propios")
def detalle(trabajo_id):
    t = obtener_trabajo_autorizado(trabajo_id, "ver_todos")
    auditar(g.usuario["usuario"], "ver_detalle", f"trabajo={trabajo_id}", ip())   # ← NUEVO
    return render_template("detalle.html", t=t)
```
```bash
docker compose up -d --build app
```

**Cómo verificarlo:** abre un trabajo en el navegador y luego ve a **Auditoría**, filtrando la acción `ver_detalle`. También se puede ver en los logs:
```bash
docker compose logs app | grep ver_detalle
```

La receta para cualquier acción es la misma: busca la función de esa ruta y agrega `auditar(g.usuario["usuario"], "nombre_accion", "detalle", ip())` justo después de que la acción ocurra con éxito. La fecha y la hora las pone PostgreSQL automáticamente (`DEFAULT now()`).

---

## Si algo sale mal (diagnóstico rápido)

```bash
docker compose ps                         # ¿algún contenedor "exited" o "unhealthy"?
docker compose logs --tail 40 app         # error de Python: muestra archivo y línea
git diff                                  # qué cambié exactamente
git checkout -- app/app.py                # deshacer mis cambios en un archivo
```
Un error de indentación en Python hace que la app no arranque. En ese caso `docker compose logs app` muestra `IndentationError` con la línea.

Si no terminas, **explica** qué intentaste, en qué archivo está el problema y cómo lo resolverías. El profe evalúa el diagnóstico, no la sintaxis.

## Preguntas que pueden hacer en la sustentación

- **¿Por qué no usaron Redis?** Porque PostgreSQL ya garantiza que dos workers no tomen el mismo trabajo (`FOR UPDATE SKIP LOCKED`). Es un componente menos que asegurar, y la cola sobrevive a reinicios porque está en el volumen de la base de datos.
- **¿IaaS o PaaS?** IaaS (EC2). Necesitamos administrar el sistema operativo (usuarios, SSH, firewall, actualizaciones), que es el objetivo de la materia.
- **¿Qué puertos están abiertos?** El 22 (SSH, solo desde nuestra IP) y el 80 (web, vía nginx). La base de datos no publica ningún puerto.
- **¿Por qué el worker no tiene Internet?** Está solo en la red `backend`, que es `internal: true`. Si un archivo malicioso lograra ejecutar código, no podría sacar datos hacia fuera.
- **¿Cómo guardan las contraseñas?** Con hash scrypt y sal (`werkzeug.security.generate_password_hash`). Nunca en texto plano.
- **¿Dónde están los secretos?** En `.env`, con permisos 600. Está en `.gitignore` y `.dockerignore`, así que no entra ni a git ni a las imágenes.
- **Limitaciones:** no hay HTTPS (habría que agregar un dominio y Let's Encrypt), la app y el worker usan el mismo usuario de base de datos, y hay un solo servidor (sin alta disponibilidad).
