# Audio Processor v0.2.0

🌐 English | [Versión en español](README-ES.md) | 📝 [Changelog](CHANGELOG.md)

**Converts** audio to MP3 or WAV, **analyzes** it into a CSV (BPM, key, energy, mood, duration) and draws **spectrograms**. A single Python script with a local web interface, built like its siblings [Image Processor](https://github.com/meteorik-media/Image-Processor) and [Video Processor](https://github.com/meteorik-media/Video-Processor): same look, named settings, recursive folder mode, failures are skipped and counted, and your originals are never touched.

```
song_id  segment  archivo     bpm   tonalidad   energia   mood    inicio  fin    duracion
a        1        loop.wav    140   Dm          7         Dark    00:00   00:14  00:14
b        1        pad.flac    128   C           3         Chill   00:00   03:05  03:05
```

## 🧰 What it does

### Convert
- **To MP3** (320k, 256k, 192k, 128k, V0 or V2, keeping cover art and tags) **or to WAV** (16 or 24 bit, lossless).
- **Keeps the original name**: only the extension changes (`loop.flac` → `loop.wav`). Folder mode mirrors subfolders; name clashes get ` (2)`.
- **Idempotent**: what's already converted is skipped (same file, size, date and settings). Outputs are written to a temp file and renamed when done. Changing the format replaces the previous output of that same file.
- Can watch a folder (`watch`) and convert whatever shows up.

### Analyze → CSV
- Columns: `song_id, segment, archivo, bpm, tonalidad, energia, mood, inicio, fin, duracion`.
- **BPM** and **key** (`Dm`, `Dmin` or Camelot `7A`; sharps or flats; BPM with 0 or 1 decimals).
- **Energy 1–10** from loudness, hit density, brightness and tempo.
- **Mood** in English: Melancholic, Dark, Aggressive, Chill, Happy, Uplifting, Euphoric, Energetic or Neutral, from the major/minor mode and the energy.
- **Start / end / duration** as `mm:ss` (`03:05`). A whole track is `00:00` to its duration.
- **`song_id`** identifies each file (`a`, `b`, … `z`, `aa`, `ab`, …, in analysis order) and **`segment`** numbers its sections (1, 2, 3…; always 1 when not split), so the sections of one song can be grouped.
- **Split into sections** (off by default): energy and mood change over a track, so with `--split auto` each section gets its own row (same file name, own start/end/duration). Auto cuts where loudness, brightness or hit density change, with sections of at least `--min-section` seconds (10). `--split fixed` uses equal chunks of about `--split-seconds` (15). The whole track is analyzed when splitting (the window is ignored).
- The results fill a table on screen as each file finishes; then **Download CSV** or **Save to output** (`analysis.csv`). The CSV opens in Excel. Low BPM/key confidence is highlighted.
- Bulk-friendly: in the file browser use **Select all** (or Ctrl+A), Shift+click for a range, or add a whole folder (subfolders included).

### Spectrogram
- PNG spectrograms with axes and dB legend, for one or many files, shown in a gallery (click to zoom) and saved to `<output>/spectrograms/`.
- Palette (magma, viridis, fire, …), linear/log frequency axis, intensity scale, FFT window, dynamic range, gain, frequency range, image size, combined/separate channels and a **time range** to zoom into a section.
- Pure ffmpeg (`showspectrumpic`): this tab doesn't use numpy.

## 🚀 Usage

**With the interface:** double-click `Audio Processor.bat` (Windows) or run `./start.sh` (macOS/Linux). Your browser opens at `http://127.0.0.1:8766`. Closing the terminal window closes the app.

**From the command line:**

```
python audio_processor.py serve                         # web interface (--port N, --no-open)
python audio_processor.py doctor
python audio_processor.py convert SAMPLES/ -o OUT/                  # to mp3 (default)
python audio_processor.py convert SAMPLES/ -o OUT/ --format wav --wav-bits 24
python audio_processor.py watch SAMPLES/ -o OUT/ --interval 300
python audio_processor.py analyze SAMPLES/ -o analysis.csv --key-format camelot
python audio_processor.py analyze SAMPLES/ -o analysis.csv --split auto      # one row per section
python audio_processor.py spectrogram song.wav -o PNGS/ --color magma --fscale log --from 1:00 --to 1:30
```

`convert` also leaves a `manifest.json` in `OUT/` (everything processed).

## 📋 Requirements

- Python 3.8 or later
- `ffmpeg` and `ffprobe` on the PATH (with `libmp3lame` for MP3 and the `showspectrumpic` filter; `doctor` checks them)
- `numpy` for the Analyze tool: `pip install numpy`

## ⚠️ Known limits

BPM, key, energy and mood are **estimates** made with a lightweight algorithm (numpy only, no AI models). They are good on samples, loops and tracks with a steady beat, and sometimes wrong:

- **Energy and mood are heuristics**, not a trained model: energy blends loudness, hit density, brightness and tempo; mood comes from major/minor mode plus energy (when the key is doubtful it falls back to Chill / Neutral / Energetic). Use them as a guide.
- **Double / half tempo** (e.g. 180 instead of 90) is a genuine ambiguity. Narrow the range in *Analysis* (max BPM 150 forces 90). The default prefers 70–190 with a bias toward ~128.
- **Relative major/minor** (Dm vs F) can't be told apart when the music uses the same notes. The key confidence is shown so you can spot the shaky ones.
- Tracks with tempo changes, free tempo, or long silences give unreliable BPM. Very short clips (a few seconds) are approximate. Silent files get empty cells.
- Only the middle 120 s of each file is analyzed by default (faster); use *Window* = 0 for the whole track. Energy is measured on that same window.
- Tested with synthetic audio; the first real-music batch is still to be tried.
- WAV output carries no cover art (the container doesn't support it).
- Console output is in Spanish only for now (the web interface is bilingual).
- The web interface is for one person on one machine: it has no login and only listens on `127.0.0.1`. Don't expose it to a network.

## 🧪 Tests

```
python -m unittest -v
```

They generate synthetic audio and skip themselves if ffmpeg or numpy aren't available. They cover conversion, analysis, energy/mood, the CSV, idempotency, collisions, broken files, spectrograms and the web server (token and host checks, a full job through the API).
