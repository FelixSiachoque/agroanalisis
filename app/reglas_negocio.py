"""
REGLAS DE NEGOCIO DEL LABORATORIO AgroAnálisis Sugamuxi
=======================================================

Aquí están TODAS las reglas propias del caso, y SOLO ellas:
  - los permisos por rol están en permisos.py
  - el aislamiento entre usuarios en seguridad.obtener_trabajo_autorizado()
  - la validación técnica de archivos (tipo, tamaño, binario, UTF-8) en validacion.py
Apagar todas las reglas de este archivo NO debilita nada de lo anterior.

CÓMO SE USA
  1. Activar / desactivar una regla:  cambiar "activa" en el diccionario REGLAS (abajo)
     y aplicar con:                    docker compose up -d --build app
     o sin reconstruir, desde el .env:  REGLA_CABECERA_CSV_OBLIGATORIA=1   ->  docker compose up -d app
  2. Cambiar un parámetro:              editar el valor en REGLAS (o su variable del .env si la tiene)
  3. Crear una regla nueva:             ver la PLANTILLA al final del archivo

FLUJO
  ruta (rutas.py) -> evaluar_subida / evaluar_descarga / ... (punto de enganche)
                  -> se ejecutan EN ORDEN las reglas activas de ese enganche
                  -> la primera que niega devuelve Decision(permitido=False, motivo, evento, http)
                  -> la ruta audita el 'evento', muestra el 'motivo' y responde con 'http'

Este archivo no usa Flask ni la base de datos: se prueba solo con
    python -m unittest pruebas/test_reglas_negocio.py
"""
import csv
import io
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional


def _env(nombre, defecto):
    return os.environ.get(nombre, "").strip() or defecto


def _env_entero(nombre, defecto):
    return int(_env(nombre, str(defecto)))


def _activa(regla, defecto):
    """Permite encender/apagar una regla desde el .env: REGLA_<NOMBRE>=1 o 0 (vacío = usar el defecto)."""
    valor = os.environ.get(f"REGLA_{regla.upper()}", "").strip()
    return defecto if valor == "" else valor in ("1", "true", "si", "sí")


