// internal_approve — untuk checker VPS: approve topup by ID (auth via secret)
import { db, EndpointError } from 'sdk';
import { eq } from 'sdk/db';
import { qris_topups, qris_users } from '../schema.js';
import { kvGet } from '../lib/auth.js';

export default async function (input, ctx) {
  const secret = String(input?.secret || '').trim();
  const expected = await kvGet('internal_secret');
  if (!expected || secret !== expected) throw new EndpointError('Unauthorized', { code: 'UNAUTHORIZED' });

  const id = Number(input?.id);
  const noCredit = !!input?.no_credit; // true = hanya tandai paid, saldo diurus pemanggil
  if (!id) throw new EndpointError('ID tidak valid.', { code: 'BAD_INPUT' });

  const topup = await db.select().from(qris_topups).where(eq(qris_topups.id, id)).get();
  if (!topup) throw new EndpointError('Tidak ditemukan.', { code: 'NOT_FOUND' });
  if (topup.status !== 'pending') return { ok: false, reason: 'already_processed' };

  const now = Date.now();
  if (!noCredit) {
    let user = await db.select().from(qris_users).where(eq(qris_users.telegram_id, topup.telegram_id)).get();
    if (!user) {
      await db.insert(qris_users).values({ telegram_id: topup.telegram_id, balance: topup.amount, created_at: now }).run();
    } else {
      await db.update(qris_users).set({ balance: user.balance + topup.amount }).where(eq(qris_users.telegram_id, topup.telegram_id)).run();
    }
  }
  await db.update(qris_topups).set({ status: 'paid', paid_at: now }).where(eq(qris_topups.id, id)).run();
  return { ok: true, amount: topup.amount, telegram_id: topup.telegram_id };
}
