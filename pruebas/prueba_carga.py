"""
Prueba de rendimiento con carga definida.
Envía N trabajos con los archivos del dataset y mide cuánto tarda el worker en procesarlos.
Uso:
    export CLAVE_DEMO='...'
    python3 pruebas/prueba_carga.py http://IP-DEL-SERVIDOR 30
Mientras corre, en el servidor ejecute:  docker stats   (para ver CPU y memoria del worker)
Se usa la cuenta tecnico1 (operador) porque la cuota de 3 trabajos aplica solo a agricultores.
"""
import os
import sys
import time

import requests

URL = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost").rstrip("/")
N = int(sys.argv[2]) if len(sys.argv) > 2 else 30
DATOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "datos_prueba")
ARCHIVOS = ["01_suelos_lote_A.csv", "02_suelos_lote_B.csv", "03_lluvias_2026.csv",
            "04_informe_visita_campo.txt", "05_bitacora_laboratorio.txt"]

s = requests.Session()
s.post(f"{URL}/login", data={"usuario": "tecnico1", "clave": os.environ["CLAVE_DEMO"]})

bytes_total = 0
inicio = time.time()
ids = []
for i in range(N):
    nombre = ARCHIVOS[i % len(ARCHIVOS)]
    ruta = os.path.join(DATOS, nombre)
    bytes_total += os.path.getsize(ruta)
    with open(ruta, "rb") as f:
        r = s.post(f"{URL}/subir", files={"archivo": (nombre, f)}, allow_redirects=False)
    ids.append(int(r.headers["Location"].split("/")[-1]))
envio = time.time() - inicio
print(f"Enviados {N} trabajos ({bytes_total / 1024:.0f} KB) en {envio:.1f} s")

pendientes = set(ids)
while pendientes:
    for tid in list(pendientes):
        if s.get(f"{URL}/api/trabajos/{tid}").json()["estado"] in ("completado", "fallido"):
            pendientes.discard(tid)
    print(f"  faltan {len(pendientes)}...", end="\r")
    time.sleep(1)
total = time.time() - inicio

datos = [s.get(f"{URL}/api/trabajos/{tid}").json() for tid in ids]
from datetime import datetime
esperas = [(datetime.fromisoformat(d["terminado"]) - datetime.fromisoformat(d["creado"])).total_seconds() for d in datos]
proc = [(datetime.fromisoformat(d["terminado"]) - datetime.fromisoformat(d["iniciado"])).total_seconds() for d in datos]
ok = sum(d["estado"] == "completado" for d in datos)

print("\n===== RESULTADO DE LA PRUEBA DE CARGA =====")
print(f"Trabajos enviados ............ {N}")
print(f"Completados / fallidos ....... {ok} / {N - ok}")
print(f"Tiempo total ................. {total:.1f} s")
print(f"Rendimiento .................. {N / total * 60:.1f} trabajos/minuto")
print(f"Procesamiento por trabajo .... prom {sum(proc) / N:.2f} s  (máx {max(proc):.2f} s)")
print(f"Espera total (cola+proceso) .. prom {sum(esperas) / N:.1f} s  (máx {max(esperas):.1f} s)")
