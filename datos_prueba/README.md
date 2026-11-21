# Carga de prueba propia

Son datos 100 % sintéticos, sin información personal real. Se regeneran idénticos con `python3 datos_prueba/generar_datos.py`, porque el script usa una semilla fija. Los archivos 01–08 no cambian aunque se agreguen archivos nuevos al final del script.

## Archivos base (política técnica y procesamiento)

| # | Archivo | Tipo | Tamaño | Contenido | Resultado esperado |
|---|---------|------|--------|-----------|--------------------|
| 1 | `01_suelos_lote_A.csv` | CSV | 1,2 KB | 25 análisis de suelo (pH, materia orgánica, N, P, K) | completado, con clasificación de pH |
| 2 | `02_suelos_lote_B.csv` | CSV | 91 KB | 2 000 análisis de suelo | completado |
| 3 | `03_lluvias_2026.csv` | CSV | 0,3 KB | lluvia y temperatura por mes | completado (sin pH) |
| 4 | `04_informe_visita_campo.txt` | TXT | 0,6 KB | informe de visita de un técnico | completado: líneas, palabras, frecuencias |
| 5 | `05_bitacora_laboratorio.txt` | TXT | 163 KB | 3 000 líneas de bitácora | completado |
| 6 | `06_invalido_columnas.csv` | CSV | 50 B | la fila 3 tiene una columna de menos | **fallido** (lo detecta el worker) |
| 7 | `07_invalido_programa.exe` | EXE | 68 B | texto con extensión no permitida | **rechazado** al subir (422) |
| 8 | `08_invalido_binario.txt` | TXT | 512 B | bytes binarios con extensión .txt | **rechazado** al subir (422) |
| — | `archivo_grande.txt` | TXT | 3,0 MB | supera el límite de 2 MB (no se versiona) | **rechazado** al subir (413) |

## Sello de autenticidad (cadena de custodia)

| Archivo | Tamaño | Uso |
|---|---|---|
| `09_sello_manipular.csv` | 18 KB | Con el worker detenido, se sube, se altera dentro de `/data` con `./scripts/demo_sello.sh manipular <id>` y se inicia el worker. Resultado: **fallido · integridad_comprometida** |

## Reglas de negocio alternativas (cada una con un archivo que la cumple y otro que la viola)

| Regla | Cumple (se acepta) | Viola (se rechaza antes de la cola) |
|---|---|---|
| `cabecera_csv_obligatoria` (`lote_id,fecha,medicion`) | `10_regla_cabecera_cumple.csv` (0,6 KB) | `11_regla_cabecera_viola.csv` (67 B) → 422 |
| `rangos_agronomicos_validos` (pH 0–14, % 0–100) | `12_regla_rangos_cumple.csv` (1 KB) | `13_regla_rangos_viola.csv` (1 KB, pH = 15,30 en la fila 8) → 422 |
| `tamano_maximo_por_rol` (agricultor: 1 MB) | `04_informe_visita_campo.txt` | `14_regla_tamano_viola.txt` (1,5 MB, no se versiona) → 413 para el agricultor; aceptado para el técnico |
| `cuota_trabajos_activos` (activa) | 3 envíos seguidos de un agricultor | el 4.º envío → 409 |
| `bloquear_borrado_finalizados` (activa) | eliminar un trabajo fallido | eliminar uno completado (siendo agricultor) → 403 |
