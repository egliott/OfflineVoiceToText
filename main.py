"""Core logic for the offline real-time transcriber.

This module exposes the :class:`RealTimeTranscriber` class which encapsulates
all the audio capture and transcription logic used by the GUI.  The code is
standalone, therefore it can be executed directly (``python main.py``) to test
recording/transcription without the graphical interface.

Key goals of this rewrite:
    * Provide a single, easy to understand entry point.
    * Guarantee clean startup/shutdown and extensive logging.
    * Fix the Windows loopback distortion by matching the sampling parameters
      of the chosen device and converting to the 16 kHz / mono format expected
      by ``faster-whisper`` before transcription.
"""
from __future__ import annotations

import argparse
import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pyaudiowpatch as pyaudio
from faster_whisper import WhisperModel

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
LOG_DIR = Path.home() / "AudioTranscriber_Logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "transcriber.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ],
)
LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TARGET_SAMPLE_RATE = 16_000  # Whisper works best with 16 kHz mono audio
SAMPLE_WIDTH = 2             # 16-bit PCM
TARGET_CHANNELS = 1

# Amount of raw audio (in seconds) that we send to the transcription thread
CHUNK_DURATION_SECONDS = 5
QUEUE_MAX_SIZE = 5


@dataclass
class DeviceInfo:
    """Simple representation of an audio device."""

    index: int
    name: str
    max_input_channels: int
    default_sample_rate: int
    host_api: str
    is_loopback: bool = False


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _resample(audio: np.ndarray, orig_rate: int, target_rate: int) -> np.ndarray:
    """Resample ``audio`` from ``orig_rate`` to ``target_rate`` using linear
    interpolation.  ``audio`` must be a mono float32 signal in the [-1, 1] range."""

    if orig_rate == target_rate or audio.size == 0:
        return audio

    duration = audio.size / orig_rate
    target_length = int(duration * target_rate)
    if target_length == 0:
        return np.zeros(0, dtype=np.float32)

    src_positions = np.linspace(0, audio.size - 1, num=target_length)
    resampled = np.interp(src_positions, np.arange(audio.size), audio)
    return resampled.astype(np.float32, copy=False)


def _int16_bytes_to_mono_float32(
    data: bytes,
    channels: int,
) -> np.ndarray:
    """Convert raw int16 bytes into a mono float32 numpy array."""

    if channels <= 0:
        raise ValueError("The selected device does not expose input channels")

    audio = np.frombuffer(data, dtype=np.int16)
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return (audio.astype(np.float32) / 32768.0).clip(-1.0, 1.0)


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------


