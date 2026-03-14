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

try:
    from scipy import signal as scipy_signal
    SCIPY_OK = True
except ImportError:
    SCIPY_OK = False

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
    if not SCIPY_OK:
        return data
    ir_len = int(sr * max(0.01, room) * 2)
    t      = np.linspace(0, 1, ir_len)
    decay  = np.exp(-damping * 6 * t)
    ir     = (np.random.randn(ir_len) * decay).astype("float32")
    ir[0]  = 1.0
    rev    = scipy_signal.fftconvolve(data, ir, mode="full")[:len(data)]
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
    if not SCIPY_OK:
        return data
    noise_len = min(int(sr * 0.2), len(data) // 4)
    noise_ref = data[:noise_len]
    n_fft = 1024
    hop   = n_fft // 4
    _, _, Zxx    = scipy_signal.stft(data,      fs=sr, nperseg=n_fft, noverlap=n_fft-hop)
    _, _, Znoise = scipy_signal.stft(noise_ref, fs=sr, nperseg=n_fft, noverlap=n_fft-hop)
    noise_p   = np.mean(np.abs(Znoise), axis=1, keepdims=True)
    Zxx_clean = np.maximum(np.abs(Zxx) - noise_p * strength, 0) * np.exp(1j * np.angle(Zxx))
    _, out = scipy_signal.istft(Zxx_clean, fs=sr, nperseg=n_fft, noverlap=n_fft-hop)
    return np.clip(out[:len(data)].astype("float32"), -1, 1)


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
            messagebox.showerror("Erreur", f"Fichier introuvable :\n{fp}")
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

        self.win.protocol("WM_DELETE_WINDOW", self._on_close)
        self.win.grab_set()
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
        footer = tk.Frame(self.win, bg="#0a0a0a")
        footer.pack(fill="x", side="bottom")

        tk.Frame(footer, bg="#222222", height=1).pack(fill="x")

        # Progression + statut dans le footer
        self.progress_var = tk.IntVar(value=0)
        ttk.Progressbar(footer, variable=self.progress_var,
                        maximum=100).pack(fill="x", padx=12, pady=(6, 2))

        self.status_lbl = tk.Label(footer,
                                    text="Prêt  —  ▶ Prévisualiser → ✔ Appliquer → ⬆ Envoyer",
                                    bg="#0a0a0a", fg="#4CAF50",
                                    font=("Segoe UI", 8))
        self.status_lbl.pack(anchor="w", padx=14, pady=(0, 4))

        tk.Frame(footer, bg="#333333", height=1).pack(fill="x")

        btn_bar = tk.Frame(footer, bg="#0a0a0a", pady=10)
        btn_bar.pack(fill="x", padx=12)

        # ▶ Prévisualiser
        tk.Button(btn_bar, text="▶  Prévisualiser",
                  font=("Segoe UI", 9),
                  bg="#0d3b4f", fg="#00b4d8",
                  activebackground="#00b4d8", activeforeground="white",
                  relief="flat", padx=12, pady=8,
                  cursor="hand2",
                  command=self._preview_fx).pack(side="left", padx=(0, 4))

        # ✔ Appliquer les effets
        self.btn_apply_fx = tk.Button(
            btn_bar,
            text="✔  Appliquer les effets",
            font=("Segoe UI", 9, "bold"),
            bg="#FFC107", fg="#0a0a0a",
            activebackground="#FFD54F",
            relief="flat", padx=14, pady=8,
            cursor="hand2",
            command=self._apply_fx_to_data)
        self.btn_apply_fx.pack(side="left", padx=4)

        # ⬆ Envoyer à la timeline
        self.btn_send = tk.Button(
            btn_bar,
            text="⬆  Envoyer à la timeline",
            font=("Segoe UI", 10, "bold"),
            bg="#4CAF50", fg="white",
            activebackground="#66BB6A",
            relief="flat", padx=16, pady=8,
            cursor="hand2",
            command=self._send_to_timeline)
        self.btn_send.pack(side="left", padx=4)

        # ↺ Reset
        tk.Button(btn_bar, text="↺  Reset",
                  bg="#1e1e1e", fg="#888888",
                  activebackground="#333",
                  relief="flat", padx=10, pady=8,
                  font=("Segoe UI", 8),
                  cursor="hand2",
                  command=self._reset_audio).pack(side="left", padx=4)

        # ✕ Fermer
        tk.Button(btn_bar, text="✕  Fermer",
                  font=("Segoe UI", 9),
                  bg="#2a2a2a", fg="white",
                  activebackground="#444",
                  relief="flat", padx=12, pady=8,
                  cursor="hand2",
                  command=self._on_close).pack(side="right")

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

        # Mousewheel
        def _on_mousewheel(e):
            scroll_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        scroll_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        self._build_content(self.content)

    # ============================================================
    # CONTENU SCROLLABLE
    # ============================================================
    def _build_content(self, parent):

        # --- TRANSPORT ---
        transport = tk.Frame(parent, bg="#0d0d0d", pady=6)
        transport.pack(fill="x", padx=0)

        self.btn_stop_t = tk.Button(
            transport, text="⏹", font=("Segoe UI", 14),
            bg="#2a2a2a", fg="white", activebackground="#555",
            relief="flat", width=3, cursor="hand2",
            command=self._transport_stop)
        self.btn_stop_t.pack(side="left", padx=(12, 4))

        self.btn_play_t = tk.Button(
            transport, text="▶", font=("Segoe UI", 14),
            bg="#4CAF50", fg="white", activebackground="#66BB6A",
            relief="flat", width=3, cursor="hand2",
            command=self._transport_play)
        self.btn_play_t.pack(side="left", padx=4)

        self.btn_rec_t = tk.Button(
            transport, text="●", font=("Segoe UI", 14),
            bg="#c0392b", fg="white", activebackground="#e74c3c",
            relief="flat", width=3, cursor="hand2",
            command=self._transport_rec)
        self.btn_rec_t.pack(side="left", padx=4)

        self.timer_lbl = tk.Label(
            transport, text="00:00.000",
            bg="#0d0d0d", fg="#cccccc",
            font=("Consolas", 10))
        self.timer_lbl.pack(side="left", padx=16)

        tk.Frame(parent, bg="#222222", height=1).pack(fill="x")

        # --- WAVEFORM ---
        wf_frame = tk.Frame(parent, bg="#111111")
        wf_frame.pack(fill="x", padx=12, pady=6)

        tk.Label(wf_frame,
                 text="Waveform — clic pour repositionner · glisser pour sélectionner",
                 bg="#111111", fg="#444444",
                 font=("Segoe UI", 7)).pack(anchor="w", padx=4)

        self.wf_canvas = tk.Canvas(wf_frame, bg="#111111",
                                    height=90, highlightthickness=0,
                                    cursor="crosshair")
        self.wf_canvas.pack(fill="x", padx=4, pady=4)
        self.wf_canvas.bind("<ButtonPress-1>",  self._wf_press)
        self.wf_canvas.bind("<B1-Motion>",       self._wf_drag)
        self.wf_canvas.bind("<ButtonRelease-1>", self._wf_release)

        self._sel_x0 = self._sel_x1 = None
        self._sel_rect    = None
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

        for txt, cmd in [
            ("Garder la sélection",    self._cut_keep),
            ("Supprimer la sélection", self._cut_remove),
        ]:
            tk.Button(cut_frame, text=txt,
                      bg="#2a2a2a", fg="white",
                      activebackground="#555",
                      relief="flat", padx=10, pady=4,
                      font=("Segoe UI", 8), cursor="hand2",
                      command=cmd).pack(side="left", padx=4)

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
                     font=("Segoe UI", 8), width=14,
                     anchor="w").pack(side="left")
            var = tk.IntVar(value=default)
            self._fx_vars[var_key] = var
            tk.Label(row, textvariable=var, bg="#141414", fg="#4CAF50",
                     font=("Segoe UI", 8), width=4).pack(side="right")
            tk.Scale(row, variable=var, from_=mn, to=mx,
                     orient="horizontal", bg="#141414", fg="white",
                     troughcolor="#2a2a2a", highlightthickness=0,
                     showvalue=False, length=220).pack(
                         side="left", fill="x", expand=True)

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

    # ============================================================
    # WAVEFORM
    # ============================================================
    def _draw_waveform(self, data, color="#00b4d8"):
        self.wf_canvas.update_idletasks()
        W = self.wf_canvas.winfo_width()
        H = 90
        if W < 10:
            W = 560
        self.wf_canvas.delete("waveform")
        self.wf_canvas.create_rectangle(0, 0, W, H,
                                         fill="#111111", outline="",
                                         tags="waveform")
        n    = len(data)
        mid  = H // 2
        step = max(1, n // W)
        for px in range(W):
            chunk = data[px * step: min(px * step + step, n)]
            if not len(chunk):
                continue
            amp = float(np.max(np.abs(chunk)))
            h   = int(amp * mid * 0.9)
            self.wf_canvas.create_line(
                px, mid - h, px, mid + h, fill=color, tags="waveform")
        self.wf_canvas.create_line(0, mid, W, mid,
                                    fill="#2a2a2a", tags="waveform")
        self._redraw_selection()
        self._draw_ph_line()

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
        W   = max(1, self.wf_canvas.winfo_width())
        dur = max(0.001, self.duration)
        x   = max(0, min(int(self._ph_pos / dur * W), W))
        self.wf_canvas.create_line(x, 0, x, 90,
                                    fill="#ff4444", width=2,
                                    tags="ph_line")

    def _px_to_time(self, px):
        W = max(1, self.wf_canvas.winfo_width())
        return max(0.0, min(px / W * self.duration, self.duration))

    def _wf_press(self, event):
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
        self.btn_play_t.config(bg="#66BB6A")
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
                self.win.after(0, lambda: self.btn_play_t.config(bg="#4CAF50"))
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
        self.btn_play_t.config(bg="#4CAF50")
        self.btn_rec_t.config(bg="#c0392b")
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
        self.btn_rec_t.config(bg="#ff0000")
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
                self.win.after(0, lambda: self.btn_rec_t.config(bg="#c0392b"))

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
                base     = os.path.splitext(
                    os.path.basename(self.filepath))[0]
                ts       = int(time.time())
                out_path = os.path.join(
                    EDITED_DIR, f"{base}_edited_{ts}.wav")
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
