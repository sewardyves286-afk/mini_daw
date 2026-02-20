import tkinter as tk
from tkinter import filedialog, ttk
import os
import time
from engine import AudioEngine

SAMPLES_FOLDER = "samples"

# ===== TOOLTIP =====
class ToolTip:
    """Tooltip style DAW (survol souris)"""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, event=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + 20
        self.tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.configure(bg="#111111")
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw,
            text=self.text,
            bg="#111111",
            fg="#eeeeee",
            relief="solid",
            borderwidth=1,
            font=("Segoe UI", 9)
        )
        label.pack(ipadx=6, ipady=2)

    def hide(self, event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None

# ===== GUI MINI DAW =====
class MiniDAWApp:
    def __init__(self):
        # CORE
        self.root = tk.Tk()
        self.root.title("Mini DAW")
        self.root.geometry("1000x600")
        self.root.configure(bg="#1e1e1e")
        self.root.resizable(False, False)
        try:
            self.root.iconbitmap("icon.ico")
        except: pass

        self.engine = AudioEngine()
        self.is_playing = False
        self.start_time = 0
        self.playhead_x = 0
        self.selected_block = None
        self.offset_x = 0

        # ===== MAIN FRAME =====
        self.main_frame = tk.Frame(self.root, bg="#1e1e1e")
        self.main_frame.pack(fill="both", expand=True)

        # ===== TRANSPORT BAR =====
        self.transport_bar = tk.Frame(self.main_frame, bg="#141414", height=36)
        self.transport_bar.pack(fill="x", side="top")
        self.transport_bar.pack_propagate(False)

        btn_style = {
            "bg": "#1f1f1f",
            "fg": "#ffffff",
            "activebackground": "#2a2a2a",
            "activeforeground": "#ffffff",
            "bd": 0,
            "font": ("Segoe UI", 9),
            "width": 5,
            "cursor": "hand2"
        }

        self.play_btn = tk.Button(self.transport_bar, text="Play", command=self.play, **btn_style)
        self.play_btn.pack(side="left", padx=4, pady=4)
        ToolTip(self.play_btn, "Start playback")

        self.stop_btn = tk.Button(self.transport_bar, text="Stop", command=self.stop, **btn_style)
        self.stop_btn.pack(side="left", padx=2, pady=4)
        ToolTip(self.stop_btn, "Stop playback")

        self.import_btn = tk.Button(self.transport_bar, text="Import", command=self.import_audio, **btn_style)
        self.import_btn.pack(side="left", padx=6, pady=4)
        ToolTip(self.import_btn, "Import audio file")

        self.samples_btn = tk.Button(self.transport_bar, text="Samples", command=self.load_samples, **btn_style)
        self.samples_btn.pack(side="left", padx=4, pady=4)
        ToolTip(self.samples_btn, "Load samples folder")

        # ===== CONTENT AREA =====
        self.content = tk.Frame(self.main_frame, bg="#1e1e1e")
        self.content.pack(fill="both", expand=True)

        # ===== MIXER PANEL (PRO COMPACT) =====
        self.mixer_panel = tk.Frame(self.content, bg="#181818", width=100)
        self.mixer_panel.pack(side="left", fill="y")
        self.mixer_panel.pack_propagate(False)
        tk.Label(self.mixer_panel, text="Mixer", bg="#181818", fg="#aaaaaa", font=("Segoe UI", 10)).pack(pady=6)

        self.track_widgets = []

        # ===== TIMELINE =====
        self.timeline_container = tk.Frame(self.content, bg="#1e1e1e")
        self.timeline_container.pack(side="right", fill="both", expand=True)

        self.canvas = tk.Canvas(self.timeline_container, bg="#202020", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self.redraw_grid)

        self.playhead = self.canvas.create_line(0,0,0,1000, fill="#ff3b3b", width=2)

    # ===== GRID =====
    def redraw_grid(self, event=None):
        self.canvas.delete("grid")
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        # Vertical lines
        for x in range(0, width, 80):
            self.canvas.create_line(x, 0, x, height, fill="#2a2a2a", tags="grid")
        # Horizontal lines (track lanes)
        for y in range(0, height, 60):
            self.canvas.create_line(0, y, width, y, fill="#252525", tags="grid")
        self.canvas.tag_lower("grid")

    # ===== ADD TRACK =====
    def add_track(self, file_path, color="#4CAF50"):
        self.engine.add_track(file_path, volume=0.8)
        track_index = len(self.engine.tracks)-1
        file_name = os.path.basename(file_path)
        short_name = file_name[:12]+"..." if len(file_name)>12 else file_name
        y = 40*track_index + 20

        # Timeline block
        block = self.canvas.create_rectangle(20, y, 180, y+25, fill=color, outline="")
        self.canvas.create_text(100, y+12, text=short_name, fill="white", font=("Segoe UI", 8))
        self.canvas.tag_bind(block, "<Button-1>", self.on_block_click)
        self.canvas.tag_bind(block, "<B1-Motion>", self.on_block_drag)
        self.canvas.tag_bind(block, "<ButtonRelease-1>", self.on_block_release)

        # ===== MIXER TRACK PRO =====
        track_frame = tk.Frame(self.mixer_panel, bg="#181818")
        track_frame.pack(pady=4)

        tk.Label(track_frame, text=f"T{track_index+1}", bg="#181818", fg="#cccccc", font=("Segoe UI", 8)).pack()

        # Volume fader
        slider = tk.Scale(
            track_frame, from_=1.0, to=0.0, resolution=0.01, orient="vertical",
            length=110, width=6, sliderlength=12,
            bg="#181818", fg="#aaaaaa", troughcolor="#2a2a2a",
            activebackground="#4CAF50", highlightthickness=0,
            command=lambda val,i=track_index:self.set_volume(i,val)
        )
        slider.set(0.8)
        slider.pack(pady=2)
        ToolTip(slider,f"Volume Track {track_index+1}")

        # Mute / Solo / Pan
        mute_btn = tk.Button(track_frame, text="M", width=2, bg="#333333", fg="white",
                             command=lambda i=track_index:self.toggle_mute(i))
        mute_btn.pack(side="left", padx=1)
        ToolTip(mute_btn,"Mute Track")

        solo_btn = tk.Button(track_frame, text="S", width=2, bg="#333333", fg="white",
                             command=lambda i=track_index:self.toggle_solo(i))
        solo_btn.pack(side="left", padx=1)
        ToolTip(solo_btn,"Solo Track")

        pan_slider = tk.Scale(track_frame, from_=-1.0, to=1.0, resolution=0.01, orient="horizontal",
                              length=60, bg="#181818", fg="white", troughcolor="#2a2a2a",
                              highlightthickness=0, command=lambda val,i=track_index:self.set_pan(i,val))
        pan_slider.set(0)
        pan_slider.pack(pady=2)
        ToolTip(pan_slider,"Pan Left/Right")

        self.track_widgets.append(track_frame)

    # ===== AUDIO CONTROL =====
    def play(self):
        self.engine.play()
        self.is_playing = True
        self.start_time = time.time()
        self.update_playhead()

    def stop(self):
        self.engine.stop()
        self.is_playing = False
        self.playhead_x = 0
        self.canvas.coords(self.playhead,0,0,0,self.canvas.winfo_height())

    def update_playhead(self):
        if not self.is_playing:
            return
        elapsed = time.time() - self.start_time
        self.playhead_x = elapsed*120
        self.canvas.coords(self.playhead,self.playhead_x,0,self.playhead_x,self.canvas.winfo_height())
        self.root.after(16,self.update_playhead)

    # ===== VOLUME / MUTE / SOLO / PAN =====
    def set_volume(self, track_index, value):
        try: self.engine.tracks[track_index]["volume"]=float(value)
        except: pass

    def toggle_mute(self, track_index):
        self.engine.tracks[track_index]["mute"]=not self.engine.tracks[track_index]["mute"]

    def toggle_solo(self, track_index):
        self.engine.tracks[track_index]["solo"]=not self.engine.tracks[track_index]["solo"]

    def set_pan(self, track_index, value):
        try: self.engine.tracks[track_index]["pan"]=float(value)
        except: pass

    # ===== IMPORT / LOAD =====
    def import_audio(self):
        file_path = filedialog.askopenfilename(filetypes=[("Audio Files","*.wav *.mp3 *.flac")])
        if file_path: self.add_track(file_path)

    def load_samples(self):
        if not os.path.exists(SAMPLES_FOLDER): return
        for w in self.track_widgets: w.destroy()
        self.track_widgets.clear()
        self.canvas.delete("all")
        self.playhead = self.canvas.create_line(0,0,0,1000, fill="#ff3b3b", width=2)
        self.engine.clear_tracks()
        files=[f for f in os.listdir(SAMPLES_FOLDER) if f.endswith(".wav")]
        for f in files: self.add_track(os.path.join(SAMPLES_FOLDER,f), color="#2196F3")

    # ===== DRAG BLOCKS =====
    def on_block_click(self,event):
        items=self.canvas.find_withtag("current")
        if items:
            self.selected_block=items[0]
            coords=self.canvas.coords(self.selected_block)
            self.offset_x=event.x-coords[0]

    def on_block_drag(self,event):
        if self.selected_block:
            x=max(0,event.x-self.offset_x)
            coords=self.canvas.coords(self.selected_block)
            y1,y2=coords[1],coords[3]
            self.canvas.coords(self.selected_block,x,y1,x+160,y2)

    def on_block_release(self,event):
        self.selected_block=None

    def run(self):
        self.root.mainloop()
