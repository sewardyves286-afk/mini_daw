"""
metronome.py — Métronome audio pour Mini DAW
Génère un clic sonore sur chaque temps selon le BPM.
"""

import threading
import numpy as np

try:
    import sounddevice as sd
    SD_OK = True
except ImportError:
    SD_OK = False


SAMPLE_RATE = 44100


def _make_click(freq=1000, duration=0.02, volume=0.6):
    """Génère un clic court (sinusoïde avec envelope)."""
    n      = int(SAMPLE_RATE * duration)
    t      = np.linspace(0, duration, n)
    wave   = np.sin(2 * np.pi * freq * t).astype("float32")
    env    = np.exp(-t * 80).astype("float32")
    click  = wave * env * volume
    stereo = np.column_stack([click, click])
    return stereo


def _make_accent(freq=1400, duration=0.025, volume=0.9):
    """Clic accentué pour le premier temps de la mesure."""
    n      = int(SAMPLE_RATE * duration)
    t      = np.linspace(0, duration, n)
    wave   = np.sin(2 * np.pi * freq * t).astype("float32")
    env    = np.exp(-t * 70).astype("float32")
    click  = wave * env * volume
    stereo = np.column_stack([click, click])
    return stereo


# Pré-générer les sons
CLICK_NORMAL = _make_click()
CLICK_ACCENT = _make_accent()


class Metronome:
    """
    Métronome audio.
    Usage :
        m = Metronome()
        m.start(bpm=120, beats_per_bar=4)
        m.stop()
    """

    def __init__(self):
        self._thread     = None
        self._stop_event = threading.Event()
        self.running     = False
        self.bpm         = 120
        self.beats_per_bar = 4
        self._beat_count   = 0
        self._on_beat_cb   = None   # callback(beat_number, is_accent)

    def start(self, bpm=120, beats_per_bar=4, on_beat=None):
        """
        Démarre le métronome.
        on_beat(beat_num, is_accent) : callback appelé à chaque temps
        """
        if self.running:
            self.stop()

        if not SD_OK:
            print("[Metronome] sounddevice manquant")
            return

        self.bpm           = max(20, min(400, bpm))
        self.beats_per_bar = beats_per_bar
        self._on_beat_cb   = on_beat
        self._beat_count   = 0
        self._stop_event.clear()
        self.running = True

        self._thread = threading.Thread(
            target=self._loop, daemon=True)
        self._thread.start()
        print(f"[Metronome] ▶ Démarré — {self.bpm} BPM, "
              f"{self.beats_per_bar}/4")

    def stop(self):
        self._stop_event.set()
        self.running = False
        print("[Metronome] ⏹ Arrêté")

    def update_bpm(self, bpm):
        """Met à jour le BPM à la volée (prend effet au prochain temps)."""
        self.bpm = max(20, min(400, bpm))

    def _loop(self):
        import time
        beat_count = 0
        while not self._stop_event.is_set():
            interval   = 60.0 / self.bpm
            is_accent  = (beat_count % self.beats_per_bar) == 0
            click_data = CLICK_ACCENT if is_accent else CLICK_NORMAL

            # Jouer le clic
            try:
                sd.play(click_data, SAMPLE_RATE, blocking=False)
            except Exception as e:
                print(f"[Metronome] Erreur audio : {e}")

            # Callback UI (beat indicator)
            if self._on_beat_cb:
                try:
                    self._on_beat_cb(beat_count, is_accent)
                except Exception:
                    pass

            beat_count += 1

            # Attendre jusqu'au prochain temps
            # (ajustement dynamique pour tenir compte du temps de traitement)
            t_start = time.perf_counter()
            while not self._stop_event.is_set():
                elapsed = time.perf_counter() - t_start
                remaining = interval - elapsed
                if remaining <= 0:
                    break
                # Sleep par petites tranches pour réagir vite au stop
                time.sleep(min(0.005, remaining))
