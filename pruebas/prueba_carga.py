"""
Prueba de rendimiento con carga DEFINIDA y resultados guardados.

Uso:
    pip install requests
    export CLAVE_DEMO='...'          # DEMO_PASSWORD del .env
    python3 pruebas/prueba_carga.py http://localhost --trabajos 30 --concurrencia 4
    python3 pruebas/prueba_carga.py http://IP --trabajos 60 --concurrencia 8 --archivos 02_suelos_lote_B.csv

Parámetros:
    --trabajos N       cuántos trabajos se envían (defecto 30)
    --concurrencia C   cuántos envíos simultáneos (hilos) (defecto 4)
    --archivos a,b,c   archivos de datos_prueba/ que se rotan (defecto: los 5 válidos)
    --usuario U        cuenta que sube los archivos (defecto tecnico1)
    --salida DIR       carpeta para el informe .md y el .csv (defecto resultados/)

Sobre la regla de cuota: 'cuota_trabajos_activos' limita a 3 trabajos en cola por AGRICULTOR.
Por eso, por defecto, se usa tecnico1 (rol operador), que no está sujeto a esa regla; el
script lo comprueba en /api/reglas y lo deja escrito en el informe.

Mientras corre, en el servidor:  docker stats   (o ./scripts/evidencias.sh)
"""
import argparse
import concurrent.futures
import csv
import os
import re
import statistics
import sys
import time
from datetime import datetime

import requests

RAIZ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DATOS = os.path.join(RAIZ, "datos_prueba")
VALIDOS = ["01_suelos_lote_A.csv", "02_suelos_lote_B.csv", "03_lluvias_2026.csv",
           "04_informe_visita_campo.txt", "05_bitacora_laboratorio.txt"]

p = argparse.ArgumentParser(description="Prueba de carga de AgroAnálisis Sugamuxi")
p.add_argument("url", nargs="?", default="http://localhost")
p.add_argument("--trabajos", type=int, default=30)
p.add_argument("--concurrencia", type=int, default=4)
p.add_argument("--archivos", default=",".join(VALIDOS))
p.add_argument("--usuario", default="tecnico1")
p.add_argument("--salida", default=os.path.join(RAIZ, "resultados"))
args = p.parse_args()
URL = args.url.rstrip("/")
ARCHIVOS = args.archivos.split(",")
CLAVE = os.environ["CLAVE_DEMO"]


def nueva_sesion():
    s = requests.Session()
    token = re.search(r'name="csrf" value="([^"]+)"', s.get(f"{URL}/login").text).group(1)
    r = s.post(f"{URL}/login", data={"usuario": args.usuario, "clave": CLAVE, "csrf": token}, allow_redirects=False)
    if r.status_code != 302:
        sys.exit(f"No se pudo iniciar sesión como {args.usuario} (HTTP {r.status_code})")
    s.csrf = re.search(r'name="csrf" value="([^"]+)"', s.get(f"{URL}/").text).group(1)
    return s


principal = nueva_sesion()
reglas = {r["nombre"]: r for r in principal.get(f"{URL}/api/reglas").json()}
cuota = reglas.get("cuota_trabajos_activos", {})
afectado = cuota.get("activa") and "usuario" in cuota.get("parametros", {}).get("roles_afectados", []) \
    and args.usuario.startswith("agricultor")
nota_cuota = (f"La regla de cuota está {'ACTIVA' if cuota.get('activa') else 'inactiva'} "
              f"(máx. {cuota.get('parametros', {}).get('max')} por agricultor). "
              + (f"La cuenta {args.usuario} SÍ está sujeta: los envíos que superen la cuota serán rechazados."
                 if afectado else f"La cuenta {args.usuario} no está sujeta a la cuota."))
print(nota_cuota)

sesiones = {}


def enviar(i):
    """Un hilo = una sesión propia (requests.Session no se comparte entre hilos)."""
    import threading
    hilo = threading.get_ident()
    if hilo not in sesiones:
        sesiones[hilo] = nueva_sesion()
    s = sesiones[hilo]
    nombre = ARCHIVOS[i % len(ARCHIVOS)]
    with open(os.path.join(DATOS, nombre), "rb") as f:
        contenido = f.read()
    t0 = time.monotonic()
    r = s.post(f"{URL}/subir", files={"archivo": (nombre, contenido)}, data={"csrf": s.csrf},
               allow_redirects=False)
    loc = r.headers.get("Location", "")
    tid = int(loc.rstrip("/").split("/")[-1]) if "/trabajos/" in loc else None
    return {"i": i, "archivo": nombre, "bytes": len(contenido), "http": r.status_code, "id": tid,
            "envio_s": time.monotonic() - t0}


