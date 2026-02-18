import sounddevice as sd
import numpy as np

fs = 44100
t = np.linspace(0, 1, fs)
tone =0.2 * np.sin(2 * np.pi * 440 * t)

sd.play(tone, fs)
sd.wait()