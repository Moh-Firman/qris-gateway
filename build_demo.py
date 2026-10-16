#!/usr/bin/env python3
"""Bangun demo/index.html dari static/index.html + shim data mock.
Demo 100% statis — tidak butuh backend, cocok di-deploy ke Vercel.
"""
import os

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")
DST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo")
DST = os.path.join(DST_DIR, "index.html")

SHIM = r"""
<script>
/* ===== MODE DEMO — semua API di-mock, tidak ada backend ===== */
(function () {
  'use strict';
  var now = Date.now();
  var D = 86400000;
  function tx(id, daysAgo, amount, status) {
    return { id: id, created_at: now - daysAgo * D - Math.floor(Math.random() * 80000) * 1000,
             username: 'user' + (1000 + id), amount: amount, total: amount,
             status: status, unique_code: 100 + (id % 800) };
  }
  var txs = [
    tx(128, 0, 50000, 'paid'), tx(127, 0, 150000, 'paid'), tx(126, 0, 25000, 'pending'),
    tx(125, 1, 100000, 'paid'), tx(124, 1, 75000, 'paid'), tx(123, 1, 200000, 'expired'),
    tx(122, 2, 50000, 'paid'), tx(121, 2, 30000, 'paid'), tx(120, 3, 100000, 'paid'),
    tx(119, 3, 50000, 'expired'), tx(118, 4, 250000, 'paid'), tx(117, 4, 50000, 'paid'),
    tx(116, 5, 150000, 'paid'), tx(115, 5, 75000, 'paid'), tx(114, 6, 100000, 'paid'),
    tx(113, 6, 50000, 'paid'),
  ];
  var notifs = [
    { created_at: now - 5 * 60000, amount: 50123, text: 'DANA: Kamu menerima Rp50.123 dari QRIS', matched: true },
    { created_at: now - 42 * 60000, amount: 150456, text: 'DANA: Kamu menerima Rp150.456 dari QRIS', matched: true },
    { created_at: now - 3 * 3600000, amount: 10000, text: 'DANA: Kamu menerima Rp10.000 dari QRIS', matched: false },
  ];
  var demoTopup = null;
  var demoUser = { id: 1, username: 'demo', is_admin: true, balance: 1250000 };

  function daily() {
    var out = [], names = ['Min','Sen','Sel','Rab','Kam','Jum','Sab'];
    for (var i = 6; i >= 0; i--) {
      var d = new Date(now - i * D);
      var vol = txs.filter(function (t) {
        var td = new Date(t.created_at);
        return td.toDateString() === d.toDateString() && t.status === 'paid';
      }).reduce(function (a, t) { return a + t.amount; }, 0);
      out.push({ date: names[d.getDay()] + ' ' + d.getDate(), volume: vol });
    }
    return out;
  }

  var paid = txs.filter(function (t) { return t.status === 'paid'; });
  var mock = {
    login: function () { return { ok: true, user: demoUser }; },
    logout: function () { return { ok: true }; },
    me: function () { return { ok: true, user: demoUser }; },
    balance_get: function () { return { ok: true, balance: demoUser.balance }; },
    admin_stats: function () {
      var vol = paid.reduce(function (a, t) { return a + t.amount; }, 0);
      var today = new Date().toDateString();
      var vol24 = paid.filter(function (t) { return new Date(t.created_at).toDateString() === today; })
                      .reduce(function (a, t) { return a + t.amount; }, 0);
      return { ok: true, total_tx: txs.length, paid_tx: paid.length,
        pending_tx: txs.filter(function (t) { return t.status === 'pending'; }).length,
        expired_tx: txs.filter(function (t) { return t.status === 'expired'; }).length,
        total_volume: vol, today_volume: vol24,
        success_rate: Math.round(paid.length / txs.length * 100) };
    },
    admin_charts: function () { return { ok: true, daily: daily() }; },
    admin_transactions: function () { return { ok: true, items: txs }; },
    admin_notifications: function () { return { ok: true, items: notifs }; },
    topup_list: function () { return { ok: true, items: txs.slice(0, 10) }; },
    topup_create: function (b) {
      var amount = Math.max(1000, Math.min(10000000, Number(b.amount) || 50000));
      var code = 100 + Math.floor(Math.random() * 800);
      demoTopup = { id: 999, topup_id: 999, amount: amount, unique_code: code,
        total: amount + code, status: 'pending', created_at: now,
        qris_string: '00020101021226610018ID.CO.QRIS.WWW01189360091431001234560215ID1234567890303UMI5204481453031005406' + (amount + code) + '5802ID5909DEMO QR6007JAKARTA61051014062070703A016304XXXX' };
      return { ok: true, topup_id: 999, id: 999, total: amount + code,
        unique_code: code, amount: amount, qris_string: demoTopup.qris_string };
    },
    topup_confirm: function () {
      return { ok: true, status: demoTopup ? demoTopup.status : 'pending',
        topup: demoTopup };
    },
    topup_cancel: function () {
      if (demoTopup) demoTopup.status = 'expired';
      return { ok: true };
    },
    qris_config: function () { return { ok: true, set: true }; },
    user_qris: function () { return { ok: true, qris_string: '' }; },
    user_profile: function () { return { ok: true, merchant_name: 'Toko Demo' }; },
    change_password: function () { return { ok: true }; },
  };

  // override fungsi api() global
  window.api = async function (name, body) {
    await new Promise(function (r) { setTimeout(r, 250); }); // simulasi latency
    var fn = mock[name];
    if (!fn) throw new Error('Demo: endpoint ' + name + ' tidak di-mock');
    return fn(body || {});
  };
  try { api = window.api; } catch (e) {}

  // banner demo + auto-login
  document.addEventListener('DOMContentLoaded', function () {
    var bar = document.createElement('div');
    bar.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:9999;background:#f59e0b;color:#1a1a1a;text-align:center;padding:8px 12px;font-size:13px;font-weight:600';
    bar.textContent = 'MODE DEMO — data contoh, tidak ada transaksi sungguhan';
    document.body.appendChild(bar);
    document.body.style.paddingTop = '36px';
    var u = document.getElementById('li-user'), p = document.getElementById('li-pass');
    if (u) u.value = 'demo';
    if (p) p.value = 'demo123';
  });
})();
</script>
"""

def main():
    with open(SRC, encoding="utf-8") as f:
        html = f.read()
    os.makedirs(DST_DIR, exist_ok=True)
    if "</body>" in html:
        html = html.replace("</body>", SHIM + "\n</body>")
    else:
        html += SHIM
    # judul demo
    html = html.replace("<title>QRIS Gateway", "<title>QRIS Gateway (Demo)")
    with open(DST, "w", encoding="utf-8") as f:
        f.write(html)
    print("demo ditulis:", DST, len(html), "bytes")

if __name__ == "__main__":
    main()
