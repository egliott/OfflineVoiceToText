# Product Requirements Document (PRD) #

Project: Offline Real-Time Speech-to-Text Desktop App (Windows)
Target: Python codebase packable into a single .exe with PyInstaller (--onefile)
Primary audience: Codex (code generator) and developers

## 1. Overview ##

We need a Windows desktop application with a graphical user interface (GUI) that can:

Record and transcribe audio in real time (for ~1-hour meetings).

Transcribe existing audio files.

The application must run fully offline, with maximum privacy, and must work on Windows 11 without administrator rights.
It will be developed in Python and packaged into a single standalone executable using PyInstaller (--onefile).

## 2. Goals and Non-Goals ##

### 2.1 Goals ###

Provide a user-friendly GUI to:

Start/stop real-time recording and transcription.

Choose audio input device (microphones and loopback devices).

Select files to transcribe.

Choose output folder and output filename.

View transcription as it progresses.

Support Italian and English with automatic language detection.

Work completely offline (no internet access required at runtime).

Run on Windows 11 with no admin rights and no extra installations required when using the final .exe.

Log operations and errors to support debugging.

### 2.2 Non-Goals ###

No cloud services, no accounts, no external APIs.

No multi-user / collaboration features.

No advanced audio editing (only recording and saving).

No integrations with conferencing tools (Teams, Zoom, etc.) in this version.

## 3. Operating Context and Constraints ##

### 3.1 Environment ###

**OS**: Windows 11 (64-bit).

**Permissions**: Standard user, no admin rights.

**Hardware**:

*RAM*: 16 GB.

Standard audio devices (microphone, possible loopback device).

**Runtime**:

Final user runs a single .exe built with PyInstaller --onefile.

The .exe must not require the user to install Python or any other dependency.

### 3.2 Privacy and Offline Constraints ###

The application must run 100% locally:

No network calls during normal operation.

Speech-to-text engine must be offline, using local models.

No audio or text data is uploaded or sent to external services.

Logging must not store raw audio; logs can reference filenames and high-level events only.

## 4. High-Level Architecture ##

The codebase will be organized at minimum as:

*main.py*
Entry point of the application.

Initializes application, logging, and core components.

Initializes and launches GUI.

Connects GUI events to backend logic (audio and transcription).

*gui_audio.py*

Contains all GUI logic and components.

Implements all visual elements and user interactions described in Section 6.

Additional suggested modules (create as needed):

*audio_engine.py*

Handles audio device enumeration and selection.

Manages audio recording streams (microphone and loopback).

Saves audio to file.

*stt_engine.py*

Encapsulates speech-to-text logic.

Manages model loading, audio chunk processing, and language detection (Italian/English).

*config.py*

Central place for constants and configuration defaults.

*logging_config.py*

Logging initialization and configuration.

The application must be architected to:

Keep the GUI responsive (use threads or asynchronous patterns).

Allow long recordings (~1 hour) without freezing.

Process audio in chunks for near real-time transcription.

## 5. Functional Requirements ##

### 5.1 Modes of Operation ###

The application must support two modes, selectable in the GUI:

“Record and transcribe” mode

User chooses this mode via a button or toggle.

When the user presses “Start recording”, the app:

Starts capturing audio from the selected input device.

Begins transcribing audio in real time.

Updates the scrollable transcription area continuously.

When the user presses “Stop and save”, the app:

Stops recording.

Finalizes the transcription.

Saves:

Audio file (e.g. .wav).

Transcription text file (e.g. .txt).

“Transcribe recorded audio” mode

User chooses this mode via a button or toggle.

User adds an existing audio file via the GUI.

User can select output folder and filename.

On “Start”, the app:

Loads the file.

Transcribes it (batch mode, not necessarily real-time).

Updates the transcription text area as transcription progresses.

Saves the transcription text file when finished.

“Stop” (if present) should cancel the transcription.

### 5.2 Audio Input Management ###

**Requirements**:

The app must enumerate available audio input devices, including:

Microphones.

Loopback / system audio devices (if available).

**GUI must provide:**

A dropdown list or similar widget to choose the active audio input.

A visual indicator (e.g. simple level bar or numeric dB/volume indicator) that shows if the chosen input is receiving audio (so user can see “it’s working”).

The selected audio device must be used for recording in “Record and transcribe” mode.

### 5.3 File Selection and Output ###

**GUI must allow:**

Add audio track to transcribe (only in “Transcribe recorded audio” mode):

Button or field to browse and select an audio file from disk.

Basic validation (supported format, file exists, readable).

*Select output folder:*

Folder selection dialog.

Store last used folder for convenience (if reasonable).

*Select output filename:*

A text input where the user can specify a base filename (without extension).

The application will generate two files:

filename.ext_audio (e.g. filename.wav).

filename.ext_text (e.g. filename.txt).

*If filename already exists, handle overwrite:*

Either prompt the user or automatically append a suffix (e.g. _1, _2).

### 5.4 Start / Stop Controls ###

*GUI must provide:
*
“Start recording” button:

Only active in “Record and transcribe” mode.

*On click:*

Validates that an audio input is selected.

Validates output folder and filename have been set.

Updates status bar to Recording.

Starts audio capture and real-time transcription.

*“Stop and save” button:*

In “Record and transcribe” mode:

Stops recording and transcription.

Finalizes text output.

Saves audio file and transcription file.

Updates status bar back to Idle when done.

