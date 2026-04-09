"""
metronome.py — Métronome audio précis pour Mini DAW
Utilise un callback sounddevice pour un timing sample-accurate.
"""

import threading
import numpy as np

try:
    import sounddevice as sd
    SD_OK = True
except ImportError:
    SD_OK = False

SAMPLE_RATE = 44100


def _make_click(freq=1000, duration=0.025, volume=0.7):
    """Génère un clic court avec envelope exponentielle."""
    n    = int(SAMPLE_RATE * duration)
    t    = np.linspace(0, duration, n, dtype=np.float32)
    wave = np.sin(2 * np.pi * freq * t)
    env  = np.exp(-t * 120).astype(np.float32)
    click = (wave * env * volume).astype(np.float32)
    return np.column_stack([click, click])


def _make_accent(freq=1500, duration=0.030, volume=1.0):
    """Clic accentué pour le 1er temps."""
    n    = int(SAMPLE_RATE * duration)
    t    = np.linspace(0, duration, n, dtype=np.float32)
    wave = np.sin(2 * np.pi * freq * t)
    env  = np.exp(-t * 100).astype(np.float32)
    click = (wave * env * volume).astype(np.float32)
    return np.column_stack([click, click])


CLICK_NORMAL = _make_click()
CLICK_ACCENT = _make_accent()


class Metronome:
    """
    Métronome précis basé sur un stream sounddevice continu.
    Le timing est calculé en samples → pas de dérive due à sleep().
    """

    def __init__(self):
        self._stream       = None
        self._lock         = threading.Lock()
        self.running       = False
        self.bpm           = 120
        self.beats_per_bar = 4
        self._on_beat_cb   = None

        # État interne du callback (sample-accurate)
        self._beat_period  = 0      # en samples
        self._next_beat    = 0      # sample absolu du prochain clic
        self._sample_pos   = 0      # position courante dans le stream
        self._beat_count   = 0
        self._click_buf    = None   # buffer actif à jouer
        self._click_pos    = 0      # position dans le buffer du clic

    # ----------------------------------------------------------------
    def start(self, bpm=120, beats_per_bar=4, on_beat=None):
        self.stop()
        if not SD_OK:
            print("[Metronome] sounddevice manquant")
            return

        self._lock.acquire()
        try:
            self.bpm           = max(20, min(400, int(bpm)))
            self.beats_per_bar = int(beats_per_bar)
            self._on_beat_cb   = on_beat
            self._beat_period  = int(SAMPLE_RATE * 60.0 / self.bpm)
            self._next_beat    = 0
            self._sample_pos   = 0
            self._beat_count   = 0
            self._click_buf    = None
            self._click_pos    = 0
            self.running       = True
        finally:
            self._lock.release()

        try:
            self._stream = sd.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=2,
                dtype="float32",
                blocksize=512,
                callback=self._callback,
                finished_callback=self._on_finished,
            )
            self._stream.start()
            print(f"[Metronome] ▶ {self.bpm} BPM  {self.beats_per_bar}/4")
        except Exception as e:
            print(f"[Metronome] Erreur stream : {e}")
            self.running = False

    # ----------------------------------------------------------------
    def stop(self):
        self.running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        print("[Metronome] ⏹ Arrêté")

    def update_bpm(self, bpm):
        """Met à jour le BPM sans redémarrer le stream."""
        self._lock.acquire()
        try:
            self.bpm          = max(20, min(400, int(bpm)))
            self._beat_period = int(SAMPLE_RATE * 60.0 / self.bpm)
        finally:
            self._lock.release()
        print(f"[Metronome] BPM mis à jour : {self.bpm}")

    def update_sig(self, beats_per_bar):
        self._lock.acquire()
        try:
            self.beats_per_bar = int(beats_per_bar)
        finally:
            self._lock.release()

    # ----------------------------------------------------------------
    def _callback(self, outdata, frames, time_info, status):
        """Callback appelé par sounddevice — timing sample-accurate."""
        if not self._lock.acquire(blocking=False):
            outdata[:] = 0
            return
        try:
            outdata[:] = 0
            pos = 0

            while pos < frames:
                # --- Injecter le clic en cours ---
                if self._click_buf is not None:
                    remaining_click = len(self._click_buf) - self._click_pos
                    remaining_frame = frames - pos
                    n = min(remaining_click, remaining_frame)
                    outdata[pos:pos+n] += \
                        self._click_buf[self._click_pos:self._click_pos+n]
                    self._click_pos += n
                    pos += n
                    if self._click_pos >= len(self._click_buf):
                        self._click_buf = None
                    continue

                # --- Chercher le prochain beat dans ce bloc ---
                samples_to_beat = self._next_beat - self._sample_pos
                if samples_to_beat <= pos:
                    # Le beat tombe dans ce bloc
                    beat_offset = max(0, int(samples_to_beat))
                    is_accent   = (self._beat_count % self.beats_per_bar) == 0

                    # Choisir le clic
                    src = CLICK_ACCENT if is_accent else CLICK_NORMAL
                    self._click_buf = src.copy()
                    self._click_pos = 0

                    # Callback UI (dans un thread séparé pour ne pas bloquer)
                    if self._on_beat_cb:
                        try:
                            self._on_beat_cb(
                                self._beat_count, is_accent)
                        except Exception:
                            pass

                    self._beat_count += 1
                    self._next_beat  += self._beat_period
                else:
                    # Pas de beat dans ce bloc → remplir de silence
                    pos = frames

            self._sample_pos += frames
        finally:
            self._lock.release()

    def _on_finished(self):
        pass
