"""Command Line Interface for Real Market Dataset Ingestion & Validation.
Provides developer commands for validating, inspecting, and importing historical market files.
"""
import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from core.data_source.contract import DataFormat
from core.data_source.importer import MarketDataImporter


def create_parser() -> argparse.ArgumentParser:
    """Construct command line arguments parser."""
    parser = argparse.ArgumentParser(
        prog="trader-machine data-source",
        description="Trader Machine V1 — Real Market Data Acquisition & Ingestion CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 'import' subcommand
    import_parser = subparsers.add_parser("import", help="Import or validate a real market dataset file")
    import_parser.add_argument("--file", "-f", required=True, help="Path to input data file (CSV, JSON, JSONL, Parquet)")
    import_parser.add_argument("--symbol", "-s", default="EURUSD", help="Expected trading symbol (default: EURUSD)")
    import_parser.add_argument("--timeframe", "-t", default="M5", help="Target timeframe (default: M5)")
    import_parser.add_argument("--timezone", "-z", default="UTC", help="Source data timezone (e.g. UTC, Asia/Jakarta) (default: UTC)")
    import_parser.add_argument("--source-name", default="EXTERNAL_HISTORICAL", help="Provider / feed name (default: EXTERNAL_HISTORICAL)")
    import_parser.add_argument("--dataset-name", default=None, help="Explicit unique dataset name (optional)")
    import_parser.add_argument("--mapping", default="generic", choices=["generic", "mt5", "dukascopy", "generic_tick"], help="Column mapping profile (default: generic)")
    import_parser.add_argument("--format", default=None, choices=["csv", "json", "jsonl", "parquet"], help="Explicit data format (optional, auto-detected by default)")
    import_parser.add_argument("--dry-run", action="store_true", help="Perform parsing and validation without writing to database")
    import_parser.add_argument("--output-manifest", default=None, help="Optional filepath to save manifest JSON")
    import_parser.add_argument("--chunk-size", type=int, default=5000, help="Database batch insert chunk size (default: 5000)")

    return parser


def format_cli_output(summary: dict) -> str:
    """Format the required standardized output string."""
    lines = [
        f"Dataset: {summary.get('dataset_name')}",
        f"Source: {summary.get('source_name')}",
        f"Symbol: {summary.get('symbol')}",
        f"Timeframe: {summary.get('timeframe')}",
        f"Timezone: {summary.get('timezone')}",
        f"First timestamp: {summary.get('first_timestamp') or 'NONE'}",
        f"Last timestamp: {summary.get('last_timestamp') or 'NONE'}",
        f"Rows: {summary.get('row_count')}",
        f"Hash: {summary.get('content_hash')}",
        f"Quality: {summary.get('quality_status')}",
        f"Warnings: {summary.get('warnings_count')}",
        f"Errors: {summary.get('errors_count')}",
    ]
    if summary.get("dry_run"):
        lines.append("Mode: DRY_RUN (No records inserted into database)")
    elif summary.get("status") == "EXISTING_DATASET":
        lines.append(f"Status: EXISTING_DATASET (id={summary.get('dataset_id')})")
    elif summary.get("status") == "IMPORTED":
        lines.append(f"Status: IMPORTED (id={summary.get('dataset_id')})")
    elif summary.get("status") == "REJECTED":
        lines.append("Status: REJECTED (Data validation failure, no records imported)")

    return "\n".join(lines)


def main(args: Optional[Sequence[str]] = None) -> int:
    """CLI entrypoint."""
    parser = create_parser()
    parsed_args = parser.parse_args(args)

    if parsed_args.command == "import":
        format_enum = DataFormat(parsed_args.format.upper()) if parsed_args.format else None
        importer = MarketDataImporter()
        try:
            summary = importer.import_dataset(
                source_file=parsed_args.file,
                symbol=parsed_args.symbol,
                timeframe=parsed_args.timeframe,
                timezone_str=parsed_args.timezone,
                source_name=parsed_args.source_name,
                dataset_name=parsed_args.dataset_name,
                mapping_profile=parsed_args.mapping,
                data_format=format_enum,
                dry_run=parsed_args.dry_run,
                chunk_size=parsed_args.chunk_size,
                output_manifest_path=parsed_args.output_manifest,
            )
            output = format_cli_output(summary)
            print(output)
            if summary.get("status") == "REJECTED":
                return 1
            return 0
        except Exception as e:
            print(f"ERROR: Import failed: {e}", file=sys.stderr)
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
