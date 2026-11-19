"""
Trabajador de procesamiento (contenedor 'worker').

Ciclo:  pendiente -> en_ejecucion -> completado | fallido

La "cola" es la tabla 'trabajos' de PostgreSQL. Para tomar un trabajo usamos
SELECT ... FOR UPDATE SKIP LOCKED: si hay varios workers, cada uno toma un
trabajo distinto sin pisarse (se puede escalar con: docker compose up -d --scale worker=2).
"""
import json
import logging
import os
import signal
import socket
import time

import psycopg
from psycopg.rows import dict_row

from procesadores import PROCESADORES

logging.basicConfig(level=logging.INFO, format="%(asctime)s worker %(levelname)s %(message)s")
log = logging.getLogger("worker")
os.umask(0o077)   # archivos y carpetas nuevos: solo el dueño puede leerlos

DSN = (
    f"host={os.environ.get('DB_HOST', 'db')} port={os.environ.get('DB_PORT', '5432')} "
    f"dbname={os.environ['POSTGRES_DB']} user={os.environ['POSTGRES_USER']} "
    f"password={os.environ['POSTGRES_PASSWORD']}"
)
DATA_DIR = os.environ.get("DATA_DIR", "/data")
DEMORA = float(os.environ.get("PROCESAMIENTO_DEMORA_S", "3"))   # pausa para poder observar el estado en la demo
NOMBRE = f"worker@{socket.gethostname()}"

seguir = True


def detener(signum, frame):
    """Al recibir SIGTERM (docker stop) terminamos el trabajo actual y salimos limpio."""
    global seguir
    log.info("Señal %s recibida: terminando después del trabajo actual", signum)
    seguir = False


signal.signal(signal.SIGTERM, detener)
signal.signal(signal.SIGINT, detener)


def sql(con, consulta, params=()):
    cur = con.execute(consulta, params)
    return cur.fetchone() if cur.description else None


def auditar(con, accion, detalle):
    sql(con, "INSERT INTO auditoria (usuario, accion, detalle) VALUES (%s, %s, %s)", (NOMBRE, accion, detalle))


def recuperar_interrumpidos(con):
    """Si el worker se cayó a mitad de un trabajo, al reiniciar lo devolvemos a la cola."""
    cur = con.execute("UPDATE trabajos SET estado = 'pendiente' WHERE estado = 'en_ejecucion' RETURNING id")
    ids = [r["id"] for r in cur.fetchall()]
    if ids:
        log.warning("Recuperados %d trabajos interrumpidos: %s", len(ids), ids)
        auditar(con, "recuperar_trabajos", f"ids={ids}")
    else:
        log.info("Sin trabajos interrumpidos que recuperar")


def tomar_trabajo(con):
    return sql(con, """
        UPDATE trabajos SET estado = 'en_ejecucion', iniciado = now(), intentos = intentos + 1
        WHERE id = (SELECT id FROM trabajos WHERE estado = 'pendiente'
                    ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1)
        RETURNING *""")


def procesar(con, t):
    log.info("Trabajo %s: inicia (%s, %s bytes)", t["id"], t["nombre_original"], t["tamano_bytes"])
    inicio = time.monotonic()
    try:
        time.sleep(DEMORA)
        resultado = PROCESADORES[t["tipo"]](t["ruta_archivo"])
        resultado.update({"trabajo": t["id"], "archivo": t["nombre_original"],
                          "procesado_por": NOMBRE, "duracion_s": round(time.monotonic() - inicio, 3)})
        carpeta = os.path.join(DATA_DIR, "results", str(t["usuario_id"]))
        os.makedirs(carpeta, mode=0o700, exist_ok=True)
        ruta = os.path.join(carpeta, f"{t['id']}.json")
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)
        os.chmod(ruta, 0o600)
        sql(con, "UPDATE trabajos SET estado = 'completado', ruta_resultado = %s, terminado = now() WHERE id = %s",
            (ruta, t["id"]))
        auditar(con, "procesar_ok", f"trabajo={t['id']}")
        log.info("Trabajo %s: completado en %.2fs", t["id"], time.monotonic() - inicio)
    except Exception as e:
        sql(con, "UPDATE trabajos SET estado = 'fallido', error = %s, terminado = now() WHERE id = %s",
            (str(e)[:500], t["id"]))
        auditar(con, "procesar_error", f"trabajo={t['id']} error={str(e)[:200]}")
        log.error("Trabajo %s: FALLIDO - %s", t["id"], e)


def main():
    log.info("Worker iniciado (%s), demora=%ss", NOMBRE, DEMORA)
    while seguir:
        try:
            with psycopg.connect(DSN, row_factory=dict_row, autocommit=True) as con:
                recuperar_interrumpidos(con)
                while seguir:
                    t = tomar_trabajo(con)
                    if t:
                        procesar(con, t)
                    else:
                        time.sleep(2)
        except psycopg.OperationalError as e:
            log.error("Sin conexión a la base de datos (%s). Reintento en 5 s", e)
            time.sleep(5)
    log.info("Worker detenido correctamente")


if __name__ == "__main__":
    main()
