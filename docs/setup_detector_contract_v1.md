# SETUP DETECTOR ENGINE V1 CONTRACT — TRADER MACHINE

## 1. CORE PHILOSOPHY & SCIENTIFIC PRINCIPLE

```text
"The engine answers: 'Does the current market state satisfy the deterministic definition of one of our known setup archetypes?'
It must never answer: 'Will price go up?' or 'BUY/SELL now.'"
```

Setup Detector Engine V1 adalah mesin identifikasi kondisi pasar terstruktur (*Deterministic Pattern Recognition & Setup Candidacy Engine*). Engine ini mengubah data pasar yang teramati secara matematis (candles, features, structure, liquidity) menjadi kandidat setup terdefinisi.

### Strict Non-Negotiable Boundaries:
* **No Trading Orders:** Engine ini **TIDAK** mengeksekusi order broker, tidak membuka posisi, dan tidak mengirim sinyal transaksi.
* **No Profitability Assumptions:** Engine tidak berasumsi bahwa sebuah setup pasti untung (*profitability is a hypothesis to be researched, not an assumption*).
* **No Probability / Win-Rate Claims:** Dilarang keras menambahkan atribut peluang (*win rate*, *probability score*, atau *expected win percentage*).
* **No Machine Learning / Black Box:** Semua aturan adalah deterministik, transparan, dan berbasis bukti observasional terukur.
* **Separation from Risk Engine:** State `FIRE` hanya berarti bahwa seluruh kondisi dan konfirmasi setup telah terpenuhi secara teknikal. Sinyal ini nantinya harus melalui **Risk Firewall** independen sebelum dipertimbangkan untuk eksekusi.

---

## 2. SETUP STATE MACHINE & LIFECYCLE

Setiap setup candidate diatur oleh state machine deterministik:

```
    [OBSERVE]
        │
        ▼
     [WATCH] ────► [EXPIRED] / [REJECTED]
        │
        ▼
     [ARMED] ────► [EXPIRED] / [REJECTED]
        │
        ▼
      [FIRE]
```

### Definisi State:
1. **`OBSERVE`**: Kondisi prasyarat awal mulai terbentuk (misal: likuiditas didekati/disentuh, volatilitas rendah membentuk kompresi).
2. **`WATCH`**: Kejadian pemicu telah terjadi (misal: sweep likuiditas, candle breakout ditutup, anomali terdeteksi). Sistem menunggu validasi fase berikutnya (return, acceptance, expansion).
3. **`ARMED`**: Validasi awal berhasil (rejection displacement tercapai, acceptance follow-through tercapai, failed expectation terkonfirmasi). Setup siap menunggu konfirmasi struktur.
4. **`FIRE`**: Seluruh kondisi setup, konfirmasi struktur (BOS/CHoCH), dan kondisi eksekusi (spread normal) telah terpenuhi 100%.
5. **`EXPIRED`**: Jendela waktu konfirmasi (default: 3 closed M5 candles) terlampaui tanpa tercapainya syarat transisi berikutnya.
6. **`REJECTED`**: Terjadi pembatalan eksplisit (misal: penembusan melebihi kedalaman sweep maksimum, harga langsung berbalik menembus level breakout, atau arah bertentangan keras dengan Higher Timeframe).

### Historical Immutability:
Sistem tidak pernah mengubah (*overwrite*) histori observasi setup di masa lalu berdasarkan kejadian di masa depan. Transisi status dicatat sebagai peristiwa terpisah dengan timestamp aktualnya.

---

## 3. THE FIVE SETUP ARCHETYPES

### S01 — Liquidity Sweep Reversal
* **Konsep:**
  $$\text{LIQUIDITY} \longrightarrow \text{SWEEP} \longrightarrow \text{REJECTION} \longrightarrow \text{FAILED EXPECTATION} \longrightarrow \text{STRUCTURE SHIFT} \longrightarrow \text{FIRE}$$
