import { table, integer, text, index } from 'sdk/db';

// Topup QRIS dengan kode unik per transaksi
export const qris_topups = table('qris_topups', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  telegram_id: integer('telegram_id').notNull(),
  amount: integer('amount').notNull(), // nominal asli (tanpa kode unik)
  unique_code: integer('unique_code').notNull(), // 3 digit kode unik
  total: integer('total').notNull(), // amount + unique_code (yang harus dibayar)
  qris_string: text('qris_string').notNull(), // QRIS dinamis
  status: text('status').notNull().default('pending'), // pending|paid|expired|cancelled
  created_at: integer('created_at').notNull(),
  paid_at: integer('paid_at'),
}, (t) => ({
  userIdx: index('idx_qris_user').on(t.telegram_id),
  statusIdx: index('idx_qris_status').on(t.status),
}));

// Saldo user (terpisah dari store utama)
export const qris_users = table('qris_users', {
  telegram_id: integer('telegram_id').primaryKey(),
  balance: integer('balance').notNull().default(0),
  created_at: integer('created_at').notNull(),
});

// Key-value untuk konfigurasi (QRIS statis merchant, dll)
export const kv_store = table('kv_store', {
  key: text('key').primaryKey(),
  value: text('value').notNull(),
});
