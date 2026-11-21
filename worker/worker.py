"""
Trabajador de procesamiento (contenedor 'worker').

Ciclo de un trabajo:  pendiente -> en_ejecucion -> completado | fallido

La "cola" es la tabla 'trabajos' de PostgreSQL. Para tomar un trabajo se usa
SELECT ... FOR UPDATE SKIP LOCKED: si hay varios workers, cada uno toma un trabajo distinto
sin pisarse (escalar con: docker compose up -d --scale worker=2).

Robustez:
  - Cada trabajo se procesa en un PROCESO HIJO con tiempo máximo (TIMEOUT_TRABAJO_S).
    Si el hijo se pasa del límite de memoria del contenedor, el kernel (OOM killer) mata al hijo,
    no al worker: el trabajo queda 'fallido' con el motivo "memoria insuficiente".
  - Latido (heartbeat): cada pocos segundos el worker actualiza la tabla 'workers' y el archivo
    /tmp/latido (lo revisa el healthcheck de Docker).
  - Recuperación segura: al arrancar, y periódicamente, se devuelven a la cola SOLO los trabajos
    de este mismo worker o de workers sin latido hace más de LATIDO_CADUCO_S segundos.
  - Reintentos limitados: un trabajo interrumpido MAX_INTENTOS veces pasa a 'fallido'
    (evita el bucle infinito de un archivo que tumba al worker una y otra vez).
"""
import json
import logging
import multiprocessing
import os
import pathlib
import signal
import socket
import time

import psycopg
from psycopg.rows import dict_row

from cgroup import leer_metricas
from procesadores import PROCESADORES

logging.basicConfig(level=logging.INFO, format="%(asctime)s worker %(levelname)s %(message)s")
log = logging.getLogger("worker")
os.umask(0o077)   # archivos y carpetas nuevos: solo el dueño puede leerlos

# Usuario de BD de mínimo privilegio (agro_worker): no puede leer usuarios ni modificar la auditoría
DSN = (
    f"host={os.environ.get('DB_HOST', 'db')} port={os.environ.get('DB_PORT', '5432')} "
    f"dbname={os.environ['POSTGRES_DB']} user={os.environ['DB_USER']} "
    f"password={os.environ['DB_PASSWORD']}"
)
DATA_DIR = os.path.realpath(os.environ.get("DATA_DIR", "/data"))
DEMORA = float(os.environ.get("PROCESAMIENTO_DEMORA_S", "3"))     # pausa para ver "en_ejecucion" en la demo
MAX_INTENTOS = int(os.environ.get("MAX_INTENTOS", "3"))
TIMEOUT_TRABAJO_S = int(os.environ.get("TIMEOUT_TRABAJO_S", "120"))
LATIDO_CADA_S = 5
LATIDO_CADUCO_S = int(os.environ.get("LATIDO_CADUCO_S", "60"))
ARCHIVO_LATIDO = pathlib.Path("/tmp/latido")
NOMBRE = f"worker@{socket.gethostname()}"

seguir = True


def detener(signum, frame):
    """Al recibir SIGTERM (docker stop) se termina el trabajo actual y se sale limpio."""
    global seguir
    log.info("Señal %s recibida: terminando después del trabajo actual", signum)
    seguir = False


signal.signal(signal.SIGTERM, detener)
signal.signal(signal.SIGINT, detener)


def sql(con, consulta, params=()):
    cur = con.execute(consulta, params)
    return cur.fetchone() if cur.description else None


def auditar(con, accion, detalle, recurso=None, resultado="permitido"):
    sql(con, "INSERT INTO auditoria (usuario, rol, accion, recurso, resultado, detalle, origen) "
             "VALUES (%s, 'worker', %s, %s, %s, %s, 'worker')",
        (NOMBRE[:50], accion, recurso, resultado, detalle[:1000]))


