"""
web_importer.py — Import audio depuis URL directe
"""

import os
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk
from urllib.parse import urlparse

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

try:
    import soundfile as sf
    SF_OK = True
except ImportError:
    SF_OK = False

SAMPLES_DIR    = os.path.join(os.path.dirname(__file__), "samples")
os.makedirs(SAMPLES_DIR, exist_ok=True)
SUPPORTED_EXTS = (".wav", ".mp3", ".flac", ".ogg")

SITES = [
    ("Freesound.org",   "https://freesound.org/search/"),
    ("Looperman",       "https://www.looperman.com/loops"),
    ("Sampleswap",      "https://sampleswap.org/"),
    ("Zapsplat",        "https://www.zapsplat.com/"),
]


class WebImporterWindow:
    def __init__(self, parent, on_imported=None):
        self.parent      = parent
        self.on_imported = on_imported
        self._cancel     = False

        self.win = tk.Toplevel(parent)
        self.win.title("mini_daw — Import Web")
        self.win.configure(bg="#0f0f0f")
        self.win.resizable(True, True)

        # Centrer + grande taille fixe
        w, h = 520, 480
        sw   = self.win.winfo_screenwidth()
        sh   = self.win.winfo_screenheight()
        self.win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self.win.minsize(520, 480)

        # Icône
        try:
            ico = os.path.join(os.path.dirname(__file__), "assets", "logo.ico")
            if os.path.exists(ico):
                self.win.iconbitmap(ico)
        except Exception:
            pass

        self.win.grab_set()
        self._build_ui()

    # ====================================================
    def _build_ui(self):

        # --- En-tête ---
        header = tk.Frame(self.win, bg="#0a0a0a")
        header.pack(fill="x")

        try:
            logo_path = os.path.join(
                os.path.dirname(__file__), "assets", "logo.png")
            if os.path.exists(logo_path):
                self._logo = tk.PhotoImage(file=logo_path).subsample(8, 8)
                tk.Label(header, image=self._logo,
                         bg="#0a0a0a").pack(side="left", padx=(12, 6), pady=8)
        except Exception:
            pass

        htext = tk.Frame(header, bg="#0a0a0a")
        htext.pack(side="left", pady=8)
        tk.Label(htext, text="mini_daw",
                 bg="#0a0a0a", fg="#4CAF50",
                 font=("Segoe UI", 12, "bold")).pack(anchor="w")
        tk.Label(htext, text="Import depuis le web",
                 bg="#0a0a0a", fg="#00b4d8",
                 font=("Segoe UI", 9)).pack(anchor="w")

        tk.Frame(self.win, bg="#222222", height=1).pack(fill="x")

        # --- Corps scrollable ---
        body = tk.Frame(self.win, bg="#0f0f0f")
        body.pack(fill="both", expand=True, padx=16, pady=10)

        # Boutons sites web
        tk.Label(body, text="1. Ouvre un site pour trouver un son :",
                 bg="#0f0f0f", fg="#cccccc",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 4))

        sites_frame = tk.Frame(body, bg="#0f0f0f")
        sites_frame.pack(fill="x", pady=(0, 8))

        for name, url in SITES:
            tk.Button(
                sites_frame,
                text=f"🌐  {name}",
                font=("Segoe UI", 9),
                bg="#0d3b4f", fg="#00b4d8",
                activebackground="#00b4d8", activeforeground="white",
                relief="flat", padx=10, pady=4,
                cursor="hand2",
                command=lambda u=url: webbrowser.open(u)
            ).pack(side="left", padx=(0, 6))

        tk.Frame(body, bg="#222222", height=1).pack(fill="x", pady=6)

        # URL
        tk.Label(body,
                 text="2. Copie le lien direct du fichier audio et colle-le ici :",
                 bg="#0f0f0f", fg="#cccccc",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(4, 2))

        tk.Label(body,
                 text="Le lien doit finir par  .wav  .mp3  .flac  ou  .ogg",
                 bg="#0f0f0f", fg="#555555",
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 4))

        url_row = tk.Frame(body, bg="#0f0f0f")
        url_row.pack(fill="x")

        self.url_var = tk.StringVar()
        self.url_entry = tk.Entry(
            url_row, textvariable=self.url_var,
            bg="#1e1e1e", fg="white", insertbackground="white",
            relief="flat", font=("Segoe UI", 9))
        self.url_entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.url_entry.bind("<Return>", lambda e: self._start_download())

        tk.Button(url_row, text="✕",
                  bg="#2a2a2a", fg="#888888",
                  relief="flat", font=("Segoe UI", 9),
                  cursor="hand2",
                  command=lambda: self.url_var.set("")
                  ).pack(side="left", padx=(4, 0), ipady=6, ipadx=4)

        # Nom fichier
        tk.Label(body, text="Nom du fichier (optionnel) :",
                 bg="#0f0f0f", fg="#cccccc",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(10, 2))

        self.name_var = tk.StringVar()
        tk.Entry(body, textvariable=self.name_var,
                 bg="#1e1e1e", fg="white", insertbackground="white",
                 relief="flat", font=("Segoe UI", 9),
                 width=28).pack(anchor="w", ipady=5)

        # Progression
        self.progress_var = tk.IntVar(value=0)
        ttk.Progressbar(body, variable=self.progress_var,
                        maximum=100).pack(fill="x", pady=10)

        # Statut
        self.status_label = tk.Label(
            body,
            text="Prêt — colle une URL puis clique Télécharger",
            bg="#0f0f0f", fg="#4CAF50",
            font=("Segoe UI", 8))
        self.status_label.pack(anchor="w")

        # --- Boutons d'action ---
        tk.Frame(self.win, bg="#222222", height=1).pack(fill="x")

        btn_bar = tk.Frame(self.win, bg="#0a0a0a", pady=12)
        btn_bar.pack(fill="x", padx=16)

        self.btn_dl = tk.Button(
            btn_bar,
            text="⬇   Télécharger",
            font=("Segoe UI", 11, "bold"),
            bg="#00b4d8", fg="white",
            activebackground="#0077b6", activeforeground="white",
            relief="flat", padx=22, pady=10,
            cursor="hand2",
            command=self._start_download)
        self.btn_dl.pack(side="left", padx=(0, 10))

        tk.Button(
            btn_bar,
            text="✕   Fermer",
            font=("Segoe UI", 10),
            bg="#2a2a2a", fg="white",
            activebackground="#444", activeforeground="white",
            relief="flat", padx=16, pady=10,
            cursor="hand2",
            command=self._close).pack(side="left")

    # ====================================================
    def _validate_url(self, url):
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return False, "L'URL doit commencer par http:// ou https://"
            if not any(parsed.path.lower().endswith(e) for e in SUPPORTED_EXTS):
                return False, "Le lien doit pointer vers un fichier .wav .mp3 .flac .ogg"
            return True, ""
        except Exception as e:
            return False, str(e)

    def _get_filename(self, url):
        name = os.path.basename(urlparse(url).path)
        for ch in '<>:"/\\|?*':
            name = name.replace(ch, '_')
        return name or "sample.wav"

    def _start_download(self):
        if not REQUESTS_OK:
            self._set_status("✗ pip install requests", "#f44336")
            return
        url = self.url_var.get().strip()
        if not url:
            self._set_status("⚠ Colle une URL d'abord", "#FFC107")
            return
        ok, msg = self._validate_url(url)
        if not ok:
            self._set_status(f"✗ {msg}", "#f44336")
            return

        custom = self.name_var.get().strip()
        ext    = os.path.splitext(self._get_filename(url))[1]
        fname  = (custom + ext) if custom else self._get_filename(url)
        outpath = os.path.join(SAMPLES_DIR, fname)

        if os.path.exists(outpath):
            import time as _t
            b, e   = os.path.splitext(fname)
            fname  = f"{b}_{int(_t.time())}{e}"
            outpath = os.path.join(SAMPLES_DIR, fname)

        self._cancel = False
        self.btn_dl.config(state="disabled", text="Téléchargement...")
        self.progress_var.set(0)
        self._set_status(f"Connexion...", "#FFC107")

        threading.Thread(
            target=self._dl_thread, args=(url, outpath), daemon=True).start()

    def _dl_thread(self, url, outpath):
        try:
            r = requests.get(url, stream=True, timeout=30,
                             headers={"User-Agent": "MiniDAW/1.0"})
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            done  = 0
            with open(outpath, "wb") as f:
                for chunk in r.iter_content(8192):
                    if self._cancel:
                        break
                    if chunk:
                        f.write(chunk)
                        done += len(chunk)
                        if total:
                            self.win.after(0, lambda p=int(done/total*100):
                                           self.progress_var.set(p))
                        self.win.after(0, lambda k=done//1024:
                                       self._set_status(
                                           f"Téléchargement... {k} KB",
                                           "#FFC107"))
            if self._cancel:
                if os.path.exists(outpath):
                    os.remove(outpath)
                self.win.after(0, self._on_cancel)
                return
            self.win.after(0, lambda: self._on_success(outpath))
        except Exception as e:
            self.win.after(0, lambda: self._set_status(f"✗ {e}", "#f44336"))
            self.win.after(0, lambda: self.btn_dl.config(
                state="normal", text="⬇   Télécharger"))

    def _on_success(self, fp):
        self.progress_var.set(100)
        self._set_status(f"✔ Téléchargé : {os.path.basename(fp)}", "#4CAF50")
        self.btn_dl.config(state="normal", text="⬇   Télécharger")
        dur = 4.0
        try:
            if SF_OK:
                dur = sf.info(fp).duration
        except Exception:
            pass
        if self.on_imported:
            self.on_imported(fp, dur)

    def _on_cancel(self):
        self._set_status("Annulé", "#888888")
        self.btn_dl.config(state="normal", text="⬇   Télécharger")
        self.progress_var.set(0)

    def _set_status(self, msg, color="#4CAF50"):
        self.status_label.config(text=msg, fg=color)

    def _close(self):
        self._cancel = True
        self.win.destroy()
