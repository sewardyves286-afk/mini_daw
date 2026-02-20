import sounddevice as sd
import soundfile as sf
import numpy as np


class AudioEngine:
    def __init__(self):
        self.tracks = []
        self.stream = None
        self.samplerate = 44100
        self.position = 0

    def add_track(self, file_path, volume=1.0):
        try:
            data, samplerate = sf.read(file_path, dtype="float32")

            # Convertir en mono si nécessaire
            if data.ndim == 2:
                data = data.mean(axis=1)

            self.tracks.append({
                "data": data,
                "volume": volume,
                "length": len(data),
                "mute": False,
                "solo": False,
                "pan": 0.0  # -1 = gauche, 0 = centre, 1 = droite
            })

            self.samplerate = samplerate
            print(f"Piste ajoutée : {file_path}")

        except Exception as e:
            print("Erreur chargement :", e)

    def clear_tracks(self):
        self.tracks.clear()
        self.position = 0

    # ===== CALLBACK AUDIO =====
    def _callback(self, outdata, frames, time, status):
        try:
            if not self.tracks:
                outdata[:] = 0
                return

            mix = np.zeros((frames, 2), dtype="float32")  # stéréo

            # Déterminer si un solo est actif
            solo_active = any(track.get("solo", False) for track in self.tracks)

            for track in self.tracks:
                data = track["data"]
                volume = track["volume"]
                mute = track.get("mute", False)
                solo = track.get("solo", False)
                pan = track.get("pan", 0.0)
                length = track["length"]

                start = self.position
                end = self.position + frames
                if start >= length:
                    continue

                chunk = data[start:min(end, length)]
                # Ajuster le volume selon mute/solo
                if mute or (solo_active and not solo):
                    chunk *= 0.0
                else:
                    chunk *= volume

                # Appliquer pan
                left = np.sqrt(0.5 * (1 - pan)) * chunk
                right = np.sqrt(0.5 * (1 + pan)) * chunk

                mix[:len(chunk), 0] += left
                mix[:len(chunk), 1] += right

            outdata[:] = mix
            self.position += frames

        except Exception as e:
            print("Erreur lecture :", e)
            outdata[:] = 0

    # ===== PLAY / STOP =====
    def play(self):
        if not self.tracks:
            print("Aucune piste chargée.")
            return

        self.position = 0
        if self.stream is not None:
            self.stop()

        self.stream = sd.OutputStream(
            samplerate=self.samplerate,
            channels=2,
            dtype="float32",
            callback=self._callback,
            latency="low"
        )
        self.stream.start()
        print("Lecture en cours...")

    def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
            print("Lecture arrêtée.")
