#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audio Processor — convierte audio a mp3/wav, lo analiza a un CSV (BPM, tonalidad, energía, mood,
duración) y genera espectrogramas.

    archivo   bpm  tonalidad  energia  mood  duracion
    loop.wav  140  Dm         7        Dark  00:14:203

Los originales nunca se modifican. Necesita ffmpeg/ffprobe en el PATH; el análisis además usa numpy.
Convertir es idempotente: lo ya procesado se salta.

Uso rápido:
    python audio_processor.py serve          (interfaz web local, la forma más cómoda)
    python audio_processor.py doctor
    python audio_processor.py convert SAMPLES/ -o SALIDA/ --format wav
    python audio_processor.py analyze SAMPLES/ -o analysis.csv
    python audio_processor.py spectrogram cancion.wav -o PNGS/ --color magma
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

__version__ = "0.2.0"

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aif", ".aiff", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".alac"}
MANIFEST_NAME = "manifest.json"
CSV_NAME = "analysis.csv"
SPEC_DIR_NAME = "spectrograms"

# Valores por defecto de cada herramienta (la web los lee de aquí, así CLI y web nunca se desincronizan).
CONVERT_DEFAULTS = {
    "format": "mp3",           # mp3 | wav
    "mp3_quality": "320k",     # 320k 256k 192k 128k v0 v2
    "wav_bits": 16,            # 16 | 24
}
ANALYZE_DEFAULTS = {
    "key_format": "short",     # short (Dm) | long (Dmin) | camelot (7A)
    "accidental": "sharp",     # sharp (F#) | flat (Gb)
    "bpm_min": 70.0,
    "bpm_max": 190.0,
    "bpm_decimals": 0,         # 0 -> 140 ; 1 -> 140.5
    "analyze_seconds": 120.0,  # 0 = pista completa (se ignora al fragmentar: ahí se analiza todo)
    "split": "off",            # off = una fila por archivo | auto = por cambios | fixed = ventanas iguales
    "min_section": 10.0,       # s: duración mínima de una sección (split auto)
    "split_seconds": 15.0,     # s: tamaño aproximado de cada sección (split fixed)
}
SPLIT_MODES = ("off", "auto", "fixed")
MP3_QUALITIES = ("320k", "256k", "192k", "128k", "v0", "v2")
WAV_BITS = (16, 24)
CSV_COLUMNS = ("archivo", "bpm", "tonalidad", "energia", "mood", "inicio", "fin", "duracion")
CSV_FIELDS = ("file", "bpm", "key", "energy", "mood", "start", "end", "duration")  # claves de cada fila, en el mismo orden
SPEC_DEFAULTS = {
    "width": 1920, "height": 1080,
    "color": "magma", "scale": "log", "fscale": "lin", "win": "hann",
    "drange": 120, "gain": 1, "fmin": 0, "fmax": 0,
    "mode": "combined", "legend": True, "start": "", "end": "",
}
SPEC_COLORS = ("channel", "intensity", "rainbow", "moreland", "nebulae", "fire", "fiery", "fruit", "cool",
               "magma", "green", "viridis", "plasma", "cividis", "terrain")
SPEC_SCALES = ("log", "sqrt", "cbrt", "lin", "4thrt", "5thrt")
SPEC_FSCALES = ("lin", "log")
SPEC_WINS = ("hann", "hamming", "blackman", "bartlett", "rect", "nuttall", "blackman_harris", "kaiser", "flattop")
SPEC_MODES = ("combined", "separate")

NOTES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOTES_FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
CAMELOT_MAJOR = {0: 8, 7: 9, 2: 10, 9: 11, 4: 12, 11: 1, 6: 2, 1: 3, 8: 4, 3: 5, 10: 6, 5: 7}
CAMELOT_MINOR = {9: 8, 4: 9, 11: 10, 6: 11, 1: 12, 8: 1, 3: 2, 10: 3, 5: 4, 0: 5, 7: 6, 2: 7}

# Perfiles tonales (Krumhansl-Kessler y Temperley); se promedian las correlaciones de ambos.
KK_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
KK_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
TP_MAJOR = [5.0, 2.0, 3.5, 2.0, 4.5, 4.0, 2.0, 4.5, 2.0, 3.5, 1.5, 4.0]
TP_MINOR = [5.0, 2.0, 3.5, 4.5, 2.0, 4.0, 2.0, 4.5, 3.5, 2.0, 1.5, 4.0]


# ───────────────────────── utilidades ─────────────────────────

def tool(name):
    """Ruta de ffmpeg/ffprobe: variable de entorno FFMPEG/FFPROBE o el PATH."""
    return os.environ.get(name.upper()) or shutil.which(name)


def to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_time(text):
    """'90' -> 90, '1:30' -> 90, '1:02:03' -> 3723, '30s'/'2m'/'1h' -> segundos; ''/None -> None."""
    if text is None or str(text).strip() == "":
        return None
    s = str(text).strip().lower()
    if ":" in s:
        try:
            parts = [float(p) for p in s.split(":")]
        except ValueError:
            raise ValueError(f"tiempo no válido: {text!r} (ej.: 90, 1:30, 2m)")
        if len(parts) > 3:
            raise ValueError(f"tiempo no válido: {text!r}")
        total = 0.0
        for p in parts:
            total = total * 60 + p
        return total
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([smh]?)", s)
    if not m:
        raise ValueError(f"tiempo no válido: {text!r} (ej.: 90, 1:30, 2m)")
    return float(m.group(1)) * {"s": 1, "m": 60, "h": 3600}[m.group(2) or "s"]


def fmt_hms(seconds):
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def duration_label(seconds):
    """mm:ss:ms (ms con 3 dígitos); los minutos pueden pasar de 99. 185.123 -> '03:05:123'."""
    total_ms = int(round(max(0.0, seconds) * 1000))
    return f"{total_ms // 60000:02d}:{total_ms // 1000 % 60:02d}:{total_ms % 1000:03d}"


def fmt_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def now_iso():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def atomic_write_text(path, text):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def clean_err(text, limit=300):
    """Una sola línea legible a partir de la salida de error de ffmpeg/ffprobe."""
    return re.sub(r"\s+", " ", text or "").strip()[-limit:]


def has_filter(name):
    ff = tool("ffmpeg")
    if not ff:
        return False
    out = subprocess.run([ff, "-hide_banner", "-filters"], capture_output=True, text=True, errors="replace").stdout
    return re.search(rf"\s{re.escape(name)}\s", out) is not None


def has_numpy():
    try:
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


