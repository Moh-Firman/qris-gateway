# QRIS Gateway

Gateway pembayaran QRIS otomatis untuk Indonesia. Buat kode QRIS dinamis, terima pembayaran dari DANA/OVO/GoPay/m-banking, saldo masuk otomatis tanpa verifikasi manual.

## Fitur

- **QRIS Dinamis** — setiap transaksi dapat kode unik untuk deteksi pembayaran otomatis
- **QRIS Statis** — QR tetap untuk merchant (khusus admin)
- **Auto-detect pembayaran** — saldo masuk otomatis setelah bayar, tanpa konfirmasi manual
- **Multi-user** — setiap pengguna punya akun, saldo, dan riwayat sendiri
- **Panel Admin** — kelola pengguna, setujui transaksi, lihat statistik
- **API lengkap** — integrasi ke aplikasi/toko online via REST API
- **Tarik Dana** — pengguna bisa tarik saldo ke e-wallet/bank

## Cara Kerja

1. Pengguna buat kode QRIS dengan nominal tertentu
2. Sistem menambahkan kode unik 3 digit (contoh: Rp50.000 → Rp50.123)
3. Pengguna scan & bayar via e-wallet/bank apapun
4. Sistem mendeteksi pembayaran masuk via notifikasi dan mencocokkan kode unik
5. Saldo otomatis bertambah

## Instalasi

### Syarat

- Node.js 18+
- Akun Telegram + Bot (via @BotFather)
- `npx tgcloud` CLI

### Langkah

```bash
# 1. Clone repo
git clone https://github.com/Moh-Firman/qris-gateway.git
cd qris-gateway

# 2. Install dependencies
npm install

# 3. Login ke tgcloud
npx tgcloud login

# 4. Deploy backend + frontend
npx tgcloud push

# 5. Migrasi database (jika ada perubahan schema)
npx tgcloud migrate
```

### Konfigurasi Awal

Setelah deploy, atur via panel admin atau endpoint:

| Key | Keterangan |
|-----|-----------|
| `config:qris_gateway_secret` | Secret untuk API internal |
| `config:qris_img` | URL gambar QRIS statis (opsional) |

## Struktur Project

```
qris-gateway/
├── web/                    # Frontend (single-page app)
│   └── index.html          # Seluruh UI dalam satu file
├── tgcloud/
│   ├── schema.js           # Skema database
│   ├── lib/                # Library shared (auth, qris)
│   ├── endpoints/          # API endpoints
│   │   ├── topup_create.js     # Buat QRIS dinamis
│   │   ├── topup_confirm.js    # Konfirmasi pembayaran
│   │   ├── topup_list.js       # Riwayat topup
│   │   ├── balance_get.js      # Cek saldo
│   │   ├── qris_config.js      # Kelola QRIS statis (admin)
│   │   ├── admin_*.js          # Endpoint khusus admin
│   │   └── internal_*.js       # API internal (pakai secret)
│   └── handlers/
│       └── message.js      # Handler bot Telegram
├── docs/                   # Dokumentasi tambahan
└── tgcloud.jsonc           # Konfigurasi project
```

## Dokumentasi API

### Autentikasi

Semua endpoint dipanggil via `POST /api/<nama>` dengan Telegram init data
(di-handle otomatis oleh `Telegram.WebApp.Serverless.call`).

Endpoint `internal_*` membutuhkan `secret` di body:

```json
{
  "secret": "SECRET_ANDA",
  "...": "parameter lain"
}
```

### Endpoint Publik

#### Buat Topup QRIS

```js
Telegram.WebApp.Serverless.call('topup_create', {
  amount: 50000,
  merchant_name: 'Toko Saya'  // opsional, maks 25 karakter
}, (err, res) => {
  // res: { topup_id, qris_string, total, unique_code, expires_at }
});
```

#### Konfirmasi Pembayaran

```js
Telegram.WebApp.Serverless.call('topup_confirm', {
  topup_id: 123
}, (err, res) => {
  // res: { status: 'paid'|'pending'|'expired', balance: 150000 }
});
```

#### Cek Saldo

```js
Telegram.WebApp.Serverless.call('balance_get', {}, (err, res) => {
  // res: { balance: 150000 }
});
```

#### Riwayat Topup

```js
Telegram.WebApp.Serverless.call('topup_list', {}, (err, res) => {
  // res: { items: [{ id, amount, status, created_at }] }
});
```

### Endpoint Internal (Server-to-Server)

#### Buat Transaksi

```
POST /api/internal_create
Body: { secret, telegram_id, amount, merchant_name }
Response: { id, qris_string, total, unique_code }
```

#### Cek Status

```
POST /api/internal_status
Body: { secret, id }
Response: { id, status, amount, telegram_id }
```

## Peran Pengguna

| Fitur | User Biasa | Admin |
|-------|:----------:|:-----:|
| Dashboard | ✅ | ✅ |
| Buat QRIS dinamis | ✅ | ✅ |
| Buat QRIS statis | ❌ | ✅ |
| Tarik dana | ✅ | ✅ |
| Lihat transaksi sendiri | ✅ | ✅ |
| Lihat semua transaksi | ❌ | ✅ |
| Kelola pengguna | ❌ | ✅ |
| Dokumentasi API | ✅ | ✅ |

## Keamanan

- Secret API disimpan di server, tidak pernah di frontend
- Setiap QRIS dinamis punya kode unik + masa berlaku
- Rate limit 15 request/menit per IP
- Cookie `Secure` + `HttpOnly`

## Lisensi

MIT License — bebas dipakai, dimodifikasi, dan didistribusikan.

## Kontribusi

Pull request dipersilakan. Untuk perubahan besar, buka issue dulu untuk diskusi.
