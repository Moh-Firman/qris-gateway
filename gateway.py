#!/usr/bin/env python3
"""QRIS Gateway — server mandiri di VPS (pengganti Telegram serverless).
- SQLite: /opt/gateway/gateway.db
- API: POST /api/<nama>
- Frontend statis: /opt/gateway/static/
- Auth: verifikasi Telegram initData (HMAC-SHA256, butuh BOT_TOKEN)
Config via environment: PORT, BOT_TOKEN, ADMIN_ID
"""
import hashlib
import hmac
import json
import logging
import os
import random
import re
import sqlite3
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8090"))
DB_PATH = os.environ.get("DB_PATH", "/opt/gateway/gateway.db")
STATIC_DIR = os.environ.get("STATIC_DIR", "/opt/gateway/static")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8441388747"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gateway")

_db_lock = threading.RLock()  # RLock: migrasi dipanggil di dalam lock
# Rate limit sederhana: {ip: [timestamps]}
_rl_store = {}
_rl_lock = threading.Lock()

def rate_limit(ip, max_req=10, window_sec=60):
    now = time.time()
    with _rl_lock:
        arr = _rl_store.get(ip, [])
        arr = [t for t in arr if now - t < window_sec]
        if len(arr) >= max_req:
            return False
        arr.append(now)
        _rl_store[ip] = arr
        return True


# Brute-force login: {key: [timestamps]}. key = "ip" atau "user:username"
_login_fails = {}
_login_lock = threading.Lock()
_LOGIN_MAX = 5       # 5x salah ...
_LOGIN_WINDOW = 300  # ... dalam 5 menit ...
_LOGIN_BLOCK = 900   # ... = blokir 15 menit

def _login_key(ip, username):
    return "u:" + username.lower() if username else "ip:" + ip

def check_login_allowed(ip, username):
    now = time.time()
    k = _login_key(ip, username)
    with _login_lock:
        arr = [t for t in _login_fails.get(k, []) if now - t < _LOGIN_WINDOW + _LOGIN_BLOCK]
        _login_fails[k] = arr
        # blokir bila 5 gagal dalam 5 menit terakhir
        recent = [t for t in arr if now - t < _LOGIN_WINDOW]
        return len(recent) < _LOGIN_MAX

def _record_login_fail(username, ip):
    with _login_lock:
        for k in (_login_key(ip, username), _login_key(ip, "")):
            _login_fails[k] = _login_fails.get(k, []) + [time.time()]

def _clear_login_fails(username, ip):
    with _login_lock:
        _login_fails.pop(_login_key(ip, username), None)
        _login_fails.pop(_login_key(ip, ""), None)


