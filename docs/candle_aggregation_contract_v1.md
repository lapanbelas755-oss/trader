# CANDLE AGGREGATION CONTRACT V1 — TRADER MACHINE

## 1. CORE PRINCIPLE

```text
CANDLES ARE DERIVED DATA, NEVER OBSERVED RAW FACTS
```

Candlestick (OHLC) bukanlah data pasar primer, melainkan agregasi matematis yang diturunkan (*derived*) dari aliran transaksi atau kuotasi tick mentah (*observed ticks*).
Semua kalkulasi pembentukan candle harus deterministik, dapat direproduksi 100% (*reproducible*), dan bebas dari bias masa depan (*zero look-ahead bias*).

---

## 2. AGGREGATION PIPELINE

```text
market_ticks
     ↓
1. Time Bucket Allocation [bucket_start, bucket_end)
     ↓
2. Deterministic Tick Ordering (timestamp ASC, id ASC)
     ↓
3. OHLC Extraction (Price source: 'last' else 'bid')
     ↓
4. Volume Computation (tick_volume = count, real_volume = sum)
     ↓
5. Spread Computation (arithmetic mean of ask - bid)
     ↓
6. Invariant Integrity Verification
     ↓
market_candles (PostgreSQL)
```

---

## 3. CANONICAL TIMEZONE & FIXED BOUNDARIES

* **Canonical Timezone:** Seluruh waktu candle wajib menggunakan **UTC** (`timezone-aware`). Dilarang menggunakan waktu lokal sistem operasi.
* **Interval Definisi (Half-Open Interval):**
  Candle mencakup tick dengan relasi waktu:
  $$\text{bucket\_start} \le \text{tick.timestamp} < \text{bucket\_end}$$
* **Rumus Boundary (Fixed UTC):**
  * **M1:** `minute = floor(minute / 1) * 1`, durasi 60 detik (`bucket_end = bucket_start + 1m`).
  * **M5:** `minute = floor(minute / 5) * 5`, durasi 300 detik (`bucket_end = bucket_start + 5m`).
  * **M15:** `minute = floor(minute / 15) * 15`, durasi 900 detik (`bucket_end = bucket_start + 15m`).
  * **H1:** `minute = 0`, `second = 0`, durasi 3600 detik (`bucket_end = bucket_start + 1h`).

---

## 4. DETERMINISTIC OHLC EXTRACTION

Untuk setiap bucket waktu:
* **`OPEN`**: Harga dari tick valid pertama dalam bucket.
* **`HIGH`**: Harga tertinggi dari seluruh tick valid dalam bucket.
* **`LOW`**: Harga terendah dari seluruh tick valid dalam bucket.
* **`CLOSE`**: Harga dari tick valid terakhir dalam bucket.

### Aturan Sumber Harga (Price Source Hierarchy):
1. Jika tick memiliki kolom `last` bernilai numerik valid (> 0), gunakan `last`.
2. **Deterministic Fallback:** Jika `last` tidak tersedia (umum pada kuotasi Forex OTC), sistem menggunakan harga **`bid`**.
3. **Aturan Tegas:** Dilarang mencampur harga `bid` dan `ask` secara sembarangan dalam satu pembentukan OHLC (misal Open dari bid, Close dari ask) karena akan merusak konsistensi spread dan geometri candle.

---

## 5. TICK ORDERING & TIE-BREAKER

* Urutan tick dalam bucket wajib diurutkan berdasarkan `timestamp ASC`.
* **Tie-Breaker Rule:** Jika terdapat beberapa tick dengan `timestamp` persis sama (misal dalam satu milidetik), tie-breaker deterministik dilakukan menggunakan `id ASC` (database primary key) atau `source_tick_id`.
* Sistem dilarang mengandalkan *insertion order* acak dari query database.

---

## 6. VOLUME AGGREGATION

* **`tick_volume`**: Dihitung murni sebagai **jumlah (count) tick valid** yang berada dalam bucket interval.
* **`real_volume`**: Dihitung sebagai penjumlahan nilai `volume` riil dari masing-masing tick (jika disediakan oleh bursa/broker), default `0`.
* **Aturan Tegas:** Dilarang mencampur atau mengklaim `tick_volume` sebagai representasi volume riil transaksi mata uang.

---

## 7. SPREAD AGGREGATION

* Spread setiap tick dihitung sebagai: $\text{spread}_{\text{tick}} = \text{ask} - \text{bid}$.
* **Candle Spread:** Dihitung sebagai **rata-rata aritmatika** (*arithmetic mean*) dari seluruh spread tick valid di dalam interval bucket tersebut.
* Dilarang menggunakan spread dari tick terakhir saja tanpa merata-ratakannya.
* Dilarang mengisi spread menggunakan *forward-fill* dari candle sebelumnya.

---

## 8. EMPTY BUCKETS & GAPS (NO FABRICATION)

* Jika tidak terdapat tick sama sekali pada suatu interval waktu (contoh: 12:01 tidak ada aktivitas transaksi):
  **SISTEM TIDAK MEMBUAT CANDLE PALSU.**
* Dilarang membuat candle dengan $O=H=L=C=\text{previous close}$. Candle interval tersebut dinyatakan **ABSENT**.
* Ketiadaan candle dicatat sebagai observasi struktural (market gap / weekend closure) oleh lapisan integrity.

---

## 9. PARTIAL VS CLOSED CANDLES

* **Closed Candle:** Candle yang seluruh rentang waktunya $[t_{\text{start}}, t_{\text{end}})$ telah berakhir relatif terhadap batas akhir data historis.
* **Partial (Open) Candle:** Candle yang rentang waktunya masih berjalan ($t_{\text{data\_end}} < t_{\text{end}}$).
* **Batch Historical Aggregation Rule:** Default output agregasi historis hanya menerbitkan **CLOSED CANDLES**. Candle parsial di ujung data tidak boleh dicatat sebagai historical closed candle.

---

## 10. ZERO LOOK-AHEAD BIAS

* Candle pada interval $[t_{\text{start}}, t_{\text{end}})$ memiliki batas atas yang eksklusif ($< t_{\text{end}}$).
* Tick dengan waktu $\ge t_{\text{end}}$ tidak boleh mempengaruhi Open, High, Low, Close, Volume, atau Spread candle tersebut.

---

## 11. INVARIANT INTEGRITY RULES

Setiap candle yang dihasilkan wajib lolos uji invarian matematis sebelum disimpan:
1. $\text{OPEN} > 0, \text{HIGH} > 0, \text{LOW} > 0, \text{CLOSE} > 0$
2. $\text{HIGH} \ge \text{OPEN}$, $\text{HIGH} \ge \text{CLOSE}$, $\text{HIGH} \ge \text{LOW}$
3. $\text{LOW} \le \text{OPEN}$, $\text{LOW} \le \text{CLOSE}$, $\text{LOW} \le \text{HIGH}$
4. $\text{spread} \ge 0$
5. $\text{tick\_volume} \ge 1$ (karena empty bucket tidak membentuk candle)
6. $\text{real\_volume} \ge 0$

---

## 12. DATABASE UPSERT & IDEMPOTENCY

* Menggunakan constraint `UNIQUE (symbol, timeframe, timestamp)`.
* Eksekusi agregasi berulang (1x, 2x, Nx) pada dataset yang sama harus menghasilkan jumlah baris dan data yang persis identik (*strictly idempotent*).
* Status transaksi diklasifikasikan sebagai `INSERTED`, `UPDATED`, atau `UNCHANGED`.
