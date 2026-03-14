"""
recorder.py — Module d'enregistrement audio du Mini DAW
Enregistre micro et/ou instrument via la carte son Windows interne.
Dépendances : sounddevice, soundfile, numpy
pip install sounddevice soundfile numpy
"""

import os
import threading
import time
import tkinter as tk
from tkinter import ttk

try:
    import sounddevice as sd
    import soundfile as sf
    import numpy as np
    SD_OK = True
except ImportError as e:
    SD_OK = False
    print(f"[Recorder] sounddevice/soundfile/numpy manquant : {e}")
    print("  → pip install sounddevice soundfile numpy")


# Dossier de sortie des enregistrements
RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "samples", "recordings")
os.makedirs(RECORDINGS_DIR, exist_ok=True)

SAMPLE_RATE = 44100
CHANNELS = 1          # Mono (carte son interne)
DTYPE = "float32"


class Recorder:
    """
    Enregistre l'audio depuis le micro/entrée ligne de la carte son interne.
    """

    def __init__(self):
        self.is_recording = False
        self._frames = []
        self._stream = None
        self._thread = None
        self._stop_event = threading.Event()
        self.last_file = None

    # ------------------------------------------------
    # LISTE DES PÉRIPHÉRIQUES
    # ------------------------------------------------
    @staticmethod
    def list_devices():
        """Retourne la liste des périphériques d'entrée disponibles."""
        if not SD_OK:
            return []
        devices = sd.query_devices()
        inputs = []
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0:
                inputs.append((i, d["name"]))
        return inputs

    @staticmethod
    def get_default_input():
        """Retourne l'index du périphérique d'entrée par défaut."""
        if not SD_OK:
            return None
        try:
            return sd.default.device[0]
        except Exception:
            return None

    # ------------------------------------------------
    # ENREGISTREMENT
    # ------------------------------------------------
    def start(self, device_index=None, channels=CHANNELS):
        """Démarre l'enregistrement."""
        if not SD_OK:
            print("[Recorder] sounddevice non disponible")
            return False

        if self.is_recording:
            print("[Recorder] Déjà en cours d'enregistrement")
            return False

        self._frames = []
        self._stop_event.clear()
        self.is_recording = True

        self._thread = threading.Thread(
            target=self._record_loop,
            args=(device_index, channels),
            daemon=True
        )
        self._thread.start()
        print(f"[Recorder] ● Enregistrement démarré (device={device_index})")
        return True

    def _record_loop(self, device_index, channels):
        """Boucle d'enregistrement dans un thread séparé."""
        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=channels,
                dtype=DTYPE,
                device=device_index,
                blocksize=1024,
            ) as stream:
                while not self._stop_event.is_set():
                    data, overflowed = stream.read(1024)
                    if overflowed:
                        print("[Recorder] Overflow détecté")
                    self._frames.append(data.copy())
        except Exception as e:
            print(f"[Recorder] Erreur stream : {e}")
        finally:
            self.is_recording = False

    def stop(self, filename=None):
        """
        Arrête l'enregistrement et sauvegarde en WAV.
        Retourne le chemin du fichier sauvegardé.
        """
        if not self.is_recording:
            return None

        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)

        self.is_recording = False

        if not self._frames:
            print("[Recorder] Aucune donnée enregistrée")
            return None

        # Générer un nom de fichier automatique si non spécifié
        if filename is None:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"rec_{timestamp}.wav"

        out_path = os.path.join(RECORDINGS_DIR, filename)

        try:
            audio_data = np.concatenate(self._frames, axis=0)
            sf.write(out_path, audio_data, SAMPLE_RATE)
            self.last_file = out_path
            duration = len(audio_data) / SAMPLE_RATE
            print(f"[Recorder] ✔ Sauvegardé : {out_path} ({duration:.1f}s)")
            return out_path
        except Exception as e:
            print(f"[Recorder] Erreur sauvegarde : {e}")
            return None

    # ------------------------------------------------
    # MONITORING (écoute en temps réel)
    # ------------------------------------------------
    def get_level(self):
        """Retourne le niveau RMS du dernier bloc (pour vumètre)."""
        if not self._frames:
            return 0.0
        last = self._frames[-1]
        rms = float(np.sqrt(np.mean(last ** 2)))
        return min(1.0, rms * 10)


