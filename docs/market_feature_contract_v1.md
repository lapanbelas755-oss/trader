# MARKET FEATURE CONTRACT V1 — TRADER MACHINE

## 1. CORE PRINCIPLE

```text
ALL FEATURES ARE DERIVED MEASUREMENTS — NEVER OBSERVED RAW DATA, NEVER INFERRED OPINIONS
```

Market Feature Engine V1 bertugas menjawab satu pertanyaan ilmiah:
> **"APA YANG SEDANG TERJADI PADA PASAR BERDASARKAN PENGUKURAN MATEMATIS OBJEKTIF?"**

Feature Engine **BUKAN signal engine**. Engine ini tidak menghasilkan sinyal `BUY`, `SELL`, `ENTRY`, atau `FIRE`. Seluruh output adalah murni metrik deskriptif (*derived measurements*) dari data candle historis tertutup (*closed candles*).

---

## 2. FEATURE TAXONOMY & MATHEMATICAL FORMULAS

Semua fitur di bawah ini dihitung per `(symbol, timeframe, timestamp)`.

### A. Average True Range — ATR(14)
* **Kategori:** Volatilitas Absolut
* **Input:** `High_t`, `Low_t`, `Close_{t-1}`
* **Formula True Range (TR):**
  $$TR_t = \max(High_t - Low_t, |High_t - Close_{t-1}|, |Low_t - Close_{t-1}|)$$
  *(Untuk candle pertama ketika $Close_{t-1}$ belum ada: $TR_1 = High_1 - Low_1$)*
* **Metode Smoothing:** **Wilder's RMA (Recursive Moving Average)**
  * Untuk 14 bar pertama ($t = 14$):
    $$ATR_{14} = \frac{1}{14} \sum_{i=1}^{14} TR_i$$
  * Untuk bar berikutnya ($t > 14$):
    $$ATR_t = \frac{ATR_{t-1} \times 13 + TR_t}{14}$$
* **Timeframe Riset V1:** `M5`, `M15`, `H1`
* **Lookback:** 14 periode
* **Output Unit:** Satuan harga (e.g. `0.00142` untuk EURUSD)
* **Warmup Behavior:**
  * $t < 14$: `atr = NULL`, status = `INSUFFICIENT_DATA`
  * $t \ge 14$: `atr` valid dan deterministik

---

### B. Price Response & Geometry
* **`range`**: Jarak total rentang harga candle.
  $$\text{range}_t = High_t - Low_t$$
  *Satuan: Harga ($> 0$)*
* **`body`**: Ukuran mutlak badan candle.
  $$\text{body}_t = |Close_t - Open_t|$$
  *Satuan: Harga ($\ge 0$)*
* **`price_change`**: Perubahan harga dari penutupan candle sebelumnya.
  $$\text{price\_change}_t = Close_t - Close_{t-1}$$
  *(Jika $Close_{t-1}$ tidak ada, gunakan $Close_t - Open_t$)*
  *Satuan: Harga signed ($+$ atau $-$)*
