import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audio_processor as ap  # noqa: E402

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

HAVE_FFMPEG = bool(ap.tool("ffmpeg") and ap.tool("ffprobe"))
SR = 44100


def synth(path, bpm, tonic, minor, bars=24):
    """Progresión i-iv-V-i (menor) o I-vi-IV-V (mayor) con graves, bombo, charles y caja."""
    rng = np.random.RandomState(1)
    beat = 60.0 / bpm
    n = int(bars * 4 * beat * SR) + SR // 2
    y = np.zeros(n)
    prog = ([(0, [0, 3, 7]), (5, [0, 3, 7]), (7, [0, 4, 7]), (0, [0, 3, 7])] if minor
            else [(0, [0, 4, 7]), (9, [0, 3, 7]), (5, [0, 4, 7]), (7, [0, 4, 7])])

    def saw(f, m, harm=8):
        t = np.arange(m) / SR
        return sum(np.sin(2 * np.pi * f * h * t) / h for h in range(1, harm + 1) if f * h < SR / 2)

    def hz(m):
        return 440 * 2 ** ((m - 69) / 12)

    for bar in range(bars):
        root, chord = prog[bar % 4]
        t0, dur = int(bar * 4 * beat * SR), int(4 * beat * SR)
        env = np.minimum(1, np.arange(dur) / 200) * np.minimum(1, (dur - np.arange(dur)) / 400)
        seg = sum(saw(hz(60 + tonic + root + iv), dur) for iv in chord) + 1.5 * saw(hz(36 + tonic + root), dur, 4)
        y[t0:t0 + dur] += 0.12 * seg * env
    for b in range(bars * 4):
        t0 = int(b * beat * SR)
        k = np.arange(int(0.15 * SR)) / SR
        y[t0:t0 + len(k)] += 0.9 * np.sin(2 * np.pi * (50 + 100 * np.exp(-k * 30)) * k) * np.exp(-k * 20)
        h0, m = int((b + 0.5) * beat * SR), int(0.04 * SR)
        y[h0:h0 + m] += 0.15 * rng.randn(m) * np.exp(-np.arange(m) / SR * 120)
        if b % 4 in (1, 3):
            m = int(0.12 * SR)
            y[t0:t0 + m] += 0.4 * rng.randn(m) * np.exp(-np.arange(m) / SR * 30)
    y /= np.abs(y).max() * 1.05
    write_wav(path, (y * 32767).astype("<i2").tobytes())


def write_wav(path, frames):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(frames)




