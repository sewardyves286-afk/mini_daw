"""
exporter.py — Export Mixdown WAV du Mini DAW
Mixe tous les clips de la timeline en un seul fichier WAV.
"""

import os
import threading
import numpy as np
import soundfile as sf

try:
    from pydub import AudioSegment
    PYDUB_OK = True
except ImportError:
    PYDUB_OK = False

import tkinter as tk
from tkinter import filedialog, ttk

SAMPLE_RATE = 44100


def load_audio(filepath, sample_rate=SAMPLE_RATE):
    """Charge un fichier audio en float32 mono."""
    if not os.path.exists(filepath):
        print(f"[Exporter] Fichier introuvable : {filepath}")
        return None

    ext = os.path.splitext(filepath)[1].lower()
    try:
        if ext == ".mp3":
            if not PYDUB_OK:
                print("[Exporter] pydub requis pour MP3")
                return None
            wav_path = filepath.replace(".mp3", "_daw_tmp.wav")
            if not os.path.exists(wav_path):
                seg = AudioSegment.from_mp3(filepath)
                seg = seg.set_frame_rate(sample_rate)
                seg.export(wav_path, format="wav")
            data, sr = sf.read(wav_path, dtype="float32")
        else:
            data, sr = sf.read(filepath, dtype="float32")

        # Stereo → Mono
        if data.ndim == 2:
            data = data.mean(axis=1)

        return data

    except Exception as e:
        print(f"[Exporter] Erreur chargement {filepath} : {e}")
        return None


def mixdown(clips: dict, sample_rate=SAMPLE_RATE, on_progress=None):
    """
    Mixe tous les clips en un tableau numpy stéréo float32.
    Utilise la durée RÉELLE du fichier audio (pas clip["duration"]).
    """
    if not clips:
        return None

    # --- Calcul de la durée totale réelle ---
    total_duration = 0.0
    clips_data = {}  # rect_id -> data numpy

    for rect_id, clip in clips.items():
        fp = clip.get("filepath")
        if not fp:
            continue
        data = load_audio(fp, sample_rate)
        if data is None:
            continue
        clips_data[rect_id] = data
        real_duration = len(data) / sample_rate
        end = clip.get("start", 0.0) + real_duration
        if end > total_duration:
            total_duration = end

    if total_duration <= 0 or not clips_data:
        print("[Exporter] Aucun clip audio valide")
        return None

    total_samples = int(total_duration * sample_rate) + 1024
    mix = np.zeros((total_samples, 2), dtype="float32")

    total = len(clips_data)
    for i, (rect_id, data) in enumerate(clips_data.items()):
        clip   = clips[rect_id]
        start  = clip.get("start", 0.0)
        volume = clip.get("volume", 80) / 100.0
        pan    = 0.0

        start_sample = int(start * sample_rate)
        end_sample   = min(start_sample + len(data), total_samples)
        length       = end_sample - start_sample

        if length <= 0:
            continue

        chunk = data[:length] * volume
        left  = np.sqrt(max(0.0, 0.5 * (1.0 - pan))) * chunk
        right = np.sqrt(max(0.0, 0.5 * (1.0 + pan))) * chunk

        mix[start_sample:end_sample, 0] += left
        mix[start_sample:end_sample, 1] += right

        print(f"[Exporter] Mixé : {os.path.basename(fp)} "
              f"@ {start:.1f}s ({len(data)/sample_rate:.2f}s)")

        if on_progress:
            on_progress(int((i + 1) / total * 90))

    mix = np.clip(mix, -1.0, 1.0)
    if on_progress:
        on_progress(100)

    return mix


def export_wav(clips: dict, output_path: str,
               sample_rate=SAMPLE_RATE, on_progress=None, on_done=None):
    def _run():
        try:
            print(f"[Exporter] Démarrage → {output_path}")
            mix = mixdown(clips, sample_rate, on_progress)
            if mix is None:
                if on_done:
                    on_done(None)
                return
            sf.write(output_path, mix, sample_rate)
            duration = len(mix) / sample_rate
            print(f"[Exporter] ✔ {output_path} ({duration:.1f}s)")
            if on_done:
                on_done(output_path)
        except Exception as e:
            print(f"[Exporter] Erreur : {e}")
            if on_done:
                on_done(None)

    threading.Thread(target=_run, daemon=True).start()


