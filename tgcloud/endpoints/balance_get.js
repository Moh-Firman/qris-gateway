// balance_get — saldo user
import { db } from 'sdk';
import { eq } from 'sdk/db';
import { qris_users } from '../schema.js';
import { getUserId } from '../lib/auth.js';

export default async function (input, ctx) {
  const tid = getUserId(ctx);
  let user = await db.select().from(qris_users).where(eq(qris_users.telegram_id, tid)).get();
  if (!user) {
    await db.insert(qris_users).values({ telegram_id: tid, balance: 0, created_at: Date.now() }).run();
    user = { balance: 0 };
  }
  return { balance: user.balance, telegram_id: tid };
}
