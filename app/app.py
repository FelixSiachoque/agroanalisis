"""
AgroAnálisis Sugamuxi - Aplicación web / API
Recibe archivos, crea trabajos en la cola (tabla 'trabajos') y entrega resultados.
El procesamiento lo hace el contenedor 'worker', no esta app.
"""
import csv
import functools
import io
import logging
import os
import uuid
from datetime import timedelta

import click
from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, send_file, session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from db import auditar, consulta
from permisos import ROLES, puede

logging.basicConfig(level=logging.INFO, format="%(asctime)s app %(levelname)s %(message)s")
log = logging.getLogger("app")
os.umask(0o077)   # archivos y carpetas nuevos: solo el dueño puede leerlos

# ---------------------------------------------------------------- configuración
DATA_DIR = os.environ.get("DATA_DIR", "/data")
MAX_MB = float(os.environ.get("MAX_MB", "2"))
MAX_BYTES = int(MAX_MB * 1024 * 1024)
EXTENSIONES_PERMITIDAS = {"txt", "csv"}
MAX_ACTIVOS_USUARIO = int(os.environ.get("MAX_ACTIVOS_USUARIO", "3"))   # regla de negocio

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)   # IP real detrás de nginx
app.config.update(
    SECRET_KEY=os.environ["SECRET_KEY"],          # viene de .env, nunca del código
    MAX_CONTENT_LENGTH=MAX_BYTES + 64 * 1024,     # tope duro de la petición
    SESSION_COOKIE_HTTPONLY=True,                 # JavaScript no puede leer la cookie
    SESSION_COOKIE_SAMESITE="Lax",                # protege contra CSRF desde otros sitios
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
)


def ip():
    return request.remote_addr


# ---------------------------------------------------------------- sesión y permisos
@app.before_request
def cargar_usuario():
    """Carga el usuario desde la BD en cada petición (si lo desactivan o le cambian el rol, aplica de inmediato)."""
    g.usuario = None
    uid = session.get("uid")
    if uid:
        u = consulta("SELECT id, usuario, rol, activo FROM usuarios WHERE id = %s", (uid,), uno=True)
        if u and u["activo"]:
            g.usuario = u
        else:
            session.clear()


@app.context_processor
def plantillas():
    return {"puede": lambda p: g.usuario is not None and puede(g.usuario["rol"], p)}


def requiere(permiso):
    """Decorador: exige sesión iniciada y que el rol tenga el permiso. Se valida EN EL SERVIDOR."""
    def decorador(vista):
        @functools.wraps(vista)
        def envoltura(*args, **kwargs):
            if g.usuario is None:
                return redirect(url_for("login"))
            if not puede(g.usuario["rol"], permiso):
                auditar(g.usuario["usuario"], "acceso_denegado", f"permiso={permiso} ruta={request.path}", ip())
                abort(403)
            return vista(*args, **kwargs)
        return envoltura
    return decorador


def obtener_trabajo_autorizado(trabajo_id, permiso_global):
    """
    AISLAMIENTO ENTRE USUARIOS.
    Devuelve el trabajo solo si es del usuario actual o si su rol tiene 'permiso_global'.
    Si no, responde 404 (no revelamos que el trabajo existe) y lo audita.
    """
    t = consulta("SELECT t.*, u.usuario AS dueno FROM trabajos t JOIN usuarios u ON u.id = t.usuario_id "
                 "WHERE t.id = %s", (trabajo_id,), uno=True)
    es_dueno = t is not None and t["usuario_id"] == g.usuario["id"]
    if t is None or not (es_dueno or puede(g.usuario["rol"], permiso_global)):
        auditar(g.usuario["usuario"], "acceso_denegado", f"trabajo={trabajo_id} ruta={request.path}", ip())
        abort(404)
    return t


