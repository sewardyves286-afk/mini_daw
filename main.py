import ctypes
import tkinter as tk
from tkinter import messagebox
from gui import MiniDAWApp
import sys
import os
import subprocess


# --- Fonctions utilitaires ---
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def check_assets():
    required = ["assets/logo.png", "assets/logo.ico"]
    missing = [f for f in required if not os.path.exists(resource_path(f))]
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
    except Exception:
        print("FFmpeg non détecté")


# --- Fix Windows Taskbar Icon ---
myappid = "mini_daw.app.v1"
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)


# --- SplashScreen ---
class SplashScreen:
    def __init__(self, root, on_done):
        self.root = root
        self.on_done = on_done
        self.root.overrideredirect(True)
        self.root.configure(bg="#0f0f0f")

        w, h = 420, 320
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        self.canvas = tk.Canvas(root, width=w, height=h,
                                bg="#0f0f0f", highlightthickness=0)
        self.canvas.pack()

        logo_path = resource_path("assets/logo.png")
        self.logo = tk.PhotoImage(file=logo_path).subsample(4, 4)

        self.cx = w // 2
        self.cy = h // 2 - 20
        r = 90

        points = [
            self.cx - r * 0.5, self.cy - r,
            self.cx + r * 0.5, self.cy - r,
            self.cx + r,       self.cy,
            self.cx + r * 0.5, self.cy + r,
            self.cx - r * 0.5, self.cy + r,
            self.cx - r,       self.cy
        ]
        self.canvas.create_polygon(points, outline="#4CAF50", width=3, fill="")
        self.canvas.create_image(self.cx, self.cy, image=self.logo)
        self.canvas.create_text(
            self.cx, self.cy + 110,
            text="mini_daw",
            fill="white",
            font=("Segoe UI", 18, "bold")
        )

        self.progress = self.canvas.create_rectangle(
            self.cx - 100, self.cy + 140,
            self.cx - 100, self.cy + 150,
            fill="#4CAF50", outline=""
        )

        self.load_progress(0)

    def load_progress(self, value):
        if value <= 200:
            self.canvas.coords(
                self.progress,
                self.cx - 100,
                self.cy + 140,
                self.cx - 100 + value,
                self.cy + 150
            )
            self.root.after(25, lambda: self.load_progress(value + 4))
        else:
            self.root.destroy()
            self.on_done()


# --- Gestionnaire d'exceptions global ---
def _handle_exception(exc_type, exc_value, exc_tb):
    """Capture toutes les exceptions non gérées — évite la fermeture silencieuse."""
    import traceback
    try:
        err = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    except Exception:
        err = f"{exc_type.__name__}: {exc_value}"
    print(f"[mini_daw] ERREUR NON GÉRÉE:\n{err}")
    try:
        messagebox.showerror(
            "mini_daw — Erreur",
            f"Une erreur inattendue s'est produite :\n\n"
            f"{exc_type.__name__}: {exc_value}\n\n"
            f"L'application continue de fonctionner.\n"
            f"Consulte le terminal pour les détails.")
    except Exception:
        pass

sys.excepthook = _handle_exception


# --- MAIN ---
if __name__ == "__main__":
    check_assets()
    check_ffmpeg()

    def launch_main_app():
        root = tk.Tk()
        ico  = resource_path("assets/logo.ico")
        root.iconbitmap(ico)

        # Propager icone mini_daw a toutes les fenetres Toplevel
        _orig = tk.Toplevel.__init__
        def _patched(self_win, master=None, **kw):
            _orig(self_win, master, **kw)
            try:
                self_win.iconbitmap(ico)
            except Exception:
                pass
        tk.Toplevel.__init__ = _patched

        # Gestionnaire d'exceptions dans les callbacks tkinter
        def _tk_exception(exc, val, tb, *args):
            _handle_exception(type(exc), exc, tb)
        root.report_callback_exception = _tk_exception

        try:
            app = MiniDAWApp(root)
            root.mainloop()
        except Exception as e:
            import traceback
            print(f"[mini_daw] Crash fatal : {e}")
            traceback.print_exc()
            messagebox.showerror("mini_daw — Crash",
                f"Erreur fatale : {e}\nRelance l'application.")

    splash_root = tk.Tk()
    SplashScreen(splash_root, on_done=launch_main_app)
    splash_root.mainloop()
