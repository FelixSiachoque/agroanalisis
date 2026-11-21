"""
VALIDACIÓN TÉCNICA DE ARCHIVOS Y DATOS (no son reglas de negocio: protegen a la plataforma).

Política de archivos:
  - solo .txt o .csv
  - máximo MAX_MB
  - texto UTF-8, sin bytes nulos (un binario disfrazado de .txt se rechaza)
  - CSV: máximo MAX_FILAS_CSV filas y MAX_COLUMNAS_CSV columnas
  - el nombre original se limpia (sin rutas ni caracteres de control) antes de guardarlo

Las reglas del laboratorio (cuota, cabecera obligatoria, etc.) están en reglas_negocio.py.
"""
import csv
import hashlib
import io
import os
import unicodedata
from dataclasses import dataclass

from config import (EXTENSIONES_PERMITIDAS, MAX_BYTES, MAX_COLUMNAS_CSV, MAX_FILAS_CSV, MAX_MB,
                    MAX_NOMBRE_ARCHIVO)


@dataclass
class ArchivoValidado:
    nombre: str      # nombre original ya saneado
    extension: str   # txt | csv
    datos: bytes     # contenido tal cual llegó
    texto: str       # contenido decodificado (UTF-8)
    sha256: str      # huella del contenido recibido (cadena de custodia)


class ArchivoInvalido(ValueError):
    """El archivo no cumple la política técnica. El mensaje se muestra al usuario."""


def sanear_nombre(nombre):
    """Quita rutas ('../', 'C:\\'), caracteres de control y recorta la longitud."""
    nombre = os.path.basename((nombre or "").replace("\\", "/"))
    nombre = "".join(c for c in nombre if unicodedata.category(c)[0] != "C").strip()
    return nombre[-MAX_NOMBRE_ARCHIVO:] or "archivo"


def validar_archivo(archivo):
    """Recibe el archivo del formulario. Devuelve ArchivoValidado o lanza ArchivoInvalido."""
    if not archivo or not archivo.filename:
        raise ArchivoInvalido("Debe seleccionar un archivo.")
    nombre = sanear_nombre(archivo.filename)
    ext = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
    if ext not in EXTENSIONES_PERMITIDAS:
        raise ArchivoInvalido(f"Tipo no permitido (.{ext}). Solo se aceptan: .txt y .csv")
    datos = archivo.read(MAX_BYTES + 1)
    if len(datos) == 0:
        raise ArchivoInvalido("El archivo está vacío.")
    if len(datos) > MAX_BYTES:
        raise ArchivoInvalido(f"El archivo supera el máximo de {MAX_MB:g} MB.")
    if b"\x00" in datos:
        raise ArchivoInvalido("El archivo parece binario; solo se acepta texto.")
    try:
        texto = datos.decode("utf-8")
    except UnicodeDecodeError:
        raise ArchivoInvalido("El archivo debe estar codificado en UTF-8.")
    if ext == "csv":
        validar_dimensiones_csv(texto)
    return ArchivoValidado(nombre, ext, datos, texto, hashlib.sha256(datos).hexdigest())


def validar_dimensiones_csv(texto):
    """Evita que un CSV gigantesco en filas o columnas consuma la memoria del worker."""
    filas = texto.count("\n") + (0 if texto.endswith("\n") else 1)
    if filas - 1 > MAX_FILAS_CSV:
        raise ArchivoInvalido(f"El CSV tiene demasiadas filas (máximo {MAX_FILAS_CSV}).")
    primera = next(csv.reader(io.StringIO(texto.lstrip("\ufeff"))), [])
    if len(primera) > MAX_COLUMNAS_CSV:
        raise ArchivoInvalido(f"El CSV tiene demasiadas columnas (máximo {MAX_COLUMNAS_CSV}).")


def celda_csv(valor):
    """
    Neutraliza "CSV injection" al EXPORTAR: si una celda empieza por = + - @ (o tab / retorno),
    Excel la ejecutaría como fórmula. Se antepone un apóstrofo para que se vea como texto.
    """
    s = "" if valor is None else str(valor)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s