class PureFunctions(unittest.TestCase):
    def test_key_labels(self):
        self.assertEqual(ap.key_label(2, "minor"), "Dm")
        self.assertEqual(ap.key_label(0, "major"), "C")
        self.assertEqual(ap.key_label(6, "minor", "short", "sharp"), "F#m")
        self.assertEqual(ap.key_label(6, "minor", "short", "flat"), "Gbm")
        self.assertEqual(ap.key_label(2, "minor", "long"), "Dmin")
        self.assertEqual(ap.key_label(7, "major", "long"), "Gmaj")
        self.assertEqual(ap.key_label(2, "minor", "camelot"), "7A")
        self.assertEqual(ap.key_label(0, "major", "camelot"), "8B")
        self.assertEqual(ap.key_label(None, None), "NA")

    def test_camelot_is_a_bijection(self):
        self.assertEqual(sorted(ap.CAMELOT_MAJOR.values()), list(range(1, 13)))
        self.assertEqual(sorted(ap.CAMELOT_MINOR.values()), list(range(1, 13)))

    def test_duration_label_is_mm_ss_ms(self):
        self.assertEqual(ap.duration_label(185.123), "03:05:123")
        self.assertEqual(ap.duration_label(0), "00:00:000")
        self.assertEqual(ap.duration_label(59.9996), "01:00:000")
        self.assertEqual(ap.duration_label(0.5), "00:00:500")
        self.assertEqual(ap.duration_label(125 * 60 + 3.007), "125:03:007")
        self.assertEqual(ap.duration_label(-3), "00:00:000")

    def test_bpm_label(self):
        self.assertEqual(ap.bpm_label(139.6), "140")
        self.assertEqual(ap.bpm_label(140.5, 1), "140.5")
        self.assertEqual(ap.bpm_label(140.0, 1), "140")
        self.assertEqual(ap.bpm_label(None), "NA")

    def test_mood_labels(self):
        self.assertEqual(ap.mood_label("minor", 0.8, 2), "Melancholic")
        self.assertEqual(ap.mood_label("minor", 0.8, 5), "Dark")
        self.assertEqual(ap.mood_label("minor", 0.8, 9), "Aggressive")
        self.assertEqual(ap.mood_label("major", 0.8, 2), "Chill")
        self.assertEqual(ap.mood_label("major", 0.8, 5), "Happy")
        self.assertEqual(ap.mood_label("major", 0.8, 7), "Uplifting")
        self.assertEqual(ap.mood_label("major", 0.8, 10), "Euphoric")
        self.assertEqual(ap.mood_label("minor", 0.05, 5), "Neutral")  # tonalidad dudosa: no se usa el modo
        self.assertEqual(ap.mood_label(None, 0.0, 9), "Energetic")
        self.assertIsNone(ap.mood_label("minor", 0.9, None))

    def test_csv_columns_and_skips_errors(self):
        rows = [{"file": "a, b.wav", "bpm": "140", "key": "Dm", "energy": 7, "mood": "Dark",
                 "start": "00:00:000", "end": "00:14:203", "duration": "00:14:203"},
                {"file": "mal.wav", "error": "ffprobe no pudo leer el archivo"},
                {"file": "mudo.wav", "bpm": "", "key": "", "energy": "", "mood": "",
                 "start": "00:00:000", "end": "00:05:000", "duration": "00:05:000"}]
        lines = ap.csv_text(rows).splitlines()
        self.assertEqual(lines[0], "archivo,bpm,tonalidad,energia,mood,inicio,fin,duracion")
        self.assertEqual(lines[1], '"a, b.wav",140,Dm,7,Dark,00:00:000,00:14:203,00:14:203')
        self.assertEqual(lines[2], "mudo.wav,,,,,00:00:000,00:05:000,00:05:000")
        self.assertEqual(len(lines), 3)

    def test_parse_time(self):
        self.assertEqual(ap.parse_time("1:30"), 90)
        self.assertEqual(ap.parse_time("2m"), 120)
        self.assertEqual(ap.parse_time("90"), 90)
        self.assertEqual(ap.parse_time("1:02:03"), 3723)
        self.assertIsNone(ap.parse_time(""))
        with self.assertRaises(ValueError):
            ap.parse_time("abc")

    def test_spec_options_validation(self):
        o = ap.spec_options({"width": "1000", "start": "0:10", "end": "0:20", "fmax": "8000"})
        self.assertEqual((o["width"], o["start"], o["end"], o["fmax"]), (1000, 10, 20, 8000))
        for bad in ({"color": "nope"}, {"width": 5}, {"drange": 5}, {"start": "30", "end": "10"},
                    {"fmin": 500, "fmax": 100}, {"width": "x"}):
            with self.assertRaises(ValueError, msg=str(bad)):
                ap.spec_options(bad)

    def test_build_cli_args_validates(self):
        mode, argv, _ = ap.build_cli_args({"mode": "convert", "inputs": ["a"], "output": "o", "format": "wav",
                                           "wav_bits": "24", "mp3_quality": "v0"})
        self.assertEqual(mode, "convert")
        self.assertIn("--wav-bits", argv)
        base = {"mode": "convert", "inputs": ["a"], "output": "o"}
        for bad in ({"mode": "x", "inputs": ["a"], "output": "o"}, {"mode": "convert", "inputs": [], "output": "o"},
                    {**base, "output": ""}, {**base, "format": "ogg"}, {**base, "wav_bits": "20"},
                    {**base, "mp3_quality": "1k"}, {**base, "settle": "abc"}):
            with self.assertRaises((ValueError, SystemExit), msg=str(bad)):
                ap.build_cli_args(bad)

    def test_analysis_options_validation(self):
        self.assertEqual(ap.analysis_options({"bpm_min": "80", "key_format": "camelot"})["bpm_min"], 80.0)
        for bad in ({"bpm_min": "200", "bpm_max": "100"}, {"key_format": "x"}, {"bpm_min": "abc"}, {"bpm_decimals": 2},
                    {"split": "x"}, {"split": "auto", "min_section": "1"}):
            with self.assertRaises(ValueError, msg=str(bad)):
                ap.analysis_options(bad)


