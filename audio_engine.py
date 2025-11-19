"""Audio engine abstraction used by the GUI and STT pipeline.

The actual project will eventually connect to native audio drivers. For this
exercise we provide a light-weight simulation that mirrors the structure and
error handling expected by the GUI. This allows the GUI, transcription logic
and threading model to be validated without requiring native audio hardware in
the execution environment.
"""

from __future__ import annotations

import os
import random
import threading
import time
import typing as t
import wave


try:  # Optional dependency, used only when available.
    import sounddevice as sd  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    sd = None


class AudioEngine:
    """Manage audio device enumeration and simulated audio streaming."""

    def __init__(self, sample_rate: int = 16_000, chunk_duration_ms: int = 2000):
        self.sample_rate = sample_rate
        self.chunk_duration_ms = chunk_duration_ms
        self._recording_thread: threading.Thread | None = None
        self._recording_event = threading.Event()
        self._callback: t.Optional[t.Callable[[bytes], None]] = None
        self._audio_buffer = bytearray()
        self._buffer_lock = threading.Lock()
        self._latest_level = 0.0

    # ------------------------------------------------------------------
    # Device enumeration
    # ------------------------------------------------------------------
    def list_input_devices(self) -> t.List[dict]:
        """Return the list of available input devices.

        When `sounddevice` is not available a deterministic mock device list is
        returned so that the GUI remains usable.
        """

        devices: t.List[dict] = []
        if sd is not None:
            try:
                for idx, info in enumerate(sd.query_devices()):
                    if info.get("max_input_channels", 0) > 0:
                        devices.append({"id": idx, "name": info.get("name", f"Device {idx}")})
            except Exception:
                devices = []

        if not devices:
            # Fallback list for environments without audio hardware.
            devices = [
                {"id": 0, "name": "Simulated Microphone"},
                {"id": 1, "name": "Simulated Loopback"},
            ]

        return devices

    # ------------------------------------------------------------------
    # Recording controls
    # ------------------------------------------------------------------
    def start_recording(self, device_id: int, callback_chunk: t.Callable[[bytes], None]):
        """Start the simulated recording loop.

        Parameters
        ----------
        device_id:
            Identifier of the selected input device. It is currently used only
            for logging purposes.
        callback_chunk:
            Callable receiving each recorded byte chunk.
        """

        if self._recording_thread and self._recording_thread.is_alive():
            raise RuntimeError("Recording already in progress")

        self._callback = callback_chunk
        self._audio_buffer = bytearray()
        self._recording_event.clear()
        self._recording_thread = threading.Thread(
            target=self._record_loop, args=(device_id,), daemon=True
        )
        self._recording_thread.start()

    def _record_loop(self, device_id: int) -> None:
        chunk_size = int(self.sample_rate * (self.chunk_duration_ms / 1000.0) * 2)
        while not self._recording_event.is_set():
            # Simulate audio capture by generating pseudo-random bytes.
            chunk = os.urandom(chunk_size)
            with self._buffer_lock:
                self._audio_buffer.extend(chunk)

            self._latest_level = random.random()

            if self._callback:
                self._callback(chunk)

            sleep_time = self.chunk_duration_ms / 1000.0
            time.sleep(sleep_time)

    def stop_recording(self):
        """Stop the simulated recording loop."""

        if self._recording_thread and self._recording_thread.is_alive():
            self._recording_event.set()
            self._recording_thread.join(timeout=2)
        self._recording_thread = None

    def save_audio(self, output_path: str):
        """Persist the recorded byte buffer as a PCM WAV file."""

        with self._buffer_lock:
            buffer_copy = bytes(self._audio_buffer)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with wave.open(output_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(buffer_copy)

    # ------------------------------------------------------------------
    # Telemetry helpers
    # ------------------------------------------------------------------
    def get_audio_level(self) -> float:
        """Return the latest simulated level for UI metering."""

        return max(0.0, min(1.0, self._latest_level))

