# Offline Real-Time Speech-to-Text Desktop App  
**Windows 11 – Offline – Privacy-Focused – Python – Packaged with PyInstaller**

---

## 📌 Overview

This repository contains the source code for an **offline speech-to-text desktop application** for Windows 11.  
The app provides:

- **Real-time audio recording + transcription**  
- **Transcription of existing audio files**  
- **Full privacy (offline models, no data sent anywhere)**  
- **Simple and user-friendly GUI**  
- **Automatic language detection (Italian / English)**  
- **Standalone executable packaging (PyInstaller --onefile)**

The application uses a modular architecture with separated components for GUI, audio recording, transcription engine, config, and logging.

---

## Quick start

```bash
git clone https://github.com/egliott/OfflineVoiceToText
```

---

## 🚀 Features

### 🎙 Recording Mode
- Select audio input device (microphone, loopback, etc.)
- Real-time transcription with ongoing text updates
- Save audio and transcription text at the end

### 📄 Audio File Transcription Mode
- Load any supported audio file (`.wav`, `.mp3`, `.flac`)
- Batch transcription with progress updates
- Save output transcript as `.txt`

### 🧠 Offline Speech Recognition
- Supports Italian 🇮🇹 and English 🇬🇧  
- Automatic language detection  
- No network access required  

### 📦 Standalone Packaging
- Compatible with **PyInstaller --onefile**
- No installation required for end-users  
- No admin rights required on Windows 11
