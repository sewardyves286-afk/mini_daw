"""
pattern_editor.py — Séquenceur de patterns (bloc PAT) pour mini_daw
Grille de steps cliquables, lecture synchronisée au BPM, export WAV du pattern.
Dépendances : numpy, sounddevice, soundfile
"""

import os
import time
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
import soundfile as sf

try:
    import sounddevice as sd
    SD_OK = True
except ImportError:
    SD_OK = False

BASE_DIR      = os.path.dirname(__file__)
SAMPLES_DIR   = os.path.join(BASE_DIR, "samples")
PATTERNS_DIR  = os.path.join(BASE_DIR, "samples", "patterns")
os.makedirs(PATTERNS_DIR, exist_ok=True)

SAMPLE_RATE   = 44100
DEFAULT_STEPS = 16

# Couleurs par ligne
ROW_COLORS = [
    "#E24B4A",  # Kick   — rouge
    "#378ADD",  # Snare  — bleu
    "#1D9E75",  # Hi-hat — vert
    "#BA7517",  # Perc   — ambre
    "#534AB7",  # Tom    — violet
    "#D4537E",  # Clap   — rose
    "#0F6E56",  # Open   — teal
    "#993C1D",  # Crash  — coral
]

# ============================================================
# MODÈLE DE PATTERN
# ============================================================
class Pattern:
    """Un pattern = N lignes × M steps."""

    def __init__(self, rows=4, steps=DEFAULT_STEPS, bpm=120):
        self.rows      = rows
        self.steps     = steps
        self.bpm       = bpm
        self.row_names = ["Kick", "Snare", "Hi-hat", "Perc",
                          "Tom", "Clap", "Open HH", "Crash"][:rows]
        self.row_files = [None] * rows   # chemin vers sample WAV
        # grid[row][step] = True/False
        self.grid      = [[False] * steps for _ in range(rows)]
        self.row_vol   = [0.8] * rows    # volume par ligne 0..1

    def toggle(self, row, step):
        self.grid[row][step] = not self.grid[row][step]

    def clear_row(self, row):
        self.grid[row] = [False] * self.steps

    def clear_all(self):
        self.grid = [[False] * self.steps for _ in range(self.rows)]

    def add_row(self):
        if self.rows < len(ROW_COLORS):
            self.rows += 1
            name = self.row_names[self.rows-1] if self.rows <= len(self.row_names) else f"Row {self.rows}"
            self.row_names.append(name)
            self.row_files.append(None)
            self.grid.append([False] * self.steps)
            self.row_vol.append(0.8)

    def to_dict(self):
        return {
            "rows":       self.rows,
            "steps":      self.steps,
            "bpm":        self.bpm,
            "row_names":  self.row_names,
            "row_files":  self.row_files,
            "grid":       self.grid,
            "row_vol":    self.row_vol,
        }

    @classmethod
    def from_dict(cls, d):
        p = cls(rows=d["rows"], steps=d["steps"], bpm=d["bpm"])
        p.row_names = d["row_names"]
        p.row_files = d["row_files"]
        p.grid      = d["grid"]
        p.row_vol   = d.get("row_vol", [0.8]*p.rows)
        return p


