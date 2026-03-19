"""Vocabulary index and retrieval using inverted index + pinyin matching."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Set

from wenzi.config import DEFAULT_DATA_DIR

logger = logging.getLogger(__name__)

# Minimum variant/term length to index (avoid noisy single-char matches)
_MIN_INDEX_LENGTH = 2


@dataclass
class VocabularyEntry:
    """A single vocabulary entry extracted from correction logs."""

    term: str
    category: str = "other"
    variants: List[str] = field(default_factory=list)
    context: str = ""
    frequency: int = 1


def _has_cjk(text: str) -> bool:
    """Return True if *text* contains at least one CJK Unified Ideograph."""
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


class VocabularyIndex:
    """Inverted-index vocabulary lookup for retrieval during text enhancement.

    Two retrieval layers:
    1. **Exact** — sliding-window substring match on lowercased text.
    2. **Pinyin** (fallback) — space-joined ``lazy_pinyin`` substring match,
       only invoked when exact matches < *top_k*.
    """

    def __init__(
        self,
        config: dict,
        data_dir: str = DEFAULT_DATA_DIR,
    ) -> None:
        self._data_dir = os.path.expanduser(data_dir)
        self._vocab_path = os.path.join(self._data_dir, "vocabulary.json")

        self._entries: List[VocabularyEntry] = []

        # Exact-match index: length → {lowercased_string → [entry_indices]}
        self._variants_by_length: Dict[int, Dict[str, List[int]]] = {}

        # Pinyin index: pinyin_string → [entry_indices]
        self._pinyin_index: Dict[str, List[int]] = {}

        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def load(self) -> bool:
        """Load vocabulary.json and build the inverted index.

        Returns True if loaded successfully.
        """
        try:
            entries = self._read_vocabulary()
            if not entries:
                logger.info("No vocabulary entries found")
                return False

            self._entries = entries
            self._build_index()
            self._loaded = True
            logger.info(
                "Vocabulary loaded: %d entries, %d exact keys, %d pinyin keys",
                len(self._entries),
                sum(len(b) for b in self._variants_by_length.values()),
                len(self._pinyin_index),
            )
            return True
        except Exception as e:
            logger.warning("Failed to load vocabulary: %s", e)
            return False

    def reload(self) -> bool:
        """Reload vocabulary and rebuild index."""
        self._loaded = False
        self._entries = []
        self._variants_by_length = {}
        self._pinyin_index = {}
        return self.load()

    def retrieve(self, text: str, top_k: int = 5) -> List[VocabularyEntry]:
        """Retrieve relevant vocabulary entries for *text*.

        Layer 1 (exact substring match) runs first.  If it already yields
        *top_k* or more results the pinyin layer is skipped entirely.
        """
        text = text.strip()
        if not self._loaded or not text:
            return []

        try:
            exact_indices = self._exact_search(text)

            if len(exact_indices) >= top_k:
                return self._rank(exact_indices, set(), top_k)

            pinyin_indices = self._pinyin_search(text, exact_indices)
            return self._rank(exact_indices, pinyin_indices, top_k)
        except Exception as e:
            logger.warning("Vocabulary retrieval failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # Formatting (unchanged public API)
    # ------------------------------------------------------------------

    @staticmethod
    def format_entry_lines(entries: List["VocabularyEntry"]) -> str:
        """Format vocabulary entries as plain lines (no header/footer).

        Returns a newline-joined string like::

            - term1（context1）
            - term2

        Used by :class:`TextEnhancer` inside the combined context section.
        """
        if not entries:
            return ""
        lines: list[str] = []
        for entry in entries:
            if entry.context:
                lines.append(f"- {entry.term}（{entry.context}）")
            else:
                lines.append(f"- {entry.term}")
        return "\n".join(lines)

    def format_for_prompt(self, entries: List[VocabularyEntry]) -> str:
        """Format vocabulary entries for injection into LLM prompt.

        Returns a self-contained section with header and footer.
        """
        if not entries:
            return ""

        header = (
            "---\n"
            "以下是用户词库中与本次输入相关的专有名词，ASR 常将其误写为同音近音词。\n"
            "仅当输入中确实存在对应误写时才替换，不要强行套用：\n"
            "\n"
        )
        return header + self.format_entry_lines(entries) + "\n---"

    # ------------------------------------------------------------------
    # Index construction
    # ------------------------------------------------------------------

    def _build_index(self) -> None:
        """Build inverted indices from *self._entries*."""
        variants_by_length: Dict[int, Dict[str, List[int]]] = {}
        pinyin_index: Dict[str, List[int]] = {}
        seen_exact: set[tuple[str, int]] = set()
        seen_pinyin: set[tuple[str, int]] = set()

        for i, entry in enumerate(self._entries):
            strings = [entry.term] + entry.variants
            for s in strings:
                if len(s) < _MIN_INDEX_LENGTH:
                    continue

                # Exact-match index (deduplicated)
                key = s.lower()
                exact_pair = (key, i)
                if exact_pair not in seen_exact:
                    seen_exact.add(exact_pair)
                    bucket = variants_by_length.setdefault(len(key), {})
                    bucket.setdefault(key, []).append(i)

                # Pinyin index (CJK only, deduplicated)
                if _has_cjk(s):
                    py = self._to_pinyin(s)
                    if py:
                        pinyin_pair = (py, i)
                        if pinyin_pair not in seen_pinyin:
                            seen_pinyin.add(pinyin_pair)
                            pinyin_index.setdefault(py, []).append(i)

        self._variants_by_length = variants_by_length
        self._pinyin_index = pinyin_index

    # ------------------------------------------------------------------
    # Search layers
    # ------------------------------------------------------------------

    def _exact_search(self, text: str) -> Set[int]:
        """Sliding-window exact substring match, returns matched entry indices."""
        text_lower = text.lower()
        matched: Set[int] = set()

        for length, bucket in self._variants_by_length.items():
            if length > len(text_lower):
                continue
            for i in range(len(text_lower) - length + 1):
                substr = text_lower[i : i + length]
                indices = bucket.get(substr)
                if indices is not None:
                    matched.update(indices)

        return matched

    def _pinyin_search(self, text: str, exclude: Set[int]) -> Set[int]:
        """Pinyin substring match on *text*, excluding already-found indices."""
        text_py = self._to_pinyin(text)
        if not text_py:
            return set()

        matched: Set[int] = set()
        for variant_py, entry_indices in self._pinyin_index.items():
            if variant_py in text_py:
                for idx in entry_indices:
                    if idx not in exclude:
                        matched.add(idx)
        return matched

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------

    def _rank(
        self,
        exact_indices: Set[int],
        pinyin_indices: Set[int],
        top_k: int,
    ) -> List[VocabularyEntry]:
        """Merge and rank results: exact first, then pinyin, each by frequency desc."""
        exact_sorted = sorted(exact_indices, key=lambda i: -self._entries[i].frequency)
        pinyin_sorted = sorted(pinyin_indices, key=lambda i: -self._entries[i].frequency)
        combined = exact_sorted + pinyin_sorted
        return [self._entries[i] for i in combined[:top_k]]

    # ------------------------------------------------------------------
    # Pinyin helpers
    # ------------------------------------------------------------------

    # Cached reference to pypinyin.lazy_pinyin (lazily resolved on first use)
    _lazy_pinyin_func = None

    @staticmethod
    def _to_pinyin(text: str) -> str:
        """Convert *text* to space-joined toneless pinyin.

        Returns empty string on failure.  ``pypinyin`` is lazily imported
        so the dependency is only incurred when the pinyin layer is actually
        used.
        """
        try:
            if VocabularyIndex._lazy_pinyin_func is None:
                from pypinyin import lazy_pinyin

                VocabularyIndex._lazy_pinyin_func = lazy_pinyin
            return " ".join(VocabularyIndex._lazy_pinyin_func(text))
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Vocabulary I/O
    # ------------------------------------------------------------------

    def _read_vocabulary(self) -> List[VocabularyEntry]:
        """Read vocabulary.json and parse entries."""
        try:
            with open(self._vocab_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            raw_entries = data.get("entries", [])
            entries = []
            for raw in raw_entries:
                entry = VocabularyEntry(
                    term=raw["term"],
                    category=raw.get("category", "other"),
                    variants=raw.get("variants", []),
                    context=raw.get("context", ""),
                    frequency=raw.get("frequency", 1),
                )
                entries.append(entry)
            return entries
        except Exception as e:
            logger.warning("Failed to read vocabulary.json: %s", e)
            return []


def _read_raw_entries(data_dir: str = DEFAULT_DATA_DIR) -> List[dict]:
    """Read raw entry dicts from vocabulary.json.

    Shared I/O helper for :func:`load_hotwords` and :func:`get_vocab_entry_count`.
    Returns an empty list on any error.
    """
    vocab_path = os.path.join(os.path.expanduser(data_dir), "vocabulary.json")
    try:
        with open(vocab_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("entries", [])
    except Exception:
        return []


def load_hotwords(
    data_dir: str = DEFAULT_DATA_DIR,
    min_frequency: int = 2,
    max_count: int = 50,
) -> List[str]:
    """Load high-frequency vocabulary terms for ASR hotword injection.

    Reads vocabulary.json, filters by frequency, and returns the top terms
    sorted by frequency descending.

    Returns an empty list on error or when no entries qualify.
    """
    entries = _read_raw_entries(data_dir)
    filtered = [
        e for e in entries if e.get("frequency", 1) >= min_frequency
    ]
    filtered.sort(key=lambda e: e.get("frequency", 1), reverse=True)
    return [e["term"] for e in filtered[:max_count] if "term" in e]


def get_vocab_entry_count(data_dir: str = DEFAULT_DATA_DIR) -> int:
    """Read the number of entries in vocabulary.json without loading the index."""
    return len(_read_raw_entries(data_dir))
