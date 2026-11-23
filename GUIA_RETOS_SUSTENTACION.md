# Guía de retos para la sustentación

Cada reto lo resuelve **un solo integrante**, sin que nadie más toque el teclado, en 5 a 10 minutos. Esta guía está pensada para que lo resuelva en menos de 3 minutos alguien que no escribió el código. Si no alcanzas a terminar, explica qué intentaste, en qué archivo está el problema y cómo lo resolverías: el profesor evalúa el diagnóstico.

## 0. Antes de empezar

**Entrar al servidor** (AWS Academy → *Start Lab* → punto verde → *AWS* → CloudShell `>_`):
```bash
ssh -i ~/agroanalisis-key.pem ubuntu@<IP_PUBLICA>
sudo -iu plataforma
cd /opt/agroanalisis
```
- **Nueva IP del servidor** (cambia cada vez que se reinicia el lab): `aws ec2 describe-instances --filters Name=tag:Name,Values=agroanalisis --query 'Reservations[].Instances[].PublicIpAddress' --output text`
- **SSH se queda colgado** (cambió la IP de CloudShell): `aws ec2 authorize-security-group-ingress --group-id "$(aws ec2 describe-security-groups --filters Name=group-name,Values=agroanalisis-sg --query 'SecurityGroups[0].GroupId' --output text)" --protocol tcp --port 22 --cidr $(curl -s https://checkip.amazonaws.com)/32`

En local todo es igual, pero sin SSH: los comandos se ejecutan en la carpeta del proyecto. En los ejemplos, `IP` es `localhost` o la IP pública.

### Regla de oro: qué aplicar después de cada cambio

| Si cambias… | Ejecuta | Por qué |
|---|---|---|
| `app/*.py` o `app/templates/*` | `docker compose up -d --build app` | el código se **copia dentro de la imagen**; `restart` NO aplica cambios |
| `worker/*.py` | `docker compose up -d --build worker` | igual |
| `docker-compose.yml` (límites, variables) | `docker compose up -d <servicio>` | recrea el contenedor con la nueva configuración |
| `.env` (por ejemplo `REGLA_X=1`) | `docker compose up -d app` | las variables se leen al crear el contenedor |
| `nginx/nginx.conf` | `docker compose restart proxy` | el archivo está montado, no copiado |

Editar: `nano archivo` (guardar con `Ctrl+O` y Enter, salir con `Ctrl+X`). Ver qué cambiaste: `git diff`. Deshacer: `git checkout -- archivo`.

### Los 5 puntos calientes (cada uno vive en un solo lugar)

| Qué | Dónde | Encontrarlo |
|---|---|---|
| Matriz de permisos por rol | `app/permisos.py`, diccionario `PERMISOS` | `grep -n '"operador"' app/permisos.py` |
| Aislamiento entre usuarios | `app/seguridad.py`, `obtener_trabajo_autorizado()` | `grep -n "def obtener_trabajo_autorizado" app/seguridad.py` |
| Registrar un evento de auditoría | `app/auditoria.py`, `auditar()` | `grep -n "def auditar" app/auditoria.py` |
| Reglas de negocio | `app/reglas_negocio.py`, diccionario `REGLAS` | `grep -n "^REGLAS" app/reglas_negocio.py` |
| Límites de RAM, CPU y procesos | `docker-compose.yml` (tabla al inicio del archivo) | `grep -n "mem_limit\|cpus:" docker-compose.yml` |

Las rutas web están en `app/rutas.py` (agricultor, técnico y API) y en `app/rutas_admin.py` (coordinador).

---

## Reto 1 · Crear un usuario con rol Usuario y demostrar 403 en una función administrativa

**Objetivo:** alta, asignación de rol y denegación efectiva en el servidor.

**Por la interfaz:**
1. Entra como `coordinador` → **Usuarios** → crea `prueba1`, contraseña `Prueba2026`, rol **Agricultor (usuario)** → *Crear usuario*.
2. Sal y entra como `prueba1`. El menú solo muestra *Mis trabajos*.
3. Escribe a mano `http://IP/admin/usuarios`: aparece **Acceso denegado (403)**. Lo mismo pasa con `/operacion` y `/admin/auditoria`.

