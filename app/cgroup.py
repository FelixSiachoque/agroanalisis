"""
Lectura de los límites y el consumo del PROPIO contenedor desde cgroups v2.
(No se usa el socket de Docker: montarlo daría control de root sobre el servidor.)

Archivos que lee (dentro de cada contenedor, en /sys/fs/cgroup/):
  memory.current  -> bytes de RAM usados ahora
  memory.max      -> límite de RAM ("max" = sin límite)  <- lo fija mem_limit en docker-compose.yml
  cpu.max         -> "cuota periodo" ("50000 100000" = 0.5 CPU) <- lo fija cpus
  cpu.stat        -> usage_usec = microsegundos de CPU consumidos desde que arrancó
  pids.current / pids.max -> procesos actuales y límite <- lo fija pids_limit
NOTA: este archivo está repetido en app/ y worker/ (son imágenes distintas); si cambia uno, copie el otro.
"""
import os

RAIZ = "/sys/fs/cgroup"


def _leer(nombre):
    try:
        with open(os.path.join(RAIZ, nombre)) as f:
            return f.read().strip()
    except OSError:
        return None


def _entero(texto):
    return int(texto) if texto and texto.isdigit() else None


def leer_metricas():
    cpu_max = (_leer("cpu.max") or "").split()
    cpu_limite = None
    if len(cpu_max) == 2 and cpu_max[0] != "max":
        cpu_limite = round(int(cpu_max[0]) / int(cpu_max[1]), 2)
    uso_usec = None
    for linea in (_leer("cpu.stat") or "").splitlines():
        if linea.startswith("usage_usec"):
            uso_usec = int(linea.split()[1])
    return {
        "memoria_bytes": _entero(_leer("memory.current")),
        "memoria_max": _entero(_leer("memory.max")),     # None si es "max" (sin límite)
        "cpu_limite": cpu_limite,                        # None si no hay límite de CPU
        "cpu_uso_usec": uso_usec,
        "pids": _entero(_leer("pids.current")),
        "pids_max": _entero(_leer("pids.max")),
    }
