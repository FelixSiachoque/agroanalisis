"""
Genera la carga de prueba propia del grupo (datos 100 % sintéticos, sin información personal real).
Uso: python3 datos_prueba/generar_datos.py
Siempre genera los mismos archivos (semilla fija) para que las pruebas sean reproducibles.
"""
import os
import random

random.seed(2026)
D = os.path.dirname(os.path.abspath(__file__))
FINCAS = ["El Mirador", "La Esperanza", "Los Alisos", "San Isidro", "El Volcán", "La Laguna", "Monquirá", "Pantanitos"]
CULTIVOS = ["papa", "cebolla larga", "arveja", "maíz", "haba", "pasto kikuyo"]


def escribir(nombre, contenido, modo="w"):
    with open(os.path.join(D, nombre), modo, **({} if "b" in modo else {"encoding": "utf-8", "newline": ""})) as f:
        f.write(contenido)


def suelos(n, lote):
    filas = ["muestra,finca,cultivo,ph,materia_organica_pct,nitrogeno_ppm,fosforo_ppm,potasio_ppm"]
    for i in range(1, n + 1):
        filas.append(f"{lote}-{i:04d},{random.choice(FINCAS)},{random.choice(CULTIVOS)},"
                     f"{random.uniform(4.6, 8.2):.2f},{random.uniform(1.5, 12):.2f},"
                     f"{random.randint(10, 90)},{random.randint(5, 60)},{random.randint(60, 400)}")
    return "\n".join(filas) + "\n"


# 1. CSV pequeño (25 muestras)
escribir("01_suelos_lote_A.csv", suelos(25, "A"))
# 2. CSV mediano (2 000 muestras)
escribir("02_suelos_lote_B.csv", suelos(2000, "B"))
# 3. CSV de lluvias mensuales
lluvia = ["mes,precipitacion_mm,dias_lluvia,temperatura_media_c"]
for m in ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]:
    lluvia.append(f"{m},{random.uniform(20, 180):.1f},{random.randint(3, 22)},{random.uniform(11, 16):.1f}")
escribir("03_lluvias_2026.csv", "\n".join(lluvia) + "\n")

# 4. Informe de visita de campo (texto corto)
escribir("04_informe_visita_campo.txt", """INFORME DE VISITA DE CAMPO - LABORATORIO AGROANÁLISIS SUGAMUXI
Finca: La Esperanza (vereda ficticia Pantanitos)
Técnico: tecnico1

Se tomaron doce muestras de suelo en el lote sembrado con papa.
El suelo presenta coloración oscura y buena cantidad de materia orgánica.
En la parte baja del lote se observa encharcamiento después de lluvias fuertes.
Se recomienda revisar el drenaje y repetir el análisis de pH en tres meses.

Observaciones:
- Las muestras se rotularon con el prefijo A.
- El agricultor reporta uso de abono orgánico desde hace dos años.
- No se observaron plagas en el momento de la visita.

Próxima visita: dentro de noventa días.
""")

# 5. Bitácora del laboratorio (texto largo, ~3 000 líneas)
eventos = ["calibración del pHmetro", "recepción de muestras", "secado de muestras", "tamizado",
           "lectura de fósforo", "lectura de potasio", "limpieza del equipo", "registro de resultados"]
lineas = [f"2026-{random.randint(1, 10):02d}-{random.randint(1, 28):02d} {random.randint(7, 17):02d}:{random.randint(0, 59):02d} "
          f"{random.choice(eventos)} lote {random.choice('ABCD')} sin novedad" for _ in range(3000)]
escribir("05_bitacora_laboratorio.txt", "\n".join(lineas) + "\n")

# --- Archivos que DEBEN fallar o ser rechazados (pruebas negativas) ---
# 6. CSV mal formado: se acepta, pero el worker lo marca como FALLIDO
escribir("06_invalido_columnas.csv", "muestra,ph,potasio\nC-1,6.1,120\nC-2,5.8\nC-3,7.0,98\n")
# 7. Extensión no permitida: la app lo RECHAZA
escribir("07_invalido_programa.exe", "esto no es un programa real, solo prueba la politica de extensiones\n")
# 8. Binario disfrazado de .txt: la app lo RECHAZA
escribir("08_invalido_binario.txt", bytes([0x89, 0x50, 0x4E, 0x47, 0x00, 0x00, 0x1A, 0x0A]) * 64, "wb")
# 9. Archivo de 3 MB (supera el límite de 2 MB): la app lo RECHAZA. No se versiona (está en .gitignore).
escribir("archivo_grande.txt", ("x" * 99 + "\n") * 31000)

for f in sorted(os.listdir(D)):
    if f != "generar_datos.py" and not f.endswith(".md"):
        print(f"{f:32s} {os.path.getsize(os.path.join(D, f)):>10,d} bytes")
