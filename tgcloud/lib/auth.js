// Auth helper + KV
import { db, EndpointError } from 'sdk';
import { eq } from 'sdk/db';
import { kv_store } from '../schema.js';

const ADMIN_ID = 8441388747;

export function getUserId(ctx) {
  const uid = ctx?.initData?.user?.id;
  if (!uid) throw new EndpointError('Unauthorized', { code: 'UNAUTHORIZED' });
  return Number(uid);
}

export function requireAdmin(ctx) {
  const uid = getUserId(ctx);
  if (uid !== ADMIN_ID) throw new EndpointError('Akses ditolak.', { code: 'FORBIDDEN' });
  return uid;
}

export async function kvGet(key) {
  const row = await db.select().from(kv_store).where(eq(kv_store.key, key)).get();
  return row?.value || null;
}

export async function kvSet(key, value) {
  await db.insert(kv_store).values({ key, value }).onConflictDoUpdate({
    target: kv_store.key, set: { value },
  }).run();
}
