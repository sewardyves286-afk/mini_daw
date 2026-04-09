"""
engine.py — Moteur audio Mini DAW v2
Corrections : playhead remis à 0 proprement, cache invalidé, noms de fichiers courts.
"""
import os
import threading
import numpy as np
import sounddevice as sd
import soundfile as sf

try:
    from pydub import AudioSegment
    PYDUB_OK = True
except ImportError:
    PYDUB_OK = False

BLOCK_SIZE = 2048
AUDIO_EXTS = {".wav",".flac",".ogg",".aiff",".aif",".mp3",".mp4",".m4a",".wma",".aac",".opus"}


def find_output_device():
    try:
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            if "Microsoft Sound Mapper" in d["name"] and d["max_output_channels"] > 0:
                print(f"[Engine] Device sortie : [{i}] {d['name']}")
                return i
        default = sd.default.device[1]
        if default is not None and default >= 0:
            print(f"[Engine] Device sortie (défaut) : [{default}]")
            return default
    except Exception as e:
        print(f"[Engine] Erreur détection device : {e}")
    return None


class AudioEngine:

    def __init__(self):
        self.tracks        = []
        self.samplerate    = 44100
        self.playing       = False
        self.bpm           = 120
        self._cache        = {}
        self._thread       = None
        self._stop_event   = threading.Event()
        self.output_device = find_output_device()

    def set_bpm(self, bpm):
        try:
            self.bpm = int(bpm)
            print(f"[Engine] BPM : {self.bpm}")
        except Exception:
            pass

    # ------------------------------------------------
    # CHARGEMENT
    # ------------------------------------------------
    def _load_file(self, fp):
        if fp in self._cache:
            return self._cache[fp], self.samplerate

        if not os.path.exists(fp):
            print(f"[Engine] Introuvable : {fp}")
            return None, None

        ext = os.path.splitext(fp)[1].lower()
        if ext not in AUDIO_EXTS:
            print(f"[Engine] Format ignoré : {ext}")
            return None, None

        try:
            if ext == ".mp3" and PYDUB_OK:
                tmp = fp.replace(".mp3", "_daw_tmp.wav")
                if not os.path.exists(tmp):
                    AudioSegment.from_mp3(fp).set_frame_rate(
                        self.samplerate).export(tmp, format="wav")
                data, sr = sf.read(tmp, dtype="float32")
            else:
                data, sr = sf.read(fp, dtype="float32")

            if data.ndim == 2:
                data = data.mean(axis=1)

            self.samplerate      = sr
            self._cache[fp]      = data
            name = os.path.basename(fp)
            print(f"[Engine] Chargé : {name[:40]} ({len(data)/sr:.2f}s)")
            return data, sr
        except Exception as e:
            print(f"[Engine] Erreur lecture {os.path.basename(fp)} : {e}")
            return None, None

    def invalidate_cache(self, fp=None):
        """Vide le cache pour forcer le rechargement d'un fichier édité."""
        if fp:
            self._cache.pop(fp, None)
        else:
            self._cache.clear()

    # ------------------------------------------------
    # LOAD CLIPS
    # ------------------------------------------------
    def load_clips(self, clips: dict, start_pos: float = 0.0):
        self.tracks.clear()
        for rect_id, clip in clips.items():
            fp = clip.get("filepath")
            if not fp:
                continue

            data, sr = self._load_file(fp)
            if data is None:
                continue

            clip_start = clip.get("start", 0.0)
            vol_raw    = clip.get("volume", 80)
            volume     = float(vol_raw) / 100.0 if vol_raw > 1 else float(vol_raw)
            pan_raw    = clip.get("pan", 0)
            pan        = max(-1.0, min(1.0,
                float(pan_raw) / 50.0 if abs(float(pan_raw)) > 1 else float(pan_raw)))

            if start_pos <= clip_start:
                silence_samples = int((clip_start - start_pos) * self.samplerate)
                read_pos        = 0
            else:
                silence_samples = 0
                read_pos        = int((start_pos - clip_start) * self.samplerate)
                if read_pos >= len(data):
                    print(f"[Engine] Ignoré (déjà terminé) : {os.path.basename(fp)}")
                    continue

            self.tracks.append({
                "data":            data,
                "volume":          volume,
                "pan":             pan,
                "mute":            False,
                "solo":            False,
                "read_pos":        read_pos,
                "silence_samples": silence_samples,
                "silence_done":    0,
                "clip_ref":        clip,
            })
            print(f"[Engine] + {os.path.basename(fp)[:35]} "
                  f"@ {clip_start:.2f}s  vol={volume:.0%}  pan={pan:+.2f}")

        print(f"[Engine] {len(self.tracks)} clip(s) prêts")

    # ------------------------------------------------
    # MIXAGE
    # ------------------------------------------------
    def _mix_block(self, frames):
        mix         = np.zeros((frames, 2), dtype="float32")
        solo_active = any(t["solo"] for t in self.tracks)

        for track in self.tracks:
            data     = track["data"]
            read_pos = track["read_pos"]

            cr = track.get("clip_ref")
            if cr is not None:
                v   = cr.get("volume", 80)
                vol = float(v) / 100.0 if v > 1 else float(v)
                p   = cr.get("pan", 0)
                pan = max(-1.0, min(1.0,
                    float(p)/50.0 if abs(float(p)) > 1 else float(p)))
            else:
                vol = track["volume"]
                pan = track["pan"]

            sil = track["silence_samples"] - track["silence_done"]
            if sil >= frames:
                track["silence_done"] += frames
                continue

            a_start = int(max(0, sil))
            if sil > 0:
                track["silence_done"] += sil

            n   = frames - a_start
            ep  = read_pos + n
            if read_pos >= len(data):
                continue

            chunk = data[read_pos : min(ep, len(data))].copy()
            if not len(chunk):
                continue

            track["read_pos"] += len(chunk)
            if track["mute"] or (solo_active and not track["solo"]):
                continue

            chunk *= vol
            L = np.sqrt(max(0.0, 0.5*(1.0 - pan))) * chunk
            R = np.sqrt(max(0.0, 0.5*(1.0 + pan))) * chunk
            mix[a_start:a_start+len(chunk), 0] += L
            mix[a_start:a_start+len(chunk), 1] += R

        return np.clip(mix, -1.0, 1.0)

    # ------------------------------------------------
    # LECTURE
    # ------------------------------------------------
    def _play_loop(self):
        device = self.output_device
        try:
            for attempt in range(3):
                try:
                    kw = dict(samplerate=self.samplerate,
                              channels=2, dtype="float32", latency="high")
                    if device is not None:
                        kw["device"] = device
                    with sd.OutputStream(**kw) as stream:
                        print(f"[Engine] ▶ Lecture (device={device})")
                        while not self._stop_event.is_set():
                            block = self._mix_block(BLOCK_SIZE)
                            stream.write(block)
                            if self.tracks and all(
                                t["read_pos"] >= len(t["data"])
                                for t in self.tracks
                            ):
                                print("[Engine] ✔ Fin")
                                break
                    break
                except sd.PortAudioError as e:
                    print(f"[Engine] Tentative {attempt+1} échouée : {e}")
                    device = None
        except Exception as e:
            print(f"[Engine] Erreur fatale : {e}")
            import traceback; traceback.print_exc()
        finally:
            self.playing = False
            print("[Engine] ⏹ Stop")

    def play_clips(self, clips, start_pos=0.0, bpm=120, on_tick=None):
        self.set_bpm(bpm)
        self.load_clips(clips, start_pos)
        if not self.tracks:
            print("[Engine] Rien à jouer")
            return
        self._start_thread()

    def _start_thread(self):
        if self._thread and self._thread.is_alive():
            self._stop_event.set()
            self._thread.join(timeout=2)
        self._stop_event.clear()
        self.playing = True
        self._thread = threading.Thread(target=self._play_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self.playing = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None
        print("[Engine] ⏹ Stop")

    def cleanup(self):
        self.stop()
        for fp in list(self._cache):
            tmp = fp.replace(".mp3", "_daw_tmp.wav")
            if os.path.exists(tmp):
                try: os.remove(tmp)
                except: pass
        self._cache.clear()
        print("[Engine] Nettoyage OK")

    def set_track_mute(self, i, v):
        if 0 <= i < len(self.tracks): self.tracks[i]["mute"] = v
    def set_track_solo(self, i, v):
        if 0 <= i < len(self.tracks): self.tracks[i]["solo"] = v
    def set_track_volume(self, i, v):
        if 0 <= i < len(self.tracks): self.tracks[i]["volume"] = v/100.0
    def set_track_pan(self, i, v):
        if 0 <= i < len(self.tracks):
            self.tracks[i]["pan"] = float(np.clip(v, -1.0, 1.0))