class RealTimeTranscriber:
    """Manage audio capture and real-time transcription."""

    def __init__(
        self,
        model_size: str = "turbo",
        model_device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        self.model_size = model_size
        self.model_device = model_device
        self.compute_type = compute_type

        self._audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=QUEUE_MAX_SIZE)
        self._record_thread: Optional[threading.Thread] = None
        self._transcribe_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._pa: Optional[pyaudio.PyAudio] = None
        self._stream: Optional[pyaudio.Stream] = None
        self._device_info: Optional[DeviceInfo] = None
        self._device_channels: int = TARGET_CHANNELS
        self._device_rate: int = TARGET_SAMPLE_RATE

        self._model: Optional[WhisperModel] = None
        self._chunks_processed = 0

    # ------------------------------------------------------------------
    # Device helpers
    # ------------------------------------------------------------------
    def get_audio_devices(self) -> List[DeviceInfo]:
        """Enumerate available input and loopback devices."""

        devices: List[DeviceInfo] = []
        pa = pyaudio.PyAudio()
        try:
            host_api_cache: Dict[int, str] = {}
            for index in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(index)
                max_input = int(info.get("maxInputChannels", 0))
                # Loopback devices expose input channels even though they are
                # internally capturing the output stream.  We flag them by
                # checking the WASAPI property exposed by pyaudiowpatch.
                is_loopback = bool(info.get("isLoopbackDevice", False))
                if max_input == 0:
                    continue

                host_api_index = info.get("hostApi", 0)
                host_api = host_api_cache.get(host_api_index)
                if host_api is None:
                    host_api = pa.get_host_api_info_by_index(host_api_index)["name"]
                    host_api_cache[host_api_index] = host_api

                devices.append(
                    DeviceInfo(
                        index=index,
                        name=info.get("name", f"Device {index}"),
                        max_input_channels=max_input,
                        default_sample_rate=int(info.get("defaultSampleRate", TARGET_SAMPLE_RATE)),
                        host_api=host_api,
                        is_loopback=is_loopback,
                    )
                )
        finally:
            pa.terminate()
        return devices

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self, device_index: int) -> None:
        """Start recording/transcription using ``device_index``."""

        if self._record_thread and self._record_thread.is_alive():
            raise RuntimeError("Recording is already running")

        devices = {d.index: d for d in self.get_audio_devices()}
        if device_index not in devices:
            raise ValueError(f"Invalid device index: {device_index}")

        self._device_info = devices[device_index]
        self._device_rate = self._device_info.default_sample_rate
        self._device_channels = min(self._device_info.max_input_channels, 2)
        LOGGER.info(
            "Selected device %s (loopback=%s, rate=%s Hz, channels=%s)",
            self._device_info.name,
            self._device_info.is_loopback,
            self._device_rate,
            self._device_channels,
        )

        self._ensure_model()

        self._pa = pyaudio.PyAudio()
        frames_per_buffer = max(1024, int(self._device_rate * 0.05))  # ~50 ms

        open_kwargs = dict(
            format=pyaudio.paInt16,
            channels=self._device_channels,
            rate=self._device_rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=frames_per_buffer,
            stream_callback=None,
        )

        # When capturing loopback audio on WASAPI we explicitly pass the
        # loopback flag to avoid distorted audio caused by driver resampling.
        if self._device_info.is_loopback and hasattr(pyaudio, "PaWasapiStreamInfo"):
            stream_info = pyaudio.PaWasapiStreamInfo(flags=pyaudio.paWinWasapiLoopback)
            open_kwargs["stream_info"] = stream_info

        self._stream = self._pa.open(**open_kwargs)
        self._stop_event.clear()
        self._chunks_processed = 0

        self._record_thread = threading.Thread(target=self._recording_worker, daemon=True)
        self._transcribe_thread = threading.Thread(target=self._transcription_worker, daemon=True)
        self._record_thread.start()
        self._transcribe_thread.start()
        LOGGER.info("Recording started")

    def stop(self) -> None:
        """Stop recording and transcription threads."""

        self._stop_event.set()
        if self._record_thread:
            self._record_thread.join()
            self._record_thread = None
        if self._transcribe_thread:
            self._transcribe_thread.join()
            self._transcribe_thread = None

        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self._pa:
            self._pa.terminate()
            self._pa = None
        LOGGER.info("Recording stopped")

    def _ensure_model(self) -> None:
        if self._model is None:
            LOGGER.info("Loading faster-whisper model '%s'", self.model_size)
            self._model = WhisperModel(
                self.model_size,
                device=self.model_device,
                compute_type=self.compute_type,
            )

    # ------------------------------------------------------------------
    # Worker threads
    # ------------------------------------------------------------------
    def _recording_worker(self) -> None:
        assert self._stream is not None
        assert self._device_info is not None

        LOGGER.info("Recording thread ready")
        bytes_per_frame = SAMPLE_WIDTH * self._device_channels
        chunk_frames = int(self._device_rate * CHUNK_DURATION_SECONDS)
        chunk_bytes_target = chunk_frames * bytes_per_frame
        buffer = bytearray()

        while not self._stop_event.is_set():
            try:
                data = self._stream.read(self._stream._frames_per_buffer, exception_on_overflow=False)
            except Exception as exc:  # pragma: no cover - hardware errors
                LOGGER.error("Audio read failed: %s", exc)
                time.sleep(0.1)
                continue

            buffer.extend(data)
            if len(buffer) < chunk_bytes_target:
                continue

            chunk = bytes(buffer[:chunk_bytes_target])
            del buffer[:chunk_bytes_target]

            float_audio = _int16_bytes_to_mono_float32(chunk, self._device_channels)
            float_audio = _resample(float_audio, self._device_rate, TARGET_SAMPLE_RATE)

            put = False
            while not put and not self._stop_event.is_set():
                try:
                    self._audio_queue.put(float_audio, timeout=0.5)
                    put = True
                except queue.Full:
                    LOGGER.warning("Audio queue is full; dropping oldest chunk")
                    try:
                        self._audio_queue.get_nowait()
                    except queue.Empty:
                        pass

    def _transcription_worker(self) -> None:
        assert self._model is not None
        LOGGER.info("Transcription thread ready")

        while not self._stop_event.is_set():
            try:
                audio = self._audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                segments, info = self._model.transcribe(
                    audio,
                    language=None,
                    vad_filter=True,
                    vad_parameters={"threshold": 0.3},
                )
                text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
                if text:
                    self._chunks_processed += 1
                    LOGGER.info("[%s] %s", info.language or "?", text)
            except Exception as exc:  # pragma: no cover - model errors
                LOGGER.error("Transcription failed: %s", exc)

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------
    def get_status(self) -> Dict[str, int]:
        return {
            "queue_size": self._audio_queue.qsize(),
            "chunks_processed": self._chunks_processed,
        }


# ---------------------------------------------------------------------------
# CLI for manual testing
# ---------------------------------------------------------------------------

def _print_devices(transcriber: RealTimeTranscriber) -> None:
    print("Available input / loopback devices:\n")
    for dev in transcriber.get_audio_devices():
        loopback_flag = " (loopback)" if dev.is_loopback else ""
        print(
            f"[{dev.index:02d}] {dev.name}{loopback_flag} - "
            f"{dev.default_sample_rate} Hz, {dev.max_input_channels} ch, API: {dev.host_api}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone test for RealTimeTranscriber")
    parser.add_argument("--list-devices", action="store_true", help="List audio devices and exit")
    parser.add_argument("--device", type=int, default=None, help="Device index to use")
    parser.add_argument("--duration", type=int, default=30, help="Seconds to run the test")
    args = parser.parse_args()

    transcriber = RealTimeTranscriber()

    if args.list_devices:
        _print_devices(transcriber)
        return

    devices = transcriber.get_audio_devices()
    if not devices:
        print("No audio devices available")
        return

    device_index = args.device if args.device is not None else devices[0].index
    _print_devices(transcriber)
    print(f"\nUsing device {device_index}")

    try:
        transcriber.start(device_index)
        print("Recording... Press Ctrl+C to stop")
        start_time = time.time()
        while time.time() - start_time < args.duration:
            time.sleep(2)
            status = transcriber.get_status()
            print(
                f"\rChunks processed: {status['chunks_processed']:3d} | "
                f"Queue fill: {status['queue_size']:2d}/{QUEUE_MAX_SIZE}",
                end="",
            )
        print()
    except KeyboardInterrupt:
        print("Interrupted by user")
    finally:
        transcriber.stop()


if __name__ == "__main__":
    main()
