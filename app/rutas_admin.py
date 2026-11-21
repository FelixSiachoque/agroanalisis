"""Rutas del coordinador (admin): usuarios, auditoría, verificación del sello y reglas de negocio."""
import csv
import io
from datetime import date

import psycopg
from flask import Response, abort, flash, g, jsonify, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

import reglas_negocio
from app import app
from auditoria import auditar, texto_verificacion, verificar_cadena
from db import consulta
from permisos import PERMISOS, ROLES
from seguridad import requiere
from validacion import celda_csv


# ---------------------------------------------------------------- usuarios
def admins_activos(excepto_id):
    return consulta("SELECT count(*) AS n FROM usuarios WHERE rol = 'admin' AND activo AND id <> %s",
                    (excepto_id,), uno=True)["n"]


def crear_usuario_desde_formulario():
    nombre = request.form.get("usuario", "").strip()
    clave = request.form.get("clave", "")
    rol = request.form.get("rol", "")
    if not nombre.isalnum() or len(nombre) > 50:
        return flash("El usuario debe ser alfanumérico (letras y números, máximo 50).", "error")
    if len(clave) < 8:
        return flash("La contraseña debe tener al menos 8 caracteres.", "error")
    if rol not in ROLES:
        return flash("Rol inválido.", "error")
    try:
        consulta("INSERT INTO usuarios (usuario, clave_hash, rol) VALUES (%s, %s, %s)",
                 (nombre, generate_password_hash(clave), rol))
    except psycopg.errors.UniqueViolation:
        return flash(f"El usuario '{nombre}' ya existe.", "error")
    auditar("crear_usuario", f"nuevo={nombre} rol={rol}", recurso=f"usuario:{nombre}")
    flash(f"Usuario {nombre} creado con rol {rol}.", "ok")


def modificar_usuario(accion):
    try:
        uid = int(request.form.get("id", ""))
    except ValueError:
        abort(400, "Identificador de usuario inválido.")
    objetivo = consulta("SELECT id, usuario, rol, activo FROM usuarios WHERE id = %s", (uid,), uno=True)
    if objetivo is None:
        abort(404)
    recurso = f"usuario:{uid}"
    if uid == g.usuario["id"]:
        auditar("modificar_usuario_rechazado", "intentó modificar su propia cuenta", recurso=recurso,
                resultado="denegado")
        return flash("No puede modificar su propia cuenta desde aquí.", "error")
    deja_de_ser_admin = objetivo["rol"] == "admin" and (
        accion == "desactivar" or (accion == "cambiar_rol" and request.form.get("rol") != "admin"))
    if deja_de_ser_admin and admins_activos(excepto_id=uid) == 0:
        auditar("modificar_usuario_rechazado", "dejaría el sistema sin coordinadores", recurso=recurso,
                resultado="denegado")
        return flash("Debe quedar al menos un coordinador (admin) activo.", "error")
    if accion == "cambiar_rol":
        nuevo = request.form.get("rol")
        if nuevo not in ROLES:
            return flash("Rol inválido.", "error")
        consulta("UPDATE usuarios SET rol = %s WHERE id = %s", (nuevo, uid))
        auditar("cambiar_rol", f"usuario={objetivo['usuario']} {objetivo['rol']}->{nuevo}", recurso=recurso)
        flash(f"{objetivo['usuario']} ahora tiene el rol {nuevo}.", "ok")
    else:
        consulta("UPDATE usuarios SET activo = %s WHERE id = %s", (accion == "activar", uid))
        auditar(accion, f"usuario={objetivo['usuario']}", recurso=recurso)
        flash(f"Cuenta {objetivo['usuario']}: {'activada' if accion == 'activar' else 'desactivada'}.", "ok")


@app.route("/admin/usuarios", methods=["GET", "POST"])
@requiere("gestionar_usuarios")
def usuarios():
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "crear":
            crear_usuario_desde_formulario()
        elif accion in ("cambiar_rol", "activar", "desactivar"):
            modificar_usuario(accion)
        else:
            abort(400, "Acción desconocida.")
        return redirect(url_for("usuarios"))
    lista = consulta("SELECT id, usuario, rol, activo, creado FROM usuarios ORDER BY id")
    return render_template("usuarios.html", lista=lista, roles=ROLES, permisos=PERMISOS)


