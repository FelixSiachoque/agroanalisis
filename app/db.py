"""Acceso a PostgreSQL y registro de auditoría."""
import logging
import os

import psycopg
from psycopg.rows import dict_row

log = logging.getLogger("app")

DSN = (
    f"host={os.environ.get('DB_HOST', 'db')} "
    f"port={os.environ.get('DB_PORT', '5432')} "
    f"dbname={os.environ['POSTGRES_DB']} "
    f"user={os.environ['POSTGRES_USER']} "
    f"password={os.environ['POSTGRES_PASSWORD']}"
)


def consulta(sql, params=(), uno=False):
    """Ejecuta SQL con parámetros (evita inyección SQL) y devuelve filas como dict."""
    with psycopg.connect(DSN, row_factory=dict_row) as con:
        cur = con.execute(sql, params)
        if cur.description is None:      # INSERT/UPDATE/DELETE sin RETURNING
            return None
        return cur.fetchone() if uno else cur.fetchall()


def auditar(usuario, accion, detalle="", ip=None):
    """Guarda un evento de auditoría: quién (usuario), qué (accion/detalle) y cuándo (fecha automática)."""
    consulta(
        "INSERT INTO auditoria (usuario, accion, detalle, ip) VALUES (%s, %s, %s, %s)",
        (usuario, accion, detalle, ip),
    )
    log.info("AUDITORIA usuario=%s accion=%s detalle=%s ip=%s", usuario, accion, detalle, ip)
