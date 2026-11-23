"""
Pruebas unitarias de app/reglas_negocio.py (cada regla activa e inactiva).
No necesitan Docker, Flask ni base de datos.

Uso (desde la raíz del proyecto):
    python -m unittest pruebas/test_reglas_negocio.py -v
Dentro del contenedor de la app (sin copiar nada):
    docker compose exec -T app python - < pruebas/test_reglas_negocio.py
"""
import contextlib
import os
import sys
import unittest
from datetime import datetime

try:
    AQUI = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(AQUI, "..", "app"))
except NameError:            # ejecutado por stdin dentro del contenedor
    sys.path.insert(0, "/srv")

import reglas_negocio as rn  # noqa: E402
from permisos import puede   # noqa: E402

CSV_SUELOS = "muestra,finca,ph,materia_organica_pct\nA-1,El Mirador,6.4,5.2\nA-2,La Laguna,7.1,3.0\n"
CSV_PH_MALO = "muestra,finca,ph,materia_organica_pct\nA-1,El Mirador,6.4,5.2\nA-2,La Laguna,15.2,3.0\n"
CSV_PCT_MALO = "muestra,ph,materia_organica_pct\nA-1,6.4,120\n"
CSV_CABECERA = "lote_id,fecha,medicion\nL1,2026-03-01,6.2\n"


def ctx(rol="usuario", usuario_id=1, **datos):
    return rn.Contexto(usuario_id=usuario_id, rol=rol, puede=lambda p: puede(rol, p), **datos)


def trabajo(estado="completado", dueno=1, **extra):
    return {"id": 10, "usuario_id": dueno, "estado": estado, **extra}


@contextlib.contextmanager
def reglas(**estado):
    """Cambia temporalmente qué reglas están activas: with ninguna(): ..."""
    antes = {n: c["activa"] for n, c in rn.REGLAS.items()}
    try:
        for nombre, activa in estado.items():
            rn.REGLAS[nombre]["activa"] = activa
        yield
    finally:
        for nombre, activa in antes.items():
            rn.REGLAS[nombre]["activa"] = activa


def solo(nombre):
    """Activa SOLO la regla indicada (las demás apagadas) para probarla aislada."""
    return reglas(**{n: (n == nombre) for n in rn.REGLAS})


def ninguna():
    """Apaga TODAS las reglas: así una regla nueva que se agregue no contamina las pruebas de las demás."""
    return reglas(**{n: False for n in rn.REGLAS})


class PruebasEstructura(unittest.TestCase):
    def test_cada_regla_tiene_funcion_y_enganche_valido(self):
        for nombre, cfg in rn.REGLAS.items():
            self.assertIn(nombre, rn.FUNCIONES, f"falta @regla('{nombre}')")
            self.assertIn(cfg["enganche"], ("subida", "descarga", "eliminacion", "reprocesado", "acceso"))
            self.assertTrue(rn.describir(nombre))

    def test_por_defecto_solo_las_dos_reglas_originales_estan_activas(self):
        activas = {n for n, c in rn.REGLAS.items() if c["activa"]}
        self.assertEqual(activas, {"cuota_trabajos_activos", "bloquear_borrado_finalizados"})

    def test_con_todas_apagadas_todo_se_permite(self):
        with reglas(**{n: False for n in rn.REGLAS}):
            self.assertTrue(rn.evaluar_subida(ctx(n_activos=99, extension="csv", texto="x\n")).permitido)
            self.assertTrue(rn.evaluar_eliminacion(ctx(trabajo=trabajo("completado"))).permitido)
            self.assertTrue(rn.evaluar_descarga(ctx(rol="operador", trabajo=trabajo(dueno=2)), "original").permitido)
            self.assertTrue(rn.evaluar_reprocesado(ctx(trabajo=trabajo("fallido", reprocesos=9))).permitido)
            self.assertTrue(rn.evaluar_acceso(ctx(rol="operador", trabajo=trabajo(dueno=2, confidencial=True))).permitido)

    def test_api_reglas_lista_todas(self):
        nombres = [r["nombre"] for r in rn.reglas_vigentes()]
        self.assertEqual(nombres, list(rn.REGLAS))

    def test_variable_de_entorno_enciende_y_apaga(self):
        os.environ["REGLA_PRUEBA_X"] = "1"
        self.assertTrue(rn._activa("prueba_x", False))
        os.environ["REGLA_PRUEBA_X"] = "0"
        self.assertFalse(rn._activa("prueba_x", True))
        os.environ["REGLA_PRUEBA_X"] = ""
        self.assertTrue(rn._activa("prueba_x", True))
        del os.environ["REGLA_PRUEBA_X"]


