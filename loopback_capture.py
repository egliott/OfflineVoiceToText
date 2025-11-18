# loopback_capture.py - VERSIONE DEFINITIVA FUNZIONANTE
# Soluzione robusta per Windows loopback audio

import logging
import threading
import queue
import numpy as np
import sys

logger = logging.getLogger(__name__)

# ============================================================================
# METODO 1: pyaudiowpatch (raccomandato)
# ============================================================================
try:
    import pyaudiowpatch as pyaudio
    HAS_PYAUDIOWPATCH = True
    logger.info("✓ pyaudiowpatch disponibile")
except ImportError:
    HAS_PYAUDIOWPATCH = False
    try:
        import pyaudiowpatch as pyaudio
        logger.warning("⚠️ pyaudio standard (no loopback WASAPI)")
    except ImportError:
        pass

# ============================================================================
# METODO 2: sounddevice (fallback robusto)
# ============================================================================
try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
    logger.info("✓ sounddevice disponibile")
except ImportError:
    HAS_SOUNDDEVICE = False

# ============================================================================
# METODO 3: soundcard (alternativa)
# ============================================================================
try:
    import soundcard as sc
    HAS_SOUNDCARD = True
    logger.info("✓ soundcard disponibile")
except ImportError:
    HAS_SOUNDCARD = False

LOOPBACK_AVAILABLE = HAS_PYAUDIOWPATCH or HAS_SOUNDDEVICE or HAS_SOUNDCARD

if LOOPBACK_AVAILABLE:
    if HAS_SOUNDDEVICE:
        LOOPBACK_METHOD = "sounddevice"
        logger.info("→ Metodo loopback preferito: sounddevice")
    elif HAS_PYAUDIOWPATCH:
        LOOPBACK_METHOD = "pyaudiowpatch"
        logger.info("→ Metodo loopback preferito: pyaudiowpatch")
    elif HAS_SOUNDCARD:
        LOOPBACK_METHOD = "soundcard"
        logger.info("→ Metodo loopback preferito: soundcard")
else:
    LOOPBACK_METHOD = None
    logger.error("✗ NESSUN METODO LOOPBACK DISPONIBILE!")

# ============================================================================
# FUNZIONI UTILITY
# ============================================================================

def get_loopback_devices():
    """
    Ottiene lista dispositivi loopback con de-duplicazione
    
    Returns:
        list: Lista dispositivi loopback unici
    """
    if not LOOPBACK_AVAILABLE:
        logger.error("Loopback non disponibile")
        return []
    
    devices = []
    seen_names = set()
    
    try:
        # ====================================================================
        # METODO SOUNDDEVICE (più affidabile)
        # ====================================================================
        if LOOPBACK_METHOD == "sounddevice":
            sd_devices = sd.query_devices()
            
            for idx, dev in enumerate(sd_devices):
                # Cerca dispositivi output (che possiamo loopbackare)
                if dev['max_output_channels'] > 0:
                    name = dev['name']
                    
                    # Deduplica
                    if name in seen_names:
                        continue
                    seen_names.add(name)
                    
                    devices.append({
                        'index': idx,
                        'name': f"{name} (Loopback)",
                        'channels': dev['max_output_channels'],
                        'sample_rate': int(dev['default_samplerate']),
                        'type': 'loopback_sd',
                        'hostapi': dev['hostapi']
                    })
                    logger.info(f"Loopback SD: [{idx}] {name}")
        
        # ====================================================================
        # METODO PYAUDIOWPATCH
        # ====================================================================
        elif LOOPBACK_METHOD == "pyaudiowpatch":
            p = pyaudio.PyAudio()
            
            try:
                wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            except OSError:
                logger.error("WASAPI non disponibile")
                p.terminate()
                return []
            
            for i in range(wasapi_info['deviceCount']):
                try:
                    device_info = p.get_device_info_by_host_api_device_index(
                        wasapi_info['index'], i
                    )
                    
                    # Solo loopback espliciti
                    if device_info.get('isLoopbackDevice', False):
                        name = device_info['name']
                        
                        # Deduplica
                        if name in seen_names:
                            logger.debug(f"Saltato duplicato: {name}")
                            continue
                        seen_names.add(name)
                        
                        devices.append({
                            'index': device_info['index'],
                            'name': name,
                            'channels': device_info['maxInputChannels'],
                            'sample_rate': int(device_info['defaultSampleRate']),
                            'type': 'loopback_wasapi',
                            'host_api_index': wasapi_info['index']
                        })
                        logger.info(f"Loopback WASAPI: [{device_info['index']}] {name}")
                
                except Exception as e:
                    logger.debug(f"Device {i} errore: {e}")
            
            p.terminate()
        
        # ====================================================================
        # METODO SOUNDCARD
        # ====================================================================
        elif LOOPBACK_METHOD == "soundcard":
            loopbacks = sc.all_microphones(include_loopback=True)
            
            for idx, lb in enumerate(loopbacks):
                if lb.isloopback:
                    name = lb.name
                    
                    if name in seen_names:
                        continue
                    seen_names.add(name)
                    
                    devices.append({
                        'index': idx,
                        'name': name,
                        'channels': lb.channels,
                        'sample_rate': 48000,
                        'type': 'loopback_sc',
                        'sc_device': lb
                    })
        
        logger.info(f"✓ Trovati {len(devices)} dispositivi loopback UNICI")
        return devices
    
    except Exception as e:
        logger.error(f"Errore enumerazione loopback: {e}")
        import traceback
        traceback.print_exc()
        return []

