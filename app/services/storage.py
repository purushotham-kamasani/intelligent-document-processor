"""Storage layer — interface + local-disk implementation.

The interface mirrors the shape an S3/GCS backend would have, so the storage
can be swapped without touching the pipeline. We just don't ship an S3 driver
to keep the demo dependency-free.
"""

from __future__ import annotations

import hashlib
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

import aiofiles

from app.core.exceptions import StorageError
from app.core.logging import get_logger

_logger = get_logger(__name__)


class StorageBackend(ABC):
    @abstractmethod
    async def save(self, data: bytes, filename: str) -> tuple[str, str]:
        """Persist bytes. Returns (storage_path, sha256)."""

    @abstractmethod
    async def read(self, storage_path: str) -> bytes:
        """Read previously-saved bytes."""

    @abstractmethod
    async def delete(self, storage_path: str) -> None:
        """Delete a stored file. No-op if missing."""


class LocalDiskStorage(StorageBackend):
    """Stores files on the local filesystem under `base_path`."""

    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def save(self, data: bytes, filename: str) -> tuple[str, str]:
        # Path = <base>/<uuid>/<safe filename>. Keeps name for humans,
        # uuid avoids collisions.
        sha256 = hashlib.sha256(data).hexdigest()
        sub = uuid.uuid4().hex
        safe = _safe_filename(filename)
        target_dir = self.base_path / sub
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / safe

        try:
            async with aiofiles.open(target, "wb") as f:
                await f.write(data)
        except OSError as exc:
            raise StorageError(f"Failed to write {target}: {exc}") from exc

        _logger.debug("storage.save", path=str(target), size=len(data), sha256=sha256[:12])
        return str(target), sha256

    async def read(self, storage_path: str) -> bytes:
        try:
            async with aiofiles.open(storage_path, "rb") as f:
                return await f.read()
        except FileNotFoundError as exc:
            raise StorageError(f"File not found: {storage_path}") from exc
        except OSError as exc:
            raise StorageError(f"Failed to read {storage_path}: {exc}") from exc

    async def delete(self, storage_path: str) -> None:
        try:
            Path(storage_path).unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError(f"Failed to delete {storage_path}: {exc}") from exc


def _safe_filename(name: str) -> str:
    """Strip path components and keep only safe characters."""
    name = Path(name).name  # strip directories
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
    return safe or "file"
