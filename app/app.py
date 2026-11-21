"""
AgroAnálisis Sugamuxi - Aplicación web / API
Recibe archivos, crea trabajos en la cola (tabla 'trabajos') y entrega resultados.
El procesamiento lo hace el contenedor 'worker', no esta app.

Mapa de archivos (dónde tocar en cada reto):
  permisos.py        -> MATRIZ DE PERMISOS por rol (retos 1 y 2)
  seguridad.py       -> requiere() y obtener_trabajo_autorizado() = AISLAMIENTO (reto 3)
  auditoria.py       -> auditar(): registrar un evento nuevo (reto 6)
  reglas_negocio.py  -> REGLAS DE NEGOCIO del laboratorio (activar / crear reglas)
  validacion.py      -> política técnica de archivos (tipo, tamaño, UTF-8)
  rutas.py           -> rutas de agricultores, técnicos y API
  rutas_admin.py     -> rutas del coordinador (usuarios, auditoría, reglas, recursos)
  app.py (este)      -> arranque, manejo de errores y comandos de consola
"""
import hashlib
import logging
import os
from datetime import timedelta, timezone

import click
import psycopg
from flask import Flask, g, jsonify, render_template, request
from markupsafe import Markup
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash

import config
from auditoria import auditar, texto_verificacion, verificar_cadena
from db import consulta
from permisos import ROLES, puede
from seguridad import cargar_usuario, token_csrf, verificar_csrf

logging.basicConfig(level=logging.INFO, format="%(asctime)s app %(levelname)s %(message)s")
log = logging.getLogger("app")
os.umask(0o077)   # archivos y carpetas nuevos: solo el dueño puede leerlos

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)   # IP real detrás de nginx
app.config.update(
    SECRET_KEY=config.SECRET_KEY,
    MAX_CONTENT_LENGTH=config.MAX_BYTES + 64 * 1024,  # tope duro de la petición
    SESSION_COOKIE_HTTPONLY=True,                     # JavaScript no puede leer la cookie
    SESSION_COOKIE_SAMESITE="Lax",                    # primera barrera contra CSRF
    SESSION_COOKIE_SECURE=config.COOKIE_SECURE,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
)

# Antes de cada petición: 1) quién es el usuario (desde la BD)  2) token anti-CSRF en los POST
app.before_request(cargar_usuario)
app.before_request(verificar_csrf)


