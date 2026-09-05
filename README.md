# Trader Machine V1

Research-first, evidence-driven automated Forex trading research system for MetaTrader 5.

## Environment & Mode
* Mode: **RESEARCH / DEMO ONLY**
* No real money trading allowed during development.
* Risk Engine acts as a hard firewall for all operations.

## Directory Structure
* `docs/` — Architecture documentation, mathematical definitions, and research logs.
* `core/` — Core calculation engines (Price Response, Liquidity, Structure, Anomaly, Risk).
* `apps/` — Application entry points (ingestion service, CLI, monitoring).
* `strategies/` — Strategy detectors and state machines (S01–S05).
* `research/` — Historical research notebooks and statistical validation pipelines.
* `tests/` — Comprehensive test suites (unit, integration, regression).
* `database/` — Schema migrations and database models (PostgreSQL).
* `config/` — Configuration settings and environment loaders.
* `logs/` — Local runtime log output (ignored by version control).
