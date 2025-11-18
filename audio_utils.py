# audio_utils.py - Utility per gestione dispositivi audio avanzata

import pyaudiowpatch
import logging

logger = logging.getLogger(__name__)

def get_device_native_rate(device_index):
    """
    Ottiene il sample rate nativo di un dispositivo
    
    Args:
        device_index: Indice dispositivo
        
    Returns:
        int: Sample rate nativo o None se errore
    """
    try:
        p = pyaudiowpatch.PyAudio()
        info = p.get_device_info_by_index(device_index)
        native_rate = int(info['defaultSampleRate'])
        p.terminate()
        return native_rate
    except Exception as e:
        logger.error(f"Errore lettura sample rate device {device_index}: {e}")
        return None

def test_device_format(device_index, rate=16000, channels=1, format=pyaudiowpatch.paInt16):
    """
    Testa se un dispositivo supporta un formato specifico
    
    Args:
        device_index: Indice dispositivo
        rate: Sample rate
        channels: Numero canali
        format: Formato audio
        
    Returns:
        bool: True se supportato
    """
    try:
        p = pyaudiowpatch.PyAudio()
        
        # Tenta di aprire stream con formato richiesto
        is_supported = p.is_format_supported(
            rate,
            input_device=device_index,
            input_channels=channels,
            input_format=format
        )
        
        p.terminate()
        return is_supported
    
    except Exception as e:
        logger.debug(f"Device {device_index} non supporta rate={rate}: {e}")
        return False

def get_best_sample_rate(device_index):
    """
    Trova il miglior sample rate per un dispositivo
    
    Args:
        device_index: Indice dispositivo
        
    Returns:
        int: Miglior sample rate
    """
    # Priorità: 16000 (ottimale per Whisper), poi rate nativi comuni
    preferred_rates = [16000, 44100, 48000, 22050, 32000, 11025, 8000]
    
    for rate in preferred_rates:
        if test_device_format(device_index, rate=rate):
            logger.info(f"Device {device_index}: sample rate {rate} Hz supportato")
            return rate
    
    # Fallback: usa rate nativo
    native_rate = get_device_native_rate(device_index)
    logger.warning(f"Device {device_index}: fallback a rate nativo {native_rate} Hz")
    return native_rate or 16000

def get_enhanced_audio_devices():
    """
    Restituisce lista dispositivi con info dettagliate e test compatibilità
    
    Returns:
        list: Lista dict con info dispositivi
    """
    devices = []
    try:
        p = pyaudiowpatch.PyAudio()
        
        for i in range(p.get_device_count()):
            try:
                info = p.get_device_info_by_index(i)
                
                # Solo dispositivi con input
                if info['maxInputChannels'] > 0:
                    native_rate = int(info['defaultSampleRate'])
                    
                    # Testa supporto per 16000 Hz (ottimale Whisper)
                    supports_16k = test_device_format(i, rate=16000)
                    
                    # Trova miglior sample rate
                    best_rate = get_best_sample_rate(i)
                    
                    devices.append({
                        'index': i,
                        'name': info['name'],
                        'channels': info['maxInputChannels'],
                        'native_rate': native_rate,
                        'supports_16k': supports_16k,
                        'best_rate': best_rate,
                        'host_api': p.get_host_api_info_by_index(info['hostApi'])['name']
                    })
                    
            except Exception as e:
                logger.warning(f"Errore analisi device {i}: {e}")
        
        p.terminate()
        logger.info(f"Trovati {len(devices)} dispositivi audio input")
        return devices
    
    except Exception as e:
        logger.error(f"Errore enumerazione dispositivi: {e}")
        return []