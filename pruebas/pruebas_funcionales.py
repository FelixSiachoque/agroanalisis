"""
Pruebas funcionales y de seguridad (reproducibles) contra la aplicación desplegada.

Uso:
    pip install requests
    export CLAVE_ADMIN='...'  CLAVE_DEMO='...'      # las del .env (ADMIN_PASSWORD y DEMO_PASSWORD)
    python3 pruebas/pruebas_funcionales.py http://localhost            # o la IP pública de EC2
    python3 pruebas/pruebas_funcionales.py http://localhost --docker   # + reinicio del worker

Requiere las cuentas demo (./scripts/crear_usuarios_demo.sh).
Las pruebas de reglas de negocio consultan /api/reglas y solo se ejecutan si la regla está
activa: encender o apagar una regla nunca rompe el resto de la suite.
--docker: además mata y reinicia el worker (solo si se ejecuta en el mismo servidor del stack).
"""
import concurrent.futures
import csv
import hashlib
import io
import os
import re
import subprocess
import sys
import time

import requests

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
URL = (ARGS[0] if ARGS else "http://localhost").rstrip("/")
CON_DOCKER = "--docker" in sys.argv
ADMIN = os.environ.get("ADMIN_USER", "coordinador")
CLAVE_ADMIN = os.environ["CLAVE_ADMIN"]
CLAVE_DEMO = os.environ["CLAVE_DEMO"]
DATOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "datos_prueba")
resultados = []


def prueba(nombre, condicion, detalle=""):
    resultados.append(bool(condicion))
    print(f"[{'PASA' if condicion else 'FALLA'}] {nombre}" + (f"  ({detalle})" if detalle else ""), flush=True)


def seccion(titulo):
    print(f"\n--- {titulo}")


class Cliente:
    """Sesión de navegador: guarda la cookie y el token anti-CSRF de los formularios."""

    def __init__(self, usuario=None, clave=None):
        self.s = requests.Session()
        self.csrf = ""
        self.codigo_login = None
        if usuario:
            self.codigo_login = self.login(usuario, clave)

    def _token(self, html):
        m = re.search(r'name="csrf" value="([^"]+)"', html)
        if m:
            self.csrf = m.group(1)

    def login(self, usuario, clave):
        self._token(self.s.get(f"{URL}/login").text)
        r = self.s.post(f"{URL}/login", data={"usuario": usuario, "clave": clave, "csrf": self.csrf},
                        allow_redirects=False)
        if r.status_code == 302:
            self._token(self.s.get(f"{URL}/").text)
        return r.status_code

    def get(self, ruta, **kw):
        return self.s.get(f"{URL}{ruta}", **kw)

    def post(self, ruta, datos=None, sin_csrf=False, **kw):
        datos = dict(datos or {})
        if not sin_csrf:
            datos["csrf"] = self.csrf
        return self.s.post(f"{URL}{ruta}", data=datos, allow_redirects=False, **kw)

    def subir(self, archivo, contenido=None):
        """Devuelve (id_trabajo o None, código HTTP)."""
        if contenido is None:
            with open(os.path.join(DATOS, archivo), "rb") as f:
                contenido = f.read()
        r = self.post("/subir", files={"archivo": (archivo, contenido)})
        loc = r.headers.get("Location", "")
        tid = int(loc.rstrip("/").split("/")[-1]) if "/trabajos/" in loc else None
        return tid, r.status_code

    def estado(self, tid):
        return self.get(f"/api/trabajos/{tid}").json()

    def esperar(self, tid, limite=120):
        for _ in range(limite):
            e = self.estado(tid)["estado"]
            if e in ("completado", "fallido"):
                return e
            time.sleep(1)
        return "timeout"


def esperar_todos(cliente, ids):
    for t in ids:
        if t:
            cliente.esperar(t)


print(f"== Pruebas contra {URL} ==")
prueba("La aplicación responde (/health)", requests.get(f"{URL}/health").status_code == 200)

