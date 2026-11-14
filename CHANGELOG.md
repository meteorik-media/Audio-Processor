# Changelog

🌐 English | [Versión en español](CHANGELOG-ES.md)

All notable changes to this project are documented here.

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