def probe(path):
    """Duración y datos del primer flujo de audio, vía ffprobe."""
    fp = tool("ffprobe")
    proc = subprocess.run([fp, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError("ffprobe no pudo leer el archivo: " + clean_err(proc.stderr))
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams", [])
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not audio:
        raise RuntimeError("el archivo no tiene pista de audio")
    cover = next((s for s in streams if s.get("codec_type") == "video"
                  and s.get("disposition", {}).get("attached_pic") == 1), None)
    duration = to_float(data.get("format", {}).get("duration")) or to_float(audio.get("duration"))
    return {"duration": duration, "sample_rate": int(to_float(audio.get("sample_rate"))),
            "channels": int(to_float(audio.get("channels"))), "codec": audio.get("codec_name"),
            "cover_index": cover.get("index") if cover else None}


def show_progress(label, pct, state):
    if os.environ.get("AP_PROGRESS") == "1":  # lo usa la interfaz web: líneas fáciles de leer
        if pct != state.get("last_pct"):
            state["last_pct"] = pct
            print(f"@progress {pct} {label}", flush=True)
    elif sys.stdout.isatty():
        print(f"\r  {label}  {pct:3d}%", end="", flush=True)
    elif pct // 25 > state.get("last", -1):
        state["last"] = pct // 25
        print(f"  {label}  {pct}%", flush=True)


def run_ffmpeg(cmd, out_duration, label):
    err_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err_file, text=True, errors="replace")
    state = {}
    for line in proc.stdout:
        if line.startswith(("out_time_us=", "out_time_ms=")):
            try:
                us = int(line.split("=", 1)[1])
            except ValueError:
                continue
            if out_duration > 0:
                show_progress(label, max(0, min(99, int(us / 1e6 / out_duration * 100))), state)
    proc.stdout.close()
    rc = proc.wait()
    err_file.seek(0)
    err = err_file.read()
    err_file.close()
    if sys.stdout.isatty():
        print("\r" + " " * 70 + "\r", end="")
    return rc, err


# ───────────────────────── análisis: BPM y tonalidad ─────────────────────────
# Solo numpy. No pretende ser un analizador de estudio: es una estimación buena y rápida para
# samples, loops y temas de ritmo estable. Todo se ve en el log y en analysis.csv para poder revisarlo.

ANALYSIS_SR = 22050


def decode_mono(path, start=0.0, dur=0.0, sr=ANALYSIS_SR):
    """Audio como float32 mono a `sr` Hz, leyendo solo la ventana pedida."""
    import numpy as np
    cmd = [tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "pipe:1"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg no pudo decodificar: " + clean_err(proc.stderr.decode("utf-8", "replace")))
    return np.frombuffer(proc.stdout, dtype="<f4").astype(np.float32)


def _stft_mag_blocks(y, n_fft, hop, block=256):
    import numpy as np
    if len(y) < n_fft:
        y = np.pad(y, (0, n_fft - len(y)))
    window = np.hanning(n_fft).astype(np.float32)
    n_frames = 1 + (len(y) - n_fft) // hop
    offsets = np.arange(n_fft)[None, :]
    for i0 in range(0, n_frames, block):
        idx = np.arange(i0, min(n_frames, i0 + block))[:, None] * hop + offsets
        yield np.abs(np.fft.rfft(y[idx] * window, axis=1)).astype(np.float32)


def onset_envelope(y, sr=ANALYSIS_SR, n_fft=1024, hop=256):
    """Flujo espectral por bandas (en dB): cuánto 'golpe nuevo' hay en cada instante. Devuelve (env, fps)."""
    import numpy as np
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    edges = np.geomspace(30, 10000, 33)
    band = np.digitize(freqs, edges) - 1
    weights = np.zeros((len(freqs), 32), np.float32)
    for b in range(32):
        weights[band == b, b] = 1.0
    parts = [10.0 * np.log10((mag ** 2) @ weights + 1e-10) for mag in _stft_mag_blocks(y, n_fft, hop)]
    spec = np.concatenate(parts, axis=0)
    spec = np.maximum(spec, spec.max() - 80.0)
    flux = np.maximum(np.diff(spec, axis=0), 0.0).mean(axis=1)
    fps = sr / hop
    win = max(3, int(fps))  # quita la media móvil de ~1 s: se queda con los golpes, no con el volumen
    flux = flux - np.convolve(flux, np.ones(win) / win, mode="same")
    return np.maximum(flux, 0.0), fps


def refine_with_comb(env, fps, bpm0, span=3.0, step=0.02):
    """Afina el BPM probando peines de pulsos (con su fase) alrededor de la estimación: usa todos los
    pulsos de la pista, así que es mucho más fino que la resolución del espectro en clips cortos."""
    import numpy as np
    sigma = max(1.0, 0.015 * fps)  # ~15 ms de tolerancia por pulso
    k = np.arange(-int(3 * sigma), int(3 * sigma) + 1)
    sm = np.convolve(env, np.exp(-0.5 * (k / sigma) ** 2), mode="same")
    n = len(sm)
    best_bpm, best_val = bpm0, -1.0
    vals = []
    cands = np.arange(max(1.0, bpm0 - span), bpm0 + span + 1e-9, step)
    for bpm in cands:
        period = fps * 60.0 / bpm
        phases = np.arange(0.0, period, max(0.5, period / 48.0))
        n_beats = int((n - 1 - period) // period)
        if n_beats < 4:
            vals.append(0.0)
            continue
        pos = phases[:, None] + np.arange(n_beats)[None, :] * period
        v = float(np.interp(pos, np.arange(n), sm).sum(axis=1).max() / n_beats)
        vals.append(v)
    vals = np.asarray(vals)
    i = int(np.argmax(vals))
    if 0 < i < len(vals) - 1 and vals[i] > 0:  # interpolación parabólica del máximo
        a, b, c = vals[i - 1], vals[i], vals[i + 1]
        d = a - 2 * b + c
        shift = 0.5 * (a - c) / d if d < 0 else 0.0
        return float(cands[i] + shift * step)
    return float(cands[i]) if vals[i] > best_val else bpm0


def estimate_tempo(env, fps, bpm_min=70.0, bpm_max=190.0, prior_center=128.0, prior_sigma=0.9):
    """BPM a partir del espectro de la envolvente de golpes. Devuelve (bpm, confianza 0..1)."""
    import numpy as np
    n = len(env)
    if n < int(fps * 3) or float(env.max()) <= 1e-6:
        return None, 0.0
    nfft = 1 << int(np.ceil(np.log2(n * 8)))
    mag = np.abs(np.fft.rfft((env - env.mean()) * np.hanning(n), nfft))
    hz = np.arange(len(mag)) * fps / nfft
    harmonics = ((1, 1.0), (2, 0.7), (3, 0.5), (4, 0.4))

    def score(bpm):
        f0 = np.asarray(bpm, dtype=float) / 60.0
        return sum(w * np.interp(h * f0, hz, mag, right=0.0) for h, w in harmonics)

    grid = np.arange(bpm_min, bpm_max + 0.05, 0.1)
    raw = score(grid)
    prior = np.exp(-0.5 * (np.log2(grid / prior_center) / prior_sigma) ** 2)
    weighted = raw * prior
    best = int(np.argmax(weighted))
    bpm = refine_with_comb(env, fps, float(grid[best]))
    # confianza: cuánto le gana al mejor rival que NO sea un múltiplo/submúltiplo suyo
    related = np.zeros(len(grid), bool)
    for ratio in (0.5, 2.0, 1 / 3, 3.0, 2 / 3, 1.5, 0.25, 4.0):
        related |= np.abs(grid / bpm - ratio) < 0.04 * ratio
    related |= np.abs(grid / bpm - 1.0) < 0.06
    rival = float(weighted[~related].max()) if (~related).any() else 0.0
    conf = float(np.clip(1.0 - rival / max(float(weighted[best]), 1e-12), 0.0, 1.0))
    return bpm, conf


def chroma_vector(y, sr=ANALYSIS_SR, n_fft=8192, hop=4096, fmin=55.0, fmax=4000.0):
    """Perfil de 12 notas a partir de los picos espectrales, con corrección de afinación."""
    import numpy as np
    bin_hz = sr / n_fft
    lo, hi = int(fmin / bin_hz), int(fmax / bin_hz)
    freqs_all, amps_all = [], []
    for mag in _stft_mag_blocks(y, n_fft, hop, block=64):
        m = mag[:, lo:hi]
        a, b, c = m[:, :-2], m[:, 1:-1], m[:, 2:]
        peak = (b > a) & (b >= c) & (b > 0.03 * m.max(axis=1, keepdims=True))
        denom = a - 2 * b + c
        with np.errstate(divide="ignore", invalid="ignore"):
            delta = np.where(denom < 0, 0.5 * (a - c) / denom, 0.0)
        rows, cols = np.nonzero(peak)
        freqs_all.append((cols + 1 + lo + delta[rows, cols]) * bin_hz)
        amps_all.append(b[rows, cols] - 0.25 * (a[rows, cols] - c[rows, cols]) * delta[rows, cols])
    if not freqs_all:
        return None, 0.0
    freqs, amps = np.concatenate(freqs_all), np.concatenate(amps_all)
    if len(freqs) == 0 or amps.max() <= 0:
        return None, 0.0
    amps = (amps / amps.max()) ** 0.5
    midi = 69.0 + 12.0 * np.log2(freqs / 440.0)
    dev = midi - np.round(midi)
    hist, edges = np.histogram(dev, bins=50, range=(-0.5, 0.5), weights=amps)
    hist = np.convolve(np.r_[hist[-2:], hist, hist[:2]], np.ones(5) / 5, mode="same")[2:-2]
    tuning = float((edges[int(np.argmax(hist))] + edges[int(np.argmax(hist)) + 1]) / 2)
    pitch_class = np.mod(np.round(midi - tuning).astype(int), 12)
    chroma = np.bincount(pitch_class, weights=amps, minlength=12).astype(float)
    return chroma, tuning


def estimate_key(chroma):
    """(tónica 0..11, 'major'|'minor', confianza 0..1) o None. Confianza = margen sobre la 2.ª mejor tonalidad."""
    import numpy as np
    if chroma is None or float(np.sum(chroma)) <= 0:
        return None
    chroma = np.asarray(chroma, float)
    scores = []
    for mode, profiles in (("major", (KK_MAJOR, TP_MAJOR)), ("minor", (KK_MINOR, TP_MINOR))):
        for tonic in range(12):
            r = np.mean([np.corrcoef(chroma, np.roll(p, tonic))[0, 1] for p in profiles])
            scores.append((float(r), tonic, mode))
    scores.sort(reverse=True)
    best, second = scores[0], scores[1]
    conf = float(np.clip((best[0] - second[0]) / 0.25, 0.0, 1.0))
    return best[1], best[2], conf


def spectral_centroid(y, sr=ANALYSIS_SR, n_fft=2048):
    """Centroide espectral medio en Hz (qué tan 'brillante' es el audio)."""
    import numpy as np
    power, count = None, 0
    for mag in _stft_mag_blocks(y, n_fft, n_fft, block=128):
        p = (mag ** 2).sum(axis=0)
        power = p if power is None else power + p
        count += len(mag)
    if power is None or float(power.sum()) <= 0:
        return 0.0
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    return float((freqs * power).sum() / power.sum())


def estimate_energy(y, env, bpm):
    """Energía 1–10 (heurística): volumen (RMS), densidad de golpes, brillo y tempo. y SIN normalizar."""
    import numpy as np
    rms_db = 20.0 * np.log10(float(np.sqrt(np.mean(y.astype(np.float64) ** 2))) + 1e-9)
    loud = float(np.clip((rms_db + 32.0) / 22.0, 0.0, 1.0))                 # -32 dBFS -> 0 ... -10 dBFS -> 1
    onset = float(np.clip(float(np.mean(env)) / 2.0, 0.0, 1.0))             # golpes nuevos por instante
    centroid = spectral_centroid(y)
    bright = float(np.clip(np.log2(max(centroid, 1.0) / 300.0) / np.log2(4000.0 / 300.0), 0.0, 1.0))
    tempo = float(np.clip((bpm - 70.0) / 105.0, 0.0, 1.0)) if bpm else 0.5
    score = 0.35 * loud + 0.25 * onset + 0.2 * bright + 0.2 * tempo
    return int(np.clip(1 + round(9 * score), 1, 10))


def mood_label(mode, key_conf, energy):
    """Etiqueta de ánimo (en inglés) a partir del modo mayor/menor y la energía. Es una heurística."""
    if energy is None:
        return None
    if mode is None or key_conf < 0.1:  # tonalidad dudosa: no nos fiamos del modo
        return "Chill" if energy <= 3 else "Energetic" if energy >= 8 else "Neutral"
    if mode == "minor":
        return "Melancholic" if energy <= 3 else "Dark" if energy <= 6 else "Aggressive"
    return "Chill" if energy <= 3 else "Happy" if energy <= 5 else "Uplifting" if energy <= 7 else "Euphoric"


def analyze_audio(path, duration, opts):
    """Analiza un archivo. Devuelve dict con bpm, key, energía, mood y confianzas (None si no se pudo estimar)."""
    import numpy as np
    window = float(opts.get("analyze_seconds") or 0)
    start, length = 0.0, 0.0
    if window and duration > window:
        start, length = (duration - window) / 2.0, window
    return analyze_samples(decode_mono(path, start, length), opts)


def analyze_samples(y, opts):
    """Analiza un tramo ya decodificado (mono, ANALYSIS_SR). Mismo resultado que analyze_audio."""
    import numpy as np
    result = {"bpm": None, "bpm_conf": 0.0, "tonic": None, "mode": None, "key_conf": 0.0,
              "energy": None, "mood": None, "analyzed_seconds": round(len(y) / ANALYSIS_SR, 1)}
    if len(y) < ANALYSIS_SR * 1.0 or float(np.abs(y).max()) < 1e-4:
        return result  # muy corto o silencio
    raw = y
    y = y / float(np.abs(y).max())
    env, fps = onset_envelope(y)
    bpm, conf = estimate_tempo(env, fps, float(opts["bpm_min"]), float(opts["bpm_max"]))
    result["bpm"], result["bpm_conf"] = (round(bpm, 2) if bpm else None), round(conf, 2)
    chroma, _ = chroma_vector(y)
    key = estimate_key(chroma)
    if key:
        result["tonic"], result["mode"], result["key_conf"] = key[0], key[1], round(key[2], 2)
    result["energy"] = estimate_energy(raw, env, bpm)
    result["mood"] = mood_label(result["mode"], result["key_conf"], result["energy"])
    return result


def section_cuts(y, mode, min_len, window, sr=ANALYSIS_SR):
    """Instantes (s) donde partir la pista en secciones. `fixed`: trozos iguales de ~`window` s.
    `auto`: donde cambian el volumen, el brillo o la densidad de golpes (cada sección dura al menos `min_len`)."""
    import numpy as np
    total = len(y) / sr
    if mode == "fixed":
        n = max(1, int(round(total / max(window, 1.0))))
        return [total * i / n for i in range(1, n)]
    n = int(total)
    min_len = max(float(min_len), 2.0)
    if n < 2 * min_len:
        return []
    env, fps = onset_envelope(y)
    feats = np.zeros((n, 3))
    for i in range(n):
        blk = y[i * sr:(i + 1) * sr].astype(np.float64)
        rms_db = 20.0 * np.log10(float(np.sqrt(np.mean(blk ** 2))) + 1e-9)
        a, b = int(i * fps), max(int(i * fps) + 1, int((i + 1) * fps))
        feats[i] = (max(rms_db, -60.0) / 6.0,                                   # 6 dB = 1 unidad
                    np.log2(max(spectral_centroid(blk), 50.0)) / 0.5,           # media octava = 1 unidad
                    float(np.mean(env[a:b])) / 0.5 if a < len(env) else 0.0)    # densidad de golpes
    w = max(3, int(min_len * 0.6))
    score = np.zeros(n)
    for t in range(2, n - 1):
        prev, nxt = feats[max(0, t - w):t], feats[t:t + w]
        if len(prev) >= 2 and len(nxt) >= 2:
            score[t] = float(np.linalg.norm(nxt.mean(axis=0) - prev.mean(axis=0)))
    cuts = []
    for t in np.argsort(-score):
        if score[t] < 1.0:
            break
        if t < min_len or total - t < min_len or any(abs(t - c) < min_len for c in cuts):
            continue
        cuts.append(float(t))
    return sorted(cuts)


# ───────────────────────── etiquetas del análisis ─────────────────────────

def key_label(tonic, mode, key_format="short", accidental="sharp"):
    if tonic is None or mode is None:
        return "NA"
    if key_format == "camelot":
        return f"{(CAMELOT_MAJOR if mode == 'major' else CAMELOT_MINOR)[tonic]}{'B' if mode == 'major' else 'A'}"
    note = (NOTES_FLAT if accidental == "flat" else NOTES_SHARP)[tonic]
    if key_format == "long":
        return note + ("maj" if mode == "major" else "min")
    return note + ("" if mode == "major" else "m")


def bpm_label(bpm, decimals=0):
    if bpm is None:
        return "NA"
    return f"{bpm:.1f}".rstrip("0").rstrip(".") if decimals else str(int(round(bpm)))


def analysis_row(path, analysis, duration, opts, start=0.0, end=None):
    """Una fila del CSV/tabla (pista completa o una sección start–end). Lo que no se pudo estimar queda vacío."""
    a = analysis
    end = duration if end is None else end
    return {"file": Path(path).name,
            "start": duration_label(start), "end": duration_label(end),
            "bpm": bpm_label(a["bpm"], int(opts.get("bpm_decimals") or 0)) if a["bpm"] else "",
            "key": key_label(a["tonic"], a["mode"], opts.get("key_format", "short"), opts.get("accidental", "sharp"))
            if a["tonic"] is not None else "",
            "energy": a["energy"] if a["energy"] is not None else "",
            "mood": a["mood"] or "",
            "duration": duration_label(end - start),
            "bpm_conf": a["bpm_conf"], "key_conf": a["key_conf"], "error": ""}


def analyze_file(path, opts):
    """Filas del archivo: una, o varias (una por sección) si `split` no es off."""
    info = probe(path)
    duration = info["duration"]
    mode = opts.get("split", "off")
    if mode == "off":
        return [analysis_row(path, analyze_audio(path, duration, opts), duration, opts)]
    y = decode_mono(path)
    total = duration or len(y) / ANALYSIS_SR
    cuts = section_cuts(y, mode, float(opts.get("min_section") or 10.0), float(opts.get("split_seconds") or 15.0)) \
        if len(y) >= ANALYSIS_SR else []
    edges = [0.0] + [c for c in cuts if 0 < c < total] + [total]
    rows = []
    for a, b in zip(edges, edges[1:]):
        seg = y[int(round(a * ANALYSIS_SR)):int(round(b * ANALYSIS_SR))]
        rows.append(analysis_row(path, analyze_samples(seg, opts), total, opts, a, b))
    return rows


def csv_text(rows):
    """CSV (archivo, bpm, tonalidad, energia, mood, duracion). Las filas con error no se incluyen."""
    import io
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_COLUMNS)
    for r in rows:
        if not r.get("error"):
            w.writerow([r.get(k, "") for k in CSV_FIELDS])
    return buf.getvalue()


def write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:  # Excel lo abre bien; newline="" evita CRCRLF en Windows
        f.write(csv_text(rows))
    os.replace(tmp, path)


# ───────────────────────── manifest y salidas ─────────────────────────

def load_manifest(out_dir):
    path = out_dir / MANIFEST_NAME
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data.get("entries"), dict):
                return data
        except (OSError, ValueError):
            backup = path.with_name(f"{MANIFEST_NAME}.corrupto-{int(time.time())}")
            shutil.copy2(path, backup)
            print(f"! manifest.json ilegible, copia guardada en {backup.name}; se empieza de cero")
    return {"version": 2, "tool": f"audio-processor {__version__}", "entries": {}}


def save_manifest(out_dir, manifest):
    manifest["tool"] = f"audio-processor {__version__}"
    atomic_write_text(out_dir / MANIFEST_NAME, json.dumps(manifest, indent=2, ensure_ascii=False))


def collect_files(inputs, out_dir=None):
    out_res = out_dir.resolve() if out_dir else None
    found = []
    for inp in inputs:
        p = Path(inp)
        if p.is_file():
            if p.suffix.lower() in AUDIO_EXTS:
                found.append((p.parent, p, False))
            else:
                print(f"! Ignorado (no parece audio): {p}")
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if (f.is_file() and f.suffix.lower() in AUDIO_EXTS and not f.name.startswith(".")
                        and (out_res is None or out_res not in f.resolve().parents)):
                    found.append((p, f, True))
        else:
            print(f"! No existe: {p}")
    return found


def entry_is_current(entry, st, settings, out_dir):
    out = (entry or {}).get("output")
    return bool(entry and entry.get("status") == "ok" and out
                and entry.get("size") == st.st_size and abs(entry.get("mtime", 0) - st.st_mtime) < 1
                and entry.get("settings") == settings and (out_dir / out["file"]).is_file())


def unique_path(out_dir, folder, base, ext, key, manifest):
    """folder/base.ext; si ya existe y es de OTRO origen, base (2).ext, base (3).ext…"""
    owners = {e["output"]["file"]: k for k, e in manifest["entries"].items() if e.get("output")}
    n = 1
    while True:
        path = folder / f"{base}{'' if n == 1 else f' ({n})'}{ext}"
        if not path.exists() or owners.get(path.relative_to(out_dir).as_posix()) == key:
            return path
        n += 1


def settings_from(args):
    """Ajustes de conversión (CLI o web), validados."""
    s = dict(CONVERT_DEFAULTS)
    for k in s:
        v = getattr(args, k, None)
        if v is not None:
            s[k] = v
    s["wav_bits"] = int(s["wav_bits"])
    if s["format"] not in ("mp3", "wav"):
        raise ValueError("--format debe ser mp3 o wav")
    if s["mp3_quality"] not in MP3_QUALITIES:
        raise ValueError(f"--mp3-quality debe ser una de: {', '.join(MP3_QUALITIES)}")
    if s["wav_bits"] not in WAV_BITS:
        raise ValueError("--wav-bits debe ser 16 o 24")
    return s


def analysis_settings_from(args):
    """Ajustes del análisis (CLI o web), validados."""
    s = dict(ANALYZE_DEFAULTS)
    for k in s:
        v = getattr(args, k, None)
        if v is not None:
            s[k] = v
    s["bpm_decimals"] = int(s["bpm_decimals"])
    s["bpm_min"], s["bpm_max"], s["analyze_seconds"] = float(s["bpm_min"]), float(s["bpm_max"]), float(s["analyze_seconds"])
    if s["key_format"] not in ("short", "long", "camelot"):
        raise ValueError("--key-format debe ser short, long o camelot")
    if s["accidental"] not in ("sharp", "flat"):
        raise ValueError("--accidental debe ser sharp o flat")
    if s["bpm_decimals"] not in (0, 1):
        raise ValueError("--bpm-decimals debe ser 0 o 1")
    s["min_section"], s["split_seconds"] = float(s["min_section"]), float(s["split_seconds"])
    if s["split"] not in SPLIT_MODES:
        raise ValueError("--split debe ser off, auto o fixed")
    if s["min_section"] < 2 or s["split_seconds"] < 2:
        raise ValueError("las secciones deben durar al menos 2 s")
    if s["analyze_seconds"] < 0:
        raise ValueError("--analyze-seconds no puede ser negativo")
    if not 20 <= s["bpm_min"] < s["bpm_max"] <= 400:
        raise ValueError("rango de BPM no válido (mín. 20, máx. 400, y mín < máx)")
    return s


def convert_audio(src, dst, info, settings, label):
    cmd = [tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-v", "error", "-progress", "pipe:1", "-nostats",
           "-i", str(src), "-map", "0:a:0"]
    if settings["format"] == "mp3":
        if info.get("cover_index") is not None:
            cmd += ["-map", f"0:{info['cover_index']}", "-c:v", "copy"]
        cmd += ["-map_metadata", "0", "-c:a", "libmp3lame"]
        q = settings["mp3_quality"]
        cmd += ["-q:a", q[1:]] if q.startswith("v") else ["-b:a", q]
        if info.get("sample_rate", 0) > 48000:
            cmd += ["-ar", "48000"]
        if info.get("channels", 2) > 2:
            cmd += ["-ac", "2"]
        cmd += ["-id3v2_version", "3", "-write_id3v1", "1", "-f", "mp3", str(dst)]
    else:  # wav: sin carátula (el contenedor no la admite), con la frecuencia de muestreo original
        cmd += ["-map_metadata", "0", "-c:a", "pcm_s24le" if settings["wav_bits"] == 24 else "pcm_s16le",
                "-f", "wav", str(dst)]
    rc, err = run_ffmpeg(cmd, info["duration"], label)
    if rc != 0:
        raise RuntimeError("ffmpeg falló: " + clean_err(err, 500))


# ───────────────────────── proceso principal ─────────────────────────

def process_file(src, rel, key, settings, out_dir, manifest, label):
    info = probe(src)
    folder = out_dir / rel.parent
    folder.mkdir(parents=True, exist_ok=True)
    final = unique_path(out_dir, folder, src.stem, "." + settings["format"], key, manifest)
    tmp = final.with_name(final.name + ".part")
    try:
        convert_audio(src, tmp, info, settings, f"{label} {src.stem}")
        os.replace(tmp, final)
    finally:
        if tmp.exists():
            tmp.unlink()
    return {"duration": info["duration"], "final": final}


def convert_once(args):
    out_dir = Path(args.output)
    settings = settings_from(args)
    if "libmp3lame" not in subprocess.run(
            [tool("ffmpeg"), "-hide_banner", "-encoders"], capture_output=True, text=True, errors="replace").stdout \
            and settings["format"] == "mp3":
        print("✗ Tu ffmpeg no trae el codificador libmp3lame (necesario para convertir a mp3).", file=sys.stderr)
        return 2
    files = collect_files(args.inputs, out_dir)
    if not files:
        print("No hay audio que procesar.")
        return 0
    multi_input = len(args.inputs) > 1
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(out_dir)

    done = skipped = failed = waiting = 0
    t0 = time.time()
    for n, (root, src, is_dir_root) in enumerate(files, 1):
        rel = src.relative_to(root)
        if is_dir_root and multi_input:
            rel = Path(root.name) / rel
        # archivos sueltos: clave por ruta completa (dos "uno.wav" de carpetas distintas no deben pisarse)
        key = rel.as_posix() if is_dir_root else f"file:{src.resolve()}"
        st = src.stat()
        label = f"[{n}/{len(files)}]"
        show_progress(f"{label} {src.stem}", int((n - 1) / len(files) * 100), {})
        if args.settle and time.time() - st.st_mtime < args.settle:
            waiting += 1
            print(f"{label} {src.name}: se modificó hace poco, lo dejo para la próxima pasada")
            continue
        entry = manifest["entries"].get(key)
        if not args.force and entry_is_current(entry, st, settings, out_dir):
            skipped += 1
            continue
        try:
            res = process_file(src, rel, key, settings, out_dir, manifest, label)
        except Exception as err:  # noqa: BLE001 - un fallo no debe parar el lote
            failed += 1
            print(f"{label} {src.name}: ✗ {err}")
            manifest["entries"][key] = {
                "id": src.stem, "source": str(src), "size": st.st_size, "mtime": st.st_mtime,
                "settings": settings, "status": "failed", "error": str(err)[-500:],
                "processed_at": now_iso(), "output": None}
            save_manifest(out_dir, manifest)
            continue
        done += 1
        final = res["final"]
        rel_out = final.relative_to(out_dir).as_posix()
        old = (entry or {}).get("output")
        if old and old["file"] != rel_out and (out_dir / old["file"]).is_file():
            try:
                (out_dir / old["file"]).unlink()  # salida vieja de este mismo origen (cambió el nombre o el formato)
            except OSError:
                pass
        manifest["entries"][key] = {
            "id": src.stem, "source": str(src), "size": st.st_size, "mtime": st.st_mtime,
            "duration": round(res["duration"], 3), "settings": settings, "status": "ok",
            "processed_at": now_iso(),
            "output": {"file": rel_out, "size": final.stat().st_size, "format": settings["format"]},
        }
        save_manifest(out_dir, manifest)
        print(f"{label} {src.name}: ✓ {duration_label(res['duration'])}\n      → {rel_out}")

    show_progress("listo", 100, {})
    print(f"\nListo en {time.time() - t0:.0f}s · convertidos {done} · ya al día {skipped} · pendientes {waiting} · con error {failed}")
    return 1 if failed else 0


def analyze_cli(args):
    opts = analysis_settings_from(args)
    if not has_numpy():
        print("✗ Falta numpy para el análisis: pip install numpy", file=sys.stderr)
        return 2
    files = collect_files(args.inputs)
    if not files:
        print("No hay audio que analizar.")
        return 0
    rows, failed, t0 = [], 0, time.time()
    for n, (_, src, _) in enumerate(files, 1):
        label = f"[{n}/{len(files)}]"
        show_progress(f"{label} {src.stem}", int((n - 1) / len(files) * 100), {})
        try:
            file_rows = analyze_file(src, opts)
        except Exception as err:  # noqa: BLE001
            failed += 1
            print(f"{label} {src.name}: ✗ {err}")
            continue
        rows.extend(file_rows)
        for row in file_rows:
            span = f" [{row['start']}–{row['end']}]" if len(file_rows) > 1 else ""
            print(f"{label} {src.name}{span}: ✓ {row['bpm'] or '—'} bpm · {row['key'] or '—'} · energía {row['energy'] or '—'}"
                  f" · {row['mood'] or '—'} · {row['duration']}")
    if rows:
        write_csv(args.output, rows)
        print(f"\nCSV: {Path(args.output).resolve()}")
    show_progress("listo", 100, {})
    print(f"Listo en {time.time() - t0:.0f}s · analizados {len(rows)} · con error {failed}")
    return 1 if failed else 0


def cmd_watch(args):
    print(f"Vigilando {', '.join(args.inputs)} cada {args.interval}s (Ctrl+C para parar)")
    try:
        while True:
            convert_once(args)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nParado.")
        return 0


# ───────────────────────── espectrograma ─────────────────────────

def spec_options(raw):
    """Valida y completa las opciones del espectrograma (de la web o de la CLI)."""
    o = dict(SPEC_DEFAULTS)
    o.update({k: v for k, v in (raw or {}).items() if k in SPEC_DEFAULTS and v not in (None, "")})
    try:
        o["width"], o["height"] = int(float(o["width"])), int(float(o["height"]))
        o["drange"], o["gain"] = float(o["drange"]), float(o["gain"])
        o["fmin"], o["fmax"] = int(float(o["fmin"] or 0)), int(float(o["fmax"] or 0))
    except (TypeError, ValueError):
        raise ValueError("ancho, alto, rango dinámico, ganancia y frecuencias deben ser números")
    if not (200 <= o["width"] <= 16000 and 100 <= o["height"] <= 8000):
        raise ValueError("tamaño fuera de rango (ancho 200–16000, alto 100–8000)")
    if not 10 <= o["drange"] <= 200:
        raise ValueError("el rango dinámico debe estar entre 10 y 200 dB")
    if not 0 <= o["gain"] <= 128:
        raise ValueError("la ganancia debe estar entre 0 y 128")
    if o["fmin"] < 0 or o["fmax"] < 0 or (o["fmax"] and o["fmax"] <= o["fmin"]):
        raise ValueError("frecuencias no válidas (la máxima debe ser mayor que la mínima)")
    for key, allowed in (("color", SPEC_COLORS), ("scale", SPEC_SCALES), ("fscale", SPEC_FSCALES),
                         ("win", SPEC_WINS), ("mode", SPEC_MODES)):
        if o[key] not in allowed:
            raise ValueError(f"{key}: valor no válido ({o[key]!r}); opciones: {', '.join(allowed)}")
    o["legend"] = bool(o["legend"])
    o["start"], o["end"] = parse_time(o["start"]), parse_time(o["end"])
    if o["start"] is not None and o["end"] is not None and o["end"] <= o["start"]:
        raise ValueError("el final debe ser mayor que el inicio")
    return o


def make_spectrogram(src, dst, raw_opts):
    o = spec_options(raw_opts)
    graph = (f"showspectrumpic=s={o['width']}x{o['height']}:mode={o['mode']}:color={o['color']}:scale={o['scale']}"
             f":fscale={o['fscale']}:win_func={o['win']}:gain={o['gain']:g}:drange={o['drange']:g}"
             f":legend={int(o['legend'])}:start={o['fmin']}:stop={o['fmax']}")
    cmd = [tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-v", "error"]
    if o["start"]:
        cmd += ["-ss", f"{o['start']:.3f}"]
    if o["end"] is not None:
        cmd += ["-t", f"{o['end'] - (o['start'] or 0):.3f}"]
    cmd += ["-i", str(src), "-lavfi", graph, "-frames:v", "1", "-f", "image2", "-c:v", "png", str(dst)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not Path(dst).is_file() or Path(dst).stat().st_size == 0:
        raise RuntimeError("ffmpeg no pudo generar el espectrograma: " + clean_err(proc.stderr, 400))


def spec_cli(args):
    out_dir = Path(args.output)
    opts = {"width": args.width, "height": args.height, "color": args.color, "scale": args.scale,
            "fscale": args.fscale, "win": args.win, "drange": args.drange, "gain": args.gain,
            "fmin": args.fmin, "fmax": args.fmax, "mode": args.mode, "legend": not args.no_legend,
            "start": args.start, "end": args.end}
    spec_options(opts)  # valida antes de empezar
    files = collect_files(args.inputs, out_dir)
    if not files:
        print("No hay audio que procesar.")
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    failed = 0
    for n, (root, src, _) in enumerate(files, 1):
        rel = src.relative_to(root)
        dst = out_dir / rel.parent / f"{src.stem}.spectrogram.png"
        label = f"[{n}/{len(files)}]"
        show_progress(f"{label} {src.stem}", int((n - 1) / len(files) * 100), {})
        if dst.exists() and not args.force:
            print(f"{label} {src.name}: ya existe, se salta (usa --force)")
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            make_spectrogram(src, dst, opts)
            print(f"{label} {src.name}: ✓ {dst.relative_to(out_dir).as_posix()}")
        except Exception as err:  # noqa: BLE001
            failed += 1
            print(f"{label} {src.name}: ✗ {err}")
    show_progress("listo", 100, {})
    return 1 if failed else 0


def cmd_doctor(args):
    ok = True

    def line(good, text, required=True):
        nonlocal ok
        ok = ok and (good or not required)
        print(("✓ " if good else "✗ ") + text)

    for name in ("ffmpeg", "ffprobe"):
        path = tool(name)
        if path:
            ver = subprocess.run([path, "-version"], capture_output=True, text=True, errors="replace").stdout
            line(True, f"{name}: {ver.splitlines()[0] if ver else path}")
        else:
            line(False, f"{name} no está en el PATH (instálalo o usa la variable {name.upper()})")
    if tool("ffmpeg"):
        enc = subprocess.run([tool("ffmpeg"), "-hide_banner", "-encoders"], capture_output=True, text=True,
                             errors="replace").stdout
        line("libmp3lame" in enc, "codificador libmp3lame (convertir a mp3)")
        line(has_filter("showspectrumpic"), "filtro showspectrumpic (espectrograma)")
    line(has_numpy(), "numpy (herramienta Analizar): pip install numpy")
    return 0 if ok else 1


def doctor_info():
    ff = tool("ffmpeg")
    enc = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True, text=True,
                         errors="replace").stdout if ff else ""
    info = {"ffmpeg": bool(ff), "ffprobe": bool(tool("ffprobe")), "mp3": "libmp3lame" in enc,
            "spectrogram": bool(ff) and has_filter("showspectrumpic"), "numpy": has_numpy()}
    info["ok"] = all(info.values())
    return info


# ───────────────────────── interfaz web local ─────────────────────────
# Servidor de la biblioteca estándar, solo en 127.0.0.1. La interfaz (web/index.html) lanza este mismo
# script como subproceso (`run`/`watch`) para renombrar, y genera los espectrogramas directamente.

WEB_DIR = Path(__file__).with_name("web")
SCRIPT = Path(__file__).resolve()


class JobRunner:
    """Un único trabajo a la vez: el subproceso, su log y el progreso."""

    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.reset()

    def reset(self):
        self.lines, self.state, self.mode = [], "idle", None
        self.progress = {"pct": 0, "label": ""}
        self.exit_code, self.output, self.cmd = None, None, ""

    def running(self):
        return self.state == "running"

    def start(self, mode, argv, output):
        with self.lock:
            if self.running():
                raise RuntimeError("ya hay un trabajo en marcha")
            self.reset()
            self.state, self.mode, self.output = "running", mode, output
            self.cmd = " ".join(["python", SCRIPT.name] + argv)
            env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", AP_PROGRESS="1")
            kw = {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)} if os.name == "nt" \
                else {"start_new_session": True}
            self.proc = subprocess.Popen([sys.executable, "-u", str(SCRIPT), *argv], stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                         errors="replace", env=env, **kw)
            threading.Thread(target=self._pump, args=(self.proc,), daemon=True).start()

    def _pump(self, proc):
        for raw in proc.stdout:
            line = raw.rstrip("\r\n")
            m = re.match(r"@progress (\d+) (.*)", line)
            if m:
                self.progress = {"pct": int(m.group(1)), "label": m.group(2)}
            elif line.strip():
                self.lines.append(line)
        proc.stdout.close()
        code = proc.wait()
        self.exit_code = code
        if self.state != "cancelled":
            self.state = "done" if code == 0 else "failed"
        self.progress = {"pct": 100 if code == 0 else self.progress["pct"], "label": self.progress["label"]}

    def cancel(self):
        proc = self.proc
        if not (proc and self.running()):
            return False
        self.state = "cancelled"
        try:
            if os.name == "nt":  # sin /T quedaría ffmpeg huérfano escribiendo
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
            else:
                import signal
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        return True

    def snapshot(self, since):
        return {"state": self.state, "mode": self.mode, "cmd": self.cmd, "exit_code": self.exit_code,
                "output": self.output, "progress": self.progress,
                "total": len(self.lines), "lines": self.lines[since:]}


def list_roots():
    roots = [str(Path.home())]
    if os.name == "nt":
        roots += [f"{c}:\\" for c in "CDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{c}:\\").exists()]
    else:
        roots.append("/")
    return roots


