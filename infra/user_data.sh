#!/bin/bash
# Script de primer arranque de la instancia EC2 (user data).
# Lo ejecuta cloud-init como root UNA sola vez. Log: /var/log/agroanalisis-setup.log
set -euxo pipefail
exec > /var/log/agroanalisis-setup.log 2>&1

REPO=https://github.com/FelixSiachoque/agroanalisis

# 1. Hardening del sistema e instalación de Docker
git clone --depth 1 "$REPO" /tmp/agro-bootstrap
bash /tmp/agro-bootstrap/infra/bootstrap_ec2.sh

# 2. Despliegue como usuario sin privilegios 'plataforma'
sudo -iu plataforma bash -c "
  set -e
  git clone $REPO /opt/agroanalisis
  cd /opt/agroanalisis
  ./scripts/generar_env.sh > /home/plataforma/credenciales.txt
  chmod 600 /home/plataforma/credenciales.txt
  python3 datos_prueba/generar_datos.py > /dev/null
  docker compose up -d --build --wait
  ./scripts/crear_usuarios_demo.sh
"
echo "DESPLIEGUE TERMINADO"
