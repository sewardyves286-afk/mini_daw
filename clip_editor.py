"""
clip_editor.py — Éditeur audio intégré au Mini DAW
Transport Play/Stop/Rec, playhead temps réel, effets DSP, découpe, apply to timeline.
Les boutons d'action sont TOUJOURS visibles en bas fixe.
"""

import os
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np
import soundfile as sf

# scipy remplacé par numpy pur (compatibilité PyInstaller)
SCIPY_OK = False  # numpy seulement


def _stft_numpy(x, n_fft=1024, hop=256):
    """STFT numpy pur."""
    frames = (len(x) - n_fft) // hop + 1
    Z = np.zeros((n_fft // 2 + 1, max(1, frames)), dtype=np.complex64)
    win = np.hanning(n_fft).astype(np.float32)
    for i in range(max(1, frames)):
        seg = x[i*hop: i*hop + n_fft]
        if len(seg) < n_fft:
            seg = np.pad(seg, (0, n_fft - len(seg)))
        Z[:, i] = np.fft.rfft(seg * win)
    return Z


def _istft_numpy(Z, n_fft=1024, hop=256, length=None):
    """ISTFT numpy pur (OLA)."""
    frames = Z.shape[1]
    out_len = (frames - 1) * hop + n_fft
    out = np.zeros(out_len, dtype=np.float32)
    win = np.hanning(n_fft).astype(np.float32)
    for i in range(frames):
        seg = np.fft.irfft(Z[:, i], n=n_fft).real * win
        out[i*hop: i*hop + n_fft] += seg
    if length:
        out = out[:length]
    return out


def _fftconvolve_numpy(a, b):
    """Convolution via FFT numpy pur."""
    n = len(a) + len(b) - 1
    fa = np.fft.rfft(a, n=n)
    fb = np.fft.rfft(b, n=n)
    return np.fft.irfft(fa * fb, n=n).real.astype(np.float32)

try:
    import sounddevice as sd
    SD_OK = True
except ImportError:
    SD_OK = False

SAMPLE_RATE = 44100
EDITED_DIR  = os.path.join(os.path.dirname(__file__), "samples", "edited")
os.makedirs(EDITED_DIR, exist_ok=True)


# ============================================================
# DSP
# ============================================================

def load_mono(filepath):
    data, sr = sf.read(filepath, dtype="float32")
    if data.ndim == 2:
        data = data.mean(axis=1)
    return data, sr


def apply_reverb(data, sr, room=0.5, damping=0.5, wet=0.4):
    """Reverb via convolution numpy pur."""
    ir_len = int(sr * max(0.01, room) * 2)
    t      = np.linspace(0, 1, ir_len)
    decay  = np.exp(-damping * 6 * t)
    ir     = (np.random.randn(ir_len) * decay).astype("float32")
    ir[0]  = 1.0
    rev    = _fftconvolve_numpy(data, ir)[:len(data)]
    rev    = rev / (np.max(np.abs(rev)) + 1e-9)
    return np.clip((1 - wet) * data + wet * rev.astype("float32"), -1, 1)


def apply_delay(data, sr, delay_ms=300, feedback=0.4, mix=0.5):
    delay_smp = int(max(10, delay_ms) / 1000.0 * sr)
    out = data.copy()
    buf = np.zeros(delay_smp, dtype="float32")
    for i in range(len(out)):
        idx      = i % delay_smp
        delayed  = buf[idx]
        buf[idx] = out[i] + delayed * max(0.0, min(0.95, feedback))
        out[i]   = out[i] * (1 - mix) + delayed * mix
    return np.clip(out, -1, 1)


def apply_pitch(data, sr, semitones=0):
    if semitones == 0:
        return data
    factor  = 2 ** (semitones / 12.0)
    n_out   = int(len(data) / factor)
    shifted = np.interp(
        np.linspace(0, 1, n_out),
        np.linspace(0, 1, len(data)), data).astype("float32")
    return np.interp(
        np.linspace(0, 1, len(data)),
        np.linspace(0, 1, len(shifted)), shifted).astype("float32")


def apply_noise_reduction(data, sr, strength=0.8):
    """Noise reduction via STFT numpy pur."""
    noise_len = min(int(sr * 0.2), len(data) // 4)
    noise_ref = data[:max(noise_len, 1)]
    n_fft = 1024
    hop   = n_fft // 4
    Zxx    = _stft_numpy(data,      n_fft=n_fft, hop=hop)
    Znoise = _stft_numpy(noise_ref, n_fft=n_fft, hop=hop)
    noise_p   = np.mean(np.abs(Znoise), axis=1, keepdims=True)
    Zxx_clean = (np.maximum(np.abs(Zxx) - noise_p * strength, 0)
                 * np.exp(1j * np.angle(Zxx)))
    out = _istft_numpy(Zxx_clean, n_fft=n_fft, hop=hop, length=len(data))
    return np.clip(out.astype("float32"), -1, 1)


# ============================================================
# ÉDITEUR
# ============================================================

class ClipEditorWindow:
    def __init__(self, parent, clip_data: dict, on_updated=None):
        self.parent     = parent
        self.clip       = clip_data
        self.on_updated = on_updated

        fp = clip_data.get("filepath")
        if not fp or not os.path.exists(fp):
            messagebox.showerror("Error", f"Fichier introuvable :\n{fp}")
            return

        self.filepath  = fp
        self.data, self.sr = load_mono(fp)
        self.orig_data = self.data.copy()
        self.duration  = len(self.data) / self.sr

        # Transport
        self._is_playing   = False
        self._is_recording = False
        self._play_start   = 0.0
        self._play_offset  = 0.0
        self._ph_pos       = 0.0
        self._stop_event   = threading.Event()
        self._rec_frames   = []

        self.win = tk.Toplevel(parent)
        self.win.title(f"mini_daw — Éditeur : {clip_data.get('label','clip')}")
        self.win.configure(bg="#0f0f0f")
        self.win.resizable(True, True)
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        # Taille adaptée à l'écran
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        w  = min(660, sw - 40)
        h  = min(int(sh * 0.88), sh - 60)
        self.win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self.win.minsize(580, 500)

        try:
            ico = os.path.join(os.path.dirname(__file__), "assets", "logo.ico")
            if os.path.exists(ico):
                self.win.iconbitmap(ico)
        except Exception:
            pass

        self._build_ui()
        self.win.after(100, lambda: self._draw_waveform(self.data))

    # ============================================================
    # LAYOUT : header + content scrollable + footer FIXE
    # ============================================================
    def _build_ui(self):
        # ── En-tête fixe ──────────────────────────────────────
        hdr = tk.Frame(self.win, bg="#0a0a0a")
        hdr.pack(fill="x", side="top")

        tk.Label(hdr, text="mini_daw",
                 bg="#0a0a0a", fg="#4CAF50",
                 font=("Segoe UI", 11, "bold")).pack(side="left", padx=12, pady=6)
        tk.Label(hdr, text=f"✂  {self.clip.get('label','')}",
                 bg="#0a0a0a", fg="#aaaaaa",
                 font=("Segoe UI", 9)).pack(side="left")
        self.dur_label = tk.Label(hdr, text=f"{self.duration:.2f}s",
                                   bg="#0a0a0a", fg="#555",
                                   font=("Segoe UI", 8))
        self.dur_label.pack(side="right", padx=12)
        tk.Frame(self.win, bg="#222222", height=1).pack(fill="x", side="top")

        # ── Pied de page fixe (toujours visible) ──────────────
        footer = tk.Frame(self.win, bg="#0d1a2a")
        footer.pack(fill="x", side="bottom")

        tk.Frame(footer, bg="#00b4d8", height=2).pack(fill="x")

        # Progression + statut dans le footer
        self.progress_var = tk.IntVar(value=0)
        ttk.Progressbar(footer, variable=self.progress_var,
                        maximum=100).pack(fill="x", padx=12, pady=(6, 2))

        self.status_lbl = tk.Label(footer,
                                    text="Prêt  —  ▶ Preview → ✔ Appliquer → ⬆ Timeline",
                                    bg="#0d1a2a", fg="#4CAF50",
                                    font=("Segoe UI", 8))
        self.status_lbl.pack(anchor="w", padx=14, pady=(0, 4))

        tk.Frame(footer, bg="#1a2a3a", height=1).pack(fill="x")

        btn_bar = tk.Frame(footer, bg="#0d1a2a", pady=8)
        btn_bar.pack(fill="x", padx=8)

        def _lighten(c):
            try:
                r = min(255, int(c[1:3],16)+25)
                g = min(255, int(c[3:5],16)+25)
                b = min(255, int(c[5:7],16)+25)
                return f"#{r:02x}{g:02x}{b:02x}"
            except Exception:
                return c

        def _pill(parent, text, bg, fg, cmd, store=None):
            """
            Bouton pill avec vrais coins arrondis via create_arc.
            Rendu stable même avant affichage car largeur calculée
            immédiatement sans winfo_reqwidth().
            """
            # Estimer la largeur d'après la longueur du texte
            W = max(60, len(text) * 7 + 26)
            H = 26
            R = 13   # rayon des coins = H/2 → capsule parfaite

            cv = tk.Canvas(parent, width=W, height=H,
                           highlightthickness=0, bg="#0a0a0a",
                           cursor="hand2")
            cv.pack(side="left", padx=3, pady=3)

            def _draw(color=bg):
                cv.delete("all")
                # Corps central
                cv.create_rectangle(R, 0, W-R, H,
                                    fill=color, outline="")
                # Demi-cercle gauche
                cv.create_arc(0, 0, R*2, H,
                              start=90, extent=180,
                              fill=color, outline="", style="pieslice")
                # Demi-cercle droit
                cv.create_arc(W-R*2, 0, W, H,
                              start=270, extent=180,
                              fill=color, outline="", style="pieslice")
                # Texte centré
                cv.create_text(W//2, H//2, text=text, fill=fg,
                               font=("Segoe UI", 8, "bold"), anchor="center")

            _draw()
            cv.bind("<ButtonPress-1>",   lambda e: (_draw("#3a3a3a"), cmd()))
            cv.bind("<ButtonRelease-1>", lambda e: _draw(bg))
            cv.bind("<Enter>",           lambda e: _draw(_lighten(bg)))
            cv.bind("<Leave>",           lambda e: _draw(bg))
            if store is not None:
                store[0] = cv
                store[1] = _draw
            cv._set_color = _draw
            return cv

        _pill(btn_bar, "▶ Preview",   "#0d3b4f", "#00b4d8", self._preview_fx)

        _apply_ref = [None, None]
        _pill(btn_bar, "✔ Appliquer", "#FFC107", "#0a0a0a",
              self._apply_fx_to_data, store=_apply_ref)
        self._btn_apply_cv  = _apply_ref[0]
        self._btn_apply_draw = _apply_ref[1]

        _send_ref = [None, None]
        _pill(btn_bar, "⬆ Timeline",  "#4CAF50", "white",
              self._send_to_timeline, store=_send_ref)
        self._btn_send_cv   = _send_ref[0]
        self._btn_send_draw = _send_ref[1]

        _pill(btn_bar, "↺ Reset",     "#1e1e1e", "#888888", self._reset_audio)
        _pill(btn_bar, "✕ Fermer",    "#2a2a2a", "white",   self._on_close)

        # Compatibilité : btn_apply_fx et btn_send pointent sur les canvas
        self.btn_apply_fx = type("Btn", (), {
            "config": lambda self_, **kw: None,
            "configure": lambda self_, **kw: None,
        })()
        self.btn_send = type("Btn", (), {
            "config": lambda self_, **kw: None,
            "configure": lambda self_, **kw: None,
        })()

        # ── Zone centrale scrollable ───────────────────────────
        outer = tk.Frame(self.win, bg="#0f0f0f")
        outer.pack(fill="both", expand=True, side="top")

        scroll_canvas = tk.Canvas(outer, bg="#0f0f0f",
                                   highlightthickness=0)
        vscroll = tk.Scrollbar(outer, orient="vertical",
                               command=scroll_canvas.yview)
        scroll_canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side="right", fill="y")
        scroll_canvas.pack(side="left", fill="both", expand=True)

        self.content = tk.Frame(scroll_canvas, bg="#0f0f0f")
        self._scroll_win_id = scroll_canvas.create_window(
            (0, 0), window=self.content, anchor="nw")

        self.content.bind("<Configure>", lambda e: scroll_canvas.configure(
            scrollregion=scroll_canvas.bbox("all")))
        scroll_canvas.bind("<Configure>", lambda e: scroll_canvas.itemconfig(
            self._scroll_win_id, width=e.width))

        # Mousewheel — bind local uniquement (évite pollution fenêtre principale)
        def _on_mousewheel(e):
            scroll_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        scroll_canvas.bind("<MouseWheel>", _on_mousewheel)

        self._build_content(self.content)

    # ============================================================
    # CONTENU SCROLLABLE
    # ============================================================
    def _build_content(self, parent):

        # --- TRANSPORT compact arrondi ---
        transport = tk.Frame(parent, bg="#0d0d0d", pady=4)
        transport.pack(fill="x", padx=0)

        def _lighten_t(c):
            try:
                return "#{:02x}{:02x}{:02x}".format(
                    min(255,int(c[1:3],16)+20),
                    min(255,int(c[3:5],16)+20),
                    min(255,int(c[5:7],16)+20))
            except Exception:
                return c

        def _round_btn_e(par, text, bg, fg, cmd, size=30, r=10):
            """Bouton carré à coins arrondis via create_arc."""
            cv = tk.Canvas(par, width=size, height=size,
                           bg="#0d0d0d", highlightthickness=0, cursor="hand2")
            def _draw(color=bg):
                cv.delete("all")
                # Corps
                cv.create_rectangle(r, 0, size-r, size, fill=color, outline="")
                cv.create_rectangle(0, r, size, size-r, fill=color, outline="")
                # 4 coins arrondis via arc
                cv.create_arc(0,        0,        r*2, r*2,
                              start=90,  extent=90, fill=color, outline="", style="pieslice")
                cv.create_arc(size-r*2, 0,        size, r*2,
                              start=0,   extent=90, fill=color, outline="", style="pieslice")
                cv.create_arc(0,        size-r*2, r*2, size,
                              start=180, extent=90, fill=color, outline="", style="pieslice")
                cv.create_arc(size-r*2, size-r*2, size, size,
                              start=270, extent=90, fill=color, outline="", style="pieslice")
                cv.create_text(size//2, size//2, text=text, fill=fg,
                               font=("Segoe UI", 10))
            _draw()
            cv.bind("<ButtonPress-1>",   lambda e: (_draw("#444"), cmd()))
            cv.bind("<ButtonRelease-1>", lambda e: _draw(bg))
            cv.bind("<Enter>",           lambda e: _draw(_lighten_t(bg)))
            cv.bind("<Leave>",           lambda e: _draw(bg))
            cv._set_color = lambda c: _draw(c)
            return cv

        self.btn_stop_t = _round_btn_e(transport,"⏹","#2a2a2a","white",
                                        self._transport_stop)
        self.btn_stop_t.pack(side="left", padx=(10,3), pady=4)

        self.btn_play_t = _round_btn_e(transport,"▶","#4CAF50","white",
                                        self._transport_play)
        self.btn_play_t.pack(side="left", padx=3, pady=4)

        self.btn_rec_t  = _round_btn_e(transport,"●","#c0392b","white",
                                        self._transport_rec)
        self.btn_rec_t.pack(side="left", padx=3, pady=4)

        self.timer_lbl = tk.Label(
            transport, text="00:00.000",
            bg="#0d0d0d", fg="#cccccc",
            font=("Consolas", 9))
        self.timer_lbl.pack(side="left", padx=12)

        tk.Frame(parent, bg="#222222", height=1).pack(fill="x")

        # --- WAVEFORM scrollable + règle des mesures ---
        wf_frame = tk.Frame(parent, bg="#111111")
        wf_frame.pack(fill="both", expand=True, padx=12, pady=6)

        tk.Label(wf_frame,
                 text="Waveform — clic pour repositionner · glisser pour sélectionner · molette pour zoomer",
                 bg="#111111", fg="#444444",
                 font=("Segoe UI", 7)).pack(anchor="w", padx=4)

        # Règle des mesures (temps)
        self.ruler_canvas = tk.Canvas(wf_frame, bg="#0a0a0a",
                                       height=18, highlightthickness=0)
        self.ruler_canvas.pack(fill="x", padx=4, pady=(2,0))

        # Waveform dans un frame avec scrollbar horizontale
        wf_inner = tk.Frame(wf_frame, bg="#111111")
        wf_inner.pack(fill="both", expand=True, padx=4, pady=(0,0))

        self.wf_canvas = tk.Canvas(wf_inner, bg="#111111",
                                    height=160, highlightthickness=0,
                                    cursor="crosshair")
        self.wf_canvas.pack(fill="both", expand=True, side="top")

        wf_hscroll = tk.Scrollbar(wf_frame, orient="horizontal",
                                   command=self._wf_scroll_x)
        wf_hscroll.pack(fill="x", padx=4, pady=(0,2))
        self._wf_hscroll    = wf_hscroll
        self._wf_zoom_px    = 100   # pixels par seconde dans la waveform
        self._wf_offset_px  = 0     # décalage horizontal en pixels
        self._wf_total_px   = 100   # largeur totale de la waveform zoomée

        self.wf_canvas.bind("<ButtonPress-1>",   self._wf_press)
        self.wf_canvas.bind("<B1-Motion>",        self._wf_drag)
        self.wf_canvas.bind("<ButtonRelease-1>",  self._wf_release)
        self.wf_canvas.bind("<MouseWheel>",       self._wf_zoom)

        self._sel_x0       = self._sel_x1 = None
        self._sel_rect     = None
        self._dragging_sel = False

        self.sel_label = tk.Label(wf_frame, text="Aucune sélection",
                                   bg="#111111", fg="#666666",
                                   font=("Segoe UI", 8))
        self.sel_label.pack(anchor="w", padx=4, pady=(0, 4))

        # --- DÉCOUPE ---
        cut_frame = tk.Frame(parent, bg="#0f0f0f")
        cut_frame.pack(fill="x", padx=12, pady=4)

        tk.Label(cut_frame, text="✂  Découpe :",
                 bg="#0f0f0f", fg="#cccccc",
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 8))

        def _cut_pill(par, text, color, cmd):
            W = max(60, len(text)*7+26); H=24; R=12
            cv = tk.Canvas(par, width=W, height=H,
                           highlightthickness=0, bg="#0f0f0f", cursor="hand2")
            cv.pack(side="left", padx=4)
            def _d(c=color):
                cv.delete("all")
                cv.create_rectangle(R,0,W-R,H,fill=c,outline="")
                cv.create_rectangle(0,R//2,W,H-R//2,fill=c,outline="")
                cv.create_arc(0,0,R*2,H,start=90,extent=180,
                              fill=c,outline="",style="pieslice")
                cv.create_arc(W-R*2,0,W,H,start=270,extent=180,
                              fill=c,outline="",style="pieslice")
                cv.create_text(W//2,H//2,text=text,fill="white",
                               font=("Segoe UI",7,"bold"),anchor="center")
            _d()
            cv.bind("<ButtonPress-1>",   lambda e: (_d("#555"),cmd()))
            cv.bind("<ButtonRelease-1>", lambda e: _d(color))
            cv.bind("<Enter>", lambda e: _d(
                "#{:02x}{:02x}{:02x}".format(
                    min(255,int(color[1:3],16)+20),
                    min(255,int(color[3:5],16)+20),
                    min(255,int(color[5:7],16)+20))))
            cv.bind("<Leave>", lambda e: _d(color))
        _cut_pill(cut_frame,"✂ Garder",   "#2a7a4f", self._cut_keep)
        _cut_pill(cut_frame,"✂ Supprimer","#7a2a2a", self._cut_remove)

        tk.Frame(parent, bg="#1e1e1e", height=1).pack(fill="x", padx=12, pady=4)

        # --- EFFETS ---
        eff_row = tk.Frame(parent, bg="#0f0f0f")
        eff_row.pack(fill="x", padx=12)
        tk.Label(eff_row, text="🎛  Effets",
                 bg="#0f0f0f", fg="#00b4d8",
                 font=("Segoe UI", 10, "bold")).pack(side="left", pady=(4, 6))

        self._fx_vars = {}
        fx_container = tk.Frame(parent, bg="#0f0f0f")
        fx_container.pack(fill="x", padx=12)

        self._build_fx_section(fx_container, "🔇 Noise Reduction", "nr", [
            ("Intensité",    "nr_strength", 0,   100, 70),
        ])
        self._build_fx_section(fx_container, "🏛 Reverb", "reverb", [
            ("Taille salle", "rv_room",     0,   100, 50),
            ("Damping",      "rv_damp",     0,   100, 50),
            ("Mix wet",      "rv_wet",      0,   100, 40),
        ])
        self._build_fx_section(fx_container, "🔁 Echo / Delay", "delay", [
            ("Délai (ms)",   "dl_ms",       10,  800, 300),
            ("Feedback",     "dl_fb",       0,   95,  40),
            ("Mix",          "dl_mix",      0,   100, 50),
        ])
        self._build_fx_section(fx_container, "🎵 Pitch Shift", "pitch", [
            ("Demi-tons",    "pt_semi",    -12,   12,  0),
        ])

        # Espace en bas pour le scroll
        tk.Frame(parent, bg="#0f0f0f", height=20).pack()

    # ============================================================
    # FX SECTIONS
    # ============================================================
    def _build_fx_section(self, parent, title, key, params):
        frame = tk.Frame(parent, bg="#141414")
        frame.pack(fill="x", pady=2)

        header = tk.Frame(frame, bg="#1a1a1a")
        header.pack(fill="x")

        var_en = tk.BooleanVar(value=False)
        self._fx_vars[f"{key}_en"] = var_en

        tk.Checkbutton(header, text=title, variable=var_en,
                       bg="#1a1a1a", fg="white",
                       selectcolor="#333",
                       activebackground="#1a1a1a",
                       font=("Segoe UI", 9, "bold"),
                       command=lambda k=key: self._toggle_fx(k)
                       ).pack(side="left", padx=8, pady=3)

        sliders = tk.Frame(frame, bg="#141414")
        sliders.pack(fill="x", padx=20)
        self._fx_vars[f"{key}_sliders"] = sliders

        for label, var_key, mn, mx, default in params:
            row = tk.Frame(sliders, bg="#141414")
            row.pack(fill="x", pady=1)
            tk.Label(row, text=label, bg="#141414", fg="#888888",
                     font=("Segoe UI", 7), width=12,
                     anchor="w").pack(side="left")
            var = tk.IntVar(value=default)
            self._fx_vars[var_key] = var
            tk.Label(row, textvariable=var, bg="#141414", fg="#4CAF50",
                     font=("Segoe UI", 7), width=4).pack(side="right")
            # Slider arrondi via Canvas (style track compact)
            self._make_fx_slider(row, var, mn, mx)

        self._toggle_fx(key)

    def _toggle_fx(self, key):
        enabled = self._fx_vars[f"{key}_en"].get()
        frame   = self._fx_vars[f"{key}_sliders"]
        state   = "normal" if enabled else "disabled"
        for child in frame.winfo_children():
            for w in child.winfo_children():
                try:
                    w.config(state=state)
                except Exception:
                    pass

    def _make_fx_slider(self, parent, var, mn, mx, color="#00b4d8"):
        """Slider compact arrondi identique aux sliders Vol/Pan des pistes."""
        LENGTH = 120
        H      = 14
        cv = tk.Canvas(parent, width=LENGTH, height=H,
                       bg="#141414", highlightthickness=0, cursor="hand2")
        cv.pack(side="left", padx=4)
        r = H // 2

        def _draw(val=None):
            cv.delete("all")
            pct   = (var.get() - mn) / max(1, mx - mn)
            track_y = H // 2
            # Track fond arrondi
            cv.create_line(r, track_y, LENGTH-r, track_y,
                           fill="#333333", width=5, capstyle="round")
            # Track rempli
            fill_x = r + pct * (LENGTH - 2*r)
            if fill_x > r:
                cv.create_line(r, track_y, fill_x, track_y,
                               fill=color, width=5, capstyle="round")
            # Thumb circulaire
            tx = int(r + pct * (LENGTH - 2*r))
            cv.create_oval(tx-r+1, 1, tx+r-1, H-1,
                           fill="white", outline="#888888")

        def _click(e):
            pct = max(0.0, min(1.0, e.x / LENGTH))
            var.set(int(mn + pct * (mx - mn)))
            _draw()

        cv.bind("<ButtonPress-1>", _click)
        cv.bind("<B1-Motion>",     _click)
        var.trace_add("write", lambda *_: _draw())
        _draw()
        return cv

    # ============================================================
    # WAVEFORM
    # ============================================================
    def _draw_waveform(self, data, color="#00b4d8"):
        self._wf_data = data   # garder pour redessiner au scroll/zoom
        self.wf_canvas.update_idletasks()
        W = self.wf_canvas.winfo_width() or 600
        H = max(100, self.wf_canvas.winfo_height() or 160)
        sr  = self.sr
        n   = len(data)
        dur = max(0.001, self.duration)

        # Pixels par seconde selon zoom
        pps = self._wf_zoom_px
        self._wf_total_px = int(dur * pps)
        off = self._wf_offset_px

        # Mettre à jour la scrollbar
        try:
            visible_frac = min(1.0, W / max(self._wf_total_px, W))
            start_frac   = off / max(self._wf_total_px - W, 1)
            self._wf_hscroll.set(start_frac,
                                 start_frac + visible_frac)
        except Exception:
            pass

        self.wf_canvas.delete("waveform")
        self.wf_canvas.create_rectangle(0, 0, W, H,
                                         fill="#0d0d0d", outline="",
                                         tags="waveform")
        mid  = H // 2
        # Dessiner seulement la portion visible
        t0   = off / pps
        t1   = (off + W) / pps
        i0   = max(0, int(t0 * sr))
        i1   = min(n, int(t1 * sr) + 1)

        if i1 > i0 and W > 0:
            seg_w    = max(1, (i1 - i0) // W)
            for px in range(W):
                si = i0 + px * (i1 - i0) // W
                ei = min(si + seg_w, n)
                if si >= ei:
                    continue
                chunk = data[si:ei]
                amp   = float(np.max(np.abs(chunk)))
                h     = int(amp * mid * 0.88)
                self.wf_canvas.create_line(
                    px, mid - h, px, mid + h,
                    fill=color, tags="waveform")

        self.wf_canvas.create_line(0, mid, W, mid,
                                    fill="#333333", tags="waveform")
        self._redraw_selection()
        self._draw_ph_line()
        self._draw_ruler()

    # ── Waveform scroll / zoom ─────────────────────────────────
    def _wf_scroll_x(self, *args):
        """Callback de la scrollbar horizontale de la waveform."""
        if args[0] == "moveto":
            frac = float(args[1])
            W    = self.wf_canvas.winfo_width() or 600
            self._wf_offset_px = int(frac * max(self._wf_total_px - W, 0))
        elif args[0] == "scroll":
            delta = int(args[1]) * 20
            W     = self.wf_canvas.winfo_width() or 600
            self._wf_offset_px = max(0, min(
                self._wf_offset_px + delta,
                max(0, self._wf_total_px - W)))
        self._draw_waveform(self._wf_data if hasattr(self, "_wf_data")
                            else self.data)

    def _wf_zoom(self, event):
        """Ctrl+molette ou molette → zoom horizontal de la waveform."""
        factor = 1.15 if event.delta > 0 else 1/1.15
        self._wf_zoom_px = max(20, min(2000, self._wf_zoom_px * factor))
        self._draw_waveform(self._wf_data if hasattr(self, "_wf_data")
                            else self.data)

    def _draw_ruler(self):
        """Règle des temps — graduations sur toute la longueur visible."""
        try:
            self.ruler_canvas.delete("all")
            self.ruler_canvas.configure(bg="#0a0a0a")
            W   = self.ruler_canvas.winfo_width() or 600
            pps = self._wf_zoom_px
            off = self._wf_offset_px

            # Fond
            self.ruler_canvas.create_rectangle(
                0, 0, W, 18, fill="#0a0a0a", outline="")

            # Intervalle auto selon zoom
            for iv in [0.01,0.025,0.05,0.1,0.25,0.5,1.0,2.0,5.0,10.0,30.0,60.0,120.0]:
                if iv * pps >= 40:
                    interval = iv
                    break
            else:
                interval = 120.0

            # t de départ = premier multiple d'interval visible
            t_start = max(0.0, (off / pps) - interval)
            t_start = (t_start // interval) * interval
            t       = t_start
            last_lbl_x = -999

            while True:
                x = int(t * pps - off)
                if x > W:
                    break
                if x >= 0:
                    # Tick
                    h = 14 if round(t % (interval*4), 6) == 0 else 8
                    self.ruler_canvas.create_line(
                        x, 18-h, x, 18, fill="#555555", width=1)
                    # Label si assez d'espace
                    if x - last_lbl_x >= 36:
                        lbl = (f"{int(t)}s"    if t >= 1 and t == int(t)
                               else f"{t:.1f}s" if t >= 1
                               else f"{int(t*1000)}ms")
                        self.ruler_canvas.create_text(
                            x+2, 4, text=lbl, anchor="w",
                            fill="#aaaaaa", font=("Segoe UI", 6))
                        last_lbl_x = x
                t = round(t + interval, 9)
        except Exception:
            pass

    def _redraw_selection(self):
        self.wf_canvas.delete("sel_rect")
        if self._sel_x0 is not None and self._sel_x1 is not None:
            x0 = min(self._sel_x0, self._sel_x1)
            x1 = max(self._sel_x0, self._sel_x1)
            self.wf_canvas.create_rectangle(
                x0, 0, x1, 90,
                fill="#ffffff", outline="",
                stipple="gray25", tags="sel_rect")

    def _draw_ph_line(self):
        self.wf_canvas.delete("ph_line")
        pps = self._wf_zoom_px
        off = self._wf_offset_px
        x   = int(self._ph_pos * pps - off)
        W   = self.wf_canvas.winfo_width() or 600
        H = self.wf_canvas.winfo_height() or 160
        if 0 <= x <= W:
            self.wf_canvas.create_line(x, 0, x, H,
                                        fill="#ff4444", width=2,
                                        tags="ph_line")

    def _px_to_time(self, px):
        """Convertit un pixel écran en temps, tenant compte du zoom/offset."""
        pps = self._wf_zoom_px
        off = self._wf_offset_px
        t   = (px + off) / pps
        return max(0.0, min(t, self.duration))

    def _wf_press(self, event):
        # Stopper la lecture en cours avant de repositionner
        if self._is_playing or self._is_recording:
            self._transport_stop()
        self._dragging_sel  = False
        self._drag_start_x  = event.x
        self._sel_x0 = self._sel_x1 = None
        self._redraw_selection()
        self._ph_pos      = self._px_to_time(event.x)
        self._play_offset = self._ph_pos
        self._draw_ph_line()
        self._update_timer(self._ph_pos)

    def _wf_drag(self, event):
        if abs(event.x - self._drag_start_x) > 4:
            self._dragging_sel = True
            if self._sel_x0 is None:
                self._sel_x0 = self._drag_start_x
            self._sel_x1 = event.x
            self._redraw_selection()
            t0 = self._px_to_time(min(self._sel_x0, self._sel_x1))
            t1 = self._px_to_time(max(self._sel_x0, self._sel_x1))
            self.sel_label.config(
                text=f"Sélection : {t0:.2f}s → {t1:.2f}s",
                fg="#00b4d8")

    def _wf_release(self, event):
        if not self._dragging_sel:
            self.sel_label.config(text="Aucune sélection", fg="#666666")

    def _get_sel_samples(self):
        if self._sel_x0 is None:
            return 0, len(self.data)
        W  = max(1, self.wf_canvas.winfo_width())
        x0 = min(self._sel_x0, self._sel_x1)
        x1 = max(self._sel_x0, self._sel_x1)
        i0 = int(x0 / W * len(self.data))
        i1 = int(x1 / W * len(self.data))
        return max(0, i0), min(len(self.data), i1)

    # ============================================================
    # DÉCOUPE
    # ============================================================
    def _cut_keep(self):
        i0, i1 = self._get_sel_samples()
        if i1 - i0 < 100:
            messagebox.showwarning("Sélection vide",
                                   "Sélectionne une zone sur la waveform.")
            return
        self.data     = self.data[i0:i1]
        self.duration = len(self.data) / self.sr
        self._sel_x0 = self._sel_x1 = None
        self.sel_label.config(text="Aucune sélection", fg="#666666")
        self.dur_label.config(text=f"{self.duration:.2f}s")
        self._draw_waveform(self.data, "#4CAF50")
        self._set_status(f"✔ Gardé {self.duration:.2f}s — "
                         "clique ⬆ pour envoyer à la timeline", "#4CAF50")

    def _cut_remove(self):
        i0, i1 = self._get_sel_samples()
        if i1 - i0 < 100:
            messagebox.showwarning("Sélection vide",
                                   "Sélectionne une zone sur la waveform.")
            return
        removed = (i1 - i0) / self.sr
        self.data     = np.concatenate([self.data[:i0], self.data[i1:]])
        self.duration = len(self.data) / self.sr
        self._sel_x0 = self._sel_x1 = None
        self.sel_label.config(text="Aucune sélection", fg="#666666")
        self.dur_label.config(text=f"{self.duration:.2f}s")
        self._draw_waveform(self.data, "#FFC107")
        self._set_status(f"✔ Supprimé {removed:.2f}s — "
                         "clique ⬆ pour envoyer à la timeline", "#FFC107")

    # ============================================================
    # TRANSPORT
    # ============================================================
    def _transport_play(self):
        if self._is_playing:
            return
        if not SD_OK:
            self._set_status("✗ sounddevice manquant", "#f44336")
            return
        self._is_playing = True
        self._stop_event.clear()
        self.btn_play_t._set_color("#66BB6A")
        self._play_start = time.time()

        data_snap = self.data.copy()

        def _play():
            try:
                offset_smp = int(self._play_offset * self.sr)
                stereo     = np.column_stack([data_snap[offset_smp:],
                                              data_snap[offset_smp:]])
                sd.play(stereo, self.sr)
                while sd.get_stream().active:
                    if self._stop_event.is_set():
                        sd.stop()
                        break
                    elapsed      = time.time() - self._play_start
                    self._ph_pos = min(self._play_offset + elapsed,
                                       self.duration)
                    self.win.after(0, self._draw_ph_line)
                    self.win.after(0, lambda p=self._ph_pos:
                                   self._update_timer(p))
                    time.sleep(0.03)
                sd.stop()
            except Exception as e:
                print(f"[ClipEditor] play: {e}")
            finally:
                self._is_playing = False
                self.win.after(0, lambda: self.btn_play_t._set_color("#4CAF50"))
                self.win.after(0, lambda: self._set_status("Prêt", "#4CAF50"))

        threading.Thread(target=_play, daemon=True).start()

    def _transport_stop(self):
        self._stop_event.set()
        self._is_playing   = False
        self._is_recording = False
        try:
            sd.stop()
        except Exception:
            pass
        self.btn_play_t._set_color("#4CAF50")
        self.btn_rec_t._set_color("#c0392b")
        self._ph_pos = self._play_offset
        self._draw_ph_line()
        self._update_timer(self._ph_pos)
        if self._rec_frames:
            self._save_recording()

    def _transport_rec(self):
        if self._is_recording:
            self._transport_stop()
            return
        if not SD_OK:
            self._set_status("✗ sounddevice manquant", "#f44336")
            return
        self._is_recording = True
        self._rec_frames   = []
        self._stop_event.clear()
        self.btn_rec_t._set_color("#ff0000")
        self._set_status("● Enregistrement...", "#f44336")
        self._play_start = time.time()

        def _rec():
            try:
                with sd.InputStream(samplerate=self.sr, channels=1,
                                    dtype="float32") as stream:
                    while not self._stop_event.is_set():
                        frames, _ = stream.read(1024)
                        self._rec_frames.append(frames.copy())
                        elapsed      = time.time() - self._play_start
                        self._ph_pos = self._play_offset + elapsed
                        self.win.after(0, self._draw_ph_line)
                        self.win.after(0, lambda p=self._ph_pos:
                                       self._update_timer(p))
            except Exception as e:
                print(f"[ClipEditor] rec: {e}")
            finally:
                self._is_recording = False
                self.win.after(0, lambda: self.btn_rec_t._set_color("#c0392b"))

        threading.Thread(target=_rec, daemon=True).start()

    def _save_recording(self):
        rec     = np.concatenate(self._rec_frames, axis=0).flatten()
        off_smp = int(self._play_offset * self.sr)
        end_smp = off_smp + len(rec)
        if end_smp > len(self.data):
            self.data = np.concatenate(
                [self.data, np.zeros(end_smp - len(self.data), "float32")])
        self.data[off_smp:end_smp] = rec
        self.duration = len(self.data) / self.sr
        self.dur_label.config(text=f"{self.duration:.2f}s")
        self._rec_frames = []
        self._draw_waveform(self.data, "#f44336")
        self._set_status("✔ Enregistrement intégré — "
                         "clique ⬆ pour envoyer à la timeline", "#4CAF50")

    def _update_timer(self, pos):
        ms = int(pos * 1000)
        m  = ms // 60000
        s  = (ms % 60000) // 1000
        ms = ms % 1000
        try:
            self.timer_lbl.config(text=f"{m:02}:{s:02}.{ms:03}")
        except Exception:
            pass

    # ============================================================
    # EFFETS
    # ============================================================
    def _build_processed(self, source=None):
        out = (source if source is not None else self.data).copy()
        steps = [
            ("nr_en",     lambda d: apply_noise_reduction(
                d, self.sr, self._fx_vars["nr_strength"].get() / 100)),
            ("reverb_en", lambda d: apply_reverb(
                d, self.sr,
                self._fx_vars["rv_room"].get() / 100,
                self._fx_vars["rv_damp"].get() / 100,
                self._fx_vars["rv_wet"].get()  / 100)),
            ("delay_en",  lambda d: apply_delay(
                d, self.sr,
                self._fx_vars["dl_ms"].get(),
                self._fx_vars["dl_fb"].get() / 100,
                self._fx_vars["dl_mix"].get() / 100)),
            ("pitch_en",  lambda d: apply_pitch(
                d, self.sr, self._fx_vars["pt_semi"].get())),
        ]
        active = [s for s in steps
                  if self._fx_vars.get(s[0], tk.BooleanVar()).get()]
        for i, (_, fn) in enumerate(active):
            out = fn(out)
            self.progress_var.set(int((i + 1) / max(1, len(active)) * 100))
        self.progress_var.set(100)
        return out

    def _preview_fx(self):
        if not SD_OK:
            self._set_status("✗ sounddevice manquant", "#f44336")
            return
        self._transport_stop()

        def _run():
            try:
                self.win.after(0, lambda: self._set_status(
                    "Traitement effets pour prévisualisation...", "#FFC107"))
                out    = self._build_processed()
                stereo = np.column_stack([out, out])
                # Afficher la waveform traitée temporairement
                self.win.after(0, lambda: self._draw_waveform(out, "#00b4d8"))
                self.win.after(0, lambda: self._set_status(
                    "▶ Écoute preview — les effets NE SONT PAS encore sauvegardés",
                    "#00b4d8"))
                sd.play(stereo, self.sr)
                sd.wait()
                # Redessiner la waveform originale
                self.win.after(0, lambda: self._draw_waveform(self.data))
                self.win.after(0, lambda: self._set_status(
                    "Preview terminée — clique ✔ Appliquer pour sauvegarder",
                    "#FFC107"))
                self.win.after(0, lambda: self.progress_var.set(0))
            except Exception as e:
                self.win.after(0, lambda: self._set_status(
                    f"✗ {e}", "#f44336"))

        threading.Thread(target=_run, daemon=True).start()

    def _apply_fx_to_data(self):
        """
        Applique et SAUVEGARDE les effets dans self.data.
        Après ça, ⬆ Envoyer met à jour la timeline.
        """
        def _run():
            try:
                self.win.after(0, lambda: self.btn_apply_fx.config(
                    state="disabled", text="Traitement..."))
                self.win.after(0, lambda: self._set_status(
                    "Application des effets...", "#FFC107"))
                out = self._build_processed()
                self.data     = out
                self.duration = len(self.data) / self.sr

                self.win.after(0, lambda: self._draw_waveform(
                    self.data, "#FFC107"))
                self.win.after(0, lambda: self.dur_label.config(
                    text=f"{self.duration:.2f}s"))
                self.win.after(0, lambda: self._set_status(
                    "✔ Effets sauvegardés dans le clip — "
                    "clique ⬆ pour mettre à jour la timeline",
                    "#FFC107"))
                self.win.after(0, lambda: self.btn_apply_fx.config(
                    state="normal", text="✔  Appliquer les effets"))
                self.win.after(0, lambda: self.progress_var.set(0))
            except Exception as e:
                self.win.after(0, lambda: self._set_status(
                    f"✗ {e}", "#f44336"))
                self.win.after(0, lambda: self.btn_apply_fx.config(
                    state="normal", text="✔  Appliquer les effets"))

        threading.Thread(target=_run, daemon=True).start()

    # ============================================================
    # ENVOYER À LA TIMELINE
    # ============================================================
    def _send_to_timeline(self):
        """
        Sauvegarde self.data en WAV et met à jour le clip dans gui.py.
        C'est cette action qui rend le clip édité audible dans la timeline.
        """
        def _run():
            try:
                self.win.after(0, lambda: self.btn_send.config(
                    state="disabled", text="Sauvegarde..."))
                stereo   = np.column_stack([self.data, self.data])
                # Nom court : garder le nom de base original sans les suffixes _edited_
                raw_base = os.path.splitext(os.path.basename(self.filepath))[0]
                # Supprimer tous les suffixes _edited_XXXXXXXXXX
                import re as _re
                clean_base = _re.sub(r'_edited_\d+', '', raw_base)
                clean_base = clean_base[:40]  # max 40 chars
                ts       = int(time.time())
                out_path = os.path.join(
                    EDITED_DIR, f"{clean_base}_v{ts % 100000}.wav")
                # Éviter écrasement
                while os.path.exists(out_path):
                    ts += 1
                    out_path = os.path.join(
                        EDITED_DIR, f"{clean_base}_v{ts % 100000}.wav")
                sf.write(out_path, stereo, self.sr)
                duration = len(self.data) / self.sr
                print(f"[ClipEditor] ✔ Fichier sauvegardé : {out_path}")

                def _done():
                    self._set_status(
                        f"✔ Clip mis à jour dans la timeline ! "
                        f"({duration:.1f}s) — tu peux fermer l'éditeur",
                        "#4CAF50")
                    self.btn_send.config(
                        state="normal",
                        text="⬆  Envoyer à la timeline")
                    if self.on_updated:
                        self.on_updated(out_path, duration)

                self.win.after(0, _done)

            except Exception as e:
                self.win.after(0, lambda: self._set_status(
                    f"✗ {e}", "#f44336"))
                self.win.after(0, lambda: self.btn_send.config(
                    state="normal", text="⬆  Envoyer à la timeline"))

        threading.Thread(target=_run, daemon=True).start()

    # ============================================================
    # RESET / FERMER
    # ============================================================
    def _reset_audio(self):
        self.data     = self.orig_data.copy()
        self.duration = len(self.data) / self.sr
        self.dur_label.config(text=f"{self.duration:.2f}s")
        self._draw_waveform(self.data, "#00b4d8")
        self._set_status("↺ Audio remis à l'original", "#888888")

    def _on_close(self):
        self._stop_event.set()
        try:
            sd.stop()
        except Exception:
            pass
        self.win.destroy()

    def _set_status(self, msg, color="#4CAF50"):
        try:
            self.status_lbl.config(text=msg, fg=color)
        except Exception:
            pass