# ---------------------------------------------------------------- latido
def latido(con, trabajo_actual=None, estado="activo", procesado=False):
    """Señal de vida: tabla 'workers' (panel de Recursos) + archivo /tmp/latido (healthcheck)."""
    m = leer_metricas()
    sql(con, """
        INSERT INTO workers (nombre, pid, estado, trabajo_actual, memoria_bytes, memoria_max,
                             cpu_limite, cpu_uso_usec, pids)
        VALUES (%(n)s, %(pid)s, %(e)s, %(t)s, %(mb)s, %(mm)s, %(cl)s, %(cu)s, %(p)s)
        ON CONFLICT (nombre) DO UPDATE SET pid = EXCLUDED.pid, estado = EXCLUDED.estado,
            ultimo_latido = now(), trabajo_actual = EXCLUDED.trabajo_actual,
            procesados = workers.procesados + %(inc)s,
            memoria_bytes = EXCLUDED.memoria_bytes, memoria_max = EXCLUDED.memoria_max,
            cpu_limite = EXCLUDED.cpu_limite, cpu_uso_usec = EXCLUDED.cpu_uso_usec, pids = EXCLUDED.pids
        """, {"n": NOMBRE, "pid": os.getpid(), "e": estado, "t": trabajo_actual, "mb": m["memoria_bytes"],
              "mm": m["memoria_max"], "cl": m["cpu_limite"], "cu": m["cpu_uso_usec"], "p": m["pids"],
              "inc": 1 if procesado else 0})
    if trabajo_actual:
        sql(con, "UPDATE trabajos SET latido = now() WHERE id = %s AND worker = %s", (trabajo_actual, NOMBRE))
    ARCHIVO_LATIDO.touch()


# ---------------------------------------------------------------- recuperación
def recuperar_interrumpidos(con, al_arrancar=False):
    """
    Devuelve a la cola los trabajos que quedaron 'en_ejecucion' porque su worker murió.
    Solo toca los de ESTE worker (al reiniciar el mismo contenedor) o los de workers sin latido
    reciente: así nunca le quita un trabajo a otro worker que sigue vivo.
    Con backoff: espera 5 s, 10 s, 20 s... antes del siguiente intento.
    """
    filas = con.execute("""
        UPDATE trabajos SET
            worker = NULL,
            estado = CASE WHEN intentos >= %(max)s THEN 'fallido' ELSE 'pendiente' END,
            error  = CASE WHEN intentos >= %(max)s
                          THEN 'Se interrumpió ' || intentos || ' veces (posible falta de memoria); no se reintenta más'
                          ELSE error END,
            terminado = CASE WHEN intentos >= %(max)s THEN now() ELSE NULL END,
            disponible_desde = now() + make_interval(secs => LEAST(60, 5 * power(2, GREATEST(intentos - 1, 0))))
        WHERE estado = 'en_ejecucion'
          AND (worker = %(yo)s OR worker IS NULL OR latido IS NULL
               OR latido < now() - make_interval(secs => %(caduco)s))
        RETURNING id, estado""", {"max": MAX_INTENTOS, "yo": NOMBRE, "caduco": LATIDO_CADUCO_S}).fetchall()
    if filas:
        resumen = ", ".join(f"#{f['id']}->{f['estado']}" for f in filas)
        log.warning("Recuperados %d trabajos interrumpidos: %s", len(filas), resumen)
        auditar(con, "recuperar_trabajos", resumen)
    elif al_arrancar:
        log.info("Sin trabajos interrumpidos que recuperar")


def tomar_trabajo(con):
    return sql(con, """
        UPDATE trabajos SET estado = 'en_ejecucion', iniciado = now(), latido = now(),
                            worker = %s, intentos = intentos + 1
        WHERE id = (SELECT id FROM trabajos WHERE estado = 'pendiente' AND disponible_desde <= now()
                    ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1)
        RETURNING *""", (NOMBRE,))


# ---------------------------------------------------------------- procesamiento
def dentro_de_data(ruta):
    """La ruta viene de la BD: solo se abre si está dentro de /data (evita path traversal)."""
    real = os.path.realpath(ruta)
    if os.path.commonpath([DATA_DIR, real]) != DATA_DIR:
        raise PermissionError("ruta fuera de /data")
    return real


def _hijo(tipo, ruta, canal):
    """Corre en un proceso aparte. Envía ('ok', resultado) o ('error', mensaje para el usuario)."""
    try:
        canal.send(("ok", PROCESADORES[tipo](ruta)))
    except ValueError as e:                  # problema del contenido: el mensaje es para el usuario
        canal.send(("error", str(e)))
    except FileNotFoundError:
        canal.send(("error", "El archivo original ya no está disponible en el servidor."))
    except MemoryError:
        canal.send(("error", "Memoria insuficiente para procesar este archivo."))
    except Exception as e:                   # error interno: no mostramos rutas ni trazas al usuario
        canal.send(("error", f"Error interno al procesar ({type(e).__name__})."))
    finally:
        canal.close()


