import tkinter as tk
from tkinter import filedialog, messagebox
import os
import time
import copy
import soundfile as sf

from engine         import AudioEngine
from recorder       import RecorderWindow
from exporter       import ExportWindow
from web_importer   import WebImporterWindow
from clip_editor    import ClipEditorWindow
from file_explorer   import FileExplorerWindow
from metronome       import Metronome
from project_manager import save_project, load_project

RESIZE_ZONE  = 10
BASE_DIR     = os.path.dirname(__file__)
SAMPLES_DIR  = os.path.join(BASE_DIR, "samples")
REC_DIR      = os.path.join(SAMPLES_DIR, "recordings")
EDITED_DIR   = os.path.join(SAMPLES_DIR, "edited")
PROJECTS_DIR = os.path.join(BASE_DIR,    "projects")

for d in [SAMPLES_DIR, REC_DIR, EDITED_DIR, PROJECTS_DIR]:
    os.makedirs(d, exist_ok=True)


class MiniDAWApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Mini Python DAW")
        self.root.configure(bg="#141414")
        self.root.minsize(960, 540)

        self.engine    = AudioEngine()
        self.metronome = Metronome()
        self._metro_on = False

        self.track_height      = 80
        self.pixels_per_second = 120
        self.tracks            = []
        self.clips             = {}
        self._current_project  = None

        self.bpm              = tk.IntVar(value=120)
        self.is_playing       = False
        self.playhead_pos     = 0.0
        self.playhead_line    = None
        self._play_start_time = None
        self._play_start_pos  = 0.0
        self._total_duration  = 0.0

        # Undo/Redo
        self._undo_stack = []
        self._redo_stack = []

        # Drag / Resize
        self.drag_tag      = None
        self.drag_item     = None
        self.drag_start_x  = 0
        self.drag_start_y  = 0
        self._resize_side  = None
        self._resize_item  = None

        # Clip sélectionné (clic gauche)
        self._selected_clip = None

        self._build_menu()
        self._build_transport()
        self._build_main()

        self.draw_ruler()
        self.draw_grid()
        for i in range(5):
            self.create_track()

        self._draw_playhead()
        # Redessiner grille selon BPM initial
        self.root.after(100, self._redraw_grid_and_ruler)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Control-z>", lambda e: self.undo())
        self.root.bind("<Control-y>", lambda e: self.redo())
        self.root.bind("<Control-s>", lambda e: self._save_project())
        self.root.bind("<Control-n>", lambda e: self._new_project())
        self.root.bind("<Delete>",    lambda e: self._delete_selected())
        self.root.bind("<Control-d>", lambda e: self._duplicate_selected())
        self.root.bind("<Control-a>", lambda e: self._select_all())

    # ============================================================
    # MENU BAR
    # ============================================================
    def _build_menu(self):
        menubar = tk.Menu(self.root, bg="#1a1a1a", fg="white",
                          activebackground="#4CAF50",
                          activeforeground="white",
                          relief="flat")

        # --- Fichier ---
        file_menu = tk.Menu(menubar, tearoff=0,
                            bg="#1a1a1a", fg="white",
                            activebackground="#4CAF50",
                            activeforeground="white")
        file_menu.add_command(label="📄  Nouveau projet",
                              accelerator="Ctrl+N",
                              command=self._new_project)
        file_menu.add_command(label="📂  Ouvrir un projet...",
                              command=self._open_project)
        file_menu.add_command(label="💾  Sauvegarder",
                              accelerator="Ctrl+S",
                              command=self._save_project)
        file_menu.add_command(label="💾  Sauvegarder sous...",
                              command=self._save_project_as)
        file_menu.add_separator()
        file_menu.add_separator()
        file_menu.add_command(label="📂  Importer un fichier audio...",
                              command=self.import_audio)
        file_menu.add_command(label="🌐  Import Web...",
                              command=self.open_web_importer)
        file_menu.add_command(label="📁  Historique des samples",
                              command=self._open_history_window)
        file_menu.add_separator()
        file_menu.add_command(label="⬇  Exporter WAV...",
                              command=self.open_export)
        file_menu.add_separator()
        file_menu.add_command(label="❌  Quitter",
                              command=self._on_close)
        menubar.add_cascade(label="Fichier", menu=file_menu)

        # --- Édition ---
        edit_menu = tk.Menu(menubar, tearoff=0,
                            bg="#1a1a1a", fg="white",
                            activebackground="#4CAF50",
                            activeforeground="white")
        edit_menu.add_command(label="↩  Annuler",
                              accelerator="Ctrl+Z",
                              command=self.undo)
        edit_menu.add_command(label="↪  Rétablir",
                              accelerator="Ctrl+Y",
                              command=self.redo)
        edit_menu.add_separator()
        edit_menu.add_command(label="🗑  Supprimer clip sélectionné",
                              accelerator="Suppr",
                              command=self._delete_selected)
        edit_menu.add_command(label="📋  Dupliquer clip",
                              accelerator="Ctrl+D",
                              command=self._duplicate_selected)
        edit_menu.add_command(label="⬜  Sélectionner tout",
                              accelerator="Ctrl+A",
                              command=self._select_all)
        menubar.add_cascade(label="Édition", menu=edit_menu)

        # --- Affichage ---
        view_menu = tk.Menu(menubar, tearoff=0,
                            bg="#1a1a1a", fg="white",
                            activebackground="#4CAF50",
                            activeforeground="white")
        view_menu.add_command(label="📁  Ouvrir le dossier samples/",
                              command=self._open_samples_folder)
        view_menu.add_command(label="🎤  Ouvrir le dossier recordings/",
                              command=self._open_recordings_folder)
        view_menu.add_command(label="🗂  Ouvrir le dossier projets/",
                              command=self._open_projects_folder)
        menubar.add_cascade(label="Affichage", menu=view_menu)

        # --- Aide ---
        help_menu = tk.Menu(menubar, tearoff=0,
                            bg="#1a1a1a", fg="white",
                            activebackground="#4CAF50",
                            activeforeground="white")
        help_menu.add_command(label="ℹ  À propos",
                              command=self._about)
        menubar.add_cascade(label="Aide", menu=help_menu)

        self.root.config(menu=menubar)

    # ============================================================
    # TRANSPORT BAR
    # ============================================================
    @staticmethod
    def _lighten(hex_color):
        try:
            rv = min(255, int(hex_color[1:3], 16) + 30)
            gv = min(255, int(hex_color[3:5], 16) + 30)
            bv = min(255, int(hex_color[5:7], 16) + 30)
            return f"#{rv:02x}{gv:02x}{bv:02x}"
        except Exception:
            return hex_color

    def _round_btn(self, parent, text, bg, fg, command, size=36, r=10):
        """Bouton Canvas arrondi réutilisable."""
        cv = tk.Canvas(parent, width=size, height=size,
                       bg="#0f0f0f", highlightthickness=0, cursor="hand2")
        def _draw(color=bg):
            cv.delete("all")
            cv.create_rectangle(r, 0, size-r, size, fill=color, outline="")
            cv.create_rectangle(0, r, size, size-r, fill=color, outline="")
            cv.create_oval(0, 0, r*2, r*2, fill=color, outline="")
            cv.create_oval(size-r*2, 0, size, r*2, fill=color, outline="")
            cv.create_oval(0, size-r*2, r*2, size, fill=color, outline="")
            cv.create_oval(size-r*2, size-r*2, size, size, fill=color, outline="")
            cv.create_text(size//2, size//2, text=text, fill=fg,
                           font=("Segoe UI", 11, "bold"))
        _draw()
        cv.bind("<ButtonPress-1>",   lambda e: (_draw("#555555"), command()))
        cv.bind("<ButtonRelease-1>", lambda e: _draw(bg))
        cv.bind("<Enter>",           lambda e: _draw(self._lighten(bg)))
        cv.bind("<Leave>",           lambda e: _draw(bg))
        cv._set_color = _draw
        return cv

    def _build_transport(self):
        transport = tk.Frame(self.root, bg="#0f0f0f", pady=6)
        transport.pack(fill="x")

        # STOP
        self.btn_stop = self._round_btn(
            transport, "⏹", "#2a2a2a", "white", self.stop, size=34, r=9)
        self.btn_stop.pack(side="left", padx=(10, 2))

        # PLAY
        self._play_bg = "#4CAF50"
        self.btn_play = self._round_btn(
            transport, "▶", self._play_bg, "white", self.play, size=34, r=9)
        self.btn_play.pack(side="left", padx=2)

        # REC
        self.btn_rec = self._round_btn(
            transport, "●", "#c0392b", "white", self.open_recorder, size=34, r=9)
        self.btn_rec.pack(side="left", padx=2)

        tk.Frame(transport, bg="#333333", width=2).pack(
            side="left", fill="y", padx=10)

        tk.Label(transport, text="BPM", bg="#0f0f0f", fg="#888888",
                 font=("Segoe UI", 9)).pack(side="left")

        tk.Button(transport, text="−", font=("Segoe UI", 11),
                  bg="#2a2a2a", fg="white",
                  activebackground="#555", relief="flat", width=2,
                  command=lambda: self.change_bpm(-1)).pack(
                      side="left", padx=(4, 0))

        self.bpm_label = tk.Label(
            transport, textvariable=self.bpm,
            bg="#1e1e1e", fg="#4CAF50",
            font=("Segoe UI", 13, "bold"), width=4)
        self.bpm_label.pack(side="left", padx=2)
        self.bpm_label.bind("<MouseWheel>", self._bpm_scroll)

        tk.Button(transport, text="+", font=("Segoe UI", 11),
                  bg="#2a2a2a", fg="white",
                  activebackground="#555", relief="flat", width=2,
                  command=lambda: self.change_bpm(1)).pack(
                      side="left", padx=(0, 4))

        self.time_label = tk.Label(
            transport, text="00:00.000",
            bg="#0f0f0f", fg="#cccccc",
            font=("Consolas", 11))
        self.time_label.pack(side="left", padx=20)

        # Métronome
        tk.Frame(transport, bg="#333333", width=2).pack(
            side="left", fill="y", padx=8)

        tk.Label(transport, text="Signature :",
                 bg="#0f0f0f", fg="#888888",
                 font=("Segoe UI", 8)).pack(side="left")

        self.sig_var = tk.IntVar(value=4)
        sig_cb = tk.OptionMenu(transport, self.sig_var, 2, 3, 4, 6, 7, 8,
                               command=lambda v: self._on_sig_change(v))
        sig_cb.config(bg="#1e1e1e", fg="white",
                      activebackground="#333",
                      highlightthickness=0,
                      relief="flat", font=("Segoe UI", 8), width=2)
        sig_cb["menu"].config(bg="#1e1e1e", fg="white")
        sig_cb.pack(side="left", padx=4)

        # Indicateur de beat (clignotant)
        self.beat_indicator = tk.Canvas(
            transport, width=18, height=18,
            bg="#0f0f0f", highlightthickness=0)
        self.beat_indicator.pack(side="left", padx=4)
        self._beat_dot = self.beat_indicator.create_oval(
            2, 2, 16, 16, fill="#333333", outline="")

        # Bouton métronome ON/OFF
        self.btn_metro = tk.Button(
            transport, text="🎵 Métronome",
            font=("Segoe UI", 9, "bold"),
            bg="#2a2a2a", fg="#888888",
            activebackground="#FFC107",
            relief="flat", padx=10, pady=2,
            cursor="hand2",
            command=self._toggle_metronome)
        self.btn_metro.pack(side="left", padx=4)

        # Droite — raccourci rapide import seulement
        tk.Button(transport, text="📂 Import",
                  command=self.import_audio,
                  bg="#2a2a2a", fg="white",
                  activebackground="#4CAF50", activeforeground="white",
                  relief="flat", padx=10, pady=2,
                  font=("Segoe UI", 9, "bold")).pack(side="right", padx=6)

    # ============================================================
    # PANEL PRINCIPAL
    # ============================================================
    def _build_main(self):
        main_frame = tk.Frame(self.root, bg="#141414")
        main_frame.pack(fill="both", expand=True)

        self.track_panel = tk.Frame(main_frame, bg="#1a1a1a", width=160)
        self.track_panel.pack(side="left", fill="y")
        self.track_panel.pack_propagate(False)
        tk.Frame(self.track_panel, bg="#111111", height=30).pack(fill="x")
        self.track_labels_frame = tk.Frame(self.track_panel, bg="#1a1a1a")
        self.track_labels_frame.pack(fill="both", expand=True)

        timeline_frame = tk.Frame(main_frame, bg="#1e1e1e")
        timeline_frame.pack(side="left", fill="both", expand=True)

        self.ruler = tk.Canvas(timeline_frame, bg="#111111",
                               height=30, highlightthickness=0)
        self.ruler.pack(fill="x")
        self.ruler.bind("<ButtonPress-1>", self._ruler_click)

        self.canvas = tk.Canvas(timeline_frame, bg="#1e1e1e",
                                highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        h_scroll = tk.Scrollbar(timeline_frame, orient="horizontal",
                                command=self._scroll_x)
        h_scroll.pack(fill="x")
        self.canvas.configure(xscrollcommand=h_scroll.set,
                              scrollregion=(0, 0, 6000, 2000))

        self.canvas.bind("<Motion>",        self._on_canvas_motion)
        self.canvas.bind("<ButtonPress-1>", self._canvas_click_bg)

    # ============================================================
    # RULER / GRID / PLAYHEAD
    # ============================================================
    def draw_ruler(self):
        for i in range(200):
            x = i * self.pixels_per_second
            self.ruler.create_line(x, 20, x, 30, fill="#555555")
            if i % 5 == 0:
                self.ruler.create_text(x + 4, 10, text=f"{i}s",
                                       fill="#888888",
                                       font=("Segoe UI", 7), anchor="w")

    def _scroll_x(self, *args):
        self.canvas.xview(*args)
        self.ruler.xview(*args)

    def _ruler_click(self, event):
        x = self.ruler.canvasx(event.x)
        self.playhead_pos = max(0.0, x / self.pixels_per_second)
        self._draw_playhead()
        self._update_time_label()

    def draw_grid(self):
        for i in range(200):
            x = i * self.pixels_per_second
            self.canvas.create_line(x, 0, x, 2000, fill="#2a2a2a", tags="grid")
        for i in range(40):
            y = i * self.track_height
            self.canvas.create_line(0, y, 6000, y, fill="#333333", tags="grid")

    def _draw_playhead(self):
        if self.playhead_line:
            self.canvas.delete(self.playhead_line)
            self.ruler.delete("playhead_ruler")
        x = self.playhead_pos * self.pixels_per_second
        self.playhead_line = self.canvas.create_line(
            x, 0, x, 4000, fill="#ff4444", width=2, tags="playhead")
        self.ruler.create_line(
            x, 0, x, 30, fill="#ff4444", width=2, tags="playhead_ruler")
        self.canvas.tag_raise("playhead")

    def _update_time_label(self):
        ms = int(self.playhead_pos * 1000)
        m  = ms // 60000
        s  = (ms % 60000) // 1000
        ms = ms % 1000
        self.time_label.config(text=f"{m:02}:{s:02}.{ms:03}")

    def _get_total_duration(self):
        total = 0.0
        for clip in self.clips.values():
            end = clip["start"] + clip["duration"]
            if end > total:
                total = end
        return total

    # ============================================================
    # TRANSPORT
    # ============================================================
    def play(self):
        if self.is_playing:
            return
        # Debug : vérifier les clips
        print(f"[GUI] play() — {len(self.clips)} clip(s) sur la timeline")
        for rect_id, clip in self.clips.items():
            fp = clip.get("filepath")
            print(f"  clip: start={clip.get('start'):.2f}s  "
                  f"dur={clip.get('duration'):.2f}s  "
                  f"file={fp}")
            if fp and not os.path.exists(fp):
                print(f"  ⚠ FICHIER INTROUVABLE : {fp}")
        self.is_playing       = True
        self.btn_play._set_color("#66BB6A")
        self._play_start_time = time.time()
        self._play_start_pos  = self.playhead_pos
        self._total_duration  = self._get_total_duration()
        self.engine.play_clips(clips=self.clips,
                               start_pos=self.playhead_pos,
                               bpm=self.bpm.get())
        # Sync métronome si actif
        if self._metro_on:
            self.metronome.stop()
            self.metronome.start(
                bpm=self.bpm.get(),
                beats_per_bar=self.sig_var.get(),
                on_beat=self._on_beat)
        self._tick_playhead()

    def stop(self):
        self.is_playing = False
        self.btn_play._set_color("#4CAF50")
        self.engine.stop()
        # Arrêter le métronome seulement s'il était lancé par le play
        # (pas s'il tourne en mode standalone)
        self.playhead_pos = 0.0
        self._draw_playhead()
        self._update_time_label()

    def _tick_playhead(self):
        if not self.is_playing:
            return
        try:
            elapsed = time.time() - self._play_start_time
            new_pos = self._play_start_pos + elapsed
            if self._total_duration > 0 and new_pos >= self._total_duration:
                self.playhead_pos = self._total_duration
                self._draw_playhead()
                self._update_time_label()
                self.is_playing = False
                self.btn_play._set_color("#4CAF50")
                self.engine.stop()
                return
            self.playhead_pos = new_pos
            self._draw_playhead()
            self._update_time_label()
            self.root.after(30, self._tick_playhead)
        except Exception as e:
            print(f"[GUI] Erreur tick playhead : {e}")
            self.is_playing = False

    def change_bpm(self, delta):
        self.bpm.set(max(40, min(300, self.bpm.get() + delta)))
        # Mettre à jour le métronome et la grille à la volée
        if self._metro_on:
            self.metronome.update_bpm(self.bpm.get())
        self._redraw_grid_and_ruler()

    def _bpm_scroll(self, event):
        self.change_bpm(1 if event.delta > 0 else -1)

    def _on_sig_change(self, val):
        self.metronome.update_sig(int(val))
        self._redraw_grid_and_ruler()

    # ============================================================
    # MÉTRONOME
    # ============================================================
    def _toggle_metronome(self):
        if self._metro_on:
            self.metronome.stop()
            self._metro_on = False
            self.btn_metro.config(bg="#2a2a2a", fg="#888888",
                                   text="🎵 Métronome")
            # Éteindre l'indicateur
            self.beat_indicator.itemconfig(self._beat_dot, fill="#333333")
        else:
            self._metro_on = True
            self.btn_metro.config(bg="#FFC107", fg="#0a0a0a",
                                   text="🎵 Métronome ●")
            self.metronome.start(
                bpm=self.bpm.get(),
                beats_per_bar=self.sig_var.get(),
                on_beat=self._on_beat)

    def _on_beat(self, beat_num, is_accent):
        """Callback appelé par le métronome à chaque temps."""
        color = "#FFC107" if is_accent else "#4CAF50"
        def _flash():
            self.beat_indicator.itemconfig(self._beat_dot, fill=color)
            self.root.after(80, lambda:
                self.beat_indicator.itemconfig(self._beat_dot, fill="#333333"))
        self.root.after(0, _flash)

    # ============================================================
    # GRILLE EN MESURES (selon BPM)
    # ============================================================
    def _redraw_grid_and_ruler(self):
        """Redessine la grille et la règle selon le BPM actuel."""
        self.canvas.delete("grid")
        self.ruler.delete("all")
        self.draw_ruler()
        self.draw_grid()
        self._draw_playhead()

    def draw_ruler(self):
        """Règle avec mesures et temps selon le BPM."""
        bpm       = self.bpm.get()
        sig       = getattr(self, 'sig_var', None)
        beats_bar = sig.get() if sig else 4
        beat_sec  = 60.0 / bpm
        bar_sec   = beat_sec * beats_bar
        bar_px    = bar_sec * self.pixels_per_second
        beat_px   = beat_sec * self.pixels_per_second

        total_px  = 6000
        bar_count = 0

        x = 0.0
        while x < total_px:
            xi = int(x)
            # Ligne de mesure (grande)
            self.ruler.create_line(xi, 0, xi, 30,
                                   fill="#666666", width=1)
            # Numéro de mesure
            self.ruler.create_text(
                xi + 4, 9,
                text=f"{bar_count + 1}",
                fill="#aaaaaa",
                font=("Segoe UI", 7, "bold"),
                anchor="w")

            # Temps internes (petits traits)
            for b in range(1, beats_bar):
                bx = xi + int(b * beat_px)
                if bx < total_px:
                    self.ruler.create_line(bx, 18, bx, 30,
                                           fill="#444444", width=1)

            x += bar_px
            bar_count += 1

    def draw_grid(self):
        """Grille avec lignes de mesure et de temps selon le BPM."""
        bpm       = self.bpm.get()
        sig       = getattr(self, 'sig_var', None)
        beats_bar = sig.get() if sig else 4
        beat_sec  = 60.0 / bpm
        bar_sec   = beat_sec * beats_bar
        bar_px    = bar_sec * self.pixels_per_second
        beat_px   = beat_sec * self.pixels_per_second

        total_px = 6000
        x = 0.0
        bar = 0
        while x < total_px:
            xi = int(x)
            # Ligne de mesure (plus visible)
            self.canvas.create_line(xi, 0, xi, 4000,
                                    fill="#2e2e2e", width=1,
                                    tags="grid")
            # Temps internes
            for b in range(1, beats_bar):
                bx = xi + int(b * beat_px)
                if bx < total_px:
                    self.canvas.create_line(bx, 0, bx, 4000,
                                            fill="#222222", width=1,
                                            tags="grid")
            x += bar_px
            bar += 1

        # Lignes horizontales des pistes
        for i in range(40):
            y = i * self.track_height
            self.canvas.create_line(0, y, total_px, y,
                                    fill="#333333", tags="grid")

    # ============================================================
    # UNDO / REDO
    # ============================================================
    def _snapshot(self):
        """Sauvegarde l'état actuel des clips pour undo."""
        snap = {}
        for rect_id, clip in self.clips.items():
            snap[rect_id] = {
                k: v for k, v in clip.items()
                if k not in ("rect", "txt")
            }
            snap[rect_id]["coords"] = self.canvas.coords(rect_id)
            snap[rect_id]["txt_coords"] = self.canvas.coords(clip["txt"])
        self._undo_stack.append(snap)
        self._redo_stack.clear()
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)

    def undo(self):
        if not self._undo_stack:
            return
        # Sauvegarde état courant dans redo
        cur = {}
        for rect_id, clip in self.clips.items():
            cur[rect_id] = {k: v for k, v in clip.items()
                            if k not in ("rect", "txt")}
            cur[rect_id]["coords"] = self.canvas.coords(rect_id)
            cur[rect_id]["txt_coords"] = self.canvas.coords(clip["txt"])
        self._redo_stack.append(cur)

        snap = self._undo_stack.pop()
        self._restore_snapshot(snap)

    def redo(self):
        if not self._redo_stack:
            return
        snap = self._redo_stack.pop()
        self._restore_snapshot(snap)

    def _restore_snapshot(self, snap):
        # Supprimer clips actuels
        for rect_id, clip in list(self.clips.items()):
            self.canvas.delete(clip["tag"])
        self.clips.clear()

        # Recréer depuis snapshot
        for rect_id, data in snap.items():
            self.create_clip(
                track_index=data["track"],
                start=data["start"],
                duration=data["duration"],
                label=data["label"],
                filepath=data.get("filepath"),
            )

    # ============================================================
    # ÉDITION
    # ============================================================
    def _canvas_click_bg(self, event):
        """Désélectionne si clic sur fond."""
        items = self.canvas.find_overlapping(
            self.canvas.canvasx(event.x) - 2,
            self.canvas.canvasy(event.y) - 2,
            self.canvas.canvasx(event.x) + 2,
            self.canvas.canvasy(event.y) + 2)
        if not any(i in self.clips for i in items):
            self._deselect_all()

    def _select_clip(self, rect_id):
        self._deselect_all()
        self._selected_clip = rect_id
        self.canvas.itemconfig(rect_id, outline="#FFD700", width=2)

    def _deselect_all(self):
        if self._selected_clip and self._selected_clip in self.clips:
            self.canvas.itemconfig(self._selected_clip,
                                   outline="#0077b6", width=1)
        self._selected_clip = None

    def _delete_selected(self):
        if not self._selected_clip:
            return
        self._snapshot()
        self._delete_clip(self._selected_clip)
        self._selected_clip = None

    def _duplicate_selected(self):
        if not self._selected_clip or self._selected_clip not in self.clips:
            return
        self._snapshot()
        clip = self.clips[self._selected_clip]
        self.create_clip(
            track_index=clip["track"],
            start=clip["start"] + clip["duration"] + 0.1,
            duration=clip["duration"],
            label=clip["label"] + "_copy",
            filepath=clip.get("filepath"),
        )

    def _select_all(self):
        for rect_id in self.clips:
            self.canvas.itemconfig(rect_id, outline="#FFD700", width=2)
        if self.clips:
            self._selected_clip = list(self.clips.keys())[-1]

    # ============================================================
    # HISTORIQUE
    # ============================================================
    def _open_history_window(self):
        HistoryWindow(self.root, on_import=self._import_from_history)

    def _import_from_history(self, filepath):
        """Importe un fichier depuis l'historique dans la timeline."""
        if not filepath or not os.path.exists(filepath):
            messagebox.showerror("Erreur", f"Fichier introuvable :\n{filepath}")
            return
        name = os.path.splitext(os.path.basename(filepath))[0]
        try:
            info     = sf.info(filepath)
            duration = info.duration
        except Exception:
            duration = 4.0
        track = self._find_free_track(self.playhead_pos, duration)
        self._snapshot()
        self.create_clip(track, self.playhead_pos, duration,
                         label=name, filepath=filepath)

    # ============================================================
    # DOSSIERS
    # ============================================================
    def _open_samples_folder(self):
        os.startfile(SAMPLES_DIR)

    def _open_recordings_folder(self):
        os.startfile(REC_DIR)

    def _open_projects_folder(self):
        os.startfile(PROJECTS_DIR)

    # ============================================================
    # PROJETS
    # ============================================================
    def _new_project(self):
        if self.clips:
            ok = messagebox.askyesno(
                "Nouveau projet",
                "Créer un nouveau projet ?\nLes modifications non sauvegardées seront perdues.")
            if not ok:
                return

        # Dialog nom du projet
        dialog = tk.Toplevel(self.root)
        dialog.title("Nouveau projet")
        dialog.configure(bg="#0f0f0f")
        dialog.resizable(False, False)
        w, h = 380, 170
        sw = dialog.winfo_screenwidth()
        sh = dialog.winfo_screenheight()
        dialog.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        dialog.grab_set()

        tk.Label(dialog, text="Nom du projet :",
                 bg="#0f0f0f", fg="#cccccc",
                 font=("Segoe UI", 10, "bold")).pack(pady=(22, 6))

        name_var = tk.StringVar(value="Mon projet")
        entry = tk.Entry(dialog, textvariable=name_var,
                         bg="#1e1e1e", fg="white",
                         insertbackground="white",
                         font=("Segoe UI", 11),
                         relief="flat", width=32)
        entry.pack(ipady=7, padx=20)
        entry.select_range(0, "end")
        entry.focus_set()

        def _confirm():
            nom = name_var.get().strip() or "Nouveau projet"
            for clip in list(self.clips.values()):
                self.canvas.delete(clip["tag"])
            self.clips.clear()
            self._undo_stack.clear()
            self._redo_stack.clear()
            self._current_project = None
            self.bpm.set(120)
            self.root.title(f"mini_daw — {nom}")
            dialog.destroy()

        entry.bind("<Return>", lambda e: _confirm())

        bf = tk.Frame(dialog, bg="#0f0f0f")
        bf.pack(pady=14)
        tk.Button(bf, text="✔  Créer",
                  bg="#4CAF50", fg="white", relief="flat",
                  padx=16, pady=7, cursor="hand2",
                  font=("Segoe UI", 9, "bold"),
                  command=_confirm).pack(side="left", padx=6)
        tk.Button(bf, text="✕  Annuler",
                  bg="#2a2a2a", fg="white", relief="flat",
                  padx=12, pady=7, cursor="hand2",
                  font=("Segoe UI", 9),
                  command=dialog.destroy).pack(side="left", padx=6)


    def _open_project(self):
        """Ouvre un projet .mdaw via l'explorateur intégré."""
        def _handle(path):
            if not path:
                return
            ext = os.path.splitext(path)[1].lower()

            # Si c'est un fichier audio → import direct sur timeline
            audio_exts = {".wav",".mp3",".flac",".ogg",".aiff",".aif",
                          ".m4a",".wma",".aac",".opus"}
            if ext in audio_exts:
                self._import_from_path(path)
                return

            # Si ce n'est pas un .mdaw → erreur claire
            if ext != ".mdaw":
                messagebox.showwarning(
                    "Format inconnu",
                    f"Sélectionne un fichier projet (.mdaw)\n"
                    f"ou un fichier audio (.wav, .mp3...)\n\n"
                    f"Fichier sélectionné : {os.path.basename(path)}")
                return

            # Charger le projet .mdaw
            result = load_project(path)
            if not result:
                messagebox.showerror("Erreur",
                    "Impossible de charger ce projet.\n"
                    "Le fichier est peut-être corrompu.")
                return

            bpm, clips_list = result

            # Vider la timeline actuelle
            for clip in list(self.clips.values()):
                self.canvas.delete(clip["tag"])
            self.clips.clear()

            self.bpm.set(bpm)
            loaded = 0
            missing = []

            for c in clips_list:
                fp = c.get("filepath", "")
                if fp and not os.path.exists(fp):
                    print(f"[GUI] Fichier manquant : {fp}")
                    missing.append(os.path.basename(fp))
                    continue
                self.create_clip(
                    track_index = c.get("track",    0),
                    start       = c.get("start",    0.0),
                    duration    = c.get("duration", 4.0),
                    label       = c.get("label",    "Clip"),
                    filepath    = fp or None,
                )
                loaded += 1

            self._current_project = path
            self.root.title(f"mini_daw — {os.path.basename(path)}")
            print(f"[GUI] Projet chargé : {loaded} clip(s)")

            if missing:
                messagebox.showwarning(
                    "Fichiers manquants",
                    f"{len(missing)} fichier(s) audio introuvable(s) :\n" +
                    "\n".join(f"  • {m}" for m in missing[:8]) +
                    ("\n  ..." if len(missing) > 8 else "") +
                    "\n\nCes clips ont été ignorés.")

        FileExplorerWindow(self.root, on_import=_handle)


    def _save_project(self):
        if self._current_project:
            save_project(self._current_project, self.clips, self.bpm.get())
            self.root.title(
                f"Mini Python DAW — {os.path.basename(self._current_project)}")
        else:
            self._save_project_as()

    def _save_project_as(self):
        path = filedialog.asksaveasfilename(
            title="Sauvegarder le projet",
            initialdir=PROJECTS_DIR,
            defaultextension=".mdaw",
            filetypes=[("Projets Mini DAW", "*.mdaw")])
        if not path:
            return
        save_project(path, self.clips, self.bpm.get())
        self._current_project = path
        self.root.title(f"Mini Python DAW — {os.path.basename(path)}")

    # ============================================================
    # IMPORT AUDIO — Explorateur intégré
    # ============================================================
    def import_audio(self):
        """Ouvre l'explorateur de fichiers intégré mini_daw."""
        FileExplorerWindow(self.root, on_import=self._import_from_path)

    def import_from_disk(self):
        """Même explorateur intégré."""
        FileExplorerWindow(self.root, on_import=self._import_from_path)

    def _import_from_path(self, path):
        if not path or not os.path.exists(path):
            return
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            duration = sf.info(path).duration
        except Exception:
            duration = 4.0
        track = self._find_free_track(self.playhead_pos, duration)
        self._snapshot()
        self.create_clip(track, self.playhead_pos, duration,
                         label=name, filepath=path)

    # ============================================================
    # WEB IMPORTER / RECORDER / EXPORT / EDITOR
    # ============================================================
    def open_web_importer(self):
        WebImporterWindow(self.root, on_imported=self._on_web_imported)

    def _on_web_imported(self, filepath, duration):
        name  = os.path.splitext(os.path.basename(filepath))[0]
        track = self._find_free_track(self.playhead_pos, duration)
        self._snapshot()
        self.create_clip(track, self.playhead_pos, duration,
                         label=name, filepath=filepath)

    def open_recorder(self):
        RecorderWindow(self.root, on_recorded=self._on_recorded)

    def _on_recorded(self, filepath, duration):
        name  = os.path.splitext(os.path.basename(filepath))[0]
        track = self._find_free_track(self.playhead_pos, duration)
        self._snapshot()
        self.create_clip(track, self.playhead_pos, duration,
                         label=name, filepath=filepath)

    def open_export(self):
        ExportWindow(self.root, clips=self.clips)

    def _about(self):
        messagebox.showinfo(
            "À propos",
            "Mini Python DAW\nVersion 1.0\n\nCréé avec Python + tkinter")

    # ============================================================
    # MENU CONTEXTUEL (clic droit sur clip)
    # ============================================================
    def _show_clip_menu(self, event, rect_id):
        clip = self.clips.get(rect_id)
        if not clip:
            return
        self._select_clip(rect_id)
        menu = tk.Menu(self.root, tearoff=0,
                       bg="#1e1e1e", fg="white",
                       activebackground="#4CAF50",
                       activeforeground="white",
                       font=("Segoe UI", 9))
        menu.add_command(label=f"✏  {clip.get('label','Clip')}",
                         state="disabled",
                         font=("Segoe UI", 9, "bold"))
        menu.add_separator()
        menu.add_command(label="🎛  Éditeur (effets & découpe)",
                         command=lambda: self._open_clip_editor(rect_id))
        menu.add_command(label="📋  Dupliquer",
                         command=self._duplicate_selected)
        menu.add_separator()
        menu.add_command(label="🗑  Supprimer",
                         command=self._delete_selected)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _open_clip_editor(self, rect_id):
        clip = self.clips.get(rect_id)
        if not clip:
            return

        def on_updated(new_fp, new_dur):
            clip["filepath"] = new_fp
            clip["duration"] = new_dur
            # Utiliser la bbox stockée (polygon != rectangle)
            x0 = clip["x0"]
            y0 = clip["y0"]
            y1 = clip["y1"]
            x1 = x0 + new_dur * self.pixels_per_second
            clip["x1"] = x1
            self._redraw_clip(rect_id)
            self.canvas.itemconfig(rect_id, fill="#4CAF50")  # vert = édité

        ClipEditorWindow(self.root, clip_data=clip, on_updated=on_updated)

    def _delete_clip(self, rect_id):
        clip = self.clips.get(rect_id)
        if not clip:
            return
        self.canvas.delete(clip["tag"])
        del self.clips[rect_id]

    # ============================================================
    # TRACK
    # ============================================================
    def _make_round_slider(self, parent, var, mn, mx, color="#4CAF50", length=34):
        """Slider compact avec apparence arrondie via Canvas."""
        H  = 14
        cv = tk.Canvas(parent, width=length, height=H,
                       bg="#222222", highlightthickness=0, cursor="hand2")
        r  = H // 2

        def _draw(val=None):
            cv.delete("all")
            pct   = (var.get() - mn) / max(1, mx - mn)
            track_y = H // 2
            # Track arrondi (fond)
            cv.create_line(r, track_y, length - r, track_y,
                           fill="#444444", width=5, capstyle="round")
            # Track arrondi (rempli)
            fill_x = r + pct * (length - 2 * r)
            if fill_x > r:
                cv.create_line(r, track_y, fill_x, track_y,
                               fill=color, width=5, capstyle="round")
            # Thumb
            tx = int(r + pct * (length - 2 * r))
            cv.create_oval(tx - r + 1, 1, tx + r - 1, H - 1,
                           fill="white", outline="#cccccc")

        def _click(e):
            pct    = max(0, min(1, e.x / length))
            newval = int(mn + pct * (mx - mn))
            var.set(newval)
            _draw()

        def _drag(e):
            _click(e)

        cv.bind("<ButtonPress-1>",  _click)
        cv.bind("<B1-Motion>",      _drag)
        var.trace_add("write", lambda *_: _draw())
        _draw()
        return cv

    def create_track(self):
        idx = len(self.tracks)
        y   = idx * self.track_height
        self.canvas.create_rectangle(
            0, y, 6000, y + self.track_height,
            outline="#444444", fill="#1e1e1e", tags="track_bg")

        row = tk.Frame(self.track_labels_frame, bg="#222222",
                       height=self.track_height)
        row.pack(fill="x")
        row.pack_propagate(False)

        tk.Label(row, text=f"Track {idx + 1}",
                 bg="#222222", fg="white",
                 font=("Segoe UI", 8, "bold")).pack(
                     anchor="w", padx=6, pady=(6, 0))

        ctrl = tk.Frame(row, bg="#222222")
        ctrl.pack(anchor="w", padx=6, pady=2)

        # Vol
        vol_var = tk.IntVar(value=80)
        tk.Label(ctrl, text="V", bg="#222222", fg="#666666",
                 font=("Segoe UI", 7)).grid(row=0, column=0, padx=(0,2))
        vol_cv = self._make_round_slider(ctrl, vol_var, 0, 100,
                                         color="#4CAF50", length=44)
        vol_cv.grid(row=0, column=1, padx=(0, 6))

        # Pan
        pan_var = tk.IntVar(value=0)
        tk.Label(ctrl, text="P", bg="#222222", fg="#666666",
                 font=("Segoe UI", 7)).grid(row=0, column=2, padx=(0,2))
        pan_cv = self._make_round_slider(ctrl, pan_var, -50, 50,
                                          color="#00b4d8", length=44)
        pan_cv.grid(row=0, column=3)

        # Proxy Scale caché pour compatibilité engine
        vol = tk.Scale(row, variable=vol_var, from_=0, to=100,
                       orient="horizontal", showvalue=False)
        vol.place_forget()
        pan = tk.Scale(row, variable=pan_var, from_=-50, to=50,
                       orient="horizontal", showvalue=False)
        pan.place_forget()

        tk.Frame(self.track_labels_frame, bg="#2a2a2a", height=1).pack(fill="x")
        track_data = {"vol": vol, "pan": pan,
                      "vol_var": vol_var, "pan_var": pan_var,
                      "index": idx}
        self.tracks.append(track_data)

        # Connecter sliders → mettre à jour clips en temps réel
        def _on_vol_change(*_, ti=idx):
            v = self.tracks[ti]["vol_var"].get() / 100.0
            for clip in self.clips.values():
                if clip.get("track") == ti:
                    clip["volume"] = self.tracks[ti]["vol_var"].get()

        def _on_pan_change(*_, ti=idx):
            p = self.tracks[ti]["pan_var"].get() / 50.0  # -1.0 .. 1.0
            for clip in self.clips.values():
                if clip.get("track") == ti:
                    clip["pan"] = p

        vol_var.trace_add("write", _on_vol_change)
        pan_var.trace_add("write", _on_pan_change)
        return idx

    def _rounded_rect(self, x0, y0, x1, y1, r=8, fill="#00b4d8", outline="#0077b6", tags=()):
        """Dessine un rectangle à coins arrondis sur le canvas."""
        r = min(r, (x1-x0)//2, (y1-y0)//2)
        pts = [
            x0+r, y0,   x1-r, y0,
            x1,   y0,   x1,   y0+r,
            x1,   y1-r, x1,   y1,
            x1-r, y1,   x0+r, y1,
            x0,   y1,   x0,   y1-r,
            x0,   y0+r, x0,   y0,
            x0+r, y0,
        ]
        return self.canvas.create_polygon(
            pts, smooth=True,
            fill=fill, outline=outline, width=1,
            tags=tags)

    def _find_free_track(self, start, duration):
        for t in range(len(self.tracks)):
            occupied = False
            for clip in self.clips.values():
                if clip["track"] == t:
                    cs, ce = clip["start"], clip["start"] + clip["duration"]
                    if not (start + duration <= cs or start >= ce):
                        occupied = True
                        break
            if not occupied:
                return t
        return 0

    # ============================================================
    # CLIP
    # ============================================================
    def create_clip(self, track_index, start, duration,
                    label="Clip", filepath=None):
        x0 = start    * self.pixels_per_second
        x1 = (start + duration) * self.pixels_per_second

        # Clips 50% plus petits en hauteur, centrés dans la piste
        clip_h   = int(self.track_height * 0.50)
        margin_y = (self.track_height - clip_h) // 2
        y0 = track_index * self.track_height + margin_y
        y1 = y0 + clip_h

        clip_id = len(self.clips) + int(time.time() * 1000) % 100000
        tag     = f"clip_{clip_id}"

        rect = self._rounded_rect(
            x0, y0, x1, y1, r=7,
            fill="#00b4d8", outline="#0077b6",
            tags=(tag, "clip"))
        txt = self.canvas.create_text(
            x0 + 8, (y0 + y1) // 2,
            text=label, fill="white",
            font=("Segoe UI", 7, "bold"), anchor="w",
            tags=(tag, "clip"))

        # Récupérer vol/pan actuels de la piste
        track_vol = 80
        track_pan = 0
        if 0 <= track_index < len(self.tracks):
            track_vol = self.tracks[track_index]["vol_var"].get()
            track_pan = self.tracks[track_index]["pan_var"].get()

        self.clips[rect] = {
            "track":    track_index,
            "tag":      tag,
            "start":    start,
            "duration": duration,
            "label":    label,
            "filepath": filepath,
            "volume":   track_vol,
            "pan":      track_pan,
            "rect":     rect,
            "txt":      txt,
            # bbox stockée manuellement (polygon != rectangle)
            "x0": x0, "y0": y0, "x1": x1, "y1": y1,
        }
        self._bind_clip(tag, rect)
        self.canvas.tag_raise("playhead")
        return rect

    # ============================================================
    # BIND CLIP
    # ============================================================
    def _bind_clip(self, tag, rect_id):
        self.canvas.tag_bind(tag, "<ButtonPress-1>",
                             lambda e, r=rect_id: self._mouse_down(e, r))
        self.canvas.tag_bind(tag, "<B1-Motion>",
                             lambda e: self._mouse_move(e))
        self.canvas.tag_bind(tag, "<ButtonRelease-1>",
                             lambda e: self._mouse_up(e))
        self.canvas.tag_bind(tag, "<ButtonPress-3>",
                             lambda e, r=rect_id: self._show_clip_menu(e, r))

    def _clip_bbox(self, rect_id):
        """Retourne (x0,y0,x1,y1) depuis clip_data (fiable avec polygon)."""
        clip = self.clips.get(rect_id)
        if not clip:
            return None
        return clip["x0"], clip["y0"], clip["x1"], clip["y1"]

    def _redraw_clip(self, rect_id):
        """Redessine le polygon arrondi aux nouvelles coordonnées."""
        clip = self.clips.get(rect_id)
        if not clip:
            return
        x0, y0, x1, y1 = clip["x0"], clip["y0"], clip["x1"], clip["y1"]
        fill    = self.canvas.itemcget(rect_id, "fill")
        outline = self.canvas.itemcget(rect_id, "outline")
        tag     = clip["tag"]
        r = 7

        # Recalculer les points du polygon arrondi
        pts = [
            x0+r, y0,   x1-r, y0,
            x1,   y0,   x1,   y0+r,
            x1,   y1-r, x1,   y1,
            x1-r, y1,   x0+r, y1,
            x0,   y1,   x0,   y1-r,
            x0,   y0+r, x0,   y0,
            x0+r, y0,
        ]
        self.canvas.coords(rect_id, *pts)
        self.canvas.coords(clip["txt"], x0 + 8, (y0 + y1) // 2)

    def _get_resize_side(self, event, rect_id):
        """
        Retourne le côté de resize :
        'left'|'right' → longueur (↔)
        'top'|'bottom' → hauteur (↕)
        None → drag
        """
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        bbox = self._clip_bbox(rect_id)
        if not bbox:
            return None
        x0, y0, x1, y1 = bbox

        # Priorité aux bords gauche/droit (longueur)
        if cx <= x0 + RESIZE_ZONE:
            return "left"
        if cx >= x1 - RESIZE_ZONE:
            return "right"
        # Bords haut/bas (hauteur)
        if cy <= y0 + RESIZE_ZONE:
            return "top"
        if cy >= y1 - RESIZE_ZONE:
            return "bottom"
        return None

    def _on_canvas_motion(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        items  = self.canvas.find_overlapping(cx-4, cy-4, cx+4, cy+4)
        cursor = "arrow"
        for item in items:
            if item in self.clips:
                side = self._get_resize_side(event, item)
                if side in ("left", "right"):
                    cursor = "sb_h_double_arrow"   # ↔ longueur
                elif side in ("top", "bottom"):
                    cursor = "sb_v_double_arrow"   # ↕ hauteur
                else:
                    cursor = "fleur"               # déplacement
                break
        self.canvas.config(cursor=cursor)

    def _mouse_down(self, event, rect_id):
        self._select_clip(rect_id)
        side = self._get_resize_side(event, rect_id)
        if side:
            self._resize_side = side
            self._resize_item = rect_id
            self.drag_tag     = None
        else:
            self._resize_side = None
            self._resize_item = None
            self.drag_item    = rect_id
            self.drag_tag     = self.clips[rect_id]["tag"]
        self.drag_start_x = self.canvas.canvasx(event.x)
        self.drag_start_y = self.canvas.canvasy(event.y)

    def _mouse_move(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        if self._resize_item is not None:
            self._do_resize(cx, cy)
        elif self.drag_tag:
            dx = cx - self.drag_start_x
            dy = cy - self.drag_start_y
            self.canvas.move(self.drag_tag, dx, dy)
            self.drag_start_x = cx
            self.drag_start_y = cy

    def _do_resize(self, cx, cy=None):
        rect   = self._resize_item
        clip   = self.clips[rect]
        MIN_W  = self.pixels_per_second * 0.25
        MIN_H  = 16   # hauteur minimale en pixels
        x0, y0, x1, y1 = clip["x0"], clip["y0"], clip["x1"], clip["y1"]

        # --- Longueur (horizontal) ---
        if self._resize_side == "right":
            new_x1 = max(x0 + MIN_W, cx)
            clip["x1"]       = new_x1
            clip["duration"] = (new_x1 - x0) / self.pixels_per_second

        elif self._resize_side == "left":
            new_x0 = min(x1 - MIN_W, max(0, cx))
            clip["x0"]       = new_x0
            clip["start"]    = new_x0 / self.pixels_per_second
            clip["duration"] = (x1 - new_x0) / self.pixels_per_second

        # --- Hauteur (vertical) ---
        elif self._resize_side == "bottom" and cy is not None:
            track_y1 = clip["track"] * self.track_height + self.track_height - 4
            new_y1   = max(y0 + MIN_H, min(track_y1, cy))
            clip["y1"] = new_y1

        elif self._resize_side == "top" and cy is not None:
            track_y0 = clip["track"] * self.track_height + 4
            new_y0   = min(y1 - MIN_H, max(track_y0, cy))
            clip["y0"] = new_y0

        self._redraw_clip(rect)

    def _mouse_up(self, event):
        if self._resize_item is not None:
            rect = self._resize_item
            clip = self.clips[rect]
            snap = self.pixels_per_second / 2
            x0, y0, x1, y1 = clip["x0"], clip["y0"], clip["x1"], clip["y1"]

            if self._resize_side == "right":
                sx = max(x0 + snap * 0.5, round(x1 / snap) * snap)
                clip["x1"]       = sx
                clip["duration"] = (sx - x0) / self.pixels_per_second

            elif self._resize_side == "left":
                sx = max(0, min(x1 - snap * 0.5, round(x0 / snap) * snap))
                clip["x0"]       = sx
                clip["start"]    = sx / self.pixels_per_second
                clip["duration"] = (x1 - sx) / self.pixels_per_second

            # Hauteur : pas de snap, juste redessiner
            # (top/bottom déjà mis à jour dans _do_resize)

            self._redraw_clip(rect)
            self._resize_item = None
            self._resize_side = None

        elif self.drag_tag and self.drag_item is not None:
            rect = self.drag_item
            clip = self.clips.get(rect)  # récupérer AVANT d'utiliser
            if clip is None:
                self.drag_tag  = None
                self.drag_item = None
                return

            snap  = self.pixels_per_second / 2
            # Utiliser bbox stockée (polygon != rectangle)
            old_x0 = clip["x0"]
            old_x1 = clip["x1"]
            old_y0 = clip["y0"]
            old_y1 = clip["y1"]
            old_w  = old_x1 - old_x0
            old_h  = old_y1 - old_y0

            # Position x snappée
            sx = max(0, round(old_x0 / snap) * snap)

            # Piste depuis y centre
            y_center = (old_y0 + old_y1) / 2
            track    = int(y_center // self.track_height)
            track    = max(0, min(track, len(self.tracks) - 1))

            # Recalculer y centré sur la piste
            clip_h   = int(self.track_height * 0.50)
            margin_y = (self.track_height - clip_h) // 2
            y0 = track * self.track_height + margin_y
            y1 = y0 + clip_h

            clip["x0"]    = sx
            clip["x1"]    = sx + old_w
            clip["y0"]    = y0
            clip["y1"]    = y1
            clip["track"] = track
            clip["start"] = sx / self.pixels_per_second
            self._redraw_clip(rect)

            self.canvas.tag_raise("playhead")
            self.drag_tag  = None
            self.drag_item = None

    # ============================================================
    # FERMETURE
    # ============================================================
    def _on_close(self):
        try:
            self.metronome.stop()
        except Exception as e:
            print(f"[GUI] Erreur arrêt métronome : {e}")
        try:
            self.engine.cleanup()
        except Exception as e:
            print(f"[GUI] Erreur cleanup engine : {e}")
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


# ============================================================
# FENÊTRE HISTORIQUE
# ============================================================
class HistoryWindow:
    """Fenêtre affichant tous les fichiers audio du dossier samples/."""

    CATEGORIES = {
        "🌐 Téléchargés":    SAMPLES_DIR,
        "🎤 Enregistrements": REC_DIR,
        "✂ Édités":          EDITED_DIR,
    }

    def __init__(self, parent, on_import=None):
        self.parent    = parent
        self.on_import = on_import

        self.win = tk.Toplevel(parent)
        self.win.title("mini_daw — Historique des fichiers")
        self.win.configure(bg="#0f0f0f")
        self.win.geometry("560x500")
        self.win.resizable(True, True)

        try:
            ico = os.path.join(os.path.dirname(__file__), "assets", "logo.ico")
            if os.path.exists(ico):
                self.win.iconbitmap(ico)
        except Exception:
            pass

        self.win.grab_set()
        self._build_ui()

    def _build_ui(self):
        # En-tête
        hdr = tk.Frame(self.win, bg="#0a0a0a")
        hdr.pack(fill="x")
        tk.Label(hdr, text="mini_daw",
                 bg="#0a0a0a", fg="#4CAF50",
                 font=("Segoe UI", 11, "bold")).pack(side="left", padx=12, pady=8)
        tk.Label(hdr, text="📁 Historique des fichiers audio",
                 bg="#0a0a0a", fg="#FFC107",
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Frame(self.win, bg="#222222", height=1).pack(fill="x")

        # Onglets
        notebook = ttk.Notebook(self.win)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        style = ttk.Style()
        style.theme_use("default")
        style.configure("TNotebook",        background="#0f0f0f", borderwidth=0)
        style.configure("TNotebook.Tab",    background="#1e1e1e", foreground="white",
                         padding=[10, 4])
        style.map("TNotebook.Tab",
                  background=[("selected", "#4CAF50")],
                  foreground=[("selected", "white")])

        # Onglet "Tous"
        all_frame = self._make_tab(notebook, self._get_all_files())
        notebook.add(all_frame, text="📂 Tous")

        # Onglets par catégorie
        for label, folder in self.CATEGORIES.items():
            files = self._get_files_from(folder, recursive=False)
            frame = self._make_tab(notebook, files)
            notebook.add(frame, text=label)

        # Barre de boutons bas
        bot = tk.Frame(self.win, bg="#0a0a0a")
        bot.pack(fill="x", padx=12, pady=8)

        tk.Button(bot, text="📂  Ouvrir le dossier samples",
                  bg="#1a1a1a", fg="#FFC107",
                  activebackground="#FFC107", activeforeground="black",
                  relief="flat", padx=12, pady=6,
                  cursor="hand2",
                  font=("Segoe UI", 8),
                  command=lambda: os.startfile(SAMPLES_DIR)
                  ).pack(side="left", padx=(0, 6))

        tk.Button(bot, text="✕  Fermer",
                  bg="#2a2a2a", fg="white",
                  activebackground="#555",
                  relief="flat", padx=14, pady=6,
                  cursor="hand2",
                  font=("Segoe UI", 9),
                  command=self.win.destroy).pack(side="right")

    def _make_tab(self, parent, files):
        frame = tk.Frame(parent, bg="#0f0f0f")

        if not files:
            tk.Label(frame, text="Aucun fichier trouvé",
                     bg="#0f0f0f", fg="#555555",
                     font=("Segoe UI", 9)).pack(pady=20)
            return frame

        # Scrollable list
        canvas = tk.Canvas(frame, bg="#0f0f0f", highlightthickness=0)
        scroll = tk.Scrollbar(frame, orient="vertical",
                              command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg="#0f0f0f")
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(
                       scrollregion=canvas.bbox("all")))

        for fp in files:
            self._make_file_row(inner, fp)

        return frame

    def _make_file_row(self, parent, filepath):
        row = tk.Frame(parent, bg="#141414")
        row.pack(fill="x", pady=1, padx=4)

        name = os.path.basename(filepath)
        ext  = os.path.splitext(name)[1].lower()
        icon = "🎵" if ext in (".wav", ".flac", ".ogg", ".aiff") else "🎧"

        # Taille
        try:
            size_kb = os.path.getsize(filepath) // 1024
            size_str = f"{size_kb} KB"
        except Exception:
            size_str = ""

        # Durée
        dur_str = ""
        try:
            info    = sf.info(filepath)
            dur_str = f"{info.duration:.1f}s"
        except Exception:
            pass

        tk.Label(row, text=f"{icon} {name}",
                 bg="#141414", fg="white",
                 font=("Segoe UI", 8),
                 anchor="w").pack(side="left", padx=6, pady=4)

        tk.Label(row, text=f"{dur_str}  {size_str}",
                 bg="#141414", fg="#555555",
                 font=("Segoe UI", 7)).pack(side="left")

        btn_frame = tk.Frame(row, bg="#141414")
        btn_frame.pack(side="right", padx=4)

        # Bouton importer
        tk.Button(btn_frame, text="⊕ Importer",
                  bg="#00b4d8", fg="white",
                  activebackground="#0077b6",
                  relief="flat", padx=8, pady=2,
                  font=("Segoe UI", 7, "bold"),
                  cursor="hand2",
                  command=lambda f=filepath: self._do_import(f)
                  ).pack(side="left", padx=2)

        # Bouton ouvrir et selectionner dans explorateur Windows
        tk.Button(btn_frame, text="📂",
                  bg="#2a2a2a", fg="white",
                  activebackground="#555",
                  relief="flat", padx=6, pady=2,
                  font=("Segoe UI", 7),
                  cursor="hand2",
                  command=lambda f=filepath: self._reveal_file(f)
                  ).pack(side="left", padx=2)

    def _do_import(self, filepath):
        """Ferme la fenetre AVANT d'appeler le callback pour eviter le blocage du grab."""
        cb = self.on_import
        fp = filepath
        self.win.grab_release()
        self.win.destroy()
        if cb:
            cb(fp)

    def _reveal_file(self, filepath):
        """Ouvre l'explorateur Windows avec le fichier selectionne."""
        import subprocess
        try:
            subprocess.Popen(f'explorer /select,"{os.path.normpath(filepath)}"')
        except Exception:
            os.startfile(os.path.dirname(filepath))

    def _get_all_files(self):
        exts  = {".wav", ".mp3", ".flac", ".ogg", ".aiff"}
        files = []
        for root_dir, _, fnames in os.walk(SAMPLES_DIR):
            for f in sorted(fnames):
                if os.path.splitext(f)[1].lower() in exts:
                    files.append(os.path.join(root_dir, f))
        return files

    def _get_files_from(self, folder, recursive=False):
        exts  = {".wav", ".mp3", ".flac", ".ogg", ".aiff"}
        files = []
        if not os.path.exists(folder):
            return files
        if recursive:
            for root_dir, _, fnames in os.walk(folder):
                for f in sorted(fnames):
                    if os.path.splitext(f)[1].lower() in exts:
                        files.append(os.path.join(root_dir, f))
        else:
            for f in sorted(os.listdir(folder)):
                if os.path.splitext(f)[1].lower() in exts:
                    files.append(os.path.join(folder, f))
        return files


# Import pour ttk dans HistoryWindow
from tkinter import ttk