# ---------------------------------------------------------------- autenticación
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        nombre = request.form.get("usuario", "").strip()
        clave = request.form.get("clave", "")
        u = consulta("SELECT * FROM usuarios WHERE usuario = %s", (nombre,), uno=True)
        if u and u["activo"] and check_password_hash(u["clave_hash"], clave):
            session.clear()
            session.permanent = True
            session["uid"] = u["id"]
            auditar(u["usuario"], "login_ok", f"rol={u['rol']}", ip())
            return redirect(url_for("panel"))
        auditar(nombre or "(vacío)", "login_fallido", "", ip())
        flash("Usuario o contraseña incorrectos.", "error")     # mensaje genérico a propósito
        return render_template("login.html"), 401
    return render_template("login.html")


@app.post("/logout")
def logout():
    if g.usuario:
        auditar(g.usuario["usuario"], "logout", "", ip())
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------- panel del usuario
def trabajos_activos(usuario_id):
    r = consulta("SELECT count(*) AS n FROM trabajos WHERE usuario_id = %s "
                 "AND estado IN ('pendiente', 'en_ejecucion')", (usuario_id,), uno=True)
    return r["n"]


@app.get("/")
@requiere("ver_propios")
def panel():
    trabajos = consulta("SELECT * FROM trabajos WHERE usuario_id = %s ORDER BY id DESC", (g.usuario["id"],))
    return render_template("panel.html", trabajos=trabajos, activos=trabajos_activos(g.usuario["id"]),
                           max_activos=MAX_ACTIVOS_USUARIO, max_mb=MAX_MB)


def validar_archivo(archivo):
    """Política de archivos: solo .txt o .csv, máximo MAX_MB, texto UTF-8 sin bytes binarios. Devuelve (ext, datos) o lanza ValueError."""
    if not archivo or not archivo.filename:
        raise ValueError("Debe seleccionar un archivo.")
    ext = archivo.filename.rsplit(".", 1)[-1].lower() if "." in archivo.filename else ""
    if ext not in EXTENSIONES_PERMITIDAS:
        raise ValueError(f"Tipo no permitido (.{ext}). Solo se aceptan: .txt y .csv")
    datos = archivo.read(MAX_BYTES + 1)
    if len(datos) == 0:
        raise ValueError("El archivo está vacío.")
    if len(datos) > MAX_BYTES:
        raise ValueError(f"El archivo supera el máximo de {MAX_MB:g} MB.")
    if b"\x00" in datos:
        raise ValueError("El archivo parece binario; solo se acepta texto.")
    try:
        datos.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("El archivo debe estar codificado en UTF-8.")
    return ext, datos


