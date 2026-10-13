// admin_approve — ADMIN: setujui topup, saldo masuk
import { db, EndpointError } from 'sdk';
import { eq } from 'sdk/db';
import { qris_topups, qris_users } from '../schema.js';
import { requireAdmin } from '../lib/auth.js';

export default async function (input, ctx) {
  requireAdmin(ctx);
  const id = Number(input?.id);
  const action = String(input?.action || 'approve'); // approve|reject
  if (!id) throw new EndpointError('ID tidak valid.', { code: 'BAD_INPUT' });

  const topup = await db.select().from(qris_topups).where(eq(qris_topups.id, id)).get();
  if (!topup) throw new EndpointError('Topup tidak ditemukan.', { code: 'NOT_FOUND' });
  if (topup.status !== 'pending') throw new EndpointError('Sudah diproses.', { code: 'ALREADY' });

  if (action === 'reject') {
    await db.update(qris_topups).set({ status: 'cancelled' }).where(eq(qris_topups.id, id)).run();
    return { ok: true, action: 'rejected' };
  }

  // Approve: tambah saldo
  const now = Date.now();
  let user = await db.select().from(qris_users).where(eq(qris_users.telegram_id, topup.telegram_id)).get();
  if (!user) {
    await db.insert(qris_users).values({ telegram_id: topup.telegram_id, balance: topup.amount, created_at: now }).run();
  } else {
    await db.update(qris_users).set({ balance: user.balance + topup.amount }).where(eq(qris_users.telegram_id, topup.telegram_id)).run();
  }
  await db.update(qris_topups).set({ status: 'paid', paid_at: now }).where(eq(qris_topups.id, id)).run();
  return { ok: true, action: 'approved', amount: topup.amount };
}