# =====================================================================================
#  CONFIGURACIÓN DE LAS REGLAS  (lo único que normalmente se toca en un reto)
#  El orden dentro de cada enganche es el orden en que se evalúan.
# =====================================================================================
REGLAS = {
    # ---------------------------------------------------------------- ACTIVAS POR DEFECTO
    "cuota_trabajos_activos": {
        "activa": _activa("cuota_trabajos_activos", True),
        "enganche": "subida",
        "descripcion": "Un agricultor puede tener como máximo {max} trabajos en cola o en proceso.",
        "max": _env_entero("MAX_ACTIVOS_USUARIO", 3),
        "roles_afectados": ["usuario"],
    },
    "bloquear_borrado_finalizados": {
        "activa": _activa("bloquear_borrado_finalizados", True),
        "enganche": "eliminacion",
        "descripcion": "Un trabajo completado o en ejecución solo lo puede eliminar el coordinador "
                       "(quien tenga el permiso 'eliminar_cualquiera').",
        "estados_protegidos": ["completado", "en_ejecucion"],
        "permiso_exento": "eliminar_cualquiera",
    },

    # ---------------------------------------------------------------- PREPARADAS (apagadas)
    "cabecera_csv_obligatoria": {
        "activa": _activa("cabecera_csv_obligatoria", False),
        "enganche": "subida",
        "descripcion": "Todo CSV debe empezar exactamente con la cabecera '{cabecera}'; si no, "
                       "se rechaza antes de entrar a la cola.",
        "cabecera": _env("CABECERA_CSV", "lote_id,fecha,medicion"),
    },
    "rangos_agronomicos_validos": {
        "activa": _activa("rangos_agronomicos_validos", False),
        "enganche": "subida",
        "descripcion": "Un CSV con pH fuera de {ph_min}-{ph_max} o porcentajes fuera de 0-100 "
                       "se rechaza antes de entrar a la cola.",
        "ph_min": 0.0, "ph_max": 14.0,
        "columnas_ph": ["ph"],
        "sufijo_porcentaje": "_pct",          # columnas como materia_organica_pct
    },
    "tamano_maximo_por_rol": {
        "activa": _activa("tamano_maximo_por_rol", False),
        "enganche": "subida",
        "descripcion": "Tamaño máximo por rol (MB): {mb}.",
        "mb": {"usuario": 1, "operador": 2, "admin": 2},
    },
    "ventana_recepcion": {
        "activa": _activa("ventana_recepcion", False),
        "enganche": "subida",
        "descripcion": "Los agricultores solo pueden enviar muestras entre las {desde}:00 y las {hasta}:00 "
                       "(hora de Colombia).",
        "desde": 6, "hasta": 18,
        "roles_afectados": ["usuario"],
    },
    "bloquear_descarga_originales_ajenos": {
        "activa": _activa("bloquear_descarga_originales_ajenos", False),
        "enganche": "descarga",
        "descripcion": "El archivo ORIGINAL solo lo descarga su dueño o el coordinador; el técnico "
                       "supervisa pero no descarga originales ajenos.",
        "roles_permitidos": ["admin"],
    },
    "trabajos_confidenciales": {
        "activa": _activa("trabajos_confidenciales", False),
        "enganche": "acceso",
        "descripcion": "Un trabajo marcado como confidencial solo lo ven su dueño y el coordinador.",
        "roles_permitidos": ["admin"],
    },
    "limite_reprocesos": {
        "activa": _activa("limite_reprocesos", False),
        "enganche": "reprocesado",
        "descripcion": "Un trabajo fallido se puede reprocesar como máximo {max} veces.",
        "max": 2,
    },
}


# =====================================================================================
#  TIPOS: lo que recibe y lo que devuelve cada regla
# =====================================================================================
@dataclass
class Contexto:
    usuario_id: int
    rol: str
    puede: Callable[[str], bool] = lambda permiso: False   # permisos.puede(rol, permiso)
    trabajo: Optional[dict] = None       # fila de la tabla trabajos (si la acción es sobre un trabajo)
    nombre: str = ""                     # nombre del archivo subido
    extension: str = ""                  # txt | csv
    tamano: int = 0                      # bytes del archivo subido
    texto: str = ""                      # contenido del archivo ya decodificado
    n_activos: int = 0                   # trabajos pendientes/en ejecución del usuario
    tipo_descarga: str = "resultado"     # resultado | original
    ahora: Optional[datetime] = None     # para probar reglas de horario
    extra: dict = field(default_factory=dict)

    @property
    def es_dueno(self):
        return self.trabajo is not None and self.trabajo.get("usuario_id") == self.usuario_id


@dataclass(frozen=True)
class Decision:
    permitido: bool
    motivo: str = ""     # mensaje para el usuario (qué pasó y qué hacer)
    evento: str = ""     # acción que se guarda en la auditoría (regla_<nombre>)
    http: int = 200      # código HTTP si se niega


PERMITIDO = Decision(True)


def negar(regla, motivo, http=403):
    return Decision(False, motivo, f"regla_{regla}", http)


# Registro de funciones: el decorador @regla("nombre") asocia la función con su entrada en REGLAS
FUNCIONES: dict = {}


def regla(nombre):
    def registrar(funcion):
        FUNCIONES[nombre] = funcion
        return funcion
    return registrar


# =====================================================================================
#  REGLAS (funciones puras: reciben Contexto y su configuración, devuelven Decision)
# =====================================================================================
@regla("cuota_trabajos_activos")
def _cuota(ctx, cfg):
    if ctx.rol in cfg["roles_afectados"] and ctx.n_activos >= cfg["max"]:
        return negar("cuota_trabajos_activos",
                     f"Regla del laboratorio: máximo {cfg['max']} trabajos en cola por agricultor. "
                     f"Tiene {ctx.n_activos}; espere a que terminen.", 409)
    return PERMITIDO


