"""
file_explorer.py — Explorateur de fichiers intégré mini_daw
Navigue sur tout le disque, prévisualise et importe n'importe quel fichier audio.
"""

import os
import threading
import tkinter as tk
from tkinter import ttk

try:
    import soundfile as sf
    SF_OK = True
except ImportError:
    SF_OK = False

try:
    import sounddevice as sd
    SD_OK = True
except ImportError:
    SD_OK = False

try:
    import numpy as np
    NP_OK = True
except ImportError:
    NP_OK = False

AUDIO_EXTS = {
    ".wav", ".mp3", ".flac", ".ogg", ".aiff", ".aif",
    ".mp4", ".m4a", ".wma", ".aac", ".opus",
    # majuscules aussi
    ".WAV", ".MP3", ".FLAC", ".OGG", ".AIFF", ".AIF",
    ".MP4", ".M4A", ".WMA", ".AAC",
}

# Dossiers favoris mini_daw
BASE_DIR    = os.path.dirname(__file__)
SAMPLES_DIR = os.path.join(BASE_DIR, "samples")
REC_DIR     = os.path.join(SAMPLES_DIR, "recordings")
EDITED_DIR  = os.path.join(SAMPLES_DIR, "edited")


def get_drives():
    """Retourne les lecteurs disponibles sur Windows."""
    drives = []
    if os.name == "nt":
        import string
        for letter in string.ascii_uppercase:
            d = f"{letter}:\\"
            if os.path.exists(d):
                drives.append(d)
    else:
        drives = ["/"]
    return drives


