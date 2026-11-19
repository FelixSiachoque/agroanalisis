"""
Pruebas funcionales y de seguridad (reproducibles).
Uso:
    pip install requests
    export CLAVE_ADMIN='...'  CLAVE_DEMO='...'      # las del .env
    python3 pruebas/pruebas_funcionales.py http://IP-DEL-SERVIDOR
Requiere las cuentas demo (./scripts/crear_usuarios_demo.sh).
"""
import os
import sys
import time

import requests

URL = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost").rstrip("/")
ADMIN = os.environ.get("ADMIN_USER", "coordinador")
CLAVE_ADMIN = os.environ["CLAVE_ADMIN"]
CLAVE_DEMO = os.environ["CLAVE_DEMO"]
DATOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "datos_prueba")
resultados = []


def prueba(nombre, condicion, detalle=""):
    resultados.append(condicion)
    print(f"[{'PASA' if condicion else 'FALLA'}] {nombre}" + (f"  ({detalle})" if detalle else ""))


def sesion(usuario, clave):
    s = requests.Session()
    r = s.post(f"{URL}/login", data={"usuario": usuario, "clave": clave}, allow_redirects=False)
    return s, r.status_code


def subir(s, archivo):
    with open(os.path.join(DATOS, archivo), "rb") as f:
        r = s.post(f"{URL}/subir", files={"archivo": (archivo, f)}, allow_redirects=False)
    loc = r.headers.get("Location", "")
    return int(loc.rstrip("/").split("/")[-1]) if "/trabajos/" in loc else None


def esperar(s, tid, limite=90):
    for _ in range(limite):
        estado = s.get(f"{URL}/api/trabajos/{tid}").json()["estado"]
        if estado in ("completado", "fallido"):
            return estado
        time.sleep(1)
    return "timeout"


print(f"== Pruebas contra {URL} ==\n")
prueba("La aplicación responde (/health)", requests.get(f"{URL}/health").status_code == 200)

# --- Autenticación
_, c = sesion("agricultor1", "clave-incorrecta")
prueba("Login con contraseña incorrecta es rechazado", c == 401, f"HTTP {c}")
a1, c = sesion("agricultor1", CLAVE_DEMO)
prueba("Login agricultor1 (rol usuario)", c == 302, f"HTTP {c}")
a2, _ = sesion("agricultor2", CLAVE_DEMO)
op, _ = sesion("tecnico1", CLAVE_DEMO)
ad, c = sesion(ADMIN, CLAVE_ADMIN)
prueba("Login administrador", c == 302, f"HTTP {c}")
prueba("Sin sesión no se accede al panel", requests.get(f"{URL}/", allow_redirects=False).status_code == 302)

# --- Autorización por rol (en el servidor)
c = a1.get(f"{URL}/admin/usuarios").status_code
prueba("Usuario NO puede gestionar usuarios", c == 403, f"HTTP {c}")
c = a1.get(f"{URL}/operacion").status_code
prueba("Usuario NO puede ver el panel de operación", c == 403, f"HTTP {c}")
c = op.get(f"{URL}/operacion").status_code
prueba("Operador SÍ puede ver el panel de operación", c == 200, f"HTTP {c}")
c = op.get(f"{URL}/admin/auditoria").status_code
prueba("Operador NO puede ver la auditoría", c == 403, f"HTTP {c}")
c = ad.get(f"{URL}/admin/usuarios").status_code
prueba("Administrador SÍ puede gestionar usuarios", c == 200, f"HTTP {c}")

# --- Política de archivos
prueba("Rechaza extensión .exe", subir(a1, "07_invalido_programa.exe") is None)
prueba("Rechaza binario disfrazado de .txt", subir(a1, "08_invalido_binario.txt") is None)
if os.path.exists(os.path.join(DATOS, "archivo_grande.txt")):
    prueba("Rechaza archivo de más de 2 MB", subir(a1, "archivo_grande.txt") is None)

# --- Procesamiento asíncrono
tid = subir(a1, "01_suelos_lote_A.csv")
prueba("Acepta CSV válido y crea trabajo", tid is not None, f"trabajo #{tid}")
estado_inicial = a1.get(f"{URL}/api/trabajos/{tid}").json()["estado"]
prueba("El trabajo queda en cola (no se procesa en la petición)", estado_inicial in ("pendiente", "en_ejecucion"), estado_inicial)
prueba("El worker lo completa", esperar(a1, tid) == "completado")
r = a1.get(f"{URL}/trabajos/{tid}/descargar")
prueba("El dueño descarga su resultado", r.status_code == 200 and "clasificacion_ph" in r.text)
tid_malo = subir(a1, "06_invalido_columnas.csv")
prueba("CSV mal formado termina en estado 'fallido'", esperar(a1, tid_malo) == "fallido")

# --- Aislamiento entre usuarios
c = a2.get(f"{URL}/api/trabajos/{tid}").status_code
prueba("agricultor2 NO ve el trabajo de agricultor1", c == 404, f"HTTP {c}")
c = a2.get(f"{URL}/trabajos/{tid}/descargar").status_code
prueba("agricultor2 NO descarga el resultado de agricultor1", c == 404, f"HTTP {c}")
c = a2.post(f"{URL}/trabajos/{tid}/eliminar").status_code
prueba("agricultor2 NO elimina el trabajo de agricultor1", c == 404, f"HTTP {c}")
c = op.get(f"{URL}/trabajos/{tid}/descargar").status_code
prueba("Operador NO descarga resultados ajenos (privacidad)", c == 404, f"HTTP {c}")

# --- Reglas de negocio
c = a1.post(f"{URL}/trabajos/{tid}/eliminar").status_code
prueba("Agricultor NO puede eliminar un resultado completado", c == 403, f"HTTP {c}")
ids = [subir(a2, "04_informe_visita_campo.txt") for _ in range(4)]
prueba("Cuota: el 4.º trabajo activo de un agricultor es rechazado",
       all(ids[:3]) and ids[3] is None, f"ids={ids}")
for t in ids[:3]:
    esperar(a2, t)

# --- Auditoría
texto = ad.get(f"{URL}/admin/auditoria").text
prueba("La auditoría registra accesos denegados", "acceso_denegado" in texto)
prueba("La auditoría registra la regla de cuota", "cuota_excedida" in texto)
csv_r = ad.get(f"{URL}/admin/auditoria.csv?usuario=agricultor2")
prueba("Exporta reporte CSV de auditoría por usuario", csv_r.status_code == 200 and "agricultor2" in csv_r.text)

print(f"\nResultado: {sum(resultados)} de {len(resultados)} pruebas pasaron")
sys.exit(0 if all(resultados) else 1)
