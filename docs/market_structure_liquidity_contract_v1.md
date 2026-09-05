# MARKET STRUCTURE & LIQUIDITY CONTRACT V1 — TRADER MACHINE

## 1. CORE PHILOSOPHY & LAW

```text
"Structure is a sequence of confirmed swing points and the market's response to those points."
```

Market Structure & Liquidity Detector Engine V1 adalah mesin **observasi murni** (*Pure Observation Engine*). Engine ini bertugas mendeskripsikan kondisi geometris dan struktural pasar secara objektif dan matematis.

### Aturan Semantik Kritis:
* **Observasi vs Inferensi:** Engine mencatat apa yang teramati secara langsung di grafik harga (*Observed/Derived*). Engine dilarang berspekulasi bahwa "bank sedang membeli" atau "institusi sedang menjebak ritel".
* **Likuiditas vs Support/Resistance:** Likuiditas adalah titik konsentrasi acuan harga (swing highs/lows, session extremes, day/week boundaries, equal highs/lows) di mana order pasar cenderung terkumpul. Likuiditas bukan sekadar garis horizontal support/resistance statis.
* **Sweep vs Reversal:** Sebuah liquidity sweep **BUKAN** sinyal pembalikan arah (*reversal*). Sweep hanyalah penetrasi batas likuiditas yang kembali ke dalam rentang. Reversal memerlukan konfirmasi struktural independen.
* **BOS & CHoCH vs Buy/Sell:** Break of Structure (BOS) dan Change of Character (CHoCH) adalah observasi mekanis perubahan struktur harga, **BUKAN** sinyal entry BUY atau SELL.

---

## 2. TIMEFRAME HIERARCHY

Sesuai Law #3, struktur pasar dianalisis melalui hierarki tiga tingkat:
* **H1 (Macro Structure):** Menentukan tren dan batasan struktural makro.
* **M15 (Context Structure):** Menentukan konteks pergerakan dan swing intermedier.
* **M5 (Confirmation Structure):** Menentukan konfirmasi pergeseran struktur mikro dan eksekusi displacement.
*(M1 tidak digunakan sebagai struktur primer pada V1 guna menghindari noise acak microstructure).*

---

## 3. SWING DETECTION & MANDATORY CONFIRMATION DELAY

### A. Parameter Fraktal
* Default: `left_bars = 2`, `right_bars = 2` (dapat dikonfigurasi).

### B. Aturan Deteksi
* **Swing High pada bar $t$:**
  $$High[t] > High[t-1] \quad \text{dan} \quad High[t] > High[t-2]$$
  $$High[t] > High[t+1] \quad \text{dan} \quad High[t] > High[t+2]$$
* **Swing Low pada bar $t$:**
  $$Low[t] < Low[t-1] \quad \text{dan} \quad Low[t] < Low[t-2]$$
  $$Low[t] < Low[t+1] \quad \text{dan} \quad Low[t] < Low[t+2]$$

### C. Mandatory Confirmation Delay (Causality Enforcement)
Sebuah swing pada bar $t$ **TIDAK DIKETAHUI** pada saat bar $t$ terjadi.
Swing tersebut baru terkonfirmasi secara formal pada saat bar $t + \text{right\_bars}$ selesai ditutup (*closed*).
* Penyimpanan mencakup dua penanda waktu:
  1. `swing_timestamp`: Waktu candle fraktal $t$ terjadi.
  2. `confirmed_at`: Waktu candle $t + \text{right\_bars}$ ditutup, yaitu saat sistem pertama kali mengamati swing tersebut secara kausal.
* Engine dilarang keras menggunakan swing point sebelum waktu `confirmed_at`.

---

## 4. SWING CLASSIFICATION (HH / HL / LH / LL)

Klasifikasi dilakukan dengan membandingkan swing point terkonfirmasi saat ini terhadap swing point terkonfirmasi sebelumnya dari tipe yang sama:

* **Swing High:**
  * $High_t > High_{prev} \implies \mathbf{HH}$ (Higher High)
  * $High_t < High_{prev} \implies \mathbf{LH}$ (Lower High)
