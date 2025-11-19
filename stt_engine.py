"""Whisper-based offline Speech-to-Text engine."""

from __future__ import annotations

import logging
import os
from typing import Callable, Optional

import numpy as np

try:  # Whisper depends on PyTorch; import errors are surfaced to the UI.
    import whisper  # type: ignore
except Exception as exc:  # pragma: no cover - dependency missing
    whisper = None  # type: ignore
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


LOGGER = logging.getLogger(__name__)


class STTEngine:
    """Offline Speech-to-Text engine built on OpenAI Whisper."""

    SUPPORTED_MODELS = ["tiny", "base", "small", "medium", "large", "turbo"]

    def __init__(self, model_name: str = "small") -> None:
        self.sample_rate = 16_000
        self.model_name = model_name
        self._model = None
        self._ensure_imports()
        self._load_model(model_name)

    def _ensure_imports(self) -> None:
        if IMPORT_ERROR is not None:
            raise RuntimeError(
                "The 'whisper' package (with PyTorch) is required for transcription"
            ) from IMPORT_ERROR

    def _load_model(self, model_name: str) -> None:
        if model_name not in self.SUPPORTED_MODELS:
            raise ValueError(f"Unsupported Whisper model: {model_name}")
        try:
            download_root = os.getenv("WHISPER_CACHE_DIR")
            load_kwargs = {"download_root": download_root} if download_root else {}
            self._model = whisper.load_model(model_name, device="cpu", **load_kwargs)
        except Exception as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(f"Failed to load Whisper model '{model_name}': {exc}") from exc
        self.model_name = model_name
        LOGGER.info("Whisper model '%s' loaded", model_name)

    def ensure_model(self, model_name: str) -> None:
        """Reload the model if the requested name differs from the current one."""

        if self._model is None or model_name != self.model_name:
            self._load_model(model_name)

    # ------------------------------------------------------------------
    # Language detection
    # ------------------------------------------------------------------
    def detect_language(self, audio_bytes: bytes) -> str:
        if not audio_bytes:
            return "en"
        self._require_model()
        audio = self._bytes_to_float32(audio_bytes)
        mel = whisper.log_mel_spectrogram(audio)
        _, probs = self._model.detect_language(mel)
        return max(probs, key=probs.get)

    # ------------------------------------------------------------------
    # Streaming chunks
    # ------------------------------------------------------------------
    def transcribe_chunk(self, audio_bytes: bytes) -> str:
        if not audio_bytes:
            return ""
        self._require_model()
        audio = self._bytes_to_float32(audio_bytes)
        try:
            result = self._model.transcribe(audio, fp16=False, language=None, verbose=False)
        except Exception as exc:  # pragma: no cover - model level error
            LOGGER.error("Whisper chunk transcription failed: %s", exc)
            return ""
        return result.get("text", "").strip()

    # ------------------------------------------------------------------
    # Batch transcription
    # ------------------------------------------------------------------
    def transcribe_file(
        self, file_path: str, callback_progress: Optional[Callable[[str], bool]] = None
    ) -> str:
        if not os.path.isfile(file_path):
            raise FileNotFoundError(file_path)

        self._require_model()
        try:
            result = self._model.transcribe(file_path, fp16=False, language=None, verbose=False)
        except Exception as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(f"Failed to transcribe file '{file_path}': {exc}") from exc

        final_segments: list[str] = []
        segments = result.get("segments") or []
        for segment in segments:
            text = (segment.get("text") or "").strip()
            if not text:
                continue
            final_segments.append(text)
            if callback_progress:
                try:
                    should_continue = callback_progress(text)
                except Exception:  # pragma: no cover - callback errors handled by caller
                    LOGGER.exception("Transcription progress callback raised an exception")
                    should_continue = True
                if should_continue is False:
                    return "\n".join(final_segments)

        if not final_segments:
            text = (result.get("text") or "").strip()
            if text:
                final_segments.append(text)
                if callback_progress:
                    callback_progress(text)

        return "\n".join(final_segments)

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------
    def _bytes_to_float32(self, audio_bytes: bytes) -> np.ndarray:
        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
        if samples.size == 0:
            return np.zeros(1, dtype=np.float32)
        return samples / 32768.0

    def _require_model(self) -> None:
        if self._model is None:
            raise RuntimeError("Whisper model is not loaded")