**Por consola (CLI):**
```bash
docker compose exec app flask --app app crear-usuario prueba2 usuario      # pide la contraseña dos veces
curl -s -o /dev/null -w "%{http_code}\n" http://localhost/admin/usuarios    # sin sesión: 302 (redirige al login)
```

**Prueba negativa con sesión, por terminal** (opcional, demuestra que es el servidor el que niega):
```bash
python3 - <<'EOF'
import re, requests
s = requests.Session(); U = "http://localhost"
t = re.search(r'name="csrf" value="([^"]+)"', s.get(U + "/login").text).group(1)
r = s.post(U + "/login", data={"usuario": "prueba1", "clave": "Prueba2026", "csrf": t}, allow_redirects=False)
print("login ->", r.status_code)                                                          # 302 = sesión iniciada
print("GET /admin/usuarios ->", s.get(U + "/admin/usuarios", allow_redirects=False).status_code)   # 403
EOF
```

**En la auditoría** (coordinador → Auditoría → usuario `prueba1`): aparecen `crear_usuario`, `login_ok` y `acceso_denegado` (resultado *denegado*, recurso `/admin/usuarios`).

**Qué decir:** "Ocultar el menú es solo comodidad. La protección real es `@requiere("gestionar_usuarios")`, que se valida en el servidor; además, el rol se lee de la base de datos en cada petición, así que si mañana desactivo la cuenta, aplica de inmediato."

---

## Reto 2 · Dar una operación al Operador sin dársela al Usuario

**Objetivo:** cambio mínimo, más una prueba positiva y otra negativa. Es **una línea en `app/permisos.py`**.

### 2a. Con un permiso que ya existe
Ejemplo: "que el técnico pueda descargar resultados de cualquier agricultor".
```bash
grep -n '"operador"' -A 6 app/permisos.py
nano app/permisos.py
```
```python
    "operador": {
        "subir",
        "ver_propios",
        "ver_todos",
        "reprocesar",
        "descargar_todos",      # NUEVO: descargar resultados de cualquier agricultor
    },
```
```bash
docker compose up -d --build app
```
- **Prueba positiva:** `tecnico1` → Operación → abre un trabajo completado de `agricultor1` → *Descargar resultado*. Funciona; antes daba 404.
- **Prueba negativa:** `agricultor2` abre `http://IP/trabajos/<id de agricultor1>/descargar` → sigue dando 404.

| Si el profesor pide que el técnico pueda… | Agrega al bloque `"operador"` |
|---|---|
| ver la auditoría | `"ver_auditoria"` |
| eliminar trabajos de cualquiera (incluso completados) | `"eliminar_cualquiera"` |
| descargar resultados u originales ajenos | `"descargar_todos"` |
| gestionar usuarios | `"gestionar_usuarios"` |

### 2b. Con un permiso nuevo (operación que hoy no se separa)
Ejemplo: "el técnico puede exportar la auditoría en CSV, pero no verla en pantalla".
1. En `app/permisos.py`, agrega `"exportar_auditoria",` a `"admin"` y a `"operador"`.
2. En `app/rutas_admin.py`, cambia el decorador de esa ruta:
   ```bash
   grep -n "def auditoria_csv" -B 2 app/rutas_admin.py
   ```
   ```python
   @app.get("/admin/auditoria.csv")
   @requiere("exportar_auditoria")      # antes: ver_auditoria
   def auditoria_csv():
   ```
3. Aplica con `docker compose up -d --build app`.
4. Prueba: `tecnico1` abre `http://IP/admin/auditoria.csv` → descarga (200); `tecnico1` abre `/admin/auditoria` → 403; `agricultor1` abre `/admin/auditoria.csv` → 403.

**Qué decir:** "Toda la matriz está en un único diccionario y el servidor la consulta en cada ruta. El cambio toca solo el rol operador; el rol usuario queda igual, y lo demostré con una prueba positiva y otra negativa."

