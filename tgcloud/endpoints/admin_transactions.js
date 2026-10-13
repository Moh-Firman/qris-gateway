// admin_transactions — riwayat transaksi (publik, telegram_id disamarkan)
import { db } from 'sdk';
import { desc, sql } from 'sdk/db';
import { qris_topups } from '../schema.js';
import { getUserId } from '../lib/auth.js';

export default async function (input, ctx) {
  getUserId(ctx); // hanya butuh login
  const status = String(input?.status || 'all'); // all|pending|paid|expired|cancelled
  const limit = Math.min(100, Math.max(10, Number(input?.limit) || 30));
  const offset = Math.max(0, Number(input?.offset) || 0);

  let where = sql`1=1`;
  if (status !== 'all') where = sql`${qris_topups.status} = ${status}`;

  const rows = await db.select().from(qris_topups).where(where)
    .orderBy(desc(qris_topups.created_at)).limit(limit).offset(offset).all();
  const total = await db.select({ c: sql`COUNT(*)` }).from(qris_topups).where(where).get();

  return {
    items: rows.map(r => ({
      id: r.id,
      // Samarkan telegram_id untuk publik: tampil 3 digit terakhir saja
      user_masked: '***' + String(r.telegram_id).slice(-3),
      amount: r.amount, unique_code: r.unique_code, total: r.total,
      status: r.status, created_at: r.created_at, paid_at: r.paid_at || null,
    })),
    total: Number(total?.c || 0), offset, limit,
  };
}
