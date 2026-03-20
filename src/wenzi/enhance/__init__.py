"""Enhance subpackage — AI text enhancement, vocabulary, and conversation history."""

from .auto_vocab_builder import AutoVocabBuilder
from .conversation_history import ConversationHistory
from .enhancer import MODE_OFF, TextEnhancer, create_enhancer
from .mode_loader import ModeDefinition, get_sorted_modes, load_modes
from .preview_history import PreviewHistoryStore, PreviewRecord
from .vocabulary import (
    LAYER_BASE,
    LAYER_CONTEXT,
    HotwordDetail,
    VocabularyEntry,
    VocabularyIndex,
    build_hotword_list,
    build_hotword_list_detailed,
    get_vocab_entry_count,
    hotword_score,
    load_hotwords,
    load_hotwords_detailed,
)
from .vocabulary_builder import BuildCallbacks, VocabularyBuilder

__all__ = [
    "AutoVocabBuilder",
    "BuildCallbacks",
    "ConversationHistory",
    "MODE_OFF",
    "ModeDefinition",
    "PreviewHistoryStore",
    "PreviewRecord",
    "TextEnhancer",
    "VocabularyBuilder",
    "VocabularyEntry",
    "VocabularyIndex",
    "build_hotword_list",
    "build_hotword_list_detailed",
    "create_enhancer",
    "get_sorted_modes",
    "get_vocab_entry_count",
    "HotwordDetail",
    "hotword_score",
    "LAYER_BASE",
    "LAYER_CONTEXT",
    "load_hotwords",
    "load_hotwords_detailed",
    "load_modes",
]
