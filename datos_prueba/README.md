# Carga de prueba propia

Son datos 100 % sintéticos, sin información personal real. Se regeneran idénticos con `python3 datos_prueba/generar_datos.py` porque el script usa una semilla fija.

| # | Archivo | Tipo | Tamaño | Contenido | Resultado esperado |
|---|---------|------|--------|-----------|--------------------|
| 1 | 01_suelos_lote_A.csv | CSV | 1,2 KB | 25 análisis de suelo (pH, materia orgánica, N, P, K) | completado, con clasificación de pH |
| 2 | 02_suelos_lote_B.csv | CSV | 91 KB | 2 000 análisis de suelo | completado |
| 3 | 03_lluvias_2026.csv | CSV | 0,3 KB | Lluvia y temperatura por mes | completado (sin pH) |
| 4 | 04_informe_visita_campo.txt | TXT | 0,6 KB | Informe de visita de un técnico | completado: líneas, palabras, frecuencias |
| 5 | 05_bitacora_laboratorio.txt | TXT | 163 KB | 3 000 líneas de bitácora | completado |
| 6 | 06_invalido_columnas.csv | CSV | 50 B | La fila 3 tiene una columna de menos | **fallido** (lo detecta el worker) |
| 7 | 07_invalido_programa.exe | EXE | 68 B | Texto con extensión no permitida | **rechazado** al subir |
| 8 | 08_invalido_binario.txt | TXT | 512 B | Bytes binarios con extensión .txt | **rechazado** al subir |
| 9 | archivo_grande.txt | TXT | 3,0 MB | Supera el límite de 2 MB (no se versiona) | **rechazado** al subir |
