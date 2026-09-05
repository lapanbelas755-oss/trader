"""Pre-import storage safety checker for large historical market datasets.
Prevents disk exhaustion and partial imports by estimating database and temporary footprint.
"""
from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Union


class InsufficientStorageError(RuntimeError):
    """Raised when available disk space is insufficient for the incoming dataset."""
    pass


@dataclass(frozen=True)
class StorageSafetyReport:
    """Audit report assessing storage availability before data ingestion."""
    available_bytes: int
    incoming_bytes: int
    estimated_temp_bytes: int
    estimated_db_bytes: int
    total_required_bytes: int
    sufficient: bool
    path: str

    def format_summary(self) -> str:
        mb = 1024 * 1024
        return (
            f"Storage Audit for '{self.path}':\n"
            f"  Available: {self.available_bytes / mb:.2f} MB\n"
            f"  Incoming Data: {self.incoming_bytes / mb:.2f} MB\n"
            f"  Estimated Temp Space: {self.estimated_temp_bytes / mb:.2f} MB\n"
            f"  Estimated DB Growth: {self.estimated_db_bytes / mb:.2f} MB\n"
            f"  Total Required: {self.total_required_bytes / mb:.2f} MB\n"
            f"  Sufficient: {'YES' if self.sufficient else 'NO'}"
        )


class StorageSafetyChecker:
    """Validates filesystem capacity prior to launching dataset import operations."""

    @staticmethod
    def check_storage_safety(
        target_path: Union[str, Path] = ".",
        incoming_bytes: int = 0,
        temp_multiplier: float = 1.5,
        db_multiplier: float = 3.0,
        min_free_margin_bytes: int = 50 * 1024 * 1024,  # 50 MB minimum buffer
    ) -> StorageSafetyReport:
        """Evaluate whether target path filesystem has adequate space for import.
        
        Args:
            target_path: Filesystem path to inspect.
            incoming_bytes: Size of the incoming raw file(s) in bytes.
            temp_multiplier: Estimated buffer for temporary parsing buffers.
            db_multiplier: Estimated PostgreSQL storage growth factor (tables + indexes).
            min_free_margin_bytes: Mandatory safety reserve that must remain free.
        """
        p = Path(target_path).resolve()
        if not p.exists():
            p = p.parent

        usage = shutil.disk_usage(p)
        available = usage.free

        estimated_temp = int(incoming_bytes * temp_multiplier)
        estimated_db = int(incoming_bytes * db_multiplier)
        total_required = incoming_bytes + estimated_temp + estimated_db + min_free_margin_bytes

        sufficient = available >= total_required

        report = StorageSafetyReport(
            available_bytes=available,
            incoming_bytes=incoming_bytes,
            estimated_temp_bytes=estimated_temp,
            estimated_db_bytes=estimated_db,
            total_required_bytes=total_required,
            sufficient=sufficient,
            path=str(p),
        )

        if not sufficient:
            mb = 1024 * 1024
            raise InsufficientStorageError(
                f"Insufficient disk space on '{p}'. "
                f"Available: {available / mb:.2f} MB, Required: {total_required / mb:.2f} MB. "
                f"Import operation halted to protect database and disk integrity."
            )

        return report