def browse_dir(path):
    p = (Path(path).expanduser() if path else Path.home()).resolve()
    if not p.is_dir():
        raise ValueError(f"no es una carpeta: {p}")
    dirs, files = [], []
    try:
        entries = sorted(os.scandir(p), key=lambda e: e.name.lower())
    except OSError as err:
        raise ValueError(f"no se puede leer {p}: {err.strerror or err}")
    for e in entries:
        try:
            if e.name.startswith("."):
                continue
            if e.is_dir():
                dirs.append(e.name)
            elif Path(e.name).suffix.lower() in AUDIO_EXTS:
                files.append({"name": e.name, "size": e.stat().st_size})
        except OSError:
            continue
    return {"path": str(p), "parent": str(p.parent) if p.parent != p else None, "dirs": dirs, "files": files}


def expand_inputs(inputs, limit=5000):
    """Lista plana de archivos de audio a partir de archivos y carpetas (recursivo), sin imprimir nada."""
    found = []
    for inp in inputs:
        p = Path(inp)
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
            found.append(str(p))
        elif p.is_dir():
            found += [str(f) for f in sorted(p.rglob("*"))
                      if f.is_file() and f.suffix.lower() in AUDIO_EXTS and not f.name.startswith(".")]
    if len(found) > limit:
        raise ValueError(f"demasiados archivos ({len(found)}); el máximo desde la web es {limit}")
    return list(dict.fromkeys(found))  # sin repetidos, en orden