* **`movement_efficiency`**: Rasio directional displacement terhadap total range (Law #1).
  $$\text{movement\_efficiency}_t = \frac{\text{body}_t}{\text{range}_t}$$
  *Edge case:* Jika $\text{range}_t = 0$, return `0.0` (definisi neutral).
  *Range:* $[0.0, 1.0]$

---

### C. Effort vs Result (Law #4)
* **`effort`**: Aktivitas pasar yang terukur secara langsung.
  Pada V1, menggunakan `tick_volume` dari bar closed:
  $$\text{effort}_t = \text{tick\_volume}_t$$
  *Dilarang keras melabeli ini sebagai "institutional buyer volume" karena data order book institusional tidak teramati.*
* **`result`**: Hasil pergerakan harga relatif terhadap volatilitas baseline (ATR):
  $$\text{result}_t = \frac{\text{range}_t}{ATR_t} \quad (\text{jika } ATR_t > 0 \text{ else } 0.0)$$
* **`effort_result_ratio`**: Rasio upaya per unit pergerakan harga yang ternormalisasi:
  $$\text{effort\_result\_ratio}_t = \frac{\text{effort}_t}{\text{result}_t} \quad (\text{jika } \text{result}_t > 0 \text{ else NULL})$$

---

### D. Volatility & Rolling Baseline (Window = 100)
Baseline digunakan untuk membandingkan observasi saat ini terhadap 100 candle tertutup sebelumnya.
* **Contamination Prevention Rule:**
  Observasi candle saat ini ($t$) **DIKELUARKAN** dari perhitungan baseline historis:
  $$\text{baseline}_t = \text{statistics}(X_{t-100}, X_{t-99}, \dots, X_{t-1})$$
* **Statistik Baseline:**
  $$\mu = \frac{1}{100} \sum_{i=1}^{100} X_{t-i}, \quad \sigma = \sqrt{\frac{1}{100} \sum_{i=1}^{100} (X_{t-i} - \mu)^2}$$
* **`volatility`**: Menggunakan nilai $ATR_t$ atau $\text{range}_t$ saat ini.
* **`volatility_baseline`**: Nilai $\mu(\text{range}_{t-100 \dots t-1})$.

---

### E. Z-Scores (Standardized Measurement)
Standardized metric:
$$z = \frac{X_t - \mu}{\sigma}$$
*(Jika $\sigma = 0$, $z = 0.0$)*
* **`activity_zscore`**: Z-score dari $\text{effort}_t$ (`tick_volume`) relatif terhadap 100 candle sebelumnya.
* **`volatility_zscore`**: Z-score dari $\text{range}_t$ relatif terhadap 100 candle sebelumnya.
* **`price_response_zscore`**: Z-score dari $\text{result}_t$ relatif terhadap 100 candle sebelumnya.
* **Peringatan Semantik:** $z\text{-score}$ BUKAN probabilitas, BUKAN sinyal arah (`BUY`/`SELL`).

---

### F. Anomaly Candidate Flags (Law #5 & AGENTS.md Sec 7 & 11)
* **`ANOMALY_CANDIDATE`**:
  $$\text{activity\_zscore}_t \ge 2.0$$
* **`STRONG_ANOMALY`**:
  $$\text{activity\_zscore}_t \ge 2.5 \quad \text{AND} \quad \text{price\_response\_zscore}_t \le -1.5$$
  *(Upaya aktivitas volume sangat tinggi namun hasil pergerakan harga terhambat secara abnormal / absorption candidate).*
* *Catatan:* Threshold ini merupakan **Initial Research Parameters** V1 dan tidak diasumsikan pasti profit.

---

### G. Market Speed
* **`movement_speed`**: Kecepatan pergerakan harga per detik:
  $$\text{movement\_speed}_t = \frac{|\text{price\_change}_t|}{\Delta t_{\text{seconds}}}$$
* **`range_per_second`**: $\frac{\text{range}_t}{\Delta t_{\text{seconds}}}$
* **`price_change_per_second`**: $\frac{\text{price\_change}_t}{\Delta t_{\text{seconds}}}$
* *Edge cases:* Jika $\Delta t_{\text{seconds}} \le 0$ atau candle sebelumnya tidak ada, return `NULL`.

---

## 3. DATA QUALITY & STATUS TAXONOMY

Setiap baris fitur memiliki label kualitas `feature_status`:
* **`VALID`**: Jumlah data historis $\ge 114$ bar (14 bar untuk initial ATR + 100 bar baseline window). Seluruh z-score dan metrik baseline terisi penuh.
* **`WARMUP`**: $14 \le \text{bar count} < 114$. Fitur ATR dan geometri terhitung valid, tetapi baseline z-score bernilai `NULL` karena sampel baseline historis belum mencapai 100 candle.
* **`INSUFFICIENT_DATA`**: $\text{bar count} < 14$. Belum cukup data untuk membentuk ATR dasar.
* **`INVALID`**: Ditemukan anomali skema fatal atau pelanggaran invarian matematis.

---

## 4. STRICT ZERO LOOK-AHEAD POLICY

1. Fitur pada bar $t$ hanya boleh memanfaatkan informasi historis $\le t$.
2. Baseline historis untuk mengukur anomali bar $t$ secara ketat hanya menggunakan bar $t-100 \dots t-1$.
3. Dilarang menyertakan outcome masa depan, candle berikutnya, atau label klasifikasi masa depan ke dalam `market_features`.
