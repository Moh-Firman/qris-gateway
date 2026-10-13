# QRIS Gateway

Gateway pembayaran QRIS otomatis untuk Indonesia. Buat kode QRIS dinamis dengan kode unik, deteksi pembayaran otomatis, kelola via dashboard web.

## Arsitektur

- **Backend**: Python (Flask-style, stdlib `http.server`) — `gateway.py`
- **Frontend**: Single-page app — `static/index.html`
- **Database**: SQLite (`/opt/gateway/gateway.db`)
- **Deploy**: systemd service di VPS, reverse proxy via Caddy/Cloudflare

## Fitur

- QRIS dinamis dengan kode unik 3 digit untuk deteksi otomatis
- QRIS statis (khusus admin, via upload foto)
- Auto-expire: pending >30 menit otomatis kadaluarsa
- Dashboard: KPI, chart volume 7 hari, distribusi status
- Profil: nama merchant, QRIS statis pribadi
- Dokumentasi API lengkap (7 endpoint, contoh cURL/JS/Python/PHP)
- Role: admin lihat semua, non-admin akses ditolak

## Instalasi di VPS

```bash
# 1. Clone
git clone https://github.com/Moh-Firman/qris-gateway.git /opt/gateway-src
mkdir -p /opt/gateway/static
cp /opt/gateway-src/gateway.py /opt/gateway/
cp /opt/gateway-src/static/index.html /opt/gateway/static/

# 2. Install systemd service
cp /opt/gateway-src/qris-gateway.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now qris-gateway

# 3. Reverse proxy (contoh Caddy)
# gateway.example.com {
#   reverse_proxy localhost:8090
# }
```

## Konfigurasi

Setelah jalan, login sebagai admin dan atur via UI atau API:

| Key | Keterangan |
|-----|-----------|
| `qris_static` | String QRIS statis (via upload foto di UI) |
| `gateway_name` | Nama gateway tampil di dashboard |

User admin pertama dibuat otomatis saat init DB (cek `init_db()` di `gateway.py`).

## API

Base URL: `https://gateway.example.com/api`

Semua endpoint: `POST /api/<nama>` dengan JSON body. Endpoint web memakai cookie session; endpoint `internal_*` memakai `secret`.

Lihat dokumentasi lengkap di halaman web setelah login (7 endpoint + contoh kode).

## Lisensi

MIT
