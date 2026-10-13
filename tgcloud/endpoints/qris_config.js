// qris_config — GET publik (info merchant), SET khusus admin
import { EndpointError } from 'sdk';
import { getUserId, requireAdmin, kvSet, kvGet } from '../lib/auth.js';
import { validQris, merchantInfo } from '../lib/qris.js';

export default async function (input, ctx) {
  if (input?.get) {
    getUserId(ctx); // info publik untuk semua user login
    const saved = await kvGet('qris_static');
    return { configured: !!saved, merchant: saved ? merchantInfo(saved) : null };
  }
  requireAdmin(ctx); // hanya admin yang bisa set
  const qris = String(input?.qris || '').trim();
  if (input?.get) {
    const saved = await kvGet('qris_static');
    return { configured: !!saved, merchant: saved ? merchantInfo(saved) : null };
  }
  if (!qris) throw new EndpointError('QRIS tidak boleh kosong.', { code: 'BAD_INPUT' });
  if (!validQris(qris)) throw new EndpointError('QRIS tidak valid (CRC salah).', { code: 'BAD_QRIS' });
  await kvSet('qris_static', qris);
  return { ok: true, merchant: merchantInfo(qris) };
}
