# QRIS Gateway

<p align="center">
  <img src="https://raw.githubusercontent.com/Moh-Firman/qris-gateway/main/docs/profile.png" width="120" style="border-radius:50%">
</p>

<p align="center">
  <b>Gateway pembayaran QRIS otomatis untuk Indonesia</b><br>
  Buat kode QRIS dinamis, terima pembayaran otomatis, kelola semua dari dashboard web.
</p>

<p align="center">
  <a href="https://github.com/Moh-Firman/qris-gateway/raw/main/dana-notify.apk">📱 Download APK DANA Notify</a>
</p>

---

## Daftar Isi

- [Tentang](#tentang)
- [Fitur](#fitur)
- [Cara Kerja](#cara-kerja)
- [Kebutuhan](#kebutuhan)
- [Instalasi](#instalasi)
  - [1. Persiapan VPS](#1-persiapan-vps)
  - [2. Install Gateway](#2-install-gateway)
  - [3. Setup Domain & HTTPS](#3-setup-domain--https)
  - [4. Install Aplikasi DANA Notify](#4-install-aplikasi-dana-notify)
  - [5. Konfigurasi Awal](#5-konfigurasi-awal)
- [Penggunaan](#penggunaan)
  - [Buat Topup](#buat-topup)
  - [QRIS Statis](#qris-statis)
  - [Lihat Transaksi](#lihat-transaksi)
  - [Log Notifikasi](#log-notifikasi)
- [Dokumentasi API](#dokumentasi-api)
- [Keamanan](#keamanan)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [Lisensi](#lisensi)

---

## Tentang

QRIS Gateway adalah sistem pembayaran mandiri yang mengubah satu akun QRIS/DANA menjadi gateway pembayaran otomatis dengan kode unik per transaksi.

**Cocok untuk:**
- Toko online yang butuh pembayaran QRIS otomatis
- Jasa top-up / voucher
- Donasi / crowdfunding
- Sistem billing / langganan

**Tidak cocok untuk:**
- Yang butuh settlement ke banyak rekening berbeda (satu akun DANA = satu tujuan)

---

## Fitur

| Fitur | Keterangan |
|-------|-----------|
| QRIS Dinamis | Setiap transaksi dapat kode unik 3 digit untuk deteksi otomatis |
| Auto-Detect | Saldo masuk otomatis setelah bayar, tanpa konfirmasi manual |
| QRIS Statis | QR tetap untuk dipajang (khusus admin) |
| Auto-Expire | Transaksi pending >30 menit otomatis kadaluarsa |
| Dashboard | KPI, grafik volume 7 hari, distribusi status |
| Log Notifikasi | Semua notifikasi DANA tercatat dan bisa dipantau |
| API Lengkap | 7+ endpoint dengan contoh cURL, JS, Python, PHP |
| Multi-User | Role admin & user biasa |
| Responsif | Tampilan menyesuaikan HP, tablet, desktop |

---

## Cara Kerja

```
1. User buat topup Rp50.000 di dashboard
         ↓
2. Sistem generate total unik: Rp50.123 (kode unik: 123)
         ↓
3. User scan QR & bayar tepat Rp50.123 via DANA/OVO/GoPay/m-banking
         ↓
4. Aplikasi DANA Notify di HP mendeteksi notifikasi pembayaran
         ↓
5. Notifikasi dikirim ke gateway → cocokkan nominal
         ↓
6. Transaksi otomatis ditandai LUNAS ✅
```

**Kenapa kode unik?** Karena notifikasi DANA hanya berisi nominal tanpa nama pengirim. Kode unik 3 digit memastikan setiap pembayaran bisa dicocokkan ke transaksi yang benar.

---

## Kebutuhan

### Server (VPS)

- OS: Ubuntu 20.04+ / Debian 11+
- RAM: minimal 512MB
- Python 3.8+
- Port 8090 terbuka (atau via reverse proxy)
- Domain + HTTPS (disarankan via Cloudflare)

### HP Android (untuk deteksi otomatis)

- Android 8.0+
- Aplikasi DANA terinstall & login
- Aplikasi DANA Notify ([download di sini](https://github.com/Moh-Firman/qris-gateway/raw/main/dana-notify.apk))
- Koneksi internet stabil

---

## Instalasi

### 1. Persiapan VPS

```bash
# Update sistem
sudo apt update && sudo apt upgrade -y

# Install Python
sudo apt install -y python3

# Buat direktori
sudo mkdir -p /opt/gateway/static
```

### 2. Install Gateway

```bash
# Clone repository
git clone https://github.com/Moh-Firman/qris-gateway.git /tmp/qris-src

# Copy file
sudo cp /tmp/qris-src/gateway.py /opt/gateway/
sudo cp /tmp/qris-src/static/index.html /opt/gateway/static/

# Install systemd service
sudo cp /tmp/qris-src/qris-gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now qris-gateway

# Cek status
sudo systemctl status qris-gateway
curl http://localhost:8090/api/health
```

### 3. Setup Domain & HTTPS

**Opsi A: Cloudflare (disarankan)**

1. Tambah domain ke Cloudflare
2. Buat DNS A record: `gateway` → IP VPS (proxy ON/orange cloud)
3. Cloudflare otomatis sediakan HTTPS

**Opsi B: Caddy**

```
gateway.example.com {
    reverse_proxy localhost:8090
}
```

### 4. Install Aplikasi DANA Notify

1. Download APK: [dana-notify.apk](https://github.com/Moh-Firman/qris-gateway/raw/main/dana-notify.apk)
2. Install di HP Android (izinkan "install dari sumber tidak dikenal")
3. Buka aplikasi, isi:
   - **Webhook URL**: `https://gateway.example.com/api/mutasi_notify`
   - **Secret**: samakan dengan secret di gateway (lihat konfigurasi)
4. Berikan izin akses notifikasi saat diminta
5. Tes dengan tombol "Test" di aplikasi — cek di dashboard bagian Notifikasi (ikon lonceng)

### 5. Konfigurasi Awal

1. Buka `https://gateway.example.com`
2. Login dengan akun admin default (cek `init_db()` di `gateway.py` untuk kredensial awal)
3. **Segera ganti password** via ikon gear di topbar
4. Upload foto QRIS statis di bagian **QRIS Statis**
5. Atur nama merchant di **Profil**

---

## Penggunaan

### Buat Topup

1. Login sebagai admin
2. Bagian **Topup Saldo** → pilih nominal atau isi custom
3. (Opsional) isi nama merchant tampil di QR
4. Klik **Buat QRIS** → QR muncul dengan total unik
5. Bayar tepat sesuai total (termasuk kode unik)
6. Status otomatis berubah jadi lunas dalam beberapa detik

### QRIS Statis

1. Bagian **QRIS Statis** → klik **Pilih File**
2. Upload foto QRIS dari DANA Bisnis
3. Sistem otomatis baca kode QR dari gambar
4. Klik **Simpan**

### Lihat Transaksi

Bagian **Transaksi** menampilkan semua transaksi dengan filter status. Klik **Muat Ulang** untuk refresh.

> **Catatan:** Kolom pengguna dikosongkan untuk privasi. Hanya nominal, waktu, dan status yang tampil.

### Log Notifikasi

Klik ikon **lonceng** di topbar untuk melihat semua notifikasi masuk dari aplikasi DANA Notify, termasuk yang tidak cocok dengan transaksi manapun.

---

## Dokumentasi API

Base URL: `https://gateway.example.com/api`

Semua endpoint memakai `POST` dengan JSON body. Dokumentasi lengkap dengan contoh kode (cURL, JavaScript, Python, PHP) tersedia di dashboard setelah login, bagian **Dokumentasi API**.

### Endpoint Utama

| Endpoint | Auth | Keterangan |
|----------|------|-----------|
| `/api/topup_create` | Session | Buat topup QRIS dinamis |
| `/api/topup_confirm` | Session | Cek status pembayaran |
| `/api/topup_cancel` | Session | Batalkan topup |
| `/api/topup_list` | Session | Riwayat transaksi |
| `/api/balance_get` | Session | Cek saldo |
| `/api/internal_create` | Secret | Buat topup (server-to-server) |
| `/api/internal_status` | Secret | Cek status (server-to-server) |
| `/api/mutasi_notify` | Secret | Terima notifikasi DANA |

### Contoh: Buat Topup via API

```bash
curl -X POST https://gateway.example.com/api/internal_create \
  -H "Content-Type: application/json" \
  -d '{"secret": "SECRET_ANDA", "telegram_id": 123456, "amount": 50000}'
```

Response:
```json
{
  "ok": true,
  "id": 123,
  "qris_string": "000201010212...",
  "total": 50123,
  "unique_code": 123
}
```

---

## Keamanan

- **Rate limiting**: 10 request/menit per IP
- **Session**: cookie HttpOnly + Secure + SameSite
- **Password**: hash dengan salt per-user
- **Security headers**: X-Frame-Options, X-Content-Type-Options, dll
- **Anti-intip**: klik kanan, F12, Ctrl+U diblokir di frontend
- **Role-based**: non-admin tidak bisa akses fitur apapun

> **Penting:**
> - Ganti kredensial admin default segera setelah install
> - Jangan bagikan API secret ke siapapun
> - Gunakan HTTPS (jangan akses via HTTP di production)
> - Backup database `/opt/gateway/gateway.db` secara berkala

---

## Troubleshooting

### Gateway tidak jalan

```bash
sudo systemctl status qris-gateway
sudo journalctl -u qris-gateway -n 50
```

### Notifikasi tidak masuk

1. Cek aplikasi DANA Notify: webhook URL benar? secret cocok?
2. Cek izin notifikasi di HP sudah diberikan?
3. Tes dari aplikasi, lalu cek Log Notifikasi di dashboard
4. Cek log server: `sudo journalctl -u qris-gateway | grep NOTIFY`

### Pembayaran tidak otomatis lunas

1. Pastikan nominal **tepat** sama dengan total unik (termasuk 3 digit kode)
2. Cek Log Notifikasi: apakah notifikasi masuk?
3. Jika notifikasi masuk tapi tidak cocok → nominal salah

### Lupa password admin

```bash
# Reset via database (ganti 'admin' dengan username)
sudo python3 -c "
import sqlite3, os, hashlib
db = sqlite3.connect('/opt/gateway/gateway.db')
salt = os.urandom(16).hex()
pw = hashlib.sha256(('passwordbaru' + salt).encode()).hexdigest()
db.execute('UPDATE users SET pw_hash=?, salt=? WHERE username=?', (pw, salt, 'admin'))
db.commit()
print('Password direset')
"
```

---

## FAQ

**Q: Apakah nama merchant tampil di aplikasi pembayaran?**
A: Tidak. Aplikasi pembayaran (DANA/OVO/GoPay) menampilkan nama terdaftar akun DANA Bisnis, bukan nama dari QR. Ini keterbatasan DANA.

**Q: Bisa untuk banyak merchant?**
A: Satu gateway = satu akun DANA tujuan. Untuk banyak merchant, setiap merchant butuh gateway + HP + akun DANA sendiri.

**Q: Apakah aman dari penipuan?**
A: Sistem mencocokkan nominal unik. Selama kode unik tidak ditebak orang lain, pembayaran teratribusi dengan benar. Jangan bagikan QR yang sama ke banyak orang.

**Q: Berapa biaya operasional?**
A: VPS (~Rp50rb/bulan) + domain (~Rp150rb/tahun). Tidak ada biaya per transaksi dari sistem ini.

---

## Tentang Pembuat

<p>
  <img src="https://raw.githubusercontent.com/Moh-Firman/qris-gateway/main/docs/profile.png" width="80" style="border-radius:50%;vertical-align:middle">
  <b>Moh Firman</b> — Indonesia
</p>

Dibuat untuk kebutuhan pribadi yang kemudian di-open source agar bermanfaat untuk orang lain.

---

## Lisensi

MIT License — bebas dipakai, dimodifikasi, dan didistribusikan untuk keperluan apapun.

---

<p align="center">
  Dibuat dengan teliti di Indonesia 🇮🇩
</p>
