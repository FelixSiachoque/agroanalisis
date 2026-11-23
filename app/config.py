"""
Configuración de la aplicación (todo sale de variables de entorno del .env).
Los parámetros de las REGLAS DE NEGOCIO no están aquí: están en reglas_negocio.py.
"""
import os

DATA_DIR = os.environ.get("DATA_DIR", "/data")

# Política técnica de archivos (validacion.py)
MAX_MB = float(os.environ.get("MAX_MB", "2"))
MAX_BYTES = int(MAX_MB * 1024 * 1024)
EXTENSIONES_PERMITIDAS = {"txt", "csv"}
MAX_FILAS_CSV = int(os.environ.get("MAX_FILAS_CSV", "50000"))
MAX_COLUMNAS_CSV = int(os.environ.get("MAX_COLUMNAS_CSV", "100"))
MAX_NOMBRE_ARCHIVO = 120

# Sesión
SECRET_KEY = os.environ["SECRET_KEY"]                       # viene de .env, nunca del código
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"  # 1 solo si hay HTTPS

# Conexión a PostgreSQL con el usuario de MÍNIMO PRIVILEGIO de la app (agro_web), no el superusuario
DB_DSN = (
    f"host={os.environ.get('DB_HOST', 'db')} port={os.environ.get('DB_PORT', '5432')} "
    f"dbname={os.environ['POSTGRES_DB']} user={os.environ['DB_USER']} "
    f"password={os.environ['DB_PASSWORD']}"
)

# Un worker se considera caído si no da señal de vida en este tiempo (panel de Recursos)
LATIDO_CADUCO_S = int(os.environ.get("LATIDO_CADUCO_S", "60"))

# Dónde corre la plataforma (lo escribe scripts/detectar_entorno.sh en el .env); se muestra en el pie de página
ENTORNO = os.environ.get("ENTORNO", "Local")
