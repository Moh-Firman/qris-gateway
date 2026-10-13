// mutasi_notify — terima laporan pembayaran dari HP (via notifikasi DANA)
// Body: { secret, amount, text?, sender? }
// Cari topup pending dengan total yang cocok -> auto approve + kredit saldo
import { db, EndpointError } from 'sdk';
import { eq, and, desc } from 'sdk/db';
import { qris_topups, qris_users } from '../schema.js';
import { kvGet } from '../lib/auth.js';

export default async function (input, ctx) {
  const secret = await kvGet('internal_secret');
  const inSec = String(input?.secret || '').trim();
  if (!secret || inSec !== secret) throw new EndpointError('Unauthorized', { code: 'UNAUTHORIZED' });

  const amount = Number(input?.amount);
  if (!amount || amount <= 0) throw new EndpointError('amount tidak valid');

  const db = ctx.db;
  // Cari topup pending dengan total persis, yang terbaru dulu
  const rows = await db.select().from(qris_topups)
    .where(and(eq(qris_topups.status, 'pending'), eq(qris_topups.total, amount)))
    .orderBy(desc(qris_topups.created_at)).limit(1);

  if (!rows.length) {
    return { ok: false, matched: false, reason: 'tidak ada topup pending dengan nominal ' + amount };
  }

  const t = rows[0];
  const now = Date.now();
  if (now - t.created_at > 30 * 60000) {
    await db.update(qris_topups).set({ status: 'expired' }).where(eq(qris_topups.id, t.id));
    return { ok: false, matched: false, reason: 'topup kedaluarsa' };
  }

  await db.update(qris_topups).set({ status: 'paid', paid_at: now }).where(eq(qris_topups.id, t.id));
  const u = await db.select().from(qris_users).where(eq(qris_users.telegram_id, t.telegram_id)).limit(1);
  const bal = (u[0]?.balance || 0) + t.amount;
  if (u.length) await db.update(qris_users).set({ balance: bal }).where(eq(qris_users.telegram_id, t.telegram_id));
  else await db.insert(qris_users).values({ telegram_id: t.telegram_id, balance: t.amount, created_at: now });

  // Notifikasi ke user via Telegram (best effort)
  try {
    const token = await kvGet('config:bot_token');
    if (token) {
      await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chat_id: t.telegram_id, text: `Pembayaran Rp${t.amount.toLocaleString('id-ID')} terdeteksi otomatis. Saldo: Rp${bal.toLocaleString('id-ID')}` }),
      });
    }
  } catch (e) {}

  return { ok: true, matched: true, topup_id: t.id, telegram_id: t.telegram_id, amount: t.amount, balance: bal };
}
