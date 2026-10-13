// topup_confirm — user konfirmasi sudah bayar → AI auto-approve, saldo langsung masuk
import { db, EndpointError } from 'sdk';
import { eq } from 'sdk/db';
import { qris_topups, qris_users } from '../schema.js';
import { getUserId } from '../lib/auth.js';

export default async function (input, ctx) {
  const tid = getUserId(ctx);
  const id = Number(input?.id);
  if (!id) throw new EndpointError('ID tidak valid.', { code: 'BAD_INPUT' });

  const topup = await db.select().from(qris_topups).where(eq(qris_topups.id, id)).get();
  if (!topup) throw new EndpointError('Topup tidak ditemukan.', { code: 'NOT_FOUND' });
  if (topup.telegram_id !== tid) throw new EndpointError('Bukan milikmu.', { code: 'FORBIDDEN' });
  if (topup.status !== 'pending') throw new EndpointError('Sudah diproses.', { code: 'ALREADY' });

  // Cek kedaluwarsa (30 menit)
  if (Date.now() - topup.created_at > 30 * 60000) {
    await db.update(qris_topups).set({ status: 'expired' }).where(eq(qris_topups.id, id)).run();
    throw new EndpointError('QRIS kedaluwarsa, buat baru.', { code: 'EXPIRED' });
  }

  // Auto-approve: langsung tambah saldo
  const now = Date.now();
  let user = await db.select().from(qris_users).where(eq(qris_users.telegram_id, tid)).get();
  if (!user) {
    await db.insert(qris_users).values({ telegram_id: tid, balance: topup.amount, created_at: now }).run();
  } else {
    await db.update(qris_users).set({ balance: user.balance + topup.amount }).where(eq(qris_users.telegram_id, tid)).run();
  }
  await db.update(qris_topups).set({ status: 'paid', paid_at: now }).where(eq(qris_topups.id, id)).run();

  const updated = await db.select().from(qris_users).where(eq(qris_users.telegram_id, tid)).get();
  return { ok: true, amount: topup.amount, balance: updated.balance };
}
