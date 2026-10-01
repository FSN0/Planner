#!/bin/bash
set -euo pipefail

# =============================================================================
# SignaPlan - Provisioning completo de servidor Ubuntu 24.04+
# =============================================================================
# Ejecutar como root en un servidor nuevo:
#   curl -sSL <url-raw-de-este-script> | bash
#   o bien: bash scripts/setup-server.sh
#
# Requisitos previos:
#   - Ubuntu 24.04+ recién instalado
#   - Acceso root (o sudo)
#   - Clave SSH ya copiada al servidor (ssh-copy-id)
# =============================================================================

APP_USER="deployer"
APP_DIR="/opt/saas"
REPO_URL="git@github.com:FSN0/Planner.git"
REPO_BRANCH="VERSION_SAAS"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_step() { echo -e "\n${GREEN}[$(date +%H:%M:%S)] ▶ $1${NC}"; }
print_warn() { echo -e "${YELLOW}⚠ $1${NC}"; }

# --- Verificación de root ---
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}Este script debe ejecutarse como root${NC}"
    exit 1
fi

echo -e "${GREEN}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║        SignaPlan - Setup Servidor de Producción           ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# =============================================================================
# 1. ACTUALIZACIÓN DEL SISTEMA
# =============================================================================
print_step "Actualizando sistema operativo..."
apt update && apt upgrade -y
apt autoremove -y

# =============================================================================
# 2. SECURIZACIÓN SSH
# =============================================================================
print_step "Securizando SSH..."
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config
systemctl restart sshd

# =============================================================================
# 3. FIREWALL (UFW) + FAIL2BAN
# =============================================================================
print_step "Configurando Firewall y Fail2ban..."
apt install -y ufw fail2ban

systemctl enable fail2ban
systemctl start fail2ban

ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
echo "y" | ufw enable

# =============================================================================
# 4. INSTALAR DOCKER
# =============================================================================
print_step "Instalando Docker..."
apt-get install -y ca-certificates curl gnupg

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Symlink para compatibilidad con docker-compose
ln -sf /usr/libexec/docker/cli-plugins/docker-compose /usr/local/bin/docker-compose

# =============================================================================
# 5. CREAR USUARIO DEPLOYER
# =============================================================================
print_step "Configurando usuario '$APP_USER'..."
if ! id "$APP_USER" &>/dev/null; then
    adduser --disabled-password --gecos "" "$APP_USER"
fi
usermod -aG docker "$APP_USER"

# Copiar claves SSH de root al deployer
if [ ! -d "/home/$APP_USER/.ssh" ]; then
    mkdir -p /home/$APP_USER/.ssh
    cp /root/.ssh/authorized_keys /home/$APP_USER/.ssh/
    chown -R $APP_USER:$APP_USER /home/$APP_USER/.ssh
    chmod 700 /home/$APP_USER/.ssh
    chmod 600 /home/$APP_USER/.ssh/authorized_keys
fi

# =============================================================================
# 6. PREPARAR DIRECTORIO DE LA APLICACIÓN
# =============================================================================
print_step "Preparando directorio de la aplicación..."
mkdir -p "$APP_DIR"
chown -R $APP_USER:$APP_USER "$APP_DIR"

# =============================================================================
# 7. GENERAR CLAVE SSH PARA GIT (si no existe)
# =============================================================================
print_step "Verificando clave SSH para Git..."
SSH_KEY="/home/$APP_USER/.ssh/id_ed25519"
if [ ! -f "$SSH_KEY" ]; then
    su - $APP_USER -c "ssh-keygen -t ed25519 -C 'vps-produccion' -f ~/.ssh/id_ed25519 -N ''"
    echo ""
    echo -e "${YELLOW}════════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  ACCIÓN REQUERIDA: Añade esta clave como Deploy Key en GitHub${NC}"
    echo -e "${YELLOW}════════════════════════════════════════════════════════════${NC}"
    echo ""
    cat "$SSH_KEY.pub"
    echo ""
fi

# =============================================================================
# 8. INSTALAR UTILIDADES
# =============================================================================
print_step "Instalando utilidades..."
apt install -y htop ncdu logrotate

# Configurar logrotate para Docker
cat > /etc/logrotate.d/docker-containers <<'LOGROTATE'
/var/lib/docker/containers/*/*.log {
    rotate 7
    daily
    compress
    missingok
    delaycompress
    copytruncate
    maxsize 50M
}
LOGROTATE

# =============================================================================
# 9. CONFIGURAR SWAP (2GB para servidores con poca RAM)
# =============================================================================
print_step "Configurando swap..."
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    sysctl vm.swappiness=10
    echo 'vm.swappiness=10' >> /etc/sysctl.conf
fi

# =============================================================================
# 10. RESUMEN
# =============================================================================
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           ✓ SERVIDOR CONFIGURADO CORRECTAMENTE            ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Próximos pasos:"
echo "  1. Añade la clave SSH pública como Deploy Key en GitHub"
echo "  2. Conéctate como deployer:"
echo "       ssh $APP_USER@$(hostname -I | awk '{print $1}')"
echo "  3. Clona el repositorio:"
echo "       cd $APP_DIR && git clone -b $REPO_BRANCH $REPO_URL ."
echo "  4. Configura el entorno:"
echo "       cp .env.production.example .env && nano .env"
echo "  5. Despliega:"
echo "       make prod-deploy"
echo ""
echo "  DNS: Configura en tu proveedor:"
echo "       signaplan.com     -> A -> $(hostname -I | awk '{print $1}')"
echo "       *.signaplan.com   -> A -> $(hostname -I | awk '{print $1}')"
echo ""
