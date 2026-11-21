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

from db import consulta, transaccion

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


# ---------------------------------------------------------------- sello: verificación de la cadena
HASH_INICIAL = "0" * 64


def verificar_cadena():
    """
    Recorre TODOS los eventos en orden (seq) y comprueba tres cosas en cada uno:
      1. que no falte ninguno (seq consecutivo)            -> detecta eventos borrados
      2. que enlace con el anterior (hash_anterior)         -> detecta eventos insertados o reordenados
      3. que su hash coincida con su contenido actual       -> detecta eventos modificados
    Al final, la tabla auditoria_cabeza debe apuntar al último evento -> detecta borrados al final.
    El hash lo recalcula la misma función SQL que usa el trigger, así ambos lados usan la misma fórmula.
    Devuelve dict(integra, total, evento_id, seq, motivo).
    """
    with transaccion() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")   # foto consistente de la tabla
        cur.execute("SELECT id, seq, hash_anterior, hash, auditoria_calcular_hash(seq, hash_anterior, fecha, "
                    "usuario, rol, accion, recurso, resultado, detalle, ip, origen) AS recalculado "
                    "FROM auditoria ORDER BY seq")
        filas = cur.fetchall()
        cur.execute("SELECT seq, ultimo_hash FROM auditoria_cabeza")
        cabeza = cur.fetchone()

    anterior, esperado = HASH_INICIAL, 1
    for f in filas:
        roto = None
        if f["seq"] != esperado:
            roto = f"falta el evento con seq={esperado} (fue borrado)"
        elif f["hash_anterior"] != anterior:
            roto = "no enlaza con el evento anterior (se insertó o reordenó un evento)"
        elif f["recalculado"] != f["hash"]:
            roto = "su contenido fue modificado después de registrarse"
        if roto:
            return {"integra": False, "total": len(filas), "evento_id": f["id"], "seq": f["seq"], "motivo": roto}
        anterior, esperado = f["hash"], esperado + 1
    if cabeza and (cabeza["seq"] != len(filas) or cabeza["ultimo_hash"] != anterior):
        return {"integra": False, "total": len(filas), "evento_id": None, "seq": cabeza["seq"],
                "motivo": f"la cabeza de la cadena espera {cabeza['seq']} eventos y hay {len(filas)} "
                          "(se borraron eventos al final)"}
    return {"integra": True, "total": len(filas), "evento_id": None, "seq": len(filas), "motivo": ""}


def texto_verificacion(r):
    if r["integra"]:
        return f"Cadena íntegra: {r['total']} eventos verificados."
    donde = f"en el evento #{r['evento_id']} (seq {r['seq']})" if r["evento_id"] else "al final de la cadena"
    return f"Cadena ROTA {donde}: {r['motivo']}."
