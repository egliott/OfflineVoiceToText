# whisperpy
# cd "C:\Users\E26051\OneDrive - E.ON\Desktop\Work\Test\Audio\Script Pyhon\claude"

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import threading
import time
from pathlib import Path
from datetime import datetime
import queue

# Import del modulo principale
try:
    from main import AudioTranscriber, logger
except ImportError:
    import sys
    print("ERRORE: Impossibile importare main.py")
    print("Assicurati che main.py sia nella stessa directory di gui_audio.py")
    sys.exit(1)

# ============================================================================
# COSTANTI GUI
# ============================================================================
WINDOW_TITLE = "Audio Transcriber - Registrazione e Trascrizione Real-time"
WINDOW_WIDTH = 900
WINDOW_HEIGHT = 700
BG_COLOR = "#f0f0f0"
ACCENT_COLOR = "#4CAF50"
ERROR_COLOR = "#f44336"
WARNING_COLOR = "#FF9800"

# ============================================================================
# CLASSE PRINCIPALE GUI
# ============================================================================
class AudioTranscriberGUI:
    def __init__(self, root):
        """
        Inizializza l'interfaccia grafica
        
        Args:
            root: Tkinter root window
        """
        self.root = root
        self.root.title(WINDOW_TITLE)
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.resizable(True, True)
        
        # Backend transcriber
        self.transcriber = None
        self.output_dir = Path.home() / "Desktop" / "Trascrizioni"
        
        # Stato applicazione
        self.is_recording = False
        self.update_thread = None
        self.should_update = False
        
        # Queue per aggiornamenti GUI thread-safe
        self.gui_queue = queue.Queue()
        
        # Configurazione stile
        self.setup_styles()
        
        # Costruzione GUI
        self.build_gui()
        
        # Inizializza transcriber
        self.init_transcriber()
        
        # Carica dispositivi audio
        self.refresh_devices()
        
        # Avvia monitor aggiornamenti
        self.start_gui_monitor()
        
        # Gestione chiusura finestra
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        logger.info("GUI inizializzata")
    
    # ========================================================================
    # CONFIGURAZIONE STILI
    # ========================================================================
    def setup_styles(self):
        """Configura stili ttk personalizzati"""
        style = ttk.Style()
        
        # Tema base
        try:
            style.theme_use('clam')
        except:
            pass
        
        # Stile pulsanti
        style.configure('Start.TButton', 
                       background=ACCENT_COLOR,
                       foreground='white',
                       font=('Arial', 11, 'bold'),
                       padding=10)
        
        style.configure('Stop.TButton',
                       background=ERROR_COLOR,
                       foreground='white',
                       font=('Arial', 11, 'bold'),
                       padding=10)
        
        style.configure('Normal.TButton',
                       font=('Arial', 10),
                       padding=5)
        
        # Stile labels
        style.configure('Title.TLabel',
                       font=('Arial', 12, 'bold'),
                       background=BG_COLOR)
        
        style.configure('Status.TLabel',
                       font=('Arial', 10),
                       background=BG_COLOR)
    
    # ========================================================================
    # COSTRUZIONE INTERFACCIA
    # ========================================================================
    def build_gui(self):
        """Costruisce tutti i componenti della GUI"""
        
        # Frame principale con padding
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configura espansione
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)  # Area testo espandibile
        
        # ====================================================================
        # SEZIONE 1: CONFIGURAZIONE
        # ====================================================================
        config_frame = ttk.LabelFrame(main_frame, text="⚙ Configurazione", padding="10")
        config_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        config_frame.columnconfigure(1, weight=1)
        
        # Selezione dispositivo audio
        ttk.Label(config_frame, text="Dispositivo Audio:").grid(row=0, column=0, sticky=tk.W, pady=5)
        
        device_frame = ttk.Frame(config_frame)
        device_frame.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=5, padx=(10, 0))
        device_frame.columnconfigure(0, weight=1)
        
        self.device_combo = ttk.Combobox(device_frame, state='readonly')
        self.device_combo.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))
        
        self.refresh_btn = ttk.Button(device_frame, text="🔄", width=3, command=self.refresh_devices, style='Normal.TButton')
        self.refresh_btn.grid(row=0, column=1)
        
        # Selezione cartella output
        ttk.Label(config_frame, text="Cartella Output:").grid(row=1, column=0, sticky=tk.W, pady=5)
        
        output_frame = ttk.Frame(config_frame)
        output_frame.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5, padx=(10, 0))
        output_frame.columnconfigure(0, weight=1)
        
        self.output_entry = ttk.Entry(output_frame)
        self.output_entry.insert(0, str(self.output_dir))
        self.output_entry.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))
        
        self.browse_btn = ttk.Button(output_frame, text="📁 Sfoglia", command=self.browse_output_dir,style='Normal.TButton')
        self.browse_btn.grid(row=0, column=1)
        
        # ====================================================================
        # SEZIONE 2: CONTROLLI REGISTRAZIONE
        # ====================================================================
        control_frame = ttk.LabelFrame(main_frame, text="🎙 Controlli", padding="10")
        control_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Pulsanti principali
        button_frame = ttk.Frame(control_frame)
        button_frame.pack(fill=tk.X, pady=5)
        
        self.start_btn = ttk.Button(button_frame, 
                                    text="▶ Avvia Registrazione",
                                    command=self.start_recording,
                                    style='Start.TButton')
        self.start_btn.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        
        self.stop_btn = ttk.Button(button_frame,
                                   text="⏹ Ferma e Salva",
                                   command=self.stop_recording,
                                   style='Stop.TButton',
                                   state='disabled')
        self.stop_btn.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        
        # Indicatore livello audio (VU Meter)
        vu_frame = ttk.Frame(control_frame)
        vu_frame.pack(fill=tk.X, pady=(10, 5))
        
        ttk.Label(vu_frame, text="Livello Audio:", style='Status.TLabel').pack(side=tk.LEFT, padx=(0, 10))
        
        self.vu_meter = ttk.Progressbar(vu_frame, 
                                        mode='determinate',
                                        maximum=100,
                                        length=400)
        self.vu_meter.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.vu_label = ttk.Label(vu_frame, text="0%", width=5, style='Status.TLabel')
        self.vu_label.pack(side=tk.LEFT, padx=(5, 0))
        
        # ====================================================================
        # SEZIONE 3: STATISTICHE
        # ====================================================================
        stats_frame = ttk.Frame(main_frame)
        stats_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        stats_frame.columnconfigure(0, weight=1)
        stats_frame.columnconfigure(1, weight=1)
        stats_frame.columnconfigure(2, weight=1)
        
        # Tempo registrazione
        time_frame = ttk.LabelFrame(stats_frame, text="⏱ Tempo", padding="5")
        time_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))
        self.time_label = ttk.Label(time_frame, text="00:00:00", 
                                    font=('Arial', 14, 'bold'))
        self.time_label.pack()
        
        # Chunk processati
        chunks_frame = ttk.LabelFrame(stats_frame, text="📦 Chunk Processati", padding="5")
        chunks_frame.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5)
        self.chunks_label = ttk.Label(chunks_frame, text="0", 
                                      font=('Arial', 14, 'bold'))
        self.chunks_label.pack()
        
        # Queue size
        queue_frame = ttk.LabelFrame(stats_frame, text="📊 Queue Audio", padding="5")
        queue_frame.grid(row=0, column=2, sticky=(tk.W, tk.E), padx=(5, 0))
        self.queue_label = ttk.Label(queue_frame, text="0", 
                                     font=('Arial', 14, 'bold'))
        self.queue_label.pack()
        
        # ====================================================================
        # SEZIONE 4: AREA TRASCRIZIONE
        # ====================================================================
        transcript_frame = ttk.LabelFrame(main_frame, text="📝 Trascrizione Real-time", padding="10")
        transcript_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        transcript_frame.columnconfigure(0, weight=1)
        transcript_frame.rowconfigure(0, weight=1)
        
        # Area testo scrollabile
        self.transcript_text = scrolledtext.ScrolledText(
            transcript_frame,
            wrap=tk.WORD,
            width=80,
            height=15,
            font=('Consolas', 10),
            state='disabled',
            bg='#ffffff',
            fg='#000000'
        )
        self.transcript_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Toolbar trascrizione
        transcript_toolbar = ttk.Frame(transcript_frame)
        transcript_toolbar.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(5, 0))
        
        self.clear_btn = ttk.Button(transcript_toolbar,
                                    text="🗑 Pulisci",
                                    command=self.clear_transcript,
                                    style='Normal.TButton')
        self.clear_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.copy_btn = ttk.Button(transcript_toolbar,
                                   text="📋 Copia",
                                   command=self.copy_transcript,
                                   style='Normal.TButton')
        self.copy_btn.pack(side=tk.LEFT)
        
        # ====================================================================
        # SEZIONE 5: STATUS BAR
        # ====================================================================
        status_frame = ttk.Frame(main_frame, relief=tk.SUNKEN, borderwidth=1)
        status_frame.grid(row=4, column=0, sticky=(tk.W, tk.E))
        
        self.status_label = ttk.Label(status_frame, 
                                      text="⚪ Stato: Idle - Pronto per registrare",
                                      style='Status.TLabel',
                                      padding="5")
        self.status_label.pack(side=tk.LEFT)
        
        self.model_label = ttk.Label(status_frame,
                                     text="Modello: Whisper Turbo (CPU)",
                                     style='Status.TLabel',
                                     padding="5")
        self.model_label.pack(side=tk.RIGHT)
    
    # ========================================================================
    # INIZIALIZZAZIONE BACKEND
    # ========================================================================
    def init_transcriber(self):
        """Inizializza il backend AudioTranscriber"""
        try:
            self.transcriber = AudioTranscriber(output_dir=self.output_dir)
            logger.info("Backend transcriber inizializzato")
        except Exception as e:
            logger.error(f"Errore inizializzazione transcriber: {e}")
            messagebox.showerror("Errore", 
                               f"Impossibile inizializzare il sistema di trascrizione:\n{str(e)}")
    
    # ========================================================================
    # GESTIONE DISPOSITIVI AUDIO
    # ========================================================================
    def refresh_devices(self):
        """Aggiorna lista dispositivi audio"""
        if self.is_recording:
            messagebox.showwarning("Attenzione", 
                                 "Impossibile aggiornare dispositivi durante la registrazione")
            return
        
        try:
            self.update_status("🔄 Caricamento dispositivi audio...", WARNING_COLOR)
            devices = self.transcriber.get_audio_devices()
            
            if not devices:
                messagebox.showerror("Errore", 
                                   "Nessun dispositivo audio trovato!\n\n"
                                   "Verifica che almeno un microfono sia connesso.")
                self.device_combo['values'] = ["Nessun dispositivo trovato"]
                self.device_combo.current(0)
                self.device_combo.state(['disabled'])
                self.start_btn.state(['disabled'])
                return
            
            # Popola combo con nomi dispositivi
            device_names = [f"[{d['index']}] {d['name']}" for d in devices]
            self.device_combo['values'] = device_names
            self.device_combo.current(0)
            self.device_combo.state(['!disabled'])
            self.start_btn.state(['!disabled'])
            
            self.update_status(f"✓ Trovati {len(devices)} dispositivi audio", ACCENT_COLOR)
            logger.info(f"Dispositivi audio caricati: {len(devices)}")
            
        except Exception as e:
            logger.error(f"Errore refresh dispositivi: {e}")
            messagebox.showerror("Errore", f"Errore durante il caricamento dispositivi:\n{str(e)}")
            self.update_status("✗ Errore caricamento dispositivi", ERROR_COLOR)
    
    def get_selected_device_index(self):
        """
        Estrae l'indice del dispositivo selezionato
        
        Returns:
            int: Indice dispositivo o None
        """
        selected = self.device_combo.get()
        if not selected or "Nessun dispositivo" in selected:
            return None
        
        try:
            # Estrai indice tra parentesi quadre: [2] Nome Device -> 2
            index = int(selected.split(']')[0].split('[')[1])
            return index
        except:
            return None
    
    # ========================================================================
    # GESTIONE OUTPUT DIRECTORY
    # ========================================================================
    def browse_output_dir(self):
        """Apre dialog per selezione cartella output"""
        if self.is_recording:
            messagebox.showwarning("Attenzione",
                                 "Impossibile cambiare cartella durante la registrazione")
            return
        
        directory = filedialog.askdirectory(
            title="Seleziona cartella per salvare le trascrizioni",
            initialdir=self.output_dir
        )
        
        if directory:
            self.output_dir = Path(directory)
            self.output_entry.delete(0, tk.END)
            self.output_entry.insert(0, str(self.output_dir))
            
            # Aggiorna transcriber
            if self.transcriber:
                self.transcriber.output_dir = self.output_dir
            
            logger.info(f"Output directory cambiata: {self.output_dir}")
    
    # ========================================================================
    # CONTROLLI REGISTRAZIONE
    # ========================================================================
    def start_recording(self):
        """Avvia registrazione e trascrizione"""
        if self.is_recording:
            return
        
        # Validazione
        device_index = self.get_selected_device_index()
        if device_index is None:
            messagebox.showerror("Errore", "Seleziona un dispositivo audio valido")
            return
        
        # Conferma output directory
        if not self.output_dir.exists():
            try:
                self.output_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Errore", 
                                   f"Impossibile creare cartella output:\n{str(e)}")
                return
        
        # Aggiorna output dir nel transcriber
        self.transcriber.output_dir = self.output_dir
        
        # Avvia registrazione
        self.update_status("🔄 Avvio registrazione...", WARNING_COLOR)
        
        try:
            success = self.transcriber.start_recording(device_index=device_index)
            
            if not success:
                messagebox.showerror("Errore",
                                   "Impossibile avviare la registrazione.\n\n"
                                   "Controlla il log per maggiori dettagli.")
                self.update_status("✗ Errore avvio registrazione", ERROR_COLOR)
                return
            
            # Aggiorna stato GUI
            self.is_recording = True
            self.start_btn.state(['disabled'])
            self.stop_btn.state(['!disabled'])
            self.device_combo.state(['disabled'])
            self.refresh_btn.state(['disabled'])
            self.browse_btn.state(['disabled'])
            
            # Pulisci area trascrizione
            self.transcript_text.config(state='normal')
            self.transcript_text.delete(1.0, tk.END)
            self.transcript_text.config(state='disabled')
            
            # Avvia thread aggiornamento
            self.should_update = True
            self.update_thread = threading.Thread(target=self._update_loop, daemon=True)
            self.update_thread.start()
            
            self.update_status("🔴 Registrazione in corso...", ERROR_COLOR)
            logger.info("Registrazione avviata da GUI")
            
        except Exception as e:
            logger.error(f"Errore avvio registrazione: {e}")
            messagebox.showerror("Errore", f"Errore durante l'avvio:\n{str(e)}")
            self.update_status("✗ Errore", ERROR_COLOR)
    
    def stop_recording(self):
        """Ferma registrazione e trascrizione"""
        if not self.is_recording:
            return
        
        self.update_status("🔄 Arresto registrazione...", WARNING_COLOR)
        self.stop_btn.state(['disabled'])
        
        try:
            # Ferma thread aggiornamento
            self.should_update = False
            if self.update_thread:
                self.update_thread.join(timeout=2)
            
            # Ferma registrazione
            success = self.transcriber.stop_recording()
            
            if success:
                self.update_status("✓ Registrazione completata e salvata", ACCENT_COLOR)
                
                # Mostra info file salvati
                messagebox.showinfo("Completato",
                                  f"Registrazione salvata con successo!\n\n"
                                  f"File salvati in:\n{self.output_dir}")
            else:
                self.update_status("⚠ Registrazione fermata con errori", WARNING_COLOR)
            
            # Ripristina stato GUI
            self.is_recording = False
            self.start_btn.state(['!disabled'])
            self.stop_btn.state(['disabled'])
            self.device_combo.state(['readonly'])
            self.refresh_btn.state(['!disabled'])
            self.browse_btn.state(['!disabled'])
            
            # Reset indicatori
            self.vu_meter['value'] = 0
            self.vu_label['text'] = "0%"
            
            logger.info("Registrazione fermata da GUI")
            
        except Exception as e:
            logger.error(f"Errore stop registrazione: {e}")
            messagebox.showerror("Errore", f"Errore durante l'arresto:\n{str(e)}")
            self.update_status("✗ Errore arresto", ERROR_COLOR)
    
    # ========================================================================
    # AGGIORNAMENTO REAL-TIME
    # ========================================================================
    def _update_loop(self):
        """Thread aggiornamento - AGGIUNTO AUDIO LEVEL REALE"""
        start_time = time.time()
        last_chunks = 0
        
        while self.should_update and self.is_recording:
            try:
                status = self.transcriber.get_status()
                
                if not status['recording']:
                    break
                
                # Tempo elapsed
                elapsed = int(time.time() - start_time)
                hours = elapsed // 3600
                minutes = (elapsed % 3600) // 60
                seconds = elapsed % 60
                time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                
                # ⚠️ USA AUDIO LEVEL REALE (non simulato)
                vu_value = int(status.get('audio_level', 0))
                
                # Invia aggiornamenti
                self.gui_queue.put({
                    'type': 'stats',
                    'time': time_str,
                    'chunks': status['chunks_processed'],
                    'queue': status['queue_size'],
                    'vu': vu_value  # ⚠️ REALE
                })
                
                # Se nuovo chunk, notifica
                if status['chunks_processed'] > last_chunks:
                    self.gui_queue.put({
                        'type': 'transcript',
                        'text': f"[Chunk {status['chunks_processed']} processato...]\n"
                    })
                    last_chunks = status['chunks_processed']
                
                time.sleep(0.2)  # ⚠️ Aggiorna ogni 200ms (era 500ms) per VU meter più reattivo
                
            except Exception as e:
                logger.error(f"Errore update loop: {e}")
                time.sleep(1)
    
    def start_gui_monitor(self):
        """Avvia monitor per aggiornamenti GUI thread-safe"""
        def monitor():
            try:
                # Processa messaggi dalla queue
                while True:
                    try:
                        msg = self.gui_queue.get_nowait()
                        
                        if msg['type'] == 'stats':
                            # Aggiorna statistiche
                            self.time_label['text'] = msg['time']
                            self.chunks_label['text'] = str(msg['chunks'])
                            self.queue_label['text'] = str(msg['queue'])
                            self.vu_meter['value'] = msg['vu']
                            self.vu_label['text'] = f"{msg['vu']}%"
                        
                        elif msg['type'] == 'transcript':
                            # Aggiorna trascrizione
                            self.append_transcript(msg['text'])
                    
                    except queue.Empty:
                        break
            
            except Exception as e:
                logger.error(f"Errore in GUI monitor: {e}")
            
            # Ri-schedula dopo 100ms
            self.root.after(100, monitor)
        
        # Avvia monitor
        self.root.after(100, monitor)
    
    # ========================================================================
    # GESTIONE AREA TRASCRIZIONE
    # ========================================================================
    def append_transcript(self, text):
        """Aggiunge testo all'area trascrizione"""
        self.transcript_text.config(state='normal')
        self.transcript_text.insert(tk.END, text)
        self.transcript_text.see(tk.END)  # Auto-scroll
        self.transcript_text.config(state='disabled')
    
    def clear_transcript(self):
        """Pulisce area trascrizione"""
        if self.is_recording:
            if not messagebox.askyesno("Conferma",
                                      "Vuoi davvero pulire l'area trascrizione?\n"
                                      "La registrazione continuerà normalmente."):
                return
        
        self.transcript_text.config(state='normal')
        self.transcript_text.delete(1.0, tk.END)
        self.transcript_text.config(state='disabled')
    
    def copy_transcript(self):
        """Copia trascrizione negli appunti"""
        try:
            text = self.transcript_text.get(1.0, tk.END).strip()
            if text:
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
                self.update_status("✓ Trascrizione copiata negli appunti", ACCENT_COLOR)
                logger.info("Trascrizione copiata negli appunti")
            else:
                messagebox.showinfo("Info", "Nessun testo da copiare")
        except Exception as e:
            logger.error(f"Errore copia trascrizione: {e}")
            messagebox.showerror("Errore", f"Impossibile copiare:\n{str(e)}")
    
    # ========================================================================
    # GESTIONE STATUS BAR
    # ========================================================================
    def update_status(self, message, color=None):
        """
        Aggiorna status bar
        
        Args:
            message: Testo da visualizzare
            color: Colore testo (opzionale)
        """
        self.status_label['text'] = message
        if color:
            self.status_label['foreground'] = color
    
    # ========================================================================
    # CHIUSURA APPLICAZIONE
    # ========================================================================
    def on_closing(self):
        """Gestisce chiusura applicazione"""
        if self.is_recording:
            if not messagebox.askyesno("Conferma uscita",
                                      "Registrazione in corso!\n\n"
                                      "Vuoi davvero uscire?\n"
                                      "La registrazione verrà salvata automaticamente."):
                return
            
            # Ferma registrazione
            self.stop_recording()
        
        # Cleanup
        if self.transcriber:
            self.transcriber.cleanup()
        
        logger.info("Applicazione chiusa")
        self.root.destroy()

# ============================================================================
# PUNTO DI INGRESSO
# ============================================================================
def main():
    """Avvia l'applicazione GUI"""
    try:
        # Crea finestra principale
        root = tk.Tk()
        
        # Imposta icona (opzionale, commentato se non disponibile)
        # try:
        #     root.iconbitmap('icon.ico')
        # except:
        #     pass
        
        # Crea GUI
        app = AudioTranscriberGUI(root)
        
        # Avvia loop eventi
        root.mainloop()
    
    except Exception as e:
        logger.error(f"Errore fatale: {e}")
        import traceback
        traceback.print_exc()
        
        # Mostra errore anche se GUI non disponibile
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Errore Fatale",
                               f"Impossibile avviare l'applicazione:\n\n{str(e)}")
        except:
            print(f"ERRORE FATALE: {e}")

if __name__ == "__main__":
    print("=" * 60)
    print("AUDIO TRANSCRIBER - Interfaccia Grafica")
    print("=" * 60)
    print("Avvio applicazione...")
    main()