* **Swing Low:**
  * $Low_t > Low_{prev} \implies \mathbf{HL}$ (Higher Low)
  * $Low_t < Low_{prev} \implies \mathbf{LL}$ (Lower Low)

*Aturan Immutabilitas:* Klasifikasi swing bersifat historis dan tidak boleh diubah secara surut (*retroactively rewritten*) oleh pergerakan harga di masa depan.

---

## 5. EQUAL HIGHS (EQH) & EQUAL LOWS (EQL)

Dua atau lebih swing high/low yang berdekatan tidak harus memiliki harga yang persis identik sampai desimal terakhir.

### Tolerance Formula:
$$|Price_A - Price_B| \le \text{tolerance}$$
* **Volatility-aware Tolerance:**
  $$\text{tolerance} = 0.05 \times ATR(M5)$$
* **Deterministic Fallback:** Jika ATR belum tersedia (warmup), gunakan fallback fixed minimum step: `0.00010` (1.0 pip untuk pasangan mata uang 5-digit EURUSD) atau `0.01` untuk JPY.

EQH/EQL mencerminkan kumpulan likuiditas yang signifikan (*resting orders pool*).

---

## 6. STRUCTURE DIRECTION

Arah struktur pada suatu timeframe ditentukan dari urutan konfirmasi swing:
* **`BULLISH`**: Urutan suksesi Higher Highs dan Higher Lows ($\dots \to HL \to HH$).
* **`BEARISH`**: Urutan suksesi Lower Lows dan Lower Highs ($\dots \to LH \to LL$).
* **`MIXED`**: Terjadi konflik swing (misal HH diikuti LL atau LH diikuti HL).
* **`TRANSITION`**: Struktur sedang mengalami potensi patahan atau transisi karakter awal.
* **`UNDEFINED`**: Data belum cukup untuk membentuk sekuens dua swing highs dan dua swing lows.

---

## 7. BREAK OF STRUCTURE (BOS) VS CHANGE OF CHARACTER (CHoCH)

### A. Break of Structure (BOS)
BOS adalah penembusan level struktural yang **SEARAH** dengan tren struktural yang sedang berjalan.
* **Bullish BOS:** Harga ditutup (**Close Candle**) di atas level Swing High terkonfirmasi sebelumnya dalam struktur Bullish.
* **Bearish BOS:** Harga ditutup (**Close Candle**) di bawah level Swing Low terkonfirmasi sebelumnya dalam struktur Bearish.
* **Wick Rule:** Penetrasi ekor (wick) tanpa candle close **BUKAN** BOS.
* **Displacement Rule:**
  $$\text{break\_distance} = |Close - \text{level}| \ge 0.10 \times ATR(M5)$$
  *(Parameter dapat dikonfigurasi; fallback 0.00010 jika ATR belum cukup).*

### B. Change of Character (CHoCH)
CHoCH adalah penembusan level struktural yang **BERLAWANAN** dengan tren struktural yang sedang berjalan, menandakan potensi perubahan karakter pasar.
* **`CHoCH_DOWN`:** Dalam struktur Bullish ($HH \to HL \to HH$), harga ditutup dengan displacement di bawah level $HL$ terkonfirmasi sebelumnya.
* **`CHoCH_UP`:** Dalam struktur Bearish ($LL \to LH \to LL$), harga ditutup dengan displacement di atas level $LH$ terkonfirmasi sebelumnya.

### C. Pembeda Mutlak BOS vs CHoCH:
* Jika penembusan memperpanjang tren aktif $\implies \mathbf{BOS}$.
* Jika penembusan mematahkan titik tumpu tren aktif $\implies \mathbf{CHoCH}$.
* Satu peristiwa candle tidak boleh menghasilkan BOS dan CHoCH secara bersamaan pada timeframe yang sama.

---

## 8. STRUCTURE STRENGTH

Kekuatan struktur diukur secara deterministik tanpa probabilitas atau sinyal:
$$\text{strength} = \text{clamp}\left(0.5 \times \frac{\text{displacement}}{ATR} + 0.3 \times \frac{\text{swing\_distance}}{ATR} + 0.2 \times \text{persistence\_count}, \ 0.0, \ 10.0\right)$$
* *Catatan:* Strength adalah skor intensitas momentum struktural numerik, **BUKAN** probabilitas kemenangan (*win rate*) dan tidak boleh dikonversi menjadi keyakinan trading.