* **Candidate Liquidity:** PDH, PDL, PWH, PWL, Session High/Low, Equal High/Low, Significant Swing High/Low.
* **Sweep Penetration:** $0.05 \times ATR_{M5} \le \text{Depth} \le 0.50 \times ATR_{M5}$.
* **Return Window:** Harga harus ditutup kembali melintasi level likuiditas dalam maksimal 3 candle M5.
* **Rejection Displacement:** Displacement menjauhi level $\ge 0.30 \times ATR_{M5}$.
* **Failed Expectation:** Penembusan gagal membentuk acceptance pada sisi breakout.
* **Structure Confirmation:** Pergeseran struktur M5 searah reversal (CHoCH atau BOS) dengan displacement $\ge 0.10 \times ATR_{M5}$.

---

### S02 — Liquidity Acceptance Continuation
* **Konsep:**
  $$\text{BREAK} \longrightarrow \text{ACCEPTANCE} \longrightarrow \text{FOLLOW THROUGH} \longrightarrow \text{STRUCTURE CONTINUATION} \longrightarrow \text{FIRE}$$
* **Break:** Candle ditutup di luar level likuiditas dengan displacement $\ge 0.10 \times ATR_{M5}$ (penetrasi wick saja diabaikan).
* **Acceptance:** Minimal 2 closed candle M5 berturut-turut bertahan di sisi breakout.
* **Follow-through:** Displacement tambahan $\ge 0.30 \times ATR_{M5}$ searah breakout.
* **Immediate Invalidation:** Candle yang kembali ditutup melintasi level secara langsung membatalkan setup (`REJECTED`).
* **HTF Filter:** Arah Higher Timeframe (H1/M15) tidak boleh berlawanan keras dengan arah setup.
* **Structure Confirmation:** Konfirmasi pergerakan struktur kelanjutan (BOS searah).

---

### S03 — Failed Breakout Trap
* **Konsep:**
  $$\text{BREAKOUT} \longrightarrow \text{FAILURE} \longrightarrow \text{RETURN} \longrightarrow \text{STRUCTURE SHIFT} \longrightarrow \text{REVERSAL (FIRE)}$$
* **Break:** Candle ditutup di luar level likuiditas $\ge 0.10 \times ATR_{M5}$.
* **Failure:** Harga berbalik dan ditutup melintasi kembali level tersebut dalam kurun waktu $\le 3$ closed candle M5.
* **Opposite Displacement:** Terjadi displacement ke arah berlawanan $\ge 0.30 \times ATR_{M5}$.
* **Structure Shift:** Konfirmasi pembalikan struktur M5 ke arah berlawanan (CHoCH / opposite BOS) $\ge 0.10 \times ATR_{M5}$.

---

### S04 — Effort vs Result Anomaly
* **Konsep:**
  $$\text{HIGH EFFORT} + \text{DISPROPORTIONATELY SMALL RESULT} \longrightarrow \text{ANOMALY CANDIDATE} \longrightarrow \text{CONTEXT} \longrightarrow \text{CONFIRMATION} \longrightarrow \text{FIRE}$$
* **Prinsip Semantik Law #4:** Tick activity **BUKAN** volume beli atau jual institusional. Ini adalah proksi matematis intensitas transaksi.
* **Anomaly Candidate:**
  $$\text{activity\_zscore} \ge 2.0 \quad \text{dan} \quad \text{price\_response\_zscore} \le -1.0$$
* **Strong Anomaly:**
  $$\text{activity\_zscore} \ge 2.5 \quad \text{dan} \quad \text{price\_response\_zscore} \le -1.5$$
* **Contextual Confirmation Requirement:** Anomali berdiri sendiri **DILARANG FIRE**. Wajib memiliki minimal satu konfirmasi kontekstual:
  1. Interaksi likuiditas (level approached/touched/swept).
  2. Kegagalan struktur (*structure failure / rejection*).
  3. Ekspektasi gagal (*failed expectation / pinbar / doji with large effort*).
* **Directional Confirmation:** Terjadi konfirmasi arah pergerakan melalui candle searah atau pergeseran struktur.

