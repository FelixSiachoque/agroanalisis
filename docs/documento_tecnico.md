# Documento técnico · AgroAnálisis Sugamuxi

**Plataforma segura de procesamiento de archivos en la nube**
Proyecto final de Sistemas Operativos · Mgtr. Fredy Alarcón · UPTC Seccional Sogamoso · 2026

> Este archivo es la fuente del documento técnico (PDF de 6 a 10 páginas). Para exportarlo: abrir en VS Code con la vista previa de Markdown e imprimir a PDF, o `pandoc docs/documento_tecnico.md -o documento_tecnico.pdf`. Antes de entregarlo, hay que agregar las capturas de `evidencias/ui/` y la salida de `./scripts/evidencias.sh` tomada en el servidor.

---

## 1. Contexto

**AgroAnálisis Sugamuxi** es un laboratorio ficticio de análisis de suelos que atiende a pequeños productores de la provincia de Sugamuxi (papa, cebolla larga, arveja, haba, pastos).

**El problema.** Hoy los resultados llegan por correo en hojas de cálculo sueltas, sin control de quién ve qué ni rastro de los cambios. El laboratorio necesita:
- recibir los resultados de laboratorio (`.csv`) y los informes de visita de campo (`.txt`);
- procesarlos automáticamente: estadísticas por columna, clasificación de pH en ácido, neutro o alcalino, y conteos de texto;
- entregar a cada agricultor **solo sus** resultados;
- poder demostrar que una muestra no fue alterada entre la recepción y la entrega.

| Perfil | Rol en el sistema | Necesidad |
|---|---|---|
| Agricultor | `usuario` | enviar sus muestras y descargar sus resultados |
| Técnico de laboratorio | `operador` | supervisar la cola, revisar errores y reprocesar; no debe llevarse los datos de los clientes |
| Coordinador | `admin` | administrar cuentas, auditar y responder por la cadena de custodia |

## 2. Arquitectura

*(Insertar aquí el diagrama Mermaid del README, renderizado.)*

| Capa | Elección |
|---|---|
| Nube | AWS Academy Learner Lab |
| Modelo | **IaaS**: instancia EC2 (t3.small recomendada; t2.micro compatible) |
| Sistema operativo | Ubuntu Server 24.04 LTS, disco EBS cifrado de 20 GB, IMDSv2 obligatorio |
| Orquestación | Docker Engine + Docker Compose; despliegue en `/opt/agroanalisis` con el usuario `plataforma` |
| Contenedores | `proxy` (nginx 1.28 sin root), `app` (Flask 3.1 + Gunicorn), `worker` (Python 3.12), `db` (PostgreSQL 16) |
| Redes | `edge` (solo el proxy, con salida), `frontend` y `backend` (`internal: true`, sin Internet) |
| Volúmenes | `db_data` (base de datos) y `datos` (`/data/uploads/<usuario>`, `/data/results/<usuario>`) |
| Puertos | 80 (HTTP, único publicado) y 22 (SSH, solo desde la IP de administración) |

**Por qué IaaS:** el objetivo de la materia es administrar el sistema operativo: cuentas, permisos de archivos, servicio SSH, firewall, actualizaciones y límites de procesos con cgroups. Un PaaS ocultaría precisamente esa capa.

**Flujo de un trabajo:**
1. El agricultor sube un archivo.
2. La app valida tipo, tamaño, UTF-8 y las reglas de negocio. Guarda el archivo con nombre UUID en la carpeta del usuario, registra su SHA-256 y crea el trabajo `pendiente`. Responde de inmediato.
3. El worker toma el trabajo, verifica la huella y lo procesa en un proceso hijo con tiempo máximo.
4. El worker escribe el JSON, registra su huella y marca el trabajo `completado`, o `fallido` con el motivo.
5. La pantalla se actualiza sola, sin recargar, y cada paso queda auditado.

## 3. Decisiones técnicas propias

| Decisión | Alternativa descartada | Justificación |
|---|---|---|
| **Cola en PostgreSQL** (`FOR UPDATE SKIP LOCKED`) | Redis o RabbitMQ | Un servicio menos que endurecer y vigilar. La cola es persistente y transaccional. Se probó que con 2 workers no hay duplicados |
| Flask con plantillas en el servidor y un único JS propio | SPA con framework de frontend | Menos superficie de ataque: la CSP prohíbe JS en línea y externo, y la sesión va en cookie HttpOnly |
| Sesión con cookie firmada y rol releído de la BD en cada petición | JWT | Desactivar una cuenta o cambiarle el rol aplica de inmediato |
| Usuarios de BD separados (`agro_web`, `agro_worker`) | Un único usuario (superusuario) | Mínimo privilegio. El worker no lee la tabla `usuarios` y nadie modifica la auditoría |
| Reglas de negocio en un módulo intercambiable | Reglas dentro de las rutas | El docente puede asignar o cambiar la regla, y el cambio es de una línea y está probado |
| Métricas leídas de cgroups v2 | Montar `/var/run/docker.sock` | El socket de Docker equivale a ser root del servidor |
| Migraciones idempotentes y prueba de equivalencia | Recrear la base en el servidor | Actualizar AWS sin perder datos; `pruebas/test_esquema.sh` demuestra que `init.sql` coincide con el esquema anterior más las migraciones |

