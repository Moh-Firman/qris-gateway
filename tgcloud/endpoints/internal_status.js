// internal_status — cek status topup (auth via secret)
import { db, EndpointError } from 'sdk';
import { eq } from 'sdk/db';
import { qris_topups } from '../schema.js';
import { kvGet } from '../lib/auth.js';

export default async function (input, ctx) {
  const secret = String(input?.secret || '').trim();
  const expected = await kvGet('internal_secret');
  if (!expected || secret !== expected) throw new EndpointError('Unauthorized', { code: 'UNAUTHORIZED' });

  const id = Number(input?.id);
  if (!id) throw new EndpointError('ID tidak valid.', { code: 'BAD_INPUT' });
  const t = await db.select().from(qris_topups).where(eq(qris_topups.id, id)).get();
  if (!t) throw new EndpointError('Tidak ditemukan.', { code: 'NOT_FOUND' });
  // Auto-expire
  if (t.status === 'pending' && Date.now() - t.created_at > 30 * 60000) {
    await db.update(qris_topups).set({ status: 'expired' }).where(eq(qris_topups.id, id)).run();
    t.status = 'expired';
  }
  return { id: t.id, telegram_id: t.telegram_id, amount: t.amount, total: t.total, status: t.status, paid_at: t.paid_at || null };
}
