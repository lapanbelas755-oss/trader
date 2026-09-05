# Real Market Data Acquisition & Dataset Validation V1 Contract

## 1. Architectural Purpose & Separation Principle

The **Real Market Data Acquisition & Dataset Validation Engine V1** is strictly separated from the **Historical Research & Dataset Engine**:

$$\text{Data Acquisition (Validated Source Dataset)} \longrightarrow \text{Research Engine (Historical Setup Discovery)}$$

- **Data Acquisition**: Responsible for ingesting raw external data (CSV, JSON, JSONL, Parquet), parsing and normalizing explicit timezones to UTC, performing mathematical quality audits, identifying gaps without fabricating synthetic candles, generating deterministic content hashes, and persisting immutable provenance in PostgreSQL.
- **Data Research**: Consumes the validated, immutable dataset to discover structural market events and setup occurrences.

Under no circumstances does Data Acquisition alter historical source prices or synthesize missing market candles.

---

## 2. Canonical Hashing & Bitwise Reproducibility

Every dataset is assigned an immutable, content-based canonical hash:
$$\text{ContentHash} = \text{SHA-256}(\text{SortedCanonicalRows})$$

### Canonical Formatting Standard:
- **Timestamp**: ISO 8601 UTC with strict `Z` suffix (`YYYY-MM-DDTHH:MM:SSZ`).
- **Symbol**: Normalized uppercase string (e.g. `EURUSD`).
- **Timeframe**: Normalized uppercase string (e.g. `M5`).
- **Numeric Fields**: Exact decimal formatting (`.6f` for prices, `.4f` for volumes).
- **Row-Order Independence**: All canonical row strings are sorted lexicographically before hashing.
  - Two datasets containing identical records in different file row orders produce **identical** hashes.
  - Modifying even a single price digit produces a **different** hash.

---

## 3. Strict Timezone Normalization (UTC Only)

- All internal Trader Machine timestamps are strictly timezone-aware UTC (`tzinfo=timezone.utc`).
- Source datasets **must** specify an explicit timezone (e.g., `UTC`, `Asia/Jakarta`, `America/New_York`, `UTC+2`).
- Datasets with missing, ambiguous, or unknown timezones are **strictly REJECTED**.

---

## 4. Mathematical Data Quality Checks

| Check Name | Mathematical / Logical Constraint | Action on Violation |
| :--- | :--- | :--- |
| **OHLC Consistency** | $High \ge \max(Open, Close, Low)$<br>$Low \le \min(Open, Close, High)$<br>$High \ge Low$<br>$Open > 0, Close > 0, High > 0, Low > 0$ | REJECTED |
| **Bid / Ask Validity** | $Bid > 0, Ask > 0$<br>$Ask \ge Bid$<br>$Spread = Ask - Bid$ | REJECTED |
| **Volume Validity** | $Volume \ge 0$ | REJECTED |
| **Duplicate Rows** | Exact duplicates: Identical timestamp, symbol, and prices.<br>Conflicting duplicates: Same timestamp, different prices. | Exact: Discarded with WARNING.<br>Conflicting: REJECTED. |
| **Symbol Consistency** | All rows must match expected symbol (case-insensitive). | REJECTED |
| **Gap Detection** | Delta between consecutive candles $> \text{expected step}$. | Logged in report with WARNING.<br>**ZERO synthetic candles fabricated.** |

---

## 5. Non-Fabrication Policy

When expected market intervals are missing:
1. The gap is recorded with: `start`, `end`, `duration_seconds`, `expected_rows`, `actual_rows = 0`.
2. The engine **never** forward-fills prices, interpolates values, or manufactures synthetic candles.

---

## 6. Provider-Specific & Non-Global Liquidity Disclaimers

### Forex Spot Volume Disclaimer:
> "FOREX SPOT VOLUME SPECIFICATION: tick_volume != real traded volume; tick_volume != buyer volume; tick_volume != seller volume; tick_volume != institutional volume. It represents source-specific observed tick activity only."

### No Global Liquidity Claim:
> "NO GLOBAL LIQUIDITY CLAIM: Forex spot trading is decentralized and fragmented. This dataset captures only observed prices and tick counts from the designated provider/source. It does not represent global FX market volume, aggregate interbank liquidity, or institutional order flow."

---

## 7. Operational CLI Developer Command & Ingestion Workflow

### CLI Command
```bash
python -m core.data_source import \
  --file <PATH_TO_DATA_FILE> \
  --symbol EURUSD \
  --timeframe M5 \
  --timezone UTC \
  --source-name EXTERNAL_HISTORICAL \
  --mapping generic \
  --chunk-size 5000 \
  --output-manifest manifest.json
```

### Dry Run Flag (`--dry-run`)
- Executes full file reading, column mapping, timezone conversion to UTC, mathematical OHLC validation, gap identification, and SHA-256 canonical hashing.
- Guaranteed zero database side-effects (no records written to `market_datasets`, `market_data_quality_reports`, or `market_candles`).

### Atomic Transaction Safety & Rollback
- Ingestion executes within an atomic database transaction.
- Ingestion inserts into `market_datasets`, `market_data_quality_reports`, and chunked `market_candles`.
- If any error occurs during ingestion or insertion, the entire transaction is rolled back cleanly. No partial datasets are ever left in the database.

