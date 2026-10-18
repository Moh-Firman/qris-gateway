# Dokumentasi API — QRIS Gateway

Base URL: `https://gateway.example.com/api`

Semua endpoint memakai **POST** dengan JSON body:

```bash
curl -X POST https://gateway.example.com/api/<endpoint> \
  -H "Content-Type: application/json" \
  -d '{"param": "value"}'
```

## Autentikasi

Ada 3 jenis autentikasi:

| Jenis | Cara | Untuk |
|-------|------|-------|
| **Session** | Cookie `session` (didapat dari `/api/login`) | Endpoint user & admin via web |
| **Secret** | Field `secret` di body | Server-to-server (`internal_*`, `mutasi_notify`) |
| **Publik** | Tanpa auth | `login`, `gateway_name` |

### Login

```bash
curl -X POST https://gateway.example.com/api/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "rahasia"}' \
  -c cookies.txt
```

Response:
```json
{"ok": true, "username": "admin", "is_admin": true}
```

Gunakan `-c cookies.txt` untuk simpan cookie, lalu `-b cookies.txt` untuk request berikutnya.

---

## Endpoint User

### `balance_get` — Cek Saldo

```bash
curl -X POST https://gateway.example.com/api/balance_get \
  -H "Content-Type: application/json" -b cookies.txt -d '{}'
```

```json
{"ok": true, "balance": 150000}
```

### `user_profile` — Profil Pengguna

```bash
curl -X POST https://gateway.example.com/api/user_profile \
  -H "Content-Type: application/json" -b cookies.txt -d '{}'
```

```json
{
  "ok": true,
  "username": "admin",
  "is_admin": true,
  "balance": 150000,
  "merchant_name": "Toko Saya"
}
```

### `user_qris` — QRIS Statis Pengguna

```bash
curl -X POST https://gateway.example.com/api/user_qris \
  -H "Content-Type: application/json" -b cookies.txt -d '{}'
```

```json
{"ok": true, "qris_string": "000201010212...", "merchant_name": "Toko Saya"}
```

### `api_secret` — Lihat API Secret

```bash
curl -X POST https://gateway.example.com/api/api_secret \
  -H "Content-Type: application/json" -b cookies.txt -d '{}'
```

### `change_password` — Ganti Password

```bash
curl -X POST https://gateway.example.com/api/change_password \
  -H "Content-Type: application/json" -b cookies.txt \
  -d '{"old_password": "lama", "new_password": "baru123"}'
```

### `gateway_name` — Nama Gateway (publik)

```bash
curl -X POST https://gateway.example.com/api/gateway_name \
  -H "Content-Type: application/json" -d '{}'
```

```json
{"ok": true, "gateway_name": "QRIS Gateway"}
```

### `logout` — Keluar

```bash
curl -X POST https://gateway.example.com/api/logout \
  -H "Content-Type: application/json" -b cookies.txt -d '{}'
```

---

## Endpoint Topup

### `topup_create` — Buat Topup QRIS Dinamis

| Parameter | Tipe | Wajib | Keterangan |
|-----------|------|-------|------------|
| `amount` | number | Ya | Nominal (min 1000) |
| `merchant_name` | string | Tidak | Nama tampil di QR |

```bash
curl -X POST https://gateway.example.com/api/topup_create \
  -H "Content-Type: application/json" -b cookies.txt \
  -d '{"amount": 50000}'
```

```json
{
  "ok": true,
  "id": 123,
  "qris_string": "000201010212...",
  "amount": 50000,
  "unique_code": 123,
  "total": 50123,
  "expires_at": 1728830400000
}
```

> **Penting:** Bayar tepat `total` (termasuk kode unik). Topup kadaluarsa 30 menit.

### `topup_confirm` — Cek Status Pembayaran

| Parameter | Tipe | Wajib | Keterangan |
|-----------|------|-------|------------|
| `id` | number | Ya | ID topup |

```bash
curl -X POST https://gateway.example.com/api/topup_confirm \
  -H "Content-Type: application/json" -b cookies.txt \
  -d '{"id": 123}'
```

```json
{"ok": true, "status": "paid", "id": 123}
```

Status: `pending` | `paid` | `expired` | `cancelled`

### `topup_cancel` — Batalkan Topup

```bash
curl -X POST https://gateway.example.com/api/topup_cancel \
  -H "Content-Type: application/json" -b cookies.txt \
  -d '{"id": 123}'
```

### `topup_list` — Riwayat Transaksi

| Parameter | Tipe | Default | Keterangan |
|-----------|------|---------|------------|
| `limit` | number | 30 | Maks 100 |
| `offset` | number | 0 | Untuk pagination |
| `status` | string | all | Filter: pending/paid/expired/cancelled |

```bash
curl -X POST https://gateway.example.com/api/topup_list \
  -H "Content-Type: application/json" -b cookies.txt \
  -d '{"limit": 20, "status": "paid"}'
```

---

## Endpoint Admin

Semua endpoint admin membutuhkan session user dengan `is_admin: true`.

### `admin_stats` — Statistik Dashboard

```bash
curl -X POST https://gateway.example.com/api/admin_stats \
  -H "Content-Type: application/json" -b cookies.txt -d '{}'
```

```json
{
  "ok": true,
  "total_users": 5,
  "total_tx": 120,
  "paid_tx": 95,
  "pending_tx": 3,
  "total_volume": 4750000,
  "today_volume": 250000,
  "success_rate": 79
}
```

### `admin_transactions` — Semua Transaksi