---

## Reto 3 · Corregir el aislamiento (IDOR)

**Objetivo:** que un usuario no pueda consultar el identificador de un archivo ajeno, en el servidor y en la API.

Todo depende de **una función**:
```bash
grep -n "def obtener_trabajo_autorizado" -A 22 app/seguridad.py
```
Versión correcta (cópiala si la dañaron):
```python
def obtener_trabajo_autorizado(trabajo_id, permiso_global):
    t = consulta("SELECT t.*, u.usuario AS dueno FROM trabajos t JOIN usuarios u ON u.id = t.usuario_id "
                 "WHERE t.id = %s", (trabajo_id,), uno=True)
    es_dueno = t is not None and t["usuario_id"] == g.usuario["id"]
    if t is None or not (es_dueno or puede(g.usuario["rol"], permiso_global)):
        auditar("acceso_denegado", f"motivo={'inexistente' if t is None else 'ajeno'} ruta={request.path}",
                recurso=f"trabajo:{trabajo_id}", resultado="denegado")
        abort(404)
    d = reglas_negocio.evaluar_acceso(contexto(trabajo=t))
    if not d.permitido:
        auditar(d.evento, d.motivo, recurso=f"trabajo:{trabajo_id}", resultado="denegado")
        abort(404)
    return t
```

**Las 3 formas típicas de romperla y cómo detectarlas:**

| Daño | Síntoma | Cómo encontrarlo | Arreglo |
|---|---|---|---|
| 1. `es_dueno` compara mal: `t["id"] == g.usuario["id"]`, `es_dueno = True` o compara contra un dato que manda el navegador (`request.args`) | `agricultor2` ve trabajos ajenos | `grep -n "es_dueno =" app/seguridad.py` | `t["usuario_id"] == g.usuario["id"]` (el id de la **sesión**) |
| 2. Se quita el `not (...)`, se cambia `or` por `and` o se borra el `abort(404)` | todos ven todo, o nadie ve nada | leer las 3 líneas del `if` | dejar `if t is None or not (es_dueno or puede(...)):` seguido de `abort(404)` |
| 3. Una ruta deja de usar la función y consulta directo: `consulta("SELECT * FROM trabajos WHERE id = %s", ...)` | solo esa ruta filtra datos | `grep -n "obtener_trabajo_autorizado(trabajo_id" app/rutas.py` debe dar 6 líneas; `grep -n "SELECT \* FROM trabajos WHERE id" app/rutas.py` debe salir vacío | reemplazar por `t = obtener_trabajo_autorizado(trabajo_id, "ver_todos")` (o `"descargar_todos"` en las descargas) |

Las rutas que deben usarla son detalle, descargar, original, eliminar, reprocesar y `api_trabajo`. Para verlas: `grep -n "obtener_trabajo_autorizado(trabajo_id" app/rutas.py`, que debe mostrar exactamente 6 líneas. Si muestra 5, una ruta dejó de usarla.

Aplica con `docker compose up -d --build app`.

**Verificación:**
```bash
# como agricultor2, con el id de un trabajo de agricultor1:
# navegador: http://IP/api/trabajos/<id>   -> {"codigo":404,...}
# navegador: http://IP/trabajos/<id>       -> No encontrado (404)
```
En Auditoría, filtrando por resultado *denegado*, aparece `acceso_denegado` de `agricultor2` con recurso `trabajo:<id>` y el detalle `motivo=ajeno`.

**Prueba automática:** `python3 pruebas/pruebas_funcionales.py http://IP` (sección "Aislamiento", 9 pruebas).

**Qué decir:** "El servidor compara el dueño del trabajo con el id del usuario de la sesión, nunca con algo que mande el navegador. Respondo 404 y no 403 para no revelar que el trabajo existe, y cada intento queda auditado."

---

## Reto 4 · Cambiar el límite de memoria o CPU de un contenedor

