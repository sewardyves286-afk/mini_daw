import tkinter as tk
from tkinter import filedialog
import os
from engine import AudioEngine

SAMPLES_FOLDER = "samples"

class MiniDAWApp:
    def __init__(self):
        self.engine = AudioEngine()
        self.root = tk.Tk()
        self.root.title("Mini DAW")
        self.root.geometry("900x600")
        self.root.resizable(False, False)  # empêche l'agrandissement bug

        self.selected_block = None
        self.offset_x = 0

        # ====== TITRE ======
        title = tk.Label(self.root, text="Mini DAW - Track Manager", font=("Arial", 16))
        title.pack(pady=10)

        # ====== BOUTONS ======
        import_button = tk.Button(
            self.root,
            text="Importer un son",
            command=self.import_audio
        )
        import_button.pack(pady=5)

        load_button = tk.Button(
            self.root,
            text="Charger les Samples",
            command=self.load_samples
        )
        load_button.pack(pady=5)

        play_button = tk.Button(
            self.root,
            text="▶ Play",
            command=self.play
        )
        play_button.pack(pady=5)

        stop_button = tk.Button(
            self.root,
            text="⏹ Stop",
            command=self.stop
        )
        stop_button.pack(pady=5)

        # ====== MIXER (PISTES + SLIDERS) ======
        self.track_frame = tk.Frame(self.root)
        self.track_frame.pack(fill="x", padx=10, pady=10)

        # ====== TIMELINE (UNE SEULE !) ======
        timeline_label = tk.Label(self.root, text="Timeline (Composition)", font=("Arial", 12))
        timeline_label.pack(pady=5)

        self.timeline = tk.Canvas(
            self.root,
            width=860,
            height=200,
            bg="#1e1e1e",
            highlightthickness=0
        )
        self.timeline.pack(padx=10, pady=5)

    # ====== IMPORT AUDIO ======
    def import_audio(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("Audio Files", "*.wav *.mp3 *.flac")]
        )

        if not file_path:
            return

        print("Fichier chargé :", file_path)
        self.engine.add_track(file_path, volume=0.8)

        file_name = os.path.basename(file_path)
        short_name = file_name[:12] + "..." if len(file_name) > 12 else file_name

        track_index = len(self.engine.tracks) - 1
        y_position = 30 * track_index + 10

        # ====== BLOC TIMELINE ======
        block = self.timeline.create_rectangle(
            10, y_position, 150, y_position + 20,
            fill="#4CAF50",
            outline=""
        )

        self.timeline.create_text(
            80, y_position + 10,
            text=short_name,
            fill="white",
            font=("Arial", 8)
        )

        # Drag & Drop
        self.timeline.tag_bind(block, "<Button-1>", self.on_block_click)
        self.timeline.tag_bind(block, "<B1-Motion>", self.on_block_drag)
        self.timeline.tag_bind(block, "<ButtonRelease-1>", self.on_block_release)

        # ====== MIXER LINE ======
        track_container = tk.Frame(self.track_frame)
        track_container.pack(fill="x", pady=2)

        label = tk.Label(track_container, text=f"🎵 {short_name}")
        label.pack(side="left")

        volume_slider = tk.Scale(
            track_container,
            from_=0,
            to=1,
            resolution=0.01,
            orient="horizontal",
            command=lambda val, i=track_index: self.set_volume(i, val)
        )
        volume_slider.set(0.8)
        volume_slider.pack(side="right")

    # ====== LOAD SAMPLES ======
    def load_samples(self):
        self.track_frame.destroy()
        self.track_frame = tk.Frame(self.root)
        self.track_frame.pack(fill="x", padx=10, pady=10)

        self.timeline.delete("all")
        self.engine.clear_tracks()

        if not os.path.exists(SAMPLES_FOLDER):
            print("Dossier samples introuvable")
            return

        files = [f for f in os.listdir(SAMPLES_FOLDER) if f.endswith(".wav")]

        for i, file in enumerate(files):
            path = os.path.join(SAMPLES_FOLDER, file)
            self.engine.add_track(path, volume=0.8)

            short_name = file[:12] + "..." if len(file) > 12 else file
            y_position = 30 * i + 10

            block = self.timeline.create_rectangle(
                10, y_position, 150, y_position + 20,
                fill="#2196F3",
                outline=""
            )

            self.timeline.create_text(
                80, y_position + 10,
                text=short_name,
                fill="white",
                font=("Arial", 8)
            )

            self.timeline.tag_bind(block, "<Button-1>", self.on_block_click)
            self.timeline.tag_bind(block, "<B1-Motion>", self.on_block_drag)
            self.timeline.tag_bind(block, "<ButtonRelease-1>", self.on_block_release)

            track_container = tk.Frame(self.track_frame)
            track_container.pack(fill="x", pady=2)

            label = tk.Label(track_container, text=f"🎵 {short_name}")
            label.pack(side="left")

            volume_slider = tk.Scale(
                track_container,
                from_=0,
                to=1,
                resolution=0.01,
                orient="horizontal",
                command=lambda val, idx=i: self.set_volume(idx, val)
            )
            volume_slider.set(0.8)
            volume_slider.pack(side="right")

        print(f"{len(files)} samples chargés.")

    # ====== DRAG BLOCS ======
    def on_block_click(self, event):
        items = self.timeline.find_withtag("current")
        if items:
            self.selected_block = items[0]
            coords = self.timeline.coords(self.selected_block)
            self.offset_x = event.x - coords[0]

    def on_block_drag(self, event):
        if self.selected_block:
            x = max(0, min(event.x - self.offset_x, 700))  # limite zone timeline
            coords = self.timeline.coords(self.selected_block)
            y1, y2 = coords[1], coords[3]
            self.timeline.coords(self.selected_block, x, y1, x + 140, y2)

    def on_block_release(self, event):
        self.selected_block = None

    # ====== AUDIO ======
    def play(self):
        self.engine.play()

    def stop(self):
        self.engine.stop()

    def set_volume(self, track_index, value):
        try:
            self.engine.tracks[track_index]["volume"] = float(value)
        except:
            pass

    def run(self):
        self.root.mainloop()