@unittest.skipUnless(HAVE_FFMPEG and np is not None, "necesita ffmpeg y numpy")
class Analysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="ap_test_"))
        cls.cases = {"dm_140": (140, 2, True), "cmaj_128": (128, 0, False), "fsm_174": (174, 6, True),
                     "a_100": (100, 9, False)}
        for name, (bpm, tonic, minor) in cls.cases.items():
            synth(cls.tmp / f"{name}.wav", bpm, tonic, minor)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_bpm_and_key(self):
        opts = dict(ap.ANALYZE_DEFAULTS)
        for name, (bpm, tonic, minor) in self.cases.items():
            info = ap.probe(self.tmp / f"{name}.wav")
            res = ap.analyze_audio(self.tmp / f"{name}.wav", info["duration"], opts)
            self.assertAlmostEqual(res["bpm"], bpm, delta=0.6, msg=name)
            self.assertEqual((res["tonic"], res["mode"]), (tonic, "minor" if minor else "major"), name)
            self.assertIn(res["energy"], range(1, 11), name)
            self.assertTrue(res["mood"], name)

    def test_energy_follows_loudness_and_density(self):
        quiet, loud = self.tmp / "quiet.wav", self.tmp / "loud.wav"
        t = np.arange(SR * 20) / SR
        pad = sum(np.sin(2 * np.pi * f * t) for f in (220, 261.63, 329.63)) * 0.03
        write_wav(quiet, (pad * 32767).astype("<i2").tobytes())
        noise = np.random.RandomState(0).randn(len(t)) * 0.5 * (np.sin(2 * np.pi * 3 * t) > 0)
        write_wav(loud, (np.clip(noise, -1, 1) * 32767).astype("<i2").tobytes())
        opts = dict(ap.ANALYZE_DEFAULTS)
        e_quiet = ap.analyze_audio(quiet, 20.0, opts)["energy"]
        e_loud = ap.analyze_audio(loud, 20.0, opts)["energy"]
        self.assertLessEqual(e_quiet, 4)
        self.assertGreaterEqual(e_loud, 7)

    def test_silence_and_short_audio_do_not_crash(self):
        silent = self.tmp / "silence.wav"
        write_wav(silent, b"\0\0" * SR * 5)
        res = ap.analyze_audio(silent, 5.0, dict(ap.ANALYZE_DEFAULTS))
        self.assertIsNone(res["bpm"])
        self.assertIsNone(res["tonic"])
        self.assertIsNone(res["energy"])
        self.assertIsNone(res["mood"])
        row = ap.analysis_row(silent, res, 5.0, dict(ap.ANALYZE_DEFAULTS))
        self.assertEqual((row["bpm"], row["key"], row["energy"], row["mood"], row["duration"]), ("", "", "", "", "00:05:000"))
        tiny = self.tmp / "tiny.wav"
        write_wav(tiny, b"\x10\x10" * 2000)
        res = ap.analyze_audio(tiny, 0.05, dict(ap.ANALYZE_DEFAULTS))
        self.assertIsNone(res["bpm"])

    def two_part_track(self):
        """20 s de pad suave + 20 s de ruido a golpes: un cambio claro en el segundo 20."""
        path = self.tmp / "two_parts.wav"
        t = np.arange(SR * 40) / SR
        pad = sum(np.sin(2 * np.pi * f * t) for f in (220, 261.63, 329.63)) * 0.03
        noise = np.random.RandomState(1).randn(len(t)) * 0.5 * (np.sin(2 * np.pi * 3 * t) > 0)
        y = np.where(t < 20, pad, noise)
        write_wav(path, (np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())
        return path

    def test_split_off_gives_one_whole_track_row(self):
        path = self.two_part_track()
        rows = ap.analyze_file(path, dict(ap.ANALYZE_DEFAULTS))
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["start"], rows[0]["end"], rows[0]["duration"]),
                         ("00:00:000", "00:40:000", "00:40:000"))

    def test_split_auto_cuts_where_the_music_changes(self):
        path = self.two_part_track()
        opts = dict(ap.ANALYZE_DEFAULTS, split="auto")
        rows = ap.analyze_file(path, opts)
        self.assertEqual(len(rows), 2, rows)
        self.assertEqual(rows[0]["start"], "00:00:000")
        self.assertEqual(rows[0]["end"], rows[1]["start"])
        self.assertEqual(rows[1]["end"], "00:40:000")
        cut = int(rows[0]["end"].split(":")[0]) * 60 + int(rows[0]["end"].split(":")[1])
        self.assertAlmostEqual(cut, 20, delta=2)
        self.assertLess(rows[0]["energy"], rows[1]["energy"], "la parte suave es menos enérgica")
        self.assertEqual(rows[0]["file"], rows[1]["file"])

    def test_split_auto_respects_min_section_and_ignores_steady_tracks(self):
        steady = self.tmp / "dm_140.wav"
        rows = ap.analyze_file(steady, dict(ap.ANALYZE_DEFAULTS, split="auto"))
        self.assertEqual(len(rows), 1, "una pista estable no se parte")
        short = ap.analyze_file(self.two_part_track(), dict(ap.ANALYZE_DEFAULTS, split="auto", min_section=25))
        self.assertEqual(len(short), 1, "con secciones de al menos 25 s no cabe un corte en 20 s")

    def test_split_fixed_makes_equal_contiguous_sections(self):
        rows = ap.analyze_file(self.two_part_track(), dict(ap.ANALYZE_DEFAULTS, split="fixed", split_seconds=15))
        self.assertEqual(len(rows), 3)  # 40 s / 15 s -> 3 trozos de ~13,3 s
        self.assertEqual(rows[0]["start"], "00:00:000")
        self.assertEqual(rows[-1]["end"], "00:40:000")
        for a, b in zip(rows, rows[1:]):
            self.assertEqual(a["end"], b["start"])
        self.assertEqual(rows[0]["duration"], "00:13:333")