class PruebasCuota(unittest.TestCase):
    def test_activa_niega_al_llegar_al_maximo(self):
        with solo("cuota_trabajos_activos"):
            maximo = rn.REGLAS["cuota_trabajos_activos"]["max"]
            self.assertTrue(rn.evaluar_subida(ctx(n_activos=maximo - 1)).permitido)
            d = rn.evaluar_subida(ctx(n_activos=maximo))
            self.assertFalse(d.permitido)
            self.assertEqual((d.http, d.evento), (409, "regla_cuota_trabajos_activos"))

    def test_no_aplica_a_operador_ni_admin(self):
        with solo("cuota_trabajos_activos"):
            self.assertTrue(rn.evaluar_subida(ctx(rol="operador", n_activos=50)).permitido)
            self.assertTrue(rn.evaluar_subida(ctx(rol="admin", n_activos=50)).permitido)

    def test_inactiva(self):
        with ninguna():
            self.assertTrue(rn.evaluar_subida(ctx(n_activos=50)).permitido)


class PruebasBorrado(unittest.TestCase):
    def test_agricultor_no_borra_completado_ni_en_ejecucion(self):
        with solo("bloquear_borrado_finalizados"):
            for estado in ("completado", "en_ejecucion"):
                d = rn.evaluar_eliminacion(ctx(trabajo=trabajo(estado)))
                self.assertFalse(d.permitido, estado)
                self.assertEqual(d.http, 403)

    def test_agricultor_si_borra_fallido_o_pendiente(self):
        with solo("bloquear_borrado_finalizados"):
            for estado in ("fallido", "pendiente"):
                self.assertTrue(rn.evaluar_eliminacion(ctx(trabajo=trabajo(estado))).permitido, estado)

    def test_coordinador_si_borra_completado(self):
        with solo("bloquear_borrado_finalizados"):
            self.assertTrue(rn.evaluar_eliminacion(ctx(rol="admin", trabajo=trabajo("completado"))).permitido)

    def test_inactiva(self):
        with ninguna():
            self.assertTrue(rn.evaluar_eliminacion(ctx(trabajo=trabajo("completado"))).permitido)


class PruebasCabecera(unittest.TestCase):
    def test_activa(self):
        with solo("cabecera_csv_obligatoria"):
            self.assertTrue(rn.evaluar_subida(ctx(extension="csv", texto=CSV_CABECERA)).permitido)
            self.assertTrue(rn.evaluar_subida(ctx(extension="csv", texto="﻿" + CSV_CABECERA)).permitido)
            d = rn.evaluar_subida(ctx(extension="csv", texto=CSV_SUELOS))
            self.assertFalse(d.permitido)
            self.assertEqual(d.http, 422)
            self.assertTrue(rn.evaluar_subida(ctx(extension="txt", texto="informe")).permitido)

    def test_inactiva(self):
        with ninguna():
            self.assertTrue(rn.evaluar_subida(ctx(extension="csv", texto=CSV_SUELOS)).permitido)


class PruebasRangos(unittest.TestCase):
    def test_activa(self):
        with solo("rangos_agronomicos_validos"):
            self.assertTrue(rn.evaluar_subida(ctx(extension="csv", texto=CSV_SUELOS)).permitido)
            d = rn.evaluar_subida(ctx(extension="csv", texto=CSV_PH_MALO))
            self.assertFalse(d.permitido)
            self.assertIn("Fila 3", d.motivo)
            self.assertFalse(rn.evaluar_subida(ctx(extension="csv", texto=CSV_PCT_MALO)).permitido)

    def test_inactiva(self):
        with ninguna():
            self.assertTrue(rn.evaluar_subida(ctx(extension="csv", texto=CSV_PH_MALO)).permitido)


