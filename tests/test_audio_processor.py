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

    def test_duration_and_bpm_labels(self):
        self.assertEqual(ap.duration_label(185), "03m05s")
        self.assertEqual(ap.duration_label(0), "00m00s")
        self.assertEqual(ap.duration_label(59.6), "01m00s")
        self.assertEqual(ap.duration_label(60.5), "01m01s")
        self.assertEqual(ap.duration_label(125 * 60 + 3), "125m03s")
        self.assertEqual(ap.bpm_label(139.6), "140")
        self.assertEqual(ap.bpm_label(140.5, 1), "140.5")
        self.assertEqual(ap.bpm_label(140.0, 1), "140")
        self.assertEqual(ap.bpm_label(None), "NA")

    def test_build_name_never_stacks_suffixes(self):
        a = {"bpm": 140.0, "tonic": 2, "mode": "minor"}
        first = ap.build_name("mi_loop", a, 185, ap.RENAME_DEFAULTS)
        self.assertEqual(first, "mi_loop__140bpm__Dm__03m05s")
        self.assertEqual(ap.build_name(first, a, 185, ap.RENAME_DEFAULTS), first)
        na = ap.build_name("x", {"bpm": None, "tonic": None, "mode": None}, 5, ap.RENAME_DEFAULTS)
        self.assertEqual(na, "x__NAbpm__NA__00m05s")
        self.assertEqual(ap.strip_suffix(na), "x")
        self.assertEqual(ap.strip_suffix("a__b__c"), "a__b__c")

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
        mode, argv, _ = ap.build_cli_args({"mode": "dry", "inputs": ["a"], "output": "o", "format": "mp3",
                                           "mp3_quality": "v0", "bpm_min": "80", "write_tags": False})
        self.assertEqual(mode, "run")
        self.assertIn("--dry-run", argv)
        self.assertIn("--no-tags", argv)
        base = {"mode": "run", "inputs": ["a"], "output": "o"}
        for bad in ({"mode": "x", "inputs": ["a"], "output": "o"}, {"mode": "run", "inputs": [], "output": "o"},
                    {**base, "output": ""}, {**base, "format": "ogg"},
                    {**base, "bpm_min": "200", "bpm_max": "100"}, {**base, "bpm_min": "abc"}):
            with self.assertRaises((ValueError, SystemExit), msg=str(bad)):
                ap.build_cli_args(bad)


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
        opts = dict(ap.RENAME_DEFAULTS)
        for name, (bpm, tonic, minor) in self.cases.items():
            info = ap.probe(self.tmp / f"{name}.wav")
            res = ap.analyze_audio(self.tmp / f"{name}.wav", info["duration"], opts)
            self.assertAlmostEqual(res["bpm"], bpm, delta=0.6, msg=name)
            self.assertEqual((res["tonic"], res["mode"]), (tonic, "minor" if minor else "major"), name)

    def test_silence_and_short_audio_do_not_crash(self):
        silent = self.tmp / "silence.wav"
        write_wav(silent, b"\0\0" * SR * 5)
        res = ap.analyze_audio(silent, 5.0, dict(ap.RENAME_DEFAULTS))
        self.assertIsNone(res["bpm"])
        self.assertIsNone(res["tonic"])
        tiny = self.tmp / "tiny.wav"
        write_wav(tiny, b"\x10\x10" * 2000)
        res = ap.analyze_audio(tiny, 0.05, dict(ap.RENAME_DEFAULTS))
        self.assertIsNone(res["bpm"])


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

    def test_original_format_is_a_renamed_copy_and_idempotent(self):
        out = self.tmp / "orig"
        r = self.run_cli("run", str(self.src), "-o", str(out))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        names = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.wav"))
        self.assertEqual(names, ["sub/uno__128bpm__C__00m16s.wav", "uno__140bpm__Dm__00m14s.wav"])
        self.assertEqual((out / "uno__140bpm__Dm__00m14s.wav").read_bytes(), (self.src / "uno.wav").read_bytes())
        self.assertTrue((self.src / "uno.wav").is_file(), "el original no se toca")
        self.assertTrue((out / "analysis.csv").is_file())
        again = self.run_cli("run", str(self.src), "-o", str(out))
        self.assertIn("ya al día 2", again.stdout)
        self.assertIn("procesados 0", again.stdout)

    def test_mp3_conversion_writes_tags_and_reprocess_replaces_old_name(self):
        out = self.tmp / "mp3"
        r = self.run_cli("run", str(self.src / "uno.wav"), "-o", str(out), "--format", "mp3", "--mp3-quality", "v2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        mp3 = out / "uno__140bpm__Dm__00m14s.mp3"
        self.assertTrue(mp3.is_file())
        probe = subprocess.run([ap.tool("ffprobe"), "-v", "error", "-show_format", "-print_format", "json", str(mp3)],
                               capture_output=True, text=True)
        tags = json.loads(probe.stdout)["format"]["tags"]
        self.assertEqual((tags.get("TBPM"), tags.get("TKEY")), ("140", "Dm"))
        # cambia el formato del nombre: la salida vieja de este mismo origen se sustituye, no se acumula
        r = self.run_cli("run", str(self.src / "uno.wav"), "-o", str(out), "--format", "mp3", "--mp3-quality", "v2",
                         "--key-format", "camelot")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sorted(p.name for p in out.glob("*.mp3")), ["uno__140bpm__7A__00m14s.mp3"])

    def test_dry_run_writes_nothing(self):
        out = self.tmp / "dry"
        r = self.run_cli("run", str(self.src), "-o", str(out), "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("uno__140bpm__Dm__00m14s", r.stdout)
        self.assertFalse(out.exists())

    def test_name_collision_gets_a_number(self):
        out = self.tmp / "coll"
        a, b = self.tmp / "a", self.tmp / "b"
        for d in (a, b):
            d.mkdir()
            shutil.copy(self.src / "uno.wav", d / "uno.wav")
        r = self.run_cli("run", str(a / "uno.wav"), str(b / "uno.wav"), "-o", str(out))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sorted(p.name for p in out.glob("*.wav")),
                         ["uno__140bpm__Dm__00m14s (2).wav", "uno__140bpm__Dm__00m14s.wav"])

    def test_broken_file_is_counted_and_does_not_stop_the_batch(self):
        d = self.tmp / "broken"
        d.mkdir()
        (d / "mal.wav").write_bytes(b"esto no es audio")
        shutil.copy(self.src / "uno.wav", d / "bien.wav")
        out = self.tmp / "brk"
        r = self.run_cli("run", str(d), "-o", str(out))
        self.assertEqual(r.returncode, 1)
        self.assertIn("con error 1", r.stdout)
        self.assertTrue(any(out.glob("bien__*.wav")))

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

    def test_full_rename_job_through_the_api(self):
        out = self.tmp / "out"
        code, r = self.req("/api/start", {"mode": "run", "inputs": [str(self.src)], "output": str(out),
                                          "format": "original"})
        self.assertEqual(code, 200, r)
        j = {}
        for _ in range(120):
            code, j = self.req("/api/job?since=0")
            if j["state"] != "running":
                break
            time.sleep(0.5)
        self.assertEqual(j["state"], "done", j)
        code, res = self.req("/api/results?output=" + str(out).replace("\\", "/"))
        self.assertEqual([(i["status"], round(i["bpm"]), i["key_name"]) for i in res["items"]], [("ok", 140, "Dm")])

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
        code, r = self.req("/api/expand", {"inputs": [str(self.src)]})
        self.assertEqual([Path(f).name for f in r["files"]], ["tema.wav"])


if __name__ == "__main__":
    unittest.main()