# ------------------------------------------------------------------ autenticación
seccion("Autenticación")
c = Cliente("agricultor1", "clave-incorrecta").codigo_login
prueba("Login con contraseña incorrecta es rechazado", c == 401, f"HTTP {c}")
a1 = Cliente("agricultor1", CLAVE_DEMO)
prueba("Login agricultor1 (rol usuario)", a1.codigo_login == 302, f"HTTP {a1.codigo_login}")
a2 = Cliente("agricultor2", CLAVE_DEMO)
op = Cliente("tecnico1", CLAVE_DEMO)
prueba("Login tecnico1 (rol operador)", op.codigo_login == 302, f"HTTP {op.codigo_login}")
ad = Cliente(ADMIN, CLAVE_ADMIN)
prueba("Login administrador", ad.codigo_login == 302, f"HTTP {ad.codigo_login}")
prueba("Sin sesión no se accede al panel", requests.get(f"{URL}/", allow_redirects=False).status_code == 302)

REGLAS = {r["nombre"]: r for r in a1.get("/api/reglas").json()}
ACTIVAS = {n for n, r in REGLAS.items() if r["activa"]}
print(f"    reglas de negocio activas: {', '.join(sorted(ACTIVAS)) or '(ninguna)'}")

# Si se exige una cabecera CSV, el flujo principal usa archivos que la cumplen
CABECERA = REGLAS["cabecera_csv_obligatoria"]["parametros"]["cabecera"] if "cabecera_csv_obligatoria" in ACTIVAS else None
if CABECERA:
    CSV_OK = ("10_regla_cabecera_cumple.csv", None)
    CSV_MAL_FORMADO = ("mal_formado.csv", f"{CABECERA}\nL-01,2026-01-01\nL-02,2026-01-02,6.1\n".encode())
else:
    CSV_OK = ("01_suelos_lote_A.csv", None)
    CSV_MAL_FORMADO = ("06_invalido_columnas.csv", None)
with open(os.path.join(DATOS, CSV_OK[0]), "rb") as f:
    INICIO_CSV_OK = f.read(20)

# ------------------------------------------------------------------ CSRF
seccion("Protección CSRF")
r = a1.post("/subir", files={"archivo": ("x.txt", b"hola")}, sin_csrf=True)
prueba("Formulario sin token CSRF es rechazado", r.status_code == 400, f"HTTP {r.status_code}")
r = requests.post(f"{URL}/login", data={"usuario": ADMIN, "clave": CLAVE_ADMIN}, allow_redirects=False)
prueba("Login sin token CSRF es rechazado", r.status_code == 400, f"HTTP {r.status_code}")

# ------------------------------------------------------------------ autorización por rol
seccion("Autorización por rol (en el servidor)")
for cliente, nombre, ruta, esperado in [
    (a1, "Usuario NO puede gestionar usuarios", "/admin/usuarios", 403),
    (a1, "Usuario NO puede ver el panel de operación", "/operacion", 403),
    (a1, "Usuario NO puede ver la auditoría", "/admin/auditoria", 403),
    (op, "Operador SÍ puede ver el panel de operación", "/operacion", 200),
    (op, "Operador NO puede ver la auditoría", "/admin/auditoria", 403),
    (op, "Operador NO puede gestionar usuarios", "/admin/usuarios", 403),
    (ad, "Administrador SÍ puede gestionar usuarios", "/admin/usuarios", 200),
    (ad, "Administrador SÍ ve las reglas de negocio", "/admin/reglas", 200),
]:
    c = cliente.get(ruta).status_code
    prueba(nombre, c == esperado, f"HTTP {c}")
r = a1.post("/admin/usuarios", {"accion": "crear", "usuario": "intruso", "clave": "12345678", "rol": "admin"})
prueba("Usuario NO puede crear cuentas por POST directo", r.status_code == 403, f"HTTP {r.status_code}")

