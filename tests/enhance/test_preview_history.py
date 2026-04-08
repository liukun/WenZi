"""Tests for PreviewHistoryStore."""

from __future__ import annotations

import os

from wenzi.enhance.preview_history import PreviewHistoryStore, PreviewRecord


def _make_record(**overrides) -> PreviewRecord:
    defaults = dict(
        timestamp="2026-01-01T00:00:00+00:00",
        created_at="2026-01-01T08:00:00",
        action="confirm",
        asr_text="hello",
        enhanced_text="Hello.",
        final_text="Hello.",
        enhance_mode="proofread",
        stt_model="funasr",
        llm_model="openai/gpt-4o",
        wav_data=b"\x00" * 100,
        audio_duration=2.5,
        source="voice",
    )
    defaults.update(overrides)
    return PreviewRecord(**defaults)


class TestPreviewHistoryStore:
    def test_empty_store(self):
        store = PreviewHistoryStore()
        assert store.count() == 0
        assert store.get_all() == []
        assert store.get(0) is None

    def test_add_and_get(self):
        store = PreviewHistoryStore()
        r = _make_record(asr_text="first")
        store.add(r)
        assert store.count() == 1
        assert store.get(0) is r

    def test_get_all_newest_first(self):
        store = PreviewHistoryStore()
        store.add(_make_record(asr_text="first"))
        store.add(_make_record(asr_text="second"))
        store.add(_make_record(asr_text="third"))

        items = store.get_all()
        assert len(items) == 3
        assert items[0].asr_text == "third"
        assert items[1].asr_text == "second"
        assert items[2].asr_text == "first"

    def test_get_by_index(self):
        store = PreviewHistoryStore()
        store.add(_make_record(asr_text="first"))
        store.add(_make_record(asr_text="second"))

        assert store.get(0).asr_text == "second"  # newest
        assert store.get(1).asr_text == "first"
        assert store.get(2) is None

    def test_max_size_eviction(self):
        store = PreviewHistoryStore(max_size=3)
        for i in range(5):
            store.add(_make_record(asr_text=f"text{i}"))

        assert store.count() == 3
        items = store.get_all()
        assert items[0].asr_text == "text4"
        assert items[1].asr_text == "text3"
        assert items[2].asr_text == "text2"
        store.shutdown()

    def test_max_size_eviction_cleans_wav_files(self):
        store = PreviewHistoryStore(max_size=2)
        r1 = _make_record(asr_text="first")
        wav_path_1 = r1.wav_path
        assert wav_path_1 is not None
        assert os.path.exists(wav_path_1)

        store.add(r1)
        store.add(_make_record(asr_text="second"))
        # r1 is still in store
        assert os.path.exists(wav_path_1)

        store.add(_make_record(asr_text="third"))
        # r1 was evicted — its temp file should be deleted
        assert not os.path.exists(wav_path_1)
        store.shutdown()

    def test_clear(self):
        store = PreviewHistoryStore()
        store.add(_make_record())
        store.add(_make_record())
        store.clear()
        assert store.count() == 0

    def test_cancel_record_has_none_timestamp(self):
        store = PreviewHistoryStore()
        store.add(_make_record(timestamp=None))
        assert store.get(0).timestamp is None

    def test_update_timestamp(self):
        store = PreviewHistoryStore()
        store.add(_make_record(timestamp=None, asr_text="first"))
        store.add(_make_record(timestamp=None, asr_text="second"))

        # Index 0 = newest ("second")
        store.update_timestamp(0, "2026-01-01T12:00:00+00:00")
        assert store.get(0).timestamp == "2026-01-01T12:00:00+00:00"
        assert store.get(1).timestamp is None

    def test_update_timestamp_out_of_range(self):
        store = PreviewHistoryStore()
        store.add(_make_record(timestamp=None))
        # Should not raise
        store.update_timestamp(5, "ts")
        assert store.get(0).timestamp is None

    def test_move_to_front(self):
        store = PreviewHistoryStore()
        store.add(_make_record(asr_text="old"))
        store.add(_make_record(asr_text="mid"))
        store.add(_make_record(asr_text="new"))

        # index 2 = oldest ("old"), move it to front
        store.move_to_front(2)
        assert store.get(0).asr_text == "old"
        assert store.get(1).asr_text == "new"
        assert store.get(2).asr_text == "mid"

    def test_move_to_front_index_zero_is_noop(self):
        store = PreviewHistoryStore()
        store.add(_make_record(asr_text="a"))
        store.add(_make_record(asr_text="b"))

        store.move_to_front(0)
        assert store.get(0).asr_text == "b"
        assert store.get(1).asr_text == "a"

    def test_move_to_front_out_of_range(self):
        store = PreviewHistoryStore()
        store.add(_make_record(asr_text="only"))
        # Should not raise
        store.move_to_front(5)
        assert store.count() == 1

    def test_move_to_front_prevents_eviction(self):
        store = PreviewHistoryStore(max_size=3)
        store.add(_make_record(asr_text="keep_me"))
        store.add(_make_record(asr_text="b"))
        store.add(_make_record(asr_text="c"))

        # "keep_me" is oldest (index 2), move to front
        store.move_to_front(2)
        # Now add a new record — "b" should be evicted, not "keep_me"
        store.add(_make_record(asr_text="d"))
        texts = [store.get(i).asr_text for i in range(store.count())]
        assert "keep_me" in texts
        assert "b" not in texts
        store.shutdown()

    def test_wav_data_spilled_to_file(self):
        store = PreviewHistoryStore()
        wav = b"RIFF" + b"\x00" * 1000
        store.add(_make_record(wav_data=wav))
        rec = store.get(0)
        # In-memory wav_data should be cleared after spill
        assert rec.wav_data is None
        # wav_path should point to a real temp file
        assert rec.wav_path is not None
        assert os.path.exists(rec.wav_path)
        # load_wav_data() should return the original bytes
        assert rec.load_wav_data() == wav
        store.shutdown()

    def test_clipboard_source(self):
        store = PreviewHistoryStore()
        store.add(_make_record(source="clipboard", wav_data=None))
        assert store.get(0).source == "clipboard"
        assert store.get(0).wav_path is None
        assert store.get(0).load_wav_data() is None
        store.shutdown()

    def test_default_max_size(self):
        store = PreviewHistoryStore()
        assert store._max_size == 10

    def test_system_prompt_and_thinking_text_defaults(self):
        r = _make_record()
        assert r.system_prompt == ""
        assert r.thinking_text == ""

    def test_system_prompt_and_thinking_text_stored(self):
        store = PreviewHistoryStore()
        store.add(_make_record(
            system_prompt="You are helpful.",
            thinking_text="Let me think...",
        ))
        rec = store.get(0)
        assert rec.system_prompt == "You are helpful."
        assert rec.thinking_text == "Let me think..."

    def test_token_usage_default_is_none(self):
        r = _make_record()
        assert r.token_usage is None

    def test_token_usage_stored(self):
        usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        store = PreviewHistoryStore()
        store.add(_make_record(token_usage=usage))
        rec = store.get(0)
        assert rec.token_usage == usage
        assert rec.token_usage["total_tokens"] == 150

    def test_token_usage_none_when_not_provided(self):
        store = PreviewHistoryStore()
        store.add(_make_record())
        assert store.get(0).token_usage is None

    def test_hotwords_detail_stored(self):
        from wenzi.enhance.vocabulary import HotwordDetail

        details = [HotwordDetail(term="API", source="asr", asr_miss_count=5)]
        store = PreviewHistoryStore()
        store.add(_make_record(hotwords_detail=details))
        rec = store.get(0)
        assert len(rec.hotwords_detail) == 1
        assert rec.hotwords_detail[0].term == "API"

    def test_hotwords_detail_defaults_empty(self):
        store = PreviewHistoryStore()
        store.add(_make_record())
        assert store.get(0).hotwords_detail == []


