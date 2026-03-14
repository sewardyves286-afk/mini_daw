"""
engine.py — Moteur audio du Mini DAW
Utilise stream.write() dans un thread (compatible Realtek Windows).
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
    print("[Engine] pydub non disponible — MP3 non supporté")


BLOCK_SIZE = 2048


def find_output_device():
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        if "Microsoft Sound Mapper" in d["name"] and d["max_output_channels"] > 0:
            print(f"[Engine] Device sortie : [{i}] {d['name']}")
            return i
    default = sd.default.device[1]
    if default is not None and default >= 0:
        print(f"[Engine] Device sortie (défaut) : [{default}] {devices[default]['name']}")
        return default
    return None


class AudioEngine:

    def __init__(self):
        self.tracks        = []
        self.stream        = None
        self.samplerate    = 44100
        self.playing       = False
        self.bpm           = 120
        self._cache        = {}
        self._thread       = None
        self._stop_event   = threading.Event()
        self.output_device = find_output_device()

    # ==============================
    # BPM
    # ==============================
    def set_bpm(self, bpm):
        try:
            self.bpm = int(bpm)
            print(f"[Engine] BPM : {self.bpm}")
        except Exception:
            print("[Engine] BPM invalide")

    # ==============================
    # CHARGEMENT FICHIER
    # ==============================
    AUDIO_EXTS = {".wav", ".flac", ".ogg", ".aiff", ".aif", ".mp3",
                   ".mp4", ".m4a", ".wma", ".aac", ".opus"}

    def _load_file(self, file_path):
        if file_path in self._cache:
            return self._cache[file_path], self.samplerate

        if not os.path.exists(file_path):
            print(f"[Engine] Fichier introuvable : {file_path}")
            return None, None

        ext = os.path.splitext(file_path)[1].lower()

        if ext not in self.AUDIO_EXTS:
            print(f"[Engine] Format non supporté ignoré : {ext} ({os.path.basename(file_path)})")
            return None, None

        try:
            if ext == ".mp3":
                if not PYDUB_OK:
                    print("[Engine] Installez pydub pour lire les MP3")
                    return None, None
                wav_path = file_path.replace(".mp3", "_daw_tmp.wav")
                if not os.path.exists(wav_path):
                    seg = AudioSegment.from_mp3(file_path)
                    seg = seg.set_frame_rate(self.samplerate)
                    seg.export(wav_path, format="wav")
                data, sr = sf.read(wav_path, dtype="float32")
            else:
                data, sr = sf.read(file_path, dtype="float32")

            if data.ndim == 2:
                data = data.mean(axis=1)

            self.samplerate = sr
            self._cache[file_path] = data
            print(f"[Engine] Chargé : {os.path.basename(file_path)} "
                  f"({len(data)/sr:.2f}s, {sr}Hz)")
            return data, sr

        except Exception as e:
            print(f"[Engine] Erreur chargement '{file_path}' : {e}")
            return None, None

    # ==============================
    # ADD TRACK
    # ==============================
    def add_track(self, file_path, volume=1.0):
        data, sr = self._load_file(file_path)
        if data is None:
            return
        self.tracks.append({
            "data":            data,
            "volume":          float(volume),
            "mute":            False,
            "solo":            False,
            "pan":             0.0,
            "read_pos":        0,
            "silence_samples": 0,
            "silence_done":    0,
        })
        print(f"[Engine] Piste ajoutée : {os.path.basename(file_path)}")

    # ==============================
    # LOAD CLIPS
    # ==============================
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
            # Volume : depuis clip (mis à jour par slider) ou défaut 80
            vol_raw = clip.get("volume", 80)
            volume  = float(vol_raw) / 100.0 if vol_raw > 1 else float(vol_raw)
            # Pan : -1.0 (gauche) .. 0 .. +1.0 (droite)
            pan_raw = clip.get("pan", 0)
            pan     = float(pan_raw) / 50.0 if abs(pan_raw) > 1 else float(pan_raw)
            pan     = max(-1.0, min(1.0, pan))

            if start_pos <= clip_start:
                silence_samples = int((clip_start - start_pos) * self.samplerate)
                read_pos = 0
            else:
                silence_samples = 0
                read_pos = int((start_pos - clip_start) * self.samplerate)
                if read_pos >= len(data):
                    print(f"[Engine] Clip '{os.path.basename(fp)}' déjà terminé, ignoré")
                    continue

            print(f"[Engine] '{os.path.basename(fp)}' "
                  f"start={clip_start:.2f}s vol={volume:.2f} pan={pan:.2f} "
                  f"silence={silence_samples}smp read_pos={read_pos}smp")

            self.tracks.append({
                "data":            data,
                "volume":          volume,
                "mute":            False,
                "solo":            False,
                "pan":             pan,
                "read_pos":        read_pos,
                "silence_samples": silence_samples,
                "silence_done":    0,
                "clip_ref":        clip,   # référence pour vol/pan live
            })
            print(f"[Engine] Clip '{os.path.basename(fp)}' prêt "
                  f"(silence={silence_samples}smp, read_pos={read_pos}smp)")

        print(f"[Engine] {len(self.tracks)} clip(s) chargé(s)")

    # ==============================
    # MIXAGE D'UN BLOC
    # ==============================
    def _mix_block(self, frames):
        mix         = np.zeros((frames, 2), dtype="float32")
        solo_active = any(t["solo"] for t in self.tracks)

        for track in self.tracks:
            data     = track["data"]
            read_pos = track["read_pos"]

            # Lire vol/pan en temps réel depuis le clip
            clip_ref = track.get("clip_ref")
            if clip_ref is not None:
                vol_raw = clip_ref.get("volume", 80)
                volume  = float(vol_raw) / 100.0 if vol_raw > 1 else float(vol_raw)
                pan_raw = clip_ref.get("pan", 0)
                pan     = float(pan_raw) / 50.0 if abs(float(pan_raw)) > 1 else float(pan_raw)
                pan     = max(-1.0, min(1.0, pan))
            else:
                volume = track["volume"]
                pan    = track["pan"]

            silence_needed = track["silence_samples"] - track["silence_done"]

            if silence_needed >= frames:
                track["silence_done"] += frames
                continue

            audio_start = int(max(0, silence_needed))
            if silence_needed > 0:
                track["silence_done"] += silence_needed

            frames_to_read = frames - audio_start
            end_pos        = read_pos + frames_to_read

            if read_pos >= len(data):
                continue

            chunk = data[read_pos : min(end_pos, len(data))].copy()
            if len(chunk) == 0:
                continue

            track["read_pos"] += len(chunk)

            if track["mute"] or (solo_active and not track["solo"]):
                continue

            chunk *= volume

            left  = np.sqrt(max(0.0, 0.5 * (1.0 - pan))) * chunk
            right = np.sqrt(max(0.0, 0.5 * (1.0 + pan))) * chunk

            mix[audio_start : audio_start + len(chunk), 0] += left
            mix[audio_start : audio_start + len(chunk), 1] += right

        return np.clip(mix, -1.0, 1.0)

    # ==============================
    # BOUCLE DE LECTURE (thread)
    # ==============================
    def _play_loop(self):
        try:
            # Essayer d'abord avec le device préféré
            device = self.output_device
            for attempt in range(3):
                try:
                    stream_kwargs = dict(
                        samplerate=self.samplerate,
                        channels=2,
                        dtype="float32",
                        latency="high"
                    )
                    if device is not None:
                        stream_kwargs["device"] = device
                    with sd.OutputStream(**stream_kwargs) as stream:
                        print(f"[Engine] ▶ Lecture démarrée (device={device})")
                        while not self._stop_event.is_set():
                            try:
                                block = self._mix_block(BLOCK_SIZE)
                                stream.write(block)
                            except Exception as e:
                                print(f"[Engine] Erreur write : {e}")
                                break
                            all_done = all(
                                t["read_pos"] >= len(t["data"])
                                for t in self.tracks
                            )
                            if all_done and self.tracks:
                                print("[Engine] ✔ Tous les clips terminés")
                                break
                    break  # succès
                except sd.PortAudioError as e:
                    print(f"[Engine] PortAudio erreur (tentative {attempt+1}) : {e}")
                    device = None  # fallback sur device par défaut
                    if attempt == 2:
                        print("[Engine] Impossible d'ouvrir le stream audio")

        except Exception as e:
            print(f"[Engine] Erreur fatale lecture : {e}")
            import traceback; traceback.print_exc()
        finally:
            self.playing = False
            print("[Engine] Thread lecture terminé")

    # ==============================
    # PLAY direct
    # ==============================
    def play(self):
        if not self.tracks:
            print("[Engine] Aucune piste chargée.")
            return
        self._start_thread()

    # ==============================
    # PLAY CLIPS (depuis gui.py)
    # ==============================
    def play_clips(self, clips: dict, start_pos: float = 0.0,
                   bpm: int = 120, on_tick=None):
        self.set_bpm(bpm)
        self.load_clips(clips, start_pos)

        if not self.tracks:
            print("[Engine] Aucun clip audio à jouer.")
            return

        self._start_thread()

    def _start_thread(self):
        """
        Lance le thread de lecture.
        NE PAS appeler self.stop() ici — ça tuerait le thread
        avant qu'il démarre et couperait le son dans gui.py.
        On arrête juste proprement l'éventuel thread précédent.
        """
        # Arrêter l'ancien thread s'il tourne encore
        if self._thread and self._thread.is_alive():
            self._stop_event.set()
            self._thread.join(timeout=2)

        # Repartir proprement
        self._stop_event.clear()
        self.playing = True

        self._thread = threading.Thread(
            target=self._play_loop,
            daemon=True
        )
        self._thread.start()
        print(f"[Engine] Thread démarré : {self._thread.is_alive()}")

    # ==============================
    # STOP
    # ==============================
    def stop(self):
        self._stop_event.set()
        self.playing = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None
        print("[Engine] ⏹ Stop")

    # ==============================
    # RESET
    # ==============================
    def reset(self):
        for t in self.tracks:
            t["read_pos"]     = 0
            t["silence_done"] = 0
        print("[Engine] Position remise à zéro")

    # ==============================
    # CONTROLES PAR PISTE
    # ==============================
    def set_track_volume(self, index, volume_0_100):
        if 0 <= index < len(self.tracks):
            self.tracks[index]["volume"] = volume_0_100 / 100.0

    def set_track_pan(self, index, pan):
        if 0 <= index < len(self.tracks):
            self.tracks[index]["pan"] = float(np.clip(pan, -1.0, 1.0))

    def set_track_mute(self, index, mute: bool):
        if 0 <= index < len(self.tracks):
            self.tracks[index]["mute"] = mute

    def set_track_solo(self, index, solo: bool):
        if 0 <= index < len(self.tracks):
            self.tracks[index]["solo"] = solo

    # ==============================
    # NETTOYAGE
    # ==============================
    def cleanup(self):
        self.stop()
        for fp in list(self._cache.keys()):
            tmp = fp.replace(".mp3", "_daw_tmp.wav")
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
        self._cache.clear()
        print("[Engine] Nettoyage OK")