print(f"Enviando {args.trabajos} trabajos con concurrencia {args.concurrencia} a {URL} ...")
inicio = time.monotonic()
with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrencia) as hilos:
    envios = list(hilos.map(enviar, range(args.trabajos)))
fin_envio = time.monotonic() - inicio
aceptados = [e for e in envios if e["id"]]
rechazados = [e for e in envios if not e["id"]]
print(f"  enviados en {fin_envio:.1f} s: {len(aceptados)} aceptados, {len(rechazados)} rechazados")

pendientes = {e["id"] for e in aceptados}
while pendientes and time.monotonic() - inicio < 1800:
    for tid in list(pendientes):
        if principal.get(f"{URL}/api/trabajos/{tid}").json()["estado"] in ("completado", "fallido"):
            pendientes.discard(tid)
    print(f"\r  en cola o en proceso: {len(pendientes):3d}", end="", flush=True)
    time.sleep(1)
total = time.monotonic() - inicio
print()

detalle = {e["id"]: principal.get(f"{URL}/api/trabajos/{e['id']}").json() for e in aceptados}
filas = []
for e in envios:
    d = detalle.get(e["id"], {})
    proceso = espera = None
    if d.get("terminado") and d.get("iniciado"):
        proceso = (datetime.fromisoformat(d["terminado"]) - datetime.fromisoformat(d["iniciado"])).total_seconds()
        espera = (datetime.fromisoformat(d["terminado"]) - datetime.fromisoformat(d["creado"])).total_seconds()
    filas.append(dict(e, estado=d.get("estado", "rechazado"), proceso_s=proceso, total_s=espera))

ok = [f for f in filas if f["estado"] == "completado"]
procs = [f["proceso_s"] for f in filas if f["proceso_s"] is not None]
esperas = [f["total_s"] for f in filas if f["total_s"] is not None]
kb = sum(f["bytes"] for f in filas) / 1024
resumen = [
    ("Trabajos enviados", f"{args.trabajos} ({kb:.0f} KB en total)"),
    ("Concurrencia de envío", f"{args.concurrencia} hilos"),
    ("Aceptados / rechazados al subir", f"{len(aceptados)} / {len(rechazados)}"),
    ("Completados / fallidos", f"{len(ok)} / {len(aceptados) - len(ok)}"),
    ("Tiempo total (envío + vaciar la cola)", f"{total:.1f} s"),
    ("Throughput", f"{len(aceptados) / total * 60:.1f} trabajos/minuto"),
    ("Procesamiento por trabajo (promedio / máx.)",
     f"{statistics.mean(procs):.2f} s / {max(procs):.2f} s" if procs else "—"),
    ("Tiempo en el sistema por trabajo, cola + proceso (promedio / máx.)",
     f"{statistics.mean(esperas):.1f} s / {max(esperas):.1f} s" if esperas else "—"),
]
print("\n===== RESULTADO DE LA PRUEBA DE CARGA =====")
for k, v in resumen:
    print(f"{k:.<60} {v}")

os.makedirs(args.salida, exist_ok=True)
marca = datetime.now().strftime("%Y%m%d_%H%M")
ruta_csv = os.path.join(args.salida, f"carga_{marca}.csv")
with open(ruta_csv, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["i", "id", "archivo", "bytes", "http", "envio_s", "estado", "proceso_s", "total_s"])
    w.writeheader()
    w.writerows(filas)
ruta_md = os.path.join(args.salida, f"carga_{marca}.md")
with open(ruta_md, "w", encoding="utf-8") as f:
    f.write(f"# Prueba de carga · {datetime.now():%Y-%m-%d %H:%M}\n\n")
    f.write(f"- Servidor: `{URL}`\n- Cuenta: `{args.usuario}`\n- Archivos rotados: {', '.join(ARCHIVOS)}\n")
    f.write(f"- {nota_cuota}\n\n| Métrica | Valor |\n|---|---|\n")
    for k, v in resumen:
        f.write(f"| {k} | {v} |\n")
    f.write("\nEl worker añade una pausa fija de PROCESAMIENTO_DEMORA_S por trabajo (para la demo); "
            "el throughput real sin esa pausa es mayor. Detalle por trabajo en el CSV del mismo nombre.\n")
print(f"\nInforme guardado en {ruta_md} y {ruta_csv}")