**Objetivo:** hacer el cambio y mostrar el límite aplicado. Los límites están agrupados al principio de `docker-compose.yml` y en cada servicio.
```bash
grep -n "mem_limit\|memswap_limit\|cpus:" docker-compose.yml
nano docker-compose.yml
```
En el servicio `worker`:
```yaml
    mem_limit: 128m          # antes 256m
    memswap_limit: 128m      # SIEMPRE igual a mem_limit (si queda menor que mem_limit, Docker da error)
    cpus: 0.25               # antes 0.5
```
```bash
docker compose up -d worker          # recrea solo el worker (sin --build: no cambió código)
```

**Comprobarlo de tres formas:**
```bash
docker inspect agroanalisis-worker-1 -f 'mem={{.HostConfig.Memory}} cpus={{.HostConfig.NanoCpus}} pids={{.HostConfig.PidsLimit}}'
#   mem=134217728 (128 MB = 128*1024*1024)   cpus=250000000 (0.25 CPU)
docker stats --no-stream             # columna "MEM USAGE / LIMIT" del worker: ... / 128MiB
docker compose exec worker cat /sys/fs/cgroup/memory.max /sys/fs/cgroup/cpu.max
#   134217728  y  25000 100000  (25 ms de CPU cada 100 ms = 0.25 CPU)
```
También se ve en la interfaz: técnico o coordinador → **Recursos** muestra el worker con "… MB de 128 MB" y la frase de interpretación. El dato sale del mismo `/sys/fs/cgroup`.

**Qué decir:** "El límite lo aplica el kernel con cgroups v2, no la aplicación. Si el worker se pasa de 128 MB, el OOM killer mata el proceso hijo que analiza el archivo, el trabajo queda fallido con el motivo 'memoria insuficiente' y la app y la base de datos no se ven afectadas. Con 832 MB en total, el sistema cabe en una t2.micro."

---

## Reto 5 · Detener y reiniciar el worker, y demostrar que vuelve a procesar

**Objetivo:** recuperación del servicio y logs del reinicio.

**A. Parada ordenada:**
```bash
docker compose stop worker
#   sube un archivo desde la web: queda "Pendiente" (nadie lo procesa); en Recursos el worker sale "sin latido"
docker compose ps worker            # Exited
docker compose start worker
docker compose logs --tail 15 worker
```
En los logs aparecen `Señal 15 recibida: terminando después del trabajo actual` y `Worker detenido correctamente` (la parada), y luego `Worker iniciado (worker@...)`, `Trabajo N: inicia` y `Trabajo N: completado`. En la web, el trabajo pasa solo a **Completado**, porque la página se actualiza cada 2 s.

**B. Caída brusca a mitad de un trabajo** (demuestra la recuperación):
```bash
#   sube datos_prueba/02_suelos_lote_B.csv y, mientras está "En ejecución":
docker compose kill worker
docker compose start worker
docker compose logs --tail 15 worker   # "Recuperados 1 trabajos interrumpidos: #N->pendiente"
```
El trabajo termina **Completado** con *Intentos: 2* en el detalle.

**En la auditoría:** aparecen `worker_detenido`, `worker_inicio`, `recuperar_trabajos` (con `#N->pendiente`) y `procesar_ok`, todos con origen worker.

**Qué decir:** "Los trabajos viven en PostgreSQL, no en la memoria del worker, así que no se pierden. Con `stop`, el worker recibe SIGTERM y termina el trabajo actual. Si muere de golpe, al arrancar devuelve a la cola solo sus trabajos o los de workers sin latido; con dos workers nunca le quita el trabajo a uno vivo. Si un archivo lo tumba tres veces seguidas (`MAX_INTENTOS`), se marca fallido para no entrar en un bucle infinito."

---

## Reto 6 · Agregar un evento de auditoría nuevo

**Objetivo:** que el evento registre usuario, acción y marca temporal. Es **una línea** con `auditar()`: el usuario, el rol, la IP y la fecha se llenan solos, y PostgreSQL lo encadena con el anterior sin tocar el trigger.