## 4. Usuarios, roles y autorización

- **Autenticación:** cuenta individual y contraseña con hash **scrypt** (werkzeug). El mensaje de error es genérico y el tiempo de respuesta es el mismo exista o no el usuario. nginx limita a 10 intentos de login por minuto por IP.
- **Sesión:** cookie firmada con `SECRET_KEY` (del `.env`), HttpOnly, SameSite=Lax y duración de 1 hora. Al iniciar sesión se genera una sesión nueva (evita la fijación de sesión). Todos los formularios llevan un **token CSRF**.
- **Autorización en el servidor:** el decorador `@requiere(permiso)` consulta la matriz de `app/permisos.py`.

| Permiso | Agricultor | Técnico | Coordinador |
|---|:-:|:-:|:-:|
| subir, ver/descargar/eliminar lo propio | Sí | Sí | Sí |
| ver todos los trabajos, operación, recursos | — | Sí | Sí |
| reprocesar fallidos | — | Sí | Sí |
| descargar resultados u originales ajenos | — | — | Sí |
| eliminar cualquier trabajo | — | — | Sí |
| gestionar usuarios | — | — | Sí |
| ver, exportar y verificar la auditoría | — | — | Sí |

- **Aislamiento:** toda ruta que recibe un identificador de trabajo pasa por `obtener_trabajo_autorizado()`. Solo deja pasar al dueño (comparando con el usuario de la **sesión**) o a quien tenga el permiso global. Si no, responde **404**, para no revelar que el trabajo existe, y audita el intento. Los archivos se guardan en carpetas por usuario con nombre UUID, y toda ruta leída de la BD se resuelve dentro de `/data` antes de usarse.
- **Gestión de usuarios:** el coordinador no puede modificar su propia cuenta y el sistema nunca queda sin coordinadores activos.

## 5. Sistema operativo y hardening

**Host** (`infra/bootstrap_ec2.sh`, comprobable con `./scripts/evidencias.sh`):

| Medida | Evidencia |
|---|---|
| SSH solo con llave, sin root, `MaxAuthTries 3`, validado con `sshd -t` | `sudo sshd -T \| grep -E 'passwordauthentication\|permitrootlogin'` |
| UFW: deny por defecto, `limit` en SSH y 80 abierto, más el Security Group | `sudo ufw status verbose` |
| Actualizaciones de seguridad automáticas | `systemctl is-enabled unattended-upgrades` |
| fail2ban contra fuerza bruta en SSH | `sudo fail2ban-client status sshd` |
| Cuenta de servicio `plataforma` sin sudo; `/opt/agroanalisis` con permisos 750 | `id plataforma; ls -ld /opt/agroanalisis` |
| Servicios innecesarios deshabilitados | `systemctl list-unit-files --state=enabled` |
| Rotación de logs de Docker (10 MB × 3) | `cat /etc/docker/daemon.json` |
| `.env` con permisos 600 | `stat -c '%a %U' .env` |

**Contenedores** (`docker-compose.yml`, comprobable con `docker inspect`):
- Ningún proceso corre como root: UID 10001 en app y worker, 101 en el proxy, 70 en PostgreSQL.
- Raíz de solo lectura (`read_only`) con `/tmp` en memoria de tamaño fijo.
- `cap_drop: ALL`. La db solo recupera CHOWN, SETUID, SETGID, DAC_OVERRIDE y FOWNER para su entrypoint.
- `no-new-privileges` en todos.
- El código de la imagen pertenece a root y no lo puede escribir el usuario de ejecución; los archivos de datos se crean con `umask 077`.
- Imágenes base fijadas por digest.

**Secretos:**
- Solo viven en `.env`, generado con claves aleatorias por `scripts/generar_env.sh`. Está en `.gitignore` y en los `.dockerignore`.
- App y worker reciben solo sus variables. Ninguno conoce la contraseña del superusuario de PostgreSQL.

