import sounddevice as sd
import soundfile as sf
import numpy as np
import os

print("=== TEST 1 : PERIPHERIQUES AUDIO ===")
print(sd.query_devices())
print("\nPeripherique sortie par defaut:", sd.default.device)

print("\n=== TEST 2 : SON PUR 1 SECONDE (bip 440Hz) ===")
try:
    sr = 44100
    t = np.linspace(0, 1, sr, False)
    tone = np.sin(2 * np.pi * 440 * t).astype("float32")
    stereo = np.column_stack([tone, tone])
    sd.play(stereo, sr)
    sd.wait()
    
    print("OK - Tu as du entendre un bip")
except Exception as e:
    print("ERREUR son pur:", e)

print("\n=== TEST 3 : SCAN DOSSIER SAMPLES ===")
samples_dir = r"C:\Users\sewar_000\Desktop\mini_daw\samples"
if os.path.exists(samples_dir):
    fichiers = os.listdir(samples_dir)
    print("Fichiers trouves:", fichiers)

    # Cherche le premier WAV ou MP3
    audio = [f for f in fichiers if f.endswith((".wav", ".mp3", ".flac"))]
    if audio:
        fichier = os.path.join(samples_dir, audio[0])
        print(f"\n=== TEST 4 : LECTURE {audio[0]} ===")
        try:
            data, sr = sf.read(fichier, dtype="float32")
            print(f"Shape: {data.shape} | SR: {sr} | Duree: {len(data)/sr:.2f}s")
            if data.ndim == 1:
                data = np.column_stack([data, data])
            sd.play(data, sr)
            sd.wait()
            print("OK - Lecture terminee")
        except Exception as e:
            print("ERREUR lecture fichier:", e)
    else:
        print("Aucun fichier audio trouve dans samples/")
else:
    print("Dossier samples introuvable:", samples_dir)

input("\nAppuie sur ENTREE pour fermer...")