def read_results(out):
    d = Path(out)
    manifest = load_manifest(d) if (d / MANIFEST_NAME).is_file() else {"entries": {}}
    items = []
    for e in manifest["entries"].values():
        items.append({"id": e.get("id"), "status": e.get("status"), "source": e.get("source"),
                      "duration": e.get("duration"), "src_size": e.get("size"), "output": e.get("output"),
                      "error": e.get("error"), "processed_at": e.get("processed_at")})
    items.sort(key=lambda i: i.get("processed_at") or "", reverse=True)
    return {"items": items, "dir": str(d.resolve())}


def build_cli_args(body):
    """Del formulario de la web a los argumentos de `convert`/`watch` (nada pasa por una shell)."""
    mode = {"convert": "convert", "watch": "watch"}.get(body.get("mode"))
    inputs = [str(x) for x in body.get("inputs") or [] if str(x).strip()]
    output = str(body.get("output") or "").strip()
    if not mode:
        raise ValueError("modo desconocido")
    if not inputs:
        raise ValueError("elige al menos un archivo o carpeta de origen")
    if not output:
        raise ValueError("elige la carpeta de salida")
    argv = [mode, *inputs, "-o", output]
    for key, flag in (("format", "--format"), ("mp3_quality", "--mp3-quality"), ("wav_bits", "--wav-bits")):
        v = body.get(key)
        if v not in (None, ""):
            argv += [flag, str(v)]
    for key, flag in (("settle", "--settle"), ("interval", "--interval")):
        v = body.get(key)
        if v in (None, "") or (key == "interval" and mode != "watch"):
            continue
        float(v)  # valida que sea un número
        argv += [flag, str(v)]
    if body.get("force"):
        argv.append("--force")
    settings_from(parse_run_args(argv))  # valida valores (formato, calidad…) antes de lanzar
    return mode, argv, output


