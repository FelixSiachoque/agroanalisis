"""
Panel de RECURSOS: consumo real de cada contenedor frente a su límite.

Fuentes (sin el socket de Docker, que daría control de root sobre el servidor):
  - app:    lee su PROPIO cgroup v2 (/sys/fs/cgroup) en el momento de la consulta
  - worker: cada worker escribe sus métricas de cgroup en la tabla 'workers' con cada latido
  - disco:  shutil.disk_usage('/data') del volumen compartido
  - BD:     tamaño de la base y conexiones abiertas (pg_database_size, pg_stat_activity)
"""
import shutil
import time
from datetime import datetime, timezone

from cgroup import leer_metricas
from config import DATA_DIR, LATIDO_CADUCO_S
from db import consulta

MB = 1024 * 1024


def porcentaje(usado, limite):
    return round(100 * usado / limite, 1) if usado is not None and limite else None


def interpretar_memoria(nombre, usado, limite, archivo_mb):
    """Frase en lenguaje natural para explicar el dato en la sustentación."""
    if usado is None:
        return f"No se pudo leer la memoria de {nombre}."
    if not limite:
        return f"{nombre} usa {usado / MB:.0f} MB y NO tiene límite de memoria: podría afectar al servidor."
    pct = 100 * usado / limite
    base = f"{nombre} usa {usado / MB:.0f} MB de {limite / MB:.0f} MB ({pct:.0f} %)"
    if pct < 60:
        return f"{base}: margen suficiente para procesar un archivo de {archivo_mb:g} MB."
    if pct < 85:
        return f"{base}: uso alto; con archivos grandes conviene subir el límite."
    return f"{base}: cerca del límite; el kernel podría matar el proceso por falta de memoria (OOM)."


def cpu_instantanea():
    """% de CPU de la app en los últimos 0,2 s (dos lecturas de cpu.stat)."""
    a = leer_metricas()["cpu_uso_usec"]
    t0 = time.monotonic()
    time.sleep(0.2)
    b = leer_metricas()["cpu_uso_usec"]
    if a is None or b is None:
        return None
    return round(100 * (b - a) / 1e6 / (time.monotonic() - t0), 1)


def recursos_app(archivo_mb):
    m = leer_metricas()
    return dict(m, nombre="app", cpu_pct=cpu_instantanea(),
                mem_pct=porcentaje(m["memoria_bytes"], m["memoria_max"]),
                frase=interpretar_memoria("La app", m["memoria_bytes"], m["memoria_max"], archivo_mb))


def recursos_workers(archivo_mb):
    ahora = datetime.now(timezone.utc)
    filas = consulta("SELECT * FROM workers ORDER BY ultimo_latido DESC")
    salida = []
    for w in filas:
        segundos = (ahora - w["ultimo_latido"]).total_seconds()
        vivo = w["estado"] == "activo" and segundos < LATIDO_CADUCO_S
        activo_s = max((w["ultimo_latido"] - w["iniciado"]).total_seconds(), 1)
        salida.append(dict(
            w, vivo=vivo, hace_s=int(segundos),
            mem_pct=porcentaje(w["memoria_bytes"], w["memoria_max"]),
            # promedio de CPU desde que arrancó = tiempo de CPU usado / tiempo transcurrido
            cpu_promedio_pct=(round(100 * w["cpu_uso_usec"] / 1e6 / activo_s, 1)
                              if w["cpu_uso_usec"] is not None else None),
            frase=(interpretar_memoria("El worker", w["memoria_bytes"], w["memoria_max"], archivo_mb) if vivo
                   else f"Sin latido hace {int(segundos)} s: el worker está detenido o caído."),
        ))
    return salida


def recursos_generales():
    uso = shutil.disk_usage(DATA_DIR)
    bd = consulta("SELECT pg_database_size(current_database()) AS bytes, "
                  "(SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()) AS conexiones",
                  uno=True)
    estados = {r["estado"]: r["n"] for r in consulta("SELECT estado, count(*) AS n FROM trabajos GROUP BY estado")}
    return {
        "disco_total": uso.total, "disco_usado": uso.used, "disco_libre": uso.free,
        "disco_pct": porcentaje(uso.used, uso.total),
        "bd_bytes": bd["bytes"], "bd_conexiones": bd["conexiones"],
        "estados": {e: estados.get(e, 0) for e in ("pendiente", "en_ejecucion", "completado", "fallido")},
    }
