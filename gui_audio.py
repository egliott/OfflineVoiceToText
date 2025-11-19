class AudioTranscriptionGUI:
    """
    Main application GUI.

    Responsibilities:
    - Provide the user interface for audio device selection.
    - Manage mode selection (record+transcribe vs. transcribe file).
    - Provide file/folder selection.
    - Display real-time transcription.
    - Display status bar updates.
    """

    def __init__(self, stt_engine, audio_engine):
        """
        Parameters:
        - stt_engine: instance of STTEngine
        - audio_engine: instance of AudioEngine
        """
        pass

    def build_ui(self):
        """Build all GUI widgets and layout."""
        pass

    # --- UI Controls ---
    def on_select_mode(self, mode: str):
        """Handle switching between modes."""
        pass

    def on_select_audio_device(self, device_id: int):
        """Handle audio device selection."""
        pass

    def on_select_audio_file(self):
        """Open dialog to select an audio file for transcription."""
        pass

    def on_select_output_folder(self):
        """Open dialog to select output folder."""
        pass

    def on_start_recording(self):
        """Start recording + real-time transcription."""
        pass

    def on_stop_and_save(self):
        """Stop recording/transcribing and save outputs."""
        pass

    # --- Live UI updates ---
    def update_transcription_text(self, text: str):
        """Append text to the scrollable transcription area."""
        pass

    def update_status(self, status: str):
        """Update the status bar."""
        pass

    def update_audio_level_meter(self, value: float):
        """Display audio input level (0.0 – 1.0)."""
        pass
