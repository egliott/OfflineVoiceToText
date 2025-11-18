# whisperpy
# cd "C:\Users\E26051\OneDrive - E.ON\Desktop\Work\Test\Audio\Script Pyhon\claude"

import os
import sys
import queue
import threading
import time
import wave
import logging
from datetime import datetime
from pathlib import Path
import numpy as np

# Suppress warnings
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*pkg_resources.*")

# Audio libraries
import pyaudiowpatch
from faster_whisper import WhisperModel

# Import utility personalizzate
try:
    from audio_utils import get_enhanced_audio_devices, get_best_sample_rate
    ENHANCED_AUDIO = True
except ImportError:
    ENHANCED_AUDIO = False
    logging.warning("audio_utils non trovato, uso modalità base")

try:
    from loopback_capture import get_loopback_devices, LoopbackRecorder, LOOPBACK_AVAILABLE
except ImportError:
    LOOPBACK_AVAILABLE = False
    logging.warning("loopback_capture non trovato, loopback non disponibile")

# ============================================================================
# CONFIGURAZIONE LOGGING
# ============================================================================
def setup_logging():
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
# CONFIGURAZIONE AUDIO - MIGLIORATA
# ============================================================================
CHUNK_SIZE = 1024
FORMAT = pyaudiowpatch.paInt16
CHANNELS = 1
RATE = 16000  # Default, verrà adattato per dispositivo
BUFFER_SECONDS = 10  # ⚠️ RIDOTTO da 30 a 10 secondi per latenza migliore
VAD_THRESHOLD = 200  # ⚠️ RIDOTTO da 500 a 200 per sensibilità maggiore

# ============================================================================
# GESTIONE PATH MODELLO
# ============================================================================
def get_model_path():
    if getattr(sys, 'frozen', False):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path.home() / ".cache" / "huggingface" / "hub"
    return base_path

