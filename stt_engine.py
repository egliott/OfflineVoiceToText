class STTEngine:
    """
    Offline Speech-to-Text engine.
    Supports:
    - Real-time chunk-based transcription
    - Batch transcription of audio files
    - Automatic language detection (IT/EN)
    """

    def __init__(self, model_path: str):
        """
        Load STT models and prepare inference.
        model_path: directory where models are stored.
        """
        pass

    def detect_language(self, audio_chunk: bytes) -> str:
        """
        Detect language for the given audio chunk.
        Return "it" or "en".
        """
        pass

    def transcribe_chunk(self, audio_chunk: bytes) -> str:
        """
        Transcribe a short audio chunk in real-time mode.
        Return the recognized text.
        """
        pass

    def transcribe_file(self, file_path: str, callback_progress: callable = None) -> str:
        """
        Transcribe an entire audio file.
        callback_progress(text_chunk) is called periodically.
        Returns final full transcription string.
        """
        pass
