// topup_list — riwayat topup user
import { db } from 'sdk';
import { desc, eq } from 'sdk/db';
import { qris_topups } from '../schema.js';
import { getUserId } from '../lib/auth.js';

export default async function (input, ctx) {
  const tid = getUserId(ctx);
  const rows = await db.select({
    id: qris_topups.id, amount: qris_topups.amount,
    unique_code: qris_topups.unique_code, total: qris_topups.total,
    status: qris_topups.status, created_at: qris_topups.created_at,
  }).from(qris_topups).where(eq(qris_topups.telegram_id, tid))
    .orderBy(desc(qris_topups.created_at)).limit(20).all();
  return { items: rows };
}
