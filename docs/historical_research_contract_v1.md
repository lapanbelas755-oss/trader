# HISTORICAL RESEARCH & DATASET ENGINE V1 CONTRACT — TRADER MACHINE

## 1. CORE PHILOSOPHY & OBJECTIVE

```text
"Historical Research answers: 'What setups actually occurred in historical market data?'
It must NOT answer: 'Would this trade have made money?'"
```

Historical Research & Dataset Engine V1 adalah fondasi empiris pembentukan dataset penelitian (*Empirical Research Foundation*). Engine ini memproses data pasar historis riil melalui pipeline deterministik terverifikasi guna menghasilkan dataset observasi setup yang terversi (*versioned*), tidak dapat diubah (*immutable*), dan dapat direproduksi secara identik (*100% reproducible*).

### Non-Negotiable Boundaries:
* **Measures Occurrences, Not Profitability:** Engine ini mengukur dan mencatat kejadian setup teknikal. Engine **DILARANG** menghitung metrik performa atau profitabilitas (seperti win rate, profit factor, drawdown, TP, SL, PnL, expectancy). Metrik tersebut menjadi tanggung jawab eksklusif Backtest Engine di fase berikutnya.
* **Real Data Only:** Data sintetis **HANYA** diizinkan untuk unit test. Dilarang mencampur fixture sintetis ke dalam dataset riset riil.
* **Separation from Live Execution:** Engine tidak terhubung ke broker, tidak menghasilkan order eksekusi, dan tidak menggunakan machine learning.

---

## 2. END-TO-END PIPELINE ARCHITECTURE

```
RAW HISTORICAL DATA (EURUSD)
        │
        ▼
   [VALIDATION]       ──► Audits OHLC, prices, intervals, timezones (no silent fabrication)
        │
        ▼
  [NORMALIZATION]     ──► Chronological UTC sorting and decimal quantization
        │
        ▼
  [DEDUPLICATION]     ──► Elimination of redundant timestamps
        │
        ▼
[CANDLE AGGREGATION]  ──► M5, M15, H1 boundaries
        │
        ▼
  [FEATURE ENGINE]    ──► ATR, range, effort vs result, rolling z-scores
        │
        ▼
 [STRUCTURE ENGINE]   ──► Swings, BOS, CHoCH (strict confirmation delay)
        │
        ▼
 [LIQUIDITY ENGINE]   ──► Levels lifecycle (Touched, Swept, Accepted, Rejected)
        │
        ▼
   [SETUP ENGINE]     ──► S01–S05 deterministic candidates (OBSERVE -> WATCH -> ARMED -> FIRE)
        │
        ▼
 [SETUP OCCURRENCES]  ──► Snapshot of observed states tagged with chronological split
        │
        ▼
  [RESEARCH DATASET]  ──► Versioned dataset with immutable content_hash and manifest
```

---

## 3. DATASET & CONFIGURATION VERSIONING

### A. Deterministic Content Hashing
Setiap dataset memiliki `content_hash` berbasis SHA-256 yang dihitung secara kanonikal:
* Data candle diurutkan secara strictly chronological berdasarkan `timestamp` UTC.
* Setiap field finansial dinormalisasi (open, high, low, close, volume) tanpa distorsi float.
* Data identik selalu menghasilkan hash SHA-256 yang identik.

### B. Explicit Configuration Hashing
Seluruh parameter sistem dicatat secara eksplisit tanpa default tersembunyi:
* `swing_left_bars`, `swing_right_bars`
* `atr_period`, `baseline_window`
* `bos_displacement_atr_mult`, `equal_high_low_tolerance`
* `sweep_min_atr_mult`, `sweep_max_atr_mult`, `sweep_return_window`
* `rejection_displacement_atr_mult`, `acceptance_candle_count`, `acceptance_follow_through_atr_mult`
* `compression_bars`, `compression_atr_percentile`, `compression_range_percentile`
* `expansion_range_multiplier`, `expansion_volatility_zscore`
* `session_configuration`, `split_ratios`
Hash konfigurasi kanonikal (`config_hash`) dicatat di setiap run dan occurrence record.

---

## 4. CHRONOLOGICAL DATA SPLITS

Untuk mencegah kebocoran temporal (*temporal leakage*), data dibagi secara strictly sequential tanpa pengacakan (*zero random shuffling*):

$$\text{IN\_SAMPLE} \quad < \quad \text{VALIDATION} \quad < \quad \text{OUT\_OF\_SAMPLE}$$

* **Default Ratios:**
  * **IN_SAMPLE:** 60% awal dari rentang waktu
  * **VALIDATION:** 20% berikutnya
  * **OUT_OF_SAMPLE (OOS):** 20% akhir
