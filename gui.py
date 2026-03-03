import tkinter as tk
from tkinter import filedialog
import os
import sys
import time
from engine import AudioEngine

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

SAMPLES_FOLDER = resource_path("samples")

class MiniDAWApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("mini_daw")
        self.root.geometry("1000x600")
        self.root.configure(bg="#1e1e1e")
        self.root.resizable(False, False)

        # Icône sécurisée
        try:
            icon_path = resource_path("assets/logo.ico")
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception as e:
            print("Icon error:", e)

        self.engine = AudioEngine()
        self.is_playing = False
        self.start_time = 0
        self.playhead_x = 0

        # Transport bar
        self.transport_bar = tk.Frame(self.root, bg="#141414", height=36)
        self.transport_bar.pack(fill="x", side="top")

        btn_style = {
            "bg": "#1f1f1f",
            "fg": "#ffffff",
            "activebackground": "#2a2a2a",
            "activeforeground": "#ffffff",
            "bd": 1,
            "font": ("Segoe UI", 9),
            "width": 6,
            "cursor": "hand2"
        }

        tk.Button(self.transport_bar, text="Play", command=self.play, **btn_style).pack(side="left", padx=4, pady=4)
        tk.Button(self.transport_bar, text="Stop", command=self.stop, **btn_style).pack(side="left", padx=2, pady=4)
        tk.Button(self.transport_bar, text="Import", command=self.import_audio, **btn_style).pack(side="left", padx=7, pady=4)
        tk.Button(self.transport_bar, text="Samples", command=self.load_samples, **btn_style).pack(side="left", padx=7, pady=4)

        # Canvas
        self.canvas = tk.Canvas(self.root, bg="#202020", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.playhead = self.canvas.create_line(0, 0, 0, 900, fill="#ff3b3b", width=2)
        self.canvas.bind("<Configure>", self.redraw_grid)

    def redraw_grid(self, event=None):
        self.canvas.delete("grid")
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()

        for x in range(0, width, 70):
            self.canvas.create_line(x, 0, x, height, fill="#2a2a2a", tags="grid")

        for y in range(0, height, 40):
            self.canvas.create_line(0, y, width, y, fill="#252525", tags="grid")

    def play(self):
        self.engine.play()
        self.is_playing = True
        self.start_time = time.time()
        self.update_playhead()

    def stop(self):
        self.engine.stop()
        self.is_playing = False
        self.canvas.coords(self.playhead, 0, 0, 0, self.canvas.winfo_height())

    def update_playhead(self):
        if not self.is_playing:
            return

        elapsed = time.time() - self.start_time
        self.playhead_x = elapsed * 120

        self.canvas.coords(
            self.playhead,
            self.playhead_x,
            0,
            self.playhead_x,
            self.canvas.winfo_height()
        )

        self.root.after(16, self.update_playhead)

    def import_audio(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("Audio Files", "*.wav *.mp3 *.flac")]
        )
        if file_path:
            self.engine.add_track(file_path)

    def load_samples(self):
        if not os.path.exists(SAMPLES_FOLDER):
            return

        files = [f for f in os.listdir(SAMPLES_FOLDER) if f.endswith(".wav")]
        for f in files:
            self.engine.add_track(os.path.join(SAMPLES_FOLDER, f))

    def run(self):
        self.root.mainloop()