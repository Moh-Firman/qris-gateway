// admin_pending — ADMIN: daftar topup menunggu
import { db } from 'sdk';
import { desc, eq } from 'sdk/db';
import { qris_topups } from '../schema.js';
import { requireAdmin } from '../lib/auth.js';

export default async function (input, ctx) {
  requireAdmin(ctx);
  const rows = await db.select().from(qris_topups)
    .where(eq(qris_topups.status, 'pending'))
    .orderBy(desc(qris_topups.created_at)).limit(50).all();
  return { items: rows.map(r => ({
    id: r.id, telegram_id: r.telegram_id, amount: r.amount,
    unique_code: r.unique_code, total: r.total, created_at: r.created_at,
  })) };
}