# ------------------------------------------------------------------ política técnica de archivos
seccion("Política de archivos")
prueba("Rechaza extensión .exe", a1.subir("07_invalido_programa.exe")[0] is None)
prueba("Rechaza binario disfrazado de .txt", a1.subir("08_invalido_binario.txt")[0] is None)
prueba("Rechaza archivo vacío", a1.subir("vacio.txt", b"")[0] is None)
tid_nombre, codigo = a1.subir("../../etc/passwd.txt", b"intento de ruta")
if tid_nombre:
    nombre = a1.estado(tid_nombre)["nombre_original"]
    prueba("El nombre con '../' se guarda saneado", nombre == "passwd.txt", nombre)
    a1.esperar(tid_nombre)
if os.path.exists(os.path.join(DATOS, "archivo_grande.txt")):
    prueba("Rechaza archivo de más de 2 MB", a1.subir("archivo_grande.txt")[0] is None)

# ------------------------------------------------------------------ procesamiento asíncrono
seccion("Procesamiento asíncrono y estados")
tid, _ = a1.subir(*CSV_OK)
prueba("Acepta CSV válido y crea trabajo", tid is not None, f"trabajo #{tid}")
estado_inicial = a1.estado(tid)["estado"]
prueba("El trabajo queda en cola (no se procesa en la petición)", estado_inicial in ("pendiente", "en_ejecucion"),
       estado_inicial)
prueba("El worker lo completa", a1.esperar(tid) == "completado")
info = a1.estado(tid)
prueba("Ciclo completo de estados con fechas (creado, iniciado, terminado)",
       all(info.get(k) for k in ("creado", "iniciado", "terminado")))
r = a1.get(f"/trabajos/{tid}/descargar")
prueba("El dueño descarga su resultado", r.status_code == 200 and '"estadisticas"' in r.text)
r = a1.get(f"/trabajos/{tid}/original")
prueba("El dueño descarga su archivo original", r.status_code == 200 and r.content.startswith(INICIO_CSV_OK))
tid_malo, _ = a1.subir(*CSV_MAL_FORMADO)
prueba("CSV mal formado termina en estado 'fallido'", a1.esperar(tid_malo) == "fallido")
prueba("El error del worker no revela rutas internas", "/data" not in (a1.estado(tid_malo)["error"] or ""))

# ------------------------------------------------------------------ aislamiento (IDOR)
seccion("Aislamiento entre usuarios (IDOR)")
for nombre, ruta, metodo in [
    ("ver el detalle", f"/trabajos/{tid}", "get"),
    ("ver por la API", f"/api/trabajos/{tid}", "get"),
    ("descargar el resultado", f"/trabajos/{tid}/descargar", "get"),
    ("descargar el original", f"/trabajos/{tid}/original", "get"),
    ("eliminar", f"/trabajos/{tid}/eliminar", "post"),
]:
    c = (a2.get(ruta) if metodo == "get" else a2.post(ruta)).status_code
    prueba(f"agricultor2 NO puede {nombre} de agricultor1", c == 404, f"HTTP {c}")
c = a2.get("/trabajos/999999").status_code
prueba("Un trabajo inexistente responde igual (404)", c == 404, f"HTTP {c}")
c = op.get(f"/trabajos/{tid}/descargar").status_code
prueba("Operador NO descarga resultados ajenos (privacidad)", c == 404, f"HTTP {c}")
c = op.get(f"/trabajos/{tid}").status_code
prueba("Operador SÍ ve el detalle (supervisión)", c == 200, f"HTTP {c}")
c = a2.post(f"/trabajos/{tid_malo}/reprocesar").status_code
prueba("Usuario NO puede reprocesar (permiso)", c == 403, f"HTTP {c}")

# ------------------------------------------------------------------ reprocesar
seccion("Reprocesar")
c = op.post(f"/trabajos/{tid}/reprocesar").status_code
prueba("No se reprocesa un trabajo completado", c == 409, f"HTTP {c}")
c = op.post(f"/trabajos/{tid_malo}/reprocesar").status_code
prueba("Operador reprocesa un trabajo fallido", c == 302, f"HTTP {c}")
prueba("El trabajo reprocesado vuelve a terminar", a1.esperar(tid_malo) == "fallido")

