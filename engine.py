import sounddevice as sd
import soundfile as sf
import numpy as np


class AudioEngine:
    def __init__(self):
        self.tracks = []
        self.stream = None
        self.samplerate = 44100
        self.position = 0  # position de lecture globale

    def add_track(self, file_path, volume=1.0):
        try:
            data, samplerate = sf.read(file_path, dtype="float32")

            # Conversion stéréo -> mono (très important pour éviter les erreurs broadcast)
            if data.ndim == 2:
                data = data.mean(axis=1)

            self.tracks.append({
                "data": data,
                "volume": volume,
                "length": len(data)
            })

            self.samplerate = samplerate
            print(f"Piste ajoutée : {file_path}")

        except Exception as e:
            print("Erreur chargement :", e)

    def clear_tracks(self):
        self.tracks.clear()
        self.position = 0

    def _callback(self, outdata, frames, time, status):
        try:
            if not self.tracks:
                outdata[:] = 0
                return

            # Buffer de mixage (mono)
            mix = np.zeros(frames, dtype="float32")

            for track in self.tracks:
                data = track["data"]
                volume = track["volume"]
                length = track["length"]

                start = self.position
                end = self.position + frames

                if start >= length:
                    continue

                chunk = data[start:min(end, length)]

                # Sécurité supplémentaire (si jamais un fichier stéréo passe)
                if chunk.ndim == 2:
                    chunk = chunk.mean(axis=1)

                mix[:len(chunk)] += chunk * volume

            # Sortie stéréo (copie du mix mono vers L et R)
            outdata[:, 0] = mix
            if outdata.shape[1] > 1:
                outdata[:, 1] = mix

            self.position += frames

        except Exception as e:
            print("Erreur lecture :", e)
            outdata[:] = 0

    def play(self):
        if not self.tracks:
            print("Aucune piste chargée.")
            return

        # Reset lecture depuis le début
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
