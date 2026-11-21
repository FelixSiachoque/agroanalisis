"""
SEGURIDAD DE LA APLICACIÓN (todo se valida EN EL SERVIDOR; ocultar botones en la interfaz es solo comodidad)

  cargar_usuario()             -> recarga el usuario y su rol desde la BD en CADA petición
  verificar_csrf()             -> exige el token anti-CSRF en todo formulario POST
  requiere(permiso)            -> decorador: sesión iniciada + permiso del rol (matriz en permisos.py)
  obtener_trabajo_autorizado() -> AISLAMIENTO ENTRE USUARIOS (el dueño o quien tenga un permiso global)
  ruta_segura()                -> una ruta leída de la BD solo se usa si está dentro de /data
"""
import functools
import hmac
import os
import secrets

from flask import abort, g, redirect, request, session, url_for

import reglas_negocio
from auditoria import auditar
from config import DATA_DIR
from db import consulta
from permisos import puede


# ---------------------------------------------------------------- sesión
def cargar_usuario():
    """Si a alguien lo desactivan o le cambian el rol, aplica de inmediato (no se confía en la cookie)."""
    g.usuario = None
    uid = session.get("uid")
    if uid:
        u = consulta("SELECT id, usuario, rol, activo FROM usuarios WHERE id = %s", (uid,), uno=True)
        if u and u["activo"]:
            g.usuario = u
        else:
            session.clear()


# ---------------------------------------------------------------- CSRF
def token_csrf():
    """Token aleatorio por sesión; las plantillas lo incluyen como campo oculto en cada formulario POST."""
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def verificar_csrf():
    """Un formulario enviado desde otro sitio no conoce el token: se rechaza con 400."""
    if request.method != "POST":
        return
    enviado = request.form.get("csrf", "")
    esperado = session.get("csrf", "")
    if not esperado or not hmac.compare_digest(enviado, esperado):
        auditar("csrf_rechazado", f"ruta={request.path}", resultado="denegado")
        abort(400, "El formulario expiró o no es válido. Recargue la página e intente de nuevo.")


# ---------------------------------------------------------------- permisos por rol
def requiere(permiso):
    """Decorador: exige sesión iniciada y que el rol tenga el permiso (ver permisos.py)."""
    def decorador(vista):
        @functools.wraps(vista)
        def envoltura(*args, **kwargs):
            if g.usuario is None:
                return redirect(url_for("login"))
            if not puede(g.usuario["rol"], permiso):
                auditar("acceso_denegado", f"permiso={permiso} ruta={request.path}",
                        recurso=request.path, resultado="denegado")
                abort(403)
            return vista(*args, **kwargs)
        return envoltura
    return decorador


# ---------------------------------------------------------------- AISLAMIENTO ENTRE USUARIOS
def obtener_trabajo_autorizado(trabajo_id, permiso_global):
    """
    AISLAMIENTO ENTRE USUARIOS (punto caliente del reto 3).
    Devuelve el trabajo SOLO si:
        - es del usuario actual (es_dueno), o
        - el rol del usuario tiene 'permiso_global' (ej. 'ver_todos', 'descargar_todos').
    En cualquier otro caso responde 404 (no revelamos que el trabajo existe) y lo audita.
    Toda ruta que reciba un trabajo_id DEBE pasar por aquí.
    """
    t = consulta("SELECT t.*, u.usuario AS dueno FROM trabajos t JOIN usuarios u ON u.id = t.usuario_id "
                 "WHERE t.id = %s", (trabajo_id,), uno=True)
    es_dueno = t is not None and t["usuario_id"] == g.usuario["id"]
    if t is None or not (es_dueno or puede(g.usuario["rol"], permiso_global)):
        auditar("acceso_denegado", f"motivo={'inexistente' if t is None else 'ajeno'} ruta={request.path}",
                recurso=f"trabajo:{trabajo_id}", resultado="denegado")
        abort(404)
    # Una regla de negocio puede RESTRINGIR más (ej. trabajos confidenciales), nunca ampliar el acceso.
    d = reglas_negocio.evaluar_acceso(contexto(trabajo=t))
    if not d.permitido:
        auditar(d.evento, d.motivo, recurso=f"trabajo:{trabajo_id}", resultado="denegado")
        abort(404)
    return t


def contexto(**datos):
    """Arma el Contexto que reciben las reglas de negocio con el usuario actual."""
    return reglas_negocio.Contexto(usuario_id=g.usuario["id"], rol=g.usuario["rol"],
                                   puede=lambda p: puede(g.usuario["rol"], p), **datos)


# ---------------------------------------------------------------- rutas de archivos
def ruta_segura(ruta):
    """
    Evita path traversal: una ruta guardada en la BD solo se usa si, ya resuelta
    (sin '..' ni enlaces simbólicos), queda dentro de DATA_DIR. Si no, devuelve None y lo audita.
    """
    base = os.path.realpath(DATA_DIR)
    real = os.path.realpath(ruta or "")
    if os.path.commonpath([base, real]) != base:
        auditar("ruta_sospechosa", f"ruta={ruta}", resultado="denegado")
        return None
    return real