# ------------------------------------------------------------------ reglas de negocio (según /api/reglas)
seccion("Reglas de negocio activas")
if "bloquear_borrado_finalizados" in ACTIVAS:
    c = a1.post(f"/trabajos/{tid}/eliminar").status_code
    prueba("[regla] Agricultor NO puede eliminar un resultado completado", c == 403, f"HTTP {c}")
    c = a1.post(f"/trabajos/{tid_malo}/eliminar").status_code
    prueba("[regla] Agricultor SÍ puede eliminar un trabajo fallido", c == 302, f"HTTP {c}")
if "cuota_trabajos_activos" in ACTIVAS:
    maximo = REGLAS["cuota_trabajos_activos"]["parametros"]["max"]
    archivo = "04_informe_visita_campo.txt"   # .txt pequeño: no lo afectan las reglas de CSV ni de tamaño
    ids = [a2.subir(archivo)[0] for _ in range(maximo + 1)]
    prueba(f"[regla] Cuota: el trabajo activo n.º {maximo + 1} de un agricultor es rechazado",
           all(ids[:maximo]) and ids[maximo] is None, f"ids={ids}")
    esperar_todos(a2, ids)
if "cabecera_csv_obligatoria" in ACTIVAS:
    prueba("[regla] CSV sin la cabecera exigida es rechazado", a1.subir("01_suelos_lote_A.csv")[0] is None)
    t_ok, _ = a1.subir("10_regla_cabecera_cumple.csv")
    prueba("[regla] CSV con la cabecera exigida es aceptado", t_ok is not None)
    a1.esperar(t_ok) if t_ok else None
if "rangos_agronomicos_validos" in ACTIVAS:
    prueba("[regla] CSV con pH fuera de 0-14 es rechazado", a1.subir("13_regla_rangos_viola.csv")[0] is None)
if "bloquear_descarga_originales_ajenos" in ACTIVAS:
    c = ad.get(f"/trabajos/{tid}/original").status_code
    prueba("[regla] El coordinador SÍ descarga el original ajeno", c == 200, f"HTTP {c}")
if not ACTIVAS:
    print("    (no hay reglas activas: se omiten)")

# ------------------------------------------------------------------ recuperación del worker
if CON_DOCKER:
    seccion("Recuperación del worker (docker)")
    tid_r, _ = op.subir(CSV_OK[0] if CABECERA else "02_suelos_lote_B.csv")
    prueba("Se encola un trabajo para la prueba de recuperación", tid_r is not None)
    for _ in range(30):
        if op.estado(tid_r)["estado"] == "en_ejecucion":
            break
        time.sleep(0.5)
    raiz = os.path.join(DATOS, "..")
    subprocess.run(["docker", "compose", "kill", "worker"], check=True, capture_output=True, cwd=raiz)
    prueba("Trabajo interrumpido queda 'en_ejecucion' con el worker caído",
           op.estado(tid_r)["estado"] == "en_ejecucion")
    subprocess.run(["docker", "compose", "start", "worker"], check=True, capture_output=True, cwd=raiz)
    prueba("Al reiniciar, el worker recupera y completa el trabajo", op.esperar(tid_r) == "completado")
    prueba("El trabajo recuperado registra 2 intentos", op.estado(tid_r)["intentos"] == 2)

# ------------------------------------------------------------------ auditoría
seccion("Auditoría")
texto = ad.get("/admin/auditoria?resultado=denegado").text
prueba("La auditoría registra accesos denegados", "acceso_denegado" in texto)
prueba("La auditoría registra el rechazo CSRF", "csrf_rechazado" in texto)
if "cuota_trabajos_activos" in ACTIVAS:
    prueba("La auditoría registra la regla de cuota", "regla_cuota_trabajos_activos" in texto)