def ejecutar_con_limite(con, t):
    """Procesa en un proceso hijo con tiempo máximo, dando latidos mientras espera."""
    ruta = dentro_de_data(t["ruta_archivo"])
    receptor, emisor = multiprocessing.Pipe(duplex=False)
    hijo = multiprocessing.Process(target=_hijo, args=(t["tipo"], ruta, emisor), daemon=True)
    hijo.start()
    emisor.close()
    inicio = time.monotonic()
    try:
        while True:
            if receptor.poll(LATIDO_CADA_S):
                try:
                    return receptor.recv()
                except EOFError:             # el hijo murió sin responder (ej. lo mató el OOM killer)
                    break
            if not hijo.is_alive():
                break
            if time.monotonic() - inicio > TIMEOUT_TRABAJO_S:
                hijo.kill()
                return ("error", f"El procesamiento superó el tiempo máximo de {TIMEOUT_TRABAJO_S} s.")
            latido(con, trabajo_actual=t["id"])
    finally:
        hijo.join(5)
        receptor.close()
    if hijo.exitcode == -signal.SIGKILL:
        return ("error", "Memoria insuficiente: el proceso superó el límite de RAM del contenedor.")
    return ("error", f"El proceso de análisis terminó inesperadamente (código {hijo.exitcode}).")


def guardar_resultado(t, resultado):
    carpeta = os.path.join(DATA_DIR, "results", str(t["usuario_id"]))
    os.makedirs(carpeta, mode=0o700, exist_ok=True)
    ruta = os.path.join(carpeta, f"{t['id']}.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    os.chmod(ruta, 0o600)
    return ruta


def procesar(con, t):
    log.info("Trabajo %s: inicia (%s, %s bytes, intento %s)", t["id"], t["nombre_original"],
             t["tamano_bytes"], t["intentos"])
    inicio = time.monotonic()
    recurso = f"trabajo:{t['id']}"
    try:
        time.sleep(DEMORA)
        estado, contenido = ejecutar_con_limite(con, t)
    except PermissionError as e:
        estado, contenido = "error", "Ruta del archivo no válida."
        log.error("Trabajo %s: %s", t["id"], e)

    if estado == "ok":
        contenido.update({"trabajo": t["id"], "archivo": t["nombre_original"],
                          "procesado_por": NOMBRE, "duracion_s": round(time.monotonic() - inicio, 3)})
        ruta = guardar_resultado(t, contenido)
        # La guarda "AND worker = yo" evita que dos workers se pisen el resultado
        ok = sql(con, "UPDATE trabajos SET estado = 'completado', ruta_resultado = %s, terminado = now(), "
                      "error = NULL WHERE id = %s AND estado = 'en_ejecucion' AND worker = %s RETURNING id",
                 (ruta, t["id"], NOMBRE))
        if not ok:   # lo eliminaron o lo recuperó otro worker mientras tanto
            os.remove(ruta)
            log.warning("Trabajo %s: ya no me pertenece; resultado descartado", t["id"])
            return
        auditar(con, "procesar_ok", f"duracion={time.monotonic() - inicio:.2f}s", recurso)
        log.info("Trabajo %s: completado en %.2fs", t["id"], time.monotonic() - inicio)
    else:
        sql(con, "UPDATE trabajos SET estado = 'fallido', error = %s, terminado = now() "
                 "WHERE id = %s AND estado = 'en_ejecucion' AND worker = %s", (contenido[:500], t["id"], NOMBRE))
        auditar(con, "procesar_error", contenido[:200], recurso, resultado="error")
        log.error("Trabajo %s: FALLIDO - %s", t["id"], contenido)
    latido(con, procesado=True)


def main():
    log.info("Worker iniciado (%s) demora=%ss max_intentos=%s timeout=%ss",
             NOMBRE, DEMORA, MAX_INTENTOS, TIMEOUT_TRABAJO_S)
    while seguir:
        try:
            with psycopg.connect(DSN, row_factory=dict_row, autocommit=True) as con:
                latido(con)
                auditar(con, "worker_inicio", f"pid={os.getpid()}")
                recuperar_interrumpidos(con, al_arrancar=True)
                ultima_revision = time.monotonic()
                while seguir:
                    t = tomar_trabajo(con)
                    if t:
                        procesar(con, t)
                    else:
                        latido(con)
                        time.sleep(2)
                    if time.monotonic() - ultima_revision > LATIDO_CADUCO_S / 2:
                        recuperar_interrumpidos(con)   # rescata trabajos de workers que murieron
                        ultima_revision = time.monotonic()
                latido(con, estado="detenido")
                auditar(con, "worker_detenido", "salida ordenada (SIGTERM)")
        except psycopg.OperationalError as e:
            log.error("Sin conexión a la base de datos (%s). Reintento en 5 s", e)
            time.sleep(5)
    log.info("Worker detenido correctamente")


if __name__ == "__main__":
    main()