class TestPreviewRecordWavLifecycle:
    def test_cleanup_wav_deletes_file(self):
        r = _make_record(wav_data=b"RIFF" + b"\x00" * 100)
        path = r.wav_path
        assert path is not None
        assert os.path.exists(path)
        r.cleanup_wav()
        assert not os.path.exists(path)
        assert r.wav_path is None

    def test_cleanup_wav_noop_when_no_file(self):
        r = _make_record(wav_data=None)
        r.cleanup_wav()  # should not raise
        assert r.wav_path is None

    def test_shutdown_cleans_all_temp_files(self):
        store = PreviewHistoryStore(max_size=5)
        paths = []
        for i in range(3):
            r = _make_record(asr_text=f"t{i}")
            paths.append(r.wav_path)
            store.add(r)

        for p in paths:
            assert os.path.exists(p)

        store.shutdown()

        for p in paths:
            assert not os.path.exists(p)
        assert store.count() == 0

    def test_load_wav_data_returns_none_after_cleanup(self):
        r = _make_record(wav_data=b"RIFF" + b"\x00" * 50)
        r.cleanup_wav()
        assert r.load_wav_data() is None


class TestPreviewRecordInputContext:
    def test_default_none(self):
        r = _make_record()
        assert r.input_context is None

    def test_with_input_context(self):
        from wenzi.input_context import InputContext
        ctx = InputContext(app_name="Terminal", bundle_id="com.apple.Terminal")
        r = _make_record(input_context=ctx)
        assert r.input_context is ctx
        assert r.input_context.app_name == "Terminal"