@unittest.skipUnless(HAVE_FFMPEG and np is not None, "necesita ffmpeg y numpy")
class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="ap_e2e_"))
        cls.src = cls.tmp / "src"
        (cls.src / "sub").mkdir(parents=True)
        synth(cls.src / "uno.wav", 140, 2, True, bars=8)
        synth(cls.src / "sub" / "uno.wav", 128, 0, False, bars=8)  # mismo nombre, otra carpeta
        (cls.src / "notas.txt").write_text("no es audio")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_cli(self, *argv):
        return subprocess.run([sys.executable, str(Path(ap.__file__)), *argv], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    def probe_stream(self, path):
        out = subprocess.run([ap.tool("ffprobe"), "-v", "error", "-select_streams", "a:0", "-show_entries",
                              "stream=codec_name,sample_rate", "-print_format", "json", str(path)],
                             capture_output=True, text=True).stdout
        return json.loads(out)["streams"][0]

    def test_convert_to_mp3_keeps_the_name_and_is_idempotent(self):
        out = self.tmp / "mp3"
        r = self.run_cli("convert", str(self.src), "-o", str(out), "--mp3-quality", "v2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        names = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.mp3"))
        self.assertEqual(names, ["sub/uno.mp3", "uno.mp3"])
        self.assertEqual(self.probe_stream(out / "uno.mp3")["codec_name"], "mp3")
        self.assertTrue((self.src / "uno.wav").is_file(), "el original no se toca")
        self.assertFalse((out / "analysis.csv").exists())
        again = self.run_cli("convert", str(self.src), "-o", str(out), "--mp3-quality", "v2")
        self.assertIn("ya al día 2", again.stdout)
        self.assertIn("convertidos 0", again.stdout)

    def test_convert_to_wav_and_format_change_replaces_old_output(self):
        out = self.tmp / "fmt"
        mp3 = self.run_cli("convert", str(self.src / "uno.wav"), "-o", str(out), "--format", "mp3", "--mp3-quality", "v2")
        self.assertEqual(mp3.returncode, 0, mp3.stdout + mp3.stderr)
        self.assertEqual([p.name for p in out.glob("*.mp3")], ["uno.mp3"])
        wav = self.run_cli("convert", str(self.src / "uno.wav"), "-o", str(out), "--format", "wav", "--wav-bits", "24")
        self.assertEqual(wav.returncode, 0, wav.stdout + wav.stderr)
        self.assertEqual([p.name for p in out.glob("*.mp3")], [], "la salida vieja del mismo origen se sustituye")
        self.assertEqual(self.probe_stream(out / "uno.wav")["codec_name"], "pcm_s24le")

    def test_name_collision_gets_a_number(self):
        out = self.tmp / "coll"
        a, b = self.tmp / "a", self.tmp / "b"
        for d in (a, b):
            d.mkdir()
            shutil.copy(self.src / "uno.wav", d / "uno.wav")
        r = self.run_cli("convert", str(a / "uno.wav"), str(b / "uno.wav"), "-o", str(out), "--format", "wav")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sorted(p.name for p in out.glob("*.wav")), ["uno (2).wav", "uno.wav"])

    def test_broken_file_is_counted_and_does_not_stop_the_batch(self):
        d = self.tmp / "broken"
        d.mkdir()
        (d / "mal.wav").write_bytes(b"esto no es audio")
        shutil.copy(self.src / "uno.wav", d / "bien.wav")
        out = self.tmp / "brk"
        r = self.run_cli("convert", str(d), "-o", str(out))
        self.assertEqual(r.returncode, 1)
        self.assertIn("con error 1", r.stdout)
        self.assertTrue((out / "bien.mp3").is_file())

    def test_analyze_cli_writes_the_csv(self):
        csv_path = self.tmp / "res" / "analysis.csv"
        r = self.run_cli("analyze", str(self.src), "-o", str(csv_path))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        raw = csv_path.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "BOM para que Excel lo abra bien")
        rows = [line.split(",") for line in raw.decode("utf-8-sig").splitlines()]
        self.assertEqual(rows[0], ["archivo", "bpm", "tonalidad", "energia", "mood", "inicio", "fin", "duracion"])
        by_bpm = sorted(rows[1:], key=lambda x: x[1])
        self.assertEqual([x[1:3] for x in by_bpm], [["128", "C"], ["140", "Dm"]])
        for row in rows[1:]:
            self.assertTrue(1 <= int(row[3]) <= 10)
            self.assertEqual(row[5], "00:00:000")
            self.assertEqual(row[6], row[7], "pista completa: fin == duración")
            self.assertRegex(row[7], r"^\d{2,}:\d{2}:\d{3}$")
        self.assertNotIn(b"\r\r", raw)
        self.assertFalse(list(self.tmp.glob("res/*.tmp")))

    def test_spectrogram_cli(self):
        out = self.tmp / "spec"
        r = self.run_cli("spectrogram", str(self.src / "uno.wav"), "-o", str(out), "--width", "800", "--height", "400",
                         "--from", "0:02", "--to", "0:06", "--fscale", "log")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        png = out / "uno.spectrogram.png"
        self.assertEqual(png.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        again = self.run_cli("spectrogram", str(self.src / "uno.wav"), "-o", str(out))
        self.assertIn("ya existe", again.stdout)


@unittest.skipUnless(HAVE_FFMPEG and np is not None, "necesita ffmpeg y numpy")
class WebServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="ap_web_"))
        cls.src = cls.tmp / "src"
        cls.src.mkdir()
        synth(cls.src / "tema.wav", 140, 2, True, bars=8)
        cls.token, cls.job, cls.specs = "tok123", ap.JobRunner(), ap.SpecStore()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ap.make_handler(cls.job, cls.specs, cls.token, 0))
        cls.port = cls.server.server_address[1]
        cls.server.RequestHandlerClass = ap.make_handler(cls.job, cls.specs, cls.token, cls.port)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.job.cancel()
        cls.server.shutdown()
        cls.server.server_close()
        cls.specs.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, path, body=None, token=True, host=None, raw=False):
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if token:
            headers["X-AP-Token"] = self.token
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        rq = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=headers)
        try:
            with urllib.request.urlopen(rq) as r:
                content = r.read()
                return r.status, (content if raw else json.loads(content))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_guards(self):
        self.assertEqual(self.req("/api/state", token=False)[0], 403)
        self.assertEqual(self.req("/api/state", host="evil.com")[0], 403)
        self.assertEqual(self.req("/api/state")[0], 200)

    def test_index_gets_token_and_version(self):
        code, html = self.req("/", token=False, raw=True)
        self.assertEqual(code, 200)
        self.assertIn(self.token.encode(), html)
        self.assertNotIn(b"__TOKEN__", html)
        self.assertNotIn(b"__VERSION__", html)

    def test_browse_lists_only_audio(self):
        (self.src / "x.txt").write_text("hola")
        code, d = self.req("/api/browse?path=" + str(self.src).replace("\\", "/"))
        self.assertEqual(code, 200)
        self.assertEqual([f["name"] for f in d["files"]], ["tema.wav"])

    def test_full_convert_job_through_the_api(self):
        out = self.tmp / "out"
        code, r = self.req("/api/start", {"mode": "convert", "inputs": [str(self.src)], "output": str(out),
                                          "format": "wav", "wav_bits": "16"})
        self.assertEqual(code, 200, r)
        j = {}
        for _ in range(120):
            code, j = self.req("/api/job?since=0")
            if j["state"] != "running":
                break
            time.sleep(0.5)
        self.assertEqual(j["state"], "done", j)
        code, res = self.req("/api/results?output=" + str(out).replace("\\", "/"))
        self.assertEqual([(i["status"], i["id"], i["output"]["file"]) for i in res["items"]], [("ok", "tema", "tema.wav")])
        self.assertEqual(self.req("/api/start", {"mode": "run", "inputs": [str(self.src)], "output": str(out)})[0], 400)

    def test_analyze_api_csv_and_save(self):
        code, r = self.req("/api/analyze", {"file": str(self.src / "tema.wav"), "options": {"key_format": "camelot"}})
        self.assertEqual(code, 200, r)
        self.assertEqual(len(r["rows"]), 1)
        row = r["rows"][0]
        self.assertEqual((row["file"], row["bpm"], row["key"]), ("tema.wav", "140", "7A"))
        self.assertTrue(1 <= row["energy"] <= 10 and row["mood"])
        bad = self.tmp / "mal.wav"
        bad.write_bytes(b"no es audio")
        err = self.req("/api/analyze", {"file": str(bad)})[1]["rows"][0]
        parts = self.req("/api/analyze", {"file": str(self.src / "tema.wav"),
                                          "options": {"split": "fixed", "split_seconds": "5"}})[1]["rows"]
        self.assertGreater(len(parts), 1)
        self.assertTrue(err["error"])
        self.assertEqual(self.req("/api/analyze", {"file": str(self.src / "tema.wav"), "options": {"bpm_min": "x"}})[0], 400)
        self.assertEqual(self.req("/api/analyze", {"file": str(self.tmp / "nada.txt")})[0], 400)
        code, csv_bytes = self.req("/api/analyze/csv", {"rows": [row, err]}, raw=True)
        self.assertEqual(code, 200)
        lines = csv_bytes.decode("utf-8-sig").splitlines()
        self.assertEqual(lines[0], "archivo,bpm,tonalidad,energia,mood,inicio,fin,duracion")
        self.assertEqual(len(lines), 2, "la fila con error no va al CSV")
        saved = self.req("/api/analyze/save", {"rows": [row], "output": str(self.tmp / "csvout")})[1]
        self.assertTrue(Path(saved["path"]).is_file())
        self.assertEqual(self.req("/api/analyze/save", {"rows": [row], "output": ""})[0], 400)

    def test_spectrogram_api_serves_by_id_only(self):
        code, r = self.req("/api/spectrogram", {"file": str(self.src / "tema.wav"),
                                                "options": {"width": 600, "height": 300}})
        self.assertEqual(code, 200, r)
        code, png = self.req("/api/spectrogram/image?id=" + r["id"], raw=True)
        self.assertEqual(png[:4], b"\x89PNG")
        self.assertEqual(self.req("/api/spectrogram/image?id=../../etc/passwd")[0], 400)
        saved = self.req("/api/spectrogram/save", {"id": r["id"], "output": str(self.tmp / "saved")})[1]
        self.assertTrue(Path(saved["path"]).is_file())
        # mismo audio otra vez: se sobrescribe; otro audio con el mismo nombre: se numera
        self.assertEqual(self.req("/api/spectrogram/save", {"id": r["id"], "output": str(self.tmp / "saved")})[1]["path"], saved["path"])
        other = self.tmp / "otra"
        other.mkdir(exist_ok=True)
        shutil.copy(self.src / "tema.wav", other / "tema.wav")
        r2 = self.req("/api/spectrogram", {"file": str(other / "tema.wav"), "options": {"width": 600, "height": 300}})[1]
        second = self.req("/api/spectrogram/save", {"id": r2["id"], "output": str(self.tmp / "saved")})[1]
        self.assertTrue(second["path"].endswith("tema (2).spectrogram.png"), second)
        (self.src / "x.txt").write_text("hola")
        self.assertEqual(self.req("/api/spectrogram", {"file": str(self.src / "x.txt")})[0], 400)
        self.assertEqual(self.req("/api/spectrogram", {"file": str(self.src / "tema.wav"),
                                                       "options": {"color": "x"}})[0], 400)

    def test_expand_folders(self):
        code, r = self.req("/api/expand", {"inputs": [str(self.src), str(self.src / "tema.wav")]})
        self.assertEqual([Path(f).name for f in r["files"]], ["tema.wav"], "sin repetidos")


if __name__ == "__main__":
    unittest.main()
