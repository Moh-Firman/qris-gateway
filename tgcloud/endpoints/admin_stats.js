// admin_stats — statistik dashboard (publik, bisa dilihat semua user)
import { db } from 'sdk';
import { sql, eq } from 'sdk/db';
import { qris_topups, qris_users } from '../schema.js';
import { getUserId, kvGet, kvSet } from '../lib/auth.js';

export default async function (input, ctx) {
  getUserId(ctx); // hanya butuh login, tidak harus admin

  const totalUsers = await db.select({ c: sql`COUNT(*)` }).from(qris_users).get();
  const totalTx = await db.select({ c: sql`COUNT(*)` }).from(qris_topups).get();
  const paidTx = await db.select({ c: sql`COUNT(*)` }).from(qris_topups).where(eq(qris_topups.status, 'paid')).get();
  const pendingTx = await db.select({ c: sql`COUNT(*)` }).from(qris_topups).where(eq(qris_topups.status, 'pending')).get();
  const volume = await db.select({ s: sql`COALESCE(SUM(${qris_topups.amount}),0)` }).from(qris_topups).where(eq(qris_topups.status, 'paid')).get();
  const todayVol = await db.select({ s: sql`COALESCE(SUM(${qris_topups.amount}),0)` }).from(qris_topups)
    .where(sql`${qris_topups.status} = 'paid' AND ${qris_topups.paid_at} > ${Date.now() - 86400000}`).get();

  // Uptime: sejak pertama kali stats diakses
  let bootTime = await kvGet('gateway_boot_time');
  if (!bootTime) { bootTime = String(Date.now()); await kvSet('gateway_boot_time', bootTime); }

  const gwName = await kvGet('gateway_name') || 'QRIS Gateway';
  const qrisSet = !!(await kvGet('qris_static'));

  return {
    gateway_name: gwName,
    qris_configured: qrisSet,
    total_users: Number(totalUsers?.c || 0),
    total_tx: Number(totalTx?.c || 0),
    paid_tx: Number(paidTx?.c || 0),
    pending_tx: Number(pendingTx?.c || 0),
    total_volume: Number(volume?.s || 0),
    today_volume: Number(todayVol?.s || 0),
    success_rate: totalTx?.c ? Math.round((paidTx.c / totalTx.c) * 100) : 0,
    boot_time: Number(bootTime),
    now: Date.now(),
  };
}