csv_r = ad.get("/admin/auditoria.csv?usuario=agricultor2")
prueba("Exporta reporte CSV de auditoría por usuario", csv_r.status_code == 200 and "agricultor2" in csv_r.text)
Cliente("=HYPERLINK(1)", "x")
celdas = [c for fila in csv.reader(io.StringIO(ad.get("/admin/auditoria.csv?accion=login_fallido").text))
          for c in fila]
prueba("El CSV exportado neutraliza fórmulas (CSV injection)",
       "'=HYPERLINK(1)" in celdas and not any(c.startswith("=") for c in celdas))
largo = Cliente("x" * 300, "x").codigo_login
prueba("Un usuario de 300 caracteres no provoca error 500", largo == 401, f"HTTP {largo}")

# ------------------------------------------------------------------ sello de autenticidad
seccion("Sello de autenticidad (cadena de custodia)")
info = a1.estado(tid)
r = a1.get(f"/trabajos/{tid}/descargar")
prueba("El resultado descargado coincide con su SHA-256 registrado",
       info.get("sha256_resultado") == hashlib.sha256(r.content).hexdigest())
with open(os.path.join(DATOS, CSV_OK[0]), "rb") as f:
    prueba("El SHA-256 del original se registró al recibirlo",
           info.get("sha256_original") == hashlib.sha256(f.read()).hexdigest())
# Muchos eventos simultáneos (2 procesos de Gunicorn): la cadena no debe romperse
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as hilos:
    list(hilos.map(lambda _: a1.get("/admin/auditoria"), range(40)))
v = ad.get("/api/auditoria/verificar").json()
prueba("Tras 40 eventos concurrentes la cadena de auditoría sigue íntegra", v["integra"], v["mensaje"])
c = a1.get("/api/auditoria/verificar").status_code
prueba("Solo el coordinador verifica la cadena", c == 403, f"HTTP {c}")

if CON_DOCKER:
    raiz = os.path.join(DATOS, "..")

    def demo(*args):
        return subprocess.run(["bash", "scripts/demo_sello.sh", *args], cwd=raiz, capture_output=True,
                              text=True, encoding="utf-8")

    salida = demo("intentar-modificar").stdout + demo("intentar-modificar").stderr
    prueba("La app (agro_web) no puede modificar la auditoría", "permission denied" in salida)
    prueba("El superusuario tampoco: el trigger lo bloquea", "solo inserción" in salida)
    evento = ad.get("/admin/auditoria.csv?accion=login_ok").text.splitlines()[-1].split(",")[0]
    demo("alterar", evento)
    v = ad.get("/api/auditoria/verificar").json()
    prueba("Alterar un evento viejo rompe la cadena justo en ese evento",
           not v["integra"] and str(v["evento_id"]) == evento, v["mensaje"])
    demo("restaurar", evento)
    v = ad.get("/api/auditoria/verificar").json()
    prueba("Al restaurarlo la cadena vuelve a estar íntegra", v["integra"], v["mensaje"])

    subprocess.run(["docker", "compose", "stop", "worker"], check=True, capture_output=True, cwd=raiz)
    t_m, _ = op.subir(CSV_OK[0] if CABECERA else "09_sello_manipular.csv")
    demo("manipular", str(t_m))
    subprocess.run(["docker", "compose", "start", "worker"], check=True, capture_output=True, cwd=raiz)
    prueba("Un archivo manipulado en /data no se procesa", op.esperar(t_m) == "fallido")
    prueba("...y queda marcado 'integridad_comprometida'",
           (op.estado(t_m)["error"] or "").startswith("integridad_comprometida"))
    c = op.get(f"/trabajos/{t_m}/original").status_code
    prueba("...y su original alterado no se entrega", c == 409, f"HTTP {c}")
    texto = ad.get("/admin/auditoria?accion=integridad_comprometida").text
    prueba("...y la auditoría lo registra", f"trabajo:{t_m}" in texto)

print(f"\nResultado: {sum(resultados)} de {len(resultados)} pruebas pasaron")
sys.exit(0 if all(resultados) else 1)
