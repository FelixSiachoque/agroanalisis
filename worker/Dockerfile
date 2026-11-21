FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
# Imagen base fijada por digest (reproducible). Actualizar: docker buildx imagetools inspect python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Mismo UID que la app (10001) para que ambos puedan leer/escribir el volumen /data
RUN groupadd -g 10001 app && useradd -u 10001 -g app -M -s /usr/sbin/nologin app \
 && mkdir -p /data && chown app:app /data && chmod 700 /data

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

USER app
CMD ["python", "worker.py"]