# ================================================
# FENÊTRE D'ENREGISTREMENT (widget tkinter)
# ================================================
class RecorderWindow:
    """
    Fenêtre flottante d'enregistrement à intégrer dans le DAW.
    Appelle on_recorded(filepath, duration) quand un enregistrement est terminé.
    """

    def __init__(self, parent, on_recorded=None):
        self.parent = parent
        self.on_recorded = on_recorded
        self.recorder = Recorder()
        self._vu_job = None

        # Fenêtre flottante
        self.win = tk.Toplevel(parent)
        self.win.title("● Enregistrement")
        self.win.configure(bg="#0f0f0f")
        self.win.resizable(False, False)
        self.win.geometry("340x280")
        self.win.grab_set()  # Modale

        self._build_ui()
        self._refresh_devices()

    def _build_ui(self):
        pad = {"padx": 12, "pady": 6}

        # Titre
        tk.Label(self.win, text="● ENREGISTREMENT",
                 bg="#0f0f0f", fg="#ff4444",
                 font=("Segoe UI", 11, "bold")).pack(pady=(14, 4))

        # Sélection périphérique
        dev_frame = tk.Frame(self.win, bg="#0f0f0f")
        dev_frame.pack(fill="x", **pad)

        tk.Label(dev_frame, text="Entrée :",
                 bg="#0f0f0f", fg="#888888",
                 font=("Segoe UI", 9)).pack(side="left")

        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(
            dev_frame, textvariable=self.device_var,
            state="readonly", width=28,
            font=("Segoe UI", 8)
        )
        self.device_combo.pack(side="left", padx=6)

        # Nom du fichier
        name_frame = tk.Frame(self.win, bg="#0f0f0f")
        name_frame.pack(fill="x", **pad)

        tk.Label(name_frame, text="Nom :",
                 bg="#0f0f0f", fg="#888888",
                 font=("Segoe UI", 9)).pack(side="left")

        self.name_var = tk.StringVar(value="")
        tk.Entry(name_frame, textvariable=self.name_var,
                 bg="#1e1e1e", fg="white", insertbackground="white",
                 relief="flat", font=("Segoe UI", 9),
                 width=26).pack(side="left", padx=6)

        # VU-mètre
        vu_frame = tk.Frame(self.win, bg="#0f0f0f")
        vu_frame.pack(fill="x", padx=12, pady=4)

        tk.Label(vu_frame, text="Niveau :",
                 bg="#0f0f0f", fg="#888888",
                 font=("Segoe UI", 9)).pack(side="left")

        self.vu_canvas = tk.Canvas(vu_frame, bg="#1a1a1a",
                                   width=200, height=14,
                                   highlightthickness=0)
        self.vu_canvas.pack(side="left", padx=8)
        self.vu_bar = self.vu_canvas.create_rectangle(
            0, 0, 0, 14, fill="#4CAF50", outline=""
        )

        # Timer
        self.timer_label = tk.Label(
            self.win, text="00:00",
            bg="#0f0f0f", fg="#cccccc",
            font=("Consolas", 22, "bold")
        )
        self.timer_label.pack(pady=6)
        self._rec_start = None

        # Boutons
        btn_frame = tk.Frame(self.win, bg="#0f0f0f")
        btn_frame.pack(pady=10)

        self.btn_rec = tk.Button(
            btn_frame, text="● REC",
            font=("Segoe UI", 11, "bold"),
            bg="#c0392b", fg="white",
            activebackground="#e74c3c",
            relief="flat", padx=16, pady=6,
            command=self._toggle_record
        )
        self.btn_rec.pack(side="left", padx=6)

        tk.Button(
            btn_frame, text="✕ Fermer",
            font=("Segoe UI", 10),
            bg="#2a2a2a", fg="white",
            activebackground="#555",
            relief="flat", padx=10, pady=6,
            command=self._close
        ).pack(side="left", padx=6)

        # Statut
        self.status_label = tk.Label(
            self.win, text="Prêt",
            bg="#0f0f0f", fg="#4CAF50",
            font=("Segoe UI", 8)
        )
        self.status_label.pack()

    def _refresh_devices(self):
        """Remplit la liste des périphériques d'entrée."""
        devices = Recorder.list_devices()
        if not devices:
            self.device_combo["values"] = ["Aucun périphérique trouvé"]
            self.device_combo.current(0)
            self._devices_index = []
            return

        self._devices_index = [d[0] for d in devices]
        self.device_combo["values"] = [d[1] for d in devices]

        # Sélectionner le périphérique par défaut
        default = Recorder.get_default_input()
        if default is not None and default in self._devices_index:
            self.device_combo.current(self._devices_index.index(default))
        else:
            self.device_combo.current(0)

    def _get_selected_device(self):
        idx = self.device_combo.current()
        if idx < 0 or not self._devices_index:
            return None
        return self._devices_index[idx]

    def _toggle_record(self):
        if not self.recorder.is_recording:
            self._start_record()
        else:
            self._stop_record()

    def _start_record(self):
        device = self._get_selected_device()
        ok = self.recorder.start(device_index=device)
        if ok:
            self._rec_start = time.time()
            self.btn_rec.config(text="⏹ STOP", bg="#e74c3c")
            self.status_label.config(text="● Enregistrement en cours...", fg="#ff4444")
            self._update_vu()
            self._update_timer()

    def _stop_record(self):
        # Nom du fichier
        name = self.name_var.get().strip()
        if name and not name.endswith(".wav"):
            name += ".wav"
        filepath = self.recorder.stop(filename=name if name else None)

        self.btn_rec.config(text="● REC", bg="#c0392b")
        self.status_label.config(text="Prêt", fg="#4CAF50")
        self.timer_label.config(text="00:00")

        # Annuler les callbacks
        if self._vu_job:
            self.win.after_cancel(self._vu_job)

        if filepath and self.on_recorded:
            duration = self._get_duration(filepath)
            self.on_recorded(filepath, duration)
            self.status_label.config(
                text=f"✔ Sauvegardé : {os.path.basename(filepath)}",
                fg="#4CAF50"
            )

    def _get_duration(self, filepath):
        """Calcule la durée d'un fichier WAV."""
        try:
            with sf.SoundFile(filepath) as f:
                return len(f) / f.samplerate
        except Exception:
            return 4.0

    def _update_vu(self):
        """Met à jour le vumètre en temps réel."""
        if not self.recorder.is_recording:
            return
        level = self.recorder.get_level()
        width = int(200 * level)
        color = "#4CAF50" if level < 0.7 else "#FFC107" if level < 0.9 else "#f44336"
        self.vu_canvas.coords(self.vu_bar, 0, 0, width, 14)
        self.vu_canvas.itemconfig(self.vu_bar, fill=color)
        self._vu_job = self.win.after(50, self._update_vu)

    def _update_timer(self):
        """Affiche le temps d'enregistrement."""
        if not self.recorder.is_recording:
            return
        elapsed = int(time.time() - self._rec_start)
        m, s = divmod(elapsed, 60)
        self.timer_label.config(text=f"{m:02}:{s:02}")
        self.win.after(500, self._update_timer)

    def _close(self):
        if self.recorder.is_recording:
            self._stop_record()
        if self._vu_job:
            self.win.after_cancel(self._vu_job)
        self.win.destroy()
