// QRIS EMVCo generator — buat QRIS dinamis dari QRIS statis merchant
// Format: https://www.bi.go.id/QRIS/

// Hitung CRC16-CCITT (0xFFFF)
function crc16(str) {
  let crc = 0xFFFF;
  for (let i = 0; i < str.length; i++) {
    crc ^= str.charCodeAt(i) << 8;
    for (let j = 0; j < 8; j++) {
      crc = (crc & 0x8000) ? ((crc << 1) ^ 0x1021) : (crc << 1);
      crc &= 0xFFFF;
    }
  }
  return crc.toString(16).toUpperCase().padStart(4, '0');
}

// Parse EMVCo TLV: { "00": "01", "26": {...atau string}, ... }
function parseTLV(str) {
  const out = {};
  let i = 0;
  while (i + 4 <= str.length) {
    const id = str.slice(i, i + 2);
    const len = parseInt(str.slice(i + 2, i + 4), 10);
    if (isNaN(len) || i + 4 + len > str.length) break;
    out[id] = str.slice(i + 4, i + 4 + len);
    i += 4 + len;
  }
  return out;
}

function buildTLV(id, value) {
  return id + String(value.length).padStart(2, '0') + value;
}

// Buat QRIS dinamis: ganti amount + PoI jadi dynamic + hitung ulang CRC
// staticQris: string QRIS statis merchant (dari stiker QRIS)
// amount: nominal dalam rupiah (integer)
// merchantName: opsional, nama custom yang tampil saat QRIS di-scan (max 25 char)
export function makeDynamicQris(staticQris, amount, merchantName) {
  const tlv = parseTLV(staticQris.trim());
  if (tlv['00'] !== '01') throw new Error('Bukan payload QRIS valid.');
  // Point of Initiation -> 12 (dynamic)
  tlv['01'] = '12';
  // Amount (54)
  tlv['54'] = String(Math.round(amount));
  // Custom merchant name (59), max 25 karakter sesuai standar EMVCo
  if (merchantName) {
    tlv['59'] = String(merchantName).trim().slice(0, 25).toUpperCase();
  }
  // Hapus CRC lama, susun ulang tanpa 63
  delete tlv['63'];
  // Urutkan ID secara numerik untuk konsistensi
  const ids = Object.keys(tlv).sort((a, b) => Number(a) - Number(b));
  let payload = '';
  for (const id of ids) payload += buildTLV(id, tlv[id]);
  // Tambah header CRC lalu hitung
  const withCrcHeader = payload + '6304';
  const crc = crc16(withCrcHeader);
  return withCrcHeader + crc;
}

// Validasi sederhana: CRC cocok?
export function validQris(qris) {
  try {
    const s = qris.trim();
    if (s.length < 8) return false;
    const body = s.slice(0, -4);
    const crcGiven = s.slice(-4).toUpperCase();
    return crc16(body) === crcGiven;
  } catch { return false; }
}

// Ambil info merchant untuk display (nama, kota)
export function merchantInfo(qris) {
  try {
    const tlv = parseTLV(qris.trim());
    return {
      name: tlv['59'] || '',
      city: tlv['60'] || '',
      mcc: tlv['52'] || '',
    };
  } catch { return {}; }
}
