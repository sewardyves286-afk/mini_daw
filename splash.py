import ctypes
import tkinter as tk
from gui import MiniDAWApp

# ===== FIX ICON TASKBAR WINDOWS =====
myappid = "mini_daw.app.v1"
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)


class SplashScreen:
    def __init__(self, root):
        self.root = root
        self.root.overrideredirect(True)
        self.root.configure(bg="#0f0f0f")

        # Centrer la fenêtre
        width = 400
        height = 400
        x = (root.winfo_screenwidth() // 2) - (width // 2)
        y = (root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        # Logo
        self.logo = tk.PhotoImage(file="assets/logo.png")
        label = tk.Label(root, image=self.logo, bg="#0f0f0f")
        label.pack(expand=True)


if __name__ == "__main__":
    # Splash
    splash_root = tk.Tk()
    splash = SplashScreen(splash_root)
    splash_root.after(3000, splash_root.destroy)
    splash_root.mainloop()

    # Lancement vrai Mini_DAW
    app = MiniDAWApp()
    app.run()