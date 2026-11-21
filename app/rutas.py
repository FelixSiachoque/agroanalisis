"""
Rutas de agricultores (usuario) y técnicos (operador), y la API JSON.
Cada ruta: 1) @requiere(permiso)  2) obtener_trabajo_autorizado() si recibe un trabajo_id
           3) reglas_negocio.evaluar_*()  4) auditar()
"""
import hashlib
import os
import uuid

from flask import abort, flash, g, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import config
import recursos
import reglas_negocio
from app import app
from auditoria import auditar
from db import consulta, transaccion
from seguridad import contexto, obtener_trabajo_autorizado, requiere, ruta_segura
from validacion import ArchivoInvalido, sanear_nombre, validar_archivo

# Hash de relleno: si el usuario no existe igual se calcula un scrypt, así el tiempo de respuesta
# no revela qué nombres de usuario existen.
HASH_FALSO = generate_password_hash("contraseña-que-nadie-tiene")


def rechazar(decision, recurso=None):
    """Una regla de negocio dijo que no: se audita y se responde con su código y su mensaje."""
    auditar(decision.evento, decision.motivo, recurso=recurso, resultado="denegado")
    abort(decision.http, decision.motivo)


# ---------------------------------------------------------------- autenticación
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        nombre = request.form.get("usuario", "").strip()[:100]
        clave = request.form.get("clave", "")
        u = consulta("SELECT * FROM usuarios WHERE usuario = %s", (nombre[:50],), uno=True)
        clave_ok = check_password_hash(u["clave_hash"] if u else HASH_FALSO, clave)
        if u and u["activo"] and clave_ok:
            session.clear()                     # sesión nueva (evita fijación de sesión)
            session.permanent = True
            session["uid"] = u["id"]
            auditar("login_ok", "", recurso=f"usuario:{u['id']}", usuario=u["usuario"], rol=u["rol"])
            return redirect(url_for("panel"))
        motivo = "cuenta inactiva" if (u and clave_ok) else ""
        auditar("login_fallido", motivo, usuario=nombre or "(vacío)", resultado="denegado")
        flash("Usuario o contraseña incorrectos.", "error")     # mensaje genérico a propósito
        return render_template("login.html"), 401
    if g.usuario:
        return redirect(url_for("panel"))
    return render_template("login.html")


@app.post("/logout")
def logout():
    if g.usuario:
        auditar("logout")
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------- panel del usuario
def contar_activos(usuario_id, cur=None):
    sql = ("SELECT count(*) AS n FROM trabajos WHERE usuario_id = %s "
           "AND estado IN ('pendiente', 'en_ejecucion')")
    if cur is None:
        return consulta(sql, (usuario_id,), uno=True)["n"]
    cur.execute(sql, (usuario_id,))
    return cur.fetchone()["n"]


def mostrar_panel(error=None, codigo=200):
    """Panel del usuario. Si 'error' viene, se muestra arriba con el código HTTP indicado."""
    trabajos = consulta("SELECT * FROM trabajos WHERE usuario_id = %s ORDER BY id DESC", (g.usuario["id"],))
    cuota = reglas_negocio.REGLAS["cuota_trabajos_activos"]
    return render_template(
        "panel.html", trabajos=trabajos, error=error,
        activos=contar_activos(g.usuario["id"]),
        cuota_aplica=cuota["activa"] and g.usuario["rol"] in cuota["roles_afectados"],
        max_activos=cuota["max"], max_mb=config.MAX_MB, max_filas=config.MAX_FILAS_CSV,
        reglas=reglas_negocio.reglas_vigentes(solo_activas=True),
        confidencial_disponible=reglas_negocio.esta_activa("trabajos_confidenciales"),
        cabecera=(reglas_negocio.REGLAS["cabecera_csv_obligatoria"]["cabecera"]
                  if reglas_negocio.esta_activa("cabecera_csv_obligatoria") else None),
    ), codigo


@app.get("/")
@requiere("ver_propios")
def panel():
    return mostrar_panel()


