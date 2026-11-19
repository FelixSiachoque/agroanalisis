"""Funciones de procesamiento. Reciben la ruta del archivo y devuelven un dict con el resultado."""
import csv
import hashlib
import re
from collections import Counter


def sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(65536), b""):
            h.update(bloque)
    return h.hexdigest()


def procesar_txt(ruta):
    """Informe de texto: líneas, palabras, caracteres y palabras más frecuentes."""
    with open(ruta, encoding="utf-8") as f:
        texto = f.read()
    lineas = texto.splitlines()
    palabras = re.findall(r"\w+", texto.lower())
    frecuentes = Counter(p for p in palabras if len(p) > 3).most_common(10)
    return {
        "tipo": "informe_texto",
        "sha256": sha256(ruta),
        "lineas": len(lineas),
        "lineas_vacias": sum(1 for l in lineas if not l.strip()),
        "palabras": len(palabras),
        "caracteres": len(texto),
        "palabras_frecuentes": [{"palabra": p, "veces": n} for p, n in frecuentes],
    }


def clasificar_ph(valor):
    if valor < 6.5:
        return "acido"
    if valor <= 7.5:
        return "neutro"
    return "alcalino"


def procesar_csv(ruta):
    """
    Resultados de laboratorio en CSV.
    Valida la estructura (encabezado y mismo número de columnas en cada fila),
    calcula estadísticas de cada columna numérica y, si existe la columna 'ph',
    clasifica las muestras en ácidas / neutras / alcalinas.
    """
    with open(ruta, encoding="utf-8", newline="") as f:
        filas = list(csv.reader(f))
    if len(filas) < 2:
        raise ValueError("El CSV debe tener encabezado y al menos una fila de datos")
    encabezado = [c.strip().lower() for c in filas[0]]
    datos = filas[1:]
    for i, fila in enumerate(datos, start=2):
        if len(fila) != len(encabezado):
            raise ValueError(f"Fila {i}: tiene {len(fila)} columnas y el encabezado tiene {len(encabezado)}")

    estadisticas = {}
    for j, col in enumerate(encabezado):
        try:
            valores = [float(f[j].replace(",", ".")) for f in datos if f[j].strip() != ""]
        except ValueError:
            continue                      # columna de texto: se omite
        if valores:
            estadisticas[col] = {
                "conteo": len(valores),
                "minimo": round(min(valores), 3),
                "maximo": round(max(valores), 3),
                "promedio": round(sum(valores) / len(valores), 3),
            }

    resultado = {
        "tipo": "resultados_laboratorio",
        "sha256": sha256(ruta),
        "filas": len(datos),
        "columnas": encabezado,
        "estadisticas": estadisticas,
    }
    if "ph" in encabezado:
        j = encabezado.index("ph")
        clases = Counter(clasificar_ph(float(f[j].replace(",", "."))) for f in datos if f[j].strip())
        resultado["clasificacion_ph"] = dict(clases)
    return resultado


PROCESADORES = {"txt": procesar_txt, "csv": procesar_csv}