def _version_estaticos():
    """Huella de estilo.css y estado.js: cambia en cada despliegue y obliga al navegador a no usar la copia vieja."""
    h = hashlib.sha256()
    for nombre in ("estilo.css", "estado.js"):
        with open(os.path.join(app.static_folder, nombre), "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:10]


VERSION_ESTATICOS = _version_estaticos()


@app.context_processor
def plantillas():
    return {
        "v": VERSION_ESTATICOS,
        "puede": lambda p: g.usuario is not None and puede(g.usuario["rol"], p),
        "csrf_campo": lambda: Markup(f'<input type="hidden" name="csrf" value="{token_csrf()}">'),
    }


ESTADOS_TEXTO = {"pendiente": "Pendiente", "en_ejecucion": "En ejecución", "completado": "Completado",
                 "fallido": "Fallido"}


@app.template_filter("estado_texto")
def estado_texto(estado):
    """'en_ejecucion' -> 'En ejecución' (en pantalla nunca se muestran los nombres internos)."""
    return ESTADOS_TEXTO.get(estado, estado)


ROLES_TEXTO = {"admin": "Coordinador", "operador": "Técnico", "usuario": "Agricultor"}


@app.template_filter("rol_texto")
def rol_texto(rol):
    """Nombre del rol en el lenguaje del laboratorio: 'operador' -> 'Técnico'."""
    return ROLES_TEXTO.get(rol, rol)


HORA_COLOMBIA = timezone(timedelta(hours=-5))   # la BD guarda en UTC; en pantalla se muestra hora de Colombia


@app.template_filter("fecha")
def fecha(valor, formato="%Y-%m-%d %H:%M:%S"):
    if not valor:
        return "—"
    if valor.tzinfo is not None:
        valor = valor.astimezone(HORA_COLOMBIA)
    return valor.strftime(formato)


@app.template_filter("tamano")
def tamano(b):
    """Bytes legibles: 50 B, 1.2 KB, 1.5 MB."""
    if b < 1024:
        return f"{b} B"
    return f"{b / 1024:.1f} KB" if b < 1024 * 1024 else f"{b / 1048576:.1f} MB"


@app.template_filter("duracion")
def duracion(t):
    """Segundos entre iniciado y terminado de un trabajo, en texto."""
    if not (t.get("iniciado") and t.get("terminado")):
        return "—"
    s = (t["terminado"] - t["iniciado"]).total_seconds()
    return f"{s:.1f} s" if s < 120 else f"{s / 60:.1f} min"


# Registrar las rutas (se importan después de crear 'app' porque la usan en sus decoradores)
import rutas         # noqa: E402,F401
import rutas_admin   # noqa: E402,F401


# ---------------------------------------------------------------- manejo de errores
MENSAJES = {
    400: "La solicitud no es válida.",
    403: "No tiene permiso para esta operación.",
    404: "No encontrado.",
    405: "Método no permitido.",
    409: "La operación no es posible en el estado actual del trabajo.",
    410: "El archivo ya no está disponible.",
    413: f"El archivo supera el máximo de {config.MAX_MB:g} MB.",
    422: "Los datos enviados no cumplen las reglas.",
    429: "Demasiados intentos seguidos. Espere un minuto e intente de nuevo.",
    500: "Error interno. Quedó registrado en los logs para revisarlo.",
    503: "La base de datos no responde en este momento. Intente de nuevo en unos segundos.",
}


def responder_error(codigo, mensaje):
    """Respuesta de error clara: JSON para la API, página HTML para el navegador. Nunca trazas."""
    if request.path.startswith("/api/") or request.path == "/health":
        return jsonify(error=mensaje, codigo=codigo), codigo
    return render_template("error.html", codigo=codigo, mensaje=mensaje), codigo


@app.errorhandler(HTTPException)
def error_http(e):
    if e.code is None or e.code < 400:          # redirecciones internas de Flask
        return e
    propio = e.description if e.description != type(e).description else None
    mensaje = propio or MENSAJES.get(e.code, e.name)
    if e.code == 413 and g.get("usuario") and request.path == "/subir":
        return rutas.mostrar_panel(error=mensaje, codigo=413)
    return responder_error(e.code, mensaje)


@app.errorhandler(psycopg.OperationalError)
def error_bd(e):
    log.error("Base de datos no disponible: %s", e)
    return responder_error(503, MENSAJES[503])


@app.errorhandler(Exception)
def error_interno(e):
    log.exception("Error no controlado en %s %s", request.method, request.path)
    try:
        auditar("error_interno", f"{type(e).__name__} en {request.path}", resultado="error")
    except Exception:
        pass
    return responder_error(500, MENSAJES[500])


# ---------------------------------------------------------------- comandos de administración (CLI)
@app.cli.command("crear-usuario")
@click.argument("usuario")
@click.argument("rol", type=click.Choice(ROLES))
@click.password_option("--clave", prompt="Contraseña")
def crear_usuario_cli(usuario, rol, clave):
    """Crea un usuario. Uso: flask --app app crear-usuario pepe usuario"""
    consulta("INSERT INTO usuarios (usuario, clave_hash, rol) VALUES (%s, %s, %s)",
             (usuario, generate_password_hash(clave), rol))
    auditar("crear_usuario", f"nuevo={usuario} rol={rol}", recurso=f"usuario:{usuario}",
            usuario="cli", origen="cli")
    click.echo(f"Usuario {usuario} creado con rol {rol}")


@app.cli.command("verificar-cadena")
def verificar_cadena_cli():
    """Sello de autenticidad: verifica la cadena de hashes de la auditoría. Uso: flask --app app verificar-cadena"""
    r = verificar_cadena()
    auditar("verificar_cadena", texto_verificacion(r), recurso="auditoria", usuario="cli", origen="cli",
            resultado="permitido" if r["integra"] else "error")
    click.echo(texto_verificacion(r))
    raise SystemExit(0 if r["integra"] else 1)


@app.cli.command("crear-demo")
def crear_demo_cli():
    """Crea las cuentas de demostración con la clave DEMO_PASSWORD del .env."""
    clave = os.environ["DEMO_PASSWORD"]
    for nombre, rol in [("tecnico1", "operador"), ("agricultor1", "usuario"), ("agricultor2", "usuario")]:
        if not consulta("SELECT 1 FROM usuarios WHERE usuario = %s", (nombre,), uno=True):
            consulta("INSERT INTO usuarios (usuario, clave_hash, rol) VALUES (%s, %s, %s)",
                     (nombre, generate_password_hash(clave), rol))
            auditar("crear_usuario", f"nuevo={nombre} rol={rol}", recurso=f"usuario:{nombre}",
                    usuario="cli", origen="cli")
            click.echo(f"Creado {nombre} ({rol})")


def crear_admin_inicial():
    """Si no existe ningún admin, lo crea con ADMIN_USER / ADMIN_PASSWORD del .env."""
    try:
        if not consulta("SELECT 1 FROM usuarios WHERE rol = 'admin'", uno=True):
            nombre = os.environ.get("ADMIN_USER", "coordinador")
            consulta("INSERT INTO usuarios (usuario, clave_hash, rol) VALUES (%s, %s, 'admin')",
                     (nombre, generate_password_hash(os.environ["ADMIN_PASSWORD"])))
            auditar("crear_usuario", f"admin inicial={nombre}", recurso=f"usuario:{nombre}",
                    usuario="sistema", origen="sistema")
    except psycopg.errors.UniqueViolation:
        pass   # otro proceso de Gunicorn lo creó al mismo tiempo
    except KeyError:
        log.error("Falta ADMIN_PASSWORD en el .env: no se pudo crear el admin inicial")
    except psycopg.OperationalError as e:
        log.warning("Admin inicial: base de datos no disponible todavía (%s)", e)


crear_admin_inicial()
