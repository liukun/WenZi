"""Tests for the vocabulary index and retrieval module."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

from wenzi.enhance.vocabulary import (
    VocabularyEntry,
    VocabularyIndex,
    _parse_timestamp,
    build_hotword_list,
    get_vocab_entry_count,
    load_hotwords,
)


# --- VocabularyEntry tests ---


class TestVocabularyEntry:
    def test_defaults(self):
        entry = VocabularyEntry(term="Python")
        assert entry.term == "Python"
        assert entry.category == "other"
        assert entry.variants == []
        assert entry.context == ""
        assert entry.frequency == 1

    def test_full_entry(self):
        entry = VocabularyEntry(
            term="Kubernetes",
            category="tech",
            variants=["库伯尼特斯", "K8S"],
            context="容器编排",
            frequency=5,
        )
        assert entry.term == "Kubernetes"
        assert entry.variants == ["库伯尼特斯", "K8S"]
        assert entry.frequency == 5


# --- Helpers ---


def _make_vocab_json(entries):
    """Create a vocabulary.json-compatible dict."""
    return {
        "last_processed_timestamp": "2026-01-01T00:00:00+00:00",
        "entries": entries,
    }


def _sample_entries():
    return [
        {
            "term": "Python",
            "category": "tech",
            "variants": ["派森"],
            "context": "编程语言",
            "frequency": 3,
        },
        {
            "term": "Kubernetes",
            "category": "tech",
            "variants": ["库伯尼特斯"],
            "context": "容器编排",
            "frequency": 2,
        },
        {
            "term": "Visual Studio Code",
            "category": "tech",
            "variants": ["VSCode"],
            "context": "代码编辑器",
            "frequency": 1,
        },
    ]


def _write_vocab(tmp_path, entries):
    """Write vocabulary.json and return a loaded VocabularyIndex."""
    vocab_path = tmp_path / "vocabulary.json"
    vocab_path.write_text(
        json.dumps(_make_vocab_json(entries)), encoding="utf-8"
    )
    idx = VocabularyIndex({}, data_dir=str(tmp_path))
    idx.load()
    return idx


# --- VocabularyIndex load tests ---


class TestVocabularyIndexLoad:
    def test_load_success(self, tmp_path):
        idx = _write_vocab(tmp_path, _sample_entries())
        assert idx.is_loaded
        assert idx.entry_count == 3

    def test_load_builds_index(self, tmp_path):
        idx = _write_vocab(tmp_path, _sample_entries())
        assert len(idx._variants_by_length) > 0
        # "派森" is CJK so pinyin index should also be populated
        assert len(idx._pinyin_index) > 0

    def test_load_no_vocabulary_file(self, tmp_path):
        idx = VocabularyIndex({}, data_dir=str(tmp_path))
        result = idx.load()
        assert result is False
        assert not idx.is_loaded

    def test_load_empty_entries(self, tmp_path):
        vocab_path = tmp_path / "vocabulary.json"
        vocab_path.write_text(
            json.dumps(_make_vocab_json([])), encoding="utf-8"
        )
        idx = VocabularyIndex({}, data_dir=str(tmp_path))
        result = idx.load()
        assert result is False


# --- Exact search tests ---


class TestExactSearch:
    def test_variant_in_text(self, tmp_path):
        idx = _write_vocab(tmp_path, _sample_entries())
        results = idx.retrieve("我用派森写代码")
        terms = [r.term for r in results]
        assert "Python" in terms

    def test_term_in_text(self, tmp_path):
        idx = _write_vocab(tmp_path, _sample_entries())
        results = idx.retrieve("I use Python for coding")
        terms = [r.term for r in results]
        assert "Python" in terms

    def test_case_insensitive(self, tmp_path):
        idx = _write_vocab(tmp_path, _sample_entries())
        results = idx.retrieve("i use python for coding")
        terms = [r.term for r in results]
        assert "Python" in terms

    def test_min_length_filtering(self, tmp_path):
        """Single-character variants are not indexed."""
        entries = [
            {"term": "AI", "variants": ["A"], "frequency": 1},
        ]
        idx = _write_vocab(tmp_path, entries)
        # "A" (1 char) should not be indexed, but "AI" (2 chars) should
        results = idx.retrieve("I like AI")
        terms = [r.term for r in results]
        assert "AI" in terms

        # Single-char variant should NOT match
        results2 = idx.retrieve("I got an A on my test")
        # "AI" should not appear since "A" is too short to index
        # and "AI" does not appear in text
        terms2 = [r.term for r in results2]
        assert "AI" not in terms2

    def test_no_match(self, tmp_path):
        idx = _write_vocab(tmp_path, _sample_entries())
        results = idx.retrieve("今天天气很好")
        assert results == []

    def test_multiple_matches(self, tmp_path):
        idx = _write_vocab(tmp_path, _sample_entries())
        results = idx.retrieve("我用派森和库伯尼特斯部署服务")
        terms = [r.term for r in results]
        assert "Python" in terms
        assert "Kubernetes" in terms


# --- Pinyin search tests ---


class TestPinyinSearch:
    def test_homophone_match(self, tmp_path):
        """Unseen variant with same pinyin should match via pinyin layer."""
        entries = [
            {"term": "Python", "variants": ["派森"], "context": "编程语言", "frequency": 3},
        ]
        idx = _write_vocab(tmp_path, entries)
        # "排森" has same pinyin as "派森" (pai sen) but different characters
        results = idx.retrieve("我用排森写代码")
        terms = [r.term for r in results]
        assert "Python" in terms

    def test_non_cjk_not_in_pinyin_index(self, tmp_path):
        """Pure ASCII terms/variants should NOT be in the pinyin index."""
        entries = [
            {"term": "Python", "variants": ["PyThon"], "frequency": 1},
        ]
        idx = _write_vocab(tmp_path, entries)
        # Pinyin index should be empty — no CJK strings
        assert len(idx._pinyin_index) == 0

    def test_pinyin_no_cross_boundary_match(self, tmp_path):
        """Pinyin matching should not match across character boundaries."""
        entries = [
            {"term": "Python", "variants": ["拍森"], "frequency": 1},
        ]
        idx = _write_vocab(tmp_path, entries)
        # "拍了一张森林的照片" — "拍" and "森" are not adjacent
        results = idx.retrieve("拍了一张森林的照片")
        terms = [r.term for r in results]
        assert "Python" not in terms


# --- Retrieve integration tests ---


class TestRetrieve:
    def test_frequency_ranking(self, tmp_path):
        entries = [
            {"term": "LowTerm", "variants": ["罗特"], "frequency": 1},
            {"term": "HighTerm", "variants": ["嗨特"], "frequency": 10},
        ]
        idx = _write_vocab(tmp_path, entries)
        results = idx.retrieve("他说嗨特然后打了个电话给罗特", top_k=5)
        assert len(results) == 2
        # Higher frequency should come first (both are exact matches)
        assert results[0].term == "HighTerm"
        assert results[1].term == "LowTerm"

    def test_exact_before_pinyin(self, tmp_path):
        """Exact matches should rank before pinyin-only matches."""
        entries = [
            {"term": "A_Term", "variants": ["阿特"], "frequency": 1},
            {"term": "B_Term", "variants": ["贝特"], "frequency": 10},
        ]
        idx = _write_vocab(tmp_path, entries)
        # "阿特" is exact match, "倍特" is pinyin match for "贝特" (bei te)
        results = idx.retrieve("我找阿特和倍特", top_k=5)
        terms = [r.term for r in results]
        if "A_Term" in terms and "B_Term" in terms:
            assert terms.index("A_Term") < terms.index("B_Term")

    def test_top_k_limiting(self, tmp_path):
        entries = [
            {"term": f"Term{i}", "variants": [f"变体{i}号"], "frequency": i}
            for i in range(10)
        ]
        idx = _write_vocab(tmp_path, entries)
        text = "".join(f"变体{i}号" for i in range(10))
        results = idx.retrieve(text, top_k=3)
        assert len(results) == 3

    def test_empty_text(self, tmp_path):
        idx = _write_vocab(tmp_path, _sample_entries())
        assert idx.retrieve("") == []
        assert idx.retrieve("   ") == []

    def test_not_loaded(self, tmp_path):
        idx = VocabularyIndex({}, data_dir=str(tmp_path))
        assert idx.retrieve("Python") == []

    def test_deduplication(self, tmp_path):
        """Same entry matched by both exact and pinyin should appear only once."""
        entries = [
            {"term": "Python", "variants": ["派森"], "context": "编程语言", "frequency": 3},
        ]
        idx = _write_vocab(tmp_path, entries)
        results = idx.retrieve("我用派森写代码", top_k=5)
        terms = [r.term for r in results]
        assert terms.count("Python") == 1

    def test_early_termination_skips_pinyin(self, tmp_path):
        """When exact matches >= top_k, pinyin layer should be skipped."""
        entries = [
            {"term": f"Term{i}", "variants": [f"变体{i}号"], "frequency": i + 1}
            for i in range(5)
        ]
        idx = _write_vocab(tmp_path, entries)
        text = "".join(f"变体{i}号" for i in range(5))
        # top_k=3, and we have 5 exact matches, so pinyin should be skipped
        results = idx.retrieve(text, top_k=3)
        assert len(results) == 3
        # Should be sorted by frequency desc
        assert results[0].frequency >= results[1].frequency >= results[2].frequency

    def test_entries_without_variants(self, tmp_path):
        """Entries with no variants can still be matched by term."""
        entries = [
            {"term": "Docker", "variants": [], "context": "容器", "frequency": 2},
        ]
        idx = _write_vocab(tmp_path, entries)
        results = idx.retrieve("I use Docker for deployment")
        terms = [r.term for r in results]
        assert "Docker" in terms


# --- Reload tests ---


class TestVocabularyIndexReload:
    def test_reload_resets_state(self, tmp_path):
        idx = _write_vocab(tmp_path, _sample_entries())
        assert idx.is_loaded

        idx.reload()
        assert idx.is_loaded
        assert idx.entry_count == 3

    def test_reload_picks_up_new_entries(self, tmp_path):
        idx = _write_vocab(tmp_path, _sample_entries())
        assert idx.entry_count == 3

        entries = _sample_entries() + [
            {"term": "Docker", "variants": [], "context": "", "frequency": 1}
        ]
        vocab_path = tmp_path / "vocabulary.json"
        vocab_path.write_text(
            json.dumps(_make_vocab_json(entries)), encoding="utf-8"
        )
        idx.reload()
        assert idx.entry_count == 4


# --- Entry count tests ---


class TestEntryCount:
    def test_entry_count_after_load(self, tmp_path):
        idx = _write_vocab(tmp_path, _sample_entries())
        assert idx.entry_count == 3

    def test_entry_count_zero_before_load(self, tmp_path):
        idx = VocabularyIndex({}, data_dir=str(tmp_path))
        assert idx.entry_count == 0


# --- Format tests ---


class TestVocabularyIndexFormatForPrompt:
    def test_format_with_context(self):
        entries = [
            VocabularyEntry(term="Python", context="编程语言"),
            VocabularyEntry(term="Kubernetes", context="容器编排"),
        ]
        idx = VocabularyIndex({})
        result = idx.format_for_prompt(entries)
        assert "用户词库" in result
        assert "不要强行套用" in result
        assert "- Python（编程语言）" in result
        assert "- Kubernetes（容器编排）" in result

    def test_format_without_context(self):
        entries = [VocabularyEntry(term="Python")]
        idx = VocabularyIndex({})
        result = idx.format_for_prompt(entries)
        assert "- Python" in result
        assert "- Python（" not in result

    def test_format_empty(self):
        idx = VocabularyIndex({})
        result = idx.format_for_prompt([])
        assert result == ""

    def test_format_mixed(self):
        entries = [
            VocabularyEntry(term="Python", context="编程语言"),
            VocabularyEntry(term="FastAPI"),
        ]
        idx = VocabularyIndex({})
        result = idx.format_for_prompt(entries)
        assert "- Python（编程语言）" in result
        assert "- FastAPI" in result


class TestVocabularyFormatEntryLines:
    def test_entries_with_context(self):
        entries = [
            VocabularyEntry(term="Python", context="编程语言"),
            VocabularyEntry(term="Kubernetes", context="容器编排"),
        ]
        result = VocabularyIndex.format_entry_lines(entries)
        assert result == "- Python（编程语言）\n- Kubernetes（容器编排）"

    def test_entries_without_context(self):
        entries = [VocabularyEntry(term="Python")]
        result = VocabularyIndex.format_entry_lines(entries)
        assert result == "- Python"

    def test_empty_entries(self):
        assert VocabularyIndex.format_entry_lines([]) == ""

    def test_mixed_entries(self):
        entries = [
            VocabularyEntry(term="Python", context="编程语言"),
            VocabularyEntry(term="FastAPI"),
        ]
        result = VocabularyIndex.format_entry_lines(entries)
        assert "- Python（编程语言）" in result
        assert "- FastAPI" in result
        assert "- FastAPI（" not in result

    def test_consistency_with_format_for_prompt(self):
        """format_entry_lines output should appear in format_for_prompt output."""
        entries = [
            VocabularyEntry(term="API", context="接口"),
            VocabularyEntry(term="SDK"),
        ]
        idx = VocabularyIndex({})
        entry_lines = VocabularyIndex.format_entry_lines(entries)
        full_prompt = idx.format_for_prompt(entries)
        assert entry_lines in full_prompt


# --- get_vocab_entry_count tests ---


class TestGetVocabEntryCount:
    def test_count_with_entries(self, tmp_path):
        vocab_path = tmp_path / "vocabulary.json"
        vocab_path.write_text(
            json.dumps(_make_vocab_json(_sample_entries())),
            encoding="utf-8",
        )
        assert get_vocab_entry_count(str(tmp_path)) == 3

    def test_count_no_file(self, tmp_path):
        assert get_vocab_entry_count(str(tmp_path)) == 0

    def test_count_empty_entries(self, tmp_path):
        vocab_path = tmp_path / "vocabulary.json"
        vocab_path.write_text(
            json.dumps(_make_vocab_json([])),
            encoding="utf-8",
        )
        assert get_vocab_entry_count(str(tmp_path)) == 0

    def test_count_invalid_json(self, tmp_path):
        vocab_path = tmp_path / "vocabulary.json"
        vocab_path.write_text("not json", encoding="utf-8")
        assert get_vocab_entry_count(str(tmp_path)) == 0


# --- load_hotwords tests ---


class TestLoadHotwords:
    def test_filters_by_frequency(self, tmp_path):
        entries = [
            {"term": "HighFreq", "frequency": 5},
            {"term": "LowFreq", "frequency": 1},
            {"term": "MidFreq", "frequency": 2},
        ]
        vocab_path = tmp_path / "vocabulary.json"
        vocab_path.write_text(
            json.dumps(_make_vocab_json(entries)), encoding="utf-8"
        )
        result = load_hotwords(data_dir=str(tmp_path), min_frequency=2)
        assert "HighFreq" in result
        assert "MidFreq" in result
        assert "LowFreq" not in result

    def test_sorts_by_frequency_desc(self, tmp_path):
        entries = [
            {"term": "Low", "frequency": 2},
            {"term": "High", "frequency": 10},
            {"term": "Mid", "frequency": 5},
        ]
        vocab_path = tmp_path / "vocabulary.json"
        vocab_path.write_text(
            json.dumps(_make_vocab_json(entries)), encoding="utf-8"
        )
        result = load_hotwords(data_dir=str(tmp_path), min_frequency=1)
        assert result == ["High", "Mid", "Low"]

    def test_respects_max_count(self, tmp_path):
        entries = [
            {"term": f"Term{i}", "frequency": 10 - i}
            for i in range(10)
        ]
        vocab_path = tmp_path / "vocabulary.json"
        vocab_path.write_text(
            json.dumps(_make_vocab_json(entries)), encoding="utf-8"
        )
        result = load_hotwords(data_dir=str(tmp_path), min_frequency=1, max_count=3)
        assert len(result) == 3
        assert result[0] == "Term0"

    def test_no_file_returns_empty(self, tmp_path):
        result = load_hotwords(data_dir=str(tmp_path))
        assert result == []

    def test_all_low_frequency_returns_empty(self, tmp_path):
        entries = [
            {"term": "A", "frequency": 1},
            {"term": "B", "frequency": 1},
        ]
        vocab_path = tmp_path / "vocabulary.json"
        vocab_path.write_text(
            json.dumps(_make_vocab_json(entries)), encoding="utf-8"
        )
        result = load_hotwords(data_dir=str(tmp_path), min_frequency=2)
        assert result == []


# --- find_terms_in_text tests ---


class TestFindTermsInText:
    def test_exact_term_match(self, tmp_path):
        idx = _write_vocab(tmp_path, _sample_entries())
        results = idx.find_terms_in_text("I use Python for coding")
        terms = [r.term for r in results]
        assert "Python" in terms

    def test_variant_match(self, tmp_path):
        idx = _write_vocab(tmp_path, _sample_entries())
        results = idx.find_terms_in_text("我用派森写代码")
        terms = [r.term for r in results]
        assert "Python" in terms

    def test_no_pinyin_layer(self, tmp_path):
        """find_terms_in_text should NOT use pinyin matching."""
        entries = [
            {"term": "Python", "variants": ["派森"], "frequency": 3},
        ]
        idx = _write_vocab(tmp_path, entries)
        # "排森" has same pinyin but different characters — should NOT match
        results = idx.find_terms_in_text("我用排森写代码")
        terms = [r.term for r in results]
        assert "Python" not in terms

    def test_not_loaded_returns_empty(self, tmp_path):
        idx = VocabularyIndex({}, data_dir=str(tmp_path))
        assert idx.find_terms_in_text("Python") == []

    def test_empty_text_returns_empty(self, tmp_path):
        idx = _write_vocab(tmp_path, _sample_entries())
        assert idx.find_terms_in_text("") == []
        assert idx.find_terms_in_text("   ") == []

    def test_sorted_by_frequency_desc(self, tmp_path):
        entries = [
            {"term": "LowTerm", "variants": ["罗特"], "frequency": 1},
            {"term": "HighTerm", "variants": ["嗨特"], "frequency": 10},
        ]
        idx = _write_vocab(tmp_path, entries)
        results = idx.find_terms_in_text("我说嗨特然后打了个电话给罗特")
        assert len(results) == 2
        assert results[0].term == "HighTerm"
        assert results[1].term == "LowTerm"


# --- _parse_timestamp tests ---


class TestParseTimestamp:
    def test_iso_with_timezone(self):
        dt = _parse_timestamp("2026-03-20T10:30:00+08:00")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_iso_without_timezone(self):
        dt = _parse_timestamp("2026-03-20T10:30:00")
        assert dt is not None
        assert dt.tzinfo == timezone.utc

    def test_invalid_string(self):
        assert _parse_timestamp("not-a-date") is None

    def test_none_input(self):
        assert _parse_timestamp(None) is None

    def test_empty_string(self):
        assert _parse_timestamp("") is None


# --- build_hotword_list tests ---


def _make_mock_history(records):
    """Create a mock ConversationHistory that returns given records."""

    class MockHistory:
        def get_recent(self, n=10):
            return records[:n]

    return MockHistory()


class TestBuildHotwordList:
    def test_context_layer_priority(self, tmp_path):
        """Context-layer terms should come before base-layer terms."""
        entries = [
            {"term": "Python", "variants": ["派森"], "frequency": 5},
            {"term": "Docker", "variants": ["多克"], "frequency": 3},
        ]
        idx = _write_vocab(tmp_path, entries)
        now = datetime.now(timezone.utc)
        records = [
            {
                "timestamp": now.isoformat(),
                "final_text": "我在用派森写代码",
                "preview_enabled": True,
            },
        ]
        history = _make_mock_history(records)
        base = ["Kubernetes", "Terraform"]
        result = build_hotword_list(idx, history, base)
        assert result is not None
        # Python should be first (from context), then base terms
        assert result[0] == "Python"
        assert "Kubernetes" in result
        assert "Terraform" in result

    def test_deduplication(self, tmp_path):
        """Terms appearing in both layers should not be duplicated."""
        entries = [
            {"term": "Python", "variants": ["派森"], "frequency": 5},
        ]
        idx = _write_vocab(tmp_path, entries)
        now = datetime.now(timezone.utc)
        records = [
            {
                "timestamp": now.isoformat(),
                "final_text": "我用派森",
                "preview_enabled": True,
            },
        ]
        history = _make_mock_history(records)
        base = ["Python", "Docker"]
        result = build_hotword_list(idx, history, base)
        assert result is not None
        assert result.count("Python") == 1

    def test_max_count_limit(self, tmp_path):
        entries = [
            {"term": f"Term{i}", "variants": [f"变体{i}号"], "frequency": i + 1}
            for i in range(10)
        ]
        idx = _write_vocab(tmp_path, entries)
        now = datetime.now(timezone.utc)
        combined_text = " ".join(f"变体{i}号" for i in range(10))
        records = [
            {
                "timestamp": now.isoformat(),
                "final_text": combined_text,
                "preview_enabled": True,
            },
        ]
        history = _make_mock_history(records)
        base = [f"Base{i}" for i in range(10)]
        result = build_hotword_list(idx, history, base, max_count=5)
        assert result is not None
        assert len(result) == 5

    def test_age_filtering(self, tmp_path):
        """Records older than max_age_hours should be skipped."""
        entries = [
            {"term": "Python", "variants": ["派森"], "frequency": 5},
        ]
        idx = _write_vocab(tmp_path, entries)
        old_time = datetime.now(timezone.utc) - timedelta(hours=3)
        records = [
            {
                "timestamp": old_time.isoformat(),
                "final_text": "我用派森",
                "preview_enabled": True,
            },
        ]
        history = _make_mock_history(records)
        # With max_age_hours=2, the old record should be filtered out
        result = build_hotword_list(idx, history, None, max_age_hours=2.0)
        assert result is None  # No context, no base

    def test_vocab_index_none_uses_base(self):
        """When vocab_index is None, only base hotwords are used."""
        base = ["Python", "Docker"]
        result = build_hotword_list(None, None, base)
        assert result == ["Python", "Docker"]

    def test_history_none_uses_base(self, tmp_path):
        """When history is None, only base hotwords are used."""
        idx = _write_vocab(tmp_path, _sample_entries())
        base = ["Python", "Docker"]
        result = build_hotword_list(idx, None, base)
        assert result == ["Python", "Docker"]

    def test_all_none_returns_none(self):
        """When everything is None/empty, return None."""
        result = build_hotword_list(None, None, None)
        assert result is None

    def test_empty_base_with_no_context_returns_none(self, tmp_path):
        idx = _write_vocab(tmp_path, _sample_entries())
        history = _make_mock_history([])
        result = build_hotword_list(idx, history, None)
        assert result is None

    def test_base_only_when_no_context(self, tmp_path):
        """When history is empty, only base hotwords are returned."""
        idx = _write_vocab(tmp_path, _sample_entries())
        history = _make_mock_history([])
        base = ["Python", "Docker"]
        result = build_hotword_list(idx, history, base)
        assert result == ["Python", "Docker"]
