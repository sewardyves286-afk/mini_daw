import ctypes
import tkinter as tk
from tkinter import messagebox
from gui import MiniDAWApp
import sys
import os
import subprocess

def resource_path(relative_path):
    """Compatibilité PyInstaller et DEV"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def check_assets():
    required_files = ["assets/logo.png", "assets/logo.ico"]
    missing = [f for f in required_files if not os.path.exists(resource_path(f))]
    if missing:
        messagebox.showerror("Erreur", f"Fichiers manquants : {', '.join(missing)}")
        sys.exit(1)

def check_ffmpeg():
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except FileNotFoundError:
        messagebox.showwarning(
            "FFmpeg manquant",
            "FFmpeg n'est pas installé. Les fichiers mp3/flac ne pourront pas être lus."
        )

# --- Fix Windows Taskbar Icon ---
myappid = "mini_daw.app.v1"
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

class SplashScreen:
    def __init__(self, root):
        self.root = root
        self.root.overrideredirect(True)
        self.root.configure(bg="#0f0f0f")

        w, h = 420, 320
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        frame = tk.Frame(root, bg="#0f0f0f")
        frame.pack(expand=True, fill="both")

        # ✅ Utilisation PNG (PAS ICO)
        logo_path = resource_path("assets/logo.png")
        try:
            self.logo = tk.PhotoImage(file=logo_path)
            tk.Label(frame, image=self.logo, bg="#0f0f0f").pack(pady=30)
        except Exception as e:
            print("Erreur chargement logo:", e)

        tk.Label(
            frame,
            text="mini_daw",
            fg="white",
            bg="#0f0f0f",
            font=("Segoe UI", 18, "bold")
        ).pack()

        tk.Label(
            frame,
            text="Digital Audio Workstation",
            fg="#aaaaaa",
            bg="#0f0f0f",
            font=("Segoe UI", 9)
        ).pack(pady=5)

        self.progress = tk.Canvas(
            frame,
            width=200,
            height=6,
            bg="#1a1a1a",
            highlightthickness=0
        )
        self.progress.pack(pady=25)

        self.bar = self.progress.create_rectangle(
            0, 0, 0, 6,
            fill="#4CAF50",
            width=0
        )

        self.load_progress(0)

    def load_progress(self, value):
        if value <= 200:
            self.progress.coords(self.bar, 0, 0, value, 6)
            self.root.after(15, lambda: self.load_progress(value + 4))
        else:
            self.root.destroy()
            MiniDAWApp().run()

if __name__ == "__main__":
    splash_root = tk.Tk()
    check_assets()
    check_ffmpeg()
    SplashScreen(splash_root)
    splash_root.mainloop()