def db():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _db_lock, db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS qris_topups (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          telegram_id INTEGER,
          amount INTEGER NOT NULL,
          unique_code INTEGER NOT NULL,
          total INTEGER NOT NULL,
          qris_string TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          created_at INTEGER NOT NULL,
          paid_at INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_qris_user ON qris_topups(user_id);
        CREATE INDEX IF NOT EXISTS idx_qris_tid ON qris_topups(telegram_id);
        CREATE INDEX IF NOT EXISTS idx_qris_status ON qris_topups(status);
        CREATE TABLE IF NOT EXISTS qris_users (
          user_id INTEGER PRIMARY KEY,
          telegram_id INTEGER,
          balance INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_qris_users_tid ON qris_users(telegram_id);
        CREATE TABLE IF NOT EXISTS kv_store (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT UNIQUE NOT NULL,
          pw_hash TEXT NOT NULL,
          salt TEXT NOT NULL,
          is_admin INTEGER NOT NULL DEFAULT 0,
          balance INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
          token TEXT PRIMARY KEY,
          user_id INTEGER NOT NULL,
          expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS withdrawals (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          amount INTEGER NOT NULL,
          destination TEXT NOT NULL,
          dest_type TEXT NOT NULL DEFAULT 'dana',
          status TEXT NOT NULL DEFAULT 'pending',
          created_at INTEGER NOT NULL,
          processed_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS qris_notifications (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          amount INTEGER NOT NULL,
          raw_text TEXT NOT NULL,
          matched_topup_id INTEGER,
          claimed_by INTEGER,
          claimed_at INTEGER,
          created_at INTEGER NOT NULL
        );
        """)
        # Migrasi kolom claimed jika tabel lama
        cols = [r["name"] for r in c.execute("PRAGMA table_info(qris_notifications)").fetchall()]
        if "claimed_by" not in cols:
            c.execute("ALTER TABLE qris_notifications ADD COLUMN claimed_by INTEGER")
        if "claimed_at" not in cols:
            c.execute("ALTER TABLE qris_notifications ADD COLUMN claimed_at INTEGER")
        # Tambah kolom merchant_name & payout ke users jika belum ada
        cols = [r["name"] for r in c.execute("PRAGMA table_info(users)").fetchall()]
        if "merchant_name" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN merchant_name TEXT DEFAULT ''")
        if "payout_dest" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN payout_dest TEXT DEFAULT ''")
        if "payout_type" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN payout_type TEXT DEFAULT 'dana'")
        if "api_secret" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN api_secret TEXT DEFAULT ''")
        # Buat admin default jika belum ada
        r = c.execute("SELECT id FROM users WHERE username='admin'").fetchone()
        if not r:
            salt = os.urandom(16).hex()
            ph = hashlib.pbkdf2_hmac("sha256", b"admin123", bytes.fromhex(salt), 100000).hex()
            c.execute("INSERT INTO users(username,pw_hash,salt,is_admin,balance,created_at)"
                      " VALUES('admin',?,?,1,0,?)", (ph, salt, int(time.time()*1000)))
            log.warning("User admin dibuat dengan password default 'admin123' — SEGERA GANTI via Pengaturan!")
        _migrate_to_userid()
    log.info("DB siap: %s", DB_PATH)


def _get_or_create_user_for_tid(c, tid):
    """Cari user.id untuk telegram_id, buat user sintetis jika belum ada.
    Hanya query tabel users (aman untuk struktur lama maupun baru)."""
    uname = f"tg_{abs(int(tid))}"
    r = c.execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone()
    if r:
        return r["id"]
    now = int(time.time() * 1000)
    salt = os.urandom(16).hex()
    ph = hash_pw(os.urandom(32).hex(), salt)
    cur = c.execute("INSERT INTO users(username,pw_hash,salt,is_admin,balance,created_at)"
                    " VALUES(?,?,?,0,0,?)", (uname, ph, salt, now))
    return cur.lastrowid


def _migrate_to_userid():
    """Migrasi data lama berbasis telegram_id ke users.id. Idempotent."""
    with _db_lock, db() as c:
        # Skip cepat jika migrasi sudah selesai (hindari lock)
        try:
            pk = c.execute("SELECT sql FROM sqlite_master WHERE name='qris_users'").fetchone()
            nulls = c.execute("SELECT COUNT(*) FROM qris_topups WHERE user_id IS NULL").fetchone()[0]
            if pk and "user_id INTEGER PRIMARY KEY" in pk["sql"] and nulls == 0:
                return
        except Exception:
            pass
        # 1. Pastikan kolom user_id ada di qris_topups (DB lama)
        cols = [r["name"] for r in c.execute("PRAGMA table_info(qris_topups)").fetchall()]
        if "user_id" not in cols:
            c.execute("ALTER TABLE qris_topups ADD COLUMN user_id INTEGER")
        # 2. Migrasi struktur qris_users lama (PK=telegram_id) ke baru (PK=user_id)
        pk = c.execute("SELECT sql FROM sqlite_master WHERE name='qris_users'").fetchone()
        if pk and "telegram_id INTEGER PRIMARY KEY" in pk["sql"]:
            c.execute("""CREATE TABLE IF NOT EXISTS qris_users_new (
              user_id INTEGER PRIMARY KEY,
              telegram_id INTEGER,
              balance INTEGER NOT NULL DEFAULT 0,
              created_at INTEGER NOT NULL
            )""")
            for row in c.execute("SELECT telegram_id, balance, created_at FROM qris_users").fetchall():
                uid = _get_or_create_user_for_tid(c, row["telegram_id"])
                c.execute("INSERT OR REPLACE INTO qris_users_new(user_id, telegram_id, balance, created_at)"
                          " VALUES(?,?,?,?)", (uid, row["telegram_id"], row["balance"], row["created_at"]))
            c.execute("DROP TABLE qris_users")
            c.execute("ALTER TABLE qris_users_new RENAME TO qris_users")
            c.execute("CREATE INDEX IF NOT EXISTS idx_qris_users_tid ON qris_users(telegram_id)")
            log.info("Migrasi qris_users: telegram_id -> user_id selesai")
        # 2b. Buat telegram_id nullable di qris_topups (jika masih NOT NULL)
        _ti = [r for r in c.execute("PRAGMA table_info(qris_topups)").fetchall()]
        _tid_col = next((r for r in _ti if r["name"] == "telegram_id"), None)
        if _tid_col and _tid_col["notnull"]:
            # Recreate tabel dengan telegram_id nullable
            cols = ", ".join([f'{r["name"]} {r["type"]}' + ("" if r["name"]=="telegram_id" else (" NOT NULL" if r["notnull"] else "")) + (f' DEFAULT {r["dflt_value"]}' if r["dflt_value"] else "") + (" PRIMARY KEY" if r["pk"] else "") for r in _ti])
            c.execute(f"CREATE TABLE qris_topups_new ({cols})")
            col_names = ", ".join([r["name"] for r in _ti])
            c.execute(f"INSERT INTO qris_topups_new ({col_names}) SELECT {col_names} FROM qris_topups")
            c.execute("DROP TABLE qris_topups")
            c.execute("ALTER TABLE qris_topups_new RENAME TO qris_topups")
            log.info("Migrasi: telegram_id jadi nullable")
        # 3. Isi user_id yang kosong di qris_topups
        for row in c.execute("SELECT id, telegram_id FROM qris_topups WHERE user_id IS NULL").fetchall():
            if row["telegram_id"] is None:
                continue
            uid = _get_or_create_user_for_tid(c, row["telegram_id"])
            c.execute("UPDATE qris_topups SET user_id=? WHERE id=?", (uid, row["id"]))
        # 4. Sinkronkan users.balance dari qris_users
        for row in c.execute("SELECT user_id, balance FROM qris_users").fetchall():
            c.execute("UPDATE users SET balance=? WHERE id=?", (row["balance"], row["user_id"]))
        log.info("Migrasi user_id selesai")


def kv_get(key):
    with _db_lock, db() as c:
        r = c.execute("SELECT value FROM kv_store WHERE key=?", (key,)).fetchone()
        return r["value"] if r else None


def kv_set(key, value):
    with _db_lock, db() as c:
        c.execute("INSERT INTO kv_store(key,value) VALUES(?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


# ---------- QRIS lib (port dari tgcloud/lib/qris.js) ----------
def _crc16(s):
    crc = 0xFFFF
    for ch in s:
        crc ^= ord(ch) << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
    return format(crc, "04X")


def _parse_tlv(s):
    out, i = {}, 0
    while i + 4 <= len(s):
        tid, ln = s[i:i+2], s[i+2:i+4]
        if not ln.isdigit():
            break
        ln = int(ln)
        if i + 4 + ln > len(s):
            break
        out[tid] = s[i+4:i+4+ln]
        i += 4 + ln
    return out


def _build_tlv(tid, v):
    return tid + str(len(v)).zfill(2) + v


def make_dynamic_qris(static_qris, amount, merchant_name=None):
    tlv = _parse_tlv(static_qris.strip())
    if tlv.get("00") != "01":
        raise ValueError("Bukan payload QRIS valid.")
    tlv["01"] = "12"
    tlv["54"] = str(round(amount))
    if merchant_name:
        tlv["59"] = str(merchant_name).strip()[:25]
    tlv.pop("63", None)
    payload = "".join(_build_tlv(k, tlv[k]) for k in sorted(tlv, key=int))
    with_crc = payload + "6304"
    return with_crc + _crc16(with_crc)


def valid_qris(q):
    try:
        s = q.strip()
        return len(s) >= 8 and _crc16(s[:-4]) == s[-4:].upper()
    except Exception:
        return False


def merchant_info(q):
    try:
        t = _parse_tlv(q.strip())
        return {"name": t.get("59", ""), "city": t.get("60", ""), "mcc": t.get("52", "")}
    except Exception:
        return {}


# ---------- Auth: user login ----------
def hash_pw(password, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 100000).hex()


def create_session(user_id):
    token = os.urandom(32).hex()
    exp = int(time.time()*1000) + 30*86400000  # 30 hari
    with _db_lock, db() as c:
        c.execute("INSERT INTO sessions(token,user_id,expires_at) VALUES(?,?,?)",
                  (token, user_id, exp))
    return token


def get_session_user(cookie_header):
    if not cookie_header:
        return None
    token = None
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith("gw_session="):
            token = part[11:]
            break
    if not token:
        return None
    now = int(time.time()*1000)
    with _db_lock, db() as c:
        r = c.execute("SELECT user_id FROM sessions WHERE token=? AND expires_at>?",
                      (token, now)).fetchone()
        if not r:
            return None
        u = c.execute("SELECT id,username,is_admin,balance FROM users WHERE id=?",
                      (r["user_id"],)).fetchone()
        return dict(u) if u else None


def destroy_session(cookie_header):
    token = None
    if cookie_header:
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("gw_session="):
                token = part[11:]; break
    if token:
        with _db_lock, db() as c:
            c.execute("DELETE FROM sessions WHERE token=?", (token,))


def ep_login(p, u):
    username = str(p.get("username") or "").strip().lower()
    password = str(p.get("password") or "")
    ip = p.get("_client_ip", "?")
    if not username or not password:
        raise EpError("Username dan password wajib.", "BAD_INPUT")
    if not check_login_allowed(ip, username):
        log.warning("LOGIN BLOKIR brute-force: user=%s ip=%s", username, ip)
        raise EpError("Terlalu banyak percobaan gagal. Coba lagi 15 menit.", "LOCKED")
    with _db_lock, db() as c:
        r = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not r or not hmac.compare_digest(hash_pw(password, r["salt"]), r["pw_hash"]):
            _record_login_fail(username, ip)
            raise EpError("Username atau password salah.", "BAD_LOGIN")
        _clear_login_fails(username, ip)
        user = dict(r)
    token = create_session(user["id"])
    return {"ok": True, "token": token,
            "_set_cookie": f"gw_session={token}; Path=/; Max-Age=2592000; HttpOnly; Secure; SameSite=Lax",
            "user": {"id": user["id"], "username": user["username"],
                     "is_admin": bool(user["is_admin"]), "balance": user["balance"]}}


def ep_register(p, u):
    """Pendaftaran akun web mandiri dengan validasi.
    Rate-limited di do_POST. Username unik, password min 6 karakter."""
    username = str(p.get("username") or "").strip().lower()
    password = str(p.get("password") or "")
    if not username or len(username) < 3 or len(username) > 20 or not username.replace("_","").isalnum():
        raise EpError("Username 3-20 karakter alfanumerik.", "BAD_INPUT")
    if len(password) < 6:
        raise EpError("Password minimal 6 karakter.", "BAD_INPUT")
    salt = os.urandom(16).hex()
    ph = hash_pw(password, salt)
    now = int(time.time()*1000)
    try:
        with _db_lock, db() as c:
            cur = c.execute("INSERT INTO users(username,pw_hash,salt,is_admin,balance,created_at)"
                            " VALUES(?, ?, ?, 0, 0, ?)", (username, ph, salt, now))
            uid = cur.lastrowid
    except sqlite3.IntegrityError:
        raise EpError("Username sudah dipakai.", "TAKEN")
    token = create_session(uid)
    return {"ok": True, "_set_cookie": f"gw_session={token}; Path=/; Max-Age=2592000; HttpOnly; Secure; SameSite=Lax",
            "user": {"id": uid, "username": username, "is_admin": False, "balance": 0}}


def ep_logout(p, u):
    return {"ok": True, "_clear_cookie": True}


def ep_me(p, u):
    su = p.get("_session_user")
    if not su:
        raise EpError("Belum login.", "UNAUTHORIZED")
    with _db_lock, db() as c:
        r = c.execute("SELECT balance FROM users WHERE id=?", (su["id"],)).fetchone()
    return {"ok": True, "user": {"id": su["id"], "username": su["username"],
            "is_admin": bool(su["is_admin"]), "balance": r["balance"] if r else 0}}


def ep_change_password(p, u):
    su = p.get("_session_user")
    if not su:
        raise EpError("Belum login.", "UNAUTHORIZED")
    old = str(p.get("old") or p.get("old_password") or ""); new = str(p.get("new") or p.get("new_password") or "")
    if len(new) < 6:
        raise EpError("Password baru minimal 6 karakter.", "BAD_INPUT")
    with _db_lock, db() as c:
        r = c.execute("SELECT * FROM users WHERE id=?", (su["id"],)).fetchone()
        if not r or hash_pw(old, r["salt"]) != r["pw_hash"]:
            raise EpError("Password lama salah.", "BAD_LOGIN")
        salt = os.urandom(16).hex()
        c.execute("UPDATE users SET pw_hash=?, salt=? WHERE id=?",
                  (hash_pw(new, salt), salt, su["id"]))
    return {"ok": True}


def settled_balance(user_id):
    """Saldo yang sudah settlement (>24 jam) dikurangi withdraw pending/approved."""
    now = int(time.time()*1000)
    cutoff = now - 24*3600000
    with _db_lock, db() as c:
        paid = c.execute("SELECT COALESCE(SUM(amount),0) s FROM qris_topups"
                         " WHERE user_id=? AND status='paid' AND paid_at<?",
                         (user_id, cutoff)).fetchone()["s"]
        out = c.execute("SELECT COALESCE(SUM(amount),0) s FROM withdrawals"
                        " WHERE user_id=? AND status IN ('pending','approved')",
                        (user_id,)).fetchone()["s"]
    return max(0, paid - out)


def ep_settled_balance(p, u):
    su = p.get("_session_user")
    if not su:
        raise EpError("Belum login.", "UNAUTHORIZED")
    return {"ok": True, "settled": settled_balance(su["id"])}


def ep_user_profile(p, u):
    su = p.get("_session_user")
    if not su:
        raise EpError("Belum login.", "UNAUTHORIZED")
    if p.get("merchant_name") is not None or p.get("payout_dest") is not None:
        mn = str(p.get("merchant_name") or "").strip()[:25].upper()
        pd = str(p.get("payout_dest") or "").strip()[:50]
        pt = str(p.get("payout_type") or "dana").strip().lower()
        if pt not in ("dana", "ovo", "gopay", "bank"):
            pt = "dana"
        with _db_lock, db() as c:
            c.execute("UPDATE users SET merchant_name=?, payout_dest=?, payout_type=?"
                      " WHERE id=?", (mn, pd, pt, su["id"]))
        return {"ok": True}
    # Ubah username
    if p.get("new_username"):
        nu = str(p.get("new_username")).strip().lower()
        if not re.match(r"^[a-z0-9_]{3,20}$", nu):
            raise EpError("Username 3-20 karakter (huruf, angka, _).", "BAD_INPUT")
        with _db_lock, db() as c:
            ex = c.execute("SELECT id FROM users WHERE username=?", (nu,)).fetchone()
            if ex and ex["id"] != su["id"]:
                raise EpError("Username sudah dipakai.", "TAKEN")
            c.execute("UPDATE users SET username=? WHERE id=?", (nu, su["id"]))
        return {"ok": True, "username": nu}
    with _db_lock, db() as c:
        r = c.execute("SELECT username, merchant_name, payout_dest, payout_type FROM users WHERE id=?",
                      (su["id"],)).fetchone()
    return {"ok": True, "username": r["username"], "merchant_name": r["merchant_name"] or "",
            "payout_dest": r["payout_dest"] or "", "payout_type": r["payout_type"] or "dana"}


def ep_withdraw_request(p, u):
    su = p.get("_session_user")
    if not su:
        raise EpError("Belum login.", "UNAUTHORIZED")
    amount = int(p.get("amount") or 0)
    if amount < 50000:
        raise EpError("Minimal penarikan Rp50.000.", "BAD_AMOUNT")
    avail = settled_balance(su["id"])
    if amount > avail:
        raise EpError(f"Saldo settlement tidak cukup (tersedia {rupiah_fmt(avail)}).", "INSUFFICIENT")
    with _db_lock, db() as c:
        r = c.execute("SELECT payout_dest, payout_type FROM users WHERE id=?", (su["id"],)).fetchone()
        dest = r["payout_dest"] or ""
        dt = r["payout_type"] or "dana"
        if not dest:
            raise EpError("Isi dulu tujuan pencairan di Profil.", "NO_DEST")
        cur = c.execute("INSERT INTO withdrawals(user_id,amount,destination,dest_type,status,created_at)"
                        " VALUES(?,?,?,?,'pending',?)",
                        (su["id"], amount, dest, dt, int(time.time()*1000)))
    return {"ok": True, "id": cur.lastrowid, "amount": amount}


def ep_withdraw_list(p, u):
    su = p.get("_session_user")
    if not su:
        raise EpError("Belum login.", "UNAUTHORIZED")
    with _db_lock, db() as c:
        rows = c.execute("SELECT * FROM withdrawals WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
                         (su["id"],)).fetchall()
    return {"ok": True, "items": [dict(r) for r in rows]}


def ep_admin_withdrawals(p, u):
    require_admin(p, u)
    status = str(p.get("status") or "pending")
    with _db_lock, db() as c:
        if status == "all":
            rows = c.execute("SELECT w.*, us.username FROM withdrawals w"
                             " JOIN users us ON w.user_id=us.id"
                             " ORDER BY w.created_at DESC LIMIT 50").fetchall()
        else:
            rows = c.execute("SELECT w.*, us.username FROM withdrawals w"
                             " JOIN users us ON w.user_id=us.id WHERE w.status=?"
                             " ORDER BY w.created_at DESC LIMIT 50", (status,)).fetchall()
    return {"ok": True, "items": [dict(r) for r in rows]}


def ep_admin_withdraw_process(p, u):
    require_admin(p, u)
    wid = int(p.get("id") or 0)
    action = str(p.get("action") or "")  # approved | rejected | done
    if action not in ("approved", "rejected", "done"):
        raise EpError("Aksi tidak valid.", "BAD_INPUT")
    with _db_lock, db() as c:
        w = c.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
        if not w:
            raise EpError("Tidak ditemukan.", "NOT_FOUND")
        if w["status"] not in ("pending", "approved"):
            raise EpError("Sudah diproses.", "ALREADY")
        c.execute("UPDATE withdrawals SET status=?, processed_at=? WHERE id=?",
                  (action, int(time.time()*1000), wid))
    return {"ok": True, "action": action}


def rupiah_fmt(n):
    return "Rp" + f"{n:,}".replace(",", ".")


# ---------- Telegram initData verification ----------
def verify_init_data(init_data):
    """Return dict user atau None. Jika BOT_TOKEN kosong -> tolak."""
    if not BOT_TOKEN or not init_data:
        return None
    try:
        pairs = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
        d = dict(pairs)
        recv_hash = d.pop("hash", None)
        if not recv_hash:
            return None
        check_str = "\n".join(f"{k}={d[k]}" for k in sorted(d))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check_str.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, recv_hash):
            return None
        return json.loads(d.get("user", "{}"))
    except Exception:
        return None


class EpError(Exception):
    def __init__(self, msg, code="ERROR"):
        super().__init__(msg)
        self.code = code


def get_user_id(payload, init_user):
    """Return users.id untuk user yang terautentikasi.
    Sumber identitas (prioritas):
    1. Session login web (_session_user) -> users.id langsung
    2. Telegram initData terverifikasi -> users.id via mapping telegram_id
    TIDAK PERNAH percaya telegram_id dari payload client (celah spoofing)."""
    su = payload.get("_session_user")
    if su:
        if su.get("is_admin"):
            return ADMIN_ID
        return int(su["id"])  # users.id langsung, bukan sintetis negatif
    if init_user and init_user.get("id"):
        # Mapping telegram_id -> users.id (buat jika belum ada)
        tid = int(init_user["id"])
        with _db_lock, db() as c:
            r = c.execute("SELECT user_id FROM qris_users WHERE telegram_id=?", (tid,)).fetchone()
            if r:
                return r["user_id"]
            uid = _get_or_create_user_for_tid(c, tid)
            now = int(time.time() * 1000)
            c.execute("INSERT OR IGNORE INTO qris_users(user_id, telegram_id, balance, created_at)"
                      " VALUES(?,?,0,?)", (uid, tid, now))
            return uid
    raise EpError("Belum login.", "UNAUTHORIZED")


def require_admin(payload, init_user):
    su = payload.get("_session_user")
    if su:
        if su.get("is_admin"):
            return ADMIN_ID
        raise EpError("Akses ditolak.", "FORBIDDEN")
    uid = get_user_id(payload, init_user)
    if uid != ADMIN_ID:
        raise EpError("Akses ditolak.", "FORBIDDEN")
    return uid


def check_secret(payload):
    """Return (is_global, user_id_atau_None). Global secret = akses penuh.
    Secret per-user = hanya untuk user itu sendiri."""
    secret = str(payload.get("secret", "")).strip()
    expected = kv_get("internal_secret")
    if expected and hmac.compare_digest(secret, expected):
        return (True, None)
    if secret:
        with _db_lock, db() as c:
            r = c.execute("SELECT id, is_admin FROM users WHERE api_secret=? AND api_secret!=''",
                          (secret,)).fetchone()
            if r:
                return (False, r["id"])
    # Log untuk diagnosis
    if expected:
        log.warning("AUTH GAGAL: diterima len=%d hash=%s | tersimpan len=%d hash=%s",
                    len(secret), hashlib.sha256(secret.encode()).hexdigest()[:12],
                    len(expected), hashlib.sha256(expected.encode()).hexdigest()[:12])
    else:
        log.warning("AUTH GAGAL: internal_secret belum diset, secret user tidak cocok")
    raise EpError("Unauthorized", "UNAUTHORIZED")


def gen_api_secret():
    import secrets as pysecrets
    return "gw_" + pysecrets.token_urlsafe(24)


def ep_user_qris(p, u):
    """QRIS statis personal user: QRIS global + nama merchant user."""
    su = p.get("_session_user")
    if not su:
        raise EpError("Belum login.", "UNAUTHORIZED")
    static = kv_get("qris_static")
    if not static:
        raise EpError("QRIS merchant belum dikonfigurasi admin.", "NOT_CONFIGURED")
    with _db_lock, db() as c:
        r = c.execute("SELECT merchant_name FROM users WHERE id=?", (su["id"],)).fetchone()
    mn = (r["merchant_name"] or "").strip() if r else ""
    # Buat versi statis: PoI tetap 11 (statis), ganti nama saja
    tlv = _parse_tlv(static.strip())
    if mn:
        tlv["59"] = mn[:25].upper()
    tlv.pop("63", None)
    payload = "".join(_build_tlv(k, tlv[k]) for k in sorted(tlv, key=int))
    with_crc = payload + "6304"
    qris = with_crc + _crc16(with_crc)
    return {"ok": True, "qris_string": qris, "merchant_name": mn or tlv.get("59", "")}


def ep_api_secret(p, u):
    su = p.get("_session_user")
    if not su:
        raise EpError("Belum login.", "UNAUTHORIZED")
    with _db_lock, db() as c:
        if p.get("regenerate"):
            ns = gen_api_secret()
            c.execute("UPDATE users SET api_secret=? WHERE id=?", (ns, su["id"]))
            return {"ok": True, "secret": ns}
        r = c.execute("SELECT api_secret FROM users WHERE id=?", (su["id"],)).fetchone()
        s = r["api_secret"] if r and r["api_secret"] else ""
        if not s:
            s = gen_api_secret()
            c.execute("UPDATE users SET api_secret=? WHERE id=?", (s, su["id"]))
        return {"ok": True, "secret": s}


def credit(user_id, amount):
    """Kredit saldo ke users.id. Juga sinkron ke users.balance."""
    now = int(time.time() * 1000)
    with _db_lock, db() as c:
        r = c.execute("SELECT balance, telegram_id FROM qris_users WHERE user_id=?", (user_id,)).fetchone()
        if r:
            bal = r["balance"] + amount
            c.execute("UPDATE qris_users SET balance=? WHERE user_id=?", (bal, user_id))
        else:
            bal = amount
            c.execute("INSERT INTO qris_users(user_id,balance,created_at) VALUES(?,?,?)",
                      (user_id, bal, now))
        c.execute("UPDATE users SET balance=? WHERE id=?", (bal, user_id))
        return bal


def new_topup(user_id, amount, merchant_name=None):
    amount = round(float(amount))
    if not amount or amount < 1:
        raise EpError("Minimal Rp1.", "BAD_AMOUNT")
    if amount > 10000000:
        raise EpError("Maksimal Rp10.000.000.", "BAD_AMOUNT")
    static_qris = kv_get("qris_static")
    if not static_qris:
        raise EpError("QRIS merchant belum dikonfigurasi.", "NOT_CONFIGURED")
    with _db_lock, db() as c:
        unique_code = total = None
        for _ in range(20):
            uc = random.randint(100, 999)
            t = amount + uc
            ex = c.execute("SELECT id FROM qris_topups WHERE total=? AND status='pending'",
                           (t,)).fetchone()
            if not ex:
                unique_code, total = uc, t
                break
        if unique_code is None:
            raise EpError("Gagal generate kode unik, coba lagi.", "RETRY")
        qris_string = make_dynamic_qris(static_qris, total, merchant_name)
        now = int(time.time() * 1000)
        # Ambil telegram_id opsional untuk referensi legacy
        trow = c.execute("SELECT telegram_id FROM qris_users WHERE user_id=?", (user_id,)).fetchone()
        legacy_tid = trow["telegram_id"] if trow else None
        cur = c.execute(
            "INSERT INTO qris_topups(user_id,telegram_id,amount,unique_code,total,qris_string,status,created_at)"
            " VALUES(?,?,?,?,?,?,'pending',?)",
            (user_id, legacy_tid, amount, unique_code, total, qris_string, now))
        tid_out = cur.lastrowid
    mn = str(merchant_name).strip()[:25].upper() if merchant_name else None
    return {"id": tid_out, "amount": amount, "unique_code": unique_code, "total": total,
            "qris_string": qris_string, "merchant_name": mn,
            "expires_at": now + 30 * 60000}


# ---------- Endpoints ----------
def ep_whoami(p, u):
    uid = get_user_id(p, u)
    su = p.get("_session_user")
    return {"user_id": uid, "first_name": (u or {}).get("first_name", ""),
            "username": (su or {}).get("username") or (u or {}).get("username", ""),
            "is_admin": uid == ADMIN_ID}


def ep_balance_get(p, u):
    uid = get_user_id(p, u)
    with _db_lock, db() as c:
        r = c.execute("SELECT balance FROM qris_users WHERE user_id=?", (uid,)).fetchone()
        if not r:
            c.execute("INSERT INTO qris_users(user_id,balance,created_at) VALUES(?,?,?)",
                      (uid, 0, int(time.time()*1000)))
            return {"balance": 0, "user_id": uid}
        return {"balance": r["balance"], "user_id": uid}


def ep_topup_create(p, u):
    uid = get_user_id(p, u)
    # Ambil merchant name custom user jika ada
    mn = p.get("merchant_name")
    su = p.get("_session_user")
    if not mn and su:
        with _db_lock, db() as c:
            r = c.execute("SELECT merchant_name FROM users WHERE id=?", (su["id"],)).fetchone()
            if r and r["merchant_name"]:
                mn = r["merchant_name"]
    return new_topup(uid, p.get("amount"), mn)


def ep_topup_cancel(p, u):
    su = p.get("_session_user")
    uid = get_user_id(p, u)
    topup_id = int(p.get("id") or 0)
    with _db_lock, db() as c:
        t = c.execute("SELECT * FROM qris_topups WHERE id=?", (topup_id,)).fetchone()
        if not t:
            raise EpError("Tidak ditemukan.", "NOT_FOUND")
        # User hanya bisa batalkan milik sendiri, admin bisa semua
        if not (su and su.get("is_admin")) and t["user_id"] != uid:
            raise EpError("Bukan milikmu.", "FORBIDDEN")
        if t["status"] != "pending":
            raise EpError("Sudah " + t["status"] + ".", "ALREADY")
        c.execute("UPDATE qris_topups SET status='expired' WHERE id=?", (topup_id,))
    return {"ok": True}


def ep_topup_confirm(p, u):
    """Cek status saja - TIDAK kredit saldo. Kredit hanya via mutasi_notify otomatis."""
    tid = get_user_id(p, u)
    _id = int(p.get("id") or 0)
    if not _id:
        raise EpError("ID tidak valid.", "BAD_INPUT")
    with _db_lock, db() as c:
        t = c.execute("SELECT * FROM qris_topups WHERE id=?", (_id,)).fetchone()
        if not t:
            raise EpError("Topup tidak ditemukan.", "NOT_FOUND")
        if t["user_id"] != tid:
            raise EpError("Bukan milikmu.", "FORBIDDEN")
        if t["status"] == "paid":
            return {"ok": True, "status": "paid", "amount": t["amount"]}
        now = int(time.time() * 1000)
        if now - t["created_at"] > 30 * 60000:
            if t["status"] == "pending":
                c.execute("UPDATE qris_topups SET status='expired' WHERE id=?", (_id,))
            return {"ok": True, "status": "expired"}
        return {"ok": True, "status": t["status"]}


def expire_old_topups():
    """Tandai pending >30 menit sebagai expired."""
    try:
        cutoff = int(time.time() * 1000) - 30 * 60000
        with _db_lock, db() as c:
            c.execute("UPDATE qris_topups SET status='expired' WHERE status='pending' AND created_at<?", (cutoff,))
    except Exception:
        pass


def ep_topup_list(p, u):
    expire_old_topups()
    uid = get_user_id(p, u)
    with _db_lock, db() as c:
        rows = c.execute(
            "SELECT id,amount,unique_code,total,status,created_at FROM qris_topups"
            " WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (uid,)).fetchall()
    return {"items": [dict(r) for r in rows]}


def ep_internal_merchant_name(p, u):
    check_secret(p)
    static = kv_get("qris_static")
    if not static:
        raise EpError("QRIS belum dikonfigurasi.", "NOT_CONFIGURED")
    info = merchant_info(static)
    return {"merchant_name": info.get("name", "")}


def ep_gateway_name(p, u):
    if p.get("name") is not None:
        require_admin(p, u)
        name = str(p["name"]).strip()[:50]
        if not name:
            raise EpError("Nama tidak boleh kosong.", "BAD_INPUT")
        kv_set("gateway_name", name)
        return {"ok": True, "name": name}
    get_user_id(p, u)
    return {"name": kv_get("gateway_name") or "QRIS Gateway"}


def ep_qris_config(p, u):
    if p.get("get"):
        get_user_id(p, u)
        saved = kv_get("qris_static")
        return {"configured": bool(saved), "merchant": merchant_info(saved) if saved else None}
    require_admin(p, u)
    qris = str(p.get("qris") or "").strip()
    if not qris:
        raise EpError("QRIS tidak boleh kosong.", "BAD_INPUT")
    if not valid_qris(qris):
        raise EpError("QRIS tidak valid (CRC salah).", "BAD_QRIS")
    kv_set("qris_static", qris)
    return {"ok": True, "merchant": merchant_info(qris)}


def ep_admin_charts(p, u):
    get_user_id(p, u)
    where, wparams = scoped_tid(p, u)
    import datetime
    days = min(30, max(7, int(p.get("days") or 7)))
    daily = []
    with _db_lock, db() as c:
        for i in range(days - 1, -1, -1):
            day = datetime.datetime.now() - datetime.timedelta(days=i)
            start = int(day.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
            end = start + 86400000
            r = c.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN status='paid' THEN amount ELSE 0 END),0) vol,"
                " SUM(CASE WHEN status='paid' THEN 1 ELSE 0 END) paid,"
                " SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) pending"
                f" FROM qris_topups WHERE {where} AND created_at>=? AND created_at<?",
                (*wparams, start, end)).fetchone()
            daily.append({"date": day.strftime("%d %b"), "tx": r["n"] or 0,
                          "volume": r["vol"] or 0, "paid": r["paid"] or 0,
                          "pending": r["pending"] or 0})
        dist = c.execute(
            f"SELECT status, COUNT(*) n FROM qris_topups WHERE {where} GROUP BY status", wparams).fetchall()
    return {"daily": daily,
            "status_dist": {r["status"]: r["n"] for r in dist}}


def scoped_tid(payload, init_user):
    """Return (where_clause, params) untuk filter data milik user sendiri.
    Admin -> tanpa filter (semua data). User biasa -> hanya miliknya."""
    su = payload.get("_session_user")
    if su and su.get("is_admin"):
        return ("1=1", [])
    uid = get_user_id(payload, init_user)
    return ("user_id=?", [uid])


def ep_admin_stats(p, u):
    get_user_id(p, u)
    where, params = scoped_tid(p, u)
    is_admin = where == "1=1"
    with _db_lock, db() as c:
        tu = c.execute("SELECT COUNT(*) c FROM qris_users").fetchone()["c"] if is_admin else 1
        tt = c.execute(f"SELECT COUNT(*) c FROM qris_topups WHERE {where}", params).fetchone()["c"]
        pd = c.execute(f"SELECT COUNT(*) c FROM qris_topups WHERE {where} AND status='paid'", params).fetchone()["c"]
        pn = c.execute(f"SELECT COUNT(*) c FROM qris_topups WHERE {where} AND status='pending'", params).fetchone()["c"]
        ex = c.execute(f"SELECT COUNT(*) c FROM qris_topups WHERE {where} AND status='expired'", params).fetchone()["c"]
        vol = c.execute(f"SELECT COALESCE(SUM(amount),0) s FROM qris_topups WHERE {where} AND status='paid'", params).fetchone()["s"]
        tv = c.execute(f"SELECT COALESCE(SUM(amount),0) s FROM qris_topups WHERE {where} AND status='paid' AND paid_at>?",
                       (*params, int(time.time()*1000)-86400000)).fetchone()["s"]
    boot = kv_get("gateway_boot_time")
    if not boot:
        boot = str(int(time.time()*1000)); kv_set("gateway_boot_time", boot)
    return {"gateway_name": kv_get("gateway_name") or "QRIS Gateway",
            "qris_configured": bool(kv_get("qris_static")),
            "total_users": tu, "total_tx": tt, "paid_tx": pd, "pending_tx": pn, "expired_tx": ex,
            "total_volume": vol, "today_volume": tv,
            "success_rate": round(pd/tt*100) if tt else 0,
            "boot_time": int(boot), "now": int(time.time()*1000)}


def ep_admin_transactions(p, u):
    expire_old_topups()
    get_user_id(p, u)
    where, wparams = scoped_tid(p, u)
    status = str(p.get("status") or "all")
    limit = min(100, max(10, int(p.get("limit") or 30)))
    offset = max(0, int(p.get("offset") or 0))
    with _db_lock, db() as c:
        if status == "all":
            rows = c.execute(f"SELECT * FROM qris_topups WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                             (*wparams, limit, offset)).fetchall()
            total = c.execute(f"SELECT COUNT(*) c FROM qris_topups WHERE {where}", wparams).fetchone()["c"]
        else:
            rows = c.execute(f"SELECT * FROM qris_topups WHERE {where} AND status=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                             (*wparams, status, limit, offset)).fetchall()
            total = c.execute(f"SELECT COUNT(*) c FROM qris_topups WHERE {where} AND status=?", (*wparams, status)).fetchone()["c"]
    items = []
    for r in rows:
        uid = r["user_id"]
        username = None
        items.append({"id": r["id"], "username": username,
              "user_masked": "***"+str(uid)[-3:] if uid else "–",
              "amount": r["amount"], "unique_code": r["unique_code"],
              "total": r["total"], "status": r["status"],
              "created_at": r["created_at"], "paid_at": r["paid_at"]})
    return {"items": items, "total": total, "offset": offset, "limit": limit}


def ep_admin_notifications(p, u):
    get_user_id(p, u)
    require_admin(p, u)
    limit = min(100, max(10, int(p.get("limit") or 30)))
    with _db_lock, db() as c:
        rows = c.execute("SELECT id, amount, raw_text, matched_topup_id, created_at FROM qris_notifications ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    items = [{"id": r["id"], "amount": r["amount"], "text": r["raw_text"],
              "matched_topup_id": r["matched_topup_id"], "created_at": r["created_at"]} for r in rows]
    return {"items": items}


def ep_admin_pending(p, u):
    require_admin(p, u)
    with _db_lock, db() as c:
        rows = c.execute("SELECT id,user_id,amount,unique_code,total,created_at FROM qris_topups"
                         " WHERE status='pending' ORDER BY created_at DESC LIMIT 50").fetchall()
    return {"items": [dict(r) for r in rows]}


def ep_admin_approve(p, u):
    require_admin(p, u)
    _id = int(p.get("id") or 0)
    action = str(p.get("action") or "approve")
    if not _id:
        raise EpError("ID tidak valid.", "BAD_INPUT")
    with _db_lock, db() as c:
        t = c.execute("SELECT * FROM qris_topups WHERE id=?", (_id,)).fetchone()
        if not t:
            raise EpError("Topup tidak ditemukan.", "NOT_FOUND")
        if t["status"] != "pending":
            raise EpError("Sudah diproses.", "ALREADY")
        now = int(time.time()*1000)
        if action == "reject":
            c.execute("UPDATE qris_topups SET status='cancelled' WHERE id=?", (_id,))
            return {"ok": True, "action": "rejected"}
        c.execute("UPDATE qris_topups SET status='paid',paid_at=? WHERE id=?", (now, _id))
    credit(t["user_id"], t["amount"])
    return {"ok": True, "action": "approved", "amount": t["amount"]}


def ep_internal_secret(p, u):
    require_admin(p, u)
    if p.get("check"):
        return {"set": bool(kv_get("internal_secret"))}
    if p.get("reveal"):
        return {"secret": kv_get("internal_secret") or ""}
    if p.get("hash"):
        s = kv_get("internal_secret") or ""
        return {"hash": hashlib.sha256(s.encode()).hexdigest()[:12] if s else ""}
    if p.get("del"):
        kv_set("internal_secret", "")
        return {"ok": True, "deleted": True}
    secret = str(p.get("secret") or "").strip()
    if len(secret) < 16:
        raise EpError("Secret minimal 16 karakter.", "BAD_INPUT")
    kv_set("internal_secret", secret)
    return {"ok": True}


def ep_internal_create(p, u):
    is_global, uid = check_secret(p)
    if is_global:
        # Terima user_id (baru) atau telegram_id (legacy, dimapping)
        target_uid = int(p.get("user_id") or 0)
        if not target_uid and p.get("telegram_id"):
            tid = int(p.get("telegram_id"))
            with _db_lock, db() as c:
                r = c.execute("SELECT user_id FROM qris_users WHERE telegram_id=?", (tid,)).fetchone()
                target_uid = r["user_id"] if r else _get_or_create_user_for_tid(c, tid)
        if not target_uid:
            raise EpError("user_id wajib.", "BAD_INPUT")
    else:
        # Secret per-user: paksa ke ID user sendiri (dari secret, bukan dari caller)
        target_uid = uid
    return new_topup(target_uid, p.get("amount"), p.get("merchant_name"))


def ep_internal_status(p, u):
    check_secret(p)  # (is_global, uid) - validasi saja
    _id = int(p.get("id") or 0)
    if not _id:
        raise EpError("ID tidak valid.", "BAD_INPUT")
    with _db_lock, db() as c:
        t = c.execute("SELECT * FROM qris_topups WHERE id=?", (_id,)).fetchone()
        if not t:
            raise EpError("Tidak ditemukan.", "NOT_FOUND")
        now = int(time.time()*1000)
        if t["status"] == "pending" and now - t["created_at"] > 30*60000:
            c.execute("UPDATE qris_topups SET status='expired' WHERE id=?", (_id,))
            t = dict(t); t["status"] = "expired"
        t = dict(t)
    return {"id": t["id"], "user_id": t["user_id"], "amount": t["amount"],
            "total": t["total"], "status": t["status"], "paid_at": t["paid_at"]}


def ep_internal_pending(p, u):
    check_secret(p)  # (is_global, uid) - validasi saja
    with _db_lock, db() as c:
        rows = c.execute("SELECT id,user_id,amount,unique_code,total,created_at FROM qris_topups"
                         " WHERE status='pending' ORDER BY created_at DESC LIMIT 100").fetchall()
    return {"items": [dict(r) for r in rows]}


def ep_internal_pending_by_user(p, u):
    is_global, uid = check_secret(p)
    if not is_global:
        # Secret per-user: paksa ke ID sendiri
        target_uid = uid
    else:
        target_uid = int(p.get("user_id") or 0)
        if not target_uid and p.get("telegram_id"):
            # Legacy: mapping telegram_id -> user_id
            tid = int(p.get("telegram_id"))
            with _db_lock, db() as c:
                r = c.execute("SELECT user_id FROM qris_users WHERE telegram_id=?", (tid,)).fetchone()
                target_uid = r["user_id"] if r else 0
        if not target_uid:
            raise EpError("user_id wajib.", "BAD_INPUT")
    with _db_lock, db() as c:
        rows = c.execute("SELECT id,amount,unique_code,total,status,created_at FROM qris_topups"
                         " WHERE user_id=? AND status IN ('pending','paid')"
                         " ORDER BY created_at DESC LIMIT 20", (target_uid,)).fetchall()
    return {"items": [dict(r) for r in rows]}


def ep_internal_approve(p, u):
    check_secret(p)  # (is_global, uid) - validasi saja
    _id = int(p.get("id") or 0)
    no_credit = bool(p.get("no_credit"))
    if not _id:
        raise EpError("ID tidak valid.", "BAD_INPUT")
    with _db_lock, db() as c:
        t = c.execute("SELECT * FROM qris_topups WHERE id=?", (_id,)).fetchone()
        if not t:
            raise EpError("Tidak ditemukan.", "NOT_FOUND")
        if t["status"] != "pending":
            return {"ok": False, "reason": "already_processed"}
        now = int(time.time()*1000)
        c.execute("UPDATE qris_topups SET status='paid',paid_at=? WHERE id=?", (now, _id))
    if not no_credit:
        credit(t["user_id"], t["amount"])
    return {"ok": True, "amount": t["amount"], "user_id": t["user_id"]}


def ep_mutasi_notify(p, u):
    check_secret(p)  # (is_global, uid) - validasi saja
    try:
        amount = int(float(p.get("amount")))
        assert amount > 0
    except Exception:
        raise EpError("amount tidak valid.", "BAD_INPUT")
    text = str(p.get("text", ""))[:200]
    log.info("NOTIFY masuk: amount=%d text=%.80s", amount, text)
    now = int(time.time()*1000)
    with _db_lock, db() as c:
        rows = c.execute("SELECT * FROM qris_topups WHERE status='pending' AND total=?"
                         " ORDER BY created_at DESC LIMIT 1", (amount,)).fetchone()
        if not rows:
            # Cek apakah sudah pernah diproses (duplikat notifikasi)
            dup = c.execute("SELECT id FROM qris_topups WHERE status='paid' AND total=?"
                            " AND paid_at>? ORDER BY paid_at DESC LIMIT 1",
                            (amount, now - 600000)).fetchone()
            if dup:
                log.info("NOTIFY duplikat diabaikan: total=%d sudah paid id=%d", amount, dup["id"])
                c.execute("INSERT INTO qris_notifications(amount,raw_text,matched_topup_id,created_at)"
                          " VALUES(?,?,?,?)", (amount, text, dup["id"], now))
                return {"ok": True, "matched": True, "duplicate": True, "topup_id": dup["id"]}
            log.warning("NOTIFY tidak cocok: tidak ada pending dengan total=%d", amount)
            c.execute("INSERT INTO qris_notifications(amount,raw_text,matched_topup_id,created_at)"
                      " VALUES(?,?,NULL,?)", (amount, text, now))
            return {"ok": False, "matched": False,
                    "reason": f"tidak ada topup pending dengan nominal {amount}"}
        t = dict(rows)
        if now - t["created_at"] > 30*60000:
            c.execute("UPDATE qris_topups SET status='expired' WHERE id=?", (t["id"],))
            c.execute("INSERT INTO qris_notifications(amount,raw_text,matched_topup_id,created_at)"
                      " VALUES(?,?,?,?)", (amount, text, t["id"], now))
            log.warning("NOTIFY kedaluarsa: topup id=%d total=%d", t["id"], amount)
            return {"ok": False, "matched": False, "reason": "topup kedaluarsa"}
        c.execute("UPDATE qris_topups SET status='paid',paid_at=? WHERE id=?", (now, t["id"]))
        c.execute("INSERT INTO qris_notifications(amount,raw_text,matched_topup_id,created_at)"
                  " VALUES(?,?,?,?)", (amount, text, t["id"], now))
    bal = credit(t["user_id"], t["amount"])
    log.info("NOTIFY OTOMATIS OK: topup id=%d total=%d -> saldo %d", t["id"], amount, bal)
    return {"ok": True, "matched": True, "topup_id": t["id"],
            "user_id": t["user_id"], "amount": t["amount"], "balance": bal}





def ep_admin_manual_credit(p, u):
    """Kredit manual ke user dari notifikasi yang tidak cocok."""
    require_admin(p, u)
    notif_id = int(p.get("notif_id") or 0)
    username = str(p.get("username") or "").strip().lower()
    if not notif_id or not username:
        raise EpError("notif_id dan username wajib.", "BAD_INPUT")
    with _db_lock, db() as c:
        n = c.execute("SELECT * FROM qris_notifications WHERE id=?", (notif_id,)).fetchone()
        if not n:
            raise EpError("Notifikasi tidak ditemukan.", "NOT_FOUND")
        if n["matched_topup_id"]:
            raise EpError("Sudah dicocokkan.", "ALREADY")
        usr = c.execute("SELECT id, is_admin FROM users WHERE username=?", (username,)).fetchone()
        if not usr:
            raise EpError("User tidak ditemukan.", "NOT_FOUND")
        uid = usr["id"]
        now = int(time.time()*1000)
        cur = c.execute("INSERT INTO qris_topups(user_id,amount,unique_code,total,qris_string,"
                        "status,created_at,paid_at) VALUES(?,?,0,?,'manual', 'paid',?,?)",
                        (uid, n["amount"], n["amount"], now, now))
        topup_id = cur.lastrowid
        c.execute("UPDATE qris_notifications SET matched_topup_id=? WHERE id=?", (topup_id, notif_id))
    bal = credit(uid, n["amount"])
    log.info("MANUAL CREDIT: notif %d -> user %s amount %d", notif_id, username, n["amount"])
    return {"ok": True, "topup_id": topup_id, "username": username,
            "amount": n["amount"], "balance": bal}


def ep_claim_list(p, u):
    """Notifikasi belum diklaim untuk user."""
    su = p.get("_session_user")
    if not su:
        raise EpError("Belum login.", "UNAUTHORIZED")
    with _db_lock, db() as c:
        rows = c.execute("SELECT * FROM qris_notifications WHERE matched_topup_id IS NULL"
                         " AND claimed_by IS NULL"
                         " ORDER BY created_at DESC LIMIT 20").fetchall()
    return {"ok": True, "items": [dict(r) for r in rows]}


def ep_claim(p, u):
    """User klaim notifikasi."""
    su = p.get("_session_user")
    if not su:
        raise EpError("Belum login.", "UNAUTHORIZED")
    notif_id = int(p.get("notif_id") or 0)
    with _db_lock, db() as c:
        n = c.execute("SELECT * FROM qris_notifications WHERE id=?", (notif_id,)).fetchone()
        if not n or n["matched_topup_id"] or n["claimed_by"]:
            raise EpError("Sudah diklaim.", "ALREADY")
        c.execute("UPDATE qris_notifications SET claimed_by=?, claimed_at=? WHERE id=?",
                  (su["id"], int(time.time()*1000), notif_id))
    return {"ok": True}


def ep_admin_claims(p, u):
    """Admin lihat klaim menunggu persetujuan."""
    require_admin(p, u)
    with _db_lock, db() as c:
        rows = c.execute("SELECT n.*, us.username FROM qris_notifications n"
                         " JOIN users us ON n.claimed_by=us.id"
                         " WHERE n.matched_topup_id IS NULL AND n.claimed_by IS NOT NULL"
                         " ORDER BY n.claimed_at DESC LIMIT 50").fetchall()
    return {"ok": True, "items": [dict(r) for r in rows]}


def ep_admin_claim_process(p, u):
    """Admin setujui/tolak klaim."""
    require_admin(p, u)
    notif_id = int(p.get("notif_id") or 0)
    action = str(p.get("action") or "")  # approve | reject
    with _db_lock, db() as c:
        n = c.execute("SELECT * FROM qris_notifications WHERE id=?", (notif_id,)).fetchone()
        if not n or not n["claimed_by"] or n["matched_topup_id"]:
            raise EpError("Tidak valid.", "BAD_INPUT")
        if action == "reject":
            c.execute("UPDATE qris_notifications SET claimed_by=NULL, claimed_at=NULL WHERE id=?",
                      (notif_id,))
            return {"ok": True, "action": "rejected"}
        # Approve: kredit ke user yang klaim
        usr = c.execute("SELECT id, is_admin FROM users WHERE id=?", (n["claimed_by"],)).fetchone()
        uid = usr["id"]
        now = int(time.time()*1000)
        cur = c.execute("INSERT INTO qris_topups(user_id,amount,unique_code,total,qris_string,"
                        "status,created_at,paid_at) VALUES(?,?,0,?,'manual-claim','paid',?,?)",
                        (uid, n["amount"], n["amount"], now, now))
        topup_id = cur.lastrowid
        c.execute("UPDATE qris_notifications SET matched_topup_id=? WHERE id=?",
                  (topup_id, notif_id))
    bal = credit(uid, n["amount"])
    return {"ok": True, "action": "approved", "topup_id": topup_id, "balance": bal}


ENDPOINTS = {
    "whoami": ep_whoami, "balance_get": ep_balance_get,
    "topup_create": ep_topup_create, "topup_confirm": ep_topup_confirm, "topup_cancel": ep_topup_cancel,
    "topup_list": ep_topup_list, "gateway_name": ep_gateway_name,
    "qris_config": ep_qris_config, "admin_stats": ep_admin_stats,
    "admin_transactions": ep_admin_transactions, "admin_notifications": ep_admin_notifications, "admin_pending": ep_admin_pending,
    "admin_approve": ep_admin_approve, "admin_charts": ep_admin_charts,
    "internal_secret": ep_internal_secret,
    "internal_create": ep_internal_create, "internal_status": ep_internal_status,
    "internal_pending": ep_internal_pending, "internal_approve": ep_internal_approve,
    "internal_pending_by_user": ep_internal_pending_by_user,
    "internal_merchant_name": ep_internal_merchant_name,
    "mutasi_notify": ep_mutasi_notify, "admin_notifications": ep_admin_notifications,
    "admin_manual_credit": ep_admin_manual_credit,
    "claim_list": ep_claim_list, "claim": ep_claim,
    "admin_claims": ep_admin_claims, "admin_claim_process": ep_admin_claim_process,
    "login": ep_login, "register": ep_register, "logout": ep_logout,
    "me": ep_me, "change_password": ep_change_password,
    "settled_balance": ep_settled_balance, "user_profile": ep_user_profile,
    "withdraw_request": ep_withdraw_request, "withdraw_list": ep_withdraw_list,
    "admin_withdrawals": ep_admin_withdrawals, "admin_withdraw_process": ep_admin_withdraw_process,
    "api_secret": ep_api_secret, "user_qris": ep_user_qris,
}

MIME = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
        ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg",
        ".svg": "image/svg+xml", ".ico": "image/x-icon"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj, cookie=None):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        self.send_header("Server", "QRIS-Gateway")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/health":
            return self._json(200, {"ok": True, "service": "qris-gateway"})
        # static files
        rel = path.lstrip("/") or "index.html"
        if ".." in rel:
            return self._json(404, {"ok": False})
        fp = os.path.join(STATIC_DIR, rel)
        if os.path.isdir(fp):
            fp = os.path.join(fp, "index.html")
        if not os.path.isfile(fp):
            # SPA fallback
            fp = os.path.join(STATIC_DIR, "index.html")
            if not os.path.isfile(fp):
                return self._json(404, {"ok": False})
        ext = os.path.splitext(fp)[1].lower()
        try:
            with open(fp, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._json(500, {"ok": False})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not path.startswith("/api/"):
            return self._json(404, {"ok": False, "reason": "unknown"})
        name = path[5:]
        fn = ENDPOINTS.get(name)
        if not fn:
            return self._json(404, {"ok": False, "reason": "unknown endpoint"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 2 * 1024 * 1024:  # tolak body > 2MB (anti memory-exhaustion)
                return self._json(413, {"ok": False, "error": "payload terlalu besar"})
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json(400, {"ok": False, "error": "bad json"})
        init_user = verify_init_data(payload.pop("_initData", ""))
        # Terima token dari body (_session_token) atau cookie (gw_session)
        _tok = payload.pop("_session_token", None)
        _cookie = self.headers.get("Cookie")
        if _tok and "gw_session=" not in (_cookie or ""):
            _cookie = f"gw_session={_tok}"
        payload["_session_user"] = get_session_user(_cookie)
        payload["_client_ip"] = self.client_address[0] if self.client_address else "?"
        # Rate limit untuk endpoint sensitif
        if name in ("login", "register", "mutasi_notify"):
            if not rate_limit(payload["_client_ip"], 15, 60):
                return self._json(429, {"ok": False, "error": "Terlalu banyak permintaan, coba lagi."})
        if name == "logout":
            destroy_session(self.headers.get("Cookie"))
        try:
            result = fn(payload, init_user)
            cookie = None
            if isinstance(result, dict):
                cookie = result.pop("_set_cookie", None)
                if result.pop("_clear_cookie", None):
                    cookie = "gw_session=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax"
            if isinstance(result, dict) and "ok" not in result and "error" not in result:
                result = {"ok": True, **result}
            self._json(200, result, cookie)
        except EpError as e:
            code = 401 if e.code in ("UNAUTHORIZED", "FORBIDDEN") else 400
            self._json(code, {"ok": False, "error": str(e), "code": e.code})
            log.warning("EP %s: %s [%s]", name, e, e.code)
        except Exception as e:
            log.exception("EP %s error", name)
            self._json(500, {"ok": False, "error": "internal error"})


if __name__ == "__main__":
    init_db()
    if not BOT_TOKEN:
        log.warning("BOT_TOKEN kosong — verifikasi Telegram nonaktif (mode dev)")
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log.info("Gateway jalan di port %s (admin=%s)", PORT, ADMIN_ID)
    srv.serve_forever()
