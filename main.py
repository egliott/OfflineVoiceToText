# main.py - Sistema di Registrazione e Trascrizione Real-time
# Compatibile con PyInstaller per distribuzione standalone
# VERSIONE CORRETTA: Risolve warning pkg_resources deprecato

import sys
import queue
import threading
import time
import wave
import logging
import shutil
import re
from datetime import datetime
from pathlib import Path
import numpy as np

# Suppress pkg_resources deprecation warning da ctranslate2
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pkg_resources")
warnings.filterwarnings("ignore", message=".*pkg_resources.*")

# Audio libraries
import pyaudio

# Import faster-whisper DOPO aver soppresso i warnings
from faster_whisper import WhisperModel

# ============================================================================
# CONFIGURAZIONE LOGGING
# ============================================================================
def setup_logging():
    """Configura logging su file per debugging"""
    log_dir = Path.home() / "AudioTranscriber_Logs"
    log_dir.mkdir(exist_ok=True)
    
    log_file = log_dir / f"transcriber_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ============================================================================
# CONFIGURAZIONE AUDIO
# ============================================================================
CHUNK_SIZE = 1024  # Frame per buffer
FORMAT = pyaudio.paInt16  # 16-bit audio
CHANNELS = 1  # Mono
RATE = 16000  # Sample rate (ottimale per Whisper)
BUFFER_SECONDS = 30  # Secondi di audio per chunk di trascrizione
VAD_THRESHOLD = 500  # Threshold per Voice Activity Detection (RMS)

# ============================================================================
# GESTIONE PATH MODELLO WHISPER (compatibile con PyInstaller)
# ============================================================================
def get_model_path():
    """
    Determina il path corretto per i modelli Whisper.
    Supporta sia esecuzione normale che da .exe
    """
    if getattr(sys, 'frozen', False):
        # Running in PyInstaller bundle
        base_path = Path(sys._MEIPASS)
    else:
        # Running in normal Python environment
        base_path = Path.home() / ".cache" / "huggingface" / "hub"
    
    return base_path

