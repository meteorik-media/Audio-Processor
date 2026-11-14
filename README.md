# Audio Processor v0.1.0

🌐 English | [Versión en español](README-ES.md) | 📝 [Changelog](CHANGELOG.md)

Reads the **BPM, key and duration** of your audio and renames it, and draws **spectrograms**. A single Python script with a local web interface, built like its siblings [Image Processor](https://github.com/meteorik-gaming/Image-Processor) and Video Processor: same look, named settings, recursive folder mode, failures are skipped and counted, and your originals are never touched.

```
my_sample.wav   →   my_sample__140bpm__Dm__03m05s.wav     (original format, a renamed copy)
my_sample.wav   →   my_sample__140bpm__Dm__03m05s.mp3     (converted to mp3)
```

## 🧰 What it does

### Rename & analyze
- **Detects BPM, key (major/minor) and duration** and builds `original_name__140bpm__Dm__03m05s.ext`.
- **Output in the original format** (a byte-for-byte copy under the new name, no re-encoding) **or converted to MP3** (320k, 256k, 192k, 128k, V0 or V2). Converting keeps cover art and tags and can write the BPM and key into the ID3 tags (`TBPM`, `TKEY`).
- **Key notation**: `Dm` (default), `Dmin` or Camelot `7A`; sharps (`F#`) or flats (`Gb`). BPM with 0 or 1 decimals.
- **Preview** (`--dry-run`, "Preview" button) analyzes and shows the new names without writing anything.
- **Results** with a confidence value for BPM and key, and `analysis.csv` (opens in Excel). Low confidence is highlighted so you know what to double-check.
- Folder mode mirrors subfolders; reprocessing never stacks suffixes (`name__140bpm__Dm__03m05s` is cleaned before renaming again); name clashes get ` (2)`.
- **Idempotent**: what's already processed is skipped (same file, size, date and settings). Outputs are written to a temp file and renamed when done.

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
python audio_processor.py run SAMPLES/ -o OUT/                      # original format
python audio_processor.py run SAMPLES/ -o OUT/ --format mp3 --key-format camelot
python audio_processor.py run SAMPLES/ -o OUT/ --dry-run            # preview names only
python audio_processor.py watch SAMPLES/ -o OUT/ --interval 300
python audio_processor.py spectrogram song.wav -o PNGS/ --color magma --fscale log --from 1:00 --to 1:30
```

`OUT/` also gets `manifest.json` (everything processed) and `analysis.csv`.

## 📋 Requirements

- Python 3.8 or later
- `ffmpeg` and `ffprobe` on the PATH (with `libmp3lame` for MP3 and the `showspectrumpic` filter; `doctor` checks them)
- `numpy` for BPM/key analysis: `pip install numpy`

## ⚠️ Known limits

BPM and key are **estimates** made with a lightweight algorithm (numpy only, no AI models). They are good on samples, loops and tracks with a steady beat, and sometimes wrong:

- **Double / half tempo** (e.g. 180 instead of 90) is a genuine ambiguity. Narrow the range in *Analysis* (max BPM 150 forces 90). The default prefers 70–190 with a bias toward ~128.
- **Relative major/minor** (Dm vs F) can't be told apart when the music uses the same notes. The key confidence is shown so you can spot the shaky ones.
- Tracks with tempo changes, free tempo, or long silences give unreliable BPM. Very short clips (a few seconds) are approximate.
- Only the middle 120 s of each file is analyzed by default (faster); use *Window* = 0 for the whole track.
- Tested with synthetic audio; the first real-music batch is still to be tried, so use *Preview* first.
- Console output is in Spanish only for now (the web interface is bilingual).
- The web interface is for one person on one machine: it has no login and only listens on `127.0.0.1`. Don't expose it to a network.

## 🧪 Tests

```
python -m unittest -v
```

They generate synthetic audio and skip themselves if ffmpeg or numpy aren't available. They cover naming, analysis, mp3 tags, idempotency, collisions, broken files, spectrograms and the web server (token and host checks, a full job through the API).
