// internal_pending — untuk checker VPS: daftar topup pending (auth via secret)
import { db, EndpointError } from 'sdk';
import { desc, eq } from 'sdk/db';
import { qris_topups } from '../schema.js';
import { kvGet } from '../lib/auth.js';

export default async function (input, ctx) {
  const secret = String(input?.secret || '').trim();
  const expected = await kvGet('internal_secret');
  if (!expected || secret !== expected) throw new EndpointError('Unauthorized', { code: 'UNAUTHORIZED' });

  const rows = await db.select().from(qris_topups)
    .where(eq(qris_topups.status, 'pending'))
    .orderBy(desc(qris_topups.created_at)).limit(100).all();
  return { items: rows.map(r => ({
    id: r.id, telegram_id: r.telegram_id, amount: r.amount,
    unique_code: r.unique_code, total: r.total, created_at: r.created_at,
  })) };
}