# ============================================================================
# CLASSE AudioTranscriber MIGLIORATA
# ============================================================================
class AudioTranscriber:
    def __init__(self, output_dir=None, device_index=None, use_loopback=False):
        """
        Args:
            output_dir: Directory output
            device_index: Indice dispositivo audio
            use_loopback: Se True, cattura anche audio loopback (Teams, etc.)
        """
        self.output_dir = output_dir or (Path.home() / "Desktop" / "Trascrizioni")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.device_index = device_index
        self.use_loopback = use_loopback and LOOPBACK_AVAILABLE
        self.sample_rate = RATE  # Verrà adattato
        
        self.is_recording = False
        self.is_transcribing = False
        
        self.audio_queue = queue.Queue(maxsize=10)
        
        self.record_thread = None
        self.transcribe_thread = None
        self.loopback_thread = None
        
        self.pyaudio_instance = None
        self.stream = None
        self.loopback_recorder = None
        
        self.transcript_file = None
        self.wav_file = None
        self.wav_writer = None
        
        self.model = None
        
        self.total_chunks_processed = 0
        self.start_time = None
        
        # ⚠️ NUOVO: per VU meter
        self.current_audio_level = 0.0  # Range 0-100
        self.level_lock = threading.Lock()
        
        logger.info(f"AudioTranscriber init. Output: {self.output_dir}, Loopback: {self.use_loopback}")
    
    # ========================================================================
    # DISPOSITIVI AUDIO - ENHANCED
    # ========================================================================
    def get_audio_devices(self):
        """Restituisce dispositivi con info dettagliate"""
        if ENHANCED_AUDIO:
            devices = get_enhanced_audio_devices()
            
            # Aggiungi loopback se disponibile
            if LOOPBACK_AVAILABLE:
                loopback_devs = get_loopback_devices()
                for ld in loopback_devs:
                    ld['is_loopback'] = True
                devices.extend(loopback_devs)
            
            return devices
        else:
            # Modalità base (codice originale)
            devices = []
            try:
                p = pyaudiowpatch.PyAudio()
                for i in range(p.get_device_count()):
                    try:
                        info = p.get_device_info_by_index(i)
                        if info['maxInputChannels'] > 0:
                            devices.append({
                                'index': i,
                                'name': info['name'],
                                'channels': info['maxInputChannels'],
                                'sample_rate': int(info['defaultSampleRate']),
                                'best_rate': int(info['defaultSampleRate'])
                            })
                    except Exception as e:
                        logger.warning(f"Errore device {i}: {e}")
                p.terminate()
                return devices
            except Exception as e:
                logger.error(f"Errore enumerazione: {e}")
                return []
    
    # ========================================================================
    # CARICAMENTO MODELLO
    # ========================================================================
    def load_model(self):
        if self.model is not None:
            return True
        
        try:
            logger.info("Caricamento Whisper 'turbo'...")
            
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                
                self.model = WhisperModel("turbo",device="cpu",compute_type="int8",download_root=str(get_model_path()))
            
            logger.info("✓ Modello caricato")
            return True
        
        except Exception as e:
            logger.error(f"✗ Errore modello: {e}")
            return False
    
    # ========================================================================
    # VAD MIGLIORATO
    # ========================================================================
    def has_voice_activity(self, audio_data):
        """VAD con threshold più basso per catturare più voce"""
        rms = np.sqrt(np.mean(audio_data**2))
        has_voice = rms > VAD_THRESHOLD
        
        if has_voice:
            logger.debug(f"VAD: Voce rilevata (RMS={rms:.2f})")
        
        return has_voice
    
    # ========================================================================
    # THREAD REGISTRAZIONE - MIGLIORATO
    # ========================================================================
    def _recording_thread(self):
        """Thread registrazione - SOGLIA VAD RIDOTTA"""
        logger.info("Thread registrazione avviato")
        
        frames_buffer = []
        frames_in_buffer = 0
        max_frames = int(self.sample_rate / CHUNK_SIZE * BUFFER_SECONDS)
        
        try:
            while self.is_recording:
                try:
                    data = self.stream.read(CHUNK_SIZE, exception_on_overflow=False)
                    
                    if self.wav_writer:
                        self.wav_writer.writeframes(data)
                    
                    frames_buffer.append(data)
                    frames_in_buffer += 1
                    
                    if frames_in_buffer >= max_frames:
                        audio_data = np.frombuffer(b''.join(frames_buffer), dtype=np.int16)
                        
                        # ⚠️ NUOVO: Aggiorna level
                        self._update_audio_level(audio_data)
                        
                        # ⚠️ VAD MOLTO PERMISSIVO
                        audio_max = np.max(np.abs(audio_data))
                        audio_rms = np.sqrt(np.mean(audio_data**2))
                        
                        # Passa se RMS > 50 O max > 100 (soglie BASSISSIME)
                        if audio_rms > 50 or audio_max > 100:
                            try:
                                audio_float = audio_data.astype(np.float32) / 32768.0
                                self.audio_queue.put(audio_float, timeout=1)
                                logger.debug(f"Mic chunk inviato: rms={audio_rms:.1f}, max={audio_max}")
                            except queue.Full:
                                logger.warning("Queue piena")
                        else:
                            logger.debug(f"Silenzio: rms={audio_rms:.1f}, max={audio_max}")
                        
                        frames_buffer = []
                        frames_in_buffer = 0
                
                except Exception as e:
                    logger.error(f"Errore registrazione: {e}")
                    time.sleep(0.1)
        
        except Exception as e:
            logger.error(f"Errore fatale registrazione: {e}")
        
        finally:
            logger.info("Thread registrazione terminato")
    
    # ========================================================================
    # THREAD LOOPBACK (NUOVO)
    # ========================================================================
    def _loopback_thread(self):
        """Thread per cattura audio loopback (Teams, etc.)"""
        if not self.use_loopback or not self.loopback_recorder:
            return
        
        logger.info("Thread loopback avviato")
        
        frames_buffer = []
        buffer_size = int(self.sample_rate * BUFFER_SECONDS)
        
        try:
            while self.is_recording:
                try:
                    audio_chunk = self.loopback_recorder.get_audio(timeout=1)
                    
                    if audio_chunk is not None:
                        # ⚠️ NUOVO: Aggiorna level
                        self._update_audio_level(audio_chunk)
                        
                        if len(frames_buffer) >= buffer_size:
                            audio_array = np.array(frames_buffer[:buffer_size], dtype=np.float32)
                            
                            if np.max(np.abs(audio_array)) > 0.01:  # Soglia loopback
                                try:
                                    self.audio_queue.put(audio_array, timeout=1)
                                    logger.debug("Loopback chunk inviato")
                                except queue.Full:
                                    logger.warning("Queue piena (loopback)")
                            
                            frames_buffer = frames_buffer[buffer_size:]
                
                except Exception as e:
                    logger.error(f"Errore loopback: {e}")
                    time.sleep(0.5)
        
        finally:
            logger.info("Thread loopback terminato")
    
    # ========================================================================
    # THREAD TRASCRIZIONE - MIGLIORATO
    # ========================================================================
    def _transcription_thread(self):
        """Thread trascrizione - OTTIMIZZATO per IT/EN"""
        logger.info("Thread trascrizione avviato")
        
        # ⚠️ Contesto per lingue miste
        previous_text = ""
        
        try:
            while self.is_transcribing:
                try:
                    audio_data = self.audio_queue.get(timeout=1)
                    
                    # Analisi preliminare
                    audio_max = np.max(np.abs(audio_data))
                    audio_rms = np.sqrt(np.mean(audio_data**2))
                    
                    logger.info(f"Chunk {self.total_chunks_processed + 1}: max={audio_max:.4f}, rms={audio_rms:.4f}")
                    
                    # ⚠️ SOGLIA MOLTO BASSA
                    if audio_max < 0.001:
                        logger.info("  → Silenzio assoluto, saltato")
                        continue
                    
                    logger.info(f"  → Trascrizione in corso...")
                    start_time = time.time()
                    
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        
                        # ⚠️ PARAMETRI OTTIMIZZATI PER IT/EN
                        segments, info = self.model.transcribe(
                            audio_data,
                            language=None,  # Auto-detect IT/EN
                            
                            # Qualità trascrizione
                            beam_size=5,
                            best_of=5,
                            temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],  # ⚠️ Temperature multiple
                            
                            # VAD ultra-permissivo
                            vad_filter=True,
                            vad_parameters=dict(
                                threshold=0.2,              # ⚠️ MOLTO BASSO (era 0.5)
                                min_speech_duration_ms=50,  # ⚠️ MOLTO BASSO (era 250)
                                min_silence_duration_ms=300,
                                speech_pad_ms=200           # Padding pre/post speech
                            ),
                            
                            # Contesto
                            initial_prompt=previous_text[-200:] if previous_text else None,  # ⚠️ Ultimi 200 char
                            condition_on_previous_text=True,
                            
                            # Performance
                            word_timestamps=False,
                            
                            # ⚠️ DISABILITA COMPRESSIONE RIPETIZIONI (causa problemi IT/EN)
                            compression_ratio_threshold=2.4,  # Default
                            # logprob_threshold=-1.0,           # Default
                            no_speech_threshold=0.3           # ⚠️ Ridotto (era 0.6)
                        )
                    
                    segment_count = 0
                    chunk_text = ""
                    
                    for segment in segments:
                        text = segment.text.strip()
                        
                        # ⚠️ Filtri aggiuntivi
                        if not text:
                            continue
                        
                        # Skip se troppo corto E bassa probabilità
                        if len(text) < 3 and segment.avg_logprob < -0.8:
                            logger.debug(f"  Scartato (corto+bassa prob): '{text}'")
                            continue
                        
                        segment_count += 1
                        elapsed = time.time() - self.start_time
                        timestamp = time.strftime('%H:%M:%S', time.gmtime(elapsed))
                        
                        # ⚠️ Aggiungi LINGUA rilevata
                        lang_label = info.language.upper()
                        line = f"[{timestamp}][{lang_label}] {text}\n"
                        
                        chunk_text += text + " "
                        
                        if self.transcript_file:
                            self.transcript_file.write(line)
                            self.transcript_file.flush()
                        
                        logger.info(f"  [{lang_label}] {text}")
                    
                    # Aggiorna contesto
                    if chunk_text.strip():
                        previous_text = (previous_text + " " + chunk_text)[-500:]  # Ultimi 500 char
                    
                    elapsed_time = time.time() - start_time
                    self.total_chunks_processed += 1
                    
                    if segment_count == 0:
                        logger.warning(f"  ⚠️ NESSUN SEGMENTO TRASCRITTO! (audio_max={audio_max:.4f})")
                    else:
                        logger.info(f"  ✓ {segment_count} segmenti in {elapsed_time:.2f}s")
                    
                except queue.Empty:
                    continue
                
                except Exception as e:
                    logger.error(f"Errore trascrizione: {e}")
                    import traceback
                    traceback.print_exc()
                    time.sleep(1)
        
        except Exception as e:
            logger.error(f"Errore fatale trascrizione: {e}")
        
        finally:
            logger.info("Thread trascrizione terminato")
            
    # ========================================================================
    # START RECORDING - MIGLIORATO
    # ========================================================================
    def start_recording(self, device_index=None):
        if self.is_recording:
            logger.warning("Già in registrazione")
            return False
        
        try:
            if not self.load_model():
                return False
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # File trascrizione
            transcript_path = self.output_dir / f"trascrizione_{timestamp}.txt"
            self.transcript_file = open(transcript_path, 'w', encoding='utf-8')
            self.transcript_file.write(f"=== TRASCRIZIONE AVVIATA: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
            self.transcript_file.flush()
            
            # Determina sample rate ottimale per dispositivo
            if ENHANCED_AUDIO and device_index is not None:
                optimal_rate = get_best_sample_rate(device_index)
                self.sample_rate = optimal_rate
                logger.info(f"Sample rate ottimale: {optimal_rate} Hz")
            else:
                self.sample_rate = RATE
            
            # File WAV
            wav_path = self.output_dir / f"audio_{timestamp}.wav"
            self.wav_file = wave.open(str(wav_path), 'wb')
            self.wav_file.setnchannels(CHANNELS)
            self.wav_file.setsampwidth(2)
            self.wav_file.setframerate(self.sample_rate)
            self.wav_writer = self.wav_file
            
            # PyAudio stream
            self.pyaudio_instance = pyaudiowpatch.PyAudio()
            device_idx = device_index if device_index is not None else self.device_index
            
            self.stream = self.pyaudio_instance.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=self.sample_rate,
                input=True,
                input_device_index=device_idx,
                frames_per_buffer=CHUNK_SIZE
            )
            
            logger.info(f"Stream audio aperto su device {device_idx} @ {self.sample_rate} Hz")
            
            # Loopback se richiesto
            if self.use_loopback:
                try:
                    self.loopback_recorder = LoopbackRecorder(sample_rate=self.sample_rate)
                    self.loopback_recorder.start()
                    logger.info("✓ Loopback avviato")
                except Exception as e:
                    logger.error(f"Errore loopback: {e}")
                    self.use_loopback = False
            
            # Reset statistiche
            self.total_chunks_processed = 0
            self.start_time = time.time()
            
            # Avvia threads
            self.is_recording = True
            self.is_transcribing = True
            
            
            # Reset statistiche
            self.total_chunks_processed = 0
            self.start_time = time.time()
            
            # Avvia threads
            self.is_recording = True
            self.is_transcribing = True
            
            # ⚠️ MODALITÀ ESCLUSIVA: loopback O microfono, MAI entrambi
            if self.use_loopback:
                logger.info("🔊 MODALITÀ LOOPBACK (microfono disabilitato)")
                logger.info("   Cattura TUTTO l'audio di sistema (Teams, Zoom, browser, etc.)")
                
                try:
                    self.loopback_recorder = LoopbackRecorder(
                        device_index=None,  # Auto-detect default output
                        sample_rate=self.sample_rate
                    )
                    self.loopback_recorder.start()
                    
                    self.loopback_thread = threading.Thread(target=self._loopback_thread, daemon=True)
                    self.loopback_thread.start()
                
                except Exception as e:
                    logger.error(f"Errore avvio loopback: {e}")
                    self.use_loopback = False
                    logger.info("Fallback a microfono")
                    
                    self.record_thread = threading.Thread(target=self._recording_thread, daemon=True)
                    self.record_thread.start()
            
            else:
                logger.info("🎤 MODALITÀ MICROFONO")
                self.record_thread = threading.Thread(target=self._recording_thread, daemon=True)
                self.record_thread.start()
            
            # Trascrizione sempre attiva
            self.transcribe_thread = threading.Thread(target=self._transcription_thread, daemon=True)
            self.transcribe_thread.start()
            
            return True
        
        except Exception as e:
            logger.error(f"✗ Errore avvio: {e}")
            import traceback
            traceback.print_exc()
            self.stop_recording()
            return False
    
    # ========================================================================
    # STOP RECORDING
    # ========================================================================
    def stop_recording(self):
        if not self.is_recording:
            logger.warning("Nessuna registrazione in corso")
            return False
        
        try:
            logger.info("Fermo registrazione...")
            
            # Segnala stop
            self.is_recording = False
            self.is_transcribing = False
            
            # Attendi threads
            if self.record_thread:
                self.record_thread.join(timeout=5)
            if self.transcribe_thread:
                self.transcribe_thread.join(timeout=5)
            if self.loopback_thread:
                self.loopback_thread.join(timeout=5)
            
            # Stop loopback
            if self.loopback_recorder:
                self.loopback_recorder.stop()
                self.loopback_recorder = None
            
            # Chiudi stream
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
                self.stream = None
            
            if self.pyaudio_instance:
                self.pyaudio_instance.terminate()
                self.pyaudio_instance = None
            
            # Chiudi WAV
            if self.wav_writer:
                self.wav_writer.close()
                self.wav_writer = None
                self.wav_file = None
            
            # Chiudi trascrizione
            if self.transcript_file:
                self.transcript_file.write(f"\n\n=== TRASCRIZIONE TERMINATA: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                self.transcript_file.write(f"Chunk processati: {self.total_chunks_processed}\n")
                self.transcript_file.close()
                self.transcript_file = None
            
            # Svuota queue
            while not self.audio_queue.empty():
                try:
                    self.audio_queue.get_nowait()
                except queue.Empty:
                    break
            
            logger.info(f"✓ Registrazione fermata. Chunk: {self.total_chunks_processed}")
            return True
        
        except Exception as e:
            logger.error(f"✗ Errore stop: {e}")
            return False
    
    # ========================================================================
    # UTILITY
    # ========================================================================
    def get_status(self):
        return {
            'recording': self.is_recording,
            'transcribing': self.is_transcribing,
            'chunks_processed': self.total_chunks_processed,
            'queue_size': self.audio_queue.qsize(),
            'audio_level': self.get_audio_level()
        }
    
    def cleanup(self):
        if self.is_recording:
            self.stop_recording()
        logger.info("Cleanup completato")

    def get_audio_level(self):
        """
        Restituisce livello audio corrente (0-100) per VU meter
        
        Returns:
            float: Livello audio 0-100
        """
        with self.level_lock:
            return self.current_audio_level
    
    def _update_audio_level(self, audio_data):
        """
        Aggiorna livello audio da chunk
        
        Args:
            audio_data: numpy array float32 o int16
        """
        try:
            # Converti a float se necessario
            if audio_data.dtype == np.int16:
                audio_float = audio_data.astype(np.float32) / 32768.0
            else:
                audio_float = audio_data
            
            # Calcola RMS normalizzato
            rms = np.sqrt(np.mean(audio_float**2))
            
            # Scala a 0-100 (con compressione logaritmica)
            # RMS 0.01 → 10%, RMS 0.1 → 50%, RMS 0.5 → 90%
            level = min(100, rms * 200)  # Moltiplicatore empirico
            
            with self.level_lock:
                self.current_audio_level = level
        
        except Exception as e:
            logger.debug(f"Errore calcolo level: {e}")
            
# ============================================================================
# TEST STANDALONE
# ============================================================================
if __name__ == "__main__":
    print("=" * 70)
    print("AUDIO TRANSCRIBER - TEST MIGLIORATO")
    print("=" * 70)
    
    transcriber = AudioTranscriber(use_loopback=True)
    
    print("\n📱 DISPOSITIVI AUDIO DISPONIBILI:")
    print("-" * 70)
    devices = transcriber.get_audio_devices()
    
    for dev in devices:
        loopback_mark = " [LOOPBACK]" if dev.get('is_loopback', False) else ""
        best_rate = dev.get('best_rate', dev.get('sample_rate', 'N/A'))
        supports_16k = dev.get('supports_16k', None)
        
        support_mark = ""
        if supports_16k is True:
            support_mark = " ✓16kHz"
        elif supports_16k is False:
            support_mark = " ✗16kHz"
        
        print(f"  [{dev['index']:2d}] {dev['name']}{loopback_mark}")
        print(f"       Rate: {best_rate} Hz{support_mark} | Canali: {dev['channels']}")
    
    if not devices:
        print("\n✗ ERRORE: Nessun dispositivo trovato!")
        sys.exit(1)
    
    print("\n" + "=" * 70)
    print("⚠️  RACCOMANDAZIONI:")
    print("-" * 70)
    print("1. Usa '[0] Microsoft Sound Mapper' per compatibilità massima")
    print("2. Per catturare Teams/Zoom, abilita loopback (richiede pyaudiowpatch)")
    print("3. Se il tuo microfono non funziona, verifica driver e sample rate")
    print("=" * 70)
    
    # Selezione dispositivo
    print(f"\nDispositivo consigliato: [0] {devices[0]['name']}")
    choice = input("Premi INVIO per default o inserisci numero: ").strip()
    
    device_idx = None
    if choice.isdigit():
        device_idx = int(choice)
        if device_idx not in [d['index'] for d in devices]:
            print(f"✗ Dispositivo {device_idx} non valido, uso default")
            device_idx = None
    
    # Test loopback
    use_loopback = False
    if LOOPBACK_AVAILABLE:
        loopback_choice = input("\n🔊 Vuoi catturare anche audio sistema (Teams/Zoom)? [s/N]: ").strip().lower()
        use_loopback = loopback_choice in ['s', 'y', 'si', 'yes']
        
        if use_loopback:
            transcriber.use_loopback = True
    
    # Avvia
    print("\n" + "=" * 70)
    print("⏳ Avvio registrazione in 3 secondi...")
    print("📍 Premi CTRL+C per fermare")
    print("=" * 70)
    time.sleep(3)
    
    if not transcriber.start_recording(device_index=device_idx):
        print("\n✗ ERRORE: Impossibile avviare!")
        sys.exit(1)
    
    try:
        print("\n🔴 REGISTRAZIONE IN CORSO\n")
        while True:
            time.sleep(5)
            status = transcriber.get_status()
            print(f"\r[{datetime.now().strftime('%H:%M:%S')}] "
                  f"Chunk: {status['chunks_processed']:3d} | "
                  f"Queue: {status['queue_size']}", end='', flush=True)
    
    except KeyboardInterrupt:
        print("\n\n⏹️  Interruzione...")
    
    finally:
        transcriber.stop_recording()
        transcriber.cleanup()
        print("\n✅ Test completato!")
        print(f"📁 File salvati in: {transcriber.output_dir}")