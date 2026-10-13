// internal_create — buat topup QRIS untuk sistem lain (auth via secret)
// Dipakai Mxthz Store agar topup-nya lewat gateway ini.
import { db, EndpointError } from 'sdk';
import { sql } from 'sdk/db';
import { qris_topups } from '../schema.js';
import { kvGet } from '../lib/auth.js';
import { makeDynamicQris } from '../lib/qris.js';

export default async function (input, ctx) {
  const secret = String(input?.secret || '').trim();
  const expected = await kvGet('internal_secret');
  if (!expected || secret !== expected) throw new EndpointError('Unauthorized', { code: 'UNAUTHORIZED' });

  const telegram_id = Number(input?.telegram_id);
  const amount = Math.round(Number(input?.amount));
  if (!telegram_id) throw new EndpointError('telegram_id wajib.', { code: 'BAD_INPUT' });
  if (!amount || amount < 10000) throw new EndpointError('Minimal Rp10.000.', { code: 'BAD_AMOUNT' });
  if (amount > 10000000) throw new EndpointError('Maksimal Rp10.000.000.', { code: 'BAD_AMOUNT' });

  const staticQris = await kvGet('qris_static');
  if (!staticQris) throw new EndpointError('QRIS merchant belum dikonfigurasi.', { code: 'NOT_CONFIGURED' });

  let unique_code, total, tries = 0;
  do {
    unique_code = 100 + Math.floor(Math.random() * 900);
    total = amount + unique_code;
    const existing = await db.select().from(qris_topups)
      .where(sql`${qris_topups.total} = ${total} AND ${qris_topups.status} = 'pending'`)
      .get();
    if (!existing) break;
    tries++;
  } while (tries < 20);
  if (tries >= 20) throw new EndpointError('Gagal generate kode unik.', { code: 'RETRY' });

  const qris_string = makeDynamicQris(staticQris, total, input?.merchant_name);
  const now = Date.now();
  const ins = await db.insert(qris_topups).values({
    telegram_id, amount, unique_code, total, qris_string,
    status: 'pending', created_at: now,
  }).run();

  return { id: ins.lastInsertRowid, amount, unique_code, total, qris_string, expires_at: now + 30 * 60000 };
}