def analysis_options(raw):
    """Opciones de análisis que llegan de la web, validadas con las mismas reglas que la CLI."""
    ns = argparse.Namespace(**{k: v for k, v in (raw or {}).items() if k in ANALYZE_DEFAULTS and v not in (None, "")})
    return analysis_settings_from(ns)


def open_in_file_manager(path):
    p = Path(path)
    if not p.exists():
        raise ValueError("esa carpeta todavía no existe")
    if os.name == "nt":
        os.startfile(str(p))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


class SpecStore:
    """Espectrogramas generados desde la web: viven en una carpeta temporal y se sirven por id,
    así la API nunca entrega rutas arbitrarias del disco."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="audio_processor_"))
        self.items, self.saved = {}, {}
        self.lock = threading.Lock()

    def generate(self, src, opts):
        src = Path(src)
        if not src.is_file() or src.suffix.lower() not in AUDIO_EXTS:
            raise ValueError(f"no es un archivo de audio: {src}")
        sid = secrets.token_hex(8)
        dst = self.dir / f"{sid}.png"
        make_spectrogram(src, dst, opts)
        with self.lock:
            self.items[sid] = {"path": dst, "name": f"{src.stem}.spectrogram.png", "source": str(src)}
        return sid, self.items[sid]["name"]

    def path(self, sid):
        with self.lock:
            item = self.items.get(sid)
        if not item:
            raise ValueError("espectrograma desconocido (¿se reinició la app?)")
        return item

    def save(self, sid, out_dir):
        item = self.path(sid)
        folder = Path(out_dir) / SPEC_DIR_NAME
        folder.mkdir(parents=True, exist_ok=True)
        stem = item["name"][:-len(".spectrogram.png")]
        n, dst = 1, folder / item["name"]
        while self.saved.get(str(dst), item["source"]) != item["source"]:  # otro audio con el mismo nombre
            n += 1
            dst = folder / f"{stem} ({n}).spectrogram.png"
        self.saved[str(dst)] = item["source"]
        tmp = dst.with_name(dst.name + ".part")
        shutil.copyfile(item["path"], tmp)
        os.replace(tmp, dst)
        return str(dst)

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def make_handler(job, specs, token, port):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "AudioProcessor"

        def log_message(self, *a):  # silencio
            pass

        def send_bytes(self, data, ctype, code=200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def send_json(self, obj, code=200):
            self.send_bytes(json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", code)

        def guard(self, api):
            """Defensa contra otras webs: solo el host exacto y, para /api, el token de esta sesión."""
            if self.headers.get("Host", "") not in allowed_hosts:
                self.send_json({"error": "host no permitido"}, 403)
                return False
            if api and self.headers.get("X-AP-Token") != token:
                self.send_json({"error": "token no válido: recarga la página"}, 403)
                return False
            return True

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            api = url.path.startswith("/api/")
            if not self.guard(api):
                return
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path in ("/", "/index.html"):
                page = (WEB_DIR / "index.html").read_text(encoding="utf-8")
                self.send_bytes(page.replace("__TOKEN__", token).replace("__VERSION__", __version__).encode("utf-8"),
                                "text/html; charset=utf-8")
                return
            try:
                if url.path == "/api/state":
                    self.send_json({"version": __version__, "doctor": doctor_info(), "roots": list_roots(),
                                    "convert_defaults": CONVERT_DEFAULTS, "analyze_defaults": ANALYZE_DEFAULTS,
                                    "spec_defaults": SPEC_DEFAULTS, "mp3_qualities": MP3_QUALITIES, "wav_bits": WAV_BITS,
                                    "spec_choices": {"color": SPEC_COLORS, "scale": SPEC_SCALES, "fscale": SPEC_FSCALES,
                                                     "win": SPEC_WINS, "mode": SPEC_MODES}})
                elif url.path == "/api/browse":
                    self.send_json(browse_dir(q.get("path")))
                elif url.path == "/api/job":
                    self.send_json(job.snapshot(int(q.get("since", 0))))
                elif url.path == "/api/results":
                    self.send_json(read_results(q.get("output", "")))
                elif url.path == "/api/spectrogram/image":
                    self.send_bytes(specs.path(q.get("id", ""))["path"].read_bytes(), "image/png")
                else:
                    self.send_json({"error": "no existe"}, 404)
            except (ValueError, OSError, SystemExit) as err:
                self.send_json({"error": str(err)}, 400)

        def do_POST(self):  # noqa: N802
            if not self.guard(True):
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                path = urlparse(self.path).path
                if path == "/api/start":
                    _, argv, output = build_cli_args(body)
                    job.start(body.get("mode"), argv, output)
                    self.send_json({"ok": True})
                elif path == "/api/cancel":
                    self.send_json({"ok": job.cancel()})
                elif path == "/api/open":
                    open_in_file_manager(body.get("path", ""))
                    self.send_json({"ok": True})
                elif path == "/api/expand":
                    self.send_json({"files": expand_inputs([str(x) for x in body.get("inputs") or []])})
                elif path == "/api/analyze":
                    src = Path(str(body.get("file") or ""))
                    if not src.is_file() or src.suffix.lower() not in AUDIO_EXTS:
                        raise ValueError(f"no es un archivo de audio: {src}")
                    if not has_numpy():
                        raise ValueError("falta numpy para el análisis: pip install numpy")
                    try:
                        self.send_json({"ok": True, "rows": analyze_file(src, analysis_options(body.get("options")))})
                    except RuntimeError as err:  # archivo ilegible: se devuelve como fila con error, no rompe el lote
                        self.send_json({"ok": True, "rows": [{"file": src.name, "error": str(err)}]})
                elif path == "/api/analyze/csv":
                    self.send_bytes(b"\xef\xbb\xbf" + csv_text(body.get("rows") or []).encode("utf-8"), "text/csv; charset=utf-8")
                elif path == "/api/analyze/save":
                    out = str(body.get("output") or "").strip()
                    if not out:
                        raise ValueError("elige la carpeta de salida")
                    dst = Path(out) / CSV_NAME
                    write_csv(dst, body.get("rows") or [])
                    self.send_json({"ok": True, "path": str(dst)})
                elif path == "/api/spectrogram":
                    sid, name = specs.generate(body.get("file", ""), body.get("options"))
                    self.send_json({"ok": True, "id": sid, "name": name})
                elif path == "/api/spectrogram/save":
                    out = str(body.get("output") or "").strip()
                    if not out:
                        raise ValueError("elige la carpeta de salida")
                    self.send_json({"ok": True, "path": specs.save(str(body.get("id") or ""), out)})
                else:
                    self.send_json({"error": "no existe"}, 404)
            except (ValueError, TypeError, RuntimeError, OSError) as err:
                self.send_json({"error": str(err)}, 400)

    return Handler


class LocalServer(ThreadingHTTPServer):
    # En Windows SO_REUSEADDR deja abrir un segundo servidor en un puerto YA ocupado (y el navegador
    # acabaría en el otro programa); sin él, un puerto ocupado da error y se prueba el siguiente.
    allow_reuse_address = os.name != "nt"


def cmd_serve(args):
    if not (WEB_DIR / "index.html").is_file():
        print(f"✗ Falta {WEB_DIR / 'index.html'} (la carpeta web/ debe ir junto al script).", file=sys.stderr)
        return 2
    token, job, specs, server, port = secrets.token_urlsafe(24), JobRunner(), SpecStore(), None, args.port
    for port in range(args.port, args.port + 20):
        try:
            server = LocalServer(("127.0.0.1", port), make_handler(job, specs, token, port))
            break
        except OSError:
            continue
    if not server:
        print(f"✗ No pude abrir ningún puerto entre {args.port} y {args.port + 19}.", file=sys.stderr)
        return 2
    url = f"http://127.0.0.1:{port}/"
    print(f"Audio Processor {__version__} · interfaz en {url}  (Ctrl+C para cerrar)")
    if not args.no_open:
        import webbrowser
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando…")
    finally:
        job.cancel()
        server.server_close()
        specs.close()
    return 0


# ───────────────────────── CLI ─────────────────────────

def add_inputs(p):
    p.add_argument("inputs", nargs="+", help="archivos y/o carpetas (se recorren con subcarpetas)")
    p.add_argument("-o", "--output", required=True, help="carpeta de salida (se crea si no existe)")
    p.add_argument("--force", action="store_true", help="rehacer aunque ya esté al día")


def add_convert(p):
    add_inputs(p)
    p.add_argument("--format", choices=["mp3", "wav"], help="formato de salida (por defecto: mp3)")
    p.add_argument("--mp3-quality", dest="mp3_quality", choices=MP3_QUALITIES, help="calidad mp3 (por defecto 320k)")
    p.add_argument("--wav-bits", dest="wav_bits", type=int, choices=WAV_BITS, help="profundidad del wav (por defecto 16)")
    p.add_argument("--settle", type=float, default=0,
                   help="saltar archivos modificados hace menos de N segundos (por si aún se copian)")


def build_parser():
    ap = argparse.ArgumentParser(prog="audio_processor",
                                 description="Convierte audio a mp3/wav, lo analiza a un CSV (BPM, tonalidad, energía, mood, duración) y genera espectrogramas.")
    ap.add_argument("--version", action="version", version=f"audio-processor {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    add_convert(sub.add_parser("convert", help="convierte a mp3 o wav una vez (ideal para un schedule)"))
    watch = sub.add_parser("watch", help="vigila la carpeta y convierte lo nuevo cada cierto tiempo")
    add_convert(watch)
    watch.add_argument("--interval", type=float, default=300, help="segundos entre pasadas (por defecto 300)")
    ana = sub.add_parser("analyze", help="analiza BPM, tonalidad, energía, mood y duración y los guarda en un CSV")
    ana.add_argument("inputs", nargs="+", help="archivos y/o carpetas (se recorren con subcarpetas)")
    ana.add_argument("-o", "--output", default=CSV_NAME, help=f"archivo CSV de salida (por defecto {CSV_NAME})")
    d = ANALYZE_DEFAULTS
    ana.add_argument("--key-format", dest="key_format", choices=["short", "long", "camelot"], help="Dm / Dmin / 7A (por defecto short)")
    ana.add_argument("--accidental", choices=["sharp", "flat"], help="F# o Gb (por defecto sharp)")
    ana.add_argument("--bpm-min", dest="bpm_min", type=float, help=f"BPM mínimo a considerar (por defecto {d['bpm_min']:g})")
    ana.add_argument("--bpm-max", dest="bpm_max", type=float, help=f"BPM máximo a considerar (por defecto {d['bpm_max']:g})")
    ana.add_argument("--bpm-decimals", dest="bpm_decimals", type=int, choices=[0, 1], help="decimales del BPM")
    ana.add_argument("--analyze-seconds", dest="analyze_seconds", type=float,
                     help="analizar solo esta ventana central, en segundos (por defecto 120; 0 = pista completa)")
    ana.add_argument("--split", choices=list(SPLIT_MODES),
                     help="fragmentar cada pista en secciones: auto (por cambios), fixed (ventanas iguales) u off (por defecto)")
    ana.add_argument("--min-section", dest="min_section", type=float,
                     help=f"duración mínima de una sección con --split auto (por defecto {d['min_section']:g} s)")
    ana.add_argument("--split-seconds", dest="split_seconds", type=float,
                     help=f"tamaño de cada sección con --split fixed (por defecto {d['split_seconds']:g} s)")
    spec = sub.add_parser("spectrogram", help="genera espectrogramas PNG")
    add_inputs(spec)
    d = SPEC_DEFAULTS
    spec.add_argument("--width", type=int, default=d["width"])
    spec.add_argument("--height", type=int, default=d["height"])
    spec.add_argument("--color", choices=SPEC_COLORS, default=d["color"], help="paleta de color")
    spec.add_argument("--scale", choices=SPEC_SCALES, default=d["scale"], help="escala de intensidad")
    spec.add_argument("--fscale", choices=SPEC_FSCALES, default=d["fscale"], help="escala de frecuencia (lin/log)")
    spec.add_argument("--win", choices=SPEC_WINS, default=d["win"], help="ventana de la FFT")
    spec.add_argument("--drange", type=float, default=d["drange"], help="rango dinámico en dB (10–200)")
    spec.add_argument("--gain", type=float, default=d["gain"], help="ganancia (0–128)")
    spec.add_argument("--fmin", type=int, default=d["fmin"], help="frecuencia mínima en Hz")
    spec.add_argument("--fmax", type=int, default=d["fmax"], help="frecuencia máxima en Hz (0 = hasta Nyquist)")
    spec.add_argument("--mode", choices=SPEC_MODES, default=d["mode"], help="canales juntos o separados")
    spec.add_argument("--no-legend", action="store_true", help="sin ejes ni leyenda")
    spec.add_argument("--from", dest="start", default="", help="inicio (90, 1:30, 2m)")
    spec.add_argument("--to", dest="end", default="", help="final (90, 1:30, 2m)")
    sub.add_parser("doctor", help="comprueba ffmpeg, mp3 y numpy")
    srv = sub.add_parser("serve", help="abre la interfaz web local (solo en tu equipo)")
    srv.add_argument("--port", type=int, default=8766, help="puerto (por defecto 8766; si está ocupado prueba los siguientes)")
    srv.add_argument("--no-open", action="store_true", help="no abrir el navegador automáticamente")
    return ap


def parse_run_args(argv):
    return build_parser().parse_args(argv)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:  # noqa: BLE001
            pass
    args = build_parser().parse_args(argv)
    if args.cmd in ("convert", "watch", "spectrogram", "analyze") and not (tool("ffmpeg") and tool("ffprobe")):
        print("✗ No encuentro ffmpeg/ffprobe. Ejecuta `doctor` para más detalles.", file=sys.stderr)
        return 2
    try:
        if args.cmd == "convert":
            return convert_once(args)
        if args.cmd == "analyze":
            return analyze_cli(args)
        if args.cmd == "watch":
            if args.settle == 0:
                args.settle = 30
            return cmd_watch(args)
        if args.cmd == "spectrogram":
            return spec_cli(args)
        if args.cmd == "doctor":
            return cmd_doctor(args)
        return cmd_serve(args)
    except ValueError as err:
        print(f"✗ {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