# ============================================================
# MOTEUR DE LECTURE DU PATTERN
# ============================================================
class PatternPlayer:
    """Joue un pattern en boucle selon le BPM."""

    def __init__(self):
        self._thread      = None
        self._stop_event  = threading.Event()
        self.playing      = False
        self._on_step_cb  = None   # callback(step_index)
        self._cache       = {}

    def _load_sample(self, fp):
        if fp in self._cache:
            return self._cache[fp]
        if not fp or not os.path.exists(fp):
            return None
        try:
            data, sr = sf.read(fp, dtype="float32")
            if data.ndim == 2:
                data = data.mean(axis=1)
            # Resampler si nécessaire
            if sr != SAMPLE_RATE:
                ratio  = SAMPLE_RATE / sr
                n_out  = int(len(data) * ratio)
                x_old  = np.linspace(0, 1, len(data))
                x_new  = np.linspace(0, 1, n_out)
                data   = np.interp(x_new, x_old, data).astype("float32")
            self._cache[fp] = data
            return data
        except Exception as e:
            print(f"[Pattern] Erreur chargement {os.path.basename(fp)}: {e}")
            return None

    def _make_click(self, freq=600, dur=0.025):
        """Son de substitution si pas de sample."""
        n   = int(SAMPLE_RATE * dur)
        t   = np.linspace(0, dur, n, dtype=np.float32)
        env = np.exp(-t * 80).astype(np.float32)
        return (np.sin(2 * np.pi * freq * t) * env)

    def start(self, pattern: Pattern, on_step=None):
        self.stop()
        if not SD_OK:
            print("[Pattern] sounddevice manquant")
            return
        self._on_step_cb = on_step
        self._stop_event.clear()
        self.playing      = True
        self._thread = threading.Thread(
            target=self._loop, args=(pattern,), daemon=True)
        self._thread.start()
        print(f"[Pattern] ▶ {pattern.bpm} BPM  {pattern.steps} steps")

    def stop(self):
        self._stop_event.set()
        self.playing = False
        try:
            sd.stop()
        except Exception:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)
        print("[Pattern] ⏹ Stop")

    def _loop(self, pattern: Pattern):
        step_sec = 60.0 / pattern.bpm / 4  # noire divisée en 4 = double-croche

        # Pré-charger les samples
        samples = []
        for r in range(pattern.rows):
            fp   = pattern.row_files[r]
            data = self._load_sample(fp)
            if data is None:
                # son par défaut selon la ligne
                freqs = [80, 220, 800, 400, 160, 600, 1000, 300]
                data  = self._make_click(freqs[r % len(freqs)])
            samples.append(data)

        step = 0
        while not self._stop_event.is_set():
            t_start = time.perf_counter()

            # Callback UI
            if self._on_step_cb:
                s = step
                threading.Thread(
                    target=self._on_step_cb, args=(s,), daemon=True).start()

            # Mixer les samples actifs pour ce step
            block_len = int(step_sec * SAMPLE_RATE)
            mix       = np.zeros((block_len, 2), dtype="float32")

            for r in range(pattern.rows):
                if pattern.grid[r][step]:
                    s_data = samples[r]
                    vol    = pattern.row_vol[r]
                    n      = min(len(s_data), block_len)
                    mix[:n, 0] += s_data[:n] * vol
                    mix[:n, 1] += s_data[:n] * vol

            mix = np.clip(mix, -1.0, 1.0)

            try:
                sd.play(mix, SAMPLE_RATE, blocking=False)
            except Exception as e:
                print(f"[Pattern] Erreur play: {e}")

            step = (step + 1) % pattern.steps

            # Attendre jusqu'au prochain step
            elapsed = time.perf_counter() - t_start
            wait    = step_sec - elapsed
            if wait > 0:
                t0 = time.perf_counter()
                while time.perf_counter() - t0 < wait:
                    if self._stop_event.is_set():
                        return
                    time.sleep(0.001)


