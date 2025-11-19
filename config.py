class AppConfig:
    """
    Holds configuration constants and defaults.
    """

    DEFAULT_SAMPLE_RATE = 16000
    DEFAULT_CHANNELS = 1
    REALTIME_CHUNK_DURATION_MS = 2000
    SUPPORTED_AUDIO_FORMATS = [".wav", ".mp3", ".flac"]
    LOG_DIR = "logs"
    MODEL_DIR = "models"
    DEFAULT_WHISPER_MODEL = "small"

def load_config() -> AppConfig:
    """Return config object."""
    return AppConfig()
