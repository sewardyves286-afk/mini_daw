import sounddevice as sd
import soundfile as sf
import os

def record_beat(filename=" beat_3_1.wav ", duration=5, samplerate=44100):
    base, ext = os.path.splitext(filename)
    counter = 1
    new_filename = filename
    while os.path.exists(new_filename):
      new_filename = f"{base}_{counter}{ext}"
      counter += 1 
    print("Enregistrement dans 2 secondes...")
    sd.sleep(2000)

    print("Enregistrement en cours...")
    audio = sd.rec(
        int(duration * samplerate),
        samplerate=samplerate,
        channels=1,
        dtype="float32"
    )
    sd.wait()

    sf.write(new_filename, audio, samplerate)
    print(f"Sauvegardé : {new_filename}")
if __name__=="__main__":
    record_beat(" beat_3_1.wav", duration=5)

 
