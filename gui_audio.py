"""Tkinter based GUI for the Offline Voice to Text prototype."""

from __future__ import annotations

import logging
import os
import queue
import threading
from typing import Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


LOGGER = logging.getLogger(__name__)


class AudioTranscriptionGUI:
    """Main application window coordinating all UI interactions."""

    def __init__(self, stt_engine, audio_engine, config):
        self.stt_engine = stt_engine
        self.audio_engine = audio_engine
        self.config = config

        self.root = tk.Tk()
        self.root.title("Offline Voice To Text")
        self.root.geometry("900x640")

        # State variables -------------------------------------------------
        self.mode_var = tk.StringVar(value="record")
        self.device_var = tk.StringVar()
        self.audio_file_var = tk.StringVar()
        self.output_folder_var = tk.StringVar()
        self.filename_var = tk.StringVar(value="meeting_notes")
        self.status_var = tk.StringVar(value="Idle")

        self.available_devices: list[dict] = []
        self.is_recording = False
        self.is_file_transcribing = False
        self._transcript_segments: list[str] = []
        self._realtime_queue: queue.Queue[bytes] | None = None
        self._realtime_thread: threading.Thread | None = None
        self._realtime_stop_event: threading.Event | None = None
        self._file_thread: threading.Thread | None = None
        self._file_cancel_event: threading.Event | None = None
        self._current_output_paths: tuple[Optional[str], str] | None = None

        self.build_ui()
        self.refresh_audio_devices()
        self._schedule_audio_meter_update()

    # ------------------------------------------------------------------
    # UI creation
    # ------------------------------------------------------------------
    def build_ui(self):
        """Create and place all widgets."""

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(6, weight=1)

        mode_frame = ttk.LabelFrame(self.root, text="Mode")
        mode_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        for idx, (value, label) in enumerate(
            [("record", "Record and transcribe"), ("file", "Transcribe recorded audio")]
        ):
            rb = ttk.Radiobutton(
                mode_frame,
                text=label,
                value=value,
                variable=self.mode_var,
                command=lambda v=value: self.on_select_mode(v),
            )
            rb.grid(row=0, column=idx, padx=5, pady=5, sticky="w")

        device_frame = ttk.LabelFrame(self.root, text="Audio input")
        device_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        device_frame.columnconfigure(1, weight=1)

        ttk.Label(device_frame, text="Device:").grid(row=0, column=0, padx=5, pady=5)
        self.device_combo = ttk.Combobox(device_frame, textvariable=self.device_var, state="readonly")
        self.device_combo.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        ttk.Button(device_frame, text="Refresh", command=self.refresh_audio_devices).grid(
            row=0, column=2, padx=5, pady=5
        )

        ttk.Label(device_frame, text="Input activity:").grid(row=1, column=0, padx=5, pady=5)
        self.level_meter = ttk.Progressbar(device_frame, orient="horizontal", length=200, mode="determinate")
        self.level_meter.grid(row=1, column=1, columnspan=2, padx=5, pady=5, sticky="ew")

        file_frame = ttk.LabelFrame(self.root, text="Audio file (batch mode)")
        file_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        file_frame.columnconfigure(1, weight=1)
        ttk.Label(file_frame, text="File:").grid(row=0, column=0, padx=5, pady=5)
        self.file_entry = ttk.Entry(file_frame, textvariable=self.audio_file_var)
        self.file_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.file_button = ttk.Button(file_frame, text="Browse", command=self.on_select_audio_file)
        self.file_button.grid(row=0, column=2, padx=5, pady=5)

        output_frame = ttk.LabelFrame(self.root, text="Output settings")
        output_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=5)
        output_frame.columnconfigure(1, weight=1)
        ttk.Label(output_frame, text="Folder:").grid(row=0, column=0, padx=5, pady=5)
        self.output_entry = ttk.Entry(output_frame, textvariable=self.output_folder_var)
        self.output_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        ttk.Button(output_frame, text="Select", command=self.on_select_output_folder).grid(
            row=0, column=2, padx=5, pady=5
        )

        ttk.Label(output_frame, text="Filename (no extension):").grid(row=1, column=0, padx=5, pady=5)
        self.filename_entry = ttk.Entry(output_frame, textvariable=self.filename_var)
        self.filename_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        ttk.Label(output_frame, text="Creates .wav (record mode) and .txt outputs").grid(
            row=2, column=0, columnspan=3, padx=5, pady=5, sticky="w"
        )

        control_frame = ttk.Frame(self.root)
        control_frame.grid(row=4, column=0, sticky="ew", padx=10, pady=5)
        control_frame.columnconfigure((0, 1), weight=1)
        self.start_button = ttk.Button(control_frame, text="Start recording", command=self.on_start_recording)
        self.start_button.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.stop_button = ttk.Button(control_frame, text="Stop and save", command=self.on_stop_and_save, state="disabled")
        self.stop_button.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        transcript_frame = ttk.LabelFrame(self.root, text="Transcription")
        transcript_frame.grid(row=5, column=0, sticky="nsew", padx=10, pady=5)
        transcript_frame.rowconfigure(0, weight=1)
        transcript_frame.columnconfigure(0, weight=1)
        self.transcript_text = tk.Text(transcript_frame, wrap="word", height=15)
        self.transcript_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(transcript_frame, orient="vertical", command=self.transcript_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.transcript_text["yscrollcommand"] = scrollbar.set

        status_frame = ttk.Frame(self.root)
        status_frame.grid(row=6, column=0, sticky="ew", padx=10, pady=(0, 10))
        ttk.Label(status_frame, text="Status:").pack(side=tk.LEFT)
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var)
        self.status_label.pack(side=tk.LEFT, padx=5)

        self.on_select_mode(self.mode_var.get())

    # ------------------------------------------------------------------
    # UI event handlers
    # ------------------------------------------------------------------
    def refresh_audio_devices(self):
        devices = self.audio_engine.list_input_devices()
        self.available_devices = devices
        self.device_combo["values"] = [d["name"] for d in devices]
        if devices and not self.device_var.get():
            self.device_combo.current(0)
            self.device_var.set(devices[0]["name"])

    def on_select_mode(self, mode: str):
        LOGGER.info("Switched mode to %s", mode)
        is_file_mode = mode == "file"
        state = "normal" if is_file_mode else "disabled"
        self.file_entry.configure(state=state)
        self.file_button.configure(state=state)
        self.start_button.configure(text="Start" if is_file_mode else "Start recording")

    def on_select_audio_file(self):
        path = filedialog.askopenfilename(
            title="Select audio file",
            filetypes=[("Audio files", "*.wav *.mp3 *.flac"), ("All files", "*.*")],
        )
        if path:
            self.audio_file_var.set(path)

    def on_select_output_folder(self):
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self.output_folder_var.set(folder)

    def on_start_recording(self):
        mode = self.mode_var.get()
        if mode == "record":
            self._start_realtime_session()
        else:
            self._start_file_transcription()

    def on_stop_and_save(self):
        if self.is_recording:
            self._stop_realtime_session()
        elif self.is_file_transcribing:
            self._stop_file_transcription()

    # ------------------------------------------------------------------
    # Recording mode
    # ------------------------------------------------------------------
    def _start_realtime_session(self):
        if self.is_recording:
            return
        try:
            device_id = self._get_selected_device_id()
        except ValueError as err:
            messagebox.showerror("Audio device", str(err))
            return

        if not self._validate_common_settings():
            return

        self._current_output_paths = self._prepare_output_paths(include_audio=True)
        self._clear_transcription_area()
        self._transcript_segments = []

        self._realtime_queue = queue.Queue()
        self._realtime_stop_event = threading.Event()
        self._realtime_thread = threading.Thread(target=self._process_realtime_chunks, daemon=True)
        self._realtime_thread.start()

        self.is_recording = True
        self._set_controls_running(True)
        self.update_status("Recording")

        try:
            self.audio_engine.start_recording(device_id, self._handle_audio_chunk)
        except Exception as exc:  # pragma: no cover - depends on environment
            messagebox.showerror("Recording", f"Unable to start recording: {exc}")
            LOGGER.exception("Failed to start recording")
            self.is_recording = False
            self._set_controls_running(False)
            return

        LOGGER.info("Recording started on device %s", device_id)

    def _handle_audio_chunk(self, chunk: bytes):
        if self._realtime_queue is not None:
            self._realtime_queue.put(chunk)

    def _process_realtime_chunks(self):
        assert self._realtime_queue is not None and self._realtime_stop_event is not None
        while not self._realtime_stop_event.is_set() or not self._realtime_queue.empty():
            try:
                chunk = self._realtime_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            text = self.stt_engine.transcribe_chunk(chunk)
            self._transcript_segments.append(text)
            self.root.after(0, lambda t=text: self.update_transcription_text(t))

    def _stop_realtime_session(self):
        if not self.is_recording:
            return

        self.update_status("Transcribing")
        if self._realtime_stop_event:
            self._realtime_stop_event.set()
        self.audio_engine.stop_recording()
        if self._realtime_thread:
            self._realtime_thread.join(timeout=2)

        audio_path, text_path = self._current_output_paths or (None, "")
        if audio_path:
            self.audio_engine.save_audio(audio_path)
        self._save_transcript(text_path)

        self.is_recording = False
        self._set_controls_running(False)
        self.update_status("Idle")
        LOGGER.info("Recording session finished")

    # ------------------------------------------------------------------
    # File transcription mode
    # ------------------------------------------------------------------
    def _start_file_transcription(self):
        if self.is_file_transcribing:
            return

        audio_file = self.audio_file_var.get().strip()
        if not audio_file:
            messagebox.showwarning("Audio file", "Please select an audio file to transcribe.")
            return
        if not os.path.isfile(audio_file):
            messagebox.showerror("Audio file", "Selected file does not exist or is not accessible.")
            return
        if not self._validate_common_settings():
            return

        self._current_output_paths = self._prepare_output_paths(include_audio=False)
        self._clear_transcription_area()
        self._transcript_segments = []

        self.is_file_transcribing = True
        self._set_controls_running(True)
        self.update_status("Transcribing")

        self._file_cancel_event = threading.Event()
        self._file_thread = threading.Thread(
            target=self._run_file_transcription,
            args=(audio_file, self._current_output_paths[1]),
            daemon=True,
        )
        self._file_thread.start()

    def _run_file_transcription(self, audio_file: str, text_path: str):
        def progress_callback(chunk_text: str) -> bool:
            self._transcript_segments.append(chunk_text)
            self.root.after(0, lambda t=chunk_text: self.update_transcription_text(t))
            if self._file_cancel_event and self._file_cancel_event.is_set():
                return False
            return True

        try:
            final_text = self.stt_engine.transcribe_file(audio_file, callback_progress=progress_callback)
        except Exception as exc:  # pragma: no cover - I/O heavy
            LOGGER.exception("Transcription failed")
            self.root.after(0, lambda: messagebox.showerror("Transcription", str(exc)))
            final_text = ""

        if final_text:
            self._save_transcript(text_path)

        self.is_file_transcribing = False
        self._set_controls_running(False)
        self.update_status("Idle")

    def _stop_file_transcription(self):
        if not self.is_file_transcribing:
            return
        if self._file_cancel_event:
            self._file_cancel_event.set()
        if self._file_thread:
            self._file_thread.join(timeout=2)
        self.is_file_transcribing = False
        self._set_controls_running(False)
        self.update_status("Idle")
        LOGGER.info("Batch transcription cancelled")

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------
    def _validate_common_settings(self) -> bool:
        folder = self.output_folder_var.get().strip()
        filename = self.filename_var.get().strip()
        if not folder:
            messagebox.showwarning("Output", "Please select an output folder.")
            return False
        if not filename:
            messagebox.showwarning("Output", "Please set a base filename.")
            return False
        if not os.path.isdir(folder):
            try:
                os.makedirs(folder, exist_ok=True)
            except OSError as exc:
                messagebox.showerror("Output", f"Cannot create folder: {exc}")
                return False
        return True

    def _prepare_output_paths(self, include_audio: bool) -> tuple[Optional[str], str]:
        folder = self.output_folder_var.get().strip()
        filename = self.filename_var.get().strip()
        base = os.path.join(folder, filename)
        suffix = ""
        counter = 1
        while True:
            candidate_audio = f"{base}{suffix}.wav" if include_audio else None
            candidate_text = f"{base}{suffix}.txt"
            conflict = os.path.exists(candidate_text)
            if candidate_audio:
                conflict = conflict or os.path.exists(candidate_audio)
            if not conflict:
                return candidate_audio, candidate_text
            suffix = f"_{counter}"
            counter += 1

    def _save_transcript(self, text_path: str):
        os.makedirs(os.path.dirname(text_path), exist_ok=True)
        with open(text_path, "w", encoding="utf-8") as f:
            f.write("\n".join(self._transcript_segments))
        LOGGER.info("Transcription saved to %s", text_path)

    def _clear_transcription_area(self):
        self.transcript_text.configure(state="normal")
        self.transcript_text.delete("1.0", tk.END)
        self.transcript_text.configure(state="normal")

    def _set_controls_running(self, running: bool):
        self.start_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")

    def _get_selected_device_id(self) -> int:
        selected_name = self.device_var.get()
        if not selected_name:
            raise ValueError("Please select an audio input device.")
        for device in self.available_devices:
            if device["name"] == selected_name:
                return device["id"]
        raise ValueError("Selected audio device is not available.")

    # ------------------------------------------------------------------
    # Live UI updates
    # ------------------------------------------------------------------
    def update_transcription_text(self, text: str):
        self.transcript_text.configure(state="normal")
        if self.transcript_text.index("end-1c") != "1.0":
            self.transcript_text.insert(tk.END, "\n")
        self.transcript_text.insert(tk.END, text)
        self.transcript_text.see(tk.END)
        self.transcript_text.configure(state="normal")

    def update_status(self, status: str):
        self.status_var.set(status)

    def update_audio_level_meter(self, value: float):
        self.level_meter["value"] = value * 100

    def _schedule_audio_meter_update(self):
        level = self.audio_engine.get_audio_level()
        self.update_audio_level_meter(level)
        self.root.after(300, self._schedule_audio_meter_update)

    def run(self):
        self.root.mainloop()

