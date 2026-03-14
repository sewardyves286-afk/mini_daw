# 🎛 mini_daw

> A lightweight Digital Audio Workstation (DAW) built from scratch in Python.

![Status](https://img.shields.io/badge/status-work%20in%20progress-yellow)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

---

## 📌 Project Goal

mini_daw is inspired by modern DAWs like **Ableton Live** and **FL Studio**, but focuses on understanding and implementing core audio fundamentals step by step — entirely in Python, with no external DAW framework.

The goal is to progressively build a modular audio workstation from scratch, including:

- Multi-track timeline with drag, resize and snap
- Real-time audio playback and mixing
- Voice and instrument recording
- Audio clip editing with effects
- BPM-synchronized grid and metronome
- Import from disk, web, or internal library
- Export final mix to WAV

---

## 🖥 Screenshots

> _Timeline view_
> ![Timeline](assets/screenshots/timeline.png)

> _Clip Editor with effects_
> ![Clip Editor](assets/screenshots/clip_editor.png)

> _File Explorer (built-in)_
> ![File Explorer](assets/screenshots/file_explorer.png)

---

## ✅ Features

### 🎚 Transport & Timeline
- Play / Stop / Record buttons with rounded UI
- BPM control with mouse wheel support
- Time signature selector (2, 3, 4, 6, 7, 8)
- Playhead with click-to-seek on ruler
- Auto-stop at end of last clip
- Grid redraws dynamically on BPM change
- Ruler displays bar numbers instead of seconds

### 🎵 Metronome
- Sample-accurate metronome via sounddevice callback stream
- Accented first beat per bar
- Visual beat indicator (flashing dot)
- Works standalone or synced to Play
- BPM and time signature update in real time

### 🎞 Clips
- Import audio: WAV, MP3, FLAC, OGG, AIFF, AAC, WMA
- Rounded clip blocks, 50% height, centered in track
- Drag clips horizontally and vertically (snap to grid)
- Resize clips: left/right edges → adjust duration (↔)
- Resize clips: top/bottom edges → adjust height (↕)
- Right-click context menu: Edit, Duplicate, Delete
- Clips turn green after editing

### 🎛 Tracks (panel left)
- 5 tracks with Vol and Pan sliders
- Rounded custom canvas sliders
- Vol/Pan updates clips in real time during playback
- Pan uses equal-power stereo law

### 🎤 Recording
- Microphone input via sounddevice InputStream
- Real-time VU meter
- Device selector
- Recordings saved to `samples/recordings/`
- Recorded clip placed at playhead position on timeline

### 🎛 Clip Editor
- Open via right-click → Editor
- Waveform display with click-drag selection
- Cut: keep selection or remove selection
- Effects (toggle per clip):
  - 🔇 **Noise Reduction** — spectral subtraction
  - 🏛 **Reverb** — convolution with synthetic IR (room size, damping, mix)
  - 🔁 **Echo / Delay** — delay ms, feedback, mix
  - 🎵 **Pitch Shift** — ±12 semitones via resampling
- Preview before applying
- Saves edited file to `samples/edited/`
- Updates clip on timeline after apply

### 📂 Import
- **Built-in File Explorer** — navigate full disk, favorites, drives
  - Back / Forward / Up navigation
  - Filter: all files or audio only
  - Mini waveform preview + audio info
  - ▶ Listen before importing
- **Import Web** — paste any direct URL (.wav, .mp3...) and download
  - Sources: Freesound, Looperman, Sampleswap, Zapsplat
  - Progress bar + file saved to `samples/`
- **My Samples** — browse internal library
  - Tabs: Downloads / Recordings / Edited
  - Import with one click

### ⬇ Export
- Full mixdown to stereo WAV (44100 Hz)
- Respects clip positions, volumes, pan
- Real audio duration (not clip visual width)
- Progress bar, custom filename and folder

### 💾 Projects
- Save / Load `.mdaw` project files (JSON)
- New project dialog with name field
- Reloads all clips from saved audio file paths
- Warning if audio files are missing on load
- Undo / Redo (Ctrl+Z / Ctrl+Y)

---

## 🗂 Project Structure

```
mini_daw/
│
├── main.py              # Entry point — splash screen, global error handler
├── gui.py               # Main window — timeline, transport, tracks, clips
├── engine.py            # Audio engine — mixing, playback via sounddevice
├── recorder.py          # Recording window — mic input, VU meter
├── metronome.py         # Sample-accurate metronome (sounddevice stream)
├── clip_editor.py       # Clip editor — waveform, cut, effects (NR/reverb/delay/pitch)
├── exporter.py          # Mixdown export to WAV
├── file_explorer.py     # Built-in file browser (replaces tkinter filedialog)
├── web_importer.py      # Import audio from URL
├── project_manager.py   # Save/load .mdaw project files (JSON)
│
├── assets/
│   ├── logo.ico
│   └── logo.png
│
├── samples/
│   ├── recordings/      # Saved voice recordings
│   └── edited/          # Clips processed in the editor
│
└── projects/            # Saved .mdaw project files
```

---

## ⚙ Installation

### Requirements

- Python 3.10+
- Windows (tested on Windows 10/11)

### Dependencies

```bash
pip install sounddevice soundfile numpy scipy pydub requests
```

| Package | Usage |
|---|---|
| `sounddevice` | Audio playback, recording, metronome stream |
| `soundfile` | Read/write WAV, FLAC, OGG files |
| `numpy` | Audio buffer processing, effects DSP |
| `scipy` | Reverb (FFT convolution), noise reduction (STFT) |
| `pydub` | MP3 decoding (requires FFmpeg) |
| `requests` | Web audio download |

### FFmpeg (for MP3 support)

Download FFmpeg and place the binary in `mini_daw/ffmpeg-*/bin/` or add it to your system PATH.

---

## 🚀 Run

```bash
cd mini_daw
python main.py
```

---

## 🎮 Quick Start

1. **Import a sample** — `Fichier → Importer un fichier audio` or `📂 Import` button
2. **Place on timeline** — clip appears at playhead position
3. **Press ▶** — hear your mix
4. **Record a voice** — press `●` REC, select microphone, record
5. **Edit a clip** — right-click on clip → `🎛 Éditeur`
6. **Export** — `Fichier → Exporter WAV`
7. **Save project** — `Fichier → Sauvegarder` (`.mdaw` file)

### Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+Z` | Undo |
| `Ctrl+Y` | Redo |
| `Ctrl+S` | Save project |
| `Ctrl+N` | New project |
| `Ctrl+D` | Duplicate clip |
| `Delete` | Delete selected clip |

---

## 🗺 Roadmap

- [ ] Waveform drawn inside each clip on the timeline
- [ ] Loop region (A/B loop)
- [ ] Mute / Solo buttons per track (connected to engine)
- [ ] MIDI input support
- [ ] Plugin system (VST-like effects per track)
- [ ] Real-time pitch correction (autotune)
- [ ] Export to MP3
- [ ] Dark / Light theme toggle
- [ ] Linux and macOS support

---

## 👤 Author

Built by **sewar** — learning audio programming one module at a time.

---

## 📄 License

MIT License — free to use, modify and distribute.
