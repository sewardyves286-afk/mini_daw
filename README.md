# 🎛 mini_daw

**mini_daw** est une application de création musicale desktop, inspirée de FL Studio et Ableton Live, construite entièrement en Python + tkinter.

![Python](https://img.shields.io/badge/Python-3.12-blue)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)
![License](https://img.shields.io/badge/License-MIT-green)

---

## ✨ Fonctionnalités

### Timeline
- Grille infinie avec mesures synchronisées au BPM
- Zoom horizontal (Ctrl+molette ou boutons −/+) de ¼x à 6x
- Snap musical automatique sur les temps (beat) selon le BPM
- Playhead déplaçable par clic ou glisser n'importe où sur la grille
- Auto-scroll : la grille suit le playhead pendant la lecture
- Sélection multiple par rectangle (lasso) + déplacement en bloc

### Outils de la toolbar
| Icône | Outil | Action |
|-------|-------|--------|
| ↖ | Sélection | Déplacer, redimensionner les clips |
| ✂ | Split | Clic sur un clip = couper en deux |
| M | Mute | Clic sur un clip = muter/démuter |

### Clips audio
- Import drag-and-drop ou via le menu File → Import
- Couleurs personnalisables (12 couleurs, clic droit → 🎨 Couleur)
- Couleurs persistées à la réouverture du projet
- Split direct dans la timeline (Ctrl+clic ou outil ✂)
- Resize horizontal (bords gauche/droit) avec snap musical
- Duplication (Ctrl+D), suppression (Suppr)
- Mute visuel avec l'outil M

### Éditeur audio (clip editor)
- Waveform scrollable et zoomable (molette)
- Règle des temps infinie (ms → secondes)
- Playhead positionnable par clic sur la waveform
- Sélection de zone (glisser) pour découper
- Effets DSP natifs (sans scipy) :
  - 🔇 Noise Reduction
  - 🏛 Reverb
  - 🔁 Echo / Delay
  - 🎵 Pitch Shift
- Transport interne (▶ ⏹ ●) avec timer
- Envoi direct sur la timeline après édition

### Enregistrement
- Enregistrement micro/ligne via sounddevice
- VU-mètre temps réel (20 segments)
- Contrôle du gain (0.1x → 2.0x)
- Envoi automatique sur la timeline après stop
- Sauvegarde dans `samples/recordings/`

### Projets
- Format `.mdaw` (JSON) — chemins absolus, zéro copie
- Save (Ctrl+S) / Save As / New Project / Open
- Templates intégrés : Blank, Minimal, Trap, Lofi, Podcast
- Recherche automatique des fichiers manquants à l'ouverture
- Dialog de sauvegarde à la fermeture
- Auto-save toutes les 2 minutes

### Transport
- BPM ajustable (40–300) par boutons +/− ou molette
- Métronome audio précis (sample-accurate via sounddevice)
- Signature rythmique variable (2/4, 3/4, 4/4, 6/4, 7/4, 8/4)
- Indicateur de beat clignotant

### Interface
- Thème sombre complet (#0f0f0f)
- Explorateur de fichiers intégré (View → Samples/Recordings/Projects)
- Navigation avec ← ↑ et chemin éditable
- Pattern Editor (séquenceur de drums)
- Plugin Picker (Phase 2)
- Associations Windows : double-clic sur `.mdaw` ouvre mini_daw

---

## 🗂 Structure du projet

```
mini_daw/
├── main.py                 # Point d'entrée — gère sys.argv (double-clic .mdaw)
├── gui.py                  # Interface principale — timeline, transport, menus
├── engine.py               # Moteur audio — lecture des clips
├── clip_editor.py          # Éditeur audio — waveform, effets DSP, découpe
├── recorder.py             # Enregistrement micro/ligne
├── project_manager.py      # Sauvegarde/chargement .mdaw
├── file_explorer.py        # Explorateur de fichiers intégré
├── metronome.py            # Métronome sample-accurate
├── pattern_editor.py       # Séquenceur de drums
├── build_exe.bat           # Compilation PyInstaller → mini_daw.exe
├── create_association.py   # Association Windows .mdaw → mini_daw.exe
├── assets/
│   ├── logo.ico
│   └── logo.png
├── samples/
│   ├── recordings/         # Enregistrements micro
│   └── edited/             # Clips édités
└── projects/               # Projets sauvegardés
    └── nom_projet/
        └── nom_projet.mdaw
```

---

## 🚀 Installation et lancement

### Prérequis
- Python 3.12
- Windows 10/11

### Dépendances
```bash
pip install sounddevice soundfile numpy pydub
pip install pyinstaller   # pour la compilation exe
```

### Lancer en développement
```bash
cd C:\Users\sewar_000\Desktop\mini_daw
python main.py
```

### Compiler l'exe
```powershell
.\build_exe.bat
```

### Associer les fichiers .mdaw
```bash
python create_association.py
```
Après ça, double-clic sur n'importe quel `.mdaw` dans l'Explorateur Windows ouvre mini_daw directement.

---

## ⌨️ Raccourcis clavier

| Raccourci | Action |
|-----------|--------|
| `Ctrl+S` | Sauvegarder |
| `Ctrl+Z` | Annuler |
| `Ctrl+Y` | Rétablir |
| `Ctrl+N` | Nouveau projet |
| `Ctrl+O` | Ouvrir un projet |
| `Ctrl+D` | Dupliquer le clip sélectionné |
| `Ctrl+A` | Sélectionner tout |
| `Ctrl+clic` | Split du clip |
| `Ctrl+molette` | Zoom horizontal |
| `Suppr` | Supprimer le clip sélectionné |

---

## 🛠 Stack technique

| Composant | Technologie |
|-----------|-------------|
| Interface | Python tkinter (Canvas natif) |
| Audio playback | sounddevice + numpy |
| Audio I/O | soundfile |
| Format export MP3 | pydub |
| Compilation | PyInstaller --onefile --windowed |
| Format projet | JSON (.mdaw) |
| DSP | numpy pur (STFT, convolution, pitch shift) |

---

## 📋 Roadmap

- [ ] VST2/VST3 support (Phase 2)
- [ ] Channel Rack (instruments)
- [ ] Mixer avec effets par piste
- [ ] Automation des paramètres
- [ ] Time-stretch selon BPM (librosa/rubberband)
- [ ] Export MP4 vidéo

---

## 👤 Auteur

Projet personnel — développé avec Python + Claude (Anthropic)