| Parameter | Tipe | Default |
|-----------|------|---------|
| `limit` | number | 30 |
| `offset` | number | 0 |
| `status` | string | all |

### `admin_charts` — Data Grafik

| Parameter | Tipe | Default |
|-----------|------|---------|
| `days` | number | 7 |

```json
{
  "ok": true,
  "daily": [
    {"date": "13 Okt", "tx": 12, "volume": 600000}
  ]
}
```

### `admin_notifications` — Log Notifikasi DANA

```bash
curl -X POST https://gateway.example.com/api/admin_notifications \
  -H "Content-Type: application/json" -b cookies.txt -d '{}'
```

```json
{
  "ok": true,
  "items": [
    {"id": 8, "amount": 10000, "text": "TES dari aplikasi", "matched_topup_id": null, "created_at": 1728830400000}
  ]
}
```

### `admin_pending` — Topup Pending

Daftar topup yang menunggu pembayaran.

### `admin_approve` — Approve Manual

| Parameter | Tipe | Wajib |
|-----------|------|-------|
| `id` | number | Ya |

### `admin_manual_credit` — Kredit Manual Saldo

| Parameter | Tipe | Wajib | Keterangan |
|-----------|------|-------|------------|
| `user_id` | number | Ya | ID user |
| `amount` | number | Ya | Nominal |

### `qris_config` — Atur QRIS Statis

| Parameter | Tipe | Keterangan |
|-----------|------|------------|
| `qris_string` | string | String QRIS statis |

### `internal_secret` — Lihat Internal Secret

---

## Endpoint Internal (Server-to-Server)

Memakai `secret` di body, bukan session cookie. Untuk integrasi backend-to-backend.

### `internal_create` — Buat Topup

| Parameter | Tipe | Wajib |
|-----------|------|-------|
| `secret` | string | Ya |
| `user_id` | number | Ya |
| `amount` | number | Ya |
| `merchant_name` | string | Tidak |

```bash
curl -X POST https://gateway.example.com/api/internal_create \
  -H "Content-Type: application/json" \
  -d '{"secret": "SECRET_ANDA", "user_id": 1, "amount": 50000}'
```

> Catatan: `telegram_id` masih diterima sebagai fallback legacy (otomatis dimapping ke `user_id`).

### `internal_status` — Cek Status

```bash
curl -X POST https://gateway.example.com/api/internal_status \
  -H "Content-Type: application/json" \
  -d '{"secret": "SECRET_ANDA", "id": 123}'
```

### `internal_pending` — Daftar Pending

### `internal_approve` — Approve via Secret

### `internal_pending_by_user` — Pending per User

| Parameter | Tipe | Wajib |
|-----------|------|-------|
| `secret` | string | Ya |
| `user_id` | number | Ya |

> Catatan: `telegram_id` masih diterima sebagai fallback legacy.

### `internal_merchant_name` — Set Nama Merchant

---

## Endpoint Notifikasi

### `mutasi_notify` — Terima Notifikasi DANA

Dipanggil oleh aplikasi DANA Notify saat ada pembayaran masuk.

| Parameter | Tipe | Wajib | Keterangan |
|-----------|------|-------|------------|
| `secret` | string | Ya | Secret gateway |
| `amount` | number | Ya | Nominal terdeteksi |
| `text` | string | Tidak | Isi notifikasi |

```bash
curl -X POST https://gateway.example.com/api/mutasi_notify \
  -H "Content-Type: application/json" \
  -d '{"secret": "SECRET_ANDA", "amount": 50123, "text": "Pembayaran Masuk Rp50.123"}'
```

Sistem otomatis mencocokkan `amount` dengan topup pending yang memiliki `total` sama.

---

## Contoh Kode

### JavaScript (Fetch)

```javascript
// Login
const login = await fetch('https://gateway.example.com/api/login', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  credentials: 'include',
  body: JSON.stringify({username: 'admin', password: 'rahasia'})
});

// Buat topup
const topup = await fetch('https://gateway.example.com/api/topup_create', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  credentials: 'include',
  body: JSON.stringify({amount: 50000})
});
const data = await topup.json();
console.log(data.qris_string, data.total);
```

### Python (Requests)

```python
import requests

s = requests.Session()
s.post('https://gateway.example.com/api/login',
       json={'username': 'admin', 'password': 'rahasia'})

r = s.post('https://gateway.example.com/api/topup_create',
           json={'amount': 50000})
print(r.json())
```

### PHP (cURL)

```php
<?php
$ch = curl_init('https://gateway.example.com/api/internal_create');
curl_setopt($ch, CURLOPT_POST, true);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_HTTPHEADER, ['Content-Type: application/json']);
curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode([
    'secret' => 'SECRET_ANDA',
    'user_id' => 1, // atau telegram_id legacy
    'amount' => 50000
]));
$response = json_decode(curl_exec($ch), true);
print_r($response);
```

---

## Error Response

Semua error memakai format:

```json
{"ok": false, "error": "Pesan error", "code": "ERROR_CODE"}
```

| Code | Arti |
|------|------|
| `BAD_INPUT` | Parameter tidak valid |
| `UNAUTHORIZED` | Belum login / session expired |
| `FORBIDDEN` | Bukan admin |
| `NOT_FOUND` | Data tidak ditemukan |
| `RATE_LIMITED` | Terlalu banyak request |
| `DISABLED` | Fitur dinonaktifkan |
| `EXPIRED` | Topup sudah kadaluarsa |

---

## Rate Limit

- **API umum**: 10 request/menit per IP
- **Login**: 5 request/menit per IP
