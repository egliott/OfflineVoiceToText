"""Audio capture engine used by the GUI and STT pipeline.

This implementation uses real audio devices exposed by the operating system.
It supports both ``sounddevice`` (WASAPI on Windows allows enabling loopback by
selecting a loopback-capable device) and ``pyaudio`` as a fallback backend.

Loopback note for Windows users: loopback capture requires selecting a device
labelled with ``(loopback)`` when WASAPI support is installed. Windows 11 users
can enable it by activating the "Stereo Mix" device or any WASAPI loopback
endpoint from the sound settings.
"""

from __future__ import annotations

import logging
import queue
import threading
import typing as t
import wave

import numpy as np

try:  # Preferred backend
    import sounddevice as sd  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    sd = None

try:  # Fallback backend
    import pyaudio  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pyaudio = None


logger = logging.getLogger(__name__)


class AudioEngine:
    """Manage audio device enumeration and real audio streaming."""

    def __init__(self, sample_rate: int = 16_000, chunk_duration_ms: int = 2000):
        self.sample_rate = sample_rate
        self.chunk_duration_ms = chunk_duration_ms
        self._chunk_frames = int(self.sample_rate * (self.chunk_duration_ms / 1000.0))
        self._callback: t.Optional[t.Callable[[bytes], None]] = None
        self._recording_thread: threading.Thread | None = None
        self._recording_event = threading.Event()
        self._buffer_lock = threading.Lock()
        self._audio_buffer = bytearray()
        self._latest_level = 0.0
        self._chunk_queue: queue.Queue[bytes] | None = None
        self._stream = None
        self._backend: str | None = None
        self._pa_instance = None
        self._producer_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Device enumeration
    # ------------------------------------------------------------------
    def list_input_devices(self) -> t.List[dict]:
        """Return a list of available input devices."""

        devices: t.List[dict] = []

        if sd is not None:
            try:
                for idx, info in enumerate(sd.query_devices()):
                    if info.get("max_input_channels", 0) > 0:
                        devices.append({"id": idx, "name": info.get("name", f"Device {idx}")})
            except Exception as exc:  # pragma: no cover - device query only
                logger.warning("Failed to query sounddevice inputs: %s", exc)

        if not devices and pyaudio is not None:
            try:
                pa = pyaudio.PyAudio()
                for idx in range(pa.get_device_count()):
                    info = pa.get_device_info_by_index(idx)
                    if info.get("maxInputChannels", 0) > 0:
                        devices.append({"id": idx, "name": info.get("name", f"Device {idx}")})
            finally:  # pragma: no cover - clean up
                try:
                    pa.terminate()
                except Exception:
                    pass

        return devices

    # ------------------------------------------------------------------
    # Recording controls
    # ------------------------------------------------------------------
    def start_recording(self, device_id: int, callback_chunk: t.Callable[[bytes], None]):
        """Start recording from the selected device."""

        if self._recording_thread and self._recording_thread.is_alive():
            raise RuntimeError("Recording already in progress")

        self._callback = callback_chunk
        self._audio_buffer = bytearray()
        self._recording_event.clear()
        self._chunk_queue = queue.Queue()

        started = False
        if sd is not None:
            try:
                self._start_sounddevice_stream(device_id)
                self._backend = "sounddevice"
                started = True
            except Exception as exc:
                logger.error("Failed to start sounddevice stream: %s", exc)

        if not started and pyaudio is not None:
            try:
                self._start_pyaudio_stream(device_id)
                self._backend = "pyaudio"
                started = True
            except Exception as exc:
                logger.error("Failed to start PyAudio stream: %s", exc)

        if not started:
            raise RuntimeError("No usable audio backend is available. Install 'sounddevice' or 'pyaudio'.")

        self._recording_thread = threading.Thread(target=self._consumer_loop, daemon=True)
        self._recording_thread.start()

    def _start_sounddevice_stream(self, device_id: int) -> None:
        if sd is None:  # pragma: no cover - guard
            raise RuntimeError("sounddevice backend not available")

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            device=device_id,
            blocksize=self._chunk_frames,
            callback=self._sounddevice_callback,
        )
        self._stream.start()

    def _sounddevice_callback(self, indata, frames, time_info, status):  # pragma: no cover - runs in C callback
        if status:
            logger.warning("Sounddevice stream status: %s", status)
        if self._chunk_queue is None:
            return
        # Copy data to avoid referencing the internal buffer after callback returns.
        chunk = indata.copy().tobytes()
        self._chunk_queue.put(chunk)

    def _start_pyaudio_stream(self, device_id: int) -> None:
        if pyaudio is None:  # pragma: no cover - guard
            raise RuntimeError("PyAudio backend not available")

        self._pa_instance = pyaudio.PyAudio()
        self._stream = self._pa_instance.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            input=True,
            input_device_index=device_id,
            frames_per_buffer=self._chunk_frames,
        )

        def producer():  # pragma: no cover - interacts with hardware
            assert self._chunk_queue is not None
            while not self._recording_event.is_set():
                data = self._stream.read(self._chunk_frames, exception_on_overflow=False)
                self._chunk_queue.put(data)

        self._producer_thread = threading.Thread(target=producer, daemon=True)
        self._producer_thread.start()

    # ------------------------------------------------------------------
    # Data processing
    # ------------------------------------------------------------------
    def _consumer_loop(self) -> None:
        assert self._chunk_queue is not None
        while not self._recording_event.is_set():
            try:
                chunk = self._chunk_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            with self._buffer_lock:
                self._audio_buffer.extend(chunk)

            self._latest_level = self._compute_level(chunk)

            if self._callback:
                try:
                    self._callback(chunk)
                except Exception:
                    logger.exception("Chunk callback raised an exception")

    # ------------------------------------------------------------------
    # Recording shutdown
    # ------------------------------------------------------------------
    def stop_recording(self):
        """Stop the recording loop and release audio resources."""

        self._recording_event.set()

        if self._backend == "pyaudio" and self._producer_thread is not None:
            self._producer_thread.join(timeout=2)

        if self._stream is not None:
            try:
                if self._backend == "pyaudio":
                    self._stream.stop_stream()
                else:
                    self._stream.stop()
            except Exception:
                pass
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        if self._backend == "pyaudio" and self._pa_instance is not None:
            try:
                self._pa_instance.terminate()
            except Exception:
                pass
            self._pa_instance = None

        if self._recording_thread and self._recording_thread.is_alive():
            self._recording_thread.join(timeout=2)
        self._recording_thread = None
        self._producer_thread = None
        self._chunk_queue = None
        self._backend = None
        self._recording_event.clear()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def save_audio(self, output_path: str):
        """Persist the recorded buffer as a PCM WAV file."""

        with self._buffer_lock:
            buffer_copy = bytes(self._audio_buffer)

        with wave.open(output_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(buffer_copy)

    # ------------------------------------------------------------------
    # Telemetry helpers
    # ------------------------------------------------------------------
    def get_audio_level(self) -> float:
        """Return the latest RMS-based level for UI metering."""

        return max(0.0, min(1.0, self._latest_level))

    @staticmethod
    def _compute_level(chunk: bytes) -> float:
        if not chunk:
            return 0.0
        samples = np.frombuffer(chunk, dtype=np.int16)
        if samples.size == 0:
            return 0.0
        rms = np.sqrt(np.mean(samples.astype(np.float64) ** 2))
        return float(min(1.0, rms / 32768.0))

