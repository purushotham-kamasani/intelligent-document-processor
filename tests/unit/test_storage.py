"""Unit tests for storage."""

from __future__ import annotations

import pytest

from app.core.exceptions import StorageError
from app.services.storage import LocalDiskStorage


@pytest.mark.asyncio
async def test_save_and_read(tmp_path):
    storage = LocalDiskStorage(tmp_path)
    data = b"hello world"
    path, sha = await storage.save(data, "test.txt")
    assert path
    assert len(sha) == 64  # sha256 hex digest length

    read = await storage.read(path)
    assert read == data


@pytest.mark.asyncio
async def test_save_sanitizes_filename(tmp_path):
    storage = LocalDiskStorage(tmp_path)
    path, _ = await storage.save(b"x", "../weird/../name with spaces.txt")
    assert "/.." not in path
    assert "spaces" in path or "name" in path


@pytest.mark.asyncio
async def test_read_missing_raises(tmp_path):
    storage = LocalDiskStorage(tmp_path)
    with pytest.raises(StorageError):
        await storage.read(str(tmp_path / "does-not-exist.txt"))


@pytest.mark.asyncio
async def test_delete_missing_is_noop(tmp_path):
    storage = LocalDiskStorage(tmp_path)
    # Should not raise.
    await storage.delete(str(tmp_path / "no-such-file"))


@pytest.mark.asyncio
async def test_sha256_is_stable(tmp_path):
    storage = LocalDiskStorage(tmp_path)
    _, s1 = await storage.save(b"identical content", "a.txt")
    _, s2 = await storage.save(b"identical content", "b.txt")
    assert s1 == s2
