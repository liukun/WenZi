"""Tests for the shared text_diff module."""

from __future__ import annotations

from wenzi.enhance.text_diff import (
    _is_punctuation_only,
    inline_diff,
    tokenize_for_diff,
)


class TestTokenizeForDiff:
    def test_english_word(self):
        assert tokenize_for_diff("cloud") == ["cloud"]

    def test_cjk_characters(self):
        assert tokenize_for_diff("派森") == ["派", "森"]

    def test_mixed_text(self):
        tokens = tokenize_for_diff("我想用cloud来写代码")
        assert "cloud" in tokens
        assert "我" in tokens

    def test_whitespace(self):
        tokens = tokenize_for_diff("gate tag")
        assert " " in tokens

    def test_punctuation(self):
        tokens = tokenize_for_diff("好的，OK。")
        assert "OK" in tokens
        assert "，" in tokens

    def test_empty(self):
        assert tokenize_for_diff("") == []

    def test_alphanumeric(self):
        tokens = tokenize_for_diff("Python3")
        assert tokens == ["Python3"]


class TestInlineDiff:
    def test_identical(self):
        assert inline_diff("没有变化", "没有变化") == "没有变化"

    def test_replacement(self):
        result = inline_diff("派森编程语言", "Python编程语言")
        assert "[派森→Python]" in result
        assert "编程语言" in result

    def test_multiple_replacements(self):
        result = inline_diff("平平和珊珊来了", "萍萍和杉杉来了")
        assert "[平平→萍萍]" in result
        assert "[珊珊→杉杉]" in result

    def test_deletion_silent(self):
        result = inline_diff("多余的文字好", "好")
        assert "[" not in result
        assert "好" in result

    def test_insertion_silent(self):
        result = inline_diff("好", "非常好")
        assert "[" not in result
        assert "非常好" in result

    def test_empty_strings(self):
        assert inline_diff("", "") == ""

    def test_empty_asr(self):
        result = inline_diff("", "新文本")
        assert "新文本" in result

    def test_empty_final(self):
        assert inline_diff("旧文本", "") == ""

    def test_punctuation_replacement_silent(self):
        """Half-width to full-width punctuation is applied silently."""
        result = inline_diff("好的,OK.", "好的，OK。")
        assert "[" not in result
        assert result == "好的，OK。"

    def test_punctuation_mixed_with_text_replacement(self):
        """Punctuation-only replacements are silent even alongside text replacements."""
        result = inline_diff("不是这个,就是你分词的,用方广号扩一下", "不是这个，就是你分词的，用方括号括一下")
        assert "，" in result  # punctuation silently replaced
        assert "[广→括]" in result  # text replacement bracketed
        assert "[扩→括]" in result
        assert "[,→，]" not in result  # punctuation NOT bracketed

    def test_question_mark_replacement_silent(self):
        result = inline_diff("你觉得靠谱吗?", "你觉得靠谱吗？")
        assert "[" not in result
        assert result == "你觉得靠谱吗？"

    def test_whitespace_stripped_from_brackets(self):
        """Whitespace around replacement content should be outside brackets."""
        result = inline_diff("Gate 库", " git 库")
        assert "[Gate→git]" in result
        assert "→ " not in result
        assert " →" not in result

    def test_whitespace_preserved_outside_brackets(self):
        """Stripped whitespace appears outside, not lost."""
        result = inline_diff("写jason格式", "写 JSON 格式")
        assert "[jason→JSON]" in result
        assert " [" in result or result.index("[") > 0  # leading space preserved


class TestIsPunctuationOnly:
    def test_ascii_punctuation(self):
        assert _is_punctuation_only(",.")

    def test_fullwidth_punctuation(self):
        assert _is_punctuation_only("，。")

    def test_mixed_punctuation(self):
        assert _is_punctuation_only(",，")

    def test_text_not_punctuation(self):
        assert not _is_punctuation_only("hello")

    def test_cjk_not_punctuation(self):
        assert not _is_punctuation_only("你")

    def test_mixed_text_and_punctuation(self):
        assert not _is_punctuation_only("a,")

    def test_empty_string(self):
        assert not _is_punctuation_only("")

    def test_space_is_punctuation(self):
        assert _is_punctuation_only(" ")
