"""
MATRIZ DE PERMISOS POR ROL  (un solo lugar para cambiar quién puede hacer qué)

Para dar o quitar un permiso a un rol basta con editar este diccionario
y reiniciar la app:  docker compose restart app

Roles del caso AgroAnálisis Sugamuxi:
  admin     -> Coordinador del laboratorio
  operador  -> Técnico de laboratorio
  usuario   -> Agricultor (cliente)
"""

PERMISOS = {
    "admin": {
        "subir",               # cargar archivos y crear trabajos
        "ver_propios",         # ver / descargar / eliminar SUS trabajos
        "ver_todos",           # ver el estado de los trabajos de todos (panel de operación)
        "reprocesar",          # volver a encolar un trabajo fallido
        "descargar_todos",     # descargar el resultado de cualquier usuario
        "eliminar_cualquiera", # eliminar cualquier trabajo, incluso completado
        "gestionar_usuarios",  # crear usuarios, cambiar rol, activar/desactivar
        "ver_auditoria",       # consultar y exportar la auditoría
    },
    "operador": {
        "subir",
        "ver_propios",
        "ver_todos",
        "reprocesar",
    },
    "usuario": {
        "subir",
        "ver_propios",
    },
}

ROLES = list(PERMISOS.keys())


def puede(rol, permiso):
    """True si el rol tiene el permiso."""
    return permiso in PERMISOS.get(rol, set())
