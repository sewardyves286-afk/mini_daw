"""
main.py -- Point d entree mini_daw
Gere :
  - Lancement normal (double-clic sur mini_daw.exe)
  - Lancement avec argument (double-clic sur un .mdaw ou fichier audio)
"""
import sys
import os
import tkinter as tk

# ── Resolution BASE_DIR ───────────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ── AppUserModelID ────────────────────────────────────────────────
# DOIT etre fait AVANT la creation de toute fenetre tkinter.
# Sans ca, Windows associe la fenetre a python.exe dans la barre
# des taches et affiche l icone de Python au lieu de mini_daw.
try:
    import ctypes
    # Identifiant unique de l application (arbitraire mais stable)
    APP_ID = "MiniDAW.MiniDAW.1.0"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
except Exception:
    pass  # Non-Windows ou erreur : on continue sans crash

from gui import MiniDAWApp


def main():
    root = tk.Tk()
    app  = MiniDAWApp(root)

    # ── Argument ligne de commande (double-clic Explorateur Windows) ──
    if len(sys.argv) >= 2:
        file_arg = sys.argv[1].strip('"')

        if os.path.isfile(file_arg):
            ext = os.path.splitext(file_arg)[1].lower()

            AUDIO_EXTS = {
                ".wav", ".mp3", ".flac", ".ogg",
                ".aiff", ".aif", ".m4a", ".wma", ".aac", ".opus"
            }

            if ext == ".mdaw":
                root.after(300, lambda: app._load_project_from_mdaw(file_arg))
            elif ext in AUDIO_EXTS:
                root.after(300, lambda: app._import_from_path(file_arg))
            else:
                print(f"[main] Type de fichier non reconnu : {ext}")
        else:
            print(f"[main] Fichier introuvable : {file_arg}")

    root.mainloop()


if __name__ == "__main__":
    main()
