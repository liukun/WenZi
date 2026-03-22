"""Tests for cc_sessions.cache module."""

from __future__ import annotations

import json
from pathlib import Path

from cc_sessions.cache import SessionCache


class TestSessionCacheInit:
    """Test cache initialization."""

    def test_creates_parent_dir(self, tmp_path: Path):
        """Cache creates parent directory if it does not exist."""
        cache_path = tmp_path / "subdir" / "cache.json"
        SessionCache(cache_path)
        assert cache_path.parent.is_dir()

    def test_loads_existing_cache(self, tmp_path: Path):
        """Cache loads data from an existing file."""
        cache_path = tmp_path / "cache.json"
        data = {
            "version": 3,
            "sessions": {
                "/tmp/s1.jsonl": {
                    "mtime": 1000.0,
                    "data": {"session_id": "s1", "title": "Hello"},
                }
            },
        }
        cache_path.write_text(json.dumps(data))
        cache = SessionCache(cache_path)
        entry = cache.get("/tmp/s1.jsonl")
        assert entry is not None
        assert entry[0] == 1000.0
        assert entry[1]["session_id"] == "s1"

    def test_handles_missing_file(self, tmp_path: Path):
        """Cache starts empty if file does not exist."""
        cache = SessionCache(tmp_path / "cache.json")
        assert cache.get("/tmp/nonexistent.jsonl") is None

    def test_handles_corrupt_file(self, tmp_path: Path):
        """Cache starts empty if file is corrupt."""
        cache_path = tmp_path / "cache.json"
        cache_path.write_text("{broken json!!")
        cache = SessionCache(cache_path)
        assert cache.get("/tmp/anything") is None

    def test_handles_wrong_version(self, tmp_path: Path):
        """Cache discards data with unknown version."""
        cache_path = tmp_path / "cache.json"
        cache_path.write_text(json.dumps({"version": 999, "sessions": {"x": {}}}))
        cache = SessionCache(cache_path)
        assert cache.get("x") is None


class TestSessionCacheGetPut:
    """Test get/put operations."""

    def test_put_and_get(self, tmp_path: Path):
        cache = SessionCache(tmp_path / "cache.json")
        session_data = {"session_id": "s1", "title": "Test"}
        cache.put("/tmp/s1.jsonl", 1234.5, session_data)
        entry = cache.get("/tmp/s1.jsonl")
        assert entry == (1234.5, session_data)

    def test_get_returns_none_for_unknown(self, tmp_path: Path):
        cache = SessionCache(tmp_path / "cache.json")
        assert cache.get("/tmp/unknown.jsonl") is None

    def test_put_overwrites_existing(self, tmp_path: Path):
        cache = SessionCache(tmp_path / "cache.json")
        cache.put("/tmp/s1.jsonl", 100.0, {"session_id": "s1", "title": "Old"})
        cache.put("/tmp/s1.jsonl", 200.0, {"session_id": "s1", "title": "New"})
        entry = cache.get("/tmp/s1.jsonl")
        assert entry == (200.0, {"session_id": "s1", "title": "New"})


class TestSessionCachePrune:
    """Test pruning of stale entries."""

    def test_prune_removes_absent_files(self, tmp_path: Path):
        cache = SessionCache(tmp_path / "cache.json")
        cache.put("/tmp/keep.jsonl", 100.0, {"session_id": "keep"})
        cache.put("/tmp/gone.jsonl", 100.0, {"session_id": "gone"})
        cache.prune(live_paths={"/tmp/keep.jsonl"})
        assert cache.get("/tmp/keep.jsonl") is not None
        assert cache.get("/tmp/gone.jsonl") is None


class TestSessionCacheSave:
    """Test saving to disk."""

    def test_save_writes_file(self, tmp_path: Path):
        cache_path = tmp_path / "cache.json"
        cache = SessionCache(cache_path)
        cache.put("/tmp/s1.jsonl", 100.0, {"session_id": "s1"})
        cache.save()
        assert cache_path.is_file()
        loaded = json.loads(cache_path.read_text())
        assert loaded["version"] == 3
        assert "/tmp/s1.jsonl" in loaded["sessions"]

    def test_save_only_when_dirty(self, tmp_path: Path):
        cache_path = tmp_path / "cache.json"
        cache = SessionCache(cache_path)
        cache.save()
        assert not cache_path.exists()

    def test_roundtrip(self, tmp_path: Path):
        cache_path = tmp_path / "cache.json"
        cache1 = SessionCache(cache_path)
        cache1.put("/tmp/s1.jsonl", 100.0, {"session_id": "s1", "title": "Hello"})
        cache1.save()

        cache2 = SessionCache(cache_path)
        entry = cache2.get("/tmp/s1.jsonl")
        assert entry == (100.0, {"session_id": "s1", "title": "Hello"})


class TestSessionCacheClear:
    """Test clear() method."""

    def test_clear_removes_entries_and_file(self, tmp_path: Path):
        """clear() empties in-memory data and deletes the cache file."""
        cache_file = tmp_path / "cache.json"
        cache = SessionCache(cache_file)
        cache.put("a.jsonl", 1.0, {"session_id": "a"})
        cache.save()
        assert cache_file.exists()

        cache.clear()
        assert cache.get("a.jsonl") is None
        assert not cache_file.exists()
