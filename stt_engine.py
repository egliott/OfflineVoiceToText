"""Simplified offline Speech-to-Text engine placeholder.

The implementation in this repository emulates the behaviour of a streaming
STT pipeline. It is intentionally light-weight so that the GUI, threading and
file management aspects of the PRD can be exercised in the execution
environment. Real deployments can replace the heuristic transcription functions
with a genuine STT backend without changing the public API.
"""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Callable, Optional


LOGGER = logging.getLogger(__name__)


class STTEngine:
    """Offline Speech-to-Text facade used by the GUI."""

    def __init__(self, model_path: str):
        self.model_path = model_path
        self._chunk_counter = 0
        LOGGER.info("STT engine initialised with models at %s", model_path)

    # ------------------------------------------------------------------
    # Language detection / heuristics
    # ------------------------------------------------------------------
    def detect_language(self, audio_chunk: bytes) -> str:
        """Return a pseudo language prediction for the chunk."""

        if not audio_chunk:
            return "en"
        checksum = sum(audio_chunk[:100])
        return "it" if checksum % 2 else "en"

    # ------------------------------------------------------------------
    # Real-time chunk transcription
    # ------------------------------------------------------------------
    def transcribe_chunk(self, audio_chunk: bytes) -> str:
        """Return a synthetic transcription string for the chunk."""

        self._chunk_counter += 1
        language = self.detect_language(audio_chunk)
        pseudo_words = random.choice(
            [
                "meeting update",
                "action item",
                "nota importante",
                "status report",
                "promemoria",
            ]
        )
        text = f"[{language.upper()} chunk {self._chunk_counter}] {pseudo_words}."
        LOGGER.debug("Transcribed chunk %s", self._chunk_counter)
        return text

    # ------------------------------------------------------------------
    # File transcription
    # ------------------------------------------------------------------
    def transcribe_file(
        self, file_path: str, callback_progress: Optional[Callable[[str], bool]] = None
    ) -> str:
        """Process a full audio file and optionally report incremental chunks.

        Parameters
        ----------
        file_path:
            Path to the audio file.
        callback_progress:
            Callable invoked with every generated text chunk. If the callback
            returns ``False`` the transcription is aborted early and the
            accumulated text is returned.
        """

        LOGGER.info("Starting batch transcription of %s", file_path)
        final_chunks: list[str] = []
        chunk_index = 0

        if not os.path.isfile(file_path):
            raise FileNotFoundError(file_path)

        with open(file_path, "rb") as audio_file:
            while True:
                raw = audio_file.read(4096)
                if not raw:
                    break

                chunk_index += 1
                text = f"[FILE chunk {chunk_index}] {self.transcribe_chunk(raw)}"
                final_chunks.append(text)

                if callback_progress:
                    should_continue = callback_progress(text)
                    if should_continue is False:
                        LOGGER.info("Batch transcription cancelled by caller")
                        return "\n".join(final_chunks)

                time.sleep(0.3)  # Simulate inference latency.

        LOGGER.info("Finished batch transcription of %s", file_path)
        return "\n".join(final_chunks)