# ---------------------------------------------------------------- auditoría
RESULTADOS = ("permitido", "denegado", "error")


def leer_fecha(texto):
    try:
        return date.fromisoformat(texto) if texto else None
    except ValueError:
        abort(400, "Fecha inválida (use el formato AAAA-MM-DD).")


def filtros_auditoria():
    f = {
        "usuario": request.args.get("usuario", "").strip()[:50],
        "accion": request.args.get("accion", "").strip()[:50],
        "resultado": request.args.get("resultado", "").strip(),
        "desde": request.args.get("desde", "").strip(),
        "hasta": request.args.get("hasta", "").strip(),
    }
    sql, params = "SELECT * FROM auditoria WHERE 1=1", []
    if f["usuario"]:
        sql += " AND usuario = %s"
        params.append(f["usuario"])
    if f["accion"]:
        sql += " AND accion = %s"
        params.append(f["accion"])
    if f["resultado"] in RESULTADOS:
        sql += " AND resultado = %s"
        params.append(f["resultado"])
    if leer_fecha(f["desde"]):
        sql += " AND fecha >= %s::date"
        params.append(f["desde"])
    if leer_fecha(f["hasta"]):
        sql += " AND fecha < %s::date + 1"
        params.append(f["hasta"])
    return f, sql, params


def eventos_auditoria(limite):
    f, sql, params = filtros_auditoria()
    return consulta(sql + " ORDER BY id DESC LIMIT %s", (*params, limite)), f


@app.get("/admin/auditoria")
@requiere("ver_auditoria")
def auditoria():
    eventos, f = eventos_auditoria(limite=300)
    acciones = consulta("SELECT accion, count(*) AS n FROM auditoria GROUP BY accion ORDER BY accion")
    return render_template("auditoria.html", eventos=eventos, f=f, acciones=acciones, resultados=RESULTADOS)


COLUMNAS_CSV = ["id", "seq", "fecha", "usuario", "rol", "accion", "recurso", "resultado", "detalle", "ip",
                "origen", "hash_anterior", "hash"]


@app.get("/admin/auditoria.csv")
@requiere("ver_auditoria")
def auditoria_csv():
    """Reporte de trazabilidad: exporta quién hizo qué, sobre qué y cuándo (máximo 10 000 filas)."""
    eventos, f = eventos_auditoria(limite=10000)
    salida = io.StringIO()
    w = csv.writer(salida)
    w.writerow(COLUMNAS_CSV)
    for e in eventos:
        e = dict(e, fecha=e["fecha"].isoformat())
        w.writerow([celda_csv(e.get(c)) for c in COLUMNAS_CSV])   # celda_csv: evita fórmulas en Excel
    filtro = " ".join(f"{k}={v}" for k, v in f.items() if v)
    auditar("exportar_auditoria", filtro or "sin filtros", recurso="auditoria")
    return Response(salida.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=reporte_auditoria.csv"})


# ---------------------------------------------------------------- reglas de negocio (solo lectura)
@app.get("/admin/reglas")
@requiere("ver_auditoria")
def reglas():
    return render_template("reglas.html", reglas=reglas_negocio.reglas_vigentes())


# ---------------------------------------------------------------- sello: verificar la cadena de auditoría
def verificar_y_auditar():
    r = verificar_cadena()
    auditar("verificar_cadena", texto_verificacion(r), recurso="auditoria",
            resultado="permitido" if r["integra"] else "error")
    return r


@app.get("/admin/auditoria/verificar")
@requiere("ver_auditoria")
def verificar_auditoria():
    r = verificar_y_auditar()
    return render_template("verificar.html", r=r, texto=texto_verificacion(r))


@app.get("/api/auditoria/verificar")
@requiere("ver_auditoria")
def api_verificar_auditoria():
    r = verificar_y_auditar()
    return jsonify(dict(r, mensaje=texto_verificacion(r)))