@regla("bloquear_borrado_finalizados")
def _borrado(ctx, cfg):
    if ctx.trabajo["estado"] in cfg["estados_protegidos"] and not ctx.puede(cfg["permiso_exento"]):
        return negar("bloquear_borrado_finalizados",
                     f"No puede eliminar un trabajo en estado '{ctx.trabajo['estado']}'. "
                     "Solo el coordinador puede hacerlo (trazabilidad del laboratorio).", 403)
    return PERMITIDO


@regla("cabecera_csv_obligatoria")
def _cabecera(ctx, cfg):
    if ctx.extension != "csv":
        return PERMITIDO
    primera = ctx.texto.lstrip("﻿").split("\n", 1)[0].strip()
    if primera != cfg["cabecera"]:
        return negar("cabecera_csv_obligatoria",
                     f"El CSV debe empezar con la cabecera exacta '{cfg['cabecera']}' "
                     f"(se recibió '{primera[:60]}').", 422)
    return PERMITIDO


def _numero(texto):
    try:
        return float(texto.strip().replace(",", "."))
    except ValueError:
        return None


@regla("rangos_agronomicos_validos")
def _rangos(ctx, cfg):
    if ctx.extension != "csv":
        return PERMITIDO
    filas = csv.reader(io.StringIO(ctx.texto.lstrip("﻿")))
    encabezado = [c.strip().lower() for c in next(filas, [])]
    for n_fila, fila in enumerate(filas, start=2):
        for col, valor in zip(encabezado, fila):
            v = _numero(valor)
            if v is None:
                continue
            if col in cfg["columnas_ph"] and not cfg["ph_min"] <= v <= cfg["ph_max"]:
                return negar("rangos_agronomicos_validos",
                             f"Fila {n_fila}: {col}={valor.strip()} está fuera del rango "
                             f"{cfg['ph_min']:g}-{cfg['ph_max']:g}.", 422)
            if col.endswith(cfg["sufijo_porcentaje"]) and not 0 <= v <= 100:
                return negar("rangos_agronomicos_validos",
                             f"Fila {n_fila}: {col}={valor.strip()} no es un porcentaje válido (0-100).", 422)
    return PERMITIDO


@regla("tamano_maximo_por_rol")
def _tamano_rol(ctx, cfg):
    limite_mb = cfg["mb"].get(ctx.rol)
    if limite_mb is not None and ctx.tamano > limite_mb * 1024 * 1024:
        return negar("tamano_maximo_por_rol",
                     f"Para su rol el archivo puede pesar como máximo {limite_mb} MB.", 413)
    return PERMITIDO


HORA_COLOMBIA = timezone(timedelta(hours=-5))   # Colombia no tiene horario de verano


@regla("ventana_recepcion")
def _ventana(ctx, cfg):
    ahora = ctx.ahora or datetime.now(HORA_COLOMBIA)
    if ctx.rol in cfg["roles_afectados"] and not cfg["desde"] <= ahora.hour < cfg["hasta"]:
        return negar("ventana_recepcion",
                     f"El laboratorio recibe muestras entre las {cfg['desde']}:00 y las {cfg['hasta']}:00. "
                     "Intente de nuevo en ese horario.", 403)
    return PERMITIDO


@regla("bloquear_descarga_originales_ajenos")
def _originales(ctx, cfg):
    if ctx.tipo_descarga == "original" and not ctx.es_dueno and ctx.rol not in cfg["roles_permitidos"]:
        return negar("bloquear_descarga_originales_ajenos",
                     "Solo el dueño o el coordinador pueden descargar el archivo original.", 403)
    return PERMITIDO


