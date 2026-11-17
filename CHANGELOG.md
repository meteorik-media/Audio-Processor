# Changelog

🌐 English | [Versión en español](CHANGELOG-ES.md)

All notable changes to this project are documented here.

## v0.2.0 — Convert, and Analyze → CSV

- **Breaking:** the "Rename & analyze" tool (`run`) is gone. It's replaced by two separate tools
- **Convert** (`convert`, `watch`): to MP3 (320k–128k, V0, V2) or WAV (16/24 bit), keeping the original file name (only the extension changes)
- **Analyze → CSV** (`analyze`): `archivo, bpm, tonalidad, energia, mood, inicio, fin, duracion` — BPM, key, energy 1–10, mood (English labels), start/end and duration as `mm:ss:ms`. Live table in the web interface, **Download CSV** or **Save to output**, and the same CSV from the command line
- **Split into sections** (`--split auto|fixed`): energy and mood change over a track, so each section gets its own row (same `archivo`, own `inicio`/`fin`/`duracion`). *Auto* cuts where loudness, brightness or hit density change (sections last at least `--min-section`, 10 s by default); *fixed* uses equal chunks of about `--split-seconds` (15 s). Off by default: one row per track, `inicio` = `00:00:000`, `fin` = duration
- File browser: **Select all** (and Ctrl+A) plus Shift+click range selection; the web limit for bulk lists goes from 500 to 5000 files
- Removed: file renaming, ID3 BPM/key tags, `--dry-run`, the old `analysis.csv` written by the converter

## v0.1.0 — First release

- **Rename & analyze** (`run`, `watch`): BPM, key and duration → `name__140bpm__Dm__03m05s.ext`
- Output in the original format (renamed copy) or converted to MP3 (320k–128k, V0, V2) keeping cover art and tags, with optional BPM/key ID3 tags
- Key as `Dm`, `Dmin` or Camelot; sharps or flats; BPM with 0 or 1 decimals; BPM range and analysis window settings
- Confidence for BPM and key, `analysis.csv`, `manifest.json`, preview mode (`--dry-run`)
- **Spectrogram** (`spectrogram`): PNG with legend, palette, frequency/intensity scales, FFT window, dynamic range, gain, frequency and time range
- Local web interface (`serve`) with two tabs, folder browser, live progress, results table and spectrogram gallery, English/Spanish.
  Standard library only (plus numpy for analysis), bound to `127.0.0.1`, guarded by a per-session token and host check
- Recursive folder mode; failures are skipped and counted; idempotent; atomic writes; name clashes get ` (2)`
- `Audio Processor.bat` and `start.sh` launchers, `doctor` command
- Unit and integration tests using synthetic audio
- MIT license
