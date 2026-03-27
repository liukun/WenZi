"""Tests for wenzi.enhance.vocabulary — hotword building from manual vocabulary."""

from __future__ import annotations

from unittest.mock import MagicMock

from wenzi.enhance.vocabulary import (
    LAYER_MANUAL,
    HotwordDetail,
    build_hotword_list_detailed,
)


class TestHotwordDetail:
    def test_defaults(self):
        d = HotwordDetail(term="API", layer="manual")
        assert d.term == "API"
        assert d.layer == "manual"
        assert d.category == "other"
        assert d.variants == []
        assert d.context == ""
        assert d.frequency == 1
        assert d.last_seen == ""
        assert d.score == 0.0
        assert d.recency_bonus == 0

    def test_full_fields(self):
        d = HotwordDetail(
            term="Kubernetes",
            layer="manual",
            category="tech",
            variants=["k8s"],
            context="container orchestration",
            frequency=5,
            last_seen="2024-01-01T00:00:00",
            score=7.0,
            recency_bonus=2,
        )
        assert d.term == "Kubernetes"
        assert d.category == "tech"
        assert d.frequency == 5
        assert d.score == 7.0


class TestBuildHotwordListDetailed:
    def _make_mock_store(self, terms):
        store = MagicMock()
        store.get_asr_hotwords.return_value = terms
        return store

    def test_empty_without_store(self):
        result = build_hotword_list_detailed()
        assert result == []

    def test_with_none_store(self):
        result = build_hotword_list_detailed(manual_vocab_store=None)
        assert result == []

    def test_returns_manual_hotwords(self):
        store = self._make_mock_store(["Claude", "Kubernetes"])
        result = build_hotword_list_detailed(manual_vocab_store=store)
        assert len(result) == 2
        assert result[0].term == "Claude"
        assert result[0].layer == LAYER_MANUAL
        assert result[1].term == "Kubernetes"

    def test_respects_max_count(self):
        store = self._make_mock_store(["a", "b", "c", "d", "e"])
        result = build_hotword_list_detailed(max_count=3, manual_vocab_store=store)
        assert len(result) == 3

    def test_deduplicates_case_insensitive(self):
        store = self._make_mock_store(["Claude", "claude", "CLAUDE"])
        result = build_hotword_list_detailed(manual_vocab_store=store)
        assert len(result) == 1
        assert result[0].term == "Claude"

    def test_passes_asr_model_and_app_bundle_id(self):
        store = self._make_mock_store(["test"])
        build_hotword_list_detailed(
            asr_model="whisper",
            app_bundle_id="com.test",
            manual_vocab_store=store,
        )
        store.get_asr_hotwords.assert_called_once_with(
            asr_model="whisper", app_bundle_id="com.test",
        )

    def test_graceful_on_store_error(self):
        store = MagicMock()
        store.get_asr_hotwords.side_effect = RuntimeError("fail")
        result = build_hotword_list_detailed(manual_vocab_store=store)
        assert result == []
