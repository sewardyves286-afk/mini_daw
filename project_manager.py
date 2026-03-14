"""
project_manager.py — Gestion des projets Mini DAW
Sauvegarde et charge l'état complet de la timeline en JSON.
"""

import os
import json
import time

PROJECTS_DIR = os.path.join(os.path.dirname(__file__), "projects")
os.makedirs(PROJECTS_DIR, exist_ok=True)


def save_project(filepath: str, clips: dict, bpm: int):
    """
    Sauvegarde le projet dans un fichier .mdaw (JSON).
    clips : dict {rect_id: clip_data} depuis gui.py
    """
    data = {
        "version":   "1.0",
        "bpm":        bpm,
        "saved_at":   time.strftime("%Y-%m-%d %H:%M:%S"),
        "clips": []
    }
    for clip in clips.values():
        data["clips"].append({
            "track":    clip.get("track",    0),
            "start":    clip.get("start",    0.0),
            "duration": clip.get("duration", 4.0),
            "label":    clip.get("label",    "Clip"),
            "filepath": clip.get("filepath", ""),
            "volume":   clip.get("volume",   80),
        })
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[ProjectManager] ✔ Sauvegardé : {filepath}")
    return True


def load_project(filepath: str):
    """
    Charge un projet depuis un fichier .mdaw.
    Retourne (bpm, clips_list) ou None si erreur.
    clips_list : liste de dicts avec track/start/duration/label/filepath/volume
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        bpm   = data.get("bpm", 120)
        clips = data.get("clips", [])
        print(f"[ProjectManager] ✔ Chargé : {filepath} ({len(clips)} clips)")
        return bpm, clips
    except Exception as e:
        print(f"[ProjectManager] Erreur chargement : {e}")
        return None
