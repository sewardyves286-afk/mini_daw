"""
create_association.py v6
- Associe .mdaw a mini_daw.exe
- Corrige l icone (pointe sur .ico, pas sur l exe)
- Purge le cache icones Windows (IconCache.db)
- Pas de taskkill explorer
"""
import sys
import os
import subprocess
import time
import ctypes

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
EXE_PATH  = os.path.join(BASE_DIR, "mini_daw.exe")
ICON_PATH = os.path.join(BASE_DIR, "assets", "logo.ico")

# ── Verification ─────────────────────────────────────────────────
if not os.path.exists(EXE_PATH):
    print("ERREUR : mini_daw.exe introuvable !")
    print("Lance d abord : build_exe.bat")
    print(f"Cherche dans : {EXE_PATH}")
    input("Entree pour fermer...")
    sys.exit(1)

if not os.path.exists(ICON_PATH):
    print(f"AVERTISSEMENT : logo.ico introuvable dans assets/")
    print(f"Cherche dans : {ICON_PATH}")
    # On continue avec l exe comme fallback icone
    ICON_SOURCE = f"{EXE_PATH},0"
else:
    # Pointer directement sur le .ico = icone stable meme apres rebuild exe
    ICON_SOURCE = ICON_PATH

OPEN_CMD = f'"{EXE_PATH}" "%1"'

print(f"EXE  : {EXE_PATH}")
print(f"ICON : {ICON_SOURCE}")
print(f"CMD  : {OPEN_CMD}")
print()

# ── Helpers ──────────────────────────────────────────────────────
def reg_set(key: str, value: str, kind: str = "REG_SZ") -> bool:
    """Ecrit la valeur par defaut d une cle registre."""
    r = subprocess.run(
        ["reg", "add", key, "/ve", "/t", kind, "/d", value, "/f"],
        capture_output=True, text=True
    )
    return r.returncode == 0

def reg_set_named(key: str, name: str, value: str, kind: str = "REG_SZ") -> bool:
    """Ecrit une valeur nommee dans une cle registre."""
    r = subprocess.run(
        ["reg", "add", key, "/v", name, "/t", kind, "/d", value, "/f"],
        capture_output=True, text=True
    )
    return r.returncode == 0

def reg_del(key: str) -> bool:
    r = subprocess.run(["reg", "delete", key, "/f"], capture_output=True)
    return r.returncode == 0

# ── 1. Purger UserChoice (Windows 10/11) ─────────────────────────
print("[1/5] Suppression des UserChoice...")
for ext in [".mdaw", ".wav", ".mp3", ".flac", ".ogg"]:
    base = (f"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion"
            f"\\Explorer\\FileExts\\{ext}")
    reg_del(f"{base}\\UserChoice")
    reg_del(f"{base}\\OpenWithList")

# ── 2. Enregistrer le ProgID miniDAW.Project ─────────────────────
print("[2/5] Enregistrement miniDAW.Project...")

prog = "HKCU\\Software\\Classes\\miniDAW.Project"
reg_set(prog,                                    "mini_daw Project")
reg_set(f"{prog}\\DefaultIcon",                  ICON_SOURCE)
reg_set(f"{prog}\\shell",                        "open")
reg_set(f"{prog}\\shell\\open",                  "Ouvrir avec mini_daw")
reg_set_named(f"{prog}\\shell\\open", "Icon",    EXE_PATH)
reg_set(f"{prog}\\shell\\open\\command",         OPEN_CMD)

# ── 3. Associer .mdaw → miniDAW.Project ──────────────────────────
print("[3/5] Association .mdaw...")
reg_set("HKCU\\Software\\Classes\\.mdaw",        "miniDAW.Project")
# Perceived type pour que Windows sache que c est un type connu
reg_set_named("HKCU\\Software\\Classes\\.mdaw",  "PerceivedType", "document")
reg_set_named("HKCU\\Software\\Classes\\.mdaw",  "Content Type",  "application/x-minidaw")

# ── 4. Enregistrer miniDAW.AudioFile pour "Ouvrir avec" ──────────
print("[4/5] Association fichiers audio...")
audio = "HKCU\\Software\\Classes\\miniDAW.AudioFile"
reg_set(audio,                                   "mini_daw Audio")
reg_set(f"{audio}\\DefaultIcon",                 ICON_SOURCE)
reg_set(f"{audio}\\shell\\open\\command",        OPEN_CMD)

for ext in [".wav", ".mp3", ".flac", ".ogg"]:
    reg_set_named(
        f"HKCU\\Software\\Classes\\{ext}\\OpenWithProgids",
        "miniDAW.AudioFile", "", "REG_NONE"
    )

# ── 5. Purger le cache d icones Windows ──────────────────────────
print("[5/5] Purge du cache icones...")

# Chemin du cache icones (varie selon la version Windows)
local_app = os.environ.get("LOCALAPPDATA", "")
icon_cache_paths = [
    os.path.join(local_app, "IconCache.db"),
    os.path.join(local_app, "Microsoft", "Windows", "Explorer", "iconcache_idx.db"),
    os.path.join(local_app, "Microsoft", "Windows", "Explorer", "iconcache_32.db"),
    os.path.join(local_app, "Microsoft", "Windows", "Explorer", "iconcache_48.db"),
    os.path.join(local_app, "Microsoft", "Windows", "Explorer", "iconcache_96.db"),
    os.path.join(local_app, "Microsoft", "Windows", "Explorer", "iconcache_256.db"),
    os.path.join(local_app, "Microsoft", "Windows", "Explorer", "iconcache_1024.db"),
    os.path.join(local_app, "Microsoft", "Windows", "Explorer", "iconcache_sr.db"),
    os.path.join(local_app, "Microsoft", "Windows", "Explorer", "iconcache_wide.db"),
    os.path.join(local_app, "Microsoft", "Windows", "Explorer", "iconcache_exif.db"),
]

# Stopper explorer proprement, purger, redemarrer
print("      Arret temporaire de l Explorateur...")
subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], capture_output=True)
time.sleep(1.5)

purged = 0
for path in icon_cache_paths:
    if os.path.exists(path):
        try:
            os.remove(path)
            purged += 1
        except Exception as e:
            print(f"      Impossible de supprimer {os.path.basename(path)}: {e}")

print(f"      {purged} fichier(s) cache purge(s)")

# Redemarrer explorer
subprocess.Popen(["explorer.exe"])
time.sleep(1)

# Notifier le shell (double securite)
try:
    shell32 = ctypes.windll.shell32
    shell32.SHChangeNotify(0x08000000, 0x0000, None, None)  # SHCNE_ASSOCCHANGED
    print("      SHChangeNotify OK")
except Exception:
    pass

print()
print("=" * 55)
print("  TERMINE !")
print()
print("  L icone devrait maintenant etre correcte.")
print("  Si l icone est encore ancienne : clic droit sur")
print("  le bureau > Actualiser, puis rouvre l Explorateur.")
print()
print("  Double-clique sur un .mdaw pour tester.")
print("=" * 55)
input("Entree pour fermer...")
