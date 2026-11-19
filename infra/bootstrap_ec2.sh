#!/usr/bin/env bash
# Preparación y HARDENING del servidor Ubuntu 24.04 en AWS (EC2).
# Ejecutar UNA vez como:  sudo bash infra/bootstrap_ec2.sh
set -euo pipefail

echo "== 1. Actualizaciones del sistema =="
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get -y upgrade
DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl git ufw fail2ban unattended-upgrades

echo "== 2. Actualizaciones de seguridad automáticas =="
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

echo "== 3. Docker Engine (repositorio oficial) =="
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
# Rotación de logs de contenedores: evita que los logs llenen el disco
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
EOF
systemctl restart docker
systemctl enable docker

echo "== 4. Cuenta de servicio no privilegiada 'plataforma' =="
id plataforma >/dev/null 2>&1 || useradd -m -s /bin/bash plataforma
usermod -aG docker plataforma          # puede manejar contenedores, pero NO tiene sudo
mkdir -p /opt/agroanalisis
chown plataforma:plataforma /opt/agroanalisis
chmod 750 /opt/agroanalisis

echo "== 5. SSH endurecido: sin root y solo con llave =="
cat > /etc/ssh/sshd_config.d/99-hardening.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
MaxAuthTries 3
X11Forwarding no
EOF
systemctl restart ssh

echo "== 6. Firewall del sistema operativo (UFW) =="
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw --force enable

echo "== 7. fail2ban: bloquea IPs que fallan el login SSH =="
systemctl enable --now fail2ban

echo "== 8. Servicios innecesarios =="
for s in cups avahi-daemon bluetooth ModemManager; do
  systemctl disable --now "$s" 2>/dev/null && echo "  deshabilitado $s" || true
done

echo
echo "Listo. Siguiente paso (como usuario plataforma):"
echo "  sudo -iu plataforma"
echo "  git clone <URL-del-repo> /opt/agroanalisis && cd /opt/agroanalisis"
echo "  ./scripts/generar_env.sh && docker compose up -d --build && ./scripts/crear_usuarios_demo.sh"
