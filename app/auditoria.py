"""
AUDITORÍA: la única función para registrar eventos es auditar().

Uso típico dentro de una ruta (el usuario, su rol y la IP se toman solos de la sesión):

    auditar("descargar", f"trabajo={t['id']}", recurso=f"trabajo:{t['id']}")
    auditar("acceso_denegado", "permiso=ver_auditoria", resultado="denegado")

Cada evento queda en la tabla 'auditoria' con: fecha, usuario, rol, acción, recurso,
resultado (permitido | denegado | error), detalle, IP y origen.
La base de datos encadena cada evento con el anterior (ver sello de autenticidad en el README),
así que agregar un evento nuevo NO requiere tocar nada más que llamar a esta función.
"""
import logging

from flask import g, has_request_context, request

from db import consulta

log = logging.getLogger("app")


def auditar(accion, detalle="", recurso=None, resultado="permitido", usuario=None, rol=None, origen="app"):
    """Guarda un evento de auditoría: quién, qué, sobre qué recurso, con qué resultado y cuándo."""
    ip = None
    if has_request_context():
        ip = request.remote_addr
        if usuario is None and g.get("usuario"):
            usuario, rol = g.usuario["usuario"], g.usuario["rol"]
    usuario = (usuario or "(anónimo)")[:50]   # recorte: un nombre gigante no debe tumbar la app
    consulta(
        "INSERT INTO auditoria (usuario, rol, accion, recurso, resultado, detalle, ip, origen) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (usuario, rol, accion[:50], (recurso or None) and recurso[:100], resultado,
         (detalle or "")[:1000], ip and ip[:45], origen),
    )
    # %r: si el texto trae saltos de línea, no puede falsificar líneas del log
    log.info("AUDITORIA usuario=%r rol=%s accion=%s recurso=%s resultado=%s detalle=%r ip=%s",
             usuario, rol, accion, recurso, resultado, detalle, ip)