Ya se auditan: `login_ok`, `login_fallido`, `logout`, `subir`, `archivo_rechazado`, `regla_*`, `descargar`, `descargar_original`, `eliminar`, `reprocesar`, `reprocesar_rechazado`, `crear_usuario`, `cambiar_rol`, `activar`, `desactivar`, `modificar_usuario_rechazado`, `acceso_denegado`, `csrf_rechazado`, `exportar_auditoria`, `verificar_cadena`, `error_interno`, `integridad_comprometida`, y del worker: `worker_inicio`, `worker_detenido`, `procesar_ok`, `procesar_error` y `recuperar_trabajos`.

**Ejemplo: "registrar cuando alguien ve el detalle de un trabajo".**
```bash
grep -n "def detalle" -A 4 app/rutas.py
nano app/rutas.py
```
```python
@app.get("/trabajos/<int:trabajo_id>")
@requiere("ver_propios")
def detalle(trabajo_id):
    t = obtener_trabajo_autorizado(trabajo_id, "ver_todos")
    auditar("ver_detalle", f"dueno={t['dueno']}", recurso=f"trabajo:{trabajo_id}")   # NUEVO
    return render_template("detalle.html", t=t)
```
```bash
docker compose up -d --build app
```
**Verificar:**
1. Abre un trabajo.
2. Entra a **Auditoría** y filtra por la acción `ver_detalle`: aparecen usuario, rol, recurso, fecha e IP.
3. Pulsa **Verificar cadena**: debe seguir diciendo "Cadena íntegra".
4. Por terminal: `docker compose logs app | grep ver_detalle`.

La receta es la misma para cualquier acción: buscar la función de esa ruta y agregar `auditar("nombre_accion", "detalle", recurso="...")` justo **después** de que la acción ocurra con éxito. Para un rechazo, se agrega además `resultado="denegado"`.

**Qué decir:** "Hay una sola función de auditoría y su firma es simple. El hash de cada evento lo calcula PostgreSQL con un trigger, así que un evento nuevo entra a la cadena de custodia sin tocar nada más. La tabla es de solo inserción: ni la app puede modificarla."

---

## Cambio de regla de negocio de último minuto

### Cómo está organizado

```
ruta (rutas.py)  ──►  punto de enganche            ──►  reglas activas de ese enganche  ──►  Decision
  subir()             evaluar_subida(ctx)                (en el orden del diccionario)        permitido / motivo /
  descargar()         evaluar_descarga(ctx, tipo)                                             evento / http
  eliminar()          evaluar_eliminacion(ctx)                                                    │
  reprocesar()        evaluar_reprocesado(ctx)                                                    ▼
  obtener_trabajo_    evaluar_acceso(ctx)                                     si niega: auditar(evento) +
  autorizado()                                                                motivo al usuario + código HTTP
```
`app/reglas_negocio.py` no importa Flask ni la base de datos, así que se prueba en 1 segundo con `python -m unittest pruebas/test_reglas_negocio.py`. Las rutas ya llaman a todos los enganches, de modo que una regla nueva **no requiere tocar las rutas**.

### Reglas preparadas

