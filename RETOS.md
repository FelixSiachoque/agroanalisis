# Retos sorpresa

Esta guía se amplió y se trasladó a **[GUIA_RETOS_SUSTENTACION.md](GUIA_RETOS_SUSTENTACION.md)**. Ahí están:

- los 6 retos, cada uno con el archivo y la función exactos (y el `grep -n` para encontrarlos), el cambio mínimo, el comando de redespliegue, las pruebas positiva y negativa, lo que debe aparecer en la auditoría y qué decir;
- el **cambio de regla de negocio de último minuto** (`app/reglas_negocio.py`);
- el kit de emergencia y el guion de 4 minutos para los 14 puntos del checklist.

Resumen de dónde se toca cada cosa:

| Reto | Archivo |
|---|---|
| 1 y 2 · Usuarios y permisos | `app/permisos.py` (diccionario `PERMISOS`) |
| 3 · Aislamiento | `app/seguridad.py` → `obtener_trabajo_autorizado()` |
| 4 · Recursos | `docker-compose.yml` → `mem_limit`, `memswap_limit`, `cpus` |
| 5 · Recuperación | `docker compose stop/kill/start worker` (lógica en `worker/worker.py`) |
| 6 · Auditoría | `auditar("accion", "detalle", recurso=...)` en `app/rutas.py` |
| Regla de negocio | `app/reglas_negocio.py` → diccionario `REGLAS` |
