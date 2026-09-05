# DATA INGESTION CONTRACT V1 — TRADER MACHINE

## 1. CORE PRINCIPLE

```text
NEVER CONFUSE OBSERVED WITH INFERRED
```

Trader Machine adalah sistem penelitian berbasis bukti (evidence-driven). Data yang masuk ke dalam sistem harus memiliki batasan klasifikasi yang tegas dan tidak boleh mencampurkan fakta pasar langsung dengan asumsi atau spekulasi.

---

## 2. DATA CLASSIFICATION TAXONOMY

Setiap data point yang diproses dalam ingestion pipeline diklasifikasikan ke dalam 4 kategori absolut:

### A. OBSERVED (Langsung Teramati)
Data mentah yang tercatat secara eksplisit dan langsung ada pada file sumber atau stream data pasar tanpa manipulasi interpretatif.
* **`timestamp`**: Waktu aktual terjadinya tick/quote yang dicatat oleh penyedia data/broker.
* **`symbol`**: Instrumen finansial yang diperdagangkan (contoh: `EURUSD`).
* **`bid`**: Harga beli terbaik yang tersedia di pasar saat tick tersebut.
* **`ask`**: Harga jual terbaik yang tersedia di pasar saat tick tersebut.
* **`last`**: Harga transaksi terakhir yang dieksekusi (jika tersedia dari bursa/broker, nullable).
* **`volume`**: Volume transaksi atau tick volume yang dilaporkan oleh sumber data.
* **`source`**: Identitas penyedia data (contoh: `MT5_EXNESS`, `CSV_HISTORICAL`).

### B. DERIVED (Diturunkan Secara Matematis)
Data yang dihitung melalui relasi matematis atau transformasi deterministik langsung dari data `OBSERVED`. Data ini tidak mengandung opini atau probabilitas.
* **`spread`**: `ask - bid`.
* **`tick_direction`**: Perubahan arah harga bid/ask relatif terhadap tick sebelumnya (`UP`, `DOWN`, `FLAT`).
* **`normalized_timestamp`**: Timestamp yang telah diseragamkan ke timezone UTC ISO-8601 tanpa mengubah titik waktu aslinya.

### C. INFERRED (Disimpulkan Secara Probabilistik)
Data hasil interpretasi, probabilitas statistik, model, atau hipotesis strategi. **DILARANG KERAS dimasukkan sebagai raw observation pada tabel `market_ticks`**.
* *Buyer Aggression* / *Seller Aggression*
* *Absorption*
* *Liquidity Sweep Candidate*
* *Institutional Order Flow*
* *Stop Run* / *Liquidity Trap*

### D. UNKNOWN (Tidak Diketahui / Spekulasi Tanpa Bukti)
Informasi yang tidak dapat dipastikan atau tidak ada bukti datanya di dalam rekaman pasar. Sistem dilarang mengubah hal yang UNKNOWN menjadi seolah-olah fakta.
* "Bank X sedang membeli EURUSD dalam jumlah besar"
* "Hedge fund Y sedang melakukan distribusi"
* "Market maker sengaja memburu stop loss ritel"

---

## 3. RAW DATA IMMUTABILITY POLICY

1. **No Silent Modification:** Sistem tidak boleh mengubah nilai raw secara diam-diam.
2. **No Data Fabrication:** Dilarang melakukan *price smoothing*, *noise filtering*, *interpolation*, atau membuat tick buatan (*missing tick fabrication*).
3. **Strict Validation:** Jika suatu baris data melanggar aturan matematis dasar (misal `bid <= 0` atau `ask < bid`), baris tersebut ditolak (`REJECTED`) dan dicatat dalam laporan audit integritas, bukan diperbaiki secara spekulatif.
4. **Separation of Raw and Derived:** Raw tick disimpan murni di `market_ticks`. Fitur kalkulasi (ATR, anomaly z-score, structural swing) berada di lapisan downstream terpisah.
