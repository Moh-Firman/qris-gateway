// gateway_name — get publik, set khusus admin
import { EndpointError } from 'sdk';
import { getUserId, requireAdmin, kvGet, kvSet } from '../lib/auth.js';

export default async function (input, ctx) {
  if (input?.name !== undefined) {
    requireAdmin(ctx); // hanya admin yang bisa ubah
    const name = String(input.name).trim().slice(0, 50);
    if (!name) throw new EndpointError('Nama tidak boleh kosong.', { code: 'BAD_INPUT' });
    await kvSet('gateway_name', name);
    return { ok: true, name };
  }
  getUserId(ctx);
  return { name: await kvGet('gateway_name') || 'QRIS Gateway' };
}
