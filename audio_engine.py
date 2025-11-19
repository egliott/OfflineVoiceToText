import typing as t

class AudioEngine:
    """
    Manages audio device enumeration, audio recording,
    and streaming audio chunks to the STT engine.
    """

    def list_input_devices(self) -> t.List[dict]:
        """
        Return a list of available audio input devices.
        Example return format:
        [
            {"id": 0, "name": "Microphone (Realtek Audio)"},
            {"id": 1, "name": "Stereo Mix (Realtek)"},
        ]
        """
        pass

    def start_recording(self, device_id: int, callback_chunk: t.Callable[[bytes], None]):
        """
        Start recording from the selected device.
        Each audio chunk is passed to callback_chunk for STT processing.
        """
        pass

    def stop_recording(self):
        """Stop the recording thread/stream."""
        pass

    def save_audio(self, output_path: str):
        """
        Save the recorded audio buffer to a .wav file.
        Recording must accumulate audio internally.
        """
        pass

    def get_audio_level(self) -> float:
        """
        Return a numeric audio input level (0.0 – 1.0).
        Used to update a visual level meter.
        """
        pass