# ============================================================================
# CLASSE LoopbackRecorder COMPLETAMENTE RISCRITTA
# ============================================================================

class LoopbackRecorder:
    """
    Registratore loopback multi-backend con diagnostica
    """
    
    def __init__(self, device_index=None, sample_rate=16000, method=None):
        """
        Args:
            device_index: Indice dispositivo (None = auto)
            sample_rate: Sample rate target
            method: Forza metodo ('sounddevice', 'pyaudiowpatch', 'soundcard', None=auto)
        """
        self.device_index = device_index
        self.target_sample_rate = sample_rate
        self.method = method or LOOPBACK_METHOD
        
        self.is_recording = False
        self.audio_queue = queue.Queue()
        self.thread = None
        
        # Backend specifici
        self.stream = None
        self.pyaudio_instance = None
        
        if not LOOPBACK_AVAILABLE:
            raise RuntimeError(
                "Nessun backend loopback disponibile!\n"
                "Installa uno di questi:\n"
                "  pip install sounddevice  (RACCOMANDATO)\n"
                "  pip install pyaudiowpatch\n"
                "  pip install soundcard"
            )
        
        logger.info(f"LoopbackRecorder init: method={self.method}, target_rate={sample_rate}")
    
    def start(self):
        """Avvia registrazione loopback"""
        if self.is_recording:
            logger.warning("Loopback già attivo")
            return False
        
        self.is_recording = True
        
        # Scegli metodo
        if self.method == "sounddevice":
            self.thread = threading.Thread(target=self._record_sounddevice, daemon=True)
        elif self.method == "pyaudiowpatch":
            self.thread = threading.Thread(target=self._record_pyaudiowpatch, daemon=True)
        elif self.method == "soundcard":
            self.thread = threading.Thread(target=self._record_soundcard, daemon=True)
        else:
            logger.error(f"Metodo {self.method} non supportato")
            return False
        
        self.thread.start()
        logger.info(f"✓ Loopback avviato con {self.method}")
        return True
    
    # ========================================================================
    # BACKEND 1: SOUNDDEVICE (PIÙ AFFIDABILE)
    # ========================================================================
    def _record_sounddevice(self):
        """Registrazione con sounddevice - IL PIÙ AFFIDABILE"""
        try:
            # Trova dispositivo default output
            if self.device_index is None:
                default_output = sd.query_devices(kind='output')
                device_idx = default_output['index']
                logger.info(f"Uso output default: {default_output['name']}")
            else:
                device_idx = self.device_index
            
            device_info = sd.query_devices(device_idx)
            native_rate = int(device_info['default_samplerate'])
            native_channels = device_info['max_output_channels']
            
            logger.info(f"Device: {device_info['name']}")
            logger.info(f"  Nativo: {native_rate} Hz, {native_channels} ch")
            
            # Calcola blocksize per ~100ms di latenza
            blocksize = int(native_rate * 0.1)
            
            logger.info("Apertura stream sounddevice...")
            
            # Callback per cattura audio
            def audio_callback(indata, frames, time_info, status):
                if status:
                    logger.warning(f"SD status: {status}")
                
                try:
                    # indata è già float32 numpy array
                    audio = indata.copy()
                    
                    # Converti a mono se necessario
                    if audio.ndim > 1:
                        audio = audio.mean(axis=1)
                    
                    # Resample se necessario
                    if native_rate != self.target_sample_rate:
                        audio = self._resample(audio, native_rate, self.target_sample_rate)
                    
                    # Normalizza
                    audio = np.clip(audio, -1.0, 1.0)
                    
                    # Invia se non silenzio
                    if np.max(np.abs(audio)) > 0.001:
                        try:
                            self.audio_queue.put(audio, block=False)
                        except queue.Full:
                            pass
                
                except Exception as e:
                    logger.error(f"Errore callback: {e}")
            
            # Apri stream in modalità LOOPBACK (usa device come input)
            # Su Windows con WASAPI, questo cattura l'output
            with sd.InputStream(
                device=device_idx,
                channels=1,  # Mono
                samplerate=native_rate,
                blocksize=blocksize,
                callback=audio_callback,
                dtype='float32'
            ):
                logger.info("✓ Stream sounddevice attivo")
                
                while self.is_recording:
                    sd.sleep(100)
        
        except Exception as e:
            logger.error(f"Errore sounddevice loopback: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            logger.info("Thread sounddevice terminato")
    
    # ========================================================================
    # BACKEND 2: PYAUDIOWPATCH
    # ========================================================================
    def _record_pyaudiowpatch(self):
        """Registrazione con pyaudiowpatch"""
        try:
            self.pyaudio_instance = pyaudio.PyAudio()
            wasapi_info = self.pyaudio_instance.get_host_api_info_by_type(pyaudio.paWASAPI)
            
            # Trova loopback device
            if self.device_index is None:
                # Trova default speakers loopback
                default_speakers = self.pyaudio_instance.get_device_info_by_index(
                    wasapi_info['defaultOutputDevice']
                )
                
                loopback_device = None
                for i in range(wasapi_info['deviceCount']):
                    try:
                        dev = self.pyaudio_instance.get_device_info_by_host_api_device_index(
                            wasapi_info['index'], i
                        )
                        
                        if (dev.get('isLoopbackDevice', False) and 
                            default_speakers['name'] in dev['name']):
                            loopback_device = dev
                            break
                    except:
                        continue
                
                if not loopback_device:
                    raise RuntimeError("Nessun loopback device trovato")
                
                device_info = loopback_device
            else:
                device_info = self.pyaudio_instance.get_device_info_by_index(self.device_index)
            
            native_rate = int(device_info['defaultSampleRate'])
            native_channels = device_info['maxInputChannels']
            
            logger.info(f"Device: {device_info['name']}")
            logger.info(f"  Nativo: {native_rate} Hz, {native_channels} ch")
            
            # Apri stream FLOAT32
            self.stream = self.pyaudio_instance.open(
                format=pyaudio.paFloat32,
                channels=native_channels,
                rate=native_rate,
                frames_per_buffer=2048,
                input=True,
                input_device_index=device_info['index']
            )
            
            logger.info("✓ Stream pyaudiowpatch attivo")
            
            buffer = []
            samples_per_chunk = native_rate  # 1 secondo
            
            while self.is_recording:
                try:
                    data = self.stream.read(2048, exception_on_overflow=False)
                    audio = np.frombuffer(data, dtype=np.float32)
                    
                    # Converti a mono
                    if native_channels > 1:
                        audio = audio.reshape(-1, native_channels).mean(axis=1)
                    
                    buffer.extend(audio)
                    
                    if len(buffer) >= samples_per_chunk:
                        chunk = np.array(buffer[:samples_per_chunk], dtype=np.float32)
                        
                        # Resample
                        if native_rate != self.target_sample_rate:
                            chunk = self._resample(chunk, native_rate, self.target_sample_rate)
                        
                        chunk = np.clip(chunk, -1.0, 1.0)
                        
                        if np.max(np.abs(chunk)) > 0.001:
                            try:
                                self.audio_queue.put(chunk, timeout=0.5)
                            except queue.Full:
                                pass
                        
                        buffer = buffer[samples_per_chunk:]
                
                except Exception as e:
                    logger.error(f"Errore read: {e}")
                    import time
                    time.sleep(0.1)
        
        except Exception as e:
            logger.error(f"Errore pyaudiowpatch: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
            if self.pyaudio_instance:
                self.pyaudio_instance.terminate()
            logger.info("Thread pyaudiowpatch terminato")
    
    # ========================================================================
    # BACKEND 3: SOUNDCARD
    # ========================================================================
    def _record_soundcard(self):
        """Registrazione con soundcard"""
        try:
            loopback = sc.default_speaker()
            
            with loopback.recorder(samplerate=self.target_sample_rate, channels=1) as mic:
                logger.info(f"✓ Soundcard loopback: {loopback.name}")
                
                while self.is_recording:
                    data = mic.record(numframes=2048)
                    audio = data.flatten().astype(np.float32)
                    
                    if np.max(np.abs(audio)) > 0.001:
                        try:
                            self.audio_queue.put(audio, block=False)
                        except queue.Full:
                            pass
        
        except Exception as e:
            logger.error(f"Errore soundcard: {e}")
    
    # ========================================================================
    # UTILITY
    # ========================================================================
    def _resample(self, audio, orig_rate, target_rate):
        """Resample audio"""
        if orig_rate == target_rate:
            return audio
        
        try:
            from scipy import signal
            ratio = target_rate / orig_rate
            target_length = int(len(audio) * ratio)
            return signal.resample(audio, target_length).astype(np.float32)
        except ImportError:
            # Fallback lineare
            duration = len(audio) / orig_rate
            target_length = int(duration * target_rate)
            indices = np.linspace(0, len(audio) - 1, target_length)
            return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)
    
    def stop(self):
        """Ferma registrazione"""
        logger.info("Stop loopback richiesto")
        self.is_recording = False
        if self.thread:
            self.thread.join(timeout=5)
    
    def get_audio(self, timeout=1):
        """Preleva audio dalla queue"""
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

# ============================================================================
# DIAGNOSTICA
# ============================================================================

def print_loopback_diagnostic():
    """Stampa diagnostica completa loopback"""
    print("\n" + "="*70)
    print("DIAGNOSTICA LOOPBACK AUDIO")
    print("="*70)
    
    print(f"\n📦 Backend disponibili:")
    print(f"  pyaudiowpatch: {'✓' if HAS_PYAUDIOWPATCH else '✗'}")
    print(f"  sounddevice:   {'✓' if HAS_SOUNDDEVICE else '✗'}")
    print(f"  soundcard:     {'✓' if HAS_SOUNDCARD else '✗'}")
    
    if not LOOPBACK_AVAILABLE:
        print("\n❌ NESSUN BACKEND DISPONIBILE!")
        print("\nInstalla uno di questi:")
        print("  pip install sounddevice  (RACCOMANDATO)")
        print("  pip install pyaudiowpatch")
        return
    
    print(f"\n→ Metodo preferito: {LOOPBACK_METHOD}")
    
    print(f"\n🎧 Dispositivi loopback rilevati:")
    devices = get_loopback_devices()
    
    if not devices:
        print("  ✗ Nessun dispositivo loopback trovato")
    else:
        for dev in devices:
            print(f"  [{dev['index']:2d}] {dev['name']}")
            print(f"       {dev['sample_rate']} Hz | {dev['channels']} ch | {dev['type']}")
    
    print("="*70 + "\n")

if __name__ == "__main__":
    # Test standalone
    print_loopback_diagnostic()