**Riesgo reconocido:** pertenecer al grupo `docker` equivale a poder llegar a root. Se mitiga protegiendo la cuenta `plataforma` como administrativa; la alternativa más estricta es Docker *rootless*.

## 6. Almacenamiento y procesamiento

- **Política de archivos:** solo `.csv` y `.txt`, 2 MB como máximo (nginx corta a 3 MB y la app aplica el límite exacto), UTF-8 sin bytes nulos, hasta 50 000 filas y 100 columnas. El nombre original se sanea (sin rutas ni caracteres de control).
- **Estados:** `pendiente → en_ejecucion → completado | fallido`, con fechas de creación, inicio y fin, número de intentos y reprocesos.
- **Robustez del worker:**
  - Procesa en un proceso hijo con `TIMEOUT_TRABAJO_S`. Si el hijo supera la memoria del contenedor, el OOM killer lo mata solo a él y el trabajo queda fallido por "memoria insuficiente".
  - Envía un latido cada 5 s a la tabla `workers` y al archivo `/tmp/latido`, que usa el healthcheck.
  - Recupera trabajos interrumpidos solo si son suyos o de un worker sin latido, con backoff de 5, 10 y 20 s.
  - Tras `MAX_INTENTOS` interrupciones marca el trabajo fallido, para no entrar en un bucle infinito.
- **Persistencia:** `docker compose down` y `up`, o un reinicio del servidor, conservan usuarios, trabajos, auditoría y archivos (volúmenes `db_data` y `datos`).
- **Migraciones:** `db/migraciones/001` a `004` (idempotentes, se pueden ejecutar dos veces) y `scripts/aplicar_migraciones.sh` para el servidor con datos.

## 7. Monitoreo y observabilidad

- **Panel Recursos** (técnico y coordinador): memoria usada frente al límite, CPU actual o promedio frente a la cuota, procesos frente a `pids_limit`, disco del volumen `/data`, tamaño de la base de datos, trabajos por estado, y latido y trabajo actual de cada worker. Los datos salen de `/sys/fs/cgroup` (`memory.current`, `memory.max`, `cpu.max`, `cpu.stat`, `pids.current`) dentro de cada contenedor, **sin** el socket de Docker. Cada dato viene con una frase de interpretación, por ejemplo: *"El worker usa 27 MB de 256 MB (10 %): margen suficiente para procesar un archivo de 2 MB."*
- **Límites de recursos:**

| Servicio | RAM | CPU | Procesos |
|---|---|---|---|
| proxy | 64 MB | 0.25 | 50 |
| app | 256 MB | 0.5 | 64 |
| worker | 256 MB | 0.5 | 50 |
| db | 256 MB | 0.5 | 100 |
| **Total** | **832 MB** | 1.75 | |

  El total cabe en una t2.micro (1 GB) y le deja unos 190 MB al sistema operativo. En una t3.small se pueden duplicar.
- **Logs:** `docker compose logs app worker`. Los eventos de auditoría se registran en una sola línea, sin posibilidad de inyectar saltos de línea; los errores internos se registran con traza en el log y al usuario solo se le muestra un mensaje claro.
- **Healthchecks** en los 4 servicios: `pg_isready`, `/health` de la app, latido del worker y `/salud-proxy`.

## 8. Pruebas

| Prueba | Comando | Resultado obtenido |
|---|---|---|
| Unitarias de reglas de negocio (cada regla activa e inactiva) | `python -m unittest pruebas/test_reglas_negocio.py` | 26/26 |
| Equivalencia del esquema: `init.sql` vs. esquema anterior + migraciones (dos veces) | `bash pruebas/test_esquema.sh` | idéntico (esquema y permisos) |
| Funcionales y de seguridad: login, CSRF, roles, archivos, estados, IDOR en 6 rutas, reprocesar, reglas, auditoría y sello | `python pruebas/pruebas_funcionales.py http://localhost --docker` | 67/67 |
| Las mismas, con todas las reglas apagadas y con `cabecera_csv_obligatoria` activa | idem, con `REGLA_…` en `.env` | 63/63 y 69/69 |
| Reinicio y recuperación: `kill` del worker a mitad de un trabajo | incluida en `--docker` | recuperado, completado con 2 intentos |
| Carga: 30 trabajos (≈1,5 MB), concurrencia 4, 1 worker | `python pruebas/prueba_carga.py http://localhost --trabajos 30 --concurrencia 4` | 30/30 completados en 95,7 s, **18,8 trabajos/min**, 3,04 s de proceso promedio |
| Carga con 2 workers (`--scale worker=2`) | idem | 30/30 en 50,2 s, **35,9 trabajos/min**; reparto 15/15 sin duplicados |

**Interpretación de la carga.** Cada trabajo incluye una pausa fija de 3 s (`PROCESAMIENTO_DEMORA_S`) para poder mostrar el estado "en ejecución" en la demo. Por eso un worker procesa unos 20 trabajos por minuto, y el tiempo de cola crece linealmente con la cantidad enviada (promedio de 47,3 s con 30 en cola). Duplicar los workers duplicó el throughput y redujo a la mitad el tiempo en el sistema. Esto confirma que el cuello de botella es el procesamiento y no la app ni la base de datos. Durante la prueba, el worker usó unos 27 MB de 256 MB, la app unos 83 MB de 256 MB y PostgreSQL unos 50 MB de 256 MB, así que hay margen para archivos de 2 MB.

## 9. Sello de autenticidad

| Elemento | Implementación propia |
|---|---|
| Identidad del caso | Laboratorio de suelos AgroAnálisis Sugamuxi; agricultores, técnicos y coordinador |
| Política de acceso propia | Matriz de 8 permisos (sección 4) y regla de negocio: **cuota de 3 trabajos activos por agricultor** y **bloqueo de eliminación de trabajos completados o en ejecución**. Hay 7 reglas alternativas preparadas en `app/reglas_negocio.py`, activables con una línea |
| Carga de prueba propia | 14 archivos sintéticos generados con semilla fija (`datos_prueba/README.md`): 5 válidos, 4 inválidos, 1 para el sello y 4 para reglas alternativas |
| Decisión de arquitectura | Cola de trabajos en PostgreSQL con `SKIP LOCKED` (sección 3) |
| Prueba de rendimiento | 30 trabajos con concurrencia 4, con 1 y 2 workers (sección 8) |
| Elemento de auditoría | **Cadena de custodia**: cada evento encadenado con SHA-256 por un trigger de PostgreSQL, tabla de solo inserción, verificación en `/admin/auditoria/verificar`, más huella SHA-256 de cada archivo verificada por el worker antes y después de procesar |

**Cadena de custodia.** El sello combina dos mecanismos y no depende de la regla de negocio activa (se probó con las reglas por defecto, con todas apagadas y con la cabecera obligatoria).
1. **Integridad del archivo.** El SHA-256 se calcula al recibir el archivo, se verifica en el worker antes de procesar y otra vez con lo que realmente se leyó, y el resultado guarda su propia huella. Si alguien modifica un archivo dentro de `/data`, el trabajo queda *integridad_comprometida*, no se procesa ni se entrega, y se audita.
2. **Auditoría encadenada e inalterable.** Un trigger `BEFORE INSERT` calcula `hash = SHA-256(seq, hash_anterior, fecha UTC, usuario, rol, acción, recurso, resultado, detalle, ip, origen)`. La fila única `auditoria_cabeza` serializa las inserciones de los procesos de Gunicorn y del worker. Otro trigger prohíbe UPDATE, DELETE y TRUNCATE, y el usuario de la app no tiene esos permisos. Si un superusuario desactiva el trigger y altera un evento, la verificación señala el evento exacto: *"Cadena ROTA en el evento #7: su contenido fue modificado"*.

Demostración en vivo: `scripts/demo_sello.sh` (intentar modificar, alterar, verificar, restaurar, manipular un archivo).

## 10. Limitaciones y trabajo futuro

- **Sin HTTPS:** las credenciales viajan sin cifrar en la red. Con un dominio y Let's Encrypt se activaría `COOKIE_SECURE=1` y el puerto 443.
- **Un solo servidor,** sin alta disponibilidad ni copias de seguridad automáticas de los volúmenes. Trabajo futuro: `pg_dump` programado hacia S3.
- **El grupo `docker` equivale a root;** Docker *rootless* sería más estricto.
- **El superusuario de PostgreSQL** puede alterar datos desactivando triggers. El sello no lo impide, pero lo deja en evidencia. Un anclaje externo periódico del último hash (por ejemplo, publicarlo fuera del servidor) cerraría esa brecha.
- **Panel de Recursos parcial:** el consumo de `db` y `proxy` se consulta con `docker stats`, porque la app no tiene acceso a otros cgroups, a propósito.
- **Tamaño máximo de 2 MB** y procesamiento en un solo hilo por worker. Se escala horizontalmente con `--scale worker=N` dentro del límite de RAM.

## Anexo · Reproducir el despliegue

Ver `README.md`, secciones 3 (local), 4 (AWS) y 5 (operación diaria). Para un servidor con datos: `./scripts/aplicar_migraciones.sh`.