@app.post("/subir")
@requiere("subir")
def subir():
    u = g.usuario
    archivo = request.files.get("archivo")
    try:
        ext, datos = validar_archivo(archivo)
    except ValueError as e:
        auditar(u["usuario"], "archivo_rechazado", f"{archivo.filename if archivo else ''}: {e}", ip())
        flash(str(e), "error")
        return redirect(url_for("panel"))

    # REGLA DE NEGOCIO PROPIA: un agricultor (rol usuario) puede tener máximo N trabajos activos.
    if u["rol"] == "usuario" and trabajos_activos(u["id"]) >= MAX_ACTIVOS_USUARIO:
        auditar(u["usuario"], "cuota_excedida", f"max={MAX_ACTIVOS_USUARIO}", ip())
        flash(f"Regla del laboratorio: máximo {MAX_ACTIVOS_USUARIO} trabajos en cola por agricultor. "
              "Espere a que terminen los actuales.", "error")
        return redirect(url_for("panel"))

    # Cada usuario tiene su propia carpeta: /data/uploads/<id_usuario>/
    carpeta = os.path.join(DATA_DIR, "uploads", str(u["id"]))
    os.makedirs(carpeta, mode=0o700, exist_ok=True)
    ruta = os.path.join(carpeta, f"{uuid.uuid4().hex}.{ext}")   # nombre aleatorio: evita rutas maliciosas
    with open(ruta, "wb") as f:
        f.write(datos)
    os.chmod(ruta, 0o600)

    t = consulta("INSERT INTO trabajos (usuario_id, nombre_original, ruta_archivo, tipo, tamano_bytes) "
                 "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                 (u["id"], archivo.filename[:200], ruta, ext, len(datos)), uno=True)
    auditar(u["usuario"], "subir", f"trabajo={t['id']} archivo={archivo.filename} bytes={len(datos)}", ip())
    flash(f"Archivo recibido. Trabajo #{t['id']} en cola.", "ok")
    return redirect(url_for("detalle", trabajo_id=t["id"]), code=303)


@app.get("/trabajos/<int:trabajo_id>")
@requiere("ver_propios")
def detalle(trabajo_id):
    t = obtener_trabajo_autorizado(trabajo_id, "ver_todos")
    return render_template("detalle.html", t=t)


@app.get("/trabajos/<int:trabajo_id>/descargar")
@requiere("ver_propios")
def descargar(trabajo_id):
    t = obtener_trabajo_autorizado(trabajo_id, "descargar_todos")
    if t["estado"] != "completado" or not t["ruta_resultado"]:
        abort(409)
    auditar(g.usuario["usuario"], "descargar", f"trabajo={trabajo_id} dueno={t['dueno']}", ip())
    return send_file(t["ruta_resultado"], as_attachment=True, download_name=f"resultado_{trabajo_id}.json")


@app.post("/trabajos/<int:trabajo_id>/eliminar")
@requiere("ver_propios")
def eliminar(trabajo_id):
    t = obtener_trabajo_autorizado(trabajo_id, "eliminar_cualquiera")
    # Trazabilidad del laboratorio: un resultado completado solo lo puede eliminar quien tenga 'eliminar_cualquiera'.
    if t["estado"] in ("completado", "en_ejecucion") and not puede(g.usuario["rol"], "eliminar_cualquiera"):
        auditar(g.usuario["usuario"], "acceso_denegado", f"eliminar trabajo={trabajo_id} estado={t['estado']}", ip())
        flash("No puede eliminar un trabajo completado o en ejecución.", "error")
        return render_template("detalle.html", t=t), 403
    for ruta in (t["ruta_archivo"], t["ruta_resultado"]):
        if ruta and os.path.exists(ruta):
            os.remove(ruta)
    consulta("DELETE FROM trabajos WHERE id = %s", (trabajo_id,))
    auditar(g.usuario["usuario"], "eliminar", f"trabajo={trabajo_id} dueno={t['dueno']}", ip())
    flash(f"Trabajo #{trabajo_id} eliminado.", "ok")
    return redirect(url_for("panel"))


# ---------------------------------------------------------------- operación (operador y admin)
@app.get("/operacion")
@requiere("ver_todos")
def operacion():
    estado = request.args.get("estado", "")
    sql = "SELECT t.*, u.usuario AS dueno FROM trabajos t JOIN usuarios u ON u.id = t.usuario_id"
    params = ()
    if estado:
        sql += " WHERE t.estado = %s"
        params = (estado,)
    trabajos = consulta(sql + " ORDER BY t.id DESC LIMIT 300", params)
    resumen = consulta("SELECT estado, count(*) AS n FROM trabajos GROUP BY estado")
    return render_template("operacion.html", trabajos=trabajos, resumen=resumen, estado=estado)


@app.post("/trabajos/<int:trabajo_id>/reprocesar")
@requiere("reprocesar")
def reprocesar(trabajo_id):
    r = consulta("UPDATE trabajos SET estado = 'pendiente', error = NULL WHERE id = %s AND estado = 'fallido' "
                 "RETURNING id", (trabajo_id,), uno=True)
    if r:
        auditar(g.usuario["usuario"], "reprocesar", f"trabajo={trabajo_id}", ip())
        flash(f"Trabajo #{trabajo_id} enviado de nuevo a la cola.", "ok")
    else:
        flash("Solo se pueden reprocesar trabajos fallidos.", "error")
    return redirect(url_for("operacion"))


# ---------------------------------------------------------------- administración
@app.route("/admin/usuarios", methods=["GET", "POST"])
@requiere("gestionar_usuarios")
def usuarios():
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "crear":
            nombre = request.form.get("usuario", "").strip()
            clave = request.form.get("clave", "")
            rol = request.form.get("rol", "")
            if not nombre.isalnum() or len(nombre) > 50:
                flash("El usuario debe ser alfanumérico (máx. 50).", "error")
            elif len(clave) < 8:
                flash("La contraseña debe tener al menos 8 caracteres.", "error")
            elif rol not in ROLES:
                flash("Rol inválido.", "error")
            elif consulta("SELECT 1 FROM usuarios WHERE usuario = %s", (nombre,), uno=True):
                flash("Ese usuario ya existe.", "error")
            else:
                consulta("INSERT INTO usuarios (usuario, clave_hash, rol) VALUES (%s, %s, %s)",
                         (nombre, generate_password_hash(clave), rol))
                auditar(g.usuario["usuario"], "crear_usuario", f"nuevo={nombre} rol={rol}", ip())
                flash(f"Usuario {nombre} creado con rol {rol}.", "ok")
        elif accion in ("cambiar_rol", "activar", "desactivar"):
            uid = int(request.form.get("id", "0"))
            if uid == g.usuario["id"]:
                flash("No puede modificar su propia cuenta desde aquí.", "error")
            elif accion == "cambiar_rol" and request.form.get("rol") in ROLES:
                consulta("UPDATE usuarios SET rol = %s WHERE id = %s", (request.form["rol"], uid))
                auditar(g.usuario["usuario"], "cambiar_rol", f"id={uid} rol={request.form['rol']}", ip())
            elif accion in ("activar", "desactivar"):
                consulta("UPDATE usuarios SET activo = %s WHERE id = %s", (accion == "activar", uid))
                auditar(g.usuario["usuario"], accion, f"id={uid}", ip())
        return redirect(url_for("usuarios"))
    lista = consulta("SELECT id, usuario, rol, activo, creado FROM usuarios ORDER BY id")
    return render_template("usuarios.html", lista=lista, roles=ROLES)


def eventos_auditoria(limite=None):
    filtro_u = request.args.get("usuario", "").strip()
    filtro_a = request.args.get("accion", "").strip()
    sql, params = "SELECT * FROM auditoria WHERE 1=1", []
    if filtro_u:
        sql += " AND usuario = %s"
        params.append(filtro_u)
    if filtro_a:
        sql += " AND accion = %s"
        params.append(filtro_a)
    sql += " ORDER BY id DESC"
    if limite:
        sql += f" LIMIT {int(limite)}"
    return consulta(sql, tuple(params)), filtro_u, filtro_a


@app.get("/admin/auditoria")
@requiere("ver_auditoria")
def auditoria():
    eventos, fu, fa = eventos_auditoria(limite=300)
    acciones = consulta("SELECT accion, count(*) AS n FROM auditoria GROUP BY accion ORDER BY n DESC")
    return render_template("auditoria.html", eventos=eventos, fu=fu, fa=fa, acciones=acciones)


@app.get("/admin/auditoria.csv")
@requiere("ver_auditoria")
def auditoria_csv():
    """Reporte de trazabilidad (sello de autenticidad): exporta quién hizo qué y cuándo."""
    eventos, fu, fa = eventos_auditoria()
    salida = io.StringIO()
    w = csv.writer(salida)
    w.writerow(["id", "fecha", "usuario", "accion", "detalle", "ip"])
    for e in eventos:
        w.writerow([e["id"], e["fecha"].isoformat(), e["usuario"], e["accion"], e["detalle"], e["ip"]])
    auditar(g.usuario["usuario"], "exportar_auditoria", f"filtro_usuario={fu} filtro_accion={fa}", ip())
    return Response(salida.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=reporte_auditoria.csv"})


# ---------------------------------------------------------------- API JSON (pruebas y estado)
def trabajo_json(t):
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v)
            for k, v in t.items() if k not in ("ruta_archivo", "ruta_resultado")}