* **Integritas Batas:** Tidak ada timestamp yang muncul di lebih dari satu split. Informasi dari OOS dilarang keras mempengaruhi kalkulasi in-sample maupun validasi.

---

## 5. DATA QUALITY & PROVENANCE

### A. Strict Data Quality Auditing
* **OHLC Consistency:** $\text{Low} \le \text{Open} \le \text{High}$ dan $\text{Low} \le \text{Close} \le \text{High}$, dengan seluruh harga $> 0$.
* **Non-negative Spreads & Volumes:** $\text{Spread} \ge 0$ dan $\text{Volume} \ge 0$.
* **Timezone Consistency:** Wajib UTC.
* **No Silent Fabrication:** Lilin yang hilang (*missing intervals*) dicatat dalam warning audit dan **TIDAK DIBUAT-BUAT** (*never fabricated*).

### B. Provenance Lineage
Setiap dataset mencatat sumber data (`source`), format (`source_format`), nama file (`source_file`), waktu impor (`imported_at`), jumlah baris (`row_count`), serta timestamp bar pertama dan terakhir.

---

## 6. RESEARCH DATABASE SCHEMA

### Tabel `research_datasets`:
* `id BIGSERIAL PRIMARY KEY`
* `dataset_name VARCHAR(64) NOT NULL`
* `symbol VARCHAR(16) NOT NULL`
* `source VARCHAR(32) NOT NULL`
* `timeframe VARCHAR(8) NOT NULL`
* `start_time TIMESTAMPTZ NOT NULL`
* `end_time TIMESTAMPTZ NOT NULL`
* `row_count BIGINT NOT NULL`
* `dataset_version VARCHAR(32) NOT NULL`
* `content_hash VARCHAR(64) NOT NULL`
* `status VARCHAR(32) NOT NULL DEFAULT 'BUILDING'`
* `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
* **Constraint:** `UNIQUE (dataset_name, dataset_version, content_hash)`

### Tabel `research_runs`:
* `id BIGSERIAL PRIMARY KEY`
* `run_id VARCHAR(64) NOT NULL UNIQUE`
* `dataset_id BIGINT REFERENCES research_datasets(id) ON DELETE CASCADE`
* `run_version VARCHAR(32) NOT NULL`
* `config_hash VARCHAR(64) NOT NULL`
* `started_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
* `completed_at TIMESTAMPTZ`
* `status VARCHAR(32) NOT NULL DEFAULT 'RUNNING'`
* `input_row_count BIGINT NOT NULL DEFAULT 0`
* `output_row_count BIGINT NOT NULL DEFAULT 0`
* `error_count INTEGER NOT NULL DEFAULT 0`

### Tabel `research_setup_occurrences`:
* `id BIGSERIAL PRIMARY KEY`
* `research_run_id BIGINT REFERENCES research_runs(id) ON DELETE CASCADE`
* `setup_id VARCHAR(64) NOT NULL`
* `setup_code VARCHAR(16) NOT NULL` ('S01', 'S02', 'S03', 'S04', 'S05')
* `symbol VARCHAR(16) NOT NULL`
* `timeframe VARCHAR(8) NOT NULL`
* `timestamp TIMESTAMPTZ NOT NULL`
* `direction VARCHAR(16) NOT NULL` ('BULLISH', 'BEARISH', 'UNDEFINED')
* `status VARCHAR(16) NOT NULL` ('OBSERVE', 'WATCH', 'ARMED', 'FIRE', 'EXPIRED', 'REJECTED')
* `regime VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN'`
* `liquidity_type VARCHAR(32)`
* `structure_type VARCHAR(32)`
* `split_type VARCHAR(16) NOT NULL DEFAULT 'IN_SAMPLE'` ('IN_SAMPLE', 'VALIDATION', 'OUT_OF_SAMPLE')
* `evidence_snapshot JSONB NOT NULL`
* `config_hash VARCHAR(64) NOT NULL`
* `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
* **Constraint:** `UNIQUE (research_run_id, setup_code, timestamp, status, direction)`

---

## 7. STRICT CAUSALITY & REPRODUCIBILITY

1. **No Look-Ahead / No Future Contamination:**
   Setup candidate pada waktu $T$ hanya boleh memanfaatkan informasi historis dengan batas waktu $\le T$. Penambahan data di masa depan ($T > T_{eval}$) tidak dapat mengubah snapshot observasi pada $T \le T_{eval}$.
2. **Reproducibility Guarantee:**
   Input historis identik + konfigurasi identik = bit-for-bit identik pada `content_hash`, `config_hash`, `occurrence_counts`, dan manifest audit.