# ============================================================================
# CLASSE PRINCIPALE: AudioTranscriber
# ============================================================================
class AudioTranscriber:
    def __init__(self, output_dir=None, device_index=None):
        """
        Inizializza il sistema di trascrizione
        
        Args:
            output_dir: Directory per salvataggio file (default: Desktop/Trascrizioni)
            device_index: Indice dispositivo audio (None = default)
        """
        self.output_dir = output_dir or (Path.home() / "Desktop" / "Trascrizioni")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.device_index = device_index
        self.is_recording = False
        self.is_transcribing = False
        
        # Queue thread-safe per passare audio da registrazione a trascrizione
        self.audio_queue = queue.Queue(maxsize=10)
        
        # Thread
        self.record_thread = None
        self.transcribe_thread = None
        
        # PyAudio
        self.pyaudio_instance = None
        self.stream = None
        
        # File output
        self.transcript_file = None
        self.wav_file = None
        self.wav_writer = None
        
        # Modello Whisper (caricato lazy)
        self.model = None

        # Callback per aggiornare la GUI in tempo reale
        self.transcript_callback = None

        # Statistiche
        self.total_chunks_processed = 0
        self.start_time = None

        # Percorsi correnti/ultimi file generati
        self.current_transcript_path = None
        self.current_audio_path = None
        self.last_transcript_path = None
        self.last_audio_path = None
        
        logger.info(f"AudioTranscriber inizializzato. Output: {self.output_dir}")
    
    # ========================================================================
    # GESTIONE DISPOSITIVI AUDIO
    # ========================================================================
    def get_audio_devices(self):
        """
        Restituisce lista dispositivi audio disponibili
        
        Returns:
            list: [(index, name, channels), ...]
        """
        devices = []
        try:
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                try:
                    info = p.get_device_info_by_index(i)
                    # Solo dispositivi con input
                    if info['maxInputChannels'] > 0:
                        devices.append({
                            'index': i,
                            'name': info['name'],
                            'channels': info['maxInputChannels'],
                            'sample_rate': int(info['defaultSampleRate'])
                        })
                except Exception as e:
                    logger.warning(f"Errore lettura device {i}: {e}")
            p.terminate()
            
            logger.info(f"Trovati {len(devices)} dispositivi audio input")
            return devices
        
        except Exception as e:
            logger.error(f"Errore enumerazione dispositivi: {e}")
            return []
    
    # ========================================================================
    # CARICAMENTO MODELLO WHISPER
    # ========================================================================
    def load_model(self):
        """Carica il modello Whisper (lazy loading)"""
        if self.model is not None:
            return True
        
        try:
            logger.info("Caricamento modello Whisper 'turbo'...")
            
            # Sopprimi warnings durante il caricamento
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                
                # Usa CPU con supporto INT8 per efficienza senza GPU
                self.model = WhisperModel(
                    "turbo",
                    device="cpu",
                    compute_type="int8",
                    download_root=str(get_model_path())
                )
            
            logger.info("✓ Modello Whisper caricato con successo")
            return True
        
        except Exception as e:
            logger.error(f"✗ Errore caricamento modello: {e}")
            return False

    # ========================================================================
    # CALLBACK TRASCRIZIONE
    # ========================================================================
    def set_transcript_callback(self, callback):
        """Registra callback per ricevere testo trascritto in tempo reale"""
        self.transcript_callback = callback

    def _emit_transcript(self, text):
        if self.transcript_callback and text:
            try:
                self.transcript_callback(text)
            except Exception as callback_error:
                logger.error(f"Errore callback trascrizione: {callback_error}")

    # ========================================================================
    # UTILS PATH
    # ========================================================================
    def _sanitize_base_name(self, base_name):
        if not base_name:
            return ""
        sanitized = re.sub(r"[^A-Za-z0-9_\-]", "_", base_name.strip())
        return sanitized[:80]

    def _prepare_output_paths(self, base_dir=None, base_name=None,
                              include_audio=True, audio_extension=".wav"):
        base_dir = Path(base_dir or self.output_dir)
        base_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_base = self._sanitize_base_name(base_name) or f"session_{timestamp}"

        counter = 1
        candidate = safe_base
        while True:
            transcript_path = base_dir / f"{candidate}_transcription.txt"
            audio_path = None
            if include_audio:
                audio_path = base_dir / f"{candidate}_audio{audio_extension}"
            if transcript_path.exists() or (audio_path and audio_path.exists()):
                candidate = f"{safe_base}_{counter}"
                counter += 1
                continue
            break

        return transcript_path, audio_path, candidate

    # ========================================================================
    # VOICE ACTIVITY DETECTION (semplice)
    # ========================================================================
    def has_voice_activity(self, audio_data):
        """
        Rileva se c'è attività vocale nel chunk audio
        
        Args:
            audio_data: numpy array con dati audio
            
        Returns:
            bool: True se rilevata voce
        """
        # Calcola RMS (Root Mean Square) come indicatore di energia
        rms = np.sqrt(np.mean(audio_data**2))
        return rms > VAD_THRESHOLD
    
    # ========================================================================
    # THREAD REGISTRAZIONE AUDIO
    # ========================================================================
    def _recording_thread(self):
        """Thread per registrazione continua audio"""
        logger.info("Thread registrazione avviato")
        
        frames_buffer = []
        frames_in_buffer = 0
        max_frames = int(RATE / CHUNK_SIZE * BUFFER_SECONDS)
        
        try:
            while self.is_recording:
                try:
                    # Leggi chunk audio
                    data = self.stream.read(CHUNK_SIZE, exception_on_overflow=False)
                    
                    # Salva su file WAV
                    if self.wav_writer:
                        self.wav_writer.writeframes(data)
                    
                    # Accumula nel buffer
                    frames_buffer.append(data)
                    frames_in_buffer += 1
                    
                    # Quando buffer pieno, invia a trascrizione
                    if frames_in_buffer >= max_frames:
                        # Converti in numpy array
                        audio_data = np.frombuffer(b''.join(frames_buffer), dtype=np.int16)
                        
                        # VAD: solo se c'è voce
                        if self.has_voice_activity(audio_data):
                            try:
                                # Converti a float32 normalizzato (richiesto da Whisper)
                                audio_float = audio_data.astype(np.float32) / 32768.0
                                
                                # Invia a queue (non-blocking con timeout)
                                self.audio_queue.put(audio_float, timeout=1)
                                logger.debug(f"Chunk audio inviato a trascrizione ({len(audio_float)} samples)")
                            
                            except queue.Full:
                                logger.warning("Queue piena, chunk audio scartato")
                        else:
                            logger.debug("Silenzio rilevato, chunk ignorato")
                        
                        # Reset buffer
                        frames_buffer = []
                        frames_in_buffer = 0
                
                except Exception as e:
                    logger.error(f"Errore durante registrazione: {e}")
                    time.sleep(0.1)
        
        except Exception as e:
            logger.error(f"Errore fatale nel thread registrazione: {e}")
        
        finally:
            logger.info("Thread registrazione terminato")
    
    # ========================================================================
    # THREAD TRASCRIZIONE
    # ========================================================================
    def _transcription_thread(self):
        """Thread per trascrizione continua"""
        logger.info("Thread trascrizione avviato")
        
        try:
            while self.is_transcribing:
                try:
                    # Preleva audio dalla queue (timeout per permettere shutdown)
                    audio_data = self.audio_queue.get(timeout=1)
                    
                    logger.info(f"Trascrizione chunk {self.total_chunks_processed + 1}...")
                    start_time = time.time()
                    
                    # Sopprimi warnings durante trascrizione
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        
                        # TRASCRIZIONE con Whisper
                        segments, info = self.model.transcribe(
                            audio_data,
                            language=None,  # Auto-detect italiano/inglese
                            beam_size=5,
                            vad_filter=True,  # VAD integrato di faster-whisper
                            vad_parameters=dict(
                                threshold=0.5,
                                min_speech_duration_ms=250
                            )
                        )
                    
                    # Processa segmenti trascritti
                    transcription_text = ""
                    for segment in segments:
                        text = segment.text.strip()
                        if text:
                            # Timestamp relativo dall'inizio registrazione
                            elapsed = time.time() - self.start_time
                            timestamp = time.strftime('%H:%M:%S', time.gmtime(elapsed))
                            
                            # Formato: [HH:MM:SS] Testo
                            line = f"[{timestamp}] {text}\n"
                            transcription_text += line

                            # Salva immediatamente su file
                            if self.transcript_file:
                                self.transcript_file.write(line)
                                self.transcript_file.flush()

                            # Aggiorna eventuale callback
                            self._emit_transcript(line)

                            logger.info(f"  Lingua: {info.language} | Testo: {text[:50]}...")
                    
                    elapsed_time = time.time() - start_time
                    self.total_chunks_processed += 1
                    
                    logger.info(f"✓ Chunk trascritto in {elapsed_time:.2f}s")
                    
                except queue.Empty:
                    # Timeout normale, continua loop
                    continue
                
                except Exception as e:
                    logger.error(f"Errore durante trascrizione: {e}")
                    time.sleep(1)
        
        except Exception as e:
            logger.error(f"Errore fatale nel thread trascrizione: {e}")
        
        finally:
            logger.info("Thread trascrizione terminato")
    
    # ========================================================================
    # API PUBBLICA
    # ========================================================================
    def start_recording(self, device_index=None, file_basename=None):
        """
        Avvia registrazione e trascrizione
        
        Args:
            device_index: Indice dispositivo audio (None = default)
            
        Returns:
            bool: True se avviato con successo
        """
        if self.is_recording:
            logger.warning("Registrazione già in corso")
            return False
        
        try:
            # Carica modello se necessario
            if not self.load_model():
                return False
            
            # File output
            transcript_path, wav_path, _ = self._prepare_output_paths(
                base_dir=self.output_dir,
                base_name=file_basename,
                include_audio=True,
                audio_extension=".wav"
            )

            # File trascrizione
            self.transcript_file = open(transcript_path, 'w', encoding='utf-8')
            self.transcript_file.write(f"=== TRASCRIZIONE AVVIATA: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
            self.transcript_file.flush()

            # File audio WAV
            self.wav_file = wave.open(str(wav_path), 'wb')
            self.wav_file.setnchannels(CHANNELS)
            self.wav_file.setsampwidth(2)  # 16-bit = 2 bytes
            self.wav_file.setframerate(RATE)
            self.wav_writer = self.wav_file

            self.current_transcript_path = transcript_path
            self.current_audio_path = wav_path

            # Inizializza PyAudio
            self.pyaudio_instance = pyaudio.PyAudio()
            
            # Apri stream audio
            device_idx = device_index if device_index is not None else self.device_index
            
            self.stream = self.pyaudio_instance.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                input_device_index=device_idx,
                frames_per_buffer=CHUNK_SIZE
            )
            
            logger.info(f"Stream audio aperto su device {device_idx}")
            
            # Reset statistiche
            self.total_chunks_processed = 0
            self.start_time = time.time()
            
            # Avvia threads
            self.is_recording = True
            self.is_transcribing = True
            
            self.record_thread = threading.Thread(target=self._recording_thread, daemon=True)
            self.transcribe_thread = threading.Thread(target=self._transcription_thread, daemon=True)
            
            self.record_thread.start()
            self.transcribe_thread.start()
            
            logger.info(f"✓ Registrazione avviata con successo")
            logger.info(f"  Trascrizione: {transcript_path}")
            logger.info(f"  Audio: {wav_path}")

            return True
        
        except Exception as e:
            logger.error(f"✗ Errore avvio registrazione: {e}")
            self.stop_recording()
            return False
    
    def stop_recording(self):
        """
        Ferma registrazione e trascrizione salvando tutto
        
        Returns:
            bool: True se fermato con successo
        """
        if not self.is_recording:
            logger.warning("Nessuna registrazione in corso")
            return False
        
        try:
            logger.info("Fermo registrazione...")
            
            # Segnala stop ai threads
            self.is_recording = False
            self.is_transcribing = False
            
            # Attendi terminazione threads (max 5 secondi)
            if self.record_thread:
                self.record_thread.join(timeout=5)
            if self.transcribe_thread:
                self.transcribe_thread.join(timeout=5)
            
            # Chiudi stream audio
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
                self.stream = None
            
            if self.pyaudio_instance:
                self.pyaudio_instance.terminate()
                self.pyaudio_instance = None
            
            # Chiudi file WAV
            if self.wav_writer:
                self.wav_writer.close()
                self.wav_writer = None
                self.wav_file = None

            if self.current_audio_path:
                self.last_audio_path = self.current_audio_path
                self.current_audio_path = None

            # Chiudi file trascrizione
            if self.transcript_file:
                self.transcript_file.write(f"\n\n=== TRASCRIZIONE TERMINATA: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                self.transcript_file.write(f"Chunk processati: {self.total_chunks_processed}\n")
                self.transcript_file.close()
                self.transcript_file = None

            if self.current_transcript_path:
                self.last_transcript_path = self.current_transcript_path
                self.current_transcript_path = None
            
            # Svuota queue
            while not self.audio_queue.empty():
                try:
                    self.audio_queue.get_nowait()
                except queue.Empty:
                    break
            
            logger.info(f"✓ Registrazione fermata. Totale chunk: {self.total_chunks_processed}")
            return True
        
        except Exception as e:
            logger.error(f"✗ Errore durante stop: {e}")
            return False
    
    def get_status(self):
        """
        Restituisce stato corrente
        
        Returns:
            dict: {'recording': bool, 'transcribing': bool, 'chunks': int}
        """
        return {
            'recording': self.is_recording,
            'transcribing': self.is_transcribing,
            'chunks_processed': self.total_chunks_processed,
            'queue_size': self.audio_queue.qsize()
        }

    def cleanup(self):
        """Pulizia risorse (chiamare prima di uscire)"""
        if self.is_recording:
            self.stop_recording()

        logger.info("Cleanup completato")

    # ========================================================================
    # TEST DISPOSITIVI AUDIO
    # ========================================================================
    def test_input_device(self, device_index=None, duration=2.0):
        """Misura livello medio del dispositivo audio selezionato"""
        p = pyaudio.PyAudio()
        try:
            idx = device_index if device_index is not None else self.device_index
            if idx is None:
                try:
                    idx = p.get_default_input_device_info().get('index')
                except Exception:
                    idx = None
            stream = p.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                input_device_index=idx,
                frames_per_buffer=CHUNK_SIZE
            )

            levels = []
            start = time.time()
            while time.time() - start < duration:
                data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.int16)
                rms = np.sqrt(np.mean(np.square(audio_data)))
                levels.append(rms)

            stream.stop_stream()
            stream.close()

            if not levels:
                return {'average': 0.0, 'peak': 0.0, 'active': False}

            avg = float(np.mean(levels))
            peak = float(np.max(levels))
            active = peak > VAD_THRESHOLD
            return {'average': avg, 'peak': peak, 'active': active}

        finally:
            p.terminate()

    # ========================================================================
    # TRASCRIZIONE FILE ESISTENTE
    # ========================================================================
    def transcribe_audio_file(self, audio_path, output_dir=None,
                              file_basename=None, language=None):
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"File audio non trovato: {audio_path}")

        if not self.load_model():
            raise RuntimeError("Impossibile caricare il modello Whisper")

        target_dir = Path(output_dir or self.output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        transcript_path, audio_copy_path, base_name = self._prepare_output_paths(
            base_dir=target_dir,
            base_name=file_basename or audio_path.stem,
            include_audio=True,
            audio_extension=audio_path.suffix or '.wav'
        )

        # Copia il file audio sorgente per avere coppia completa
        try:
            if audio_path.resolve() != audio_copy_path.resolve():
                shutil.copy2(audio_path, audio_copy_path)
        except Exception as copy_error:
            logger.warning(f"Impossibile copiare file audio: {copy_error}")

        with open(transcript_path, 'w', encoding='utf-8') as transcript_out:
            transcript_out.write(f"=== TRASCRIZIONE FILE: {audio_path.name} ===\n")
            transcript_out.flush()

            segments, info = self.model.transcribe(
                str(audio_path),
                language=language,
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(
                    threshold=0.5,
                    min_speech_duration_ms=250
                )
            )

            for segment in segments:
                text = segment.text.strip()
                if not text:
                    continue
                start_ts = time.strftime('%H:%M:%S', time.gmtime(segment.start))
                line = f"[{start_ts}] {text}\n"
                transcript_out.write(line)
                transcript_out.flush()
                self._emit_transcript(line)

        logger.info(f"Trascrizione completata: {transcript_path}")
        self.last_transcript_path = transcript_path
        self.last_audio_path = audio_copy_path
        return {
            'transcript_path': transcript_path,
            'audio_path': audio_copy_path,
            'base_name': base_name
        }

# ============================================================================
# TEST STANDALONE
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("TEST AUDIO TRANSCRIBER - Modalità Standalone")
    print("=" * 60)
    
    # Crea istanza
    transcriber = AudioTranscriber()
    
    # Mostra dispositivi disponibili
    print("\nDispositivi audio disponibili:")
    devices = transcriber.get_audio_devices()
    for dev in devices:
        print(f"  [{dev['index']}] {dev['name']} ({dev['channels']} canali, {dev['sample_rate']} Hz)")
    
    if not devices:
        print("\n✗ ERRORE: Nessun dispositivo audio trovato!")
        sys.exit(1)
    
    # Selezione dispositivo
    print(f"\nDispositivo default: {devices[0]['name']}")
    choice = input("Premi INVIO per usare default o inserisci numero dispositivo: ").strip()
    
    device_idx = None
    if choice.isdigit():
        device_idx = int(choice)
        if device_idx not in [d['index'] for d in devices]:
            print(f"✗ Dispositivo {device_idx} non valido, uso default")
            device_idx = None
    
    # Avvia registrazione
    print("\n" + "=" * 60)
    print("Avvio registrazione in 3 secondi...")
    print("Premi CTRL+C per fermare")
    print("=" * 60)
    time.sleep(3)
    
    if not transcriber.start_recording(device_index=device_idx):
        print("\n✗ ERRORE: Impossibile avviare registrazione!")
        sys.exit(1)
    
    try:
        # Loop stato
        while True:
            time.sleep(5)
            status = transcriber.get_status()
            print(f"\r[{datetime.now().strftime('%H:%M:%S')}] "
                  f"Recording: {status['recording']} | "
                  f"Chunks: {status['chunks_processed']} | "
                  f"Queue: {status['queue_size']}", end='')
    
    except KeyboardInterrupt:
        print("\n\nInterruzione richiesta...")
    
    finally:
        transcriber.stop_recording()
        transcriber.cleanup()
        print("\n✓ Test completato. Controlla la cartella output per i file generati.")
        print(f"   Output directory: {transcriber.output_dir}")