@app.get("/api/trabajos")
@requiere("ver_propios")
def api_trabajos():
    filas = consulta("SELECT * FROM trabajos WHERE usuario_id = %s ORDER BY id DESC", (g.usuario["id"],))
    return jsonify([trabajo_json(t) for t in filas])


@app.get("/api/trabajos/<int:trabajo_id>")
@requiere("ver_propios")
def api_trabajo(trabajo_id):
    return jsonify(trabajo_json(obtener_trabajo_autorizado(trabajo_id, "ver_todos")))


@app.get("/health")
def health():
    consulta("SELECT 1", uno=True)
    return {"estado": "ok"}


# ---------------------------------------------------------------- errores
@app.errorhandler(403)
def e403(e):
    return render_template("error.html", codigo=403, mensaje="No tiene permiso para esta operación."), 403


@app.errorhandler(404)
def e404(e):
    return render_template("error.html", codigo=404, mensaje="No encontrado."), 404


@app.errorhandler(409)
def e409(e):
    return render_template("error.html", codigo=409, mensaje="El resultado aún no está disponible."), 409


@app.errorhandler(413)
def e413(e):
    flash(f"El archivo supera el máximo de {MAX_MB:g} MB.", "error")
    return redirect(url_for("panel"))


# ---------------------------------------------------------------- comandos de administración (CLI)
@app.cli.command("crear-usuario")
@click.argument("usuario")
@click.argument("rol", type=click.Choice(ROLES))
@click.password_option("--clave", prompt="Contraseña")
def crear_usuario_cli(usuario, rol, clave):
    """Crea un usuario. Uso: flask --app app crear-usuario pepe usuario"""
    consulta("INSERT INTO usuarios (usuario, clave_hash, rol) VALUES (%s, %s, %s)",
             (usuario, generate_password_hash(clave), rol))
    auditar("cli", "crear_usuario", f"nuevo={usuario} rol={rol}")
    click.echo(f"Usuario {usuario} creado con rol {rol}")


