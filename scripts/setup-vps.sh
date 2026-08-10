#!/usr/bin/env bash
# ============================================================
# Staykaro AI Caller — VPS Provisioning Script
# NH-05: One-time setup on a fresh Ubuntu 22.04 LTS server.
#
# Run as root (or with sudo) immediately after provisioning:
#   bash scripts/setup-vps.sh
# ============================================================
set -euo pipefail

DEPLOY_USER="deploy"
APP_DIR="/opt/staykaro"

log()   { echo -e "\033[36m[$(date '+%H:%M:%S')]\033[0m $*"; }
ok()    { echo -e "\033[32m[OK]\033[0m $*"; }
error() { echo -e "\033[31m[ERROR]\033[0m $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || error "Run this script as root or with sudo."

# ── 1. Verify Ubuntu ─────────────────────────────────────────
. /etc/os-release
[[ "$ID" == "ubuntu" ]] || error "This script targets Ubuntu. Detected: $ID"
log "Ubuntu $VERSION_ID detected."

# ── 2. System update ─────────────────────────────────────────
log "Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    curl wget git unzip \
    ca-certificates gnupg lsb-release \
    ufw fail2ban

# ── 3. Install Docker Engine ─────────────────────────────────
log "Installing Docker Engine..."
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    | tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update -qq
apt-get install -y -qq \
    docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin

systemctl enable docker
systemctl start docker
ok "Docker $(docker --version) installed."

# ── 4. Create deploy user ────────────────────────────────────
log "Creating deploy user: $DEPLOY_USER"
if ! id "$DEPLOY_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$DEPLOY_USER"
fi
usermod -aG docker "$DEPLOY_USER"

# Copy root's authorized SSH keys so the deploy user can SSH in.
DEPLOY_HOME="/home/$DEPLOY_USER"
mkdir -p "$DEPLOY_HOME/.ssh"
if [ -f /root/.ssh/authorized_keys ]; then
    cp /root/.ssh/authorized_keys "$DEPLOY_HOME/.ssh/authorized_keys"
    chown -R "$DEPLOY_USER:$DEPLOY_USER" "$DEPLOY_HOME/.ssh"
    chmod 700 "$DEPLOY_HOME/.ssh"
    chmod 600 "$DEPLOY_HOME/.ssh/authorized_keys"
    ok "SSH keys copied for $DEPLOY_USER."
else
    log "No /root/.ssh/authorized_keys found. Add your public key manually:"
    log "  echo 'YOUR_PUBLIC_KEY' >> $DEPLOY_HOME/.ssh/authorized_keys"
fi

# ── 5. Firewall (UFW) ────────────────────────────────────────
log "Configuring UFW firewall..."
ufw --force reset > /dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH       # 22/tcp
ufw allow 80/tcp        # HTTP
ufw allow 443/tcp       # HTTPS (future)
ufw --force enable
ok "Firewall active. Allowed: SSH, 80, 443."

# ── 6. fail2ban ──────────────────────────────────────────────
log "Enabling fail2ban..."
systemctl enable fail2ban
systemctl start fail2ban
ok "fail2ban running."

# ── 7. Application directory ─────────────────────────────────
log "Creating application directory: $APP_DIR"
mkdir -p "$APP_DIR"
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"

# ── 8. Harden SSH ────────────────────────────────────────────
log "Hardening SSH config..."
SSHD_CONFIG="/etc/ssh/sshd_config"
# Disable root login and password auth.
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' "$SSHD_CONFIG"
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' "$SSHD_CONFIG"
sed -i 's/^#\?PubkeyAuthentication.*/PubkeyAuthentication yes/' "$SSHD_CONFIG"
systemctl reload sshd
ok "SSH hardened: root login and password auth disabled."

echo ""
echo "============================================================"
ok "VPS provisioning complete."
echo ""
echo "  Deploy user : $DEPLOY_USER"
echo "  App dir     : $APP_DIR"
echo "  Next steps  :"
echo "    1. SSH as $DEPLOY_USER: ssh $DEPLOY_USER@<server-ip>"
echo "    2. Clone the repo:     git clone <repo-url> $APP_DIR"
echo "    3. Create .env:        cp $APP_DIR/.env.production.example $APP_DIR/.env"
echo "    4. Edit .env:          nano $APP_DIR/.env"
echo "    5. Deploy:             bash $APP_DIR/scripts/deploy.sh"
echo "============================================================"
