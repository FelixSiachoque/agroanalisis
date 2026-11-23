#!/usr/bin/env bash
# Instala en AWS CloudShell el comando "entrar", que deja al usuario dentro del servidor en un solo paso.
# Se ejecuta UNA vez en CloudShell (queda guardado en ~/.bashrc, que CloudShell conserva entre sesiones):
#   curl -sO https://raw.githubusercontent.com/FelixSiachoque/agroanalisis/main/scripts/instalar_entrar_cloudshell.sh
#   bash instalar_entrar_cloudshell.sh && source ~/.bashrc
#
# Comandos que instala:
#   abrir_ssh  1. Si la instancia "agroanalisis" está detenida, la enciende y espera.
#              2. Autoriza el puerto 22 SOLO para la IP actual de CloudShell (cambia en cada sesión) y borra las IPs viejas.
#              Después se entra a mano mostrando la llave:  ssh -i ~/agroanalisis-key.pem ubuntu@34.200.132.2
#   entrar     abrir_ssh + entra por SSH y abre una terminal como "plataforma" en /opt/agroanalisis.
# Además habilita el plan B: el botón "Conectar → EC2 Instance Connect" de la consola de EC2.
set -euo pipefail

# --- Llave y alias SSH (si no existen) ---
[ -f ~/agroanalisis-key.pem ] || { echo "Falta ~/agroanalisis-key.pem en CloudShell"; exit 1; }
mkdir -p ~/.ssh && chmod 700 ~/.ssh
if ! grep -q "^Host agro$" ~/.ssh/config 2>/dev/null; then
  cat >> ~/.ssh/config <<'EOF'
Host agro
  HostName 34.200.132.2
  User ubuntu
  IdentityFile ~/agroanalisis-key.pem
  StrictHostKeyChecking accept-new
  ServerAliveInterval 30
  ConnectTimeout 10
EOF
  chmod 600 ~/.ssh/config
fi

# --- Comando "entrar" ---
sed -i '/# >>> agroanalisis entrar >>>/,/# <<< agroanalisis entrar <<</d' ~/.bashrc
cat >> ~/.bashrc <<'EOF'
# >>> agroanalisis entrar >>>
abrir_ssh() {
  local SG ID ESTADO IP viejo
  SG=$(aws ec2 describe-security-groups --filters Name=group-name,Values=agroanalisis-sg \
        --query 'SecurityGroups[0].GroupId' --output text)
  ID=$(aws ec2 describe-instances --filters Name=tag:Name,Values=agroanalisis \
        Name=instance-state-name,Values=pending,running,stopping,stopped \
        --query 'Reservations[0].Instances[0].InstanceId' --output text)
  ESTADO=$(aws ec2 describe-instances --instance-ids "$ID" --query 'Reservations[0].Instances[0].State.Name' --output text)
  if [ "$ESTADO" != "running" ]; then
    echo "La instancia está '$ESTADO': encendiéndola (1-2 minutos)..."
    aws ec2 start-instances --instance-ids "$ID" > /dev/null 2>&1 || true
    aws ec2 wait instance-running --instance-ids "$ID"; sleep 25
  fi
  IP="$(curl -s https://checkip.amazonaws.com)/32"
  for viejo in $(aws ec2 describe-security-groups --group-ids "$SG" \
                 --query 'SecurityGroups[0].IpPermissions[?FromPort==`22`].IpRanges[].CidrIp' --output text); do
    [ "$viejo" != "$IP" ] && aws ec2 revoke-security-group-ingress --group-id "$SG" --protocol tcp --port 22 --cidr "$viejo" > /dev/null 2>&1
  done
  aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port 22 --cidr "$IP" > /dev/null 2>&1 || true
  echo "SSH autorizado solo para $IP (puerto 22)."
}
entrar() {
  abrir_ssh || return
  echo "Entrando al servidor como 'plataforma'..."
  ssh -t agro 'sudo -iu plataforma bash -c "cd /opt/agroanalisis && exec bash"'
}
# <<< agroanalisis entrar <<<
EOF

# --- Plan B: EC2 Instance Connect (botón "Conectar" de la consola) ---
SG=$(aws ec2 describe-security-groups --filters Name=group-name,Values=agroanalisis-sg --query 'SecurityGroups[0].GroupId' --output text)
PL=$(aws ec2 describe-managed-prefix-lists --filters "Name=prefix-list-name,Values=com.amazonaws.$(aws configure get region || echo us-east-1).ec2-instance-connect" \
      --query 'PrefixLists[0].PrefixListId' --output text)
aws ec2 authorize-security-group-ingress --group-id "$SG" \
  --ip-permissions "IpProtocol=tcp,FromPort=22,ToPort=22,PrefixListIds=[{PrefixListId=$PL,Description=EC2-Instance-Connect}]" > /dev/null 2>&1 || true
echo "Listo. Ejecute:  source ~/.bashrc   y luego:  abrir_ssh  (o  entrar  para el atajo)"
echo "Plan B: consola EC2 → instancia agroanalisis → Conectar → EC2 Instance Connect (usuario ubuntu)."