---

### S05 — Compression $\longrightarrow$ Expansion
* **Konsep:**
  $$\text{COMPRESSION (TIGHT RANGE)} \longrightarrow \text{VOLATILITY EXPANSION} \longrightarrow \text{DIRECTIONAL BREAK} \longrightarrow \text{ACCEPTANCE} \longrightarrow \text{FIRE}$$
* **Compression:**
  $$\text{ATR Percentile} \le 20\% \quad \text{dan} \quad \text{Range Percentile} \le 25\% \quad (\text{durasi} \ge 10 \text{ candle M5})$$
* **Expansion:**
  $$\text{Current Range} \ge 1.5 \times \text{Median Historical Range} \quad \text{dan} \quad \text{volatility\_zscore} \ge 1.5$$
* **Directional Prerequisites:** Ekspansi sendiri **BUKAN** sinyal. Diperlukan:
  1. Penembusan batas likuiditas / rentang kompresi.
  2. Struktur konfirmasi searah ekspansi.
  3. Acceptance & Follow-through $\ge 0.30 \times ATR_{M5}$.

---

## 4. AUDITABLE EVIDENCE STRUCTURE

Setiap setup memaparkan objek `evidence` yang transparan dan dapat diaudit secara independen:

```json
{
  "liquidity": "SWEPT",
  "price_response": "STRONG_REJECTION",
  "structure": "CHOCH_DOWN",
  "anomaly": null,
  "trap": "FAILED_ACCEPTANCE",
  "regime": "HIGH_VOLATILITY",
  "confirmation": "VALID",
  "execution": "ACCEPTABLE",
  "metrics": {
    "sweep_depth": "0.000350",
    "rejection_displacement": "0.000450",
    "structure_displacement": "0.000200"
  }
}
```

---

## 5. DATABASE ARCHITECTURE

### Tabel `setups`:
* `id BIGSERIAL PRIMARY KEY`
* `setup_id VARCHAR(64) NOT NULL`
* `setup_code VARCHAR(16) NOT NULL` ('S01', 'S02', 'S03', 'S04', 'S05')
* `symbol VARCHAR(16) NOT NULL`
* `timeframe VARCHAR(8) NOT NULL DEFAULT 'M5'`
* `timestamp TIMESTAMPTZ NOT NULL`
* `direction VARCHAR(16) NOT NULL` ('BULLISH', 'BEARISH', 'UNDEFINED')
* `regime VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN'`
* `liquidity_type VARCHAR(32)`
* `structure_type VARCHAR(32)`
* `anomaly_type VARCHAR(32)`
* `status VARCHAR(16) NOT NULL` ('OBSERVE', 'WATCH', 'ARMED', 'FIRE', 'EXPIRED', 'REJECTED')
* `reason TEXT`
* `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
* `expires_at TIMESTAMPTZ`
* **Constraint Idempotensi:** `UNIQUE (symbol, timeframe, setup_code, timestamp, status, direction)`

### Tabel `setup_evidence`:
* `id BIGSERIAL PRIMARY KEY`
* `setup_id VARCHAR(64) NOT NULL`
* `evidence_key VARCHAR(64) NOT NULL`
* `evidence_value VARCHAR(128) NOT NULL`
* `numeric_value NUMERIC(16, 6)`
* `details JSONB`
* `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
* **Constraint:** `UNIQUE (setup_id, evidence_key)`

---

## 6. STRICT CAUSALITY & NO LOOK-AHEAD GUARANTEE

Evaluasi setup pada bar bertanda waktu $T$ hanya berhak mengakses informasi dengan batas waktu:
$$\text{Data Timestamp} \le T$$

Untuk swing points dan event struktur pasar, engine menggunakan penanda waktu `confirmed_at` ($\le T$). Penambahan data masa depan di $T > T_{eval}$ terbukti secara matematis **TIDAK MENGUBAH** keputusan historis setup yang telah dibuat pada $T \le T_{eval}$.
