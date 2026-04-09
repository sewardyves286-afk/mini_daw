"""
project_manager.py v4 — Gestion de projets mini_daw

Structure d un projet :
    projects/
        nom_projet/
            nom_projet.mdaw     <- JSON avec chemins RELATIFS depuis nom_projet/
            audio/              <- tous les fichiers audio du projet
"""

import os
import json
import shutil
import time
import threading
import zipfile

try:
    import numpy as np
    import soundfile as sf
    AUDIO_OK = True
except ImportError:
    AUDIO_OK = False

try:
    from pydub import AudioSegment
    PYDUB_OK = True
except ImportError:
    PYDUB_OK = False

import sys as _sys
if getattr(_sys, 'frozen', False):
    BASE_DIR = os.path.dirname(_sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROJECTS_DIR  = os.path.join(BASE_DIR, "projects")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
SAMPLE_RATE   = 44100

for d in [PROJECTS_DIR, TEMPLATES_DIR]:
    os.makedirs(d, exist_ok=True)

# ============================================================
# TEMPLATES
# ============================================================
BUILTIN_TEMPLATES = {
    "Minimal":  {"bpm": 130, "tracks": 4, "description": "4 pistes, 130 BPM"},
    "Trap":     {"bpm": 140, "tracks": 8, "description": "8 pistes, 140 BPM"},
    "Lofi":     {"bpm": 85,  "tracks": 6, "description": "6 pistes, 85 BPM"},
    "Podcast":  {"bpm": 120, "tracks": 3, "description": "3 pistes — voix/musique/effets"},
    "Blank":    {"bpm": 120, "tracks": 5, "description": "Projet vide"},
}

# ============================================================
# UTILITAIRES INTERNES
# ============================================================
def _safe_name(name: str) -> str:
    safe = "".join(
        c for c in name
        if c.isalnum() or c in " _-àâäéèêëîïôùûüçÀÂÄÉÈÊËÎÏÔÙÛÜÇ"
    ).strip()
    return safe[:60] or "projet"

def _proj_dir(name: str) -> str:
    return os.path.join(PROJECTS_DIR, _safe_name(name))

def _mdaw_path(proj_dir: str) -> str:
    name = os.path.basename(proj_dir)
    return os.path.join(proj_dir, f"{name}.mdaw")

def _resolve_filepath(fp: str, proj_dir: str) -> str:
    """
    Résout un chemin de fichier audio en chemin ABSOLU.
    Gère les chemins relatifs (depuis proj_dir) et absolus.
    Retourne le chemin absolu si le fichier existe, sinon fp tel quel.
    """
    if not fp:
        return fp

    # Déjà absolu et existant
    if os.path.isabs(fp) and os.path.exists(fp):
        return fp

    # Relatif → essayer depuis proj_dir
    # Gère "audio\fichier.wav", "fichier.wav", "audio/fichier.wav"
    # En extrayant juste le nom de base pour éviter le double "audio/"
    basename = os.path.basename(fp)

    candidates = [
        # 1. Chemin tel quel depuis proj_dir
        os.path.normpath(os.path.join(proj_dir, fp)),
        # 2. Juste le nom dans audio/
        os.path.join(proj_dir, "audio", basename),
        # 3. Juste le nom dans proj_dir
        os.path.join(proj_dir, basename),
    ]

    for c in candidates:
        if os.path.exists(c):
            return c

    # Recherche élargie dans tous les projets
    for entry in os.listdir(PROJECTS_DIR):
        candidate = os.path.join(PROJECTS_DIR, entry, "audio", basename)
        if os.path.exists(candidate):
            print(f"[PM] Trouvé dans autre projet : {candidate}")
            return candidate

    # Recherche récursive dans BASE_DIR (max 4 niveaux)
    for root_dir, dirs, files in os.walk(BASE_DIR):
        depth = root_dir.replace(BASE_DIR, "").count(os.sep)
        if depth > 4:
            dirs.clear()
            continue
        if basename in files:
            found = os.path.join(root_dir, basename)
            print(f"[PM] Trouvé par recherche : {found}")
            return found

    # Introuvable — retourner le chemin absolu reconstruit pour le message d'erreur
    return os.path.normpath(os.path.join(proj_dir, fp))


def _make_relative(fp_abs: str, proj_dir: str) -> str:
    """
    Transforme un chemin absolu en chemin relatif depuis proj_dir.
    Ex: proj_dir/audio/fichier.wav  →  audio/fichier.wav
    """
    try:
        return os.path.relpath(fp_abs, proj_dir)
    except ValueError:
        # Lecteurs différents sur Windows
        return fp_abs

def _serialize_clips(clips: dict, proj_dir: str,
                     copy_audio: bool = True) -> list:
    """
    Sérialise self.clips pour le .mdaw.
    Règle unique : TOUS les fichiers audio sont copiés dans proj_dir/audio/.
    Le .mdaw stocke uniquement des chemins relatifs depuis proj_dir.
    """
    clips_data = []

    for clip in clips.values():
        fp_raw = clip.get("filepath", "")

        if fp_raw:
            fp_abs = _resolve_filepath(fp_raw, proj_dir)
            if os.path.exists(fp_abs):
                rel = fp_abs   # chemin absolu, rien copié
            else:
                print(f"[PM] ⚠ Introuvable : {os.path.basename(fp_raw)}")
                rel = fp_raw
        else:
            rel = ""

        clips_data.append({
            "track":    clip.get("track",    0),
            "start":    clip.get("start",    0.0),
            "duration": clip.get("duration", 4.0),
            "label":    clip.get("label",    "Clip"),
            "filepath": rel,
            "volume":   clip.get("volume",   80),
            "pan":      clip.get("pan",      0),
            "color":    clip.get("color",    "#00b4d8"),
        })

    return clips_data

# ============================================================
# NEW PROJECT
# ============================================================
def new_project(name: str, template: str = "Blank") -> dict:
    proj_dir = _proj_dir(name)
    os.makedirs(proj_dir, exist_ok=True)
    # audio/ créé seulement au premier save avec des fichiers

    tmpl = BUILTIN_TEMPLATES.get(template, BUILTIN_TEMPLATES["Blank"])
    bpm  = tmpl["bpm"]

    data = {
        "version":    "3.0",
        "name":       name,
        "template":   template,
        "bpm":        bpm,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "saved_at":   time.strftime("%Y-%m-%d %H:%M:%S"),
        "clips":      [],
    }
    mdaw = _mdaw_path(proj_dir)
    with open(mdaw, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"[PM] Nouveau projet : {proj_dir}")
    return {"project_dir": proj_dir, "mdaw_path": mdaw,
            "bpm": bpm, "tracks": tmpl["tracks"]}

# ============================================================
# SAVE
# ============================================================
def save_project(mdaw_path: str, clips: dict,
                 bpm: int, name: str = "") -> bool:
    proj_dir = os.path.dirname(mdaw_path)

    clips_data = _serialize_clips(clips, proj_dir, copy_audio=True)

    existing = {}
    if os.path.exists(mdaw_path):
        try:
            with open(mdaw_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    data = {
        "version":    "3.0",
        "name":       name or existing.get("name", os.path.basename(proj_dir)),
        "template":   existing.get("template", "Blank"),
        "bpm":        bpm,
        "created_at": existing.get("created_at", time.strftime("%Y-%m-%d %H:%M:%S")),
        "saved_at":   time.strftime("%Y-%m-%d %H:%M:%S"),
        "clips":      clips_data,
    }

    try:
        with open(mdaw_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[PM] ✔ Sauvegardé : {mdaw_path}")
        return True
    except Exception as e:
        print(f"[PM] ✗ Erreur sauvegarde : {e}")
        return False

# ============================================================
# SAVE AS
# ============================================================
def save_project_as(new_name: str, clips: dict,
                    bpm: int, src_mdaw: str = "") -> dict:
    proj_dir = _proj_dir(new_name)
    os.makedirs(proj_dir, exist_ok=True)

    # Résoudre les chemins relatifs depuis l'ancien projet si applicable
    src_proj_dir = os.path.dirname(src_mdaw) if src_mdaw else ""
    if src_proj_dir:
        # Pré-résoudre tous les chemins relatifs depuis l'ancien projet
        for clip in clips.values():
            fp = clip.get("filepath", "")
            if fp and not os.path.isabs(fp):
                resolved = _resolve_filepath(fp, src_proj_dir)
                if os.path.exists(resolved):
                    clip["filepath"] = resolved

    clips_data = _serialize_clips(clips, proj_dir, copy_audio=True)

    mdaw = _mdaw_path(proj_dir)
    data = {
        "version":    "3.0",
        "name":       new_name,
        "template":   "Blank",
        "bpm":        bpm,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "saved_at":   time.strftime("%Y-%m-%d %H:%M:%S"),
        "clips":      clips_data,
    }

    with open(mdaw, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"[PM] ✔ Save As : {mdaw}")
    return {"project_dir": proj_dir, "mdaw_path": mdaw}

# ============================================================
# SAVE AS TEMPLATE
# ============================================================
def save_as_template(template_name: str, clips: dict,
                     bpm: int, description: str = "") -> bool:
    tmpl_dir  = os.path.join(TEMPLATES_DIR, _safe_name(template_name))
    os.makedirs(tmpl_dir, exist_ok=True)

    clips_data = []
    for clip in clips.values():
        clips_data.append({
            "track":    clip.get("track",    0),
            "start":    clip.get("start",    0.0),
            "duration": clip.get("duration", 4.0),
            "label":    clip.get("label",    "Clip"),
            "filepath": "",
            "volume":   clip.get("volume",   80),
            "pan":      clip.get("pan",      0),
            "color":    clip.get("color",    "#00b4d8"),
        })

    data = {
        "version":     "3.0",
        "name":        template_name,
        "description": description or f"Template {template_name}",
        "bpm":         bpm,
        "is_template": True,
        "created_at":  time.strftime("%Y-%m-%d %H:%M:%S"),
        "clips":       clips_data,
    }
    tmpl_file = os.path.join(tmpl_dir, f"{_safe_name(template_name)}.mdaw")
    try:
        with open(tmpl_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[PM] ✔ Template : {tmpl_file}")
        return True
    except Exception as e:
        print(f"[PM] ✗ Erreur template : {e}")
        return False

# ============================================================
# LOAD PROJECT
# ============================================================
def load_project(mdaw_path: str):
    """
    Charge un projet .mdaw.
    Retourne (bpm, clips_list, missing_list, meta) ou None.
    """
    try:
        with open(mdaw_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[PM] ✗ Lecture : {e}")
        return None

    bpm      = data.get("bpm", 120)
    proj_dir = os.path.dirname(os.path.abspath(mdaw_path))
    meta     = {
        "name":       data.get("name", os.path.basename(proj_dir)),
        "template":   data.get("template", ""),
        "created_at": data.get("created_at", ""),
        "saved_at":   data.get("saved_at", ""),
        "version":    data.get("version", "1.0"),
    }

    clips_list   = []
    missing_list = []

    for c in data.get("clips", []):
        fp_raw = c.get("filepath", "")
        fp_abs = _resolve_filepath(fp_raw, proj_dir)

        c_out = dict(c)
        if fp_raw and not os.path.exists(fp_abs):
            c_out["filepath"] = fp_abs
            c_out["missing"]  = True
            missing_list.append(fp_abs)
            print(f"[PM] Manquant : {os.path.basename(fp_abs)}")
        else:
            c_out["filepath"] = fp_abs
            c_out["missing"]  = False

        clips_list.append(c_out)

    print(f"[PM] ✔ {meta['name']} — "
          f"{len(clips_list)} clips, {len(missing_list)} manquants")
    return bpm, clips_list, missing_list, meta

# ============================================================
# LIST PROJECTS / TEMPLATES
# ============================================================
def list_projects() -> list:
    projects = []
    if not os.path.isdir(PROJECTS_DIR):
        return projects
    for entry in sorted(os.listdir(PROJECTS_DIR)):
        proj_dir = os.path.join(PROJECTS_DIR, entry)
        if not os.path.isdir(proj_dir):
            continue
        if entry.startswith("_") or entry == ".gitkeep":
            continue
        mdaw = _mdaw_path(proj_dir)
        if not os.path.exists(mdaw):
            for f in os.listdir(proj_dir):
                if f.endswith(".mdaw"):
                    mdaw = os.path.join(proj_dir, f)
                    break
            else:
                continue
        info = {"name": entry, "path": proj_dir,
                "mdaw": mdaw, "saved_at": "", "bpm": 120}
        try:
            with open(mdaw, "r", encoding="utf-8") as f:
                d = json.load(f)
            info["saved_at"] = d.get("saved_at", "")
            info["bpm"]      = d.get("bpm", 120)
            info["name"]     = d.get("name", entry)
        except Exception:
            pass
        projects.append(info)
    return projects

def list_templates() -> list:
    templates = []
    for name, tmpl in BUILTIN_TEMPLATES.items():
        templates.append({
            "name": name, "description": tmpl["description"],
            "bpm": tmpl["bpm"], "builtin": True, "path": None,
        })
    if os.path.isdir(TEMPLATES_DIR):
        for entry in sorted(os.listdir(TEMPLATES_DIR)):
            tmpl_dir = os.path.join(TEMPLATES_DIR, entry)
            if not os.path.isdir(tmpl_dir):
                continue
            for f in os.listdir(tmpl_dir):
                if f.endswith(".mdaw"):
                    mdaw = os.path.join(tmpl_dir, f)
                    info = {"name": entry,
                            "description": "Template personnalisé",
                            "bpm": 120, "builtin": False, "path": mdaw}
                    try:
                        with open(mdaw, "r", encoding="utf-8") as ff:
                            d = json.load(ff)
                        info["description"] = d.get("description", info["description"])
                        info["bpm"]         = d.get("bpm", 120)
                        info["name"]        = d.get("name", entry)
                    except Exception:
                        pass
                    templates.append(info)
                    break
    return templates


# ============================================================
# EXPORT WAV / MP3 / OGG / STEMS / ZIP
# ============================================================
def _mix_clips(clips: dict, sample_rate=SAMPLE_RATE):
    if not AUDIO_OK:
        return None
    total_dur = 0.0
    cache = {}
    for clip in clips.values():
        fp = clip.get("filepath")
        if not fp or not os.path.exists(fp):
            continue
        end = clip.get("start", 0) + clip.get("duration", 0)
        total_dur = max(total_dur, end)
    if total_dur <= 0:
        return None
    total_smp = int(total_dur * sample_rate) + sample_rate
    mix       = np.zeros((total_smp, 2), dtype="float32")
    for clip in clips.values():
        fp = clip.get("filepath")
        if not fp or not os.path.exists(fp):
            continue
        if fp not in cache:
            try:
                data, sr = sf.read(fp, dtype="float32")
                if data.ndim == 2:
                    data = data.mean(axis=1)
                cache[fp] = data
            except Exception:
                continue
        data  = cache[fp]
        start = int(clip.get("start", 0) * sample_rate)
        vol   = clip.get("volume", 80) / 100.0
        pan   = clip.get("pan", 0) / 50.0
        n     = min(len(data), total_smp - start)
        if n <= 0:
            continue
        chunk = data[:n] * vol
        L = np.sqrt(max(0.0, 0.5 * (1.0 - pan))) * chunk
        R = np.sqrt(max(0.0, 0.5 * (1.0 + pan))) * chunk
        mix[start:start+n, 0] += L
        mix[start:start+n, 1] += R
    return np.clip(mix, -1.0, 1.0)

def export_wav(clips, out_path, on_progress=None, on_done=None):
    def _run():
        try:
            if on_progress: on_progress(10)
            mix = _mix_clips(clips)
            if mix is None:
                if on_done: on_done(None)
                return
            if on_progress: on_progress(80)
            sf.write(out_path, mix, SAMPLE_RATE)
            if on_progress: on_progress(100)
            if on_done: on_done(out_path)
        except Exception as e:
            print(f"[PM] ✗ WAV : {e}")
            if on_done: on_done(None)
    threading.Thread(target=_run, daemon=True).start()

def export_mp3(clips, out_path, bitrate="192k", on_progress=None, on_done=None):
    def _run():
        try:
            if not PYDUB_OK:
                if on_done: on_done(None)
                return
            if on_progress: on_progress(10)
            mix = _mix_clips(clips)
            if mix is None:
                if on_done: on_done(None)
                return
            if on_progress: on_progress(60)
            tmp = out_path.replace(".mp3", "_tmp.wav")
            sf.write(tmp, mix, SAMPLE_RATE)
            AudioSegment.from_wav(tmp).export(out_path, format="mp3", bitrate=bitrate)
            os.remove(tmp)
            if on_progress: on_progress(100)
            if on_done: on_done(out_path)
        except Exception as e:
            print(f"[PM] ✗ MP3 : {e}")
            if on_done: on_done(None)
    threading.Thread(target=_run, daemon=True).start()

def export_ogg(clips, out_path, quality=5, on_progress=None, on_done=None):
    def _run():
        try:
            if on_progress: on_progress(10)
            mix = _mix_clips(clips)
            if mix is None:
                if on_done: on_done(None)
                return
            if on_progress: on_progress(70)
            sf.write(out_path, mix, SAMPLE_RATE, format="OGG", subtype="VORBIS")
            if on_progress: on_progress(100)
            if on_done: on_done(out_path)
        except Exception as e:
            print(f"[PM] ✗ OGG : {e}")
            if on_done: on_done(None)
    threading.Thread(target=_run, daemon=True).start()

def export_stems(clips, out_dir, on_progress=None, on_done=None):
    def _run():
        try:
            os.makedirs(out_dir, exist_ok=True)
            tracks = {}
            for clip in clips.values():
                t = clip.get("track", 0)
                tracks.setdefault(t, []).append(clip)
            total = len(tracks)
            files = []
            for i, (idx, track_clips) in enumerate(sorted(tracks.items())):
                mix = _mix_clips({j: c for j, c in enumerate(track_clips)})
                if mix is None:
                    continue
                path = os.path.join(out_dir, f"stem_track{idx+1:02d}.wav")
                sf.write(path, mix, SAMPLE_RATE)
                files.append(path)
                if on_progress: on_progress(int((i+1) / total * 100))
            if on_done: on_done(files)
        except Exception as e:
            print(f"[PM] ✗ Stems : {e}")
            if on_done: on_done(None)
    threading.Thread(target=_run, daemon=True).start()

def export_zip(project_dir, out_path, on_progress=None, on_done=None):
    def _run():
        try:
            if on_progress: on_progress(10)
            with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(project_dir):
                    for file in files:
                        fp  = os.path.join(root, file)
                        arc = os.path.relpath(fp, os.path.dirname(project_dir))
                        zf.write(fp, arc)
            if on_progress: on_progress(100)
            if on_done: on_done(out_path)
        except Exception as e:
            print(f"[PM] ✗ ZIP : {e}")
            if on_done: on_done(None)
    threading.Thread(target=_run, daemon=True).start()