@app.cli.command("crear-demo")
def crear_demo_cli():
    """Crea las cuentas de demostración con la clave DEMO_PASSWORD del .env."""
    clave = os.environ["DEMO_PASSWORD"]
    for nombre, rol in [("tecnico1", "operador"), ("agricultor1", "usuario"), ("agricultor2", "usuario")]:
        if not consulta("SELECT 1 FROM usuarios WHERE usuario = %s", (nombre,), uno=True):
            consulta("INSERT INTO usuarios (usuario, clave_hash, rol) VALUES (%s, %s, %s)",
                     (nombre, generate_password_hash(clave), rol))
            auditar("cli", "crear_usuario", f"nuevo={nombre} rol={rol}")
            click.echo(f"Creado {nombre} ({rol})")


def crear_admin_inicial():
    """Si no existe ningún admin, lo crea con ADMIN_USER / ADMIN_PASSWORD del .env."""
    try:
        if not consulta("SELECT 1 FROM usuarios WHERE rol = 'admin'", uno=True):
            nombre = os.environ.get("ADMIN_USER", "coordinador")
            consulta("INSERT INTO usuarios (usuario, clave_hash, rol) VALUES (%s, %s, 'admin')",
                     (nombre, generate_password_hash(os.environ["ADMIN_PASSWORD"])))
            auditar("sistema", "crear_usuario", f"admin inicial={nombre}")
    except Exception as e:  # varios procesos de gunicorn pueden intentarlo a la vez
        log.warning("admin inicial: %s", e)


crear_admin_inicial()
