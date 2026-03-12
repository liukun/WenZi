"""Whisper API speech-to-text transcriber (OpenAI-compatible, e.g. Groq)."""

from __future__ import annotations

import io
import logging
import os
from typing import Optional

from openai import OpenAI

from .transcriber import BaseTranscriber

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "whisper-large-v3-turbo"


class WhisperAPITranscriber(BaseTranscriber):
    """Speech-to-text via OpenAI-compatible audio transcription API."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        language: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> None:
        self._base_url = base_url or DEFAULT_BASE_URL
        self._api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self._model = model or DEFAULT_MODEL
        self._language = language
        self._temperature = temperature if temperature is not None else 0.0
        self._client: Optional[OpenAI] = None
        self._initialized = False

    @property
    def initialized(self) -> bool:
        return self._initialized

    def initialize(self) -> None:
        if self._initialized:
            return
        self._client = OpenAI(base_url=self._base_url, api_key=self._api_key)
        self._initialized = True
        logger.info(
            "Whisper API transcriber ready (base_url=%s, model=%s)",
            self._base_url,
            self._model,
        )

    def cleanup(self) -> None:
        self._client = None
        self._initialized = False
        logger.info("Whisper API transcriber cleaned up")

    def transcribe(self, wav_data: bytes) -> str:
        if not self._initialized:
            self.initialize()

        audio_file = io.BytesIO(wav_data)
        audio_file.name = "audio.wav"

        kwargs: dict = {
            "model": self._model,
            "file": audio_file,
            "temperature": self._temperature,
        }
        if self._language:
            kwargs["language"] = self._language

        response = self._client.audio.transcriptions.create(**kwargs)
        text = response.text.strip()

        logger.info("Transcription result: %s", text[:100])
        return text
