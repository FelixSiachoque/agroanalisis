"""
Acceso a PostgreSQL.

- consulta(): ejecuta una sentencia con parámetros (evita inyección SQL) y devuelve dicts.
- transaccion(): bloque 'with' donde varias sentencias se confirman juntas (o ninguna).

Se usa un pool de conexiones: cada proceso de Gunicorn mantiene de 1 a 4 conexiones abiertas
en vez de abrir una conexión TCP nueva en cada consulta.
"""
import contextlib
import logging

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from config import DB_DSN

log = logging.getLogger("app")

_pool = None


def pool():
    """Crea el pool la primera vez que se usa (ya dentro del proceso de Gunicorn, después del fork)."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(DB_DSN, min_size=1, max_size=4, timeout=10,
                               kwargs={"row_factory": dict_row},
                               check=ConnectionPool.check_connection,  # descarta conexiones muertas (BD reiniciada)
                               open=True)
    return _pool


def consulta(sql, params=(), uno=False):
    """Ejecuta SQL con parámetros y devuelve filas como dict (o una sola fila si uno=True)."""
    with pool().connection() as con:
        cur = con.execute(sql, params)
        if cur.description is None:      # INSERT/UPDATE/DELETE sin RETURNING
            return None
        return cur.fetchone() if uno else cur.fetchall()


@contextlib.contextmanager
def transaccion():
    """
    Uso:
        with transaccion() as cur:
            cur.execute(...)
            cur.execute(...)
    Si ocurre una excepción dentro del bloque, se deshace todo (rollback).
    """
    with pool().connection() as con:
        with con.transaction():
            with con.cursor() as cur:
                yield cur
