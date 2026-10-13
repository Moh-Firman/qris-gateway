// internal_secret — ADMIN: set/cek secret untuk API internal & checker VPS
import { requireAdmin, kvSet, kvGet } from '../lib/auth.js';

export default async function (input, ctx) {
  requireAdmin(ctx);
  if (input?.check) {
    const s = await kvGet('internal_secret');
    return { set: !!s };
  }
  if (input?.reveal) {
    const s = await kvGet('internal_secret');
    return { secret: s || '' };
  }
  if (input?.hash) {
    const s = await kvGet('internal_secret');
    if (!s) return { hash: '' };
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
    const hex = [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
    return { hash: hex.slice(0, 12) };
  }
  if (input?.del) {
    await kvSet('internal_secret', '');
    return { ok: true, deleted: true };
  }
  const secret = String(input?.secret || '').trim();
  if (secret.length < 16) throw new Error('Secret minimal 16 karakter.');
  await kvSet('internal_secret', secret);
  return { ok: true };
}