class PruebasTamanoPorRol(unittest.TestCase):
    def test_activa(self):
        with solo("tamano_maximo_por_rol"):
            mb = 1024 * 1024
            self.assertTrue(rn.evaluar_subida(ctx(tamano=mb // 2)).permitido)
            d = rn.evaluar_subida(ctx(tamano=int(1.5 * mb)))
            self.assertFalse(d.permitido)
            self.assertEqual(d.http, 413)
            self.assertTrue(rn.evaluar_subida(ctx(rol="operador", tamano=int(1.5 * mb))).permitido)

    def test_inactiva(self):
        with ninguna():
            self.assertTrue(rn.evaluar_subida(ctx(tamano=10 * 1024 * 1024)).permitido)


class PruebasVentana(unittest.TestCase):
    def test_activa(self):
        with solo("ventana_recepcion"):
            dia = datetime(2026, 11, 20, 10, 0, tzinfo=rn.HORA_COLOMBIA)
            noche = datetime(2026, 11, 20, 22, 0, tzinfo=rn.HORA_COLOMBIA)
            self.assertTrue(rn.evaluar_subida(ctx(ahora=dia)).permitido)
            self.assertFalse(rn.evaluar_subida(ctx(ahora=noche)).permitido)
            self.assertTrue(rn.evaluar_subida(ctx(rol="operador", ahora=noche)).permitido)

    def test_inactiva(self):
        with ninguna():
            noche = datetime(2026, 11, 20, 22, 0, tzinfo=rn.HORA_COLOMBIA)
            self.assertTrue(rn.evaluar_subida(ctx(ahora=noche)).permitido)


class PruebasOriginales(unittest.TestCase):
    def test_activa(self):
        with solo("bloquear_descarga_originales_ajenos"):
            ajeno = trabajo(dueno=2)
            self.assertFalse(rn.evaluar_descarga(ctx(rol="operador", trabajo=ajeno), "original").permitido)
            self.assertTrue(rn.evaluar_descarga(ctx(rol="admin", trabajo=ajeno), "original").permitido)
            self.assertTrue(rn.evaluar_descarga(ctx(trabajo=trabajo(dueno=1)), "original").permitido)
            # solo afecta originales, no resultados
            self.assertTrue(rn.evaluar_descarga(ctx(rol="operador", trabajo=ajeno), "resultado").permitido)

    def test_inactiva(self):
        with ninguna():
            self.assertTrue(rn.evaluar_descarga(ctx(rol="operador", trabajo=trabajo(dueno=2)), "original").permitido)


class PruebasConfidenciales(unittest.TestCase):
    def test_activa(self):
        with solo("trabajos_confidenciales"):
            secreto = trabajo(dueno=2, confidencial=True)
            self.assertFalse(rn.evaluar_acceso(ctx(rol="operador", trabajo=secreto)).permitido)
            self.assertTrue(rn.evaluar_acceso(ctx(rol="admin", trabajo=secreto)).permitido)
            self.assertTrue(rn.evaluar_acceso(ctx(usuario_id=2, trabajo=secreto)).permitido)
            self.assertTrue(rn.evaluar_acceso(ctx(rol="operador", trabajo=trabajo(dueno=2))).permitido)

    def test_inactiva(self):
        with ninguna():
            self.assertTrue(rn.evaluar_acceso(ctx(rol="operador", trabajo=trabajo(dueno=2, confidencial=True))).permitido)


class PruebasLimiteReprocesos(unittest.TestCase):
    def test_activa(self):
        with solo("limite_reprocesos"):
            self.assertTrue(rn.evaluar_reprocesado(ctx(rol="operador", trabajo=trabajo("fallido", reprocesos=1))).permitido)
            d = rn.evaluar_reprocesado(ctx(rol="operador", trabajo=trabajo("fallido", reprocesos=2)))
            self.assertFalse(d.permitido)
            self.assertEqual(d.http, 409)

    def test_inactiva(self):
        with ninguna():
            self.assertTrue(rn.evaluar_reprocesado(ctx(trabajo=trabajo("fallido", reprocesos=10))).permitido)


if __name__ == "__main__":
    unittest.main(verbosity=2)
