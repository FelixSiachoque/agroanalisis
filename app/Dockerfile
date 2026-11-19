FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Usuario sin privilegios (UID fijo 10001, sin shell de login)
RUN groupadd -g 10001 app && useradd -u 10001 -g app -M -s /usr/sbin/nologin app \
 && mkdir -p /data && chown app:app /data && chmod 700 /data

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# El código queda de root y solo lectura para 'app': si alguien compromete la app, no puede modificarlo
COPY . .

USER app
EXPOSE 5000
CMD ["gunicorn", "--workers", "2", "--bind", "0.0.0.0:5000", "--worker-tmp-dir", "/tmp", "--access-logfile", "-", "app:app"]