---

## 9. MULTI-TIMEFRAME ALIGNMENT (H1, M15, M5)

Status multi-timeframe digabungkan secara kausal:
* **`ALIGNED_BULLISH`**: H1 == BULLISH, M15 == BULLISH, M5 == BULLISH.
* **`ALIGNED_BEARISH`**: H1 == BEARISH, M15 == BEARISH, M5 == BEARISH.
* **`MIXED`**: Terdapat pertentangan arah antar timeframe.
* **`TRANSITION`**: Satu timeframe mengalami CHoCH aktif sementara timeframe makro masih netral/belum mengonfirmasi.
* **`UNDEFINED`**: Satu atau lebih timeframe belum memiliki data struktural yang cukup.

Timeframe yang lebih rendah **tidak boleh** menimpa arah timeframe yang lebih tinggi secara semena-mena.

---

## 10. LIQUIDITY LEVEL ENGINE & TAXONOMY

Tipe level likuiditas yang dideteksi:
1. **`PREVIOUS_DAY_HIGH` (PDH)** & **`PREVIOUS_DAY_LOW` (PDL)**: High dan Low dari hari perdagangan kalender sebelumnya yang sudah selesai ditutup (00:00 - 23:59:59 UTC).
2. **`PREVIOUS_WEEK_HIGH` (PWH)** & **`PREVIOUS_WEEK_LOW` (PWL)**: High dan Low dari minggu perdagangan sebelumnya (Senin 00:00 UTC - Jumat 23:59:59 UTC).
3. **`SESSION_HIGH`** & **`SESSION_LOW`**: Ekstrem dari sesi perdagangan yang terdefinisi:
   * **`ASIA`**: 00:00 - 08:00 UTC
   * **`LONDON`**: 07:00 - 15:30 UTC
   * **`NEW_YORK`**: 12:00 - 20:30 UTC
   *(Semua waktu berbasis UTC timezone-aware; bebas dari bias timezone lokal OS).*
4. **`EQUAL_HIGH` (EQH)** & **`EQUAL_LOW` (EQL)**.
5. **`SIGNIFICANT_SWING_HIGH`** & **`SIGNIFICANT_SWING_LOW`**.

---

## 11. LIQUIDITY LIFECYCLE STATE MACHINE

Setiap level likuiditas memiliki siklus hidup yang tegas:
```text
UNTOUCHED ──> APPROACHED ──> TOUCHED ──> SWEPT ──> REJECTED
                                │          │
                                │          └───> ACCEPTED
                                └───> INVALIDATED (Expired)
```

1. **`UNTOUCHED`**: Level aktif baru teridentifikasi dan harga belum mendekatinya.
2. **`APPROACHED`**: Harga berada dalam jarak $0.20 \times ATR(M5)$ dari level.
3. **`TOUCHED`**: Harga mencapai level dalam batas toleransi $\le 0.05 \times ATR(M5)$.
4. **`SWEPT` (Liquidity Sweep):**
   * Penetrasi harga melampaui level likuiditas dengan kedalaman:
     $$0.05 \times ATR(M5) \le \text{sweep\_depth} \le 0.50 \times ATR(M5)$$
   * Harga kemudian kembali menyeberangi level tersebut dalam maksimal 3 candle M5.
5. **`REJECTED` (Rejection):**
   * Setelah terjadi Sweep, harga kembali menyeberangi level dan membentuk perpindahan berlawanan (*displacement away*):
     $$\text{rejection\_distance} \ge 0.30 \times ATR(M5)$$
6. **`ACCEPTED` (Acceptance):**
   * Harga menembus level dan bertahan di luar level minimal 2 closed candle M5.
   * Disertai follow-through directional displacement $\ge 0.30 \times ATR(M5)$.
   * Penetrasi wick saja tanpa close di luar level tidak memenuhi syarat acceptance.
7. **`INVALIDATED`**: Level kedaluwarsa sesuai masa berlakunya (misal sesi trading telah selesai, atau hari perdagangan telah berganti ke hari berikutnya).
