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
from pattern_editor  import PatternEditorWindow
from project_manager import (
    new_project, save_project, save_project_as,
    save_as_template, load_project,
    list_projects, list_templates,
    export_wav, export_mp3, export_ogg,
    export_stems, export_zip, BUILTIN_TEMPLATES
)

RESIZE_ZONE  = 10
import sys as _sys
if getattr(_sys, "frozen", False):
    BASE_DIR = os.path.dirname(_sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLES_DIR  = os.path.join(BASE_DIR, "samples")
REC_DIR      = os.path.join(SAMPLES_DIR, "recordings")
EDITED_DIR   = os.path.join(SAMPLES_DIR, "edited")
PROJECTS_DIR = os.path.join(BASE_DIR,    "projects")

for d in [SAMPLES_DIR, REC_DIR, EDITED_DIR, PROJECTS_DIR]:
    os.makedirs(d, exist_ok=True)


class MiniDAWApp:
    def __init__(self, root):
        self.root = root
        self.root.title("mini_daw")
        self.root.configure(bg="#141414")
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.minsize(960, 540)

        # Icone principale
        try:
            _ico = os.path.join(BASE_DIR, "assets", "logo.ico")
            if os.path.exists(_ico):
                self.root.iconbitmap(_ico)
                self._ico_path = _ico
            else:
                self._ico_path = None
        except Exception:
            self._ico_path = None

        self.engine    = AudioEngine()
        self.metronome = Metronome()
        self._metro_on = False

        self.track_height      = 80
        self.pixels_per_second = 120
        self.tracks            = []
        self.clips             = {}
        self._current_project  = None
        self._project_dir      = None

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

        # Outil actif dans la timeline
        # "select" = déplacer/resize  "split" = couper au clic  "mute" = muter
        self._active_tool  = "select"

        # Drag / Resize
        self.drag_tag      = None
        self.drag_item     = None
        self.drag_start_x  = 0
        self.drag_start_y  = 0
        self._resize_side  = None
        self._resize_item  = None

        # Clip sélectionné (clic gauche)
        self._selected_clip  = None

        # Sélection multiple (lasso + bloc)
        self._selected_clips  = set()   # rect_ids sélectionnés
        self._lasso_active    = False
        self._lasso_start_x   = 0
        self._lasso_start_y   = 0
        self._lasso_rect      = None
        self._block_drag_x    = 0
        self._block_drag_y    = 0
        self._block_dragging  = False

        self._build_menu()
        self._build_transport()
        self._build_main()

        for i in range(5):
            self.create_track()

        # Un seul appel qui fait tout : ruler + grid + playhead
        self._redraw_grid_and_ruler()
        # S'assurer que la vue commence à 0
        self.canvas.xview_moveto(0)
        self.ruler.xview_moveto(0)
        # Charger le recovery si disponible
        self.root.after(200, self._load_recovery)
        # Auto-save toutes les 2 minutes
        self._auto_save_loop()
        self.root.bind("<Control-z>", lambda e: self.undo())
        self.root.bind("<Control-y>", lambda e: self.redo())
        self.root.bind("<Control-s>", lambda e: self._save_project())
        self.root.bind("<Control-n>", lambda e: self._new_project())
        self.root.bind("<Control-o>", lambda e: self._open_project())
        self.root.bind("<Control-q>", lambda e: self._on_close())
        self.root.bind("<Delete>",    lambda e: self._delete_selected())
        self.root.bind("<Control-d>", lambda e: self._duplicate_selected())
        self.root.bind("<Control-a>", lambda e: self._select_all())
    def load_project(self, path):
        print(f"[GUI] Chargement projet : {path}")
        try:
             if hasattr(self, "project_manager"):
                  self.project_manager.load_project(path)
             else:
                 print("[GUI] project_manager non trouvé")
        except Exception as e:
            print(f"[GUI] Erreur load_project : {e}")


    def import_audio(self, path):
        print(f"[GUI] Import audio : {path}")
        try:
             if hasattr(self, "project_manager"):
                 self.project_manager.import_audio_file(path)
             else:
                 print("[GUI] project_manager non trouvé")
        except Exception as e:
            print(f"[GUI] Erreur import_audio : {e}")
    # ============================================================
    # HELPER ICONE
    # ============================================================
    def _apply_icon(self, win):
        """Applique l icone mini_daw a une fenetre Toplevel."""
        try:
            ico = getattr(self, '_ico_path', None)
            if ico and os.path.exists(ico):
                win.iconbitmap(ico)
        except Exception:
            pass

    # ============================================================
    # RECHARGEMENT PROJET APRÈS SAVE AS
    # ============================================================
    def _reload_project_after_save(self, mdaw_path: str):
        """
        Recharge silencieusement le projet depuis le .mdaw
        après un Save As pour synchroniser tous les chemins de clips.
        Ne pose aucune question — le fichier vient d être sauvegardé,
        tout doit exister.
        """
        from project_manager import load_project as _load
        result = _load(mdaw_path)
        if not result:
            return
        bpm, clips_list, missing_list, meta = result

        # Effacer les clips actuels du canvas
        for clip in list(self.clips.values()):
            self.canvas.delete(clip["tag"])
        self.clips.clear()

        # Recréer depuis le .mdaw rechargé
        self.bpm.set(bpm)
        self._current_project = mdaw_path
        self._project_dir     = os.path.dirname(mdaw_path)

        for c in clips_list:
            if c.get("missing"):
                # Ne devrait pas arriver juste après un save — on skip
                print(f"[GUI] Avertissement : {c.get('filepath')} manquant après save")
                continue
            self.create_clip(
                track_index = c.get("track",    0),
                start       = c.get("start",    0.0),
                duration    = c.get("duration", 4.0),
                label       = c.get("label",    "Clip"),
                filepath    = c.get("filepath") or None,
                color       = c.get("color")    or None,
            )
        name = meta.get("name", "")
        self.root.title(f"mini_daw — {name}")
        # Invalider tout le cache engine
        try:
            self.engine.invalidate_cache(None)
        except Exception:
            pass
        print(f"[GUI] Projet rechargé après Save As : {name}")

    # ============================================================
    # RECHERCHE FICHIER MANQUANT
    # ============================================================
    def _search_missing_file(self, filename: str) -> str:
        """
        Cherche automatiquement un fichier manquant dans les dossiers connus.
        Retourne le chemin complet si trouve, sinon None.
        """
        if not filename:
            return None

        # Dossiers a chercher en priorite
        search_dirs = []
        if getattr(self, "_project_dir", None) and os.path.isdir(self._project_dir):
            search_dirs.append(self._project_dir)
            # Sous-dossier audio/ du projet
            audio_sub = os.path.join(self._project_dir, "audio")
            if os.path.isdir(audio_sub):
                search_dirs.append(audio_sub)
        # Dossiers DAW standards
        search_dirs += [SAMPLES_DIR, REC_DIR, EDITED_DIR, PROJECTS_DIR]
        # Bureau et Documents utilisateur
        search_dirs += [
            os.path.join(os.path.expanduser("~"), "Desktop"),
            os.path.join(os.path.expanduser("~"), "Documents"),
            os.path.join(os.path.expanduser("~"), "Music"),
            os.path.join(os.path.expanduser("~"), "Downloads"),
        ]

        name_lower = filename.lower()
        for folder in search_dirs:
            if not os.path.isdir(folder):
                continue
            # Cherche recursivement (max 3 niveaux)
            for root_dir, dirs, files in os.walk(folder):
                depth = root_dir.replace(folder, "").count(os.sep)
                if depth > 3:
                    dirs.clear()
                    continue
                for f in files:
                    if f.lower() == name_lower:
                        found = os.path.join(root_dir, f)
                        print(f"[GUI] Fichier retrouve automatiquement : {found}")
                        return found
        return None

    # ============================================================
    # MENU BAR
    # ============================================================
    def _build_menu(self):
        menubar = tk.Menu(self.root, bg="white", fg="#111111",
                          activebackground="#4CAF50",
                          activeforeground="white",
                          relief="flat")

        def _menu(parent):
            return tk.Menu(parent, tearoff=0,
                           bg="white", fg="#111111",
                           activebackground="#4CAF50",
                           activeforeground="white",
                           font=("Segoe UI", 9))

        # --- Fichier ---
        file_menu = _menu(menubar)

        # NEW
        new_sub = _menu(file_menu)
        new_sub.add_command(label="Empty Project",
                            command=self._new_project)
        new_sub.add_separator()
        for tmpl_name in BUILTIN_TEMPLATES:
            new_sub.add_command(
                label=tmpl_name,
                command=lambda t=tmpl_name: self._new_from_template(t))
        file_menu.add_cascade(label="New", menu=new_sub)

        # NEW FROM TEMPLATE (raccourci direct)
        file_menu.add_command(label="New from Template...",
                              command=self._new_from_template_dialog)
        file_menu.add_separator()

        # OPEN / SAVE
        file_menu.add_command(label="Open",
                              accelerator="Ctrl+O",
                              command=self._open_project)
        file_menu.add_command(label="Save",
                              accelerator="Ctrl+S",
                              command=self._save_project)
        file_menu.add_command(label="Save As...",
                              command=self._save_project_as_dialog)
        file_menu.add_command(label="Save As Template...",
                              command=self._save_as_template_dialog)
        file_menu.add_separator()

        # IMPORT
        file_menu.add_command(label="Import",
                              command=self._import_dialog)
        file_menu.add_separator()

        # EXPORT
        export_sub = _menu(file_menu)
        export_sub.add_command(label="Wave File (.wav)",
                               command=lambda: self._export_dialog("wav"))
        export_sub.add_command(label="MP3 File (.mp3)",
                               command=lambda: self._export_dialog("mp3"))
        export_sub.add_command(label="OGG File (.ogg)",
                               command=lambda: self._export_dialog("ogg"))
        export_sub.add_separator()
        export_sub.add_command(label="All Playlist Tracks (stems)",
                               command=self._export_stems_dialog)
        export_sub.add_separator()
        export_sub.add_command(label="Zipped Loop Package (.zip)",
                               command=self._export_zip_dialog)
        file_menu.add_cascade(label="Export", menu=export_sub)
        file_menu.add_separator()

        file_menu.add_command(label="Quit",
                              accelerator="Ctrl+Q",
                              command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        # --- Édition ---
        edit_menu = tk.Menu(menubar, tearoff=0,
                            bg="white", fg="#111111",
                            activebackground="#4CAF50",
                            activeforeground="white")
        edit_menu.add_command(label="↩  Undo",
                              accelerator="Ctrl+Z",
                              command=self.undo)
        edit_menu.add_command(label="↪  Redo",
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
        menubar.add_cascade(label="Edit", menu=edit_menu)

        # --- Affichage ---
        view_menu = tk.Menu(menubar, tearoff=0,
                            bg="white", fg="#111111",
                            activebackground="#4CAF50",
                            activeforeground="white",
                            font=("Segoe UI", 9))
        view_menu.add_command(label="📁  Samples",
                              command=self._open_samples_folder)
        view_menu.add_command(label="🎤  Recordings",
                              command=self._open_recordings_folder)
        view_menu.add_command(label="🗂  Projects",
                              command=self._open_projects_folder)
        menubar.add_cascade(label="View", menu=view_menu)

        # --- Aide ---
        help_menu = tk.Menu(menubar, tearoff=0,
                            bg="white", fg="#111111",
                            activebackground="#4CAF50",
                            activeforeground="white")
        help_menu.add_command(label="ℹ  À propos",
                              command=self._about)
        # --- ADD ---
        add_menu = _menu(menubar)
        add_menu.add_command(label="Channel (Instrument / Generator)", command=self._add_channel)
        add_menu.add_command(label="Effect (Plugin to Mixer)", command=self._add_effect)
        add_menu.add_separator()
        add_menu.add_command(label="View Plugin Picker", command=self._view_plugin_picker)
        add_menu.add_separator()
        browse_sub = _menu(add_menu)
        browse_sub.add_command(label="Plugin Database", command=lambda: self._browse_plugins("database"))
        browse_sub.add_command(label="Installed Plugins", command=lambda: self._browse_plugins("installed"))
        browse_sub.add_command(label="Presets", command=lambda: self._browse_plugins("presets"))
        add_menu.add_cascade(label="Browse", menu=browse_sub)
        add_menu.add_separator()
        add_menu.add_command(label="Refresh Plugin List  (Fast Scan)", command=self._refresh_plugins)
        add_menu.add_command(label="Manage Plugins", command=self._manage_plugins)
        add_menu.add_separator()
        add_menu.add_command(label="Automation for Last Tweaked Parameter", command=self._add_automation)
        add_menu.add_command(label="Pattern", command=self.open_pattern_editor)
        menubar.add_cascade(label="ADD", menu=add_menu)

        menubar.add_cascade(label="Help", menu=help_menu)

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

    @staticmethod
    def _darken(hex_color):
        try:
            rv = max(0, int(hex_color[1:3], 16) - 40)
            gv = max(0, int(hex_color[3:5], 16) - 40)
            bv = max(0, int(hex_color[5:7], 16) - 40)
            return f"#{rv:02x}{gv:02x}{bv:02x}"
        except Exception:
            return hex_color

    def _round_btn(self, parent, text, bg, fg, command, size=36, r=10):
        """Bouton Canvas arrondi réutilisable."""
        cv = tk.Canvas(parent, width=size, height=size,
                       bg="#0f0f0f", highlightthickness=0, cursor="hand2")
        def _draw(color=bg):
            try:
                cv.delete("all")
                cv.create_rectangle(r, 0, size-r, size, fill=color, outline="")
                cv.create_rectangle(0, r, size, size-r, fill=color, outline="")
                cv.create_oval(0, 0, r*2, r*2, fill=color, outline="")
                cv.create_oval(size-r*2, 0, size, r*2, fill=color, outline="")
                cv.create_oval(0, size-r*2, r*2, size, fill=color, outline="")
                cv.create_oval(size-r*2, size-r*2, size, size, fill=color, outline="")
                cv.create_text(size//2, size//2, text=text, fill=fg,
                               font=("Segoe UI", 11, "bold"))
            except Exception:
                pass
        _draw()
        cv.bind("<ButtonPress-1>",   lambda e: (_draw("#555555"), command()))
        cv.bind("<ButtonRelease-1>", lambda e: _draw(bg))
        cv.bind("<Enter>",           lambda e: _draw(self._lighten(bg)))
        cv.bind("<Leave>",           lambda e: _draw(bg))
        def _safe_set_color(color):
            try:
                _draw(color)
            except Exception:
                pass
        cv._set_color = _safe_set_color
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

        # Bouton Pattern
        self.btn_pattern = tk.Button(
            transport, text="PAT",
            font=("Segoe UI", 8, "bold"),
            bg="#534AB7", fg="white",
            activebackground="#7F77DD",
            relief="flat", padx=8, pady=4,
            cursor="hand2",
            command=self.open_pattern_editor)
        self.btn_pattern.pack(side="left", padx=4)

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
        sig_cb = tk.OptionMenu(transport, self.sig_var, 2, 3, 4, 6, 7, 8)
        # Command assignée après init pour éviter le déclenchement prématuré
        sig_cb.config(bg="#1e1e1e", fg="white",
                      activebackground="#333",
                      highlightthickness=0,
                      relief="flat", font=("Segoe UI", 8), width=2)
        sig_cb["menu"].config(bg="#1e1e1e", fg="white")
        sig_cb.pack(side="left", padx=4)
        # trace_add: déclenche seulement quand la valeur change
        self.sig_var.trace_add(
            "write",
            lambda *a: self._on_sig_change()
            if hasattr(self, "canvas") else None)

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

        # ── Zoom horizontal ─────────────────────────────────────
        tk.Frame(transport, bg="#333333", width=2).pack(
            side="left", fill="y", padx=8)

        tk.Label(transport, text="ZOOM", bg="#0f0f0f", fg="#888888",
                 font=("Segoe UI", 8)).pack(side="left")

        tk.Button(transport, text="−", font=("Segoe UI", 11),
                  bg="#2a2a2a", fg="white",
                  activebackground="#555", relief="flat", width=2,
                  command=lambda: self._zoom(-1)).pack(side="left", padx=(4,0))

        self.zoom_label = tk.Label(
            transport, text="1x",
            bg="#1e1e1e", fg="#FFC107",
            font=("Segoe UI", 10, "bold"), width=4)
        self.zoom_label.pack(side="left", padx=2)

        tk.Button(transport, text="+", font=("Segoe UI", 11),
                  bg="#2a2a2a", fg="white",
                  activebackground="#555", relief="flat", width=2,
                  command=lambda: self._zoom(1)).pack(side="left", padx=(0,4))

        tk.Button(transport, text="↺", font=("Segoe UI", 9),
                  bg="#2a2a2a", fg="#888888",
                  activebackground="#555", relief="flat", width=2,
                  command=lambda: self._zoom_reset()).pack(side="left", padx=2)

    # ============================================================
    # PANEL PRINCIPAL
    # ============================================================
    def _build_main(self):
        main_frame = tk.Frame(self.root, bg="#141414")
        main_frame.pack(fill="both", expand=True)

        self.track_panel = tk.Frame(main_frame, bg="#1a1a1a", width=160)
        self.track_panel.pack(side="left", fill="y")
        self.track_panel.pack_propagate(False)

        # En-tête fixe (aligne avec la règle)
        tk.Frame(self.track_panel, bg="#111111", height=30).pack(fill="x")

        # Zone scrollable pour les tracks (canvas + scrollbar)
        track_scroll_frame = tk.Frame(self.track_panel, bg="#1a1a1a")
        track_scroll_frame.pack(fill="both", expand=True)

        self._track_canvas = tk.Canvas(
            track_scroll_frame, bg="#1a1a1a",
            highlightthickness=0, width=160)
        self._track_scrollbar = tk.Scrollbar(
            track_scroll_frame, orient="vertical",
            command=self._track_canvas.yview)
        self._track_canvas.configure(
            yscrollcommand=self._track_scrollbar.set)

        self._track_scrollbar.pack(side="right", fill="y")
        self._track_canvas.pack(side="left", fill="both", expand=True)

        self.track_labels_frame = tk.Frame(self._track_canvas, bg="#1a1a1a")
        self._track_canvas.create_window(
            (0, 0), window=self.track_labels_frame, anchor="nw")
        self.track_labels_frame.bind(
            "<Configure>",
            lambda e: self._track_canvas.configure(
                scrollregion=self._track_canvas.bbox("all")))

        # Bouton + Ajouter une piste
        self._btn_add_track = tk.Button(
            self.track_labels_frame,
            text="+ Ajouter une piste",
            bg="#1e1e1e", fg="#4CAF50",
            activebackground="#4CAF50", activeforeground="white",
            relief="flat", cursor="hand2",
            font=("Segoe UI", 8, "bold"),
            command=self._add_track)
        self._btn_add_track.pack(fill="x", pady=4, padx=4)

        timeline_frame = tk.Frame(main_frame, bg="#1e1e1e")
        timeline_frame.pack(side="left", fill="both", expand=True)

        # ── TOOLBAR OUTILS ──────────────────────────────────────
        toolbar = tk.Frame(timeline_frame, bg="#0a0a0a", height=32)
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)

        tk.Frame(toolbar, bg="#222222", width=1).pack(side="left", fill="y", padx=2)

        self._tool_btns = {}

        def _tool_btn(text, tool, tooltip):
            SIZE = 28
            cv = tk.Canvas(toolbar, width=SIZE, height=SIZE,
                           bg="#0a0a0a", highlightthickness=0, cursor="hand2")
            cv.pack(side="left", padx=2, pady=2)

            def _draw(active=False):
                cv.delete("all")
                bg = "#00b4d8" if active else "#1e1e1e"
                fg = "white"
                R  = 6
                cv.create_arc(0,      0,      R*2, R*2,     start=90,  extent=90,
                              fill=bg, outline="", style="pieslice")
                cv.create_arc(SIZE-R*2,0,     SIZE, R*2,    start=0,   extent=90,
                              fill=bg, outline="", style="pieslice")
                cv.create_arc(0,      SIZE-R*2,R*2, SIZE,   start=180, extent=90,
                              fill=bg, outline="", style="pieslice")
                cv.create_arc(SIZE-R*2,SIZE-R*2,SIZE,SIZE,  start=270, extent=90,
                              fill=bg, outline="", style="pieslice")
                cv.create_rectangle(R, 0, SIZE-R, SIZE, fill=bg, outline="")
                cv.create_rectangle(0, R, SIZE, SIZE-R, fill=bg, outline="")
                cv.create_text(SIZE//2, SIZE//2, text=text,
                               fill=fg, font=("Segoe UI", 11))

            _draw(tool == "select")

            def _click():
                self._active_tool = tool
                for t, (c, d) in self._tool_btns.items():
                    d(t == tool)
                # Changer le curseur du canvas
                cursors = {"select": "arrow", "split": "sb_h_double_arrow",
                           "mute": "X_cursor", "color": "spraycan"}
                try:
                    self.canvas.config(cursor=cursors.get(tool, "arrow"))
                except Exception:
                    pass

            cv.bind("<ButtonPress-1>", lambda e: _click())
            self._tool_btns[tool] = (cv, _draw)
            return cv

        _tool_btn("↖", "select", "Sélectionner / Déplacer")
        _tool_btn("✂", "split",  "Couper (split)")
        _tool_btn("M", "mute",   "Muter un clip")

        tk.Frame(toolbar, bg="#333333", width=1).pack(side="left", fill="y", padx=4)

        # Label outil actif
        self._tool_label = tk.Label(toolbar, text="Sélection",
                                     bg="#0a0a0a", fg="#888888",
                                     font=("Segoe UI", 7))
        self._tool_label.pack(side="left", padx=4)

        tk.Frame(toolbar, bg="#222222", width=1).pack(side="left", fill="y", padx=2)

        # ── RÈGLE ────────────────────────────────────────────────
        self.ruler = tk.Canvas(timeline_frame, bg="#111111",
                               height=30, highlightthickness=0)
        self.ruler.pack(fill="x")
        # Même scrollregion que le canvas — crucial pour la sync
        self.ruler.configure(scrollregion=(0, 0, 60000, 30))
        self.ruler.bind("<ButtonPress-1>",  self._ruler_click)
        self.ruler.bind("<B1-Motion>",      self._ruler_drag)
        self.ruler.bind("<ButtonRelease-1>",self._ruler_release)

        self.canvas = tk.Canvas(timeline_frame, bg="#1e1e1e",
                                highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        h_scroll = tk.Scrollbar(timeline_frame, orient="horizontal",
                                command=self._scroll_x)
        h_scroll.pack(fill="x", side="bottom")

        v_scroll = tk.Scrollbar(timeline_frame, orient="vertical",
                                command=self._scroll_y_sync)
        v_scroll.pack(fill="y", side="right")

        def _y_scroll_sync(first, last):
            v_scroll.set(first, last)
            try:
                self._track_canvas.yview_moveto(float(first))
            except Exception:
                pass

        self.canvas.configure(
            xscrollcommand=h_scroll.set,
            yscrollcommand=_y_scroll_sync,
            scrollregion=(0, 0, 60000, 99999))

        self.canvas.bind("<Motion>",          self._on_canvas_motion)
        self.canvas.bind("<ButtonPress-1>",   self._canvas_click_bg)
        self.canvas.bind("<B1-Motion>",       self._canvas_b1_motion)
        self.canvas.bind("<ButtonRelease-1>", self._canvas_b1_release)

        # ---- Scroll / Pan de la grille ----
        # Clic-glisser bouton du milieu (molette enfoncée)
        self.canvas.bind("<ButtonPress-2>",   self._pan_start)
        self.canvas.bind("<B2-Motion>",        self._pan_move)
        self.canvas.bind("<ButtonRelease-2>",  self._pan_end)
        self.ruler.bind("<ButtonPress-2>",    self._pan_start)
        self.ruler.bind("<B2-Motion>",         self._pan_move)

        # Clic-glisser bouton droit (surface tactile Windows = bouton droit)
        # UNIQUEMENT sur fond vide (pas sur un clip)
        self.canvas.bind("<ButtonPress-3>",   self._bg_pan_start)
        self.canvas.bind("<B3-Motion>",        self._bg_pan_move)
        self.canvas.bind("<ButtonRelease-3>",  self._bg_pan_end)

        # Molette souris → scroll horizontal
        self.canvas.bind("<MouseWheel>",         self._on_mousewheel)
        self.ruler.bind("<MouseWheel>",          self._on_mousewheel)

        # Shift+molette → scroll horizontal forcé
        self.canvas.bind("<Shift-MouseWheel>",   self._on_shift_mousewheel)
        self.ruler.bind("<Shift-MouseWheel>",    self._on_shift_mousewheel)

        # Ctrl+molette → ZOOM horizontal (grille + clips)
        self.canvas.bind("<Control-MouseWheel>", self._on_zoom)
        self.ruler.bind("<Control-MouseWheel>",  self._on_zoom)

        # Note: TouchpadScroll non supporté par tkinter Windows
        # Le trackpad utilise MouseWheel automatiquement

    # ============================================================
    # RULER / GRID / PLAYHEAD
    # ============================================================
    def _scroll_x(self, *args):
        self.canvas.xview(*args)
        self.ruler.xview(*args)
        # Maintenir le playhead au premier plan après scroll
        try:
            self.canvas.tag_raise("playhead")
            self.ruler.tag_raise("playhead_ruler")
        except Exception:
            pass

    def _scroll_y_sync(self, *args):
        """Synchronise le scroll vertical canvas ↔ panel tracks."""
        self.canvas.yview(*args)
        try:
            # Forcer la même position que le canvas
            frac = self.canvas.yview()[0]
            self._track_canvas.yview_moveto(frac)
        except Exception:
            pass

    def _on_canvas_yscroll(self, *args):
        """Callback scroll vertical du canvas → sync track panel."""
        try:
            frac = self.canvas.yview()[0]
            self._track_canvas.yview_moveto(frac)
        except Exception:
            pass

    def _set_playhead(self, x_canvas):
        """Positionne le playhead à la position x (en pixels canvas)."""
        self.playhead_pos = max(0.0, x_canvas / self.pixels_per_second)
        self._draw_playhead()
        self._update_time_label()
        if self.is_playing:
            self._play_start_time = time.time()
            self._play_start_pos  = self.playhead_pos
            self.engine.play_clips(
                clips=self.clips,
                start_pos=self.playhead_pos,
                bpm=self.bpm.get())

    def _ruler_click(self, event):
        """Clic sur la règle → repositionne le playhead."""
        self._ruler_dragging = True
        self.ruler.config(cursor="sb_h_double_arrow")
        self._set_playhead(self.ruler.canvasx(event.x))

    def _ruler_drag(self, event):
        """Glisser sur la règle → playhead suit le curseur en temps réel."""
        if getattr(self, '_ruler_dragging', False):
            self._set_playhead(self.ruler.canvasx(event.x))

    def _ruler_release(self, event):
        """Fin du glisser sur la règle."""
        self._ruler_dragging = False
        self.ruler.config(cursor="arrow")

    def _canvas_b1_motion(self, event):
        """Glisser sur le canvas."""
        if self._resize_item is not None:
            return  # resize en cours
        if self.drag_item is not None:
            return  # drag clip en cours
        if getattr(self, '_lasso_active', False):
            self._lasso_move(event)
            return
        # Sur fond vide → déplacer le playhead
        self._set_playhead(self.canvas.canvasx(event.x))


    def _draw_playhead(self):
        # Supprimer ABSOLUMENT tout ce qui porte ces tags
        self.canvas.delete("playhead")
        self.ruler.delete("playhead_ruler")
        self.playhead_line = None

        x = self.playhead_pos * self.pixels_per_second
        ph_height = max(99999, len(self.tracks) * self.track_height + 2000)

        # Créer le trait dans le canvas principal
        self.playhead_line = self.canvas.create_line(
            x, 0, x, ph_height,
            fill="#ff4444", width=2, tags="playhead")

        # Créer le triangle + trait dans la règle
        # Triangle indicateur en haut
        self.ruler.create_polygon(
            x-5, 0, x+5, 0, x, 10,
            fill="#ff4444", outline="", tags="playhead_ruler")
        self.ruler.create_line(
            x, 10, x, 30,
            fill="#ff4444", width=2, tags="playhead_ruler")

        # Toujours au premier plan
        self.canvas.tag_raise("playhead")
        self.ruler.tag_raise("playhead_ruler")

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
        # Pas de clips → rien à lire
        if not self.clips:
            self.playhead_pos = 0.0
            self._draw_playhead()
            self._update_time_label()
            return
        self.is_playing       = True
        self.btn_play._set_color("#66BB6A")
        self._play_start_time = time.time()
        self._play_start_pos  = self.playhead_pos
        self._total_duration  = self._get_total_duration()
        self.engine.play_clips(clips=self.clips,
                               start_pos=self.playhead_pos,
                               bpm=self.bpm.get())
        # Métronome : update BPM seulement si déjà actif
        # Ne JAMAIS redémarrer le stream pendant la lecture
        if self._metro_on:
            self.metronome.update_bpm(self.bpm.get())
        self._tick_playhead()

    def stop(self):
        self.is_playing = False
        self.btn_play._set_color("#4CAF50")
        self.engine.stop()
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
                self.playhead_pos = self._play_start_pos
                self._draw_playhead()
                self._update_time_label()
                self.is_playing = False
                self.btn_play._set_color("#4CAF50")
                self.engine.stop()
                return
            self.playhead_pos = new_pos
            self._draw_playhead()
            self._auto_scroll_to_playhead()
            self._update_time_label()
            self.root.after(30, self._tick_playhead)
        except Exception as e:
            print(f"[GUI] Erreur tick playhead : {e}")
            self.is_playing = False

    def _auto_scroll_to_playhead(self):
        """
        Fait défiler la vue pour garder le playhead toujours visible.
        Le playhead est maintenu dans une zone centrale (20%-80% de la vue).
        """
        try:
            canvas_w   = self.canvas.winfo_width()
            if canvas_w < 10:
                return

            # Position pixel absolue du playhead
            ph_x = self.playhead_pos * self.pixels_per_second

            # Position pixel de la vue actuelle (left edge)
            scroll_region_w = 60000  # même valeur que scrollregion
            view_left_frac  = self.canvas.xview()[0]
            view_left_px    = view_left_frac * scroll_region_w

            # Position relative du playhead dans la vue
            ph_in_view = ph_x - view_left_px

            # Marges : garder le playhead entre 20% et 75% de la largeur
            margin_left  = canvas_w * 0.20
            margin_right = canvas_w * 0.75

            if ph_in_view > margin_right:
                # Playhead sort à droite → scroll forward
                # Centrer le playhead à 30% de la vue
                new_left_px   = ph_x - canvas_w * 0.30
                new_left_frac = max(0.0, new_left_px / scroll_region_w)
                self.canvas.xview_moveto(new_left_frac)
                self.ruler.xview_moveto(new_left_frac)

            elif ph_in_view < margin_left and ph_x > canvas_w * 0.20:
                # Playhead sort à gauche (seek arrière) → scroll backward
                new_left_px   = ph_x - canvas_w * 0.30
                new_left_frac = max(0.0, new_left_px / scroll_region_w)
                self.canvas.xview_moveto(new_left_frac)
                self.ruler.xview_moveto(new_left_frac)
        except Exception:
            pass

    def change_bpm(self, delta):
        self.bpm.set(max(40, min(300, self.bpm.get() + delta)))
        if self._metro_on:
            self.metronome.update_bpm(self.bpm.get())
        # Redessiner la grille + repositionner les clips
        if hasattr(self, '_grid_redraw_job'):
            self.root.after_cancel(self._grid_redraw_job)
        self._grid_redraw_job = self.root.after(
            150, self._redraw_grid_and_ruler)

    def _bpm_scroll(self, event):
        self.change_bpm(1 if event.delta > 0 else -1)

    def _safe_grid_redraw(self):
        try:
            if not hasattr(self, 'canvas'): return
            if not hasattr(self, 'ruler'): return
            if not hasattr(self, 'sig_var'): return
            if not self.canvas.winfo_exists(): return
            self._redraw_grid_and_ruler()
        except Exception:
            pass

    def _on_sig_change(self, val=None):
        if not hasattr(self, 'canvas') or not hasattr(self, 'ruler'):
            return
        try:
            v = int(self.sig_var.get())
            if self._metro_on and hasattr(self, 'metronome'):
                self.metronome.update_sig(v)
            if hasattr(self, '_sig_job'):
                self.root.after_cancel(self._sig_job)
            self._sig_job = self.root.after(200, self._safe_grid_redraw)
        except Exception as e:
            print(f"[GUI] sig_change: {e}")

    # ============================================================
    # MÉTRONOME
    # ============================================================
    def _toggle_metronome(self):
        if self._metro_on:
            self.metronome.stop()
            self._metro_on = False
            self.btn_metro.config(bg="#2a2a2a", fg="#888888",
                                   text="🎵 Métronome")
            self.beat_indicator.itemconfig(self._beat_dot, fill="#333333")
        else:
            self._metro_on = True
            self.btn_metro.config(bg="#FFC107", fg="#0a0a0a",
                                   text="🎵 Métronome ●")
            # Démarrer proprement avec le BPM et signature actuels
            self.metronome.start(
                bpm=self.bpm.get(),
                beats_per_bar=int(self.sig_var.get()),
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
        # 1. Supprimer le playhead
        self.canvas.delete("playhead")
        self.ruler.delete("playhead_ruler")
        self.playhead_line = None

        # 2. Redessiner grille
        self.canvas.delete("grid")
        self.draw_grid()

        # 3. Redessiner ruler COMPLET
        self.ruler.delete("all")
        self.draw_ruler()

        # 4. Remonter clips au-dessus de la grille
        for clip in self.clips.values():
            try:
                self.canvas.tag_raise(clip["tag"])
            except Exception:
                pass

        # 5. Playhead au premier plan (toujours en dernier)
        self._draw_playhead()

        # 6. Mettre à jour le scrollregion canvas
        # Scrollregion infinie : s'adapte au nombre de pistes
        n_tracks = max(50, len(self.tracks) + 20)
        h = n_tracks * self.track_height + 2000
        self.canvas.configure(scrollregion=(0, 0, 60000, h))

    def draw_ruler(self):
        """Règle — numéros de mesures sur 60000px."""
        bpm       = self.bpm.get()
        sig       = getattr(self, 'sig_var', None)
        beats_bar = int(sig.get()) if sig else 4
        beat_sec  = 60.0 / bpm
        bar_sec   = beat_sec * beats_bar
        bar_px    = bar_sec * self.pixels_per_second
        beat_px   = beat_sec * self.pixels_per_second

        total_px     = 60000   # couvre toute la scrollregion
        bar_count    = 0
        MIN_LABEL_PX = max(28, int(bar_px * 0.4))
        last_label_x = -(MIN_LABEL_PX + 1)  # force affichage dès x=0

        # Fond de la règle — ligne séparatrice en bas
        self.ruler.create_line(0, 29, total_px, 29,
                               fill="#333333", width=1)

        x = 0.0
        while x < total_px:
            xi = int(x)

            # Ligne verticale de mesure
            h = 20 if bar_count % 4 == 0 else 14
            self.ruler.create_line(xi, 30 - h, xi, 30,
                                   fill="#666666", width=1)

            # Numéro de mesure — afficher si assez d'espace
            if xi - last_label_x >= MIN_LABEL_PX:
                self.ruler.create_text(
                    xi + 3, 10,
                    text=str(bar_count + 1),
                    fill="#cccccc",
                    font=("Segoe UI", 7, "bold"),
                    anchor="w")
                last_label_x = xi

            # Temps internes
            if bar_px >= 24:
                for b in range(1, beats_bar):
                    bx = xi + int(b * beat_px)
                    if bx < total_px:
                        self.ruler.create_line(
                            bx, 24, bx, 30,
                            fill="#444444", width=1)

            x += bar_px
            bar_count += 1

    def draw_grid(self):
        """Grille infinie avec lignes de mesure selon le BPM."""
        bpm       = self.bpm.get()
        sig       = getattr(self, 'sig_var', None)
        beats_bar = sig.get() if sig else 4
        beat_sec  = 60.0 / bpm
        bar_sec   = beat_sec * beats_bar
        bar_px    = bar_sec * self.pixels_per_second
        beat_px   = beat_sec * self.pixels_per_second
        total_w   = 60000
        total_h   = max(99999, len(self.tracks) * self.track_height + 2000)

        x = 0.0
        while x < total_w:
            xi = int(x)
            self.canvas.create_line(xi, 0, xi, total_h,
                                    fill="#2a2a2a", width=1,
                                    tags="grid")
            if bar_px >= 10:
                for b in range(1, beats_bar):
                    bx = xi + int(b * beat_px)
                    if bx < total_w:
                        self.canvas.create_line(bx, 0, bx, total_h,
                                                fill="#1e1e1e", width=1,
                                                tags="grid")
            x += bar_px

        # Lignes horizontales — une par piste + 200 de réserve
        n_lines = max(200, len(self.tracks) + 50)
        for i in range(n_lines):
            y = i * self.track_height
            self.canvas.create_line(0, y, total_w, y,
                                    fill="#2d2d2d", tags="grid")

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
    # ============================================================
    # SCROLL / PAN DE LA GRILLE
    # ============================================================
    def _pan_start(self, event):
        """Démarre le pan (bouton milieu)."""
        self.canvas.config(cursor="fleur")
        self._pan_start_x = event.x
        self._pan_active  = True

    def _pan_move(self, event):
        """Pan en cours."""
        if not getattr(self, '_pan_active', False):
            return
        dx = self._pan_start_x - event.x
        self._pan_start_x = event.x
        # Déplacer la vue
        self.canvas.xview_scroll(int(dx / 2), "units")
        self.ruler.xview_scroll(int(dx / 2), "units")

    def _pan_end(self, event):
        """Fin du pan."""
        self._pan_active = False
        self.canvas.config(cursor="arrow")

    def _bg_pan_start(self, event):
        """Pan avec clic droit sur fond vide (surface tactile)."""
        # Vérifier qu'on est sur le fond (pas sur un clip)
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        items = self.canvas.find_overlapping(cx-2, cy-2, cx+2, cy+2)
        on_clip = any(i in self.clips for i in items)
        if on_clip:
            # Laisser le menu contextuel gérer ça
            return
        self._bg_pan_x   = event.x
        self._bg_panning = True
        self.canvas.config(cursor="fleur")

    def _bg_pan_move(self, event):
        """Pan fond vide en cours."""
        if not getattr(self, '_bg_panning', False):
            return
        dx = self._bg_pan_x - event.x
        self._bg_pan_x = event.x
        self.canvas.xview_scroll(int(dx / 2), "units")
        self.ruler.xview_scroll(int(dx / 2), "units")

    def _bg_pan_end(self, event):
        """Fin pan fond."""
        self._bg_panning = False
        self.canvas.config(cursor="arrow")

    def _on_mousewheel(self, event):
        """Molette → scroll horizontal (naturel sur trackpad Windows)."""
        # Sur Windows: event.delta = ±120 par cran
        delta = -1 if event.delta > 0 else 1
        self.canvas.xview_scroll(delta * 3, "units")
        self.ruler.xview_scroll(delta * 3, "units")
        return "break"

    def _on_shift_mousewheel(self, event):
        """Shift+molette → scroll horizontal forcé."""
        delta = -1 if event.delta > 0 else 1
        self.canvas.xview_scroll(delta * 5, "units")
        self.ruler.xview_scroll(delta * 5, "units")
        return "break"

    # ============================================================
    # ZOOM HORIZONTAL
    # ============================================================
    # pixels_per_second de base = 120 → zoom 1x
    _PPS_BASE = 120
    _ZOOM_LEVELS = [30, 45, 60, 90, 120, 180, 240, 360, 480, 720]

    def _zoom(self, direction: int):
        """Zoom in (+1) ou out (-1) d un niveau."""
        pps    = self.pixels_per_second
        levels = self._ZOOM_LEVELS
        try:
            idx = levels.index(pps)
        except ValueError:
            idx = levels.index(min(levels, key=lambda x: abs(x - pps)))
        new_idx = max(0, min(len(levels)-1, idx + direction))
        self._apply_zoom(levels[new_idx])

    def _zoom_reset(self):
        self._apply_zoom(self._PPS_BASE)

    def _on_zoom(self, event):
        """Ctrl+molette → zoom centré sur la position du curseur."""
        direction = 1 if event.delta > 0 else -1
        self._zoom(direction)
        return "break"

    def _apply_zoom(self, new_pps: int):
        """
        Change pixels_per_second et repositionne TOUS les clips + grille.
        Garde le centre de vue stable pendant le zoom.
        """
        if new_pps == self.pixels_per_second:
            return

        # Facteur de changement
        factor = new_pps / self.pixels_per_second

        # Position actuelle du centre de la vue (pour zoom centré)
        view_l, view_r = self.canvas.xview()
        sr_w    = 60000
        center  = (view_l + (view_r - view_l) / 2) * sr_w

        # Appliquer le nouveau pixels_per_second
        self.pixels_per_second = new_pps

        # Redimensionner tous les clips
        for clip in self.clips.values():
            clip["x0"] = clip["start"]    * new_pps
            clip["x1"] = (clip["start"] + clip["duration"]) * new_pps
            # Hauteur = toute la piste (inchangée)
            self._redraw_clip(list(self.clips.keys())[
                list(self.clips.values()).index(clip)])

        # Redessiner grille + règle + playhead
        self._redraw_grid_and_ruler()

        # Recentrer la vue sur le même point musical
        new_center_frac = (center * factor) / sr_w
        new_left_frac   = max(0.0, new_center_frac - (view_r - view_l) / 2)
        self.canvas.xview_moveto(new_left_frac)
        self.ruler.xview_moveto(new_left_frac)

        # Mettre à jour le label zoom
        ratio = new_pps / self._PPS_BASE
        if ratio >= 1:
            lbl = f"{ratio:.0f}x" if ratio == int(ratio) else f"{ratio:.1f}x"
        else:
            lbl = f"1/{1/ratio:.0f}"
        try:
            self.zoom_label.config(text=lbl)
        except Exception:
            pass

        print(f"[GUI] Zoom : {new_pps} px/s ({lbl})")

    # ============================================================
    def _canvas_click_bg(self, event):
        """Clic sur fond : désélectionne ou démarre le lasso."""
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        items = self.canvas.find_overlapping(cx-2, cy-2, cx+2, cy+2)
        on_clip = any(i in self.clips for i in items)
        if on_clip:
            return
        # Fond vide → désélectionner + démarrer lasso
        self._deselect_all()
        self._lasso_start(event)

    def _lasso_start(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        self._lasso_active  = True
        self._lasso_start_x = cx
        self._lasso_start_y = cy
        self._lasso_rect    = self.canvas.create_rectangle(
            cx, cy, cx, cy,
            outline="#FFC107", width=1,
            dash=(4, 4), tags="lasso")

    def _lasso_move(self, event):
        if not self._lasso_active or not self._lasso_rect:
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        self.canvas.coords(
            self._lasso_rect,
            self._lasso_start_x, self._lasso_start_y, cx, cy)

    def _lasso_end(self, event):
        if not self._lasso_active:
            return
        self._lasso_active = False
        if self._lasso_rect:
            # Récupérer la bbox du lasso
            x0 = min(self._lasso_start_x, self.canvas.canvasx(event.x))
            y0 = min(self._lasso_start_y, self.canvas.canvasy(event.y))
            x1 = max(self._lasso_start_x, self.canvas.canvasx(event.x))
            y1 = max(self._lasso_start_y, self.canvas.canvasy(event.y))
            self.canvas.delete(self._lasso_rect)
            self._lasso_rect = None
            # Sélectionner tous les clips dans la zone
            if x1 - x0 > 5 or y1 - y0 > 5:
                self._lasso_select(x0, y0, x1, y1)

    def _lasso_select(self, x0, y0, x1, y1):
        """Sélectionne tous les clips qui intersectent le rectangle."""
        self._selected_clips.clear()
        for rect_id, clip in self.clips.items():
            cx0, cy0 = clip["x0"], clip["y0"]
            cx1, cy1 = clip["x1"], clip["y1"]
            # Intersection
            if cx1 >= x0 and cx0 <= x1 and cy1 >= y0 and cy0 <= y1:
                self._selected_clips.add(rect_id)
                self.canvas.itemconfig(rect_id, outline="#FFC107", width=2)
        if self._selected_clips:
            print(f"[GUI] {len(self._selected_clips)} clip(s) sélectionnés")

    def _canvas_b1_release(self, event):
        """Fin du clic gauche sur canvas."""
        if self._lasso_active:
            self._lasso_end(event)
        elif self._block_dragging:
            self._block_drag_end(event)

    def _select_clip(self, rect_id):
        self._deselect_all()
        self._selected_clip = rect_id
        color = self.clips[rect_id].get("color", "#00b4d8")
        self.canvas.itemconfig(rect_id, outline="#FFD700", width=2)

    def _deselect_all(self):
        if self._selected_clip and self._selected_clip in self.clips:
            clip  = self.clips[self._selected_clip]
            color = clip.get("color", "#00b4d8")
            outline = self._darken(color)
            self.canvas.itemconfig(self._selected_clip,
                                   outline=outline, width=1)
        self._selected_clip = None
        # Désélectionner aussi la sélection multiple
        for rid in self._selected_clips:
            if rid in self.clips:
                clip    = self.clips[rid]
                outline = self._darken(clip.get("color", "#00b4d8"))
                self.canvas.itemconfig(rid, outline=outline, width=1)
        self._selected_clips.clear()
        self._block_dragging = False

    def _start_block_drag(self, event):
        """Démarre le déplacement d un bloc de clips sélectionnés."""
        self._block_dragging = True
        self._block_drag_x   = self.canvas.canvasx(event.x)
        self._block_drag_y   = self.canvas.canvasy(event.y)

    def _block_drag_move(self, event):
        """Déplace tous les clips sélectionnés ensemble."""
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        dx = cx - self._block_drag_x
        dy = cy - self._block_drag_y
        self._block_drag_x = cx
        self._block_drag_y = cy
        for rid in self._selected_clips:
            clip = self.clips.get(rid)
            if clip:
                clip["x0"] += dx
                clip["x1"] += dx
                clip["y0"] += dy
                clip["y1"] += dy
                self._redraw_clip(rid)

    def _block_drag_end(self, event):
        """Snap et finalise le déplacement du bloc."""
        snap = self._get_snap_px()
        for rid in self._selected_clips:
            clip = self.clips.get(rid)
            if not clip:
                continue
            sx    = max(0, round(clip["x0"] / snap) * snap)
            w     = clip["x1"] - clip["x0"]
            y_center = (clip["y0"] + clip["y1"]) / 2
            track = max(0, min(int(y_center // self.track_height),
                               len(self.tracks)-1))
            MARGIN = 2
            y0    = track * self.track_height + MARGIN
            y1    = (track+1) * self.track_height - MARGIN
            clip["x0"]    = sx
            clip["x1"]    = sx + w
            clip["y0"]    = y0
            clip["y1"]    = y1
            clip["start"] = sx / self.pixels_per_second
            clip["track"] = track
            self._redraw_clip(rid)
        self._block_dragging = False

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
        self._open_folder_browser(SAMPLES_DIR, "Samples")

    def _open_recordings_folder(self):
        self._open_folder_browser(REC_DIR, "Enregistrements")

    def _open_projects_folder(self):
        self._open_folder_browser(PROJECTS_DIR, "Projets")

    def _open_folder_browser(self, folder, title):
        """Explorateur de dossier avec navigation ← ↑ et double-clic."""
        win = tk.Toplevel(self.root)
        self._apply_icon(win)
        win.title(f"mini_daw — {title}")
        win.configure(bg="#0f0f0f")
        win.resizable(True, True)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.minsize(520, 400)
        w, h = 600, 460
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        win.focus_set()

        # Historique de navigation
        _history  = []
        _current  = [folder]   # liste pour mutabilité dans les closures

        # ── Barre de navigation ──────────────────────────────────
        nav = tk.Frame(win, bg="#111111")
        nav.pack(fill="x", padx=0, pady=0)

        btn_back = tk.Button(nav, text="←",
                             bg="#1a1a1a", fg="#aaaaaa",
                             activebackground="#333", activeforeground="white",
                             relief="flat", padx=10, pady=4,
                             font=("Segoe UI", 11, "bold"), cursor="hand2")
        btn_back.pack(side="left", padx=(4,1), pady=4)

        btn_up = tk.Button(nav, text="↑",
                           bg="#1a1a1a", fg="#aaaaaa",
                           activebackground="#333", activeforeground="white",
                           relief="flat", padx=10, pady=4,
                           font=("Segoe UI", 11, "bold"), cursor="hand2")
        btn_up.pack(side="left", padx=(1,4), pady=4)

        path_var = tk.StringVar(value=folder)
        path_entry = tk.Entry(nav, textvariable=path_var,
                              bg="#1e1e1e", fg="#4CAF50",
                              insertbackground="white",
                              relief="flat", font=("Segoe UI", 9))
        path_entry.pack(side="left", fill="x", expand=True, ipady=4, padx=4)

        tk.Frame(win, bg="#222", height=1).pack(fill="x")

        # ── Liste fichiers ───────────────────────────────────────
        lf = tk.Frame(win, bg="#0f0f0f")
        lf.pack(fill="both", expand=True)

        sb = tk.Scrollbar(lf)
        sb.pack(side="right", fill="y")
        lb = tk.Listbox(lf, bg="#1a1a1a", fg="white",
                        selectbackground="#4CAF50",
                        font=("Segoe UI", 9),
                        relief="flat", borderwidth=0,
                        yscrollcommand=sb.set,
                        activestyle="none")
        lb.pack(fill="both", expand=True)
        sb.config(command=lb.yview)

        # ── Popule la liste ──────────────────────────────────────
        def _populate(d):
            if not os.path.isdir(d):
                return
            _current[0] = d
            path_var.set(d)
            lb.delete(0, "end")
            # Entrée parent ".."
            parent = os.path.dirname(d)
            if parent != d:
                lb.insert("end", "  📁   ..")
                lb.itemconfig("end", fg="#FFC107")
            try:
                entries = sorted(os.listdir(d),
                                 key=lambda x: (not os.path.isdir(
                                     os.path.join(d, x)), x.lower()))
            except PermissionError:
                lb.insert("end", "  ⛔  Accès refusé")
                return
            for entry in entries:
                full = os.path.join(d, entry)
                if os.path.isdir(full):
                    lb.insert("end", f"  📁   {entry}")
                    lb.itemconfig("end", fg="#FFC107")
                else:
                    ext = os.path.splitext(entry)[1].lower()
                    if ext in {".wav",".mp3",".flac",".ogg",".aiff",".m4a",".wma"}:
                        icon = "🎵"
                        color = "#00b4d8"
                    elif ext == ".mdaw":
                        icon = "📄"
                        color = "#4CAF50"
                    else:
                        icon = "📎"
                        color = "#666666"
                    lb.insert("end", f"  {icon}   {entry}")
                    lb.itemconfig("end", fg=color)

        def _get_selected():
            sel = lb.curselection()
            if not sel:
                return None
            txt = lb.get(sel[0]).strip()
            # Extraire le nom après l'icône (3 espaces séparateurs)
            parts = txt.split("   ", 1)
            name  = parts[1].strip() if len(parts) > 1 else txt
            if name == "..":
                return os.path.dirname(_current[0])
            return os.path.join(_current[0], name)

        def _navigate(d, push_history=True):
            if not os.path.isdir(d):
                return
            if push_history and _current[0] != d:
                _history.append(_current[0])
            _populate(d)

        def _go_back():
            if _history:
                prev = _history.pop()
                _navigate(prev, push_history=False)

        def _go_up():
            parent = os.path.dirname(_current[0])
            if parent != _current[0]:
                _navigate(parent)

        def _on_double_click(event):
            path = _get_selected()
            if not path:
                return
            if os.path.isdir(path):
                _navigate(path)
            else:
                _do_open(path)

        def _on_enter_path(event=None):
            d = path_var.get().strip()
            if os.path.isdir(d):
                _navigate(d)

        def _do_open(path=None):
            if path is None:
                path = _get_selected()
            if not path:
                return
            if os.path.isdir(path):
                _navigate(path)
                return
            if not os.path.exists(path):
                return
            ext = os.path.splitext(path)[1].lower()
            win.destroy()
            if ext == ".mdaw":
                self._load_project_from_mdaw(path)
            elif ext in {".wav",".mp3",".flac",".ogg",
                         ".aiff",".m4a",".wma",".flac"}:
                self._import_from_path(path)
            else:
                try:
                    os.startfile(path)
                except Exception:
                    pass

        btn_back.config(command=_go_back)
        btn_up.config(command=_go_up)
        lb.bind("<Double-Button-1>", _on_double_click)
        lb.bind("<Return>",          lambda e: _on_double_click(e))
        path_entry.bind("<Return>",  _on_enter_path)

        # ── Boutons du bas ───────────────────────────────────────
        tk.Frame(win, bg="#222", height=1).pack(fill="x")
        bf = tk.Frame(win, bg="#0a0a0a")
        bf.pack(fill="x", padx=10, pady=8)

        tk.Button(bf, text="📂 Ouvrir dans l'Explorateur",
                  bg="#2a2a2a", fg="white", relief="flat",
                  padx=10, pady=5, cursor="hand2",
                  font=("Segoe UI", 8),
                  command=lambda: os.startfile(
                      _current[0])).pack(side="left", padx=4)

        tk.Button(bf, text="✔ Ouvrir",
                  bg="#4CAF50", fg="white", relief="flat",
                  padx=16, pady=5, cursor="hand2",
                  font=("Segoe UI", 9, "bold"),
                  command=_do_open).pack(side="right", padx=4)
        tk.Button(bf, text="✕ Fermer",
                  bg="#2a2a2a", fg="white", relief="flat",
                  padx=12, pady=5, cursor="hand2",
                  font=("Segoe UI", 9),
                  command=win.destroy).pack(side="right", padx=4)

        _populate(folder)

    # ============================================================
    # PROJETS
    # ============================================================
    def _new_project(self):
        """Nouveau projet vide via le nouveau système."""
        self._ask_project_name(
            callback=lambda name: self._create_new_project(name, "Blank"))
    def _save_project(self):
        proj = self._current_project or ""
        if proj and "_recovery" not in proj and os.path.isdir(os.path.dirname(proj)):
            ok = save_project(proj, self.clips, self.bpm.get())
            name = os.path.splitext(os.path.basename(proj))[0]
            if ok:
                self.root.title(f"mini_daw — {name} ✓")
                self.root.after(2000, lambda: self.root.title(f"mini_daw — {name}"))
                print(f"[GUI] Saved: {proj}")
        else:
            self._save_project_as_dialog()

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
        # Rejeter les fichiers projet .mdaw — ce ne sont pas des audios
        ext = os.path.splitext(path)[1].lower()
        if ext == ".mdaw":
            messagebox.showwarning(
                "Format invalide",
                f"{os.path.basename(path)} est un fichier projet .mdaw,\n"
                "pas un fichier audio.\n\n"
                "Utilise Fichier → Ouvrir un projet pour l'ouvrir.")
            return
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            duration = sf.info(path).duration
        except Exception:
            try:
                from pydub import AudioSegment
                audio    = AudioSegment.from_file(path)
                duration = len(audio) / 1000.0
            except Exception:
                duration = 4.0

        # Toujours placer au début (position 0) pour éviter
        # que le clip soit hors vue
        start = 0.0
        track = self._find_free_track(start, duration)
        self._snapshot()
        self.create_clip(track, start, duration,
                         label=name, filepath=path)
        # Scroller vers le début pour que le clip soit visible
        self.canvas.xview_moveto(0)
        self.ruler.xview_moveto(0)
        print(f"[GUI] Import : '{name}' {duration:.2f}s sur piste {track}")

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

    def open_pattern_editor(self):
        """Ouvre le Pattern Editor (séquenceur de drums)."""
        def on_export(filepath, duration):
            """Ajoute le pattern rendu sur la timeline."""
            name  = os.path.splitext(os.path.basename(filepath))[0]
            track = self._find_free_track(self.playhead_pos, duration)
            self._snapshot()
            self.create_clip(track, self.playhead_pos, duration,
                             label=name, filepath=filepath)
        PatternEditorWindow(
            self.root,
            bpm_var=self.bpm,
            on_export=on_export)

    def open_export(self):
        ExportWindow(self.root, clips=self.clips)

    def _export_full_project(self):
        """Exporte le projet complet dans un dossier autonome."""
        # Demander le nom du projet
        dialog = tk.Toplevel(self.root)
        self._apply_icon(dialog)
        dialog.title("Export Full Project")
        dialog.configure(bg="#0f0f0f")
        dialog.resizable(True, True)
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.minsize(360, 160)
        w, h = 400, 220
        sw, sh = dialog.winfo_screenwidth(), dialog.winfo_screenheight()
        dialog.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        dialog.focus_set()
        dialog.lift()

        tk.Label(dialog, text="📦 EXPORTER PROJET COMPLET",
                 bg="#0f0f0f", fg="#4CAF50",
                 font=("Segoe UI", 11, "bold")).pack(pady=(16, 4))
        tk.Label(dialog,
                 text="Crée un dossier avec tous les fichiers audio copiés dedans.",
                 bg="#0f0f0f", fg="#888888",
                 font=("Segoe UI", 8)).pack()

        tk.Label(dialog, text="Project name:",
                 bg="#0f0f0f", fg="#cccccc",
                 font=("Segoe UI", 9)).pack(pady=(12, 2))

        # Nom par défaut depuis le projet courant
        default_name = "Mon projet"
        if self._current_project:
            default_name = os.path.splitext(
                os.path.basename(self._current_project))[0]

        name_var = tk.StringVar(value=default_name)
        entry = tk.Entry(dialog, textvariable=name_var,
                         bg="#1e1e1e", fg="white",
                         insertbackground="white",
                         font=("Segoe UI", 10),
                         relief="flat", width=34)
        entry.pack(ipady=6, padx=20)
        entry.select_range(0, "end")
        entry.focus_set()

        prog_var = tk.IntVar(value=0)
        from tkinter import ttk as _ttk
        prog = _ttk.Progressbar(dialog, variable=prog_var,
                                maximum=100, length=360)
        prog.pack(padx=20, pady=8)

        status_lbl = tk.Label(dialog, text="",
                              bg="#0f0f0f", fg="#4CAF50",
                              font=("Segoe UI", 8))
        status_lbl.pack()

        def _start():
            name = name_var.get().strip() or "Mon projet"
            btn_ok.config(state="disabled")

            def _progress(pct):
                dialog.after(0, lambda: prog_var.set(pct))

            def _done(path):
                def _finish():
                    if path:
                        status_lbl.config(
                            text=f"✔ Exporté dans : {path}", fg="#4CAF50")
                        prog_var.set(100)
                        # Ouvrir le dossier dans l'explorateur
                        try:
                            os.startfile(path)
                        except Exception:
                            pass
                        dialog.after(2000, dialog.destroy)
                    else:
                        status_lbl.config(
                            text="✗ Erreur lors de l'export", fg="#f44336")
                        btn_ok.config(state="normal")
                dialog.after(0, _finish)

                export_project_full(
                project_name=name,
                clips=self.clips,
                bpm=self.bpm.get(),
                on_progress=_progress,
                on_done=_done)

        bf = tk.Frame(dialog, bg="#0f0f0f")
        bf.pack(pady=4)
        btn_ok = tk.Button(bf, text="📦 Exporter",
                           bg="#4CAF50", fg="white",
                           relief="flat", padx=14, pady=6,
                           cursor="hand2",
                           font=("Segoe UI", 9, "bold"),
                           command=_start)
        btn_ok.pack(side="left", padx=6)
        tk.Button(bf, text="✕ Cancel",
                  bg="#2a2a2a", fg="white",
                  relief="flat", padx=10, pady=6,
                  cursor="hand2",
                  font=("Segoe UI", 9),
                  command=dialog.destroy).pack(side="left", padx=6)

        entry.bind("<Return>", lambda e: _start())

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
        menu.add_command(label="✂  Couper ici (Ctrl+clic)",
                         command=lambda: self._split_clip_at_playhead(rect_id))
        menu.add_command(label="📋  Dupliquer",
                         command=self._duplicate_selected)
        menu.add_separator()
        # Sous-menu couleurs
        color_menu = tk.Menu(menu, tearoff=0,
                             bg="#1e1e1e", fg="white",
                             activebackground="#4CAF50",
                             activeforeground="white",
                             font=("Segoe UI", 9))
        color_labels = [
            ("🔵 Bleu (défaut)",  "#00b4d8"),
            ("🟢 Vert",           "#4CAF50"),
            ("🟡 Jaune",          "#FFC107"),
            ("🔴 Rouge",          "#f44336"),
            ("🟣 Violet",         "#9C27B0"),
            ("🟠 Orange",         "#FF5722"),
            ("🩵 Cyan",           "#00BCD4"),
            ("🩷 Rose",           "#E91E63"),
            ("⚫ Gris bleu",      "#607D8B"),
            ("🪲 Vert clair",     "#8BC34A"),
            ("🔶 Orange vif",     "#FF9800"),
            ("🫐 Indigo",         "#3F51B5"),
        ]
        for lbl, hex_c in color_labels:
            color_menu.add_command(
                label=lbl,
                command=lambda r=rect_id, c=hex_c: self._set_clip_color(r, c))
        menu.add_cascade(label="🎨  Couleur du clip", menu=color_menu)
        menu.add_separator()
        menu.add_command(label="🗑  Delete",
                         command=self._delete_selected)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _split_clip_at_playhead(self, rect_id):
        """Coupe le clip à la position du playhead (via menu contextuel)."""
        clip = self.clips.get(rect_id)
        if not clip:
            return
        split_time = self.playhead_pos
        c_start    = clip["start"]
        c_end      = c_start + clip["duration"]
        MIN_DUR    = 60.0 / self.bpm.get() / 2

        if split_time <= c_start + MIN_DUR or split_time >= c_end - MIN_DUR:
            from tkinter import messagebox
            messagebox.showwarning(
                "Split impossible",
                "Le playhead doit être à l intérieur du clip\n"
                "(pas trop près des bords).")
            return

        # Créer un event synthétique avec la position du playhead
        class _FakeEvent:
            pass
        e = _FakeEvent()
        e.x = int(split_time * self.pixels_per_second - self.canvas.canvasx(0))
        self._split_clip(e, rect_id)

    def _toggle_mute_clip(self, rect_id):
        """Mute/unmute un clip — assombrit visuellement."""
        clip = self.clips.get(rect_id)
        if not clip:
            return
        muted = clip.get("muted", False)
        clip["muted"] = not muted
        if clip["muted"]:
            self.canvas.itemconfig(rect_id, fill="#333333", outline="#555555")
        else:
            color   = clip.get("color", "#00b4d8")
            outline = self._darken(color)
            self.canvas.itemconfig(rect_id, fill=color, outline=outline)

    def _set_clip_color(self, rect_id, color: str):
        """Change la couleur d un clip et la persiste dans self.clips."""
        clip = self.clips.get(rect_id)
        if not clip:
            return
        clip["color"] = color
        outline = self._darken(color)
        try:
            self.canvas.itemconfig(rect_id, fill=color, outline=outline)
        except Exception:
            pass

    def _open_clip_editor(self, rect_id):
        clip = self.clips.get(rect_id)
        if not clip:
            return

        def on_updated(new_fp, new_dur):
            # Invalider le cache engine
            self.engine.invalidate_cache(new_fp)
            orig_start = clip.get("start", 0.0)
            orig_track = clip.get("track", 0)
            new_track  = self._find_free_track(orig_start, new_dur,
                                               start_from=orig_track + 1)
            import os as _os
            name  = _os.path.splitext(_os.path.basename(new_fp))[0]
            # Couleur verte pour distinguer le clip modifié
            EDITED_COLOR = "#4CAF50"
            self._snapshot()
            self.create_clip(
                track_index = new_track,
                start       = orig_start,
                duration    = new_dur,
                label       = name,
                filepath    = new_fp,
                color       = EDITED_COLOR,
            )

        ClipEditorWindow(self.root, clip_data=clip, on_updated=on_updated)

    def _delete_clip(self, rect_id):
        clip = self.clips.get(rect_id)
        if not clip:
            return
        self.canvas.delete(clip["tag"])
        del self.clips[rect_id]
        # Plus de clips → arrêter la lecture et reset playhead
        if not self.clips:
            if self.is_playing:
                self.is_playing = False
                self.btn_play._set_color("#4CAF50")
                self.engine.stop()
            self.playhead_pos = 0.0
            self._draw_playhead()
            self._update_time_label()

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

    def _add_track(self):
        """Ajoute une nouvelle piste depuis le bouton +."""
        self.create_track()
        # Repositionner le bouton + en bas
        self._btn_add_track.pack_forget()
        self._btn_add_track.pack(fill="x", pady=4, padx=4)
        # Étendre la grille
        self._redraw_grid_and_ruler()

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
        # Mettre à jour le scrollregion du track canvas
        try:
            self._track_canvas.update_idletasks()
            self._track_canvas.configure(
                scrollregion=self._track_canvas.bbox("all"))
        except Exception:
            pass

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

    def _find_free_track(self, start, duration, start_from=0):
        for t in range(start_from, start_from + max(20, len(self.tracks)) + 5):
            occupied = False
            for clip in self.clips.values():
                if clip["track"] == t:
                    cs, ce = clip["start"], clip["start"]+clip["duration"]
                    if not (start >= ce or start + duration <= cs):
                        occupied = True
                        break
            if not occupied:
                while len(self.tracks) <= t:
                    self._add_track()
                return t
        return start_from
    # Palette de couleurs disponibles pour les clips
    CLIP_COLORS = [
        ("#00b4d8", "#0077b6"),  # bleu (défaut)
        ("#4CAF50", "#2e7d32"),  # vert
        ("#FFC107", "#f57f17"),  # jaune
        ("#f44336", "#c62828"),  # rouge
        ("#9C27B0", "#6a1b9a"),  # violet
        ("#FF5722", "#bf360c"),  # orange
        ("#00BCD4", "#00838f"),  # cyan
        ("#E91E63", "#880e4f"),  # rose
        ("#607D8B", "#37474f"),  # gris bleu
        ("#8BC34A", "#558b2f"),  # vert clair
        ("#FF9800", "#e65100"),  # orange vif
        ("#3F51B5", "#1a237e"),  # indigo
    ]

    def create_clip(self, track_index, start, duration,
                    label="Clip", filepath=None, color=None):
        x0 = start    * self.pixels_per_second
        x1 = (start + duration) * self.pixels_per_second

        # Clip = hauteur complète de la piste (2px de marge haut/bas)
        MARGIN = 2
        y0 = track_index * self.track_height + MARGIN
        y1 = (track_index + 1) * self.track_height - MARGIN

        clip_id = len(self.clips) + int(time.time() * 1000) % 100000
        tag     = f"clip_{clip_id}"

        fill_color    = color if color else "#00b4d8"
        outline_color = self._darken(fill_color)

        rect = self._rounded_rect(
            x0, y0, x1, y1, r=7,
            fill=fill_color, outline=outline_color,
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
            "color":    fill_color,
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
                             lambda e, r=rect_id: self._clip_right_click(e, r))
        # Ctrl+clic gauche = SPLIT du clip à cet endroit
        self.canvas.tag_bind(tag, "<Control-ButtonPress-1>",
                             lambda e, r=rect_id: self._split_clip(e, r))

    def _clip_right_click(self, event, rect_id):
        """Clic droit sur clip → menu (annule le pan fond)."""
        self._bg_panning = False
        self._show_clip_menu(event, rect_id)

    def _split_clip(self, event, rect_id):
        """
        Ctrl+clic sur un clip = SPLIT.
        Coupe le clip en deux à la position exacte du clic.
        Le clip gauche garde le fichier audio original (début→split).
        Le clip droit garde le fichier audio original (split→fin).
        Les deux clips jouent la bonne portion grâce à start/duration.
        """
        clip = self.clips.get(rect_id)
        if not clip:
            return

        # Position du clic en secondes
        cx         = self.canvas.canvasx(event.x)
        split_time = cx / self.pixels_per_second

        # Vérifier que le split est bien DANS le clip
        c_start = clip["start"]
        c_end   = c_start + clip["duration"]
        MIN_DUR = 60.0 / self.bpm.get() / 2  # minimum = demi-temps

        if split_time <= c_start + MIN_DUR or split_time >= c_end - MIN_DUR:
            return  # trop près des bords

        self._snapshot()

        # Durées des deux moitiés
        left_dur  = split_time - c_start
        right_dur = c_end - split_time

        color = clip.get("color", "#00b4d8")
        fp    = clip.get("filepath")
        track = clip["track"]

        # Supprimer le clip original
        self._delete_clip(rect_id)
        if self._selected_clip == rect_id:
            self._selected_clip = None

        # Créer clip GAUCHE (début → split)
        self.create_clip(
            track_index = track,
            start       = c_start,
            duration    = left_dur,
            label       = clip["label"] + "_L",
            filepath    = fp,
            color       = color,
        )

        # Créer clip DROIT (split → fin)
        self.create_clip(
            track_index = track,
            start       = split_time,
            duration    = right_dur,
            label       = clip["label"] + "_R",
            filepath    = fp,
            color       = color,
        )

        print(f"[GUI] Split : {clip['label']} → L({left_dur:.2f}s) + R({right_dur:.2f}s)")

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
        'left'|'right'  → longueur (↔)
        'top'|'bottom'  → hauteur (↕) — zone 6px
        None            → drag libre
        """
        cx   = self.canvas.canvasx(event.x)
        cy   = self.canvas.canvasy(event.y)
        bbox = self._clip_bbox(rect_id)
        if not bbox:
            return None
        x0, y0, x1, y1 = bbox
        clip_h = y1 - y0

        # Priorité bords gauche/droit (longueur)
        if cx <= x0 + RESIZE_ZONE:
            return "left"
        if cx >= x1 - RESIZE_ZONE:
            return "right"
        # Bords haut/bas (hauteur) — zone 6px, seulement si clip assez haut
        VZ = 6  # zone verticale réduite
        if clip_h > 20:
            if cy <= y0 + VZ:
                return "top"
            if cy >= y1 - VZ:
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
                    cursor = "sb_v_double_arrow"
                else:
                    cursor = "fleur"
                break
        self.canvas.config(cursor=cursor)

    def _get_snap_px(self) -> float:
        """
        Retourne la valeur de snap en pixels selon BPM et zoom.
        Snap = 1 temps musical (beat).
        Si zoom très petit → snap sur mesure.
        Si zoom très grand → snap sur demi-temps.
        """
        bpm      = self.bpm.get()
        beat_sec = 60.0 / bpm
        beat_px  = beat_sec * self.pixels_per_second

        if beat_px < 8:
            # Très dézoomé → snap sur mesure
            sig = int(self.sig_var.get()) if hasattr(self, 'sig_var') else 4
            return beat_px * sig
        elif beat_px > 120:
            # Très zoomé → snap sur demi-temps
            return beat_px / 2
        else:
            return beat_px

    def _mouse_down(self, event, rect_id):
        tool = getattr(self, "_active_tool", "select")

        # Outil SPLIT → couper immédiatement
        if tool == "split":
            self._split_clip(event, rect_id)
            return

        # Outil MUTE → toggler transparence
        if tool == "mute":
            self._toggle_mute_clip(rect_id)
            return

        side = self._get_resize_side(event, rect_id)

        # Sélection multiple → déplacement en bloc
        if rect_id in self._selected_clips and not side:
            self._start_block_drag(event)
            return

        self._select_clip(rect_id)
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
        if self._block_dragging:
            self._block_drag_move(event)
        elif self._resize_item is not None:
            self._do_resize(cx, cy)
        elif self.drag_tag and self.drag_item is not None:
            dx = cx - self.drag_start_x
            dy = cy - self.drag_start_y
            # Mettre à jour la bbox stockée EN TEMPS RÉEL
            clip = self.clips.get(self.drag_item)
            if clip:
                clip["x0"] += dx
                clip["x1"] += dx
                clip["y0"] += dy
                clip["y1"] += dy
                self._redraw_clip(self.drag_item)
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
            snap = self._get_snap_px()
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

            snap  = self._get_snap_px()
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

            # Recalculer y = hauteur complète de la piste
            MARGIN = 2
            y0 = track * self.track_height + MARGIN
            y1 = (track + 1) * self.track_height - MARGIN

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
    def _load_recovery(self):
        """Au démarrage, propose de restaurer la session précédente."""
        # Chercher dans _recovery/ d'abord, puis ancien chemin
        recovery = os.path.join(PROJECTS_DIR, "_recovery", "_recovery.mdaw")
        if not os.path.exists(recovery):
            recovery = os.path.join(PROJECTS_DIR, "_recovery_autosave.mdaw")
        if not os.path.exists(recovery):
            return
        if self.clips:
            return  # déjà des clips chargés (projet ouvert)
        try:
            result = load_project(recovery)
            if not result:
                return
            bpm, clips_list, missing, meta = result
            if not clips_list:
                return
            # Compter les clips valides
            valid = [c for c in clips_list if not c.get("missing")]
            if not valid:
                return
            ans = messagebox.askyesno(
                "Restaurer la session précédente ?",
                f"mini_daw a trouvé une session non sauvegardée :\n"
                f"{len(valid)} clip(s) disponible(s).\n\n"
                "Veux-tu restaurer cette session ?")
            if ans:
                self.bpm.set(bpm)
                for c in valid:
                    self.create_clip(
                        track_index = c.get("track",    0),
                        start       = c.get("start",    0.0),
                        duration    = c.get("duration", 4.0),
                        label       = c.get("label",    "Clip"),
                        filepath    = c.get("filepath") or None,
                    )
                self._current_project = None  # force Save As au premier Ctrl+S
                print(f"[GUI] Session restaurée : {len(valid)} clip(s)")
        except Exception as e:
            print(f"[GUI] Erreur restauration : {e}")


    # ============================================================
    # SYSTÈME PROJET — NEW / OPEN / SAVE / TEMPLATE / IMPORT / EXPORT
    # ============================================================

    def _new_from_template(self, template_name):
        self._ask_project_name(
            callback=lambda name: self._create_new_project(name, template_name))

    def _new_from_template_dialog(self):
        win = tk.Toplevel(self.root)
        self._apply_icon(win)
        win.title("New from Template")
        win.configure(bg="#0f0f0f")
        win.resizable(True, True)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.minsize(360, 200)
        w, h = 420, 340
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        win.focus_set()
        win.lift()
        tk.Label(win, text="Choose a template",
                 bg="#0f0f0f", fg="#4CAF50",
                 font=("Segoe UI", 11, "bold")).pack(pady=(16, 8))
        templates = list_templates()
        selected  = tk.StringVar(value=templates[0]["name"] if templates else "")
        frame = tk.Frame(win, bg="#0f0f0f")
        frame.pack(fill="both", expand=True, padx=16)
        for tmpl in templates:
            row = tk.Frame(frame, bg="#1a1a1a", cursor="hand2")
            row.pack(fill="x", pady=2)
            row.bind("<Button-1>", lambda e, n=tmpl["name"]: selected.set(n))
            tk.Radiobutton(row, text=tmpl["name"],
                           variable=selected, value=tmpl["name"],
                           bg="#1a1a1a", fg="white", selectcolor="#333",
                           activebackground="#1a1a1a",
                           font=("Segoe UI", 9, "bold")).pack(
                               side="left", padx=8, pady=6)
            tk.Label(row,
                     text=f"  {tmpl['bpm']} BPM — {tmpl['description']}",
                     bg="#1a1a1a", fg="#888888",
                     font=("Segoe UI", 8)).pack(side="left")
        def _ok():
            t = selected.get()
            win.destroy()
            if t:
                self._new_from_template(t)
        bf = tk.Frame(win, bg="#0f0f0f")
        bf.pack(pady=12)
        tk.Button(bf, text="Create", bg="#4CAF50", fg="white",
                  relief="flat", padx=14, pady=6, cursor="hand2",
                  font=("Segoe UI", 9, "bold"),
                  command=_ok).pack(side="left", padx=6)
        tk.Button(bf, text="Cancel", bg="#2a2a2a", fg="white",
                  relief="flat", padx=10, pady=6, cursor="hand2",
                  font=("Segoe UI", 9),
                  command=win.destroy).pack(side="left", padx=6)

    def _ask_project_name(self, callback, default="Mon projet"):
        win = tk.Toplevel(self.root)
        self._apply_icon(win)
        win.title("Project Name")
        win.configure(bg="#0f0f0f")
        win.resizable(True, True)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.minsize(320, 130)
        w, h = 360, 140
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        win.focus_set()
        win.lift()
        tk.Label(win, text="Project name:",
                 bg="#0f0f0f", fg="#cccccc",
                 font=("Segoe UI", 10)).pack(pady=(20, 6))
        name_var = tk.StringVar(value=default)
        entry = tk.Entry(win, textvariable=name_var,
                         bg="#1e1e1e", fg="white",
                         insertbackground="white",
                         font=("Segoe UI", 11),
                         relief="flat", width=34)
        entry.pack(ipady=6, padx=20)
        entry.select_range(0, "end")
        entry.focus_set()
        def _ok():
            name = name_var.get().strip()
            if name:
                win.destroy()
                callback(name)
        entry.bind("<Return>", lambda e: _ok())
        bf = tk.Frame(win, bg="#0f0f0f")
        bf.pack(pady=10)
        tk.Button(bf, text="OK", bg="#4CAF50", fg="white",
                  relief="flat", padx=14, pady=5, cursor="hand2",
                  font=("Segoe UI", 9, "bold"),
                  command=_ok).pack(side="left", padx=6)
        tk.Button(bf, text="Cancel", bg="#2a2a2a", fg="white",
                  relief="flat", padx=10, pady=5, cursor="hand2",
                  font=("Segoe UI", 9),
                  command=win.destroy).pack(side="left", padx=6)

    def _create_new_project(self, name, template="Blank"):
        if self.clips:
            ok = messagebox.askyesno(
                "New Project",
                "Save current project before continuing?")
            if ok:
                self._save_project()
        for clip in list(self.clips.values()):
            self.canvas.delete(clip["tag"])
        self.clips.clear()
        self._undo_stack.clear()
        self._redo_stack.clear()
        result = new_project(name, template)
        if result:
            self._current_project = result["mdaw_path"]
            self._project_dir     = result["project_dir"]
            self.bpm.set(result["bpm"])
            self.root.title(f"mini_daw — {name}")
            print(f"[GUI] Nouveau projet : {name} ({template})")

    def _open_project(self):
        projects = list_projects()
        win = tk.Toplevel(self.root)
        self._apply_icon(win)
        win.title("Open Project")
        win.configure(bg="#0f0f0f")
        win.resizable(True, True)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        w, h = 520, 380
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        win.focus_set()
        win.lift()
        tk.Label(win, text="Open a project",
                 bg="#0f0f0f", fg="#4CAF50",
                 font=("Segoe UI", 11, "bold")).pack(pady=(14, 2))
        tk.Label(win, text=f"{len(projects)} projet(s) disponible(s)",
                 bg="#0f0f0f", fg="#888",
                 font=("Segoe UI", 8)).pack()
        lf = tk.Frame(win, bg="#0f0f0f")
        lf.pack(fill="both", expand=True, padx=12, pady=8)
        sb = tk.Scrollbar(lf)
        sb.pack(side="right", fill="y")
        lb = tk.Listbox(lf, bg="#1a1a1a", fg="white",
                        selectbackground="#4CAF50",
                        font=("Segoe UI", 9), relief="flat",
                        yscrollcommand=sb.set)
        lb.pack(fill="both", expand=True)
        sb.config(command=lb.yview)
        if not projects:
            lb.insert("end", "  Aucun projet — crée d'abord un projet (Ctrl+N)")
        for p in projects:
            saved = p["saved_at"][:16] if p["saved_at"] else "—"
            lb.insert("end",
                      f"  {p['name']}   ·   {p['bpm']} BPM   ·   {saved}")
        def _load():
            sel = lb.curselection()
            if not sel or not projects:
                return
            p = projects[sel[0]]
            win.destroy()
            self._load_project_from_mdaw(p["mdaw"])
        lb.bind("<Double-Button-1>", lambda e: _load())
        bf = tk.Frame(win, bg="#0f0f0f")
        bf.pack(pady=8)
        tk.Button(bf, text="Open", bg="#4CAF50", fg="white",
                  relief="flat", padx=14, pady=6, cursor="hand2",
                  font=("Segoe UI", 9, "bold"),
                  command=_load).pack(side="left", padx=6)
        tk.Button(bf, text="Cancel", bg="#2a2a2a", fg="white",
                  relief="flat", padx=10, pady=6, cursor="hand2",
                  font=("Segoe UI", 9),
                  command=win.destroy).pack(side="left", padx=6)

    def _load_project_from_mdaw(self, mdaw_path):
        result = load_project(mdaw_path)
        if not result:
            messagebox.showerror("Erreur",
                "Impossible de charger ce projet.")
            return
        bpm, clips_list, missing_list, meta = result
        for clip in list(self.clips.values()):
            self.canvas.delete(clip["tag"])
        self.clips.clear()
        self.bpm.set(bpm)
        self._current_project = mdaw_path
        self._project_dir     = os.path.dirname(mdaw_path)
        for c in clips_list:
            if c.get("missing"):
                missing_name = os.path.basename(c.get("filepath", ""))
                # Chercher automatiquement dans les dossiers connus
                found_path = self._search_missing_file(missing_name)
                if found_path:
                    c["filepath"] = found_path
                else:
                    ans = messagebox.askyesno(
                        "Fichier manquant",
                        f"Introuvable : {missing_name}\n\n"
                        "Veux-tu le localiser manuellement ?")
                    if ans:
                        # Choisir le meilleur dossier de départ :
                        # 1. audio/ du projet courant
                        # 2. dossier projet
                        # 3. samples/
                        # 4. Bureau utilisateur
                        audio_sub = os.path.join(
                            self._project_dir, "audio") if getattr(
                            self, "_project_dir", None) else ""
                        if audio_sub and os.path.isdir(audio_sub):
                            init_dir = audio_sub
                        elif getattr(self, "_project_dir", None) and os.path.isdir(self._project_dir):
                            init_dir = self._project_dir
                        elif os.path.isdir(SAMPLES_DIR):
                            init_dir = SAMPLES_DIR
                        else:
                            init_dir = os.path.expanduser("~")
                        fp = filedialog.askopenfilename(
                            title=f"Retrouver : {missing_name}",
                            initialdir=init_dir,
                            filetypes=[("Audio",
                                        "*.wav *.mp3 *.flac *.ogg "                                        "*.aiff *.aif *.m4a"),
                                       ("Tous les fichiers", "*.*")])
                        if fp:
                            c["filepath"] = fp
                        else:
                            continue
                    else:
                        continue
            self.create_clip(
                track_index = c.get("track",    0),
                start       = c.get("start",    0.0),
                duration    = c.get("duration", 4.0),
                label       = c.get("label",    "Clip"),
                filepath    = c.get("filepath") or None,
                color       = c.get("color")    or None,
            )
        name = meta.get("name", "")
        self.root.title(f"mini_daw — {name}")
        print(f"[GUI] Project loaded: {name}")

    def _save_project_as_dialog(self):
        """Save As — demande un nom, crée projects/nom/audio/, sauvegarde."""
        proj = self._current_project or ""
        default = "My Project"
        if proj and "_recovery" not in proj:
            default = os.path.splitext(os.path.basename(proj))[0]

        def _do(name):
            name = name.strip()
            if not name:
                return
            # Créer le projet
            result = save_project_as(
                name, self.clips, self.bpm.get(),
                src_mdaw=proj)
            if not result:
                messagebox.showerror("Save As", "Save failed — check the name.")
                return
            # Mettre à jour l'état
            self._current_project = result["mdaw_path"]
            self._project_dir     = result["project_dir"]
            self.root.title(f"mini_daw — {name}")
            # Recharger le projet depuis le .mdaw pour synchroniser
            # tous les chemins (plus fiable que la mise à jour manuelle)
            proj_dir = result["project_dir"]
            mdaw     = result["mdaw_path"]
            self._reload_project_after_save(mdaw)
            messagebox.showinfo(
                "Saved",
                f"Project : {name}\n"
                f"Location : {proj_dir}")
            print(f"[GUI] Save As OK: {proj_dir}")

        self._ask_project_name(_do, default=default)

    def _save_as_template_dialog(self):
        def _do(name):
            ok = save_as_template(name, self.clips, self.bpm.get())
            if ok:
                messagebox.showinfo("Template sauvegardé",
                    f"'{name}' disponible dans New > From Template")
        self._ask_project_name(_do, default="Mon template")

    def _import_dialog(self):
        path = filedialog.askopenfilename(
            title="Importer un fichier audio",
            initialdir=os.path.expanduser("~"),
            filetypes=[("Audio", "*.wav *.mp3 *.flac *.ogg *.aiff"),
                       ("Tous", "*.*")])
        if not path:
            return
        if os.path.splitext(path)[1].lower() == ".mdaw":
            messagebox.showwarning("Format invalide",
                "Utilise Open pour ouvrir un projet .mdaw.")
            return
        self._import_from_path(path)

    def _export_dialog(self, fmt="wav"):
        ext_map = {"wav": ".wav", "mp3": ".mp3", "ogg": ".ogg"}
        ext     = ext_map.get(fmt, ".wav")
        name    = "mixdown"
        if self._current_project:
            name = os.path.splitext(
                os.path.basename(self._current_project))[0]
        if getattr(self, "_project_dir", None):
            init_dir = self._project_dir
        else:
            init_dir = os.path.expanduser("~/Desktop")
        os.makedirs(init_dir, exist_ok=True)
        path = filedialog.asksaveasfilename(
            title=f"Export {fmt.upper()}",
            initialdir=init_dir,
            initialfile=f"{name}{ext}",
            defaultextension=ext,
            filetypes=[(f"{fmt.upper()}", f"*{ext}"),
                       ("Tous", "*.*")])
        if not path:
            return
        def _done(p):
            def _ui():
                if p:
                    messagebox.showinfo("Export OK", f"Exporté :\n{p}")
                    try: os.startfile(os.path.dirname(p))
                    except: pass
                else:
                    messagebox.showerror("Erreur", "Export échoué.")
            self.root.after(0, _ui)
        if fmt == "wav":   export_wav(self.clips, path, on_done=_done)
        elif fmt == "mp3": export_mp3(self.clips, path, on_done=_done)
        elif fmt == "ogg": export_ogg(self.clips, path, on_done=_done)

    def _export_stems_dialog(self):
        if getattr(self, "_project_dir", None):
            out_dir = os.path.join(self._project_dir, "stems")
        else:
            out_dir = filedialog.askdirectory(
                title="Dossier destination pour les stems")
        if not out_dir:
            return
        os.makedirs(out_dir, exist_ok=True)
        def _done(files):
            def _ui():
                if files:
                    messagebox.showinfo("Stems exportés",
                        f"{len(files)} fichier(s) dans :\n{out_dir}")
                    try: os.startfile(out_dir)
                    except: pass
                else:
                    messagebox.showerror("Erreur", "Export stems échoué.")
            self.root.after(0, _ui)
        export_stems(self.clips, out_dir, on_done=_done)

    def _export_zip_dialog(self):
        if not getattr(self, "_project_dir", None):
            messagebox.showwarning("Projet requis",
                "Fais d'abord Ctrl+S pour créer le dossier projet.")
            return
        name = os.path.basename(self._project_dir)
        path = filedialog.asksaveasfilename(
            title="Zipped Loop Package",
            initialdir=os.path.expanduser("~/Desktop"),
            initialfile=f"{name}.zip",
            defaultextension=".zip",
            filetypes=[("ZIP", "*.zip")])
        if not path:
            return
        def _done(p):
            def _ui():
                if p:
                    messagebox.showinfo("ZIP créé", f"Archive :\n{p}")
                    try: os.startfile(os.path.dirname(p))
                    except: pass
                else:
                    messagebox.showerror("Erreur", "ZIP échoué.")
            self.root.after(0, _ui)
        export_zip(self._project_dir, path, on_done=_done)

    def _auto_save_loop(self):
        proj = self._current_project or ""
        if self.clips and proj and "_recovery" not in proj:
            try:
                save_project(proj, self.clips, self.bpm.get())
                print("[GUI] Auto-save ✔")
            except Exception as e:
                print(f"[GUI] Auto-save error: {e}")
        try:
            self.root.after(120_000, self._auto_save_loop)
        except Exception:
            pass

    def _on_close(self):
        # Marquer les modifications non sauvegardées
        proj = self._current_project or ""

        if self.clips:
            if proj and "_recovery" not in proj:
                # Projet nommé → demander si sauvegarder
                title = os.path.basename(proj) if proj else "ce projet"
                from tkinter import messagebox as _mb
                ans = _mb.askyesnocancel(
                    "Sauvegarder avant de quitter ?",
                    ("Voulez-vous sauvegarder les modifications de :\n"
                     + title +
                     "\nOui = sauvegarder et quitter"
                     "\nNon = quitter sans sauvegarder"
                     "\nAnnuler = rester dans mini_daw"))
                if ans is None:
                    return  # Annuler → ne pas quitter
                if ans:
                    try:
                        save_project(proj, self.clips, self.bpm.get())
                        print(f"[GUI] Saved on exit: {proj}")
                    except Exception as e:
                        print(f"[GUI] Exit save error: {e}")
            else:
                # Pas de projet nommé → proposer de sauvegarder
                from tkinter import messagebox as _mb
                ans = _mb.askyesnocancel(
                    "Sauvegarder avant de quitter ?",
                    ("Clips non sauvegardes."
                     "\nOui = Save As puis quitter"
                     "\nNon = quitter sans sauvegarder"
                     "\nAnnuler = rester dans mini_daw"))
                if ans is None:
                    return
                if ans:
                    self._save_project_as_dialog()
                    return  # La dialog gère la suite

        self._shutdown()

    def _shutdown(self):
        """Arrêt propre de toutes les ressources."""
        try:
            self.metronome.stop()
        except Exception:
            pass
        try:
            self.engine.cleanup()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


# ============================================================
# FENÊTRE HISTORIQUE
# ============================================================

    # ADD MENU methods

    # ============================================================
    # ADD MENU — Plugin / Channel / Effect / Automation
    # ============================================================
    def _add_channel(self):
        messagebox.showinfo("Add Channel",
            "Channel Rack — coming soon.\n"
            "Will support VST2/VST3 instruments and samplers.")

    def _add_effect(self):
        messagebox.showinfo("Add Effect",
            "Mixer effect slots — coming soon.\n"
            "Will support VST2/VST3 effects.")

    def _view_plugin_picker(self):
        self._plugin_picker_window()

    def _plugin_picker_window(self):
        win = tk.Toplevel(self.root)
        self._apply_icon(win)
        win.title("mini_daw — Plugin Picker")
        win.configure(bg="#0f0f0f")
        win.resizable(True, True)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.minsize(500, 380)
        w, h = 620, 480
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        tk.Label(win, text="Plugin Picker",
                 bg="#0f0f0f", fg="#4CAF50",
                 font=("Segoe UI", 12, "bold")).pack(pady=(14, 2))
        tk.Label(win, text="VST2 / VST3 support — Phase 2",
                 bg="#0f0f0f", fg="#555555",
                 font=("Segoe UI", 9)).pack()
        # Category filter
        cats = tk.Frame(win, bg="#0f0f0f")
        cats.pack(fill="x", padx=12, pady=8)
        self._plugin_cat = tk.StringVar(value="All")
        for cat in ["All", "Instruments", "Effects",
                    "Generators", "MIDI", "VST3"]:
            tk.Radiobutton(cats, text=cat,
                           variable=self._plugin_cat, value=cat,
                           bg="#0f0f0f", fg="white", selectcolor="#333",
                           activebackground="#0f0f0f",
                           font=("Segoe UI", 8),
                           command=self._filter_plugins
                           ).pack(side="left", padx=6)
        # Search bar
        sf = tk.Frame(win, bg="#0f0f0f")
        sf.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(sf, text="Search:", bg="#0f0f0f", fg="#888",
                 font=("Segoe UI", 8)).pack(side="left")
        self._plugin_search = tk.StringVar()
        self._plugin_search.trace_add("write", lambda *a: self._filter_plugins())
        tk.Entry(sf, textvariable=self._plugin_search,
                 bg="#1e1e1e", fg="white",
                 insertbackground="white",
                 font=("Segoe UI", 9), relief="flat"
                 ).pack(side="left", fill="x",
                        expand=True, padx=8, ipady=4)
        # Plugin list
        lf = tk.Frame(win, bg="#0f0f0f")
        lf.pack(fill="both", expand=True, padx=12)
        sb = tk.Scrollbar(lf)
        sb.pack(side="right", fill="y")
        self._plugin_lb = tk.Listbox(
            lf, bg="#1a1a1a", fg="white",
            selectbackground="#4CAF50",
            font=("Consolas", 9), relief="flat",
            yscrollcommand=sb.set)
        self._plugin_lb.pack(fill="both", expand=True)
        sb.config(command=self._plugin_lb.yview)
        self._plugin_data = [
            {"name": "Native Reverb",  "cat": "Effects",  "type": "Native"},
            {"name": "Native EQ",      "cat": "Effects",  "type": "Native"},
            {"name": "Native Delay",   "cat": "Effects",  "type": "Native"},
            {"name": "Pitch Shift",    "cat": "Effects",  "type": "Native"},
            {"name": "MIDI Out",       "cat": "MIDI",     "type": "Native"},
            {"name": "(Scan VST below)", "cat": "All",    "type": "Info"},
        ]
        self._filter_plugins()
        # Buttons
        tk.Frame(win, bg="#222", height=1).pack(fill="x", pady=4)
        bf = tk.Frame(win, bg="#0a0a0a")
        bf.pack(fill="x", padx=10, pady=6)
        tk.Button(bf, text="Scan VST Folders",
                  bg="#2a2a2a", fg="white", relief="flat",
                  padx=10, pady=5, cursor="hand2",
                  font=("Segoe UI", 8),
                  command=self._refresh_plugins
                  ).pack(side="left", padx=4)
        tk.Button(bf, text="Load Plugin",
                  bg="#4CAF50", fg="white", relief="flat",
                  padx=14, pady=5, cursor="hand2",
                  font=("Segoe UI", 9, "bold"),
                  command=lambda: self._load_plugin(win)
                  ).pack(side="right", padx=4)
        tk.Button(bf, text="Close",
                  bg="#2a2a2a", fg="white", relief="flat",
                  padx=10, pady=5, cursor="hand2",
                  font=("Segoe UI", 9),
                  command=win.destroy).pack(side="right", padx=4)

    def _filter_plugins(self):
        try:
            cat    = getattr(self, "_plugin_cat",
                             tk.StringVar(value="All")).get()
            search = getattr(self, "_plugin_search",
                             tk.StringVar()).get().lower()
            lb     = getattr(self, "_plugin_lb", None)
            data   = getattr(self, "_plugin_data", [])
            if not lb:
                return
            lb.delete(0, "end")
            for p in data:
                if cat != "All" and p["cat"] != cat:
                    continue
                if search and search not in p["name"].lower():
                    continue
                lb.insert("end", f"  [{p['type']:8}]  {p['name']}")
        except Exception:
            pass

    def _load_plugin(self, win):
        messagebox.showinfo("Load Plugin",
            "VST loading — Phase 2.\n"
            "Currently mini_daw uses native audio processing.")
        win.destroy()

    def _browse_plugins(self, mode="database"):
        msgs = {
            "database": (
                "Plugin database browser — Phase 2.\n"
                "Will index all VST2/VST3 plugins with metadata."),
            "installed": (
                "Installed plugins — Phase 2.\n"
                "Shows plugins found in configured scan folders."),
            "presets": (
                "Preset browser — Phase 2.\n"
                "Will browse .fxp / .fxb / native preset files."),
        }
        messagebox.showinfo(
            f"Browse — {mode.title()}", msgs.get(mode, ""))

    def _refresh_plugins(self):
        import glob
        vst_dirs = [
            r"C:\Program Files\VSTPlugins",
            r"C:\Program Files\Common Files\VST3",
            r"C:\Program Files (x86)\VSTPlugins",
            r"C:\Program Files (x86)\Steinberg\VstPlugins",
        ]
        found = []
        for d in vst_dirs:
            if os.path.isdir(d):
                found += glob.glob(
                    os.path.join(d, "**", "*.dll"), recursive=True)
                found += glob.glob(
                    os.path.join(d, "**", "*.vst3"), recursive=True)
        if found:
            messagebox.showinfo("Plugin Scan",
                f"Found {len(found)} plugin file(s).\n"
                "Full VST loading available in Phase 2.")
        else:
            messagebox.showinfo("Plugin Scan",
                "No VST plugins found.\n"
                "Standard Windows VST folders were scanned.")

    def _manage_plugins(self):
        messagebox.showinfo("Manage Plugins",
            "Plugin Manager — Phase 2.\n"
            "Configure VST scan folders, enable/disable,\n"
            "categorize and blacklist plugins.")

    def _add_automation(self):
        messagebox.showinfo("Automation",
            "Automation clip — Phase 2.\n"
            "Will create a clip linked to the last\n"
            "adjusted parameter (volume, pan, BPM...).")



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
        self.win.title("mini_daw — File History")
        self.win.configure(bg="#0f0f0f")
        self.win.geometry("560x500")
        self.win.resizable(True, True)
        self.win.protocol("WM_DELETE_WINDOW", self.win.destroy)

        try:
            ico = os.path.join(os.path.dirname(__file__), "assets", "logo.ico")
            if os.path.exists(ico):
                self.win.iconbitmap(ico)
        except Exception:
            pass

        self.win.focus_set()
        self.win.lift()
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