# ============================================================
# FENÊTRE PATTERN EDITOR
# ============================================================
class PatternEditorWindow:
    """
    Fenêtre complète du séquenceur de pattern.
    on_export(filepath, duration) : callback quand le pattern est exporté en WAV
    """

    CELL_W = 28
    CELL_H = 26
    LABEL_W = 72

    def __init__(self, parent, bpm_var: tk.IntVar = None, on_export=None):
        self.parent     = parent
        self.bpm_var    = bpm_var
        self.on_export  = on_export
        self.pattern    = Pattern(rows=4, steps=16,
                                  bpm=bpm_var.get() if bpm_var else 120)
        self.player     = PatternPlayer()
        self._cells     = []    # liste de Canvas par cellule
        self._step_highlights = []  # Canvas de la colonne active

        self.win = tk.Toplevel(parent)
        self.win.title("mini_daw — Pattern Editor")
        self.win.configure(bg="#0f0f0f")
        self.win.resizable(True, True)

        w = self.LABEL_W + self.pattern.steps * (self.CELL_W + 2) + 120 + 24
        h = 80 + self.pattern.rows * (self.CELL_H + 4) + 120
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        self.win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        try:
            ico = os.path.join(BASE_DIR, "assets", "logo.ico")
            if os.path.exists(ico):
                self.win.iconbitmap(ico)
        except Exception:
            pass

        self.win.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()

    # --------------------------------------------------------
    def _build_ui(self):
        # En-tête
        hdr = tk.Frame(self.win, bg="#0a0a0a")
        hdr.pack(fill="x")
        tk.Label(hdr, text="mini_daw",
                 bg="#0a0a0a", fg="#4CAF50",
                 font=("Segoe UI", 11, "bold")).pack(side="left", padx=12, pady=6)
        tk.Label(hdr, text="Pattern Editor",
                 bg="#0a0a0a", fg="#aaaaaa",
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Frame(self.win, bg="#222222", height=1).pack(fill="x")

        # Barre de contrôle
        ctrl = tk.Frame(self.win, bg="#111111", pady=6)
        ctrl.pack(fill="x", padx=12)

        # BPM (synchronisé avec gui.py)
        tk.Label(ctrl, text="BPM", bg="#111111", fg="#888888",
                 font=("Segoe UI", 8)).pack(side="left")
        self.bpm_local = tk.IntVar(value=self.pattern.bpm)
        if self.bpm_var:
            self.bpm_local.set(self.bpm_var.get())
        tk.Spinbox(ctrl, from_=40, to=300, width=5,
                   textvariable=self.bpm_local,
                   bg="#1e1e1e", fg="#4CAF50",
                   buttonbackground="#2a2a2a",
                   insertbackground="white",
                   relief="flat", font=("Segoe UI", 10, "bold"),
                   command=self._on_bpm_change).pack(side="left", padx=4)

        # Steps
        tk.Label(ctrl, text="Steps", bg="#111111", fg="#888888",
                 font=("Segoe UI", 8)).pack(side="left", padx=(10, 0))
        self.steps_var = tk.IntVar(value=self.pattern.steps)
        for n in [8, 16, 32]:
            tk.Radiobutton(ctrl, text=str(n), variable=self.steps_var, value=n,
                           bg="#111111", fg="white",
                           selectcolor="#333333",
                           activebackground="#111111",
                           font=("Segoe UI", 8),
                           command=self._on_steps_change).pack(side="left")

        # Shuffle
        tk.Label(ctrl, text="Swing", bg="#111111", fg="#888888",
                 font=("Segoe UI", 8)).pack(side="left", padx=(10, 0))
        self.swing_var = tk.IntVar(value=0)
        tk.Scale(ctrl, variable=self.swing_var, from_=0, to=50,
                 orient="horizontal", length=70,
                 bg="#111111", fg="white",
                 troughcolor="#333", highlightthickness=0,
                 showvalue=False).pack(side="left", padx=4)

        # Boutons droite
        self.btn_play = tk.Button(
            ctrl, text="▶ Play",
            font=("Segoe UI", 9, "bold"),
            bg="#4CAF50", fg="white",
            activebackground="#66BB6A",
            relief="flat", padx=10, pady=3,
            cursor="hand2",
            command=self._toggle_play)
        self.btn_play.pack(side="right", padx=4)

        tk.Button(ctrl, text="Clear",
                  bg="#2a2a2a", fg="white",
                  activebackground="#555",
                  relief="flat", padx=8, pady=3,
                  cursor="hand2",
                  font=("Segoe UI", 8),
                  command=self._clear_all).pack(side="right", padx=2)

        tk.Button(ctrl, text="+ Track",
                  bg="#2a2a2a", fg="white",
                  activebackground="#4CAF50",
                  relief="flat", padx=8, pady=3,
                  cursor="hand2",
                  font=("Segoe UI", 8),
                  command=self._add_row).pack(side="right", padx=2)

        tk.Frame(self.win, bg="#222222", height=1).pack(fill="x")

        # Grille scrollable
        self.grid_frame_outer = tk.Frame(self.win, bg="#0f0f0f")
        self.grid_frame_outer.pack(fill="both", expand=True, padx=8, pady=8)

        self.grid_canvas = tk.Canvas(
            self.grid_frame_outer, bg="#0f0f0f",
            highlightthickness=0)
        self.grid_canvas.pack(side="left", fill="both", expand=True)

        self.grid_inner = tk.Frame(self.grid_canvas, bg="#0f0f0f")
        self.grid_canvas.create_window((0, 0), window=self.grid_inner, anchor="nw")
        self.grid_inner.bind("<Configure>",
                             lambda e: self.grid_canvas.configure(
                                 scrollregion=self.grid_canvas.bbox("all")))

        self._build_grid()

        # Barre du bas
        tk.Frame(self.win, bg="#222222", height=1).pack(fill="x")
        bot = tk.Frame(self.win, bg="#0a0a0a", pady=8)
        bot.pack(fill="x", padx=12)

        self.status_lbl = tk.Label(
            bot, text="Ready",
            bg="#0a0a0a", fg="#4CAF50",
            font=("Segoe UI", 8))
        self.status_lbl.pack(side="left")

        tk.Button(bot, text="⬇ Export WAV",
                  bg="#1a1a2e", fg="#4CAF50",
                  activebackground="#4CAF50", activeforeground="white",
                  relief="flat", padx=12, pady=5,
                  cursor="hand2",
                  font=("Segoe UI", 9, "bold"),
                  command=self._export_wav).pack(side="right")

        tk.Button(bot, text="→ Send to Timeline",
                  bg="#00b4d8", fg="white",
                  activebackground="#0077b6",
                  relief="flat", padx=12, pady=5,
                  cursor="hand2",
                  font=("Segoe UI", 9, "bold"),
                  command=self._send_to_timeline).pack(side="right", padx=6)

    # --------------------------------------------------------
    def _build_grid(self):
        """Construit la grille de steps."""
        for w in self.grid_inner.winfo_children():
            w.destroy()
        self._cells = []
        self._step_highlights = []

        steps = self.pattern.steps

        # En-tête numéros de steps
        hdr_row = tk.Frame(self.grid_inner, bg="#0f0f0f")
        hdr_row.pack(fill="x", pady=(0, 2))
        tk.Label(hdr_row, width=self.LABEL_W // 7 + 2,
                 bg="#0f0f0f").pack(side="left")
        for s in range(steps):
            color = "#555555" if (s % 4 == 0) else "#333333"
            lbl = tk.Label(hdr_row,
                           text=str(s+1) if s % 4 == 0 else "",
                           bg="#0f0f0f", fg=color,
                           font=("Segoe UI", 7),
                           width=self.CELL_W // 7)
            lbl.pack(side="left", padx=1)

        # Lignes de pistes
        for r in range(self.pattern.rows):
            row_cells = []
            color = ROW_COLORS[r % len(ROW_COLORS)]

            row_frame = tk.Frame(self.grid_inner, bg="#0f0f0f")
            row_frame.pack(fill="x", pady=1)

            # Label + boutons de la ligne
            lbl_frame = tk.Frame(row_frame,
                                 bg="#1a1a1a", width=self.LABEL_W)
            lbl_frame.pack(side="left", padx=(0, 4))
            lbl_frame.pack_propagate(False)

            tk.Label(lbl_frame,
                     text=self.pattern.row_names[r],
                     bg="#1a1a1a", fg="white",
                     font=("Segoe UI", 8, "bold"),
                     anchor="w").pack(side="left", padx=4)

            # Bouton sample
            tk.Button(lbl_frame, text="S",
                      bg="#2a2a2a", fg="#888888",
                      relief="flat", font=("Segoe UI", 7),
                      padx=2, pady=0,
                      cursor="hand2",
                      command=lambda ri=r: self._pick_sample(ri)
                      ).pack(side="right", padx=2)

            # Volume de la ligne
            vol_var = tk.DoubleVar(value=self.pattern.row_vol[r])
            tk.Scale(lbl_frame, variable=vol_var,
                     from_=0, to=1, resolution=0.05,
                     orient="horizontal", length=30,
                     bg="#1a1a1a", troughcolor="#333",
                     highlightthickness=0, showvalue=False,
                     command=lambda v, ri=r: self._set_row_vol(ri, float(v))
                     ).pack(side="right")

            # Cellules de steps
            for s in range(steps):
                is_active = self.pattern.grid[r][s]
                bg_off = "#222222" if (s // 4) % 2 == 0 else "#1a1a1a"
                bg = color if is_active else bg_off

                cell = tk.Canvas(row_frame,
                                 width=self.CELL_W, height=self.CELL_H,
                                 bg=bg, highlightthickness=0,
                                 cursor="hand2")
                cell.pack(side="left", padx=1)
                cell.bind("<ButtonPress-1>",
                          lambda e, ri=r, si=s: self._toggle_cell(ri, si))
                row_cells.append((cell, bg_off))

            self._cells.append(row_cells)

    # --------------------------------------------------------
    def _toggle_cell(self, row, step):
        self.pattern.toggle(row, step)
        cell, bg_off = self._cells[row][step]
        color = ROW_COLORS[row % len(ROW_COLORS)]
        bg = color if self.pattern.grid[row][step] else bg_off
        cell.config(bg=bg)

    def _set_row_vol(self, row, val):
        self.pattern.row_vol[row] = val

    def _pick_sample(self, row):
        fp = filedialog.askopenfilename(
            title=f"Sample pour {self.pattern.row_names[row]}",
            initialdir=SAMPLES_DIR,
            filetypes=[("Audio", "*.wav *.mp3 *.flac *.ogg"), ("Tous", "*.*")])
        if fp:
            self.pattern.row_files[row] = fp
            self.player._cache.pop(fp, None)
            self._set_status(
                f"Sample chargé : {os.path.basename(fp)}", "#4CAF50")

    def _on_bpm_change(self):
        self.pattern.bpm = self.bpm_local.get()
        if self.bpm_var:
            self.bpm_var.set(self.pattern.bpm)

    def _on_steps_change(self):
        n = self.steps_var.get()
        # Adapter la grille
        for r in range(self.pattern.rows):
            if n > len(self.pattern.grid[r]):
                self.pattern.grid[r].extend(
                    [False] * (n - len(self.pattern.grid[r])))
            else:
                self.pattern.grid[r] = self.pattern.grid[r][:n]
        self.pattern.steps = n
        was_playing = self.player.playing
        if was_playing:
            self.player.stop()
        self._build_grid()
        if was_playing:
            self.player.start(self.pattern, on_step=self._on_step)

    def _add_row(self):
        if self.pattern.rows >= len(ROW_COLORS):
            messagebox.showinfo("Maximum", "Maximum 8 tracks per pattern.")
            return
        self.pattern.add_row()
        self._cells.append([])
        self._build_grid()

    def _clear_all(self):
        self.pattern.clear_all()
        self._build_grid()

    # --------------------------------------------------------
    # LECTURE
    # --------------------------------------------------------
    def _toggle_play(self):
        if self.player.playing:
            self.player.stop()
            self.btn_play.config(text="▶ Play", bg="#4CAF50")
            self._clear_highlights()
        else:
            self.pattern.bpm = self.bpm_local.get()
            self.player.start(self.pattern, on_step=self._on_step)
            self.btn_play.config(text="⏹ Stop", bg="#c0392b")

    def _on_step(self, step):
        """Flash de la colonne active."""
        def _update():
            self._clear_highlights()
            for r in range(len(self._cells)):
                if step < len(self._cells[r]):
                    cell, bg_off = self._cells[r][step]
                    if not self.pattern.grid[r][step]:
                        cell.config(bg="#555555")
        try:
            self.win.after(0, _update)
        except Exception:
            pass

    def _clear_highlights(self):
        for r, row_cells in enumerate(self._cells):
            for s, (cell, bg_off) in enumerate(row_cells):
                color = ROW_COLORS[r % len(ROW_COLORS)]
                bg = color if self.pattern.grid[r][s] else bg_off
                try:
                    cell.config(bg=bg)
                except Exception:
                    pass

    # --------------------------------------------------------
    # EXPORT WAV
    # --------------------------------------------------------
    def _render_pattern(self):
        """Rend le pattern en numpy array stéréo."""
        steps    = self.pattern.steps
        bpm      = self.pattern.bpm
        step_sec = 60.0 / bpm / 4
        total_sec = steps * step_sec
        total_smp = int(total_sec * SAMPLE_RATE) + SAMPLE_RATE
        mix       = np.zeros((total_smp, 2), dtype="float32")

        for r in range(self.pattern.rows):
            fp   = self.pattern.row_files[r]
            data = self.player._load_sample(fp)
            if data is None:
                freqs = [80, 220, 800, 400, 160, 600, 1000, 300]
                data  = self.player._make_click(freqs[r % len(freqs)])
            vol = self.pattern.row_vol[r]
            for s in range(steps):
                if self.pattern.grid[r][s]:
                    offset = int(s * step_sec * SAMPLE_RATE)
                    n      = min(len(data), total_smp - offset)
                    mix[offset:offset+n, 0] += data[:n] * vol
                    mix[offset:offset+n, 1] += data[:n] * vol

        return np.clip(mix, -1.0, 1.0)

    def _export_wav(self):
        path = filedialog.asksaveasfilename(
            title="Exporter le pattern",
            initialdir=PATTERNS_DIR,
            initialfile="pattern.wav",
            defaultextension=".wav",
            filetypes=[("WAV", "*.wav")])
        if not path:
            return

        self._set_status("Rendering...", "#FFC107")

        def _run():
            try:
                mix = self._render_pattern()
                sf.write(path, mix, SAMPLE_RATE)
                dur = len(mix) / SAMPLE_RATE
                print(f"[Pattern] ✔ Exporté : {path} ({dur:.2f}s)")
                self.win.after(0, lambda: self._set_status(
                    f"✔ Exporté : {os.path.basename(path)}", "#4CAF50"))
                if self.on_export:
                    self.win.after(0, lambda: self.on_export(path, dur))
            except Exception as e:
                self.win.after(0, lambda: self._set_status(
                    f"✗ Erreur : {e}", "#f44336"))

        threading.Thread(target=_run, daemon=True).start()

    def _send_to_timeline(self):
        """Rend le pattern et l'envoie directement sur la timeline."""
        import time as _t
        ts   = int(_t.time())
        path = os.path.join(PATTERNS_DIR, f"pattern_{ts}.wav")
        self._set_status("Rendu...", "#FFC107")

        def _run():
            try:
                mix = self._render_pattern()
                sf.write(path, mix, SAMPLE_RATE)
                dur = len(mix) / SAMPLE_RATE
                print(f"[Pattern] ✔ Envoyé : {path} ({dur:.2f}s)")
                self.win.after(0, lambda: self._set_status(
                    "✔ Clip ajouté sur la timeline !", "#4CAF50"))
                if self.on_export:
                    self.win.after(0, lambda: self.on_export(path, dur))
            except Exception as e:
                self.win.after(0, lambda: self._set_status(
                    f"✗ {e}", "#f44336"))

        threading.Thread(target=_run, daemon=True).start()

    def _set_status(self, msg, color="#4CAF50"):
        try:
            self.status_lbl.config(text=msg, fg=color)
        except Exception:
            pass

    def _on_close(self):
        self.player.stop()
        self.win.destroy()
