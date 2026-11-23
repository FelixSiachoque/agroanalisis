#!/usr/bin/env bash
# Evidencia de LOGS (requisito 2.4): provoca un error de procesamiento y un archivo rechazado,
# y muestra cómo quedan registrados en los logs del worker y de la app.
# Uso (en el servidor, como plataforma, en /opt/agroanalisis):  ./scripts/logs_evidencia.sh
set -uo pipefail
cd "$(dirname "$0")/.."
export CLAVE_DEMO=$(grep '^DEMO_PASSWORD=' .env | cut -d= -f2-)

python3 - <<'EOF'
import os, re, time, requests
URL = "http://localhost"
s = requests.Session()
token = lambda html: re.search(r'name="csrf" value="([^"]+)"', html).group(1)
r = s.get(f"{URL}/login")
s.post(f"{URL}/login", data={"usuario": "tecnico1", "clave": os.environ["CLAVE_DEMO"], "csrf": token(r.text)})
for nombre in ("06_invalido_columnas.csv", "07_invalido_programa.exe"):
    pagina = s.get(f"{URL}/")
    with open(f"datos_prueba/{nombre}", "rb") as f:
        s.post(f"{URL}/subir", data={"csrf": token(pagina.text)}, files={"archivo": (nombre, f)})
    print("Enviado:", nombre)
time.sleep(8)
EOF

echo
echo "== docker compose logs worker  (errores de procesamiento)"
docker compose logs --no-log-prefix --since 2m worker | grep -E "inicia|FALLIDO|completado|Recuperad" | tail -6
echo
echo "== docker compose logs app  (archivo rechazado por la política)"
docker compose logs --no-log-prefix --since 2m app | grep -E "archivo_rechazado|subir" | tail -4
