# OfflineVoiceToText

This repository contains a specialized Python desktop application designed for real-time, offline transcription of meetings on Windows 11 systems.

The core goal is to provide maximum privacy and performance without requiring administrative privileges or external cloud services. It uses pyaudio for continuous audio input and the highly optimized faster-whisper model (specifically the "turbo" variant) for high-speed, CPU-based transcription.

Key Features:
Offline & Private: All processing, including transcription, runs locally.

Real-Time Performance: Utilizes multi-threading and faster-whisper for low-latency results.

Loopback Audio Capture: Capable of recording system audio (e.g., virtual meeting platforms) via a robust pyaudio configuration.

Automatic Language Detection: Supports both English and Italian.

Standalone Executable: Designed for easy deployment via PyInstaller.

The application includes a tkinter GUI for input device selection, real-time transcription display, and output file management.

## Quick start

```bash
git clone https://github.com/ggml-org/whisper.cpp.git
```
