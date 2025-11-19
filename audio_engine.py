"""Audio capture engine built on top of real audio backends."""

from __future__ import annotations

import logging
import queue
import threading
import typing as t
import wave

import numpy as np

try:  # Preferred backend (WASAPI capable on Windows)
    import sounddevice as sd  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    sd = None

try:  # Fallback backend
    import pyaudio  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pyaudio = None


LOGGER = logging.getLogger(__name__)


class AudioEngine:
    """Manage audio device enumeration and PCM streaming."""

    def __init__(self, sample_rate: int = 16_000, chunk_duration_ms: int = 2000) -> None:
        self.sample_rate = sample_rate
        self.chunk_duration_ms = chunk_duration_ms
        self._chunk_frames = int(self.sample_rate * (self.chunk_duration_ms / 1000.0))

        self._chunk_queue: queue.Queue[bytes] | None = None
        self._callback: t.Optional[t.Callable[[bytes], None]] = None
        self._recording_event = threading.Event()
        self._recording_thread: threading.Thread | None = None
        self._producer_thread: threading.Thread | None = None
        self._audio_buffer = bytearray()
        self._buffer_lock = threading.Lock()
        self._latest_level = 0.0

        # Backend specific handles
        self._sd_stream = None
        self._pa_instance = None
        self._pa_stream = None

    # ------------------------------------------------------------------
    # Device enumeration
    # ------------------------------------------------------------------
    def list_input_devices(self) -> list[dict]:
        """Return the list of available input devices."""

        devices: list[dict] = []

        if sd is not None:
            try:
                for idx, info in enumerate(sd.query_devices()):
                    if info.get("max_input_channels", 0) > 0:
                        devices.append({"id": idx, "name": info.get("name", f"Device {idx}")})
            except Exception as exc:  # pragma: no cover - hardware specific
                LOGGER.warning("Failed to query sounddevice inputs: %s", exc)

        if not devices and pyaudio is not None:
            try:
                pa = pyaudio.PyAudio()
                for idx in range(pa.get_device_count()):
                    info = pa.get_device_info_by_index(idx)
                    if info.get("maxInputChannels", 0) > 0:
                        devices.append({"id": idx, "name": info.get("name", f"Device {idx}")})
            except Exception as exc:  # pragma: no cover - hardware specific
                LOGGER.warning("Failed to query PyAudio inputs: %s", exc)
            finally:
                try:
                    pa.terminate()
                except Exception:
                    pass

        return devices

    # ------------------------------------------------------------------
    # Recording controls
    # ------------------------------------------------------------------
    def start_recording(self, device_id: int, callback_chunk: t.Callable[[bytes], None]) -> None:
        """Start capturing audio from the given device."""

        if self._recording_thread and self._recording_thread.is_alive():
            raise RuntimeError("Recording already in progress")

        self._callback = callback_chunk
        self._audio_buffer = bytearray()
        self._chunk_queue = queue.Queue()
        self._recording_event.clear()
        self._latest_level = 0.0

        if not self._initialise_backend(device_id):
            raise RuntimeError(
                "No usable audio backend available. Install 'sounddevice' or 'pyaudio'."
            )

        self._recording_thread = threading.Thread(target=self._consumer_loop, daemon=True)
        self._recording_thread.start()

    def _initialise_backend(self, device_id: int) -> bool:
        """Try sounddevice first, fall back to PyAudio."""

        if sd is not None:
            try:
                self._start_sounddevice_stream(device_id)
                LOGGER.info("Sounddevice backend initialised (device %s)", device_id)
                return True
            except Exception as exc:
                LOGGER.error("Failed to start sounddevice stream: %s", exc)
                self._cleanup_sounddevice()

        if pyaudio is not None:
            try:
                self._start_pyaudio_stream(device_id)
                LOGGER.info("PyAudio backend initialised (device %s)", device_id)
                return True
            except Exception as exc:
                LOGGER.error("Failed to start PyAudio stream: %s", exc)
                self._cleanup_pyaudio()

        return False

    def _start_sounddevice_stream(self, device_id: int) -> None:
        if sd is None:  # pragma: no cover - guard
            raise RuntimeError("sounddevice not available")

        self._sd_stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self._chunk_frames,
            device=device_id,
            callback=self._sounddevice_callback,
        )
        self._sd_stream.start()

    def _sounddevice_callback(self, indata, frames, time_info, status):  # pragma: no cover - C callback
        if status:
            LOGGER.warning("Sounddevice stream status: %s", status)
        if self._chunk_queue is None:
            return
        chunk = indata.copy().tobytes()
        self._chunk_queue.put(chunk)

    def _start_pyaudio_stream(self, device_id: int) -> None:
        if pyaudio is None:  # pragma: no cover - guard
            raise RuntimeError("PyAudio not available")

        self._pa_instance = pyaudio.PyAudio()
        self._pa_stream = self._pa_instance.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            input=True,
            input_device_index=device_id,
            frames_per_buffer=self._chunk_frames,
        )

        def producer() -> None:  # pragma: no cover - interacts with audio hardware
            assert self._chunk_queue is not None
            while not self._recording_event.is_set():
                data = self._pa_stream.read(self._chunk_frames, exception_on_overflow=False)
                self._chunk_queue.put(data)

        self._producer_thread = threading.Thread(target=producer, daemon=True)
        self._producer_thread.start()

    # ------------------------------------------------------------------
    # Data processing
    # ------------------------------------------------------------------
    def _consumer_loop(self) -> None:
        assert self._chunk_queue is not None
        while not self._recording_event.is_set() or not self._chunk_queue.empty():
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
                except Exception:  # pragma: no cover - user callback error
                    LOGGER.exception("Chunk callback raised an exception")

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def stop_recording(self) -> None:
        """Stop recording and free resources."""

        self._recording_event.set()

        if self._producer_thread is not None:
            self._producer_thread.join(timeout=2)
            self._producer_thread = None

        if self._sd_stream is not None:
            try:
                self._sd_stream.stop()
            except Exception:
                pass
            try:
                self._sd_stream.close()
            except Exception:
                pass
            self._sd_stream = None

        if self._pa_stream is not None:
            try:
                self._pa_stream.stop_stream()
            except Exception:
                pass
            try:
                self._pa_stream.close()
            except Exception:
                pass
            self._pa_stream = None

        if self._pa_instance is not None:
            try:
                self._pa_instance.terminate()
            except Exception:
                pass
            self._pa_instance = None

        if self._recording_thread is not None:
            self._recording_thread.join(timeout=2)
            self._recording_thread = None

        self._chunk_queue = None
        self._callback = None
        self._recording_event.clear()

    def _cleanup_sounddevice(self) -> None:
        if self._sd_stream is not None:
            try:
                self._sd_stream.close()
            except Exception:
                pass
            self._sd_stream = None

    def _cleanup_pyaudio(self) -> None:
        if self._pa_stream is not None:
            try:
                self._pa_stream.close()
            except Exception:
                pass
            self._pa_stream = None
        if self._pa_instance is not None:
            try:
                self._pa_instance.terminate()
            except Exception:
                pass
            self._pa_instance = None

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def save_audio(self, output_path: str) -> None:
        """Write the recorded audio buffer to a WAV file."""

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
