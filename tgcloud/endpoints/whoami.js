// whoami — info user + apakah admin (untuk sembunyikan tab admin)
import { getUserId } from '../lib/auth.js';

const ADMIN_ID = 8441388747;

export default async function (input, ctx) {
  const tid = getUserId(ctx);
  const u = ctx.initData.user || {};
  return {
    telegram_id: tid,
    first_name: u.first_name || '',
    username: u.username || '',
    is_admin: tid === ADMIN_ID,
  };
}
