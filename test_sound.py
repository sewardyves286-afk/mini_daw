import numpy as np
import sounddevice as sd

samplerate = 44100
duration = 2 # secondes
frequency = 440 # La

t = np.linspace(0, duration, int(samplerate * duration),endpoint=False)
wave = 0.5 * np.sin(2 * np.pi * frequency * t)

sd.play(wave, samplerate)
sd.wait()