| Regla | Qué hace / cómo se le explica al profesor | Activar | Parámetro | Archivo que cumple / viola |
|---|---|---|---|---|
| `cuota_trabajos_activos` (activa) | "Un agricultor no puede saturar la cola: máximo 3 trabajos pendientes o en proceso" | ya activa | `MAX_ACTIVOS_USUARIO` (.env) | 3 subidas pasan / la 4.ª da 409 |
| `bloquear_borrado_finalizados` (activa) | "Trazabilidad: un resultado completado solo lo borra el coordinador" (ejemplo logística) | ya activa | `estados_protegidos` | eliminar un fallido / eliminar uno completado da 403 |
| `cabecera_csv_obligatoria` | "Validación estructural antes de la cola" (regla del plan original) | `REGLA_CABECERA_CSV_OBLIGATORIA=1` | `CABECERA_CSV` (.env) | `10_regla_cabecera_cumple.csv` / `11_regla_cabecera_viola.csv` |
| `rangos_agronomicos_validos` | "No entra a la cola un análisis imposible: pH fuera de 0–14 o % fuera de 0–100" (ejemplo financiero) | `REGLA_RANGOS_AGRONOMICOS_VALIDOS=1` | `ph_min`, `ph_max` | `12_regla_rangos_cumple.csv` / `13_regla_rangos_viola.csv` |
| `tamano_maximo_por_rol` | "El agricultor envía hasta 1 MB; técnico y coordinador hasta 2 MB" | `REGLA_TAMANO_MAXIMO_POR_ROL=1` | `mb` por rol | `04_informe_visita_campo.txt` / `14_regla_tamano_viola.txt` (1,5 MB) |
| `ventana_recepcion` | "El laboratorio recibe muestras de 6:00 a 18:00 (hora de Colombia)" | `REGLA_VENTANA_RECEPCION=1` | `desde`, `hasta` | subir de día / subir de noche (o cambiar `hasta` a la hora actual) |
| `bloquear_descarga_originales_ajenos` | "El técnico supervisa pero no descarga originales ajenos, aunque se le dé `descargar_todos`" (regla del plan) | `REGLA_BLOQUEAR_DESCARGA_ORIGINALES_AJENOS=1` | `roles_permitidos` | el coordinador descarga / el técnico con `descargar_todos` da 403 |
| `trabajos_confidenciales` | "Un trabajo confidencial solo lo ven su dueño y el coordinador" (ejemplo clínico) | `REGLA_TRABAJOS_CONFIDENCIALES=1` (aparece la casilla *Confidencial* al subir) | `roles_permitidos` | el dueño lo ve / `tecnico1` recibe 404 y no lo ve en Operación |
| `limite_reprocesos` | "Un trabajo fallido se reprocesa como máximo 2 veces" | `REGLA_LIMITE_REPROCESOS=1` | `max` | 2 reprocesos pasan / el 3.º da 409 |

**Dos formas de activarlas:**
- **Sin reconstruir (10 segundos):** `echo "REGLA_CABECERA_CSV_OBLIGATORIA=1" >> .env && docker compose up -d app`
- **En el código:** `grep -n '"activa": _activa("cabecera' app/reglas_negocio.py`, cambiar `False` por `True` y aplicar con `docker compose up -d --build app`.

Se comprueba en **Reglas** (coordinador), en el panel de cualquier agricultor ("Reglas vigentes del laboratorio") o con `curl` autenticado a `/api/reglas`.

### Receta para una regla NUEVA en menos de 2 minutos

Ejemplo resuelto: **"los agricultores solo pueden enviar CSV, no TXT"**.

1. `nano app/reglas_negocio.py`. Dentro de `REGLAS`, por ejemplo después de `"cuota_trabajos_activos"`, agrega:
   ```python
       "solo_csv_para_agricultores": {
           "activa": _activa("solo_csv_para_agricultores", True),
           "enganche": "subida",
           "descripcion": "Los agricultores solo pueden enviar resultados de laboratorio en CSV.",
       },
   ```
2. Al final del archivo, encima de la PLANTILLA, agrega la función:
   ```python
   @regla("solo_csv_para_agricultores")
   def _solo_csv(ctx, cfg):
       if ctx.rol == "usuario" and ctx.extension != "csv":
           return negar("solo_csv_para_agricultores", "Los agricultores solo pueden enviar archivos CSV.", 422)
       return PERMITIDO
   ```
3. Verifica sin Docker: `python3 -m unittest pruebas/test_reglas_negocio.py`. Va a fallar **una sola** prueba, `test_por_defecto_solo_las_dos_reglas_originales_estan_activas`, porque documenta qué reglas están activas por defecto. Es lo esperado, y se arregla agregando el nombre nuevo al conjunto de esa prueba:
   ```bash
   grep -n '{"cuota_trabajos_activos", "bloquear_borrado_finalizados"}' pruebas/test_reglas_negocio.py
   #   -> {"cuota_trabajos_activos", "bloquear_borrado_finalizados", "solo_csv_para_agricultores"}
   ```
   Otra opción es dejar la regla nueva en `False` y activarla por `.env`: así no falla nada.
4. Aplica con `docker compose up -d --build app`.
5. Demuestra: `agricultor1` sube `04_informe_visita_campo.txt` y recibe un mensaje claro (422); sube `01_suelos_lote_A.csv` y funciona; `tecnico1` sube el `.txt` y funciona. En Auditoría aparece `regla_solo_csv_para_agricultores` con resultado *denegado*.

Otro ejemplo, "el operador no puede reprocesar un trabajo más de 2 veces", ya existe: es `limite_reprocesos`.

**Campos disponibles en `ctx`:** `rol`, `usuario_id`, `es_dueno`, `trabajo` (dict con `estado`, `intentos`, `reprocesos`, `confidencial`…), `nombre`, `extension`, `tamano` (bytes), `texto` (contenido del archivo), `n_activos`, `tipo_descarga`, `ahora`, y `puede("permiso")`.

### Cómo verificar sin romper nada
```bash
python3 -m unittest pruebas/test_reglas_negocio.py         # 1. reglas aisladas (1 s)
python3 pruebas/pruebas_funcionales.py http://localhost     # 2. se adaptan a las reglas activas según /api/reglas
#  3. Auditoría -> filtrar acción "regla_<nombre>"; Reglas -> la regla aparece "Activa"
```

### Cómo deshacer en 10 segundos
```bash
git checkout -- app/reglas_negocio.py && docker compose up -d --build app
#  o, si se activó por .env:
sed -i '/^REGLA_CABECERA_CSV_OBLIGATORIA=/d' .env && docker compose up -d app
```

### Frase modelo para el profesor
"La regla de negocio está desacoplada: vive en un solo módulo, con un diccionario de configuración y funciones puras. Las rutas solo preguntan '¿se permite?' en cada punto de enganche, así que agregar o cambiar una regla no toca permisos, aislamiento ni validación (principio abierto/cerrado). Cada rechazo se audita con su propio evento y entra a la cadena de custodia."

---

## Kit de emergencia

```bash
docker compose ps                          # ¿algún contenedor "unhealthy", "restarting" o "exited"?
docker compose logs --tail 40 app          # error de Python: archivo, línea y tipo de error
docker compose logs --tail 40 worker
git diff                                   # qué cambié exactamente
git checkout -- app/permisos.py            # deshacer los cambios de un archivo
docker compose up -d --build app           # volver a construir y levantar
```

| Síntoma | Causa típica | Solución |
|---|---|---|
| Hice el cambio y no pasa nada | olvidé `--build` (usé `restart`) | `docker compose up -d --build app` |
| `app` en "restarting" o la web da 502 | error de sintaxis o de indentación | `docker compose logs app \| grep -E "Error\|line"` → corregir → `--build` |
| `IndentationError` | mezclé tabulaciones y espacios, o faltó sangría | usar 4 espacios; copiar la sangría de la línea de arriba |
| `NameError: name 'x' is not defined` | escribí mal un nombre o falta un import | comparar con `git diff` |
| 400 "El formulario expiró" | se reinició la app con la página vieja abierta | recargar la página (F5) |
| 429 "Demasiados intentos" | más de 10 logins por minuto | esperar un minuto |
| Error de Docker con la memoria al cambiar `mem_limit` | `memswap_limit` quedó menor que `mem_limit` | poner los dos iguales |
| El trabajo se queda "Pendiente" | worker detenido | `docker compose ps worker`; `docker compose start worker` |

---

## Guion de 4 minutos para el checklist (14 puntos)