# ================================================
# FENÊTRE D'EXPORT
# ================================================
class ExportWindow:
    def __init__(self, parent, clips: dict):
        self.parent = parent
        self.clips  = clips

        self.win = tk.Toplevel(parent)
        self.win.title("Export Mixdown")
        self.win.configure(bg="#0f0f0f")
        self.win.resizable(False, False)
        self.win.geometry("380x260")
        self.win.grab_set()
        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 16, "pady": 6}

        tk.Label(self.win, text="⬇ EXPORT MIXDOWN WAV",
                 bg="#0f0f0f", fg="#4CAF50",
                 font=("Segoe UI", 11, "bold")).pack(pady=(16, 4))

        n_clips = sum(1 for c in self.clips.values() if c.get("filepath"))
        tk.Label(self.win, text=f"{n_clips} clip(s) audio détecté(s)",
                 bg="#0f0f0f", fg="#888888",
                 font=("Segoe UI", 9)).pack()

        name_frame = tk.Frame(self.win, bg="#0f0f0f")
        name_frame.pack(fill="x", **pad)
        tk.Label(name_frame, text="Nom du fichier :",
                 bg="#0f0f0f", fg="#cccccc",
                 font=("Segoe UI", 9)).pack(anchor="w")

        file_row = tk.Frame(name_frame, bg="#0f0f0f")
        file_row.pack(fill="x", pady=4)
        self.filename_var = tk.StringVar(value="mixdown")
        tk.Entry(file_row, textvariable=self.filename_var,
                 bg="#1e1e1e", fg="white", insertbackground="white",
                 relief="flat", font=("Segoe UI", 10), width=24).pack(side="left")
        tk.Label(file_row, text=".wav", bg="#0f0f0f", fg="#888888",
                 font=("Segoe UI", 10)).pack(side="left", padx=4)
        tk.Button(file_row, text="📁", bg="#2a2a2a", fg="white",
                  relief="flat", font=("Segoe UI", 10),
                  command=self._browse).pack(side="left", padx=4)

        dir_frame = tk.Frame(self.win, bg="#0f0f0f")
        dir_frame.pack(fill="x", padx=16, pady=2)
        tk.Label(dir_frame, text="Dossier :", bg="#0f0f0f", fg="#cccccc",
                 font=("Segoe UI", 9)).pack(anchor="w")
        self.dir_var = tk.StringVar(value=os.path.expanduser("~/Desktop"))
        tk.Label(dir_frame, textvariable=self.dir_var,
                 bg="#1a1a1a", fg="#888888",
                 font=("Segoe UI", 8), anchor="w", width=42).pack(fill="x", pady=2)
        tk.Button(dir_frame, text="Changer le dossier",
                  bg="#2a2a2a", fg="white", relief="flat",
                  font=("Segoe UI", 8),
                  command=self._browse_dir).pack(anchor="w", pady=2)

        self.progress_var = tk.IntVar(value=0)
        ttk.Progressbar(self.win, variable=self.progress_var,
                        maximum=100, length=340).pack(padx=16, pady=8)

        self.status_label = tk.Label(self.win, text="Prêt",
                                     bg="#0f0f0f", fg="#4CAF50",
                                     font=("Segoe UI", 8))
        self.status_label.pack()

        btn_frame = tk.Frame(self.win, bg="#0f0f0f")
        btn_frame.pack(pady=8)
        self.btn_export = tk.Button(
            btn_frame, text="⬇ Exporter",
            font=("Segoe UI", 10, "bold"),
            bg="#4CAF50", fg="white",
            activebackground="#66BB6A",
            relief="flat", padx=16, pady=6,
            command=self._start_export)
        self.btn_export.pack(side="left", padx=6)
        tk.Button(btn_frame, text="✕ Fermer",
                  font=("Segoe UI", 10), bg="#2a2a2a", fg="white",
                  activebackground="#555", relief="flat", padx=10, pady=6,
                  command=self.win.destroy).pack(side="left", padx=6)

    def _browse(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".wav",
            filetypes=[("WAV files", "*.wav")],
            initialfile=self.filename_var.get())
        if path:
            self.dir_var.set(os.path.dirname(path))
            self.filename_var.set(os.path.splitext(os.path.basename(path))[0])

    def _browse_dir(self):
        d = filedialog.askdirectory()
        if d:
            self.dir_var.set(d)

    def _start_export(self):
        name = self.filename_var.get().strip() or "mixdown"
        if not name.endswith(".wav"):
            name += ".wav"
        output_path = os.path.join(self.dir_var.get(), name)

        self.btn_export.config(state="disabled", text="Export en cours...")
        self.status_label.config(text="Mixage en cours...", fg="#FFC107")
        self.progress_var.set(0)

        def on_progress(pct):
            self.win.after(0, lambda: self.progress_var.set(pct))

        def on_done(path):
            def _update():
                if path:
                    self.status_label.config(
                        text=f"✔ Exporté : {os.path.basename(path)}",
                        fg="#4CAF50")
                    self.btn_export.config(state="normal", text="⬇ Exporter")
                    self.progress_var.set(100)
                else:
                    self.status_label.config(text="✗ Erreur export", fg="#f44336")
                    self.btn_export.config(state="normal", text="⬇ Exporter")
            self.win.after(0, _update)

        export_wav(clips=self.clips, output_path=output_path,
                   on_progress=on_progress, on_done=on_done)
