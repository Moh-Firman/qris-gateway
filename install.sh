#!/bin/bash
# QRIS Gateway - Installer otomatis dengan custom domain
# Usage: curl -fsSL https://raw.githubusercontent.com/Moh-Firman/qris-gateway/main/install.sh | sudo bash
set -e

echo "==================================="
echo "  QRIS Gateway - Auto Installer"
echo "==================================="
echo ""

# --- Tanya domain ---
read -p "Masukkan domain (misal: eg.domain.com) [kosongkan jika pakai IP saja]: " DOMAIN
DOMAIN=$(echo "$DOMAIN" | xargs) # trim

if [ -n "$DOMAIN" ]; then
  echo ""
  echo "Pastikan DNS A record untuk $DOMAIN sudah mengarah ke IP VPS ini."
  read -p "DNS sudah disetting? (y/n): " DNS_OK
  if [ "$DNS_OK" != "y" ] && [ "$DNS_OK" != "Y" ]; then
    echo "Setting dulu DNS-nya, lalu jalankan ulang installer ini."
    exit 1
  fi
fi

echo ""
echo "[1/5] Update sistem & install dependensi..."
apt update -qq && apt install -y -qq python3 git curl debian-keyring debian-archive-keyring apt-transport-https > /dev/null 2>&1
echo "      OK"

echo "[2/5] Download QRIS Gateway..."
rm -rf /tmp/qris-src
git clone -q https://github.com/Moh-Firman/qris-gateway.git /tmp/qris-src
mkdir -p /opt/gateway/static
cp /tmp/qris-src/gateway.py /opt/gateway/
cp -r /tmp/qris-src/static/. /opt/gateway/static/
echo "      OK"

echo "[3/5] Install systemd service..."
cp /tmp/qris-src/qris-gateway.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable -q qris-gateway
systemctl restart qris-gateway
sleep 2
echo "      OK"

# --- Setup domain + HTTPS via Caddy ---
if [ -n "$DOMAIN" ]; then
  echo "[4/5] Install Caddy & setup HTTPS untuk $DOMAIN..."
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg > /dev/null 2>&1
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null
  apt update -qq && apt install -y -qq caddy > /dev/null 2>&1

  cat > /etc/caddy/Caddyfile << EOF
$DOMAIN {
    reverse_proxy localhost:8090
}
EOF
  systemctl reload caddy
  echo "      OK — HTTPS otomatis via Let's Encrypt"

  BASE_URL="https://$DOMAIN"
else
  echo "[4/5] Skip setup domain (pakai IP publik)"
  BASE_URL="http://$(curl -s -m 5 ifconfig.me 2>/dev/null || echo '<IP-VPS>'):8090"
fi

echo "[5/5] Verifikasi..."
sleep 2
if curl -s -m 5 http://localhost:8090/health > /dev/null 2>&1 || curl -s -m 5 http://localhost:8090/api/health > /dev/null 2>&1; then
  echo "      Gateway jalan OK"
else
  echo "      WARNING: gateway tidak merespon, cek: systemctl status qris-gateway"
fi

echo ""
echo "==================================="
echo "  Instalasi selesai!"
echo "==================================="
echo "  Dashboard : $BASE_URL"
echo "  API docs  : $BASE_URL (otomatis pakai domain ini)"
echo "  Login     : admin / admin123  (SEGERA GANTI!)"
if [ -n "$DOMAIN" ]; then
  echo "  Webhook APK: $BASE_URL/api/mutasi_notify"
fi
echo "==================================="