class FileExplorerWindow:
    """
    Explorateur de fichiers intégré avec :
    - Panneau gauche : favoris + lecteurs
    - Panneau central : liste des fichiers/dossiers
    - Panneau droit : infos + prévisualisation audio
    - Bouton Importer
    """

    def __init__(self, parent, on_import=None):
        self.parent    = parent
        self.on_import = on_import
        self._current  = os.path.expanduser("~")
        self._selected = None
        self._history  = []   # historique navigation ←
        self._future   = []   # historique navigation →
        self._preview_data   = None
        self._preview_sr     = None
        self._preview_thread = None
        self._stop_preview   = threading.Event()

        self.win = tk.Toplevel(parent)
        self.win.title("mini_daw — Import de fichiers")
        self.win.configure(bg="#0f0f0f")
        self.win.resizable(True, True)

        w, h = 820, 560
        sw   = self.win.winfo_screenwidth()
        sh   = self.win.winfo_screenheight()
        self.win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self.win.minsize(700, 450)

        try:
            ico = os.path.join(BASE_DIR, "assets", "logo.ico")
            if os.path.exists(ico):
                self.win.iconbitmap(ico)
        except Exception:
            pass

        self.win.grab_set()
        self._build_ui()
        self._navigate(self._current)

    # ================================================================
    def _build_ui(self):

        # --- En-tête ---
        hdr = tk.Frame(self.win, bg="#0a0a0a")
        hdr.pack(fill="x")
        tk.Label(hdr, text="mini_daw",
                 bg="#0a0a0a", fg="#4CAF50",
                 font=("Segoe UI", 11, "bold")).pack(side="left", padx=12, pady=6)
        tk.Label(hdr, text="📂 Import de fichiers",
                 bg="#0a0a0a", fg="#aaaaaa",
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Frame(self.win, bg="#222222", height=1).pack(fill="x")

        # --- Barre de chemin ---
        path_bar = tk.Frame(self.win, bg="#111111")
        path_bar.pack(fill="x", padx=0)

        tk.Button(path_bar, text="←",
                  bg="#1a1a1a", fg="#aaaaaa",
                  activebackground="#333", activeforeground="white",
                  relief="flat", padx=8, pady=3,
                  cursor="hand2", font=("Segoe UI", 10, "bold"),
                  command=self._go_back).pack(side="left", padx=(4,1), pady=3)

        tk.Button(path_bar, text="→",
                  bg="#1a1a1a", fg="#aaaaaa",
                  activebackground="#333", activeforeground="white",
                  relief="flat", padx=8, pady=3,
                  cursor="hand2", font=("Segoe UI", 10, "bold"),
                  command=self._go_forward).pack(side="left", padx=(1,4), pady=3)

        tk.Button(path_bar, text="⬆",
                  bg="#1a1a1a", fg="#aaaaaa",
                  activebackground="#333", activeforeground="white",
                  relief="flat", padx=8, pady=3,
                  cursor="hand2", font=("Segoe UI", 10, "bold"),
                  command=self._go_up).pack(side="left", padx=(0,4), pady=3)

        self.path_var = tk.StringVar(value=self._current)
        path_entry = tk.Entry(path_bar, textvariable=self.path_var,
                              bg="#1e1e1e", fg="white",
                              insertbackground="white",
                              relief="flat", font=("Segoe UI", 9))
        path_entry.pack(side="left", fill="x", expand=True, ipady=4, padx=4)
        path_entry.bind("<Return>", lambda e: self._navigate(self.path_var.get()))

        tk.Button(path_bar, text="▶ Aller",
                  bg="#333", fg="white",
                  activebackground="#4CAF50",
                  relief="flat", padx=8, pady=3,
                  cursor="hand2", font=("Segoe UI", 8),
                  command=lambda: self._navigate(self.path_var.get())
                  ).pack(side="left", padx=4, pady=3)

        tk.Frame(self.win, bg="#222222", height=1).pack(fill="x")

        # --- Corps à 3 colonnes ---
        body = tk.Frame(self.win, bg="#0f0f0f")
        body.pack(fill="both", expand=True)

        # == COLONNE GAUCHE : Favoris + Lecteurs ==
        left = tk.Frame(body, bg="#111111", width=160)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        tk.Label(left, text="FAVORIS",
                 bg="#111111", fg="#555555",
                 font=("Segoe UI", 7, "bold")).pack(anchor="w", padx=8, pady=(8,2))

        favorites = [
            ("🏠 Bureau",         os.path.join(os.path.expanduser("~"), "Desktop")),
            ("🏠 Documents",      os.path.join(os.path.expanduser("~"), "Documents")),
            ("🏠 Musique",        os.path.join(os.path.expanduser("~"), "Music")),
            ("🏠 Téléchargements",os.path.join(os.path.expanduser("~"), "Downloads")),
        ]
        daw_favs = [
            ("🎵 Samples DAW",    SAMPLES_DIR),
            ("🎤 Enregistrements",REC_DIR),
            ("✂ Édités",          EDITED_DIR),
        ]

        for label, path in favorites:
            self._fav_btn(left, label, path)

        tk.Frame(left, bg="#222222", height=1).pack(fill="x", pady=4)
        tk.Label(left, text="MINI DAW",
                 bg="#111111", fg="#555555",
                 font=("Segoe UI", 7, "bold")).pack(anchor="w", padx=8, pady=(2,2))

        for label, path in daw_favs:
            self._fav_btn(left, label, path)

        tk.Frame(left, bg="#222222", height=1).pack(fill="x", pady=4)
        tk.Label(left, text="LECTEURS",
                 bg="#111111", fg="#555555",
                 font=("Segoe UI", 7, "bold")).pack(anchor="w", padx=8, pady=(2,2))

        for drive in get_drives():
            self._fav_btn(left, f"💾 {drive}", drive)

        # == COLONNE CENTRALE : Liste fichiers ==
        mid = tk.Frame(body, bg="#1a1a1a")
        mid.pack(side="left", fill="both", expand=True)

        # Filtre
        filter_bar = tk.Frame(mid, bg="#111111")
        filter_bar.pack(fill="x")

        tk.Label(filter_bar, text="Filtre :",
                 bg="#111111", fg="#888", font=("Segoe UI", 8)).pack(side="left", padx=6)

        self.filter_var = tk.StringVar(value="Tous les fichiers")
        filter_cb = ttk.Combobox(filter_bar, textvariable=self.filter_var,
                                  values=["Tous les fichiers", "Audio seulement"],
                                  state="readonly", width=16,
                                  font=("Segoe UI", 8))
        filter_cb.pack(side="left", padx=4, pady=3)
        filter_cb.bind("<<ComboboxSelected>>",
                       lambda e: self._navigate(self._current))

        # Liste avec scrollbar
        list_frame = tk.Frame(mid, bg="#1a1a1a")
        list_frame.pack(fill="both", expand=True)

        scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        self.listbox = tk.Listbox(
            list_frame,
            bg="#1a1a1a", fg="white",
            selectbackground="#00b4d8",
            selectforeground="white",
            activestyle="none",
            font=("Segoe UI", 9),
            relief="flat",
            borderwidth=0,
            yscrollcommand=scrollbar.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.listbox.yview)

        self.listbox.bind("<Double-Button-1>", self._on_double_click)
        self.listbox.bind("<<ListboxSelect>>",  self._on_select)
        self.listbox.bind("<Return>",           self._on_double_click)

        # == COLONNE DROITE : Infos + Preview ==
        right = tk.Frame(body, bg="#111111", width=200)
        right.pack(side="left", fill="y")
        right.pack_propagate(False)

        tk.Label(right, text="INFOS",
                 bg="#111111", fg="#555555",
                 font=("Segoe UI", 7, "bold")).pack(anchor="w", padx=8, pady=(8,2))

        self.info_name = tk.Label(right, text="—",
                                   bg="#111111", fg="white",
                                   font=("Segoe UI", 8, "bold"),
                                   wraplength=180, justify="left")
        self.info_name.pack(anchor="w", padx=8, pady=2)

        self.info_dur = tk.Label(right, text="",
                                  bg="#111111", fg="#888888",
                                  font=("Segoe UI", 8))
        self.info_dur.pack(anchor="w", padx=8)

        self.info_size = tk.Label(right, text="",
                                   bg="#111111", fg="#888888",
                                   font=("Segoe UI", 8))
        self.info_size.pack(anchor="w", padx=8)

        self.info_sr = tk.Label(right, text="",
                                 bg="#111111", fg="#888888",
                                 font=("Segoe UI", 8))
        self.info_sr.pack(anchor="w", padx=8)

        tk.Frame(right, bg="#222222", height=1).pack(fill="x", pady=8)

        # Mini waveform
        self.wf_canvas = tk.Canvas(right, bg="#0a0a0a",
                                    height=70, highlightthickness=0)
        self.wf_canvas.pack(fill="x", padx=8, pady=4)

        # Bouton preview
        self.btn_preview = tk.Button(
            right, text="▶ Écouter",
            bg="#2a2a2a", fg="white",
            activebackground="#00b4d8",
            relief="flat", padx=8, pady=4,
            cursor="hand2", font=("Segoe UI", 8),
            command=self._toggle_preview)
        self.btn_preview.pack(fill="x", padx=8, pady=2)

        # --- Barre du bas ---
        tk.Frame(self.win, bg="#222222", height=1).pack(fill="x")

        bot = tk.Frame(self.win, bg="#0a0a0a", pady=8)
        bot.pack(fill="x", padx=12)

        self.selected_label = tk.Label(
            bot, text="Aucun fichier sélectionné",
            bg="#0a0a0a", fg="#555555",
            font=("Segoe UI", 8), anchor="w")
        self.selected_label.pack(side="left", fill="x", expand=True)

        tk.Button(bot, text="✕ Annuler",
                  bg="#2a2a2a", fg="white",
                  activebackground="#444",
                  relief="flat", padx=12, pady=6,
                  cursor="hand2", font=("Segoe UI", 9),
                  command=self._cancel).pack(side="right", padx=(6, 0))

        self.btn_import = tk.Button(
            bot, text="⊕ Importer",
            bg="#4CAF50", fg="white",
            activebackground="#66BB6A",
            relief="flat", padx=18, pady=6,
            cursor="hand2", font=("Segoe UI", 10, "bold"),
            state="disabled",
            command=self._do_import)
        self.btn_import.pack(side="right")

    # ================================================================
    def _fav_btn(self, parent, label, path):
        def _cmd():
            if os.path.exists(path):
                self._navigate(path)
            else:
                self._set_status(f"Dossier introuvable : {path}")
        tk.Button(parent, text=label,
                  bg="#111111", fg="#aaaaaa",
                  activebackground="#222222", activeforeground="white",
                  relief="flat", anchor="w",
                  padx=8, pady=3,
                  font=("Segoe UI", 8),
                  cursor="hand2",
                  command=_cmd).pack(fill="x")

    # ================================================================
    def _navigate(self, path, from_history=False):
        path = path.strip()
        if not os.path.exists(path):
            return
        if os.path.isfile(path):
            path = os.path.dirname(path)

        # Historique
        if not from_history and self._current != path:
            self._history.append(self._current)
            self._future.clear()

        self._current = path
        self.path_var.set(path)
        self.listbox.delete(0, "end")
        self._entries = []  # liste de (display_text, full_path, is_dir)

        audio_only = self.filter_var.get() == "Audio seulement"

        try:
            items = sorted(os.listdir(path))
        except PermissionError:
            self.listbox.insert("end", "⛔ Accès refusé")
            return
        except Exception as e:
            self.listbox.insert("end", f"Erreur : {e}")
            return

        # Dossiers en premier
        dirs  = [i for i in items if os.path.isdir(os.path.join(path, i))]
        files = [i for i in items if os.path.isfile(os.path.join(path, i))]

        for d in dirs:
            full = os.path.join(path, d)
            self.listbox.insert("end", f"📁  {d}")
            self.listbox.itemconfig("end", fg="#FFC107")
            self._entries.append((d, full, True))

        for f in files:
            full = os.path.join(path, f)
            ext      = os.path.splitext(f)[1].lower()
            is_audio = ext in AUDIO_EXTS

            if audio_only and not is_audio:
                continue

            icon = "🎵" if is_audio else "📄"
            self.listbox.insert("end", f"{icon}  {f}")
            if is_audio:
                self.listbox.itemconfig("end", fg="#00b4d8")
            else:
                self.listbox.itemconfig("end", fg="#888888")
            self._entries.append((f, full, False))

    def _go_back(self):
        if self._history:
            self._future.append(self._current)
            prev = self._history.pop()
            self._navigate(prev, from_history=True)

    def _go_forward(self):
        if self._future:
            self._history.append(self._current)
            nxt = self._future.pop()
            self._navigate(nxt, from_history=True)

    def _go_up(self):
        parent = os.path.dirname(self._current)
        if parent and parent != self._current:
            self._navigate(parent)

    def _on_double_click(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._entries):
            return
        name, full, is_dir = self._entries[idx]
        if is_dir:
            self._navigate(full)
        else:
            # Simple clic sélectionne, double-clic importe directement
            self._selected = full
            self.btn_import.config(state="normal")
            self._do_import()

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._entries):
            return
        name, full, is_dir = self._entries[idx]

        if is_dir:
            self._selected = None
            self.btn_import.config(state="disabled")
            self.selected_label.config(text=f"📁 {name}", fg="#FFC107")
            self._clear_info()
            return

        self._selected = full
        ext      = os.path.splitext(full)[1].lower()
        is_audio = ext in AUDIO_EXTS

        # Bouton Importer actif pour TOUT fichier sélectionné
        self.btn_import.config(state="normal")

        self.selected_label.config(
            text=f"{'🎵' if is_audio else '📄'} {name}",
            fg="#00b4d8" if is_audio else "#cccccc")

        # Infos
        self.info_name.config(text=name)
        try:
            size_kb = os.path.getsize(full) // 1024
            self.info_size.config(text=f"Taille : {size_kb} KB")
        except Exception:
            self.info_size.config(text="")

        if is_audio and SF_OK:
            threading.Thread(
                target=self._load_info,
                args=(full,), daemon=True).start()
        else:
            self.info_dur.config(text="")
            self.info_sr.config(text="")
            self.wf_canvas.delete("all")

    def _load_info(self, filepath):
        try:
            info = sf.info(filepath)
            dur  = info.duration
            sr   = info.samplerate
            self.win.after(0, lambda: self.info_dur.config(
                text=f"Durée : {dur:.2f}s"))
            self.win.after(0, lambda: self.info_sr.config(
                text=f"Sample rate : {sr} Hz"))
            # Waveform mini
            if NP_OK:
                data, _ = sf.read(filepath, dtype="float32",
                                  always_2d=False)
                if data.ndim == 2:
                    data = data.mean(axis=1)
                self.win.after(0, lambda d=data: self._draw_wf(d))
        except Exception:
            pass

    def _draw_wf(self, data):
        self.wf_canvas.delete("all")
        W = self.wf_canvas.winfo_width() or 180
        H = 70
        mid = H // 2
        n   = len(data)
        step = max(1, n // W)
        for px in range(W):
            i0  = px * step
            i1  = min(i0 + step, n)
            amp = float(max(abs(data[i0:i1]))) if i1 > i0 else 0
            h   = int(amp * mid * 0.9)
            self.wf_canvas.create_line(
                px, mid - h, px, mid + h, fill="#00b4d8")

    def _clear_info(self):
        self.info_name.config(text="—")
        self.info_dur.config(text="")
        self.info_size.config(text="")
        self.info_sr.config(text="")
        self.wf_canvas.delete("all")

    # ================================================================
    # PREVIEW
    # ================================================================
    def _toggle_preview(self):
        if not self._selected:
            return
        if not SD_OK or not SF_OK:
            return
        if self.btn_preview.cget("text") == "⏹ Stop":
            self._stop_preview.set()
            sd.stop()
            self.btn_preview.config(text="▶ Écouter", bg="#2a2a2a")
            return

        self._stop_preview.clear()
        self.btn_preview.config(text="⏹ Stop", bg="#c0392b")

        def _play():
            try:
                data, sr = sf.read(self._selected, dtype="float32",
                                   always_2d=True)
                sd.play(data, sr)
                sd.wait()
            except Exception:
                pass
            finally:
                try:
                    self.win.after(0, lambda: self.btn_preview.config(
                        text="▶ Écouter", bg="#2a2a2a"))
                except Exception:
                    pass

        self._preview_thread = threading.Thread(target=_play, daemon=True)
        self._preview_thread.start()

    # ================================================================
    # IMPORT
    # ================================================================
    def _do_import(self):
        if not self._selected or not os.path.isfile(self._selected):
            self.selected_label.config(
                text="⚠ Sélectionne un fichier d'abord", fg="#FFC107")
            return
        fp = self._selected
        cb = self.on_import
        self._stop_preview.set()
        try:
            sd.stop()
        except Exception:
            pass
        self.win.grab_release()
        self.win.destroy()
        if cb:
            cb(fp)

    def _cancel(self):
        self._stop_preview.set()
        try:
            sd.stop()
        except Exception:
            pass
        self.win.destroy()

    def _set_status(self, msg):
        self.selected_label.config(text=msg, fg="#f44336")
