"""
Capturas de pantalla para el anexo de evidencias (reproducibles).
Recorre la plataforma con un navegador sin interfaz (Playwright + Chromium) con las cuentas demo
y guarda una imagen por punto del checklist en evidencias/ui_nube/.

Uso (desde un equipo con acceso a la plataforma, por ejemplo AWS CloudShell):
    pip install playwright requests && python -m playwright install chromium
    export CLAVE_ADMIN='...' CLAVE_DEMO='...'          # las del .env del servidor
    python3 pruebas/capturas.py http://IP_PUBLICA
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

URL = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost").rstrip("/")
ADMIN = os.environ.get("ADMIN_USER", "coordinador")
CLAVES = {ADMIN: os.environ["CLAVE_ADMIN"], "tecnico1": os.environ["CLAVE_DEMO"],
          "agricultor1": os.environ["CLAVE_DEMO"], "agricultor2": os.environ["CLAVE_DEMO"]}
RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATOS = os.path.join(RAIZ, "datos_prueba")
SALIDA = os.path.join(RAIZ, "evidencias", "ui_nube")
os.makedirs(SALIDA, exist_ok=True)


def foto(pagina, nombre):
    ruta = os.path.join(SALIDA, f"{nombre}.png")
    pagina.screenshot(path=ruta, full_page=True)
    print(f"  {nombre}.png  <- {pagina.url}")


def sesion(navegador, usuario):
    """Abre un contexto nuevo (cookies separadas) e inicia sesión con el formulario real."""
    ctx = navegador.new_context(viewport={"width": 1280, "height": 800}, locale="es-CO")
    p = ctx.new_page()
    p.goto(f"{URL}/login")
    p.fill("#usuario", usuario)
    p.fill("#clave", CLAVES[usuario])
    p.click("button[type=submit], form button")
    p.wait_for_load_state("networkidle")
    return p


def subir(p, archivo):
    p.goto(f"{URL}/")
    p.set_input_files("#archivo", os.path.join(DATOS, archivo))
    p.click("form[action$='/subir'] button[type=submit], form[action$='/subir'] button")
    p.wait_for_load_state("networkidle")
    return p.url.rstrip("/").split("/")[-1] if "/trabajos/" in p.url else None


def esperar_estado(p, tid, estados=("Completado", "Fallido"), limite=60):
    for _ in range(limite):
        p.goto(f"{URL}/trabajos/{tid}")
        if any(e in p.content() for e in estados):
            return
        time.sleep(1)


with sync_playwright() as pw:
    nav = pw.chromium.launch(executable_path=os.environ.get("CHROME_PATH") or None)
    print(f"Capturas de {URL} en {SALIDA}")

    # 1. Despliegue + entorno (pie de página)
    ctx = nav.new_context(viewport={"width": 1280, "height": 800})
    p = ctx.new_page()
    p.goto(f"{URL}/login")
    foto(p, "01_login_entorno_nube")

    # 2. Agricultor: procesamiento, ciclo del trabajo
    a1 = sesion(nav, "agricultor1")
    tid = subir(a1, "01_suelos_lote_A.csv")
    foto(a1, "02_trabajo_recien_subido")
    esperar_estado(a1, tid)
    foto(a1, "03_trabajo_completado")
    malo = subir(a1, "06_invalido_columnas.csv")
    esperar_estado(a1, malo)
    foto(a1, "04_trabajo_fallido_con_causa")
    subir(a1, "07_invalido_programa.exe")
    foto(a1, "05_archivo_rechazado_politica")
    a1.goto(f"{URL}/")
    foto(a1, "06_panel_agricultor")

    # 3. Autorización: operación denegada para el rol usuario
    a1.goto(f"{URL}/admin/usuarios")
    foto(a1, "07_usuario_denegado_403")

    # 4. Aislamiento: agricultor2 intenta abrir el trabajo de agricultor1
    a2 = sesion(nav, "agricultor2")
    a2.goto(f"{URL}/trabajos/{tid}")
    foto(a2, "08_aislamiento_trabajo_ajeno_404")

    # 5. Regla de negocio: cuota de 3 trabajos activos
    # Se envían archivos seguidos hasta que la regla rechace uno (con 3 en cola el 4.º se rechaza)
    for _ in range(8):
        if subir(a2, "05_bitacora_laboratorio.txt") is None:
            break
    foto(a2, "09_regla_cuota_rechazada")

    # 6. Técnico: operación y recursos
    op = sesion(nav, "tecnico1")
    op.goto(f"{URL}/operacion")
    foto(op, "10_tecnico_operacion")
    op.goto(f"{URL}/recursos")
    time.sleep(3)
    foto(op, "11_tecnico_recursos")

    # 7. Coordinador: usuarios, auditoría, sello y reglas
    ad = sesion(nav, ADMIN)
    ad.goto(f"{URL}/admin/usuarios")
    foto(ad, "12_coordinador_usuarios")
    ad.goto(f"{URL}/admin/auditoria")
    foto(ad, "13_coordinador_auditoria")
    ad.goto(f"{URL}/admin/auditoria/verificar")
    foto(ad, "14_coordinador_cadena_verificada")
    ad.goto(f"{URL}/admin/reglas")
    foto(ad, "15_coordinador_reglas")

    nav.close()
print("Listo.")