@regla("trabajos_confidenciales")
def _confidenciales(ctx, cfg):
    if ctx.trabajo.get("confidencial") and not ctx.es_dueno and ctx.rol not in cfg["roles_permitidos"]:
        return negar("trabajos_confidenciales", "Trabajo confidencial.", 404)
    return PERMITIDO


@regla("limite_reprocesos")
def _reprocesos(ctx, cfg):
    if ctx.trabajo.get("reprocesos", 0) >= cfg["max"]:
        return negar("limite_reprocesos",
                     f"Este trabajo ya se reprocesó {cfg['max']} veces; revise el archivo original.", 409)
    return PERMITIDO


# =====================================================================================
#  PUNTOS DE ENGANCHE (lo único que llaman las rutas)
# =====================================================================================
def _evaluar(enganche, ctx):
    for nombre, cfg in REGLAS.items():
        if cfg["enganche"] == enganche and cfg["activa"]:
            decision = FUNCIONES[nombre](ctx, cfg)
            if not decision.permitido:
                return decision
    return PERMITIDO


def evaluar_subida(ctx):
    """Antes de guardar el archivo y encolar el trabajo."""
    return _evaluar("subida", ctx)


def evaluar_descarga(ctx, tipo="resultado"):
    """Antes de entregar un archivo. tipo = 'resultado' | 'original'."""
    ctx.tipo_descarga = tipo
    return _evaluar("descarga", ctx)


def evaluar_eliminacion(ctx):
    """Antes de borrar un trabajo."""
    return _evaluar("eliminacion", ctx)


def evaluar_reprocesado(ctx):
    """Antes de devolver un trabajo fallido a la cola."""
    return _evaluar("reprocesado", ctx)


def evaluar_acceso(ctx):
    """Después del aislamiento: solo puede RESTRINGIR el acceso a un trabajo, nunca ampliarlo."""
    return _evaluar("acceso", ctx)


def esta_activa(nombre):
    return REGLAS.get(nombre, {}).get("activa", False)


def describir(nombre):
    """Descripción legible con los parámetros reales, ej. 'máximo 3 trabajos...'."""
    cfg = REGLAS[nombre]
    return cfg["descripcion"].format(**{k: v for k, v in cfg.items() if k != "descripcion"})


def reglas_vigentes(solo_activas=False):
    """Lista para la interfaz y para GET /api/reglas."""
    salida = []
    for nombre, cfg in REGLAS.items():
        if solo_activas and not cfg["activa"]:
            continue
        parametros = {k: v for k, v in cfg.items() if k not in ("activa", "enganche", "descripcion")}
        salida.append({"nombre": nombre, "activa": cfg["activa"], "enganche": cfg["enganche"],
                       "descripcion": describir(nombre), "parametros": parametros})
    return salida


# =====================================================================================
#  PLANTILLA: REGLA NUEVA (copiar, quitar los '#' y adaptar)
# =====================================================================================
# 1) Agregue su configuración dentro de REGLAS (arriba):
#    "mi_regla": {
#        "activa": _activa("mi_regla", True),
#        "enganche": "subida",            # subida | descarga | eliminacion | reprocesado | acceso
#        "descripcion": "Los agricultores no pueden subir archivos de más de {mb} MB.",
#        "mb": 1,
#    },
#
# 2) Escriba la función (aquí abajo). Recibe ctx (Contexto) y cfg (su configuración):
# @regla("mi_regla")
# def _mi_regla(ctx, cfg):
#     if ctx.rol == "usuario" and ctx.tamano > cfg["mb"] * 1024 * 1024:
#         return negar("mi_regla", f"Máximo {cfg['mb']} MB para agricultores.", 413)
#     return PERMITIDO
#
# 3) Pruebe:   python -m unittest pruebas/test_reglas_negocio.py
#    Aplique:  docker compose up -d --build app
#    Verifique en Auditoría el evento 'regla_mi_regla'.
