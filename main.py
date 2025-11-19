"""Application entry point."""

from __future__ import annotations

import logging
import os
import sys

from audio_engine import AudioEngine
from config import load_config
from gui_audio import AudioTranscriptionGUI
from logging_config import setup_logging
from stt_engine import STTEngine


def main() -> int:
    """Bootstrap and start the GUI application."""

    config = load_config()
    setup_logging(config.LOG_DIR)
    LOGGER = logging.getLogger(__name__)

    model_cache = config.MODEL_DIR
    os.makedirs(model_cache, exist_ok=True)
    os.environ.setdefault("WHISPER_CACHE_DIR", model_cache)

    default_model = getattr(config, "DEFAULT_WHISPER_MODEL", "small")
    try:
        stt_engine = STTEngine(model_name=default_model)
    except Exception as exc:
        LOGGER.error("Failed to load default Whisper model '%s': %s", default_model, exc)
        return 1
    audio_engine = AudioEngine(
        sample_rate=config.DEFAULT_SAMPLE_RATE, chunk_duration_ms=config.REALTIME_CHUNK_DURATION_MS
    )

    gui = AudioTranscriptionGUI(stt_engine=stt_engine, audio_engine=audio_engine, config=config)
    try:
        gui.run()
    except KeyboardInterrupt:
        LOGGER.info("Application interrupted by user")
    return 0


if __name__ == "__main__":
    sys.exit(main())
