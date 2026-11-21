#!/usr/bin/env bash
# Crea la infraestructura en AWS Academy desde la terminal del Learner Lab (AWS CLI ya configurado):
#   par de llaves, security group (22 solo desde la IP de administración, 80 abierto) e instancia EC2
#   Ubuntu 24.04 que se configura sola con infra/user_data.sh.
# Uso:  bash crear_infra_aws.sh            (ADMIN_IPS="1.2.3.4/32 5.6.7.8/32" para autorizar más IPs a SSH)
set -euo pipefail
NOMBRE=agroanalisis
# t3.small (2 GB) recomendado; t2.micro (1 GB) también funciona con los límites de docker-compose.yml (832 MB)
TIPO=${TIPO:-t3.small}
MI_IP=$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')
if ! [[ "$MI_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "No se pudo averiguar la IP pública de administración (resultado: '$MI_IP')"; exit 1
fi
ADMIN_IPS=${ADMIN_IPS:-"$MI_IP/32"}

echo "== AMI oficial de Ubuntu 24.04 (Canonical)"
AMI=$(aws ec2 describe-images --owners 099720109477 \
  --filters "Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*" "Name=state,Values=available" \
  --query 'sort_by(Images,&CreationDate)[-1].ImageId' --output text)
echo "   $AMI"

echo "== Par de llaves SSH"
if [ ! -f ~/$NOMBRE-key.pem ]; then
  aws ec2 delete-key-pair --key-name $NOMBRE-key 2>/dev/null || true
  aws ec2 create-key-pair --key-name $NOMBRE-key --query KeyMaterial --output text > ~/$NOMBRE-key.pem
  chmod 400 ~/$NOMBRE-key.pem
fi
echo "   ~/$NOMBRE-key.pem"

echo "== Security group"
VPC=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
SG=$(aws ec2 describe-security-groups --filters Name=group-name,Values=$NOMBRE-sg Name=vpc-id,Values=$VPC \
     --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo None)
if [ "$SG" = "None" ]; then
  SG=$(aws ec2 create-security-group --group-name $NOMBRE-sg --vpc-id "$VPC" \
       --description "AgroAnalisis: SSH solo administracion, HTTP publico" --query GroupId --output text)
  aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port 80 --cidr 0.0.0.0/0 > /dev/null
fi
for ip in $ADMIN_IPS; do
  aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port 22 --cidr "$ip" > /dev/null 2>&1     || echo "   (la regla SSH para $ip ya existía)"
done
echo "   $SG  (22 desde: $ADMIN_IPS; 80 desde: 0.0.0.0/0)"

echo "== Instancia EC2 ($TIPO)"
curl -fsS -o /tmp/user_data.sh https://raw.githubusercontent.com/FelixSiachoque/agroanalisis/main/infra/user_data.sh
grep -q "bootstrap_ec2.sh" /tmp/user_data.sh || { echo "user_data.sh descargado no es válido"; exit 1; }
ID=$(aws ec2 run-instances --image-id "$AMI" --instance-type "$TIPO" --key-name $NOMBRE-key \
  --security-group-ids "$SG" --user-data file:///tmp/user_data.sh \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":20,"VolumeType":"gp3","Encrypted":true}}]' \
  --metadata-options HttpTokens=required,HttpEndpoint=enabled \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NOMBRE}]" \
  --query 'Instances[0].InstanceId' --output text)
aws ec2 wait instance-running --instance-ids "$ID"
IP=$(aws ec2 describe-instances --instance-ids "$ID" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)

echo
echo "LISTO: instancia $ID  IP pública $IP"
echo "La configuración automática tarda unos 5-8 minutos. Para seguirla:"
echo "  ssh -i ~/$NOMBRE-key.pem ubuntu@$IP 'sudo tail -f /var/log/agroanalisis-setup.log'"
echo "Luego abra http://$IP"