| # | Punto | Qué mostrar (comando o pantalla) | Qué decir |
|---|---|---|---|
| 1 | Despliegue en la nube | consola de EC2 (instancia `agroanalisis`) y `http://<IP>` en el navegador | "IaaS en AWS Academy: EC2 Ubuntu 24.04" |
| 2 | Contenedores | `docker compose ps` (los 4 *healthy*) | "proxy es la única entrada; app, worker y db en redes internas" |
| 3 | Linux y procesos | `hostnamectl; docker compose top app worker; docker compose exec app id` | "uid 10001, no root; Gunicorn con 2 procesos" |
| 4 | Recursos | `docker stats --no-stream` y la pantalla **Recursos** | leer la frase: "el worker usa 27 MB de 256 MB: margen suficiente para un CSV de 2 MB" |
| 5 | Dos cuentas con roles distintos | entrar como `agricultor1` y luego como `coordinador`: el menú cambia | "el rol se valida en el servidor en cada petición" |
| 6 | Operación permitida y denegada | `agricultor1` → `http://IP/admin/usuarios` → 403 | "decorador `@requiere`" |
| 7 | Aislamiento | `agricultor2` → `http://IP/trabajos/<id de agricultor1>` → 404 | "comparo con el usuario de la sesión, 404 para no revelar que existe" |
| 8 | Procesamiento | subir `01_suelos_lote_A.csv`: Pendiente → En ejecución → Completado, sin recargar; descargar el JSON | "cola en PostgreSQL con SKIP LOCKED, worker separado" |
| 9 | Persistencia | `docker compose down && docker compose up -d --wait`, volver a entrar: todo sigue ahí | "volúmenes `db_data` y `datos`" |
| 10 | Hardening | `grep -n "read_only\|cap_drop\|no-new-privileges" docker-compose.yml`; `sudo ufw status`; `stat -c '%a' .env` | "sin root, sin capacidades, solo lectura, .env con 600, UFW y SSH solo con llave" |
| 11 | Red y puertos | `sudo ss -tlnp` (solo 22 y 80); `docker compose port db 5432` (vacío); `docker compose exec worker python -c "import socket; socket.create_connection(('1.1.1.1',443),3)"` → *Network is unreachable* | "la base de datos no publica puertos; el worker no tiene Internet" |
| 12 | Auditoría | **Auditoría** → filtrar resultado *denegado* → *Exportar CSV* | "quién, rol, qué, sobre qué recurso, resultado, cuándo e IP" |
| 13 | Autenticidad | **Reglas** + 4.º envío rechazado por la cuota + **Verificar cadena** + `./scripts/demo_sello.sh alterar 7` → cadena rota en el evento #7 | "regla propia desacoplada y cadena de custodia SHA-256 calculada por PostgreSQL" |
| 14 | Repositorio sin secretos | `git ls-files \| grep -c "^.env$"` (0); `cat .gitignore`; `git grep -nI -E "AKIA\|BEGIN .*PRIVATE"` (vacío) | ".env solo existe en el servidor, con permisos 600" |

## Preguntas frecuentes

- **¿Por qué no usaron Redis?** PostgreSQL ya garantiza con `FOR UPDATE SKIP LOCKED` que dos workers no tomen el mismo trabajo. Es un componente menos que asegurar, y la cola sobrevive a reinicios.
- **¿IaaS o PaaS?** IaaS (EC2), porque necesitamos administrar el sistema operativo: usuarios, SSH, firewall, actualizaciones y cgroups.
- **¿Qué puertos están abiertos?** El 22 (SSH, solo desde la IP de administración, en el Security Group y con `ufw limit`) y el 80 (web, vía nginx). No hay 443 porque no hay HTTPS (limitación documentada).
- **¿Por qué el worker no tiene Internet?** Está solo en la red `backend` (`internal: true`). Si un archivo malicioso lograra ejecutar código, no podría sacar datos.
- **¿Cómo guardan las contraseñas?** Con hash scrypt y sal. El login tarda lo mismo exista o no el usuario.
- **¿Qué pasa si roban la base de datos o alguien entra como superusuario?** La app y el worker usan usuarios sin privilegios. Un superusuario podría desactivar el trigger, pero la verificación de la cadena señala el evento exacto que alteró.
- **Limitaciones:** sin HTTPS, un solo servidor, el grupo `docker` equivale a root, y los límites de db y proxy se ven con `docker stats` y no en el panel.