@app.post("/subir")
@requiere("subir")
def subir():
    u = g.usuario
    archivo = request.files.get("archivo")

    # 1. Validación técnica (tipo, tamaño, binario, UTF-8)
    try:
        a = validar_archivo(archivo)
    except ArchivoInvalido as e:
        nombre = sanear_nombre(archivo.filename if archivo else "")
        auditar("archivo_rechazado", f"{nombre}: {e}", resultado="denegado")
        return mostrar_panel(error=str(e), codigo=422)

    confidencial = (request.form.get("confidencial") == "1"
                    and reglas_negocio.esta_activa("trabajos_confidenciales"))
    carpeta = os.path.join(config.DATA_DIR, "uploads", str(u["id"]))   # carpeta propia de cada usuario
    ruta = os.path.join(carpeta, f"{uuid.uuid4().hex}.{a.extension}")  # nombre aleatorio: evita rutas maliciosas

    # 2. Reglas de negocio + guardar + encolar, en UNA transacción.
    #    El candado por usuario evita que dos subidas simultáneas se salten la cuota.
    with transaccion() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(1, %s)", (u["id"],))
        d = reglas_negocio.evaluar_subida(contexto(
            nombre=a.nombre, extension=a.extension, tamano=len(a.datos), texto=a.texto,
            n_activos=contar_activos(u["id"], cur)))
        if d.permitido:
            os.makedirs(carpeta, mode=0o700, exist_ok=True)
            try:
                with open(ruta, "wb") as f:
                    f.write(a.datos)
                os.chmod(ruta, 0o600)
                # sha256_original: huella del archivo AL RECIBIRLO (cadena de custodia, sello)
                cur.execute("INSERT INTO trabajos (usuario_id, nombre_original, ruta_archivo, tipo, tamano_bytes, "
                            "confidencial, sha256_original) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                            (u["id"], a.nombre, ruta, a.extension, len(a.datos), confidencial, a.sha256))
                tid = cur.fetchone()["id"]
            except Exception:
                if os.path.exists(ruta):        # no dejar archivos huérfanos si falla la BD
                    os.remove(ruta)
                raise

    if not d.permitido:
        auditar(d.evento, d.motivo, recurso=f"archivo:{a.nombre}", resultado="denegado")
        return mostrar_panel(error=d.motivo, codigo=d.http)

    auditar("subir", f"archivo={a.nombre} bytes={len(a.datos)} sha256={a.sha256}", recurso=f"trabajo:{tid}")
    flash(f"Archivo recibido. Trabajo #{tid} en cola.", "ok")
    return redirect(url_for("detalle", trabajo_id=tid), code=303)


# ---------------------------------------------------------------- un trabajo
def huella(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(65536), b""):
            h.update(bloque)
    return h.hexdigest()


def entregar_con_custodia(t, ruta_bd, esperado, accion, nombre_descarga):
    """Entrega un archivo solo si su SHA-256 coincide con el registrado (sello de autenticidad)."""
    ruta = ruta_segura(ruta_bd)
    if not ruta or not os.path.isfile(ruta):
        abort(410)
    if esperado and huella(ruta) != esperado:
        auditar("integridad_comprometida", f"{accion}: el SHA-256 del archivo no coincide con el registrado",
                recurso=f"trabajo:{t['id']}", resultado="error")
        abort(409, "Integridad comprometida: el archivo fue modificado en el servidor después de registrarse. "
                   "No se entrega. Avise al coordinador.")
    auditar(accion, f"dueno={t['dueno']} sha256={esperado or '-'}", recurso=f"trabajo:{t['id']}")
    return send_file(ruta, as_attachment=True, download_name=nombre_descarga)

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
        abort(409, f"El resultado aún no está disponible: el trabajo está '{t['estado']}'.")
    d = reglas_negocio.evaluar_descarga(contexto(trabajo=t), tipo="resultado")
    if not d.permitido:
        rechazar(d, f"trabajo:{trabajo_id}")
    return entregar_con_custodia(t, t["ruta_resultado"], t["sha256_resultado"], "descargar",
                                 f"resultado_{trabajo_id}.json")


@app.get("/trabajos/<int:trabajo_id>/original")
@requiere("ver_propios")
def descargar_original(trabajo_id):
    """Archivo original tal como se subió. Mismo aislamiento que el resultado + regla de originales."""
    t = obtener_trabajo_autorizado(trabajo_id, "descargar_todos")
    d = reglas_negocio.evaluar_descarga(contexto(trabajo=t), tipo="original")
    if not d.permitido:
        rechazar(d, f"trabajo:{trabajo_id}")
    return entregar_con_custodia(t, t["ruta_archivo"], t["sha256_original"], "descargar_original",
                                 t["nombre_original"])


@app.post("/trabajos/<int:trabajo_id>/eliminar")
@requiere("ver_propios")
def eliminar(trabajo_id):
    t = obtener_trabajo_autorizado(trabajo_id, "eliminar_cualquiera")
    d = reglas_negocio.evaluar_eliminacion(contexto(trabajo=t))
    if not d.permitido:
        auditar(d.evento, d.motivo, recurso=f"trabajo:{trabajo_id}", resultado="denegado")
        return render_template("detalle.html", t=t, error=d.motivo), d.http
    # El DELETE exige que el estado siga siendo el que se evaluó (el worker pudo tomarlo justo ahora)
    r = consulta("DELETE FROM trabajos WHERE id = %s AND estado = %s RETURNING ruta_archivo, ruta_resultado",
                 (trabajo_id, t["estado"]), uno=True)
    if r is None:
        abort(409, "El estado del trabajo cambió mientras tanto. Recargue la página e intente de nuevo.")
    for ruta in (r["ruta_archivo"], r["ruta_resultado"]):
        real = ruta_segura(ruta) if ruta else None
        if real and os.path.exists(real):
            os.remove(real)
    auditar("eliminar", f"dueno={t['dueno']} estado={t['estado']}", recurso=f"trabajo:{trabajo_id}")
    flash(f"Trabajo #{trabajo_id} eliminado.", "ok")
    return redirect(url_for("panel"))


@app.post("/trabajos/<int:trabajo_id>/reprocesar")
@requiere("reprocesar")
def reprocesar(trabajo_id):
    t = obtener_trabajo_autorizado(trabajo_id, "ver_todos")
    if t["estado"] != "fallido":
        auditar("reprocesar_rechazado", f"estado={t['estado']}", recurso=f"trabajo:{trabajo_id}",
                resultado="denegado")
        abort(409, "Solo se pueden reprocesar trabajos fallidos.")
    d = reglas_negocio.evaluar_reprocesado(contexto(trabajo=t))
    if not d.permitido:
        rechazar(d, f"trabajo:{trabajo_id}")
    r = consulta("UPDATE trabajos SET estado = 'pendiente', error = NULL, intentos = 0, worker = NULL, "
                 "latido = NULL, iniciado = NULL, terminado = NULL, disponible_desde = now(), "
                 "reprocesos = reprocesos + 1 WHERE id = %s AND estado = 'fallido' RETURNING id",
                 (trabajo_id,), uno=True)
    if not r:
        abort(409, "El estado del trabajo cambió mientras tanto.")
    auditar("reprocesar", f"dueno={t['dueno']}", recurso=f"trabajo:{trabajo_id}")
    flash(f"Trabajo #{trabajo_id} enviado de nuevo a la cola.", "ok")
    if request.form.get("volver") == "operacion":
        return redirect(url_for("operacion"))
    return redirect(url_for("detalle", trabajo_id=trabajo_id))


# ---------------------------------------------------------------- operación (técnico y coordinador)
ESTADOS = ("pendiente", "en_ejecucion", "completado", "fallido")


@app.get("/operacion")
@requiere("ver_todos")
def operacion():
    estado = request.args.get("estado", "")
    sql = "SELECT t.*, u.usuario AS dueno FROM trabajos t JOIN usuarios u ON u.id = t.usuario_id"
    params = ()
    if estado in ESTADOS:
        sql += " WHERE t.estado = %s"
        params = (estado,)
    trabajos = consulta(sql + " ORDER BY t.id DESC LIMIT 300", params)
    # Si la regla de confidencialidad está activa, el listado también la respeta
    trabajos = [t for t in trabajos if reglas_negocio.evaluar_acceso(contexto(trabajo=t)).permitido]
    resumen = consulta("SELECT estado, count(*) AS n FROM trabajos GROUP BY estado ORDER BY estado")
    return render_template("operacion.html", trabajos=trabajos, resumen=resumen, estado=estado)


@app.get("/recursos")
@requiere("ver_todos")
def recursos_panel():
    """Consumo de RAM/CPU/procesos/disco frente a los límites de docker-compose.yml (leído de cgroups v2)."""
    return render_template("recursos.html", app_r=recursos.recursos_app(config.MAX_MB),
                           workers=recursos.recursos_workers(config.MAX_MB), general=recursos.recursos_generales())


@app.get("/api/recursos")
@requiere("ver_todos")
def api_recursos():
    return jsonify(app=recursos.recursos_app(config.MAX_MB), workers=recursos.recursos_workers(config.MAX_MB),
                   general=recursos.recursos_generales())


# ---------------------------------------------------------------- API JSON (pruebas y estado en vivo)
OCULTOS_API = ("ruta_archivo", "ruta_resultado", "worker")


def trabajo_json(t):
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in t.items() if k not in OCULTOS_API}


@app.get("/api/trabajos")
@requiere("ver_propios")
def api_trabajos():
    filas = consulta("SELECT * FROM trabajos WHERE usuario_id = %s ORDER BY id DESC", (g.usuario["id"],))
    return jsonify([trabajo_json(t) for t in filas])


@app.get("/api/trabajos/<int:trabajo_id>")
@requiere("ver_propios")
def api_trabajo(trabajo_id):
    return jsonify(trabajo_json(obtener_trabajo_autorizado(trabajo_id, "ver_todos")))


@app.get("/api/reglas")
@requiere("ver_propios")
def api_reglas():
    """Reglas de negocio y su estado: las pruebas funcionales se adaptan a lo que esté activo."""
    return jsonify(reglas_negocio.reglas_vigentes())


@app.get("/health")
def health():
    consulta("SELECT 1", uno=True)
    return {"estado": "ok"}