In “Transcribe recorded audio” mode (if used as stop/cancel):

Stops transcription process if still running.

Writes partial transcription if possible.

Returns to Idle.

Buttons must be mutually consistent with the current state:

Disable “Start” when recording/transcribing is already running.

Enable “Stop” only when recording/transcribing is running.

### 5.5 Real-Time Transcription Area ###

**GUI must include:**

*A scrollable text area that:*

Displays transcription in progress in real time.

Appends text as new chunks are recognized.

Allows the user to scroll through the full transcript.

When a new session is started, the text area should be cleared (or user should have the option to clear).

*Optional but recommended behaviour:*

Add timestamps and/or paragraph breaks when there is a pause in speech.

Handle both Italian and English, with correct language recognition.

### 5.6 Status Bar ###

GUI must include a status bar showing clearly one of the following states:

Idle

Recording

Transcribing

The status bar must be updated by the backend logic whenever the state changes (e.g., start/stop recording, start/finish transcription, errors).

## 6. GUI Requirements (gui_audio.py) ##

gui_audio.py must implement a user-friendly interface that includes at least:

Mode selection control

Button, toggle, or radio buttons to select:

“Record and transcribe”

“Transcribe recorded audio”

Audio input selection

Dropdown list of available audio input devices (microphones, loopback).

Button or automatic refresh to update the list.

Simple audio activity indicator for the selected device.

Add audio track to transcribe

File selection button (only enabled in “Transcribe recorded audio” mode).

Text field showing the selected file path.

Output folder selection

Folder selection dialog.

Text field showing the chosen folder.

Output filename selection

Text input for base filename.

UI hint that two outputs will be generated: audio track (where applicable) and transcription text.

Control buttons

“Start recording” (primary control in “Record and transcribe” mode).

“Stop and save” (stop/cancel and save results).

Scrollable transcription area

Multi-line text widget with vertical scrollbar.

Real-time appending of recognized text.

Status bar

A dedicated area at the bottom or top of the window.

Displays Idle, Recording, or Transcribing.

The GUI toolkit can be PyQt, Tkinter, or similar, but it must be compatible with PyInstaller and Windows 11.

## 7. Speech-to-Text Requirements (stt_engine.py) ##

Must support Italian and English.

Must implement automatic language detection between these languages.

Must work offline with local models.

For real-time mode:

Process audio in small chunks (e.g. a few seconds).

Update the GUI text area as each chunk is processed.

For recorded files:

Process the entire file, updating the text area periodically to show progress.

Performance constraints:

Must be able to handle ~1-hour recordings on a 16 GB Windows 11 machine without crashing.

Memory usage must remain within reasonable limits (no unbounded growth).

## 8. Audio Engine Requirements (audio_engine.py) ##

Enumerate available audio input devices, including possible loopback devices.

Provide functions to:

Start recording from a given device.

Stop recording.

Stream audio data to the STT engine in real-time mode.

Save recorded audio to a file (e.g. .wav with reasonable parameters such as 16 kHz, mono).

Handle errors:

Device unavailable.

Device disconnected.

Sample rate not supported (fallback or adapt if needed).

## 9. Non-Functional Requirements ##

### 9.1 Performance ###

Startup time: Under a few seconds on a typical Windows 11 machine.

Responsiveness: GUI must remain responsive:

No blocking on long operations.

Use worker threads or asynchronous mechanisms for recording and transcription.

Real-time transcription latency:

Target: visible text updates within a few seconds (or less) of speaking.

### 9.2 Reliability ###

Must handle:

Sudden stop requests.

Errors from audio devices.

STT model errors during inference.

On errors, app should:

Show a user-friendly error message.

Log details to the log file.

Try to fail gracefully without crashing.

### 9.3 Packaging and Deployment ###

Must be compatible with PyInstaller using --onefile:

No reliance on dynamic imports that PyInstaller cannot detect (or provide necessary hooks).

All necessary models, DLLs, and resources must be bundled in the executable or in a simple structure created by PyInstaller.

No extra installations for end user:

End user should only need to run the .exe.

No Python installation required.

No additional system-wide libraries that require admin.

## 10. Logging and Debugging Requirements ##

Implement a logging system (e.g. Python logging module).

Log levels: at least INFO, WARNING, ERROR, and optionally DEBUG.

Log file behavior:

Write logs to a file on disk (e.g. next to the executable or in a known folder).

Use a rotating log handler to avoid large files, if possible.

Content to log:

App startup and shutdown.

Selected mode, input device, and output paths.

Start/stop recording, start/finish transcription.

Errors and exceptions (with traceback).

Do not log raw audio data or the full transcription text (for privacy).
Ok to log that a transcription was completed and the output filename.

## 11. Error Handling and User Feedback ##

All critical operations must provide clear feedback to the user:

Dialogs or status messages when:

Output folder is not writable.

Output filename is invalid.

Audio device cannot be opened.

Selected file cannot be read.

Status bar updates and messages for:

Starting/Stopping recording.

Starting/Finishing transcription.

On irrecoverable errors:
Show an error dialog.
Write full trace to log.
Return app to a safe state (e.g. Idle).

## 12. Future Extensions (Out of Scope for Now) ##

These are not required now, but the architecture should not make them impossible:

Support for more languages.

Simple export to formats like .docx or .srt.

Basic speaker diarization (multiple speakers). *[will be implemented into release 2.0]*

Simple noise suppression. *[will be implemented into release 2.0]*
