"""
Cursed_Vishleshan
-----------------
Run it -> choose model + languages + what to process -> get:
  - <video>_transcript.txt           : full script in the original spoken language(s)
  - <video>_transcript_<Lang>.txt    : full script translated into each output language you chose
  - <video>_summary[_<Lang>].md      : summary in each output language you chose

Sources:  a video/audio file  |  a whole folder (batch, e.g. overnight)  |  a YouTube or other
          link (playlists too)  |  a watched folder (new videos processed automatically)  |
          live microphone  |  live system audio  |  a call (mic = You + PC sound = Them)
Extras:   only part of a video (e.g. 10:00-25:00), voice cleanup for noisy/garbled audio
          (AI voice isolation + AI noise removal, offline or online), custom vocabulary,
          live translated captions (always-on-top bar), keyword alerts, read aloud (text-to-speech)
It also detects which languages are spoken (and where), uses an NVIDIA GPU automatically if
present, and keeps a searchable History of everything processed.

Live microphone / system audio: press Record, the text appears as it's spoken; then translate,
copy or save (saved to Documents\\Cursed_Vishleshan, together with downloads and history).

Transcription: faster-whisper, runs locally (offline after the first model download).
Summaries and translations use (tried in order, first one that works is used):
  - claude   : Claude Code CLI (`claude -p`)  -> best quality, needs internet
  - ollama   : local model via Ollama         -> offline
  - lmstudio : local model via LM Studio      -> offline
Without any of these, English can still be produced offline by Whisper itself.

Setup (one time, needs internet):
    pip install faster-whisper sounddevice PyAudioWPatch yt-dlp edge-tts
    ffmpeg on PATH
    Optional GPU:  pip install nvidia-cublas-cu12 nvidia-cudnn-cu12==9.*
    Voice cleanup "Studio AI":    pip install demucs     (DeepFilterNet downloads itself once)
    Voice cleanup "Online AI":    an ElevenLabs API key (entered in the settings window)
    Optional live noise cleanup:  pip install noisereduce
    Optional: Claude Code installed + logged in
    Optional: Ollama  (e.g. `ollama pull gemma3:4b`  or  `ollama pull qwen2.5:7b`)
    Optional: LM Studio with a model downloaded + local server enabled
    Optional: Claude Code installed + logged in
    Optional: Ollama  (e.g. `ollama pull gemma3:4b`  or  `ollama pull qwen2.5:7b`)
    Optional: LM Studio with a model downloaded + local server enabled
"""

import os
import re
import sys
import json
import time
import wave
import queue
import base64
import datetime
import shutil
import socket
import fnmatch
import inspect
import tempfile
import threading
import subprocess
import contextlib
import urllib.request
from collections import Counter
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# ======================= Settings =======================
# Defaults (used the first time)
WHISPER_MODEL = "small"
SPOKEN_LANGUAGE = None                  # None = auto-detect, or e.g. "hi", "en"
OUTPUT_LANGUAGES = ["Original", "English"]

# --- Transcription ---
DEVICE = "auto"              # "auto" = use an NVIDIA GPU if available, else CPU. Or "cuda" / "cpu"
COMPUTE_TYPE = "auto"        # "auto" = float16 on GPU, int8 on CPU

# --- Language detection ---
DETECT_LANGUAGES = True      # check which languages are spoken, and where
DETECT_WINDOW_SEC = 30       # size of each checked piece of audio
MAX_DETECT_WINDOWS = 120     # long videos: check at most this many pieces (spread evenly)
MIN_LANGUAGE_SHARE = 0.10    # a language counts as "used" if it's at least 10% of the speech

# --- Summary / translation backends ---
BACKEND = "auto"             # "auto", "claude", "ollama", "lmstudio"
BACKEND_ORDER = ["claude", "ollama", "lmstudio"]

# --- Frames (what's shown on screen) ---
USE_FRAMES = True
MAX_FRAMES = 20              # frames given to Claude
LOCAL_SEND_FRAMES = False    # send frames to local models too (needs a VISION model,
                             #   e.g. gemma3:4b, qwen2.5vl:7b, llava in Ollama)
LOCAL_MAX_FRAMES = 6

# --- Claude Code ---
CLAUDE_TIMEOUT_SEC = 1200

# --- Ollama ---
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = ""            # "" = first installed model. e.g. "gemma3:4b", "qwen2.5:7b"
OLLAMA_NUM_CTX = 16384       # lower (8192) if you run out of RAM

# --- LM Studio ---
LMSTUDIO_URL = "http://localhost:1234"
LMSTUDIO_MODEL = ""          # "" = first available model

# --- Live microphone ---
LIVE_COMMIT_SEC = 8          # lock in finished sentences once this much speech is waiting
LIVE_MAX_PENDING_SEC = 20    # never keep more than this much un-locked audio
LIVE_SILENCE_COMMIT_SEC = 0.9  # a pause this long locks in what was said
LIVE_BEAM_SIZE = 1           # 1 = fastest live updates (final pass after Stop uses 5)
SAVE_DIR = Path.home() / "Documents" / "Cursed_Vishleshan"   # mic/system recordings, downloads, history

# --- YouTube / links ---
DOWNLOAD_MAX_HEIGHT = 720    # video quality to download (lower = faster; frames only need ~720p)
DOWNLOAD_AUDIO_ONLY = False  # True = much faster downloads, but no frames for the summary

# --- Batch ---
BATCH_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".mpg",
                    ".mpeg", ".3gp", ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
KEEP_PC_AWAKE = True         # stop Windows from sleeping during batch / long jobs

# --- Watch folder ---
WATCH_INTERVAL_SEC = 5       # how often to look for new videos
WATCH_STABLE_SEC = 8         # a file must stop growing for this long (finished copying) first

# --- Local model tuning ---
LOCAL_TIMEOUT_SEC = 1800
CHUNK_CHARS = 12000          # long transcripts are summarized in parts of this size first
TRANSLATE_CHUNK_CHARS = 4000 # transcripts are translated in parts of this size
# ========================================================

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SR = 16000
VIDEO_TYPES = [
    ("Video files", "*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.wmv *.flv *.mpg *.mpeg *.3gp"),
    ("Audio files", "*.mp3 *.wav *.m4a *.aac *.ogg *.flac"),
    ("All files", "*.*"),
]

# All languages Whisper can recognise
LANG_NAMES = {
    "en": "English", "zh": "Chinese", "de": "German", "es": "Spanish", "ru": "Russian",
    "ko": "Korean", "fr": "French", "ja": "Japanese", "pt": "Portuguese", "tr": "Turkish",
    "pl": "Polish", "ca": "Catalan", "nl": "Dutch", "ar": "Arabic", "sv": "Swedish",
    "it": "Italian", "id": "Indonesian", "hi": "Hindi", "fi": "Finnish", "vi": "Vietnamese",
    "he": "Hebrew", "uk": "Ukrainian", "el": "Greek", "ms": "Malay", "cs": "Czech",
    "ro": "Romanian", "da": "Danish", "hu": "Hungarian", "ta": "Tamil", "no": "Norwegian",
    "th": "Thai", "ur": "Urdu", "hr": "Croatian", "bg": "Bulgarian", "lt": "Lithuanian",
    "la": "Latin", "mi": "Maori", "ml": "Malayalam", "cy": "Welsh", "sk": "Slovak",
    "te": "Telugu", "fa": "Persian", "lv": "Latvian", "bn": "Bengali", "sr": "Serbian",
    "az": "Azerbaijani", "sl": "Slovenian", "kn": "Kannada", "et": "Estonian",
    "mk": "Macedonian", "br": "Breton", "eu": "Basque", "is": "Icelandic", "hy": "Armenian",
    "ne": "Nepali", "mn": "Mongolian", "bs": "Bosnian", "kk": "Kazakh", "sq": "Albanian",
    "sw": "Swahili", "gl": "Galician", "mr": "Marathi", "pa": "Punjabi", "si": "Sinhala",
    "km": "Khmer", "sn": "Shona", "yo": "Yoruba", "so": "Somali", "af": "Afrikaans",
    "oc": "Occitan", "ka": "Georgian", "be": "Belarusian", "tg": "Tajik", "sd": "Sindhi",
    "gu": "Gujarati", "am": "Amharic", "yi": "Yiddish", "lo": "Lao", "uz": "Uzbek",
    "fo": "Faroese", "ht": "Haitian Creole", "ps": "Pashto", "tk": "Turkmen",
    "nn": "Nynorsk", "mt": "Maltese", "sa": "Sanskrit", "lb": "Luxembourgish",
    "my": "Myanmar", "bo": "Tibetan", "tl": "Tagalog", "mg": "Malagasy", "as": "Assamese",
    "tt": "Tatar", "haw": "Hawaiian", "ln": "Lingala", "ha": "Hausa", "ba": "Bashkir",
    "jw": "Javanese", "su": "Sundanese", "yue": "Cantonese",
}
LANG_CODES = {v: k for k, v in LANG_NAMES.items()}

# Shown in the settings window
SPOKEN_CHOICES = ["Auto-detect", "English", "Hindi", "Urdu", "Punjabi", "Bengali", "Marathi",
                  "Gujarati", "Tamil", "Telugu", "Kannada", "Malayalam", "Nepali", "Arabic",
                  "Chinese", "Japanese", "Korean", "French", "German", "Spanish", "Russian"]
OUTPUT_CHOICES = ["Original"] + SPOKEN_CHOICES[1:]


def lang_name(code):
    return LANG_NAMES.get(code, code)


# ---------------------------------------------------------------- general helpers
def fmt(t: float) -> str:
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def internet_ok() -> bool:
    for host in ("api.anthropic.com", "1.1.1.1"):
        try:
            socket.create_connection((host, 443), timeout=3).close()
            return True
        except OSError:
            continue
    return False


# Local HTTP calls must never go through a system proxy
_local_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_json(url, payload=None, timeout=10):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with _local_opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def strip_thinking(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def split_chunks(text: str, size: int):
    chunks, cur = [], ""
    for line in text.splitlines():
        if cur and len(cur) + len(line) + 1 > size:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        chunks.append(cur)
    return chunks


def pick_evenly(items, n):
    if len(items) <= n:
        return list(items)
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def safe_name(s: str) -> str:
    return re.sub(r"[^\w\-]+", "_", s).strip("_")


def parse_time(s: str):
    """'90' / '10:00' / '1:02:03' -> seconds.  '' -> None.  Raises ValueError on bad input."""
    s = (s or "").strip()
    if not s:
        return None
    parts = s.split(":")
    if len(parts) > 3:
        raise ValueError(s)
    sec = 0.0
    for p in parts:
        v = float(p)
        if v < 0:
            raise ValueError(s)
        sec = sec * 60 + v
    return sec


# ---------------------------------------------------------------- custom vocabulary
VOCAB_FILE = Path(__file__).with_name("vocabulary.txt")
VOCAB = []


def load_vocab():
    try:
        lines = VOCAB_FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    return [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]


_hotwords_ok = {}


def vocab_kwargs(model):
    """Extra transcribe() arguments that make Whisper prefer the custom spellings."""
    if not VOCAB:
        return {}
    key = type(model)
    if key not in _hotwords_ok:
        try:
            _hotwords_ok[key] = "hotwords" in inspect.signature(model.transcribe).parameters
        except Exception:
            _hotwords_ok[key] = False
    words = ", ".join(VOCAB)
    if _hotwords_ok[key]:
        return {"hotwords": words}           # applied to every 30s window
    return {"initial_prompt": f"Glossary: {words}."}


def vocab_note():
    if not VOCAB:
        return ""
    return ("\nIf any of these names/terms occur, spell them exactly like this: "
            + ", ".join(VOCAB) + ".")


# ---------------------------------------------------------------- voice cleanup
# off / light / strong  = quick ffmpeg filters
# studio                = offline AI: Demucs (isolate voices) -> DeepFilterNet (remove noise) -> level
# online                = ElevenLabs Voice Isolator (needs API key; audio is uploaded) -> level
NOISE_CHOICES = [("Off", "off"), ("Light filter", "light"), ("Strong filter", "strong"),
                 ("Studio AI (offline)", "studio"), ("Online AI (ElevenLabs)", "online")]
NOISE_HELP = {
    "off": "No cleanup.",
    "light": "Light filter: quick, gentle hiss/hum reduction.",
    "strong": "Strong filter: quick, heavy noise reduction (can dull quiet voices).",
    "studio": "Studio AI: isolates the voices from music/crowd/background, then AI noise removal. "
              "Offline. Slow on CPU (about real time), much faster with an NVIDIA GPU.",
    "online": "Online AI: ElevenLabs Voice Isolator - excellent on very noisy audio. Needs an API key, "
              "uses credits, and the audio is uploaded to ElevenLabs.",
}
NOISE_FILTERS = {
    # measured on noisy test audio: Light ~ +5-8 dB cleaner, Strong ~ +30-40 dB (speech level kept)
    "light": "highpass=f=80,lowpass=f=7600,afftdn=nr=12:nf=-30:tn=1",
    "strong": "highpass=f=100,lowpass=f=7000,afftdn=nr=25:nf=-20:tn=1,afftdn=nr=15:nf=-30",
}
FINAL_LEVEL = "highpass=f=70,loudnorm=I=-20:TP=-2:LRA=11"   # even out the volume of the cleaned voice
DEMUCS_MODEL = "auto"        # "auto" = htdemucs_ft on GPU (best), htdemucs on CPU (4x faster)
DEMUCS_CHUNK_SEC = 120       # audio is separated in pieces of this length (keeps memory low)
TOOLS_DIR = Path(__file__).with_name("tools")
ELEVEN_PIECE_SEC = 50 * 60  # ElevenLabs takes up to 1 hour per file; send 50-minute pieces


def _ff(*args):
    ff = shutil.which("ffmpeg")
    r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", *map(str, args)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise RuntimeError("ffmpeg: " + (r.stderr or "")[-300:])


def _wav_len(path):
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def demucs_isolate(src44: Path, out: Path):
    """Separate the voices from everything else with Demucs (offline AI). Returns out or None."""
    try:
        import numpy as np
        import torch
        from demucs.pretrained import get_model
        from demucs.apply import apply_model
    except ImportError:
        print("  [i] Voice isolation needs:  pip install demucs   - skipping this step.")
        return None
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    name = DEMUCS_MODEL if DEMUCS_MODEL != "auto" else ("htdemucs_ft" if dev == "cuda" else "htdemucs")
    print(f"  Isolating voices with Demucs ({name}, {'GPU' if dev == 'cuda' else 'CPU'}) - "
          f"first use downloads the model...")
    try:
        model = get_model(name)
        model.eval()
        vi = model.sources.index("vocals")
        with wave.open(str(src44), "rb") as r, wave.open(str(out), "wb") as w:
            sr, ch, n = r.getframerate(), r.getnchannels(), r.getnframes()
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            step, ctx, t0 = int(DEMUCS_CHUNK_SEC * sr), int(4 * sr), time.time()
            for start in range(0, n, step):
                a, b = max(0, start - ctx), min(n, start + step + ctx)
                r.setpos(a)
                x = np.frombuffer(r.readframes(b - a), np.int16).reshape(-1, ch).T.astype(np.float32) / 32768
                if ch == 1:
                    x = np.vstack([x, x])
                x = torch.from_numpy(np.ascontiguousarray(x))
                ref = x.mean(0)
                m, s = ref.mean(), ref.std() + 1e-8
                with torch.no_grad():
                    y = apply_model(model, ((x - m) / s)[None], device=dev, split=True,
                                    overlap=0.25, progress=False)[0]
                voc = (y[vi] * s + m).mean(0).cpu().numpy()
                keep = voc[start - a: start - a + min(step, n - start)]
                w.writeframes((np.clip(keep, -1, 1) * 32767).astype(np.int16).tobytes())
                done = min(start + step, n) / n
                el = time.time() - t0
                print(f"\r    {done:4.0%}  (about {fmt(el / done - el)} left)", end="", flush=True)
        print()
        return out
    except Exception as e:
        print(f"\n  [!] Voice isolation failed ({str(e)[:150]}) - continuing without it.")
        return None


def ensure_deepfilter_exe(online):
    """The standalone DeepFilterNet program (no Python packages needed). Downloaded once."""
    exe = TOOLS_DIR / ("deep-filter.exe" if os.name == "nt" else "deep-filter")
    if exe.exists():
        return exe
    if not online:
        return None
    plat = {"nt": r"x86_64-pc-windows.*\.exe$"}.get(os.name, r"x86_64-unknown-linux")
    if sys.platform == "darwin":
        plat = r"apple-darwin"
    try:
        req = urllib.request.Request("https://api.github.com/repos/Rikorose/DeepFilterNet/releases",
                                     headers={"User-Agent": "video-summarizer"})
        with urllib.request.urlopen(req, timeout=30) as r:
            releases = json.loads(r.read().decode("utf-8"))
        asset = next((a for rel in releases for a in rel.get("assets", [])
                      if a["name"].startswith("deep-filter") and re.search(plat, a["name"])), None)
        if not asset:
            print("  [i] No DeepFilterNet program found for this system.")
            return None
        print(f"  Downloading DeepFilterNet (one time, {asset['size'] / 1e6:.0f} MB): {asset['name']}")
        TOOLS_DIR.mkdir(exist_ok=True)
        tmp = exe.with_suffix(".part")
        urllib.request.urlretrieve(asset["browser_download_url"], tmp)
        tmp.replace(exe)
        if os.name != "nt":
            exe.chmod(0o755)
        return exe
    except Exception as e:
        print(f"  [i] Could not download DeepFilterNet: {str(e)[:120]}")
        return None


def deepfilter_denoise(src: Path, tmp: Path, online):
    """AI noise removal with DeepFilterNet. Returns the cleaned file or None."""
    in48 = tmp / "df_in.wav"
    _ff("-i", src, "-ac", 1, "-ar", 48000, "-c:a", "pcm_s16le", in48)
    exe = ensure_deepfilter_exe(online)
    if exe:
        print("  Removing noise with DeepFilterNet (AI, offline)...")
        od = tmp / "df_out"
        od.mkdir(exist_ok=True)
        for args in (["--pf", "-o", od, in48], ["-o", od, in48]):   # --pf = extra post-filter
            r = subprocess.run([str(exe), *map(str, args)], capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            outs = sorted(od.glob("*.wav"))
            if r.returncode == 0 and outs:
                return outs[0]
        print(f"  [!] DeepFilterNet program failed: {(r.stderr or r.stdout)[-150:]}")
    try:   # the Python package, if installed
        import numpy as np
        import torch
        from df.enhance import enhance, init_df
        print("  Removing noise with DeepFilterNet (Python package)...")
        model, state, _ = init_df()
        out = tmp / "df_py.wav"
        with wave.open(str(in48), "rb") as r, wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(48000)
            n, step = r.getnframes(), 48000 * 60
            for start in range(0, n, step):
                x = np.frombuffer(r.readframes(step), np.int16).astype(np.float32) / 32768
                y = enhance(model, state, torch.from_numpy(x)[None]).squeeze().numpy()
                w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())
        return out
    except ImportError:
        pass
    except Exception as e:
        print(f"  [!] DeepFilterNet failed: {str(e)[:150]}")
    return None


def elevenlabs_isolate(src: Path, tmp: Path, key):
    """ElevenLabs Voice Isolator (online). Long audio is sent in pieces. Returns a WAV or None."""
    total = _wav_len(src)
    piece, outs = ELEVEN_PIECE_SEC, []
    print(f"  Uploading to ElevenLabs Voice Isolator ({fmt(total)} of audio)...")
    for i, start in enumerate(range(0, int(total) + 1, piece)):
        if start >= total:
            break
        part = tmp / f"el_in_{i}.flac"
        _ff("-ss", start, "-i", src, "-t", piece, "-ac", 1, part)
        boundary = "----vidsum" + os.urandom(8).hex()
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"{part.name}\"\r\n"
                f"Content-Type: audio/flac\r\n\r\n").encode() + part.read_bytes() + \
               f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request("https://api.elevenlabs.io/v1/audio-isolation", data=body, method="POST",
                                     headers={"xi-api-key": key,
                                              "Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=1800) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:200]
            hint = {401: "the API key is wrong", 402: "not enough credits",
                    429: "too many requests / out of credits"}.get(e.code, "")
            print(f"  [!] ElevenLabs error {e.code} {hint}: {msg}")
            return None
        except Exception as e:
            print(f"  [!] ElevenLabs request failed: {str(e)[:150]}")
            return None
        got = tmp / f"el_out_{i}.audio"
        got.write_bytes(data)
        wav_i = tmp / f"el_out_{i}.wav"
        _ff("-i", got, "-ac", 1, "-ar", 44100, wav_i)
        outs.append(wav_i)
        print(f"    piece {i + 1} done")
    if len(outs) == 1:
        return outs[0]
    lst = tmp / "el_list.txt"
    lst.write_text("".join("file '" + o.resolve().as_posix().replace("'", "'\\''") + "'\n" for o in outs),
                   encoding="utf-8")
    out = tmp / "el_joined.wav"
    _ff("-f", "concat", "-safe", 0, "-i", lst, "-c", "copy", out)
    return out


def elevenlabs_key():
    return os.environ.get("ELEVENLABS_API_KEY") or load_settings().get("elevenlabs_key", "")


def prepare_audio(video, clip, noise, tmpdir, online=False):
    """Cut the clip range and/or clean up the voice into a temporary WAV for Whisper.
    Returns (path_for_whisper, start_offset_seconds)."""
    noise = {"ai": "studio"}.get(noise, noise or "off")
    start = float(clip[0] or 0) if clip else 0.0
    end = clip[1] if clip else None
    if not clip and noise == "off":
        return str(video), 0.0
    if not shutil.which("ffmpeg"):
        print("[!] ffmpeg not found - clip range / voice cleanup skipped.")
        return str(video), 0.0
    tmp = Path(tmpdir)
    what = []
    if clip:
        what.append(f"part {fmt(start)} - {fmt(end) if end else 'end'}")
    if noise != "off":
        what.append("voice cleanup: " + dict((v, k) for k, v in NOISE_CHOICES)[noise])
    print("Preparing audio (" + ", ".join(what) + ")...")
    cut = (["-ss", f"{start:.3f}"] if start else []) + ["-i", str(video), "-vn"] + \
          (["-t", f"{max(end - start, 0.1):.3f}"] if end else [])
    t0 = time.time()

    if noise in ("off", "light", "strong"):
        out = tmp / "audio.wav"
        _ff(*cut, "-ac", 1, "-ar", SR, *(["-af", NOISE_FILTERS[noise]] if noise in NOISE_FILTERS else []), out)
        return str(out), start

    # ---- AI cleanup: work on a high-quality copy
    src = tmp / "src.wav"
    _ff(*cut, "-ac", 2, "-ar", 44100, "-c:a", "pcm_s16le", src)
    voice = None
    if noise == "online":
        key = elevenlabs_key()
        if not online:
            print("  [!] Online AI needs internet - using Studio AI (offline) instead.")
        elif not key:
            print("  [!] No ElevenLabs API key saved - using Studio AI (offline) instead.")
        else:
            try:
                voice = elevenlabs_isolate(src, tmp, key)
            except Exception as e:
                print(f"  [!] Online cleanup failed: {str(e)[:150]}")
                voice = None
            if not voice:
                print("  Falling back to Studio AI (offline)...")
    if voice is None:
        iso = demucs_isolate(src, tmp / "vocals.wav") or src
        voice = deepfilter_denoise(iso, tmp, online)
        if voice is None:
            print("  [i] AI noise removal not available - using the Strong filter for this step.")
            voice = tmp / "strong.wav"
            _ff("-i", iso, "-ac", 1, "-ar", SR, "-af", NOISE_FILTERS["strong"], voice)
    out = tmp / "clean.wav"
    _ff("-i", voice, "-ac", 1, "-ar", SR, "-af", FINAL_LEVEL, out)
    print(f"  Voice cleanup finished in {fmt(time.time() - t0)}.")
    return str(out), start


# ---------------------------------------------------------------- read aloud (text-to-speech)
_edge_voices = {}
_EDGE_LOCALE_FIX = {"yue": "zh-HK", "jw": "jv", "no": "nb", "tl": "fil"}

_WIN_TTS_PS = r"""
$ErrorActionPreference = 'Stop'
$text = [IO.File]::ReadAllText('__TXT__', [Text.Encoding]::UTF8)
$out = '__WAV__'
$lang = '__LANG__'
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
  $null = [Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime]
  $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
      $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
      $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
  function Await($op, [Type]$t) {
      $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $null = $task.Wait(-1); $task.Result }
  $synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
  $voice = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices |
           Where-Object { $_.Language -like "$lang*" } | Select-Object -First 1
  if ($voice) { $synth.Voice = $voice; $name = $voice.DisplayName } else { $name = 'NOVOICE' }
  $stream = Await ($synth.SynthesizeTextToStreamAsync($text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
  $reader = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
  $size = [uint32]$stream.Size
  $null = Await ($reader.LoadAsync($size)) ([uint32])
  $bytes = New-Object byte[] $size
  $reader.ReadBytes($bytes)
  [IO.File]::WriteAllBytes($out, $bytes)
  Write-Output "VOICE:$name"
} catch {
  Add-Type -AssemblyName System.Speech
  $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $v = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like "$lang*" } |
       Select-Object -First 1
  if ($v) { $s.SelectVoice($v.VoiceInfo.Name); $name = $v.VoiceInfo.Name } else { $name = 'NOVOICE' }
  $s.SetOutputToWaveFile($out); $s.Speak($text); $s.Dispose()
  Write-Output "VOICE:$name"
}
"""


def _edge_voice(code):
    import asyncio
    import edge_tts
    if code not in _edge_voices:
        prefix = _EDGE_LOCALE_FIX.get(code, code).lower()
        voices = asyncio.run(edge_tts.list_voices())
        match = [v for v in voices
                 if v["Locale"].lower() == prefix or v["Locale"].lower().startswith(prefix + "-")]
        match.sort(key=lambda v: (v.get("Gender") != "Female", "Multilingual" in v["ShortName"]))
        _edge_voices[code] = match[0]["ShortName"] if match else None
    return _edge_voices[code]


def _windows_tts(text, code, wav: Path):
    tmp = wav.with_suffix(".txt")
    tmp.write_text(text, encoding="utf-8")
    q_ = lambda p: str(p).replace("'", "''")
    script = (_WIN_TTS_PS.replace("__TXT__", q_(tmp)).replace("__WAV__", q_(wav))
              .replace("__LANG__", code))
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    finally:
        tmp.unlink(missing_ok=True)
    voice = next((l[6:].strip() for l in r.stdout.splitlines() if l.startswith("VOICE:")), None)
    if not voice or not wav.exists():
        return False, "Windows speech failed: " + (r.stderr or r.stdout)[-200:]
    if voice == "NOVOICE" and code != "en":
        wav.unlink(missing_ok=True)
        return False, (f"No offline {lang_name(code)} voice on this PC. Add one in Windows Settings > "
                       f"Time & language > Language & region > {lang_name(code)} > Language options > "
                       f"Speech (or go online to use Microsoft's online voices).")
    return True, f"Windows voice ({voice if voice != 'NOVOICE' else 'default'}, offline)"


def tts_to_file(text, lang, out_base, online):
    """Speech for `text` in language `lang` (name). Online: Microsoft neural voices via
    edge-tts. Offline: the voices built into Windows. Returns (path, info) or (None, reason)."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return None, "Nothing to read."
    code = LANG_CODES.get(lang, lang if lang in LANG_NAMES else "en")
    out_base = Path(out_base)
    why = "Online voices need:  pip install edge-tts"
    if online:
        try:
            import asyncio
            import edge_tts
            voice = _edge_voice(code)
            why = f"No online {lang_name(code)} voice available"
            if voice:
                mp3 = out_base.with_suffix(".mp3")
                asyncio.run(edge_tts.Communicate(text, voice).save(str(mp3)))
                if mp3.exists() and mp3.stat().st_size > 0:
                    return mp3, f"Microsoft online voice ({voice})"
        except ImportError:
            pass
        except Exception as e:
            print(f"  [read aloud] Online voice failed ({str(e)[:80]}) - trying offline voices.")
    if os.name == "nt":
        wav = out_base.with_suffix(".wav")
        ok, info = _windows_tts(text, code, wav)
        return (wav, info) if ok else (None, info)
    return None, f"{why}; offline voices need Windows." if online else "Offline voices need Windows."


def play_audio(path: Path, stop_event):
    """Play a sound file (blocking) until it ends or stop_event is set. Windows only."""
    if os.name != "nt" or not path:
        return
    import winsound
    wav = Path(path)
    if wav.suffix.lower() != ".wav":
        conv = wav.with_suffix(".play.wav")
        ff = shutil.which("ffmpeg")
        if not ff:
            os.startfile(str(wav))   # let the default player handle mp3
            return
        subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav), str(conv)],
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        wav = conv
    try:
        with wave.open(str(wav), "rb") as w:
            dur = w.getnframes() / float(w.getframerate())
    except Exception:
        dur = 5.0
    winsound.PlaySound(str(wav), winsound.SND_FILENAME | winsound.SND_ASYNC)
    end = time.time() + dur + 0.2
    while time.time() < end and not stop_event.is_set():
        time.sleep(0.1)
    if stop_event.is_set():
        winsound.PlaySound(None, winsound.SND_PURGE)


class SpeechPlayer:
    """Reads texts aloud one after another in a background thread."""

    def __init__(self, online, on_status=None):
        self.online, self.on_status = online, on_status or (lambda s: None)
        self.q, self.stop_ev, self.busy, self.n = queue.Queue(), threading.Event(), False, 0
        self.tmp = Path(tempfile.mkdtemp(prefix="vidsum_tts_"))
        threading.Thread(target=self._run, daemon=True).start()

    def say(self, text, lang):
        self.stop_ev.clear()
        self.q.put((text, lang))

    def stop(self):
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break
        self.stop_ev.set()

    def _run(self):
        while True:
            text, lang = self.q.get()
            self.busy = True
            self.n += 1
            try:
                path, info = tts_to_file(text, lang, self.tmp / f"say{self.n}", self.online)
                self.on_status(("Reading aloud - " + info) if path else info)
                if path and not self.stop_ev.is_set():
                    play_audio(path, self.stop_ev)
            except Exception as e:
                self.on_status(f"Read aloud failed: {e}")
            self.busy = not self.q.empty()
            if not self.busy:
                self.on_status("")


# ---------------------------------------------------------------- Whisper models
WHISPER_MODELS = [
    ("tiny",            "~75 MB",  "Fastest, lowest accuracy"),
    ("base",            "~145 MB", "Very fast, basic accuracy"),
    ("small",           "~485 MB", "Good balance of speed and accuracy"),
    ("medium",          "~1.5 GB", "More accurate, slower"),
    ("large-v3-turbo",  "~1.6 GB", "Near-best accuracy, fast (weak at English translation)"),
    ("large-v3",        "~3.1 GB", "Best accuracy, slowest"),
    ("distil-large-v3", "~1.5 GB", "Fast and accurate - English audio only"),
]
_FALLBACK_REPOS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
}
WHISPER_FILES = ["config.json", "preprocessor_config.json", "model.bin",
                 "tokenizer.json", "vocabulary.*"]
SETTINGS_FILE = Path(__file__).with_name("video_summarizer_settings.json")


def repo_for(name: str) -> str:
    try:
        from faster_whisper.utils import _MODELS
        if name in _MODELS:
            return _MODELS[name]
    except Exception:
        pass
    return _FALLBACK_REPOS.get(name, name)


def is_downloaded(name: str) -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache
        return isinstance(try_to_load_from_cache(repo_for(name), "model.bin"), str)
    except Exception:
        return False


def _folder_bytes(folder: Path) -> int:
    total = 0
    if folder.exists():
        for f in folder.rglob("*"):
            try:
                if f.is_file():
                    total += f.stat().st_size
            except OSError:
                pass
    return total


def download_whisper(name: str, progress_cb):
    """Download a Whisper model into the Hugging Face cache, reporting % progress."""
    from huggingface_hub import snapshot_download, HfApi
    from huggingface_hub.constants import HF_HUB_CACHE

    repo = repo_for(name)
    total = 0
    try:
        info = HfApi().model_info(repo, files_metadata=True)
        total = sum((s.size or 0) for s in info.siblings
                    if any(fnmatch.fnmatch(s.rfilename, p) for p in WHISPER_FILES))
    except Exception:
        pass

    blobs = Path(HF_HUB_CACHE) / ("models--" + repo.replace("/", "--")) / "blobs"
    stop = threading.Event()

    def monitor():
        while not stop.is_set():
            if total:
                progress_cb(min(99, int(_folder_bytes(blobs) * 100 / total)))
            stop.wait(0.5)

    threading.Thread(target=monitor, daemon=True).start()
    try:
        snapshot_download(repo, allow_patterns=WHISPER_FILES)
    finally:
        stop.set()
    progress_cb(100)


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(s: dict):
    try:
        SETTINGS_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------- persistent app shell
ROOT = None       # the single tk.Tk() window, created once in main()
NOTEBOOK = None   # ttk.Notebook living in ROOT - every feature opens a tab in here
APP_STATE = {}    # small cross-tab bag: is_downloading(), history_frame, online_var
# ponytail: one job at a time app-wide (matches the old fully-sequential app); move to
# per-job contextvars-based stdout capture if concurrent file/folder/url/watch jobs are wanted.
PROCESSING_LOCK = threading.Lock()


def _close_tab(frame):
    cb = getattr(frame, "on_close", None)
    if cb:
        try:
            cb()
            return
        except Exception:
            pass
    try:
        NOTEBOOK.forget(frame)
    except Exception:
        pass


def open_feature_tab(title, builder_fn, *args, closable=True, **kwargs):
    """Create a new Notebook tab and build a feature into it. Never touches other tabs."""
    import tkinter as tk
    frame = tk.Frame(NOTEBOOK, bg="#ffffff")
    NOTEBOOK.add(frame, text=title)
    if closable:
        bar = tk.Frame(frame, bg="#f1f3f4")
        bar.pack(fill="x", side="top")
        tk.Button(bar, text="✕ Close tab", font=("Segoe UI", 8), relief="flat", bg="#f1f3f4",
                  command=lambda: _close_tab(frame)).pack(side="right", padx=4, pady=2)
    NOTEBOOK.select(frame)
    builder_fn(frame, *args, **kwargs)
    return frame


class _QueueWriter:
    """File-like object whose .write() pushes onto a queue, for redirecting print() output."""
    def __init__(self, q):
        self.q = q

    def write(self, s):
        if s:
            self.q.put(s)

    def flush(self):
        pass


def open_log_tab(title, target_fn, *args, stoppable=False, stop_event=None, **kwargs):
    """Run target_fn(*args, **kwargs) in a background thread, streaming its print() output
    into a scrolling log tab. Only one such job runs at a time app-wide (PROCESSING_LOCK)."""
    import tkinter as tk
    from tkinter import scrolledtext

    frame = tk.Frame(NOTEBOOK, bg="#ffffff")
    NOTEBOOK.add(frame, text=title)
    NOTEBOOK.select(frame)

    bar = tk.Frame(frame, bg="#f1f3f4")
    bar.pack(fill="x", side="top")
    status_lbl = tk.Label(bar, text="Queued...", bg="#f1f3f4", font=("Segoe UI", 9))
    status_lbl.pack(side="left", padx=6)
    if stoppable and stop_event is not None:
        tk.Button(bar, text="Stop", font=("Segoe UI", 8), relief="flat", bg="#fce8e6",
                  command=stop_event.set).pack(side="right", padx=4, pady=2)
    tk.Button(bar, text="✕ Close tab", font=("Segoe UI", 8), relief="flat", bg="#f1f3f4",
              command=lambda: NOTEBOOK.forget(frame)).pack(side="right", padx=4, pady=2)

    log = scrolledtext.ScrolledText(frame, wrap="word", font=("Consolas", 10),
                                    relief="solid", bd=1, bg="#ffffff")
    log.pack(fill="both", expand=True, padx=8, pady=(0, 8))
    log.configure(state="disabled")

    q = queue.Queue()

    def _worker():
        with PROCESSING_LOCK:
            q.put("--- starting ---\n")
            try:
                with contextlib.redirect_stdout(_QueueWriter(q)):
                    target_fn(*args, **kwargs)
                q.put("\n--- done ---\n")
            except Exception as e:
                q.put(f"\n[!] Failed: {e}\n")
        q.put(None)

    def _poll():
        drained = False
        while True:
            try:
                item = q.get_nowait()
            except queue.Empty:
                break
            if item is None:
                status_lbl.configure(text="Done")
                return
            log.configure(state="normal")
            log.insert("end", item)
            log.see("end")
            log.configure(state="disabled")
            drained = True
        if drained:
            status_lbl.configure(text="Running...")
        ROOT.after(200, _poll)

    threading.Thread(target=_worker, daemon=True).start()
    ROOT.after(200, _poll)
    return frame


def on_app_close():
    from tkinter import messagebox
    is_downloading = APP_STATE.get("is_downloading")
    if is_downloading and is_downloading() and not messagebox.askyesno(
            "Download in progress", "A model is downloading. Quit anyway?\n"
            "(It will resume next time.)", parent=ROOT):
        return
    for tab_id in list(NOTEBOOK.tabs()):
        frame = NOTEBOOK.nametowidget(tab_id)
        cb = getattr(frame, "on_close", None)
        if cb:
            try:
                cb()
            except Exception:
                pass
    ROOT.destroy()


# ---------------------------------------------------------------- home tab (settings)
def build_home_tab(parent_frame, online0, on_start):
    """Model / language / source picker. Lives in the persistent Home tab - Start opens
    the chosen feature as a NEW tab instead of replacing this one.
    online0 is REAL internet connectivity (checked once at startup) - it gates Whisper
    model downloads and the URL/link mode, independently of the Online/Offline tool-
    preference toggle (that toggle only changes which summarize/translate/cleanup tool
    is tried by default - see launch_feature() / build_voice_cleanup_tab())."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    GREEN, GREY, ORANGE, RED = "#1e8e3e", "#9aa0a6", "#e37400", "#c5221f"
    WHITE, SEL, MUTED = "#ffffff", "#e8f0fe", "#5f6368"
    FONT = "Segoe UI"

    saved = load_settings()
    status = {n: is_downloaded(n) for n, _, _ in WHISPER_MODELS}
    st = {"selected": None, "downloading": None, "progress": 0, "errors": {}, "finished": None}
    pref = saved.get("model", WHISPER_MODEL)
    st["selected"] = pref if status.get(pref) else next(
        (n for n, _, _ in WHISPER_MODELS if status[n]), None)
    APP_STATE["is_downloading"] = lambda: bool(st["downloading"])

    root = parent_frame
    root.configure(bg=WHITE)

    def heading(text, top=8):
        tk.Label(root, text=text, bg=WHITE, font=(FONT, 12, "bold")).pack(
            anchor="w", padx=16, pady=(top, 0))

    def small(parent, text, **kw):
        return tk.Label(parent, text=text, bg=WHITE, fg=MUTED, font=(FONT, 9), **kw)

    # ---- 1. Models (two columns)
    heading("1.  Speech-to-text (Whisper) model", top=12)
    info = tk.Frame(root, bg=WHITE)
    info.pack(anchor="w", padx=16)
    small(info, "Green = downloaded (click to select)    Grey = not downloaded (click to download)").pack(side="left")
    online_lbl = tk.Label(info, bg=WHITE, font=(FONT, 9, "bold"))
    online_lbl.pack(side="left")

    listf = tk.Frame(root, bg=WHITE)
    listf.pack(fill="x", padx=12, pady=(4, 0))
    desc_lbl = small(root, "", anchor="w")
    rows = {}
    for i, (name, size, desc) in enumerate(WHISPER_MODELS):
        row = tk.Frame(listf, bg=WHITE, cursor="hand2", padx=6, pady=2,
                       highlightthickness=1, highlightbackground="#dadce0")
        dot = tk.Label(row, text="●", font=(FONT, 13), bg=WHITE)
        title = tk.Label(row, text=name, font=(FONT, 10, "bold"), width=14, anchor="w", bg=WHITE)
        sz = tk.Label(row, text=size, width=8, anchor="w", bg=WHITE, fg=MUTED, font=(FONT, 9))
        stat = tk.Label(row, width=17, anchor="e", bg=WHITE, font=(FONT, 9, "bold"))
        for c, w in enumerate((dot, title, sz, stat)):
            w.grid(row=0, column=c, sticky="w")
        row.grid(row=i % 4, column=i // 4, sticky="ew", padx=(0 if i < 4 else 8, 0), pady=1)
        widgets = (row, dot, title, sz, stat)
        for w in widgets:
            w.bind("<Button-1>", lambda e, n=name: on_click(n))
            w.bind("<Enter>", lambda e, n=name, d=desc: desc_lbl.configure(text=f"{n}:  {d}"))
            w.bind("<Leave>", lambda e: show_desc())
        rows[name] = (widgets, dot, title, stat)
    listf.columnconfigure(0, weight=1)
    listf.columnconfigure(1, weight=1)
    desc_lbl.pack(fill="x", padx=16, pady=(2, 0))

    def show_desc():
        d = next((d for n, _, d in WHISPER_MODELS if n == st["selected"]), "")
        desc_lbl.configure(text=f"{st['selected']}:  {d}" if st["selected"] else "")

    # ---- 2. Spoken language + vocabulary
    heading("2.  Spoken language")
    sp = tk.Frame(root, bg=WHITE)
    sp.pack(fill="x", padx=16, pady=(4, 0))
    saved_lang = saved.get("language", SPOKEN_LANGUAGE)
    spoken_var = tk.StringVar(value=lang_name(saved_lang) if saved_lang else "Auto-detect")
    ttk.Combobox(sp, textvariable=spoken_var, values=SPOKEN_CHOICES, state="readonly",
                 width=16).pack(side="left")
    small(sp, "  (auto-detect handles mixed languages)").pack(side="left")
    vocab_btn = tk.Button(sp, font=(FONT, 9), relief="flat", bg="#e8f0fe", padx=10,
                          command=lambda: edit_vocab())
    vocab_btn.pack(side="right")
    tk.Label(sp, text="Custom vocabulary:", bg=WHITE, font=(FONT, 10)).pack(side="right", padx=6)

    def vocab_text():
        n = len(load_vocab())
        vocab_btn.configure(text=f"Edit list ({n} terms)" if n else "Add names / terms")

    def edit_vocab():
        w = tk.Toplevel(ROOT)
        w.title("Custom vocabulary")
        w.configure(bg=WHITE)
        w.transient(ROOT)
        w.grab_set()
        tk.Label(w, bg=WHITE, justify="left", font=(FONT, 9),
                 text="One name, term or abbreviation per line (any language).\n"
                      "Whisper will prefer these spellings, and translations / summaries keep them.\n"
                      "Lines starting with # are ignored.").pack(anchor="w", padx=12, pady=(10, 4))
        t = tk.Text(w, width=52, height=14, font=(FONT, 10), relief="solid", bd=1)
        t.pack(padx=12)
        try:
            t.insert("1.0", VOCAB_FILE.read_text(encoding="utf-8"))
        except Exception:
            t.insert("1.0", "# Examples:\n# Vikram\n# JSSD\n# PSForge\n")
        b = tk.Frame(w, bg=WHITE)
        b.pack(fill="x", padx=12, pady=10)

        def save_():
            VOCAB_FILE.write_text(t.get("1.0", "end").strip() + "\n", encoding="utf-8")
            vocab_text()
            w.destroy()
        tk.Button(b, text="Save", font=(FONT, 10, "bold"), bg="#1a73e8", fg="white", relief="flat",
                  padx=16, command=save_).pack(side="right")
        tk.Button(b, text="Cancel", font=(FONT, 10), relief="flat", padx=12,
                  command=w.destroy).pack(side="right", padx=6)

    vocab_text()

    # ---- 3. Output languages
    heading("3.  Output languages (transcript + summary in each)")
    small(root, "'Original' = exactly as spoken. Translations other than English need "
                "Claude Code, Ollama or LM Studio.").pack(anchor="w", padx=16)
    outf = tk.Frame(root, bg=WHITE)
    outf.pack(fill="x", padx=12, pady=(2, 0))
    saved_outs = set(saved.get("outputs", OUTPUT_LANGUAGES))
    out_vars = {}
    for i, name in enumerate(OUTPUT_CHOICES):
        v = tk.BooleanVar(value=name in saved_outs)
        out_vars[name] = v
        tk.Checkbutton(outf, text=name, variable=v, bg=WHITE, activebackground=WHITE,
                       font=(FONT, 10, "bold" if name == "Original" else "normal"),
                       width=11, anchor="w", bd=0, highlightthickness=0).grid(row=i // 7, column=i % 7, sticky="w")
    speak_var = tk.BooleanVar(value=saved.get("speak_save", False))
    tk.Checkbutton(root, text="Also save each translation as spoken audio (read aloud)",
                   variable=speak_var, bg=WHITE, activebackground=WHITE, font=(FONT, 10), bd=0,
                   highlightthickness=0).pack(anchor="w", padx=12, pady=(2, 0))

    # ---- 4. Source
    heading("4.  What to process")
    srcf = tk.Frame(root, bg=WHITE)
    srcf.pack(fill="x", padx=12, pady=(4, 0))
    mode0 = saved.get("mode", "file")
    if mode0 == "url" and not online0:
        mode0 = "file"
    src_var = tk.StringVar(value=mode0)
    url_var = tk.StringVar()
    skip_var = tk.BooleanVar(value=saved.get("skip_done", True))
    sub_var = tk.BooleanVar(value=saved.get("subfolders", False))

    def radio(text, value, r, c, **kw):
        b = tk.Radiobutton(srcf, text=text, variable=src_var, value=value, bg=WHITE,
                           activebackground=WHITE, font=(FONT, 10), bd=0, highlightthickness=0, **kw)
        b.grid(row=r, column=c, sticky="w", padx=(0, 14), pady=1)
        return b

    def check(text, var, r, c):
        tk.Checkbutton(srcf, text=text, variable=var, bg=WHITE, activebackground=WHITE,
                       font=(FONT, 9), bd=0, highlightthickness=0).grid(row=r, column=c, sticky="w")

    radio("Video / audio file", "file", 0, 0)
    radio("Folder (batch)", "folder", 0, 1)
    url_radio = radio("YouTube / link:", "url", 0, 2)
    url_entry = tk.Entry(srcf, textvariable=url_var, width=30, font=(FONT, 9))
    url_entry.grid(row=0, column=3, sticky="w")
    url_entry.bind("<FocusIn>", lambda e: src_var.set("url"))
    radio("Live microphone", "mic", 1, 0)
    radio("System audio (PC sound)", "system", 1, 1)
    radio("Call (mic + PC sound)", "call", 1, 2)
    radio("Watch folder (automatic)", "watch", 2, 0)
    check("Folders: skip already done", skip_var, 2, 1)
    check("include subfolders", sub_var, 2, 2)

    extra = tk.Frame(root, bg=WHITE)
    extra.pack(fill="x", padx=12, pady=(6, 0))
    tk.Label(extra, text="Only this part:", bg=WHITE, font=(FONT, 10)).pack(side="left")
    from_var, to_var = tk.StringVar(), tk.StringVar()
    tk.Entry(extra, textvariable=from_var, width=8, font=(FONT, 9)).pack(side="left", padx=(6, 2))
    tk.Label(extra, text="to", bg=WHITE, font=(FONT, 10)).pack(side="left")
    tk.Entry(extra, textvariable=to_var, width=8, font=(FONT, 9)).pack(side="left", padx=(2, 4))
    small(extra, "e.g. 10:00 to 25:00  (file / link; blank = all)").pack(side="left")

    small(root, "Voice cleanup is configured in its own \"Voice Cleanup\" tab.").pack(
        anchor="w", padx=16, pady=(6, 0))

    hint = small(root, "")
    hint.pack(anchor="w", padx=16, pady=(8, 0))

    btns = tk.Frame(root, bg=WHITE)
    btns.pack(fill="x", padx=16, pady=(6, 14))
    start_btn = tk.Button(btns, text="Start  ▶", font=(FONT, 10, "bold"),
                          bg="#1a73e8", fg="white", activebackground="#1765cc",
                          activeforeground="white", relief="flat", padx=14, pady=6)
    start_btn.pack(side="right")
    tk.Button(btns, text="History", font=(FONT, 10), relief="flat", padx=12, pady=6,
              command=lambda: open_history_tab()).pack(side="left")

    START_TEXT = {"file": "Select video & start  ▶", "folder": "Select folder & start  ▶",
                  "url": "Download & start  ▶", "mic": "Start microphone  ▶",
                  "system": "Start system audio  ▶", "call": "Start call capture  ▶",
                  "watch": "Select folder & watch  ▶"}
    src_var.trace_add("write", lambda *a: start_btn.configure(text=START_TEXT[src_var.get()]))
    start_btn.configure(text=START_TEXT[src_var.get()])

    def refresh():
        for name, (widgets, dot, title, stat) in rows.items():
            sel = st["selected"] == name
            for w in widgets:
                w.configure(bg=SEL if sel else WHITE)
            widgets[0].configure(highlightbackground=("#1a73e8" if sel else "#dadce0"))
            if st["downloading"] == name:
                color, text = ORANGE, f"Downloading {st['progress']}%"
            elif status[name]:
                color, text = GREEN, ("✔ Selected" if sel else "Downloaded")
            elif name in st["errors"]:
                color, text = RED, "Failed - click to retry"
            else:
                color, text = GREY, ("Click to download" if online0 else "Not downloaded")
            dot.configure(fg=color)
            title.configure(fg=color)
            stat.configure(fg=color, text=text)
        show_desc()
        ok = bool(st["selected"]) and status.get(st["selected"])
        start_btn.configure(state=("normal" if ok else "disabled"))
        if st["downloading"]:
            hint.configure(text="Downloading... it is saved for next time.")
        elif not ok:
            hint.configure(text="Download at least one model to continue."
                           if online0 else "No model downloaded yet - connect to the internet once.")
        else:
            hint.configure(text="Tip: for live microphone / system audio / call / captions, "
                                "tiny / base / small give the quickest on-screen text.")

    def worker(name):
        try:
            download_whisper(name, lambda p: st.__setitem__("progress", p))
            st["finished"] = (name, None)
        except Exception as e:
            st["finished"] = (name, str(e))

    def poll():
        fin = st["finished"]
        if fin:
            st["finished"] = None
            name, err = fin
            st["downloading"] = None
            if err:
                st["errors"][name] = err
                messagebox.showerror("Download failed", f"{name}:\n{err[:500]}", parent=root)
            else:
                status[name] = is_downloaded(name)
                if status[name]:
                    st["selected"] = name
            refresh()
            return
        refresh()
        root.after(400, poll)

    def on_click(name):
        if status[name]:
            st["selected"] = name
            refresh()
            return
        if st["downloading"]:
            messagebox.showinfo("Please wait", f"'{st['downloading']}' is still downloading.", parent=root)
            return
        if not online0:
            messagebox.showwarning("Offline", "Connect to the internet to download this model.", parent=root)
            return
        size = next(s for n, s, _ in WHISPER_MODELS if n == name)
        if not messagebox.askyesno("Download model", f"Download '{name}' ({size})?", parent=root):
            return
        st["downloading"], st["progress"] = name, 0
        st["errors"].pop(name, None)
        threading.Thread(target=worker, args=(name,), daemon=True).start()
        poll()

    def start():
        mode = src_var.get()
        outputs = [n for n in OUTPUT_CHOICES if out_vars[n].get()]
        if not outputs:
            messagebox.showwarning("Output language", "Tick at least one output language.", parent=root)
            return
        url = url_var.get().strip()
        if mode == "url" and not re.match(r"https?://", url):
            messagebox.showwarning("Link", "Paste a link starting with http:// or https://", parent=root)
            url_entry.focus_set()
            return
        try:
            a, b = parse_time(from_var.get()), parse_time(to_var.get())
        except ValueError:
            messagebox.showwarning("Only this part", "Use times like 90, 10:00 or 1:05:30.", parent=root)
            return
        clip = None
        if a is not None or b is not None:
            if b is not None and b <= (a or 0):
                messagebox.showwarning("Only this part", "The end time must be after the start time.",
                                       parent=root)
                return
            clip = [a or 0.0, b]
        spoken = spoken_var.get()
        res = {"model": st["selected"],
               "language": None if spoken == "Auto-detect" else LANG_CODES.get(spoken),
               "outputs": outputs, "mode": mode,
               "skip_done": bool(skip_var.get()), "subfolders": bool(sub_var.get()),
               "speak_save": bool(speak_var.get())}
        s = load_settings()      # keep other saved things (voice cleanup, caption style, alerts...)
        s.update(res)
        save_settings(s)
        res.update(url=url, clip=clip)
        on_start(res)

    online_lbl.configure(text=("    ● Internet connected" if online0 else "    ● Offline - downloads unavailable"),
                         fg=(GREEN if online0 else RED))
    url_radio.configure(state=("normal" if online0 else "disabled"))
    url_entry.configure(state=("normal" if online0 else "disabled"))
    start_btn.configure(command=start)
    refresh()


def pick_video() -> str:
    from tkinter import filedialog
    return filedialog.askopenfilename(parent=ROOT, title="Select a video to summarize",
                                      filetypes=VIDEO_TYPES)


# ---------------------------------------------------------------- Whisper
def _add_nvidia_dlls():
    """The pip packages nvidia-cublas-cu12 / nvidia-cudnn-cu12 ship the CUDA DLLs that
    faster-whisper needs. Make them findable so no separate CUDA install is required."""
    import importlib.util
    for pkg in ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_runtime"):
        try:
            spec = importlib.util.find_spec(pkg)
        except Exception:
            spec = None
        if not spec or not spec.submodule_search_locations:
            continue
        for base in spec.submodule_search_locations:
            for sub in ("bin", "lib"):
                d = Path(base) / sub
                if d.is_dir():
                    os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
                    if hasattr(os, "add_dll_directory"):
                        try:
                            os.add_dll_directory(str(d))
                        except Exception:
                            pass


def pick_device():
    if DEVICE != "auto":
        ct = COMPUTE_TYPE if COMPUTE_TYPE != "auto" else ("float16" if DEVICE == "cuda" else "int8")
        return DEVICE, ct
    try:
        import ctranslate2
        gpus = ctranslate2.get_cuda_device_count()
    except Exception:
        gpus = 0
    if gpus > 0:
        return "cuda", (COMPUTE_TYPE if COMPUTE_TYPE != "auto" else "float16")
    return "cpu", (COMPUTE_TYPE if COMPUTE_TYPE != "auto" else "int8")


def load_whisper(model_name):
    try:
        from faster_whisper import WhisperModel
        import numpy as np
    except ImportError:
        print("\n[!] faster-whisper is not installed. Run:\n    pip install faster-whisper\n")
        sys.exit(1)
    _add_nvidia_dlls()
    device, ctype = pick_device()
    print(f"Loading Whisper model '{model_name}' on {'NVIDIA GPU' if device == 'cuda' else 'CPU'}...")
    try:
        # Passing the repo id makes newer models work even on older faster-whisper versions
        model = WhisperModel(repo_for(model_name), device=device, compute_type=ctype)
        if device == "cuda":
            # Missing CUDA libraries only show up when the GPU is actually used - test it now
            segs, _ = model.transcribe(np.zeros(SR, np.float32), language="en")
            list(segs)
        return model
    except Exception as e:
        if device != "cuda":
            print(f"\n[!] Could not load the Whisper model: {e}")
            print("    If you're offline, run the script once with internet so the model gets downloaded.")
            sys.exit(1)
        print(f"\n[!] NVIDIA GPU found, but it couldn't be used: {str(e)[:200]}")
        print("    To enable the GPU, run:  pip install nvidia-cublas-cu12 nvidia-cudnn-cu12==9.*")
        print("    Using the CPU for now.\n")
    try:
        return WhisperModel(repo_for(model_name), device="cpu", compute_type="int8")
    except Exception as e:
        print(f"\n[!] Could not load the Whisper model: {e}")
        print("    If you're offline, run the script once with internet so the model gets downloaded.")
        sys.exit(1)


def detect_languages(model, video):
    """Check the language of each ~30s piece of audio. Returns [(start_sec, code, prob)]."""
    import numpy as np
    from faster_whisper.audio import decode_audio

    print("Detecting spoken languages...")
    try:
        audio = decode_audio(video, sampling_rate=SR)
    except Exception as e:
        print(f"  [!] Could not read audio for language detection: {e}")
        return []

    win = DETECT_WINDOW_SEC * SR
    starts = pick_evenly(list(range(0, len(audio), win)), MAX_DETECT_WINDOWS)
    results = []
    for i, s in enumerate(starts, 1):
        print(f"\r  checking {i}/{len(starts)}", end="", flush=True)
        chunk = audio[s:s + win]
        if len(chunk) < SR * 2 or float(np.sqrt(np.mean(chunk ** 2))) < 0.003:
            continue   # too short or silent
        try:
            if hasattr(model, "detect_language"):
                code, prob, _ = model.detect_language(audio=chunk, vad_filter=True)
            else:
                _, info = model.transcribe(chunk, vad_filter=True)
                code, prob = info.language, info.language_probability
        except Exception:
            continue
        if prob >= 0.5:
            results.append((s / SR, code, prob))
    print()
    del audio
    return results


def language_stats(detections, end_limit=None):
    """-> [{code, name, share, ranges}] sorted by share."""
    if not detections:
        return []
    counts = Counter(c for _, c, _ in detections)
    total = sum(counts.values())
    ranges = {}
    for i, (t, code, _) in enumerate(detections):
        end = detections[i + 1][0] if i + 1 < len(detections) else t + DETECT_WINDOW_SEC
        if end_limit:
            end = min(end, end_limit)
        r = ranges.setdefault(code, [])
        if r and abs(r[-1][1] - t) < 1:
            r[-1][1] = end
        else:
            r.append([t, end])
    stats = [{"code": c, "name": lang_name(c), "share": n / total, "ranges": ranges[c]}
             for c, n in counts.most_common()]
    return stats


def print_language_stats(stats):
    print("\nLanguages spoken in the video:")
    for s in stats:
        bar = "█" * round(s["share"] * 20) + "░" * (20 - round(s["share"] * 20))
        rng = ", ".join(f"{fmt(a)}-{fmt(b)}" for a, b in s["ranges"][:4])
        if len(s["ranges"]) > 4:
            rng += f", ... (+{len(s['ranges']) - 4} more)"
        print(f"  {s['name']:<12} {bar} {s['share']:>4.0%}   {rng}")
    print()


# Phrases Whisper tends to invent on noise / silence (from its YouTube training data)
HALLUCINATIONS = [
    "thank you for watching", "thanks for watching", "please subscribe", "subscribe to",
    "like and subscribe", "subtitles by", "captions by", "transcribed by", "amara.org",
    "www.", ".com", "see you in the next video", "don't forget to subscribe",
    "اشتركوا في القناة",          # Arabic: subscribe to the channel
    "شكرا للمشاهدة",                    # Arabic: thanks for watching
    "ترجمة نانسي",                      # Arabic: "translated by Nancy..." (classic)
    "सब्सक्राइब",                         # Hindi: subscribe
]
MARK_UNCLEAR = True          # add [unclear] to lines Whisper is unsure about
UNCLEAR_LOGPROB = -0.9       # lower = only very unsure lines get marked


def decode_kwargs(model, noisy):
    """Whisper settings. 'noisy' = safer decoding for rough audio (fewer made-up words)."""
    k = {"vad_filter": True, "beam_size": 5}
    if noisy:
        k.update(best_of=5, condition_on_previous_text=False,   # stops runaway repeated lines
                 no_speech_threshold=0.6, compression_ratio_threshold=2.2, log_prob_threshold=-1.0,
                 vad_parameters={"threshold": 0.4, "min_silence_duration_ms": 600, "speech_pad_ms": 400})
    k.update(vocab_kwargs(model))
    try:
        ok = inspect.signature(model.transcribe).parameters
        if not any(p.kind == p.VAR_KEYWORD for p in ok.values()):
            k = {a: b for a, b in k.items() if a in ok}
    except Exception:
        pass
    return k


def is_hallucination(text, seg=None):
    t = text.strip().lower()
    if not t or re.fullmatch(r"[\W_]+", t):
        return True
    if any(h in t for h in HALLUCINATIONS) and len(t) < 90:
        return True
    if seg is not None and getattr(seg, "no_speech_prob", 0) > 0.6 and getattr(seg, "avg_logprob", 0) < -1.0:
        return True
    return False


def unclear(seg):
    return MARK_UNCLEAR and getattr(seg, "avg_logprob", 0) < UNCLEAR_LOGPROB


class LoopGuard:
    """Whisper sometimes gets stuck repeating one line. Real speech repeats too ("Roger... Roger"),
    so only the 3rd+ identical line in a row is dropped."""

    def __init__(self):
        self.last, self.n = None, 0

    def repeat(self, text):
        t = text.strip().lower()
        self.n = self.n + 1 if t == self.last else 0
        self.last = t
        return self.n >= 2


def transcribe(model, video, language, multilingual=False, detections=None, offset=0.0, noisy=False):
    """offset = where the audio starts inside the full video (clip range), added to timestamps."""
    kwargs = {"language": language, "task": "transcribe"}
    if multilingual and "multilingual" in inspect.signature(model.transcribe).parameters:
        kwargs["multilingual"] = True
    kwargs.update(decode_kwargs(model, noisy))
    segments, info = model.transcribe(video, **kwargs)
    print(f"Duration: {fmt(info.duration)}")
    print("Transcribing...")

    det_times = [d[0] for d in detections] if detections else []
    stamped, plain, prev, guard, dropped, marked = [], [], None, LoopGuard(), 0, 0
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        if is_hallucination(text, seg) or guard.repeat(text):
            dropped += 1
            continue
        if unclear(seg):
            text += " [unclear]"
            marked += 1
        t = seg.start + offset
        prefix = ""
        if detections:  # mixed-language video: mark where the language changes
            idx = max(0, sum(1 for d in det_times if d <= t) - 1)
            code = detections[idx][1]
            if code != prev:
                prefix = f"({lang_name(code)}) "
                prev = code
        stamped.append(f"[{fmt(t)}] {prefix}{text}")
        plain.append(text)
        print(f"\r  {fmt(seg.end)} / {fmt(info.duration)}", end="", flush=True)
    print()
    if dropped:
        print(f"  Removed {dropped} made-up / repeated line(s) (typical Whisper noise artefacts).")
    if marked:
        print(f"  {marked} line(s) marked [unclear] - check those parts by ear.")
    return stamped, " ".join(plain), info


def whisper_translate_english(model, video, language, offset=0.0, noisy=False):
    print("Translating to English with Whisper...")
    segments, info = model.transcribe(video, language=language, task="translate",
                                      **decode_kwargs(model, noisy))
    lines, guard = [], LoopGuard()
    for seg in segments:
        if seg.text.strip() and not is_hallucination(seg.text, seg) and not guard.repeat(seg.text):
            lines.append(f"[{fmt(seg.start + offset)}] {seg.text.strip()}")
            print(f"\r  {fmt(seg.end)} / {fmt(info.duration)}", end="", flush=True)
    print()
    return "\n".join(lines)


def extract_frames(video: str, duration: float, outdir: Path, start=0.0):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or duration <= 0:
        return [], 0
    interval = max(duration / MAX_FRAMES, 1.0)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", video, "-t", f"{duration:.3f}", "-vf", f"fps=1/{interval:.3f},scale=768:-2",
            "-frames:v", str(MAX_FRAMES), str(outdir / "frame_%03d.jpg")]
    subprocess.run(cmd, check=False)
    return sorted(outdir.glob("frame_*.jpg")), interval


# ---------------------------------------------------------------- LLM backends
def summary_format(out_lang):
    return f"""Write the summary in {out_lang}, in Markdown, with these sections:

# <a short descriptive title>
## TL;DR
2-3 sentences.
## Key points
Bullet list of the most important points.
## Section-by-section
Chronological breakdown with [HH:MM:SS] timestamps.
## On-screen / visual notes
Only if images/frames were provided: important things visible that the speech doesn't say.

If the transcript is empty or has no speech, base the summary on the frames.
Output ONLY the Markdown summary, nothing else.""" + vocab_note()


def claude_text(prompt):
    claude = shutil.which("claude")
    r = subprocess.run([claude, "-p"], input=prompt, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=CLAUDE_TIMEOUT_SEC)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError((r.stderr or r.stdout or "no output")[-500:])
    return r.stdout.strip()


def summarize_claude(workdir: Path, video_name, frames, interval, lang_desc, out_lang):
    claude = shutil.which("claude")
    if not claude:
        print("  [claude] 'claude' command not found - skipping.")
        return None

    frame_note = ""
    if frames:
        frame_note = (
            f"\nThere are also {len(frames)} key frames from the video in this folder "
            f"(frame_001.jpg, frame_002.jpg, ...). Frame N was taken at about "
            f"(N-1) x {interval:.0f} seconds. Read them to understand what is shown on screen.\n"
        )
    prompt = (
        f'You are summarizing a video called "{video_name}".\n'
        f"Read transcript.txt in the current folder. Languages spoken: {lang_desc}.{frame_note}\n"
        f"{summary_format(out_lang)}\nDo not create or edit any files."
    )
    print(f"  [claude] Writing {out_lang} summary...")
    try:
        r = subprocess.run(
            [claude, "-p", "--allowedTools", "Read"],
            input=prompt, cwd=workdir, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=CLAUDE_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        print("  [claude] Timed out.")
        return None
    if r.returncode != 0 or not r.stdout.strip():
        print("  [claude] Error:\n" + (r.stderr or r.stdout)[-1500:])
        return None
    return r.stdout.strip(), "Claude Code"


def ensure_ollama():
    try:
        http_json(OLLAMA_URL + "/api/tags", timeout=3)
        return True
    except Exception:
        pass
    exe = shutil.which("ollama")
    if not exe:
        return False
    print("  [ollama] Starting Ollama...")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=flags)
    for _ in range(15):
        time.sleep(1)
        try:
            http_json(OLLAMA_URL + "/api/tags", timeout=2)
            return True
        except Exception:
            continue
    return False


def list_ollama_models():
    tags = http_json(OLLAMA_URL + "/api/tags", timeout=5)
    return [m["name"] for m in tags.get("models", []) if "embed" not in m["name"].lower()]


def ollama_model():
    picked = load_settings().get("ollama_model") or OLLAMA_MODEL
    names = list_ollama_models()
    if picked and picked in names:
        return picked
    return names[0] if names else None


def ollama_chat(model, system, user, images_b64=None):
    msg = {"role": "user", "content": user}
    if images_b64:
        msg["images"] = images_b64
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, msg],
        "stream": False,
        "options": {"num_ctx": OLLAMA_NUM_CTX, "temperature": 0.3},
    }
    r = http_json(OLLAMA_URL + "/api/chat", payload, timeout=LOCAL_TIMEOUT_SEC)
    return strip_thinking(r["message"]["content"])


def ensure_lmstudio():
    try:
        http_json(LMSTUDIO_URL + "/v1/models", timeout=3)
        return True
    except Exception:
        pass
    exe = shutil.which("lms")
    if not exe:
        return False
    print("  [lmstudio] Starting LM Studio server...")
    subprocess.run([exe, "server", "start"], capture_output=True, timeout=60)
    for _ in range(10):
        time.sleep(1)
        try:
            http_json(LMSTUDIO_URL + "/v1/models", timeout=2)
            return True
        except Exception:
            continue
    return False


def list_lmstudio_models():
    r = http_json(LMSTUDIO_URL + "/v1/models", timeout=5)
    return [m["id"] for m in r.get("data", []) if "embed" not in m["id"].lower()]


def lmstudio_model():
    picked = load_settings().get("lmstudio_model") or LMSTUDIO_MODEL
    ids = list_lmstudio_models()
    if picked and picked in ids:
        return picked
    return ids[0] if ids else None


def lmstudio_chat(model, system, user, images_b64=None):
    if images_b64:
        content = [{"type": "text", "text": user}] + [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b}"}}
            for b in images_b64
        ]
    else:
        content = user
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": content}],
        "temperature": 0.3,
        "stream": False,
    }
    r = http_json(LMSTUDIO_URL + "/v1/chat/completions", payload, timeout=LOCAL_TIMEOUT_SEC)
    return strip_thinking(r["choices"][0]["message"]["content"])


def local_backend(backend):
    """-> (label, model, chat_fn) or None"""
    if backend == "ollama":
        if not ensure_ollama():
            print("  [ollama] Ollama is not running/installed - skipping.")
            return None
        get_model, chat, label = ollama_model, ollama_chat, "Ollama"
    else:
        if not ensure_lmstudio():
            print("  [lmstudio] LM Studio server is not running - skipping.")
            print("             (Open LM Studio > Developer tab > Start server)")
            return None
        get_model, chat, label = lmstudio_model, lmstudio_chat, "LM Studio"
    try:
        model = get_model()
    except Exception as e:
        print(f"  [{backend}] Could not list models: {e}")
        return None
    if not model:
        print(f"  [{backend}] No model found. Download one first.")
        return None
    return label, model, chat


_notes_cache = {}


def summarize_local(backend, transcript, video_name, frames, interval, lang_desc, out_lang):
    tag = f"[{backend}]"
    lb = local_backend(backend)
    if not lb:
        return None
    label, model, chat = lb
    print(f"  {tag} Using model: {model}")
    system = "You are an expert at summarizing videos accurately and concisely. Never invent facts."

    try:
        if len(transcript) > CHUNK_CHARS:
            key = (backend, model)
            if key not in _notes_cache:   # part-notes are reused for every output language
                chunks = split_chunks(transcript, CHUNK_CHARS)
                notes = []
                for i, ch in enumerate(chunks, 1):
                    print(f"  {tag} Reading part {i}/{len(chunks)}...")
                    notes.append(chat(model, system,
                        f"This is part {i} of {len(chunks)} of a timestamped transcript of the video "
                        f'"{video_name}". Write detailed bullet-point notes in English of everything '
                        f"important in this part, keeping the [HH:MM:SS] timestamps. Notes only.\n\n{ch}"))
                _notes_cache[key] = "Notes from each part of the transcript:\n\n" + "\n\n".join(
                    f"--- Part {i} ---\n{n}" for i, n in enumerate(notes, 1))
            material = _notes_cache[key]
        else:
            material = f"Timestamped transcript:\n\n{transcript}"

        images = None
        if frames and LOCAL_SEND_FRAMES:
            chosen = pick_evenly(frames, LOCAL_MAX_FRAMES)
            images = [base64.b64encode(f.read_bytes()).decode("ascii") for f in chosen]
            material += (f"\n\n{len(images)} frames from the video are attached, in order, "
                         f"spread evenly across its {fmt(interval * len(frames))} runtime.")

        print(f"  {tag} Writing {out_lang} summary...")
        prompt = (f'Summarize the video "{video_name}". Languages spoken: {lang_desc}.\n\n'
                  f"{material}\n\n{summary_format(out_lang)}")
        summary = chat(model, system, prompt, images)
    except Exception as e:
        print(f"  {tag} Error: {e}")
        if LOCAL_SEND_FRAMES and frames:
            print(f"  {tag} Tip: if the model has no vision support, set LOCAL_SEND_FRAMES = False")
        return None

    if not summary:
        print(f"  {tag} Empty response.")
        return None
    return summary, f"{label} ({model})"


def backend_order():
    return BACKEND_ORDER if BACKEND == "auto" else [BACKEND]


def summarize(workdir, transcript, video_name, frames, interval, lang_desc, out_lang, online):
    for b in backend_order():
        if b == "claude":
            if not online:
                print("  [claude] Offline - skipping.")
                continue
            res = summarize_claude(workdir, video_name, frames, interval, lang_desc, out_lang)
        elif b in ("ollama", "lmstudio"):
            res = summarize_local(b, transcript, video_name, frames, interval, lang_desc, out_lang)
        else:
            continue
        if res:
            return res
    return None


def text_llms(online):
    """Yield (label, fn(system, user) -> text) for each usable backend, in order."""
    for b in backend_order():
        if b == "claude":
            if online and shutil.which("claude"):
                yield "Claude Code", lambda s, u: claude_text(f"{s}\n\n{u}")
        elif b in ("ollama", "lmstudio"):
            lb = local_backend(b)
            if lb:
                label, model, chat = lb
                yield f"{label} ({model})", (lambda s, u, m=model, c=chat: c(m, s, u))


def translate_transcript(transcript, target, online):
    chunks = split_chunks(transcript, TRANSLATE_CHUNK_CHARS)
    system = "You are a professional translator. Translate faithfully and naturally."
    for label, fn in text_llms(online):
        try:
            out = []
            for i, ch in enumerate(chunks, 1):
                print(f"\r  Translating to {target} ({label}): part {i}/{len(chunks)}", end="", flush=True)
                out.append(fn(system,
                    f"Translate this timestamped video transcript into {target}.\n"
                    f"Rules: keep every [HH:MM:SS] timestamp at the start of its line, keep one "
                    f"output line per input line, drop the (Language) markers, and output ONLY "
                    f"the translated lines - no notes or explanations.{vocab_note()}\n\n{ch}"))
            print()
            return "\n".join(o.strip() for o in out), label
        except Exception as e:
            print(f"\n  [{label}] Translation failed: {e}")
    return None, None


# ---------------------------------------------------------------- live captions
CAPTION_DEFAULTS = {"opacity": 0.85, "position": "Bottom", "width": 70, "font": "Segoe UI",
                    "size": 22, "lines": 2, "fg": "#ffffff", "bg": "#000000",
                    "show_original": False, "no_bg": False, "speak": False,
                    "x": None, "y": None}
CAP_ORIGINAL = "Original (as spoken)"
CAP_FAST_EN = "English (fast, offline)"


class CaptionBar:
    """Borderless always-on-top subtitle bar. Drag to move, right-click for options."""

    def __init__(self, root, cs, on_moved, on_settings, on_hide):
        import tkinter as tk
        import tkinter.font as tkfont
        self.tkfont, self.cs = tkfont, cs
        self.on_moved = on_moved
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.lbl = tk.Label(self.win, justify="center", anchor="center")
        self.sub = tk.Label(self.win, justify="center", anchor="center")
        self.lbl.pack(fill="both", expand=True, padx=18, pady=(8, 2))
        self.menu = tk.Menu(self.win, tearoff=0)
        self.menu.add_command(label="Caption settings...", command=on_settings)
        self.menu.add_command(label="Hide captions", command=on_hide)
        for w in (self.win, self.lbl, self.sub):
            w.bind("<ButtonPress-1>", self._press)
            w.bind("<B1-Motion>", self._drag)
            w.bind("<ButtonRelease-1>", self._release)
            w.bind("<Button-3>", lambda e: self.menu.tk_popup(e.x_root, e.y_root))
        self.main_text, self.sub_text = "", ""
        self.apply()
        self.set_text("Captions will appear here  (drag to move, right-click for settings)")

    def apply(self):
        cs = self.cs
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        self.width = max(300, int(sw * cs["width"] / 100))
        self.font = self.tkfont.Font(family=cs["font"], size=int(cs["size"]), weight="bold")
        self.subfont = self.tkfont.Font(family=cs["font"], size=max(9, int(cs["size"] * 0.55)))
        for w, f in ((self.lbl, self.font), (self.sub, self.subfont)):
            w.configure(font=f, fg=cs["fg"], bg=cs["bg"], wraplength=self.width - 40)
        self.win.configure(bg=cs["bg"])
        try:
            self.win.attributes("-alpha", float(cs["opacity"]))
        except Exception:
            pass
        try:   # Windows only: make the background colour fully see-through
            self.win.attributes("-transparentcolor", cs["bg"] if cs["no_bg"] else "")
        except Exception:
            pass
        if cs["show_original"]:
            self.sub.pack(fill="x", padx=18, pady=(0, 8))
        else:
            self.sub.pack_forget()
        h = int(cs["lines"]) * self.font.metrics("linespace") + 22
        if cs["show_original"]:
            h += self.subfont.metrics("linespace") + 8
        if cs["position"] == "Custom" and cs.get("x") is not None:
            x, y = int(cs["x"]), int(cs["y"])
        elif cs["position"] == "Top":
            x, y = (sw - self.width) // 2, 30
        else:
            x, y = (sw - self.width) // 2, sh - h - 90
        self.win.geometry(f"{self.width}x{h}+{x}+{y}")
        self.set_text(self.main_text, self.sub_text)

    def _fit(self, text, font, lines):
        """Keep only the newest words that fit in `lines` lines."""
        out, cur = [], ""
        for word in reversed(text.split()):
            cand = f"{word} {cur}".strip()
            if cur and font.measure(cand) > self.width - 40:
                out.insert(0, cur)
                cur = word
                if len(out) >= lines:
                    cur = ""
                    break
            else:
                cur = cand
        if cur and len(out) < lines:
            out.insert(0, cur)
        return "\n".join(out[-lines:])

    def set_text(self, main, sub=""):
        self.main_text, self.sub_text = main, sub
        self.lbl.configure(text=self._fit(main, self.font, int(self.cs["lines"])))
        self.sub.configure(text=self._fit(sub, self.subfont, 1))

    def _press(self, e):
        self._off = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

    def _drag(self, e):
        self.win.geometry(f"+{e.x_root - self._off[0]}+{e.y_root - self._off[1]}")

    def _release(self, e):
        self.cs.update(position="Custom", x=self.win.winfo_x(), y=self.win.winfo_y())
        self.on_moved()

    def destroy(self):
        try:
            self.win.destroy()
        except Exception:
            pass


def caption_settings_window(parent, cs, apply_cb):
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import ttk, colorchooser

    FONT = "Segoe UI"
    w = tk.Toplevel(parent)
    w.title("Caption settings")
    w.configure(bg="#ffffff")
    w.resizable(False, False)
    w.attributes("-topmost", True)
    g = tk.Frame(w, bg="#ffffff")
    g.pack(padx=16, pady=12)

    def row(r, label):
        tk.Label(g, text=label, bg="#ffffff", font=(FONT, 10), anchor="w").grid(row=r, column=0, sticky="w", pady=4)

    def changed(*_):
        apply_cb()

    row(0, "Opacity")
    op = tk.Scale(g, from_=20, to=100, orient="horizontal", length=220, bg="#ffffff", highlightthickness=0,
                  command=lambda v: (cs.__setitem__("opacity", int(v) / 100), changed()))
    op.set(int(cs["opacity"] * 100))
    op.grid(row=0, column=1, sticky="w")

    row(1, "Position")
    pos = tk.StringVar(value=cs["position"])
    cb = ttk.Combobox(g, textvariable=pos, values=["Bottom", "Top", "Custom"], state="readonly", width=12)
    cb.grid(row=1, column=1, sticky="w")
    cb.bind("<<ComboboxSelected>>", lambda e: (cs.__setitem__("position", pos.get()), changed()))
    tk.Label(g, text="(Custom = drag the bar anywhere)", bg="#ffffff", fg="#5f6368",
             font=(FONT, 8)).grid(row=1, column=2, sticky="w")

    row(2, "Width (% of screen)")
    wd = tk.Scale(g, from_=30, to=100, orient="horizontal", length=220, bg="#ffffff", highlightthickness=0,
                  command=lambda v: (cs.__setitem__("width", int(v)), changed()))
    wd.set(int(cs["width"]))
    wd.grid(row=2, column=1, sticky="w")

    row(3, "Font")
    fams = sorted(set(tkfont.families()))
    prefer = [f for f in ("Segoe UI", "Arial", "Calibri", "Tahoma", "Verdana", "Nirmala UI",
                          "Times New Roman", "Consolas") if f in fams]
    fvar = tk.StringVar(value=cs["font"])
    fb = ttk.Combobox(g, textvariable=fvar, values=prefer + [f for f in fams if f not in prefer and not f.startswith("@")],
                      state="readonly", width=24)
    fb.grid(row=3, column=1, sticky="w")
    fb.bind("<<ComboboxSelected>>", lambda e: (cs.__setitem__("font", fvar.get()), changed()))

    row(4, "Text size")
    sv = tk.IntVar(value=int(cs["size"]))
    tk.Spinbox(g, from_=10, to=72, textvariable=sv, width=6,
               command=lambda: (cs.__setitem__("size", sv.get()), changed())).grid(row=4, column=1, sticky="w")

    row(5, "Lines shown")
    lv = tk.IntVar(value=int(cs["lines"]))
    tk.Spinbox(g, from_=1, to=5, textvariable=lv, width=6,
               command=lambda: (cs.__setitem__("lines", lv.get()), changed())).grid(row=5, column=1, sticky="w")

    def color_btn(r, label, key):
        row(r, label)
        b = tk.Button(g, text="      ", bg=cs[key], relief="solid", bd=1, width=6)

        def pick():
            c = colorchooser.askcolor(color=cs[key], parent=w, title=label)[1]
            if c:
                cs[key] = c
                b.configure(bg=c)
                changed()
        b.configure(command=pick)
        b.grid(row=r, column=1, sticky="w")

    color_btn(6, "Text colour", "fg")
    color_btn(7, "Background colour", "bg")

    def flag(r, text, key):
        v = tk.BooleanVar(value=bool(cs[key]))
        tk.Checkbutton(g, text=text, variable=v, bg="#ffffff", activebackground="#ffffff", font=(FONT, 10),
                       command=lambda: (cs.__setitem__(key, v.get()), changed())).grid(
            row=r, column=0, columnspan=3, sticky="w")

    flag(8, "Show the original words under the translation", "show_original")
    flag(9, "No background - text only (Windows)", "no_bg")
    flag(10, "Read translated captions aloud", "speak")

    b = tk.Frame(w, bg="#ffffff")
    b.pack(fill="x", padx=16, pady=(0, 12))

    def reset():
        cs.update(CAPTION_DEFAULTS)
        changed()
        w.destroy()
        caption_settings_window(parent, cs, apply_cb)
    tk.Button(b, text="Reset to defaults", relief="flat", font=(FONT, 9), command=reset).pack(side="left")
    tk.Button(b, text="Close", relief="flat", font=(FONT, 10, "bold"), bg="#1a73e8", fg="white",
              padx=16, command=w.destroy).pack(side="right")


# ---------------------------------------------------------------- live capture
def stamped_from_entries(entries):
    lines, prev = [], None
    for e in sorted(entries, key=lambda x: x["t"]):
        tag = f"({lang_name(e['lang'])}) " if e["lang"] != prev else ""
        prev = e["lang"]
        who = f"{e['who']}: " if e.get("who") else ""
        lines.append(f"[{fmt(e['t'])}] {tag}{who}{e['text']}")
    return "\n".join(lines)


def run_mic(parent_frame, cfg, online, source="mic"):
    """Live transcription tab.
    source: "mic" (microphone), "system" (PC sound), "call" (both: You + Them)."""
    call = source == "call"
    use_mic, use_sys = source in ("mic", "call"), source in ("system", "call")
    try:
        import numpy as np
        if use_mic:
            import sounddevice as sd
        if use_sys:
            import pyaudiowpatch as pyaudio
    except ImportError:
        libs = [l for l, need in (("sounddevice", use_mic), ("PyAudioWPatch", use_sys)) if need]
        print(f"\n[!] This needs:  pip install {' '.join(libs)}\n")
        if use_sys:
            print("    (PC-sound capture works on Windows only.)")
        return
    nr = None
    if cfg.get("noise", "off") != "off":
        try:
            import noisereduce as nr
        except ImportError:
            print("[i] Live noise cleanup needs:  pip install noisereduce   (continuing without it)")
    import tkinter as tk
    from tkinter import ttk, messagebox, scrolledtext

    SRC_NAME = {"mic": "Microphone", "system": "System audio", "call": "Call"}[source]
    FONT = "Segoe UI"
    WHITE, RED, GREEN, GREY, BLUE = "#ffffff", "#d93025", "#1e8e3e", "#80868b", "#1a73e8"
    q, cap_q = queue.Queue(), queue.Queue()
    lock, model_lock = threading.Lock(), threading.Lock()

    def new_ch(key, label):
        return {"key": key, "label": label, "parts": [], "pending": np.zeros(0, np.float32),
                "offset": 0.0, "last_len": 0, "all": [], "level": 0.0, "rate": SR,
                "t0": None, "received": 0}

    chans = []
    if use_mic:
        chans.append(new_ch("mic", "You" if call else None))
    if use_sys:
        chans.append(new_ch("sys", "Them" if call else None))
    settings = load_settings()
    cs = dict(CAPTION_DEFAULTS)
    cs.update(settings.get("captions", {}))
    S = {"model": None, "recording": False, "entries": [], "finalize": False, "closing": False,
         "busy": False, "translations": {}, "alerts": [], "llm": None, "streams": [],
         "cap_on": False, "cap_lang": settings.get("caption_lang", CAP_FAST_EN),
         "alert_words": [], "pa": None}

    # ---------------- tab
    root = parent_frame
    root.configure(bg=WHITE)

    top = tk.Frame(root, bg=WHITE)
    top.pack(fill="x", padx=14, pady=(12, 4))
    rec_btn = tk.Button(top, text="●  Record", font=(FONT, 12, "bold"), bg=RED, fg="white",
                        activebackground="#b3261e", activeforeground="white", relief="flat",
                        padx=18, pady=8, state="disabled")
    rec_btn.pack(side="left")
    info_col = tk.Frame(top, bg=WHITE)
    info_col.pack(side="left", padx=14, fill="x", expand=True)
    status = tk.Label(info_col, text="Loading Whisper model...", bg=WHITE, fg=GREY,
                      font=(FONT, 10, "bold"), anchor="w")
    status.pack(fill="x")
    lang_lbl = tk.Label(info_col, text="Language: -", bg=WHITE, fg=BLUE, font=(FONT, 10), anchor="w")
    lang_lbl.pack(fill="x")
    meters = {}
    mrow = tk.Frame(info_col, bg=WHITE)
    mrow.pack(anchor="w", pady=(3, 0))
    for ch in chans:
        if call:
            tk.Label(mrow, text=ch["label"], bg=WHITE, font=(FONT, 8)).pack(side="left")
        meters[ch["key"]] = ttk.Progressbar(mrow, maximum=100, length=(110 if call else 220))
        meters[ch["key"]].pack(side="left", padx=(2, 10))

    devcol = tk.Frame(top, bg=WHITE)
    devcol.pack(side="right")
    mic_devices, sys_devices = [], []
    if use_mic:
        mic_devices = [("Default microphone", None)]
        try:
            api = sd.default.hostapi
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0 and (api is None or d["hostapi"] == api):
                    mic_devices.append((d["name"], i))
        except Exception:
            pass
    if use_sys:
        try:
            S["pa"] = pyaudio.PyAudio()
            wasapi = S["pa"].get_host_api_info_by_type(pyaudio.paWASAPI)
            default_out = S["pa"].get_device_info_by_index(wasapi["defaultOutputDevice"])["name"]
            loops = sorted(S["pa"].get_loopback_device_info_generator(),
                           key=lambda d: default_out not in d["name"])
            sys_devices = [(d["name"], d["index"]) for d in loops]
        except Exception as e:
            print(f"[!] Could not list PC sound devices: {e}")
        if not sys_devices:
            sys_devices = [("(no PC sound device found)", None)]
    mic_var = tk.StringVar(value=mic_devices[0][0] if mic_devices else "")
    sys_var = tk.StringVar(value=sys_devices[0][0] if sys_devices else "")
    if use_mic:
        tk.Label(devcol, text="Microphone" + (" (You):" if call else ":"), bg=WHITE,
                 font=(FONT, 9)).pack(anchor="e")
        ttk.Combobox(devcol, textvariable=mic_var, values=[n for n, _ in mic_devices],
                     state="readonly", width=32).pack()
    if use_sys:
        tk.Label(devcol, text="PC sound from" + (" (Them):" if call else ":"), bg=WHITE,
                 font=(FONT, 9)).pack(anchor="e")
        ttk.Combobox(devcol, textvariable=sys_var, values=[n for n, _ in sys_devices],
                     state="readonly", width=32).pack()

    hrow = tk.Frame(root, bg=WHITE)
    hrow.pack(fill="x", padx=14, pady=(6, 2))
    tk.Label(hrow, text="Live transcript  (grey = still listening, black = final)", bg=WHITE,
             font=(FONT, 10, "bold")).pack(side="left")
    if call:
        tk.Label(hrow, text="Tip: wear headphones, so your mic doesn't also pick up the other side",
                 bg=WHITE, fg=GREY, font=(FONT, 9)).pack(side="right")
    txt = scrolledtext.ScrolledText(root, wrap="word", font=(FONT, 12), height=9,
                                    relief="solid", bd=1, padx=8, pady=6)
    txt.pack(fill="both", expand=True, padx=14)
    txt.tag_configure("prov", foreground=GREY)
    txt.tag_configure("lang", foreground=BLUE, font=(FONT, 10, "bold"))
    txt.tag_configure("alert", background="#fce8e6", foreground="#c5221f")
    txt.mark_set("cend", "1.0")
    txt.mark_gravity("cend", "left")

    # captions + alerts
    crow = tk.Frame(root, bg=WHITE)
    crow.pack(fill="x", padx=14, pady=(8, 0))
    cap_var = tk.BooleanVar(value=False)
    tk.Checkbutton(crow, text="Captions on screen", variable=cap_var, bg=WHITE, activebackground=WHITE,
                   font=(FONT, 10, "bold"), command=lambda: toggle_captions()).pack(side="left")
    cap_lang_var = tk.StringVar(value=S["cap_lang"])
    cap_choices = [CAP_ORIGINAL, CAP_FAST_EN] + OUTPUT_CHOICES[1:]
    cl = ttk.Combobox(crow, textvariable=cap_lang_var, values=cap_choices, state="readonly", width=20)
    cl.pack(side="left", padx=6)
    tk.Button(crow, text="Caption settings...", font=(FONT, 9), relief="flat", bg="#e8f0fe",
              command=lambda: caption_settings_window(ROOT, cs, apply_captions)).pack(side="left")
    arow = tk.Frame(root, bg=WHITE)
    arow.pack(fill="x", padx=14, pady=(4, 0))
    tk.Label(arow, text="Alert words:", bg=WHITE, font=(FONT, 10, "bold")).pack(side="left")
    alert_var = tk.StringVar(value=settings.get("alert_words", ""))
    tk.Entry(arow, textvariable=alert_var, width=40, font=(FONT, 10)).pack(side="left", padx=6)
    tk.Label(arow, text="comma separated", bg=WHITE, fg=GREY, font=(FONT, 9)).pack(side="left")
    beep_var = tk.BooleanVar(value=settings.get("alert_beep", True))
    tk.Checkbutton(arow, text="Beep", variable=beep_var, bg=WHITE, activebackground=WHITE,
                   font=(FONT, 10)).pack(side="left", padx=8)
    alert_count = tk.Label(arow, text="", bg=WHITE, fg=RED, font=(FONT, 10, "bold"))
    alert_count.pack(side="left")

    trow = tk.Frame(root, bg=WHITE)
    trow.pack(fill="x", padx=14, pady=(8, 2))
    tk.Label(trow, text="Translate to:", bg=WHITE, font=(FONT, 10, "bold")).pack(side="left")
    default_t = next((o for o in cfg.get("outputs", []) if o != "Original"), "English")
    tr_var = tk.StringVar(value=default_t)
    ttk.Combobox(trow, textvariable=tr_var, values=OUTPUT_CHOICES[1:], state="readonly",
                 width=14).pack(side="left", padx=6)
    tr_btn = tk.Button(trow, text="Translate", font=(FONT, 10), relief="flat", bg="#e8f0fe",
                       padx=12, pady=3, state="disabled")
    tr_btn.pack(side="left")
    read_btn = tk.Button(trow, text="Read aloud", font=(FONT, 10), relief="flat", bg="#e6f4ea",
                         padx=12, pady=3)
    read_btn.pack(side="left", padx=6)
    tr_status = tk.Label(trow, text="", bg=WHITE, fg=GREY, font=(FONT, 9), anchor="w")
    tr_status.pack(side="left", padx=4, fill="x", expand=True)

    out = scrolledtext.ScrolledText(root, wrap="word", font=(FONT, 12), height=5,
                                    relief="solid", bd=1, padx=8, pady=6)
    out.pack(fill="both", expand=True, padx=14)

    brow = tk.Frame(root, bg=WHITE)
    brow.pack(fill="x", padx=14, pady=10)
    save_btn = tk.Button(brow, text="Save", font=(FONT, 10, "bold"), bg=BLUE, fg="white",
                         relief="flat", padx=16, pady=5, state="disabled")
    save_btn.pack(side="right")
    copy_btn = tk.Button(brow, text="Copy text", font=(FONT, 10), relief="flat", padx=12, pady=5)
    copy_btn.pack(side="right", padx=6)
    clear_btn = tk.Button(brow, text="Clear", font=(FONT, 10), relief="flat", padx=12, pady=5)
    clear_btn.pack(side="left")
    redo_btn = tk.Button(brow, text="Clean up & re-transcribe", font=(FONT, 10), relief="flat",
                         bg="#fef7e0", padx=12, pady=5, state="disabled")
    redo_btn.pack(side="left", padx=6)

    player = SpeechPlayer(online, on_status=lambda s: q.put(("speech", s)))

    # ---------------- audio input
    def feed(ch, chunk):
        if ch["rate"] != SR:
            n = int(len(chunk) * SR / ch["rate"])
            if n <= 0:
                return
            chunk = np.interp(np.linspace(0, len(chunk) - 1, n), np.arange(len(chunk)),
                              chunk).astype(np.float32)
        with lock:
            if ch["t0"] is not None:   # PC sound sends nothing during silence: keep the timeline
                gap = int((time.time() - ch["t0"]) * SR) - ch["received"] - len(chunk)
                if gap > int(0.12 * SR):
                    z = np.zeros(gap, np.float32)
                    ch["parts"].append(z)
                    ch["all"].append(z)
                    ch["received"] += gap
            ch["parts"].append(chunk)
            ch["all"].append(chunk)
            ch["received"] += len(chunk)
        ch["level"] = float(np.sqrt(np.mean(chunk ** 2)))

    def pad_to_now(ch):
        with lock:
            if ch["t0"] is None:
                return
            gap = int((time.time() - ch["t0"]) * SR) - ch["received"]
            if gap > 0:
                z = np.zeros(gap, np.float32)
                ch["parts"].append(z)
                ch["all"].append(z)
                ch["received"] += gap

    class LoopbackStream:
        def __init__(self, ch, index):
            pa = S["pa"]
            info = pa.get_device_info_by_index(index)
            nch = max(1, int(info["maxInputChannels"]))
            ch["rate"] = int(info["defaultSampleRate"])

            def pcb(in_data, frame_count, time_info, status_):
                a = np.frombuffer(in_data, np.int16).reshape(-1, nch).mean(axis=1)
                feed(ch, (a / 32768.0).astype(np.float32))
                return (None, pyaudio.paContinue)

            self.s = pa.open(format=pyaudio.paInt16, channels=nch, rate=ch["rate"], input=True,
                             input_device_index=index, frames_per_buffer=int(ch["rate"] * 0.1),
                             stream_callback=pcb)

        def start(self):
            self.s.start_stream()

        def stop(self):
            self.s.stop_stream()

        def close(self):
            self.s.close()

    def open_stream(ch):
        if ch["key"] == "sys":
            idx = dict(sys_devices).get(sys_var.get())
            if idx is None:
                raise RuntimeError("No PC sound device found.")
            return LoopbackStream(ch, idx)
        dev = dict(mic_devices).get(mic_var.get())
        cb = lambda indata, f, t, s_: feed(ch, indata[:, 0].astype(np.float32))
        ch["rate"] = SR
        try:
            return sd.InputStream(samplerate=SR, channels=1, dtype="float32", device=dev,
                                  blocksize=int(SR * 0.1), callback=cb)
        except Exception:
            ch["rate"] = int(sd.query_devices(dev, "input")["default_samplerate"])
            return sd.InputStream(samplerate=ch["rate"], channels=1, dtype="float32", device=dev,
                                  blocksize=int(ch["rate"] * 0.1), callback=cb)

    # ---------------- recognition
    def cut(ch, sec):
        with lock:
            n = int(sec * SR)
            ch["pending"] = ch["pending"][n:]
            ch["offset"] += n / SR
            ch["last_len"] = 0

    def check_alerts(text, t, who):
        low = text.lower()
        hits = [w for w in S["alert_words"] if w.lower() in low]
        if hits:
            S["alerts"].append({"t": t, "who": who, "words": hits, "text": text})
            q.put(("alert", hits, t, who))

    def commit(ch, segs, code, audio, upto):
        text = " ".join(s.text.strip() for s in segs)
        t = ch["offset"] + segs[0].start
        S["entries"].append({"t": t, "lang": code, "text": text, "who": ch["label"],
                             "dur": max(segs[-1].end - segs[0].start, 0.5)})
        q.put(("commit", ch["key"], text, code, ch["label"]))
        check_alerts(text, t, ch["label"])
        if not S["cap_on"] or S["cap_lang"] == CAP_ORIGINAL:
            return
        if S["cap_lang"] == CAP_FAST_EN:
            piece = audio[int(segs[0].start * SR): int(upto * SR)]
            try:
                with model_lock:
                    tsegs, _ = S["model"].transcribe(piece, language=code, task="translate", beam_size=1,
                                                     vad_filter=True, condition_on_previous_text=False)
                    tr = " ".join(s.text.strip() for s in tsegs if s.text.strip())
            except Exception:
                tr = ""
            q.put(("caption", tr or text, text, ch["label"], "English"))
        else:
            cap_q.put((text, S["cap_lang"], ch["label"]))

    def process(ch, audio, final):
        dur = len(audio) / SR
        lang = cfg["language"]
        mine = [e for e in S["entries"] if e["who"] == ch["label"]]
        if not lang and dur < 3 and mine:
            lang = mine[-1]["lang"]   # too short to detect reliably: keep this speaker's language
        if nr is not None:
            try:
                audio = nr.reduce_noise(y=audio, sr=SR, stationary=True, prop_decrease=0.8).astype(np.float32)
            except Exception:
                pass
        with model_lock:
            segs, info = S["model"].transcribe(
                audio, language=lang, beam_size=(5 if final else LIVE_BEAM_SIZE),
                vad_filter=True, condition_on_previous_text=False, **vocab_kwargs(S["model"]))
            segs = [s for s in segs if s.text.strip() and not is_hallucination(s.text, s)]
        code = lang or info.language
        if not segs:
            if final:
                cut(ch, dur)
            elif dur > 4:
                cut(ch, dur - 1.0)   # drop the silence, but keep the last second: speech may be starting
            q.put(("prov", ch["key"], "", None, ch["label"]))
            return
        if final or dur - segs[-1].end >= LIVE_SILENCE_COMMIT_SEC:
            commit(ch, segs, code, audio, dur)
            cut(ch, dur)
            q.put(("prov", ch["key"], "", code, ch["label"]))
        elif (dur >= LIVE_COMMIT_SEC or dur >= LIVE_MAX_PENDING_SEC) and len(segs) > 1:
            commit(ch, segs[:-1], code, audio, segs[-2].end)
            cut(ch, segs[-2].end)
            q.put(("prov", ch["key"], segs[-1].text.strip(), code, ch["label"]))
        elif dur >= LIVE_MAX_PENDING_SEC:
            commit(ch, segs, code, audio, segs[-1].end)
            cut(ch, segs[-1].end)
            q.put(("prov", ch["key"], "", code, ch["label"]))
        else:
            q.put(("prov", ch["key"], " ".join(s.text.strip() for s in segs), code, ch["label"]))

    def take(ch):
        with lock:
            if ch["parts"]:
                ch["pending"] = np.concatenate([ch["pending"]] + ch["parts"])
                ch["parts"] = []
            return ch["pending"]

    def worker():
        try:
            S["model"] = load_whisper(cfg["model"])
        except BaseException as e:
            q.put(("error", f"Could not load the Whisper model: {e}"))
            return
        q.put(("ready",))
        while not S["closing"]:
            try:
                if S["finalize"] and not S["recording"]:
                    for ch in chans:
                        pending = take(ch)
                        if len(pending) / SR >= 0.3:
                            process(ch, pending, final=True)
                        with lock:
                            ch["offset"] += len(ch["pending"]) / SR
                            ch["pending"] = np.zeros(0, np.float32)
                    end = max(ch["offset"] for ch in chans)   # line the channels up again
                    for ch in chans:
                        pad = int((end - ch["offset"]) * SR)
                        with lock:
                            if pad > 0:
                                ch["all"].append(np.zeros(pad, np.float32))
                            ch["offset"] = end
                    S["finalize"] = False
                    q.put(("stopped",))
                    continue
                did = False
                for ch in chans:
                    pending = take(ch)
                    if S["recording"] and len(pending) / SR >= 1.0 and len(pending) != ch["last_len"]:
                        ch["last_len"] = len(pending)
                        process(ch, pending, final=False)
                        did = True
                if not did:
                    time.sleep(0.12)
            except Exception as e:
                q.put(("error", f"Recognition error: {e}"))
                time.sleep(1)

    def cap_worker():   # AI translation of captions into any language
        while not S["closing"]:
            try:
                text, target, who = cap_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if cap_q.qsize() > 2:   # falling behind: merge what's waiting
                more = [text]
                while not cap_q.empty():
                    more.append(cap_q.get_nowait()[0])
                text = " ".join(more)
            if S["llm"] is None:
                S["llm"] = next(iter(text_llms(online)), False)
            if not S["llm"]:
                q.put(("speech", f"No AI translator for {target} captions (needs Claude Code, Ollama or "
                                 f"LM Studio) - showing the original words"))
                q.put(("caption", text, text, who, None))
                continue
            try:
                tr = S["llm"][1]("You translate live subtitles. Output ONLY the translation, nothing else.",
                                 f"Translate into {target}:\n{text}{vocab_note()}")
                q.put(("caption", strip_thinking(tr).strip(), text, who, target))
            except Exception as e:
                q.put(("speech", f"Caption translation failed: {str(e)[:80]}"))
                q.put(("caption", text, text, who, None))

    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=cap_worker, daemon=True).start()

    # ---------------- captions
    cap = {"bar": None, "done": [], "prov": {}, "last_who": None, "orig": ""}

    def save_ui_settings():
        s = load_settings()
        s.update(captions={k: cs[k] for k in CAPTION_DEFAULTS}, caption_lang=S["cap_lang"],
                 alert_words=alert_var.get(), alert_beep=bool(beep_var.get()))
        save_settings(s)

    def apply_captions():
        if cap["bar"]:
            cap["bar"].apply()
        save_ui_settings()

    def cap_refresh():
        if not cap["bar"]:
            return
        main = " ".join(cap["done"][-40:])
        if S["cap_lang"] == CAP_ORIGINAL:
            provs = [f"{w}: {t}" if (call and w) else t for (t, w) in cap["prov"].values() if t]
            main = (main + " " + " ".join(provs)).strip()
        sub = cap["orig"] if cs["show_original"] and S["cap_lang"] != CAP_ORIGINAL else ""
        cap["bar"].set_text(main, sub)

    def cap_add(text, who, original="", speak_lang=None):
        if call and who and who != cap["last_who"]:
            text = f"{who}: {text}"
        cap["last_who"] = who
        cap["done"].append(text)
        cap["orig"] = original
        cap_refresh()
        if cs["speak"] and speak_lang:
            player.say(re.sub(r"^(You|Them): ", "", text), speak_lang)

    def toggle_captions():
        S["cap_on"] = bool(cap_var.get())
        if S["cap_on"] and not cap["bar"]:
            cap["bar"] = CaptionBar(ROOT, cs, on_moved=save_ui_settings,
                                    on_settings=lambda: caption_settings_window(ROOT, cs, apply_captions),
                                    on_hide=lambda: (cap_var.set(False), toggle_captions()))
            cap_refresh()
        elif not S["cap_on"] and cap["bar"]:
            cap["bar"].destroy()
            cap["bar"] = None

    def on_cap_lang(*_):
        S["cap_lang"] = cap_lang_var.get()
        cap["done"].clear()
        cap_refresh()
        save_ui_settings()
    cl.bind("<<ComboboxSelected>>", on_cap_lang)

    def on_alert_words(*_):
        S["alert_words"] = [w.strip() for w in alert_var.get().split(",") if w.strip()]
        highlight_alerts()
    alert_var.trace_add("write", on_alert_words)

    def highlight_alerts():
        txt.tag_remove("alert", "1.0", "end")
        for w in S["alert_words"]:
            start = "1.0"
            while True:
                pos = txt.search(w, start, stopindex="cend", nocase=True)
                if not pos:
                    break
                end = f"{pos}+{len(w)}c"
                txt.tag_add("alert", pos, end)
                start = end

    on_alert_words()

    # ---------------- UI actions
    def lang_summary():
        tot = Counter()
        for e in S["entries"]:
            tot[e["lang"]] += e["dur"]
        total = sum(tot.values()) or 1
        return ", ".join(f"{lang_name(c)} ({d / total:.0%})" for c, d in tot.most_common())

    def main_lang():
        tot = Counter()
        for e in S["entries"]:
            tot[e["lang"]] += e["dur"]
        return lang_name(tot.most_common(1)[0][0]) if tot else "English"

    def set_buttons():
        idle = not S["recording"] and not S["finalize"]
        has = bool(S["entries"])
        tr_btn.configure(state=("normal" if idle and has and not S["busy"] else "disabled"))
        save_btn.configure(state=("normal" if idle and has else "disabled"))
        redo_btn.configure(state=("normal" if idle and has and not S["busy"] else "disabled"))
        read_btn.configure(text=("Stop reading" if player.busy else "Read aloud"))

    def toggle():
        if not S["recording"]:
            opened = []
            try:
                for ch in chans:
                    s_ = open_stream(ch)
                    opened.append(s_)
                now = time.time()
                for ch in chans:
                    ch["t0"], ch["received"] = now, 0
                for s_ in opened:
                    s_.start()
            except Exception as e:
                for s_ in opened:
                    try:
                        s_.close()
                    except Exception:
                        pass
                messagebox.showerror(SRC_NAME, f"Could not start capturing:\n{e}", parent=root)
                return
            S["streams"], S["recording"] = opened, True
            rec_btn.configure(text="■  Stop", bg="#3c4043")
            status.configure(text={"mic": "Listening... speak now",
                                   "system": "Capturing PC sound... (text appears when something plays)",
                                   "call": "Capturing the call - both sides..."}[source], fg=RED)
        else:
            S["recording"] = False
            for s_ in S["streams"]:
                try:
                    s_.stop()
                    s_.close()
                except Exception:
                    pass
            for ch in chans:
                pad_to_now(ch)
                ch["t0"] = None
                ch["level"] = 0
            S["finalize"] = True
            rec_btn.configure(state="disabled")
            status.configure(text="Finishing the last words...", fg=GREY)
        set_buttons()

    def whisper_english():
        lines = []
        for ch in chans:
            with lock:
                audio = np.concatenate(ch["all"]) if ch["all"] else np.zeros(0, np.float32)
            if not len(audio):
                continue
            with model_lock:
                segs, _ = S["model"].transcribe(audio, language=cfg["language"], task="translate",
                                                vad_filter=True, **vocab_kwargs(S["model"]))
                for s in segs:
                    if s.text.strip():
                        who = f"{ch['label']}: " if ch["label"] else ""
                        lines.append((s.start, f"[{fmt(s.start)}] {who}{s.text.strip()}"))
        return "\n".join(l for _, l in sorted(lines))

    def translate():
        target = tr_var.get()
        stamped = stamped_from_entries(S["entries"])
        S["busy"] = True
        set_buttons()
        tr_status.configure(text=f"Translating to {target}...")

        def job():
            text, by = translate_transcript(stamped, target, internet_ok())
            if not text and target == "English":
                text, by = whisper_english(), "Whisper"
            q.put(("translated", target, text, by))

        threading.Thread(target=job, daemon=True).start()

    def redo():
        level = cfg.get("noise", "off")
        level = "studio" if level in ("off", "light", "strong") else level
        name = dict((v, k) for k, v in NOISE_CHOICES)[level]
        if not messagebox.askyesno(
                "Clean up & re-transcribe",
                f"Clean the whole recording with '{name}' (voice isolation + noise removal) and "
                f"transcribe it again at full quality?\n\nThis replaces the live transcript and can take "
                f"a while (progress is shown in the black console window).", parent=root):
            return
        S["busy"] = True
        set_buttons()
        status.configure(text=f"Cleaning up with {name} and re-transcribing... (see console)", fg=GREY)

        def job():
            new = []
            try:
                tmp = Path(tempfile.mkdtemp(prefix="vidsum_redo_"))
                for ch in chans:
                    with lock:
                        audio = np.concatenate(ch["all"]) if ch["all"] else np.zeros(0, np.float32)
                    if len(audio) < SR:
                        continue
                    raw = tmp / f"{ch['key']}_raw.wav"
                    with wave.open(str(raw), "wb") as w:
                        w.setnchannels(1)
                        w.setsampwidth(2)
                        w.setframerate(SR)
                        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
                    print(f"\n--- {ch['label'] or SRC_NAME}: cleaning {fmt(len(audio) / SR)} of audio ---")
                    (tmp / ch["key"]).mkdir(exist_ok=True)
                    path, _ = prepare_audio(raw, None, level, tmp / ch["key"], online)
                    kw = decode_kwargs(S["model"], noisy=True)
                    if not cfg["language"] and "multilingual" in inspect.signature(S["model"].transcribe).parameters:
                        kw["multilingual"] = True
                    with model_lock:
                        segs, info = S["model"].transcribe(path, language=cfg["language"], **kw)
                        guard = LoopGuard()
                        for s_ in segs:
                            t_ = s_.text.strip()
                            if not t_ or is_hallucination(t_, s_) or guard.repeat(t_):
                                continue
                            new.append({"t": s_.start, "lang": cfg["language"] or info.language,
                                        "text": t_ + (" [unclear]" if unclear(s_) else ""),
                                        "who": ch["label"], "dur": max(s_.end - s_.start, 0.5)})
                shutil.rmtree(tmp, ignore_errors=True)
                q.put(("redone", new, name))
            except Exception as e:
                q.put(("redone", None, str(e)[:150]))

        threading.Thread(target=job, daemon=True).start()

    def render_entries():
        txt.delete("1.0", "end")
        txt.mark_set("cend", "1.0")
        ui["last"] = None
        txt.mark_gravity("cend", "right")
        for e in sorted(S["entries"], key=lambda x: x["t"]):
            if (e["who"], e["lang"]) != ui["last"]:
                label = " · ".join(x for x in (e["who"], lang_name(e["lang"])) if x)
                txt.insert("cend", f"{chr(10) if ui['last'] else ''}[{label}] ", "lang")
                ui["last"] = (e["who"], e["lang"])
            txt.insert("cend", e["text"] + " ")
        txt.mark_gravity("cend", "left")
        highlight_alerts()

    def read_aloud():
        if player.busy:
            player.stop()
            return
        shown = out.get("1.0", "end").strip()
        if shown:
            text, lang = shown, S.get("out_lang", tr_var.get())
        else:
            text, lang = " ".join(e["text"] for e in sorted(S["entries"], key=lambda e: e["t"])), main_lang()
        if not text.strip():
            tr_status.configure(text="Nothing to read yet.")
            return
        player.say(re.sub(r"\b(You|Them): ", "", text), lang)
        tr_status.configure(text="Preparing speech...")
        root.after(300, set_buttons)

    def save():
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base = SAVE_DIR / f"{source}_{stamp}"
        with lock:
            tracks = [np.concatenate(ch["all"]) if ch["all"] else np.zeros(0, np.float32) for ch in chans]
        n = max(len(t) for t in tracks) if tracks else 0
        audio = np.zeros(n, np.float32)
        for t in tracks:
            audio[:len(t)] += t
        if len(tracks) > 1:
            audio /= len(tracks)
        duration = n / SR
        title = f"{SRC_NAME} recording"
        lang_line = f"Languages spoken: {lang_summary()}"
        note = ""
        if S["alerts"]:
            note = "\n===== ALERTS =====\n" + "\n".join(
                f"[{fmt(a['t'])}] {(a['who'] + ': ') if a['who'] else ''}{', '.join(a['words'])}  ->  {a['text']}"
                for a in S["alerts"]) + "\n"
        files = [Path(f"{base}_transcript.txt")]
        write_transcript(files[0], title, lang_line, duration, stamped_from_entries(S["entries"]), note)
        for target, (text, by) in S["translations"].items():
            f = Path(f"{base}_transcript_{safe_name(target)}.txt")
            write_transcript(f, title, f"{lang_line}  |  Translated to {target} by {by}", duration, text)
            files.append(f)
        with wave.open(f"{base}_audio.wav", "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        files.append(Path(f"{base}_audio.wav"))
        add_history(source, f"{title} {datetime.datetime.now():%d %b %Y %H:%M}", SRC_NAME,
                    lang_summary(), duration, files)
        messagebox.showinfo("Saved", f"Saved to:\n{SAVE_DIR}\n\n{base.name}_*", parent=root)
        open_path(SAVE_DIR)

    def copy():
        root.clipboard_clear()
        root.clipboard_append(stamped_from_entries(S["entries"]) if call else
                              " ".join(e["text"] for e in sorted(S["entries"], key=lambda e: e["t"])))
        status.configure(text="Text copied to clipboard", fg=GREEN)

    def clear():
        if S["recording"]:
            return
        if S["entries"] and not messagebox.askyesno("Clear", "Clear the transcript and recording?", parent=root):
            return
        with lock:
            for ch in chans:
                ch.update(all=[], parts=[], offset=0.0, last_len=0, received=0,
                          pending=np.zeros(0, np.float32))
            S.update(entries=[], translations={}, alerts=[])
        txt.delete("1.0", "end")
        txt.mark_set("cend", "1.0")
        out.delete("1.0", "end")
        ui.update(last=None, prov={})
        cap.update(done=[], prov={}, last_who=None, orig="")
        cap_refresh()
        lang_lbl.configure(text="Language: -")
        alert_count.configure(text="")
        tr_status.configure(text="")
        set_buttons()

    ui = {"last": None, "prov": {}}

    def show_prov():
        txt.delete("cend", "end-1c")
        parts = [(f"[{w}] " if (call and w) else "") + t for (t, w) in ui["prov"].values() if t]
        if parts:
            txt.insert("cend", " " + "   ".join(parts), "prov")
            txt.see("end")

    def beep():
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            root.bell()

    def poll():
        while True:
            try:
                msg = q.get_nowait()
            except queue.Empty:
                break
            kind = msg[0]
            if kind == "ready":
                rec_btn.configure(state="normal")
                status.configure(text=f"Ready - press Record  (model: {cfg['model']})", fg=GREEN)
            elif kind == "error":
                status.configure(text=msg[1][:140], fg=RED)
            elif kind == "commit":
                _, key, text, code, who = msg
                ui["prov"].pop(key, None)
                txt.delete("cend", "end-1c")
                txt.mark_gravity("cend", "right")
                if (who, code) != ui["last"]:
                    label = " · ".join(x for x in (who, lang_name(code)) if x)
                    txt.insert("cend", f"{chr(10) if ui['last'] else ''}[{label}] ", "lang")
                    ui["last"] = (who, code)
                txt.insert("cend", text + " ")
                txt.mark_gravity("cend", "left")
                highlight_alerts()
                show_prov()
                txt.see("end")
                lang_lbl.configure(text=f"Language: {lang_summary()}")
                if S["cap_on"] and S["cap_lang"] == CAP_ORIGINAL:
                    cap["prov"].pop(key, None)
                    cap_add(text, who, speak_lang=None)
            elif kind == "prov":
                _, key, text, code, who = msg
                ui["prov"][key] = (text, who)
                show_prov()
                if S["cap_on"] and S["cap_lang"] == CAP_ORIGINAL:
                    cap["prov"][key] = (text, who)
                    cap_refresh()
                if code and not S["entries"]:
                    lang_lbl.configure(text=f"Language: {lang_name(code)}")
            elif kind == "caption":
                _, tr, orig, who, lang = msg
                if S["cap_on"]:
                    cap_add(tr, who, orig, speak_lang=lang)
            elif kind == "alert":
                _, words, t, who = msg
                status.configure(text=f"ALERT: '{', '.join(words)}' at {fmt(t)}" + (f" ({who})" if who else ""),
                                 fg=RED)
                alert_count.configure(text=f"{len(S['alerts'])} alert{'s' if len(S['alerts']) != 1 else ''}")
                if beep_var.get():
                    beep()
                if cap["bar"]:
                    cap["bar"].win.configure(highlightthickness=4, highlightbackground="#d93025")
                    root.after(1500, lambda: cap["bar"] and cap["bar"].win.configure(highlightthickness=0))
            elif kind == "stopped":
                ui["prov"] = {}
                txt.delete("cend", "end-1c")
                rec_btn.configure(text="●  Record", bg=RED, state="normal")
                status.configure(text="Stopped - press Record to continue, or translate / read / save below",
                                 fg=GREY)
                if S["entries"]:
                    lang_lbl.configure(text=f"Language: {lang_summary()}")
            elif kind == "translated":
                _, target, text, by = msg
                S["busy"] = False
                if text:
                    S["translations"][target] = (text, by)
                    S["out_lang"] = target
                    out.delete("1.0", "end")
                    out.insert("1.0", re.sub(r"^\[\d\d:\d\d:\d\d\]\s*", "", text, flags=re.M))
                    tr_status.configure(text=f"{target} - by {by}")
                else:
                    tr_status.configure(text=f"No translator available for {target} "
                                             f"(needs Claude Code, Ollama or LM Studio)")
            elif kind == "redone":
                _, new, name = msg
                S["busy"] = False
                if new is None:
                    status.configure(text=f"Clean-up failed: {name}", fg=RED)
                else:
                    S["entries"], S["translations"] = sorted(new, key=lambda e: e["t"]), {}
                    S["alerts"] = [{"t": e["t"], "who": e["who"], "text": e["text"],
                                    "words": [w for w in S["alert_words"] if w.lower() in e["text"].lower()]}
                                   for e in S["entries"]
                                   if any(w.lower() in e["text"].lower() for w in S["alert_words"])]
                    alert_count.configure(text=f"{len(S['alerts'])} alert(s)" if S["alerts"] else "")
                    out.delete("1.0", "end")
                    render_entries()
                    lang_lbl.configure(text=f"Language: {lang_summary()}")
                    n_unclear = sum("[unclear]" in e["text"] for e in S["entries"])
                    status.configure(text=f"Re-transcribed after '{name}' cleanup"
                                          + (f" - {n_unclear} line(s) marked [unclear]" if n_unclear else ""),
                                     fg=GREEN)
            elif kind == "speech":
                if msg[1]:
                    tr_status.configure(text=msg[1][:160])
            set_buttons()
        for ch in chans:
            meters[ch["key"]]["value"] = min(100, ch["level"] * 400) if S["recording"] else 0
        root.after(100, poll)

    def on_close():
        S["closing"] = True
        save_ui_settings()
        player.stop()
        for s_ in S["streams"]:
            try:
                s_.stop()
                s_.close()
            except Exception:
                pass
        if cap["bar"]:
            cap["bar"].destroy()
        if S["pa"]:
            try:
                S["pa"].terminate()
            except Exception:
                pass
        NOTEBOOK.forget(root)

    rec_btn.configure(command=toggle)
    tr_btn.configure(command=translate)
    read_btn.configure(command=read_aloud)
    save_btn.configure(command=save)
    copy_btn.configure(command=copy)
    clear_btn.configure(command=clear)
    redo_btn.configure(command=redo)
    root.on_close = on_close
    poll()


# ---------------------------------------------------------------- main
def write_transcript(path, video_name, lang_line, duration, stamped_text, note=""):
    plain = re.sub(r"^\[\d\d:\d\d:\d\d\]\s*(\([^)]*\)\s*)?", "", stamped_text, flags=re.M)
    plain = " ".join(l.strip() for l in plain.splitlines() if l.strip())
    path.write_text(
        f"Transcript of: {video_name}\n{lang_line}  |  Duration: {fmt(duration)}\n{note}\n"
        f"===== TIMESTAMPED =====\n{stamped_text or '(No speech detected)'}\n\n"
        f"===== PLAIN TEXT =====\n{plain or '(No speech detected)'}\n",
        encoding="utf-8",
    )


def keep_awake(on: bool):
    """Stop Windows from going to sleep while a long job runs."""
    if not KEEP_PC_AWAKE or os.name != "nt":
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
    except Exception:
        pass


def open_path(p, select=False):
    try:
        if select and os.name == "nt":
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            os.startfile(str(p))
    except Exception:
        pass


# ---------------------------------------------------------------- history
HISTORY_FILE = SAVE_DIR / "history.json"
KIND_LABELS = {"file": "Video", "url": "Link", "mic": "Microphone", "system": "System audio",
               "call": "Call", "watch": "Watched"}


def load_history():
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_history(items):
    try:
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"  [!] Could not update history: {e}")


def add_history(kind, title, source, languages, duration, files):
    items = load_history()
    items.append({"time": datetime.datetime.now().isoformat(timespec="seconds"), "kind": kind,
                  "title": title, "source": str(source), "languages": languages,
                  "duration": duration, "files": [str(f) for f in files]})
    save_history(items)


def open_history(parent_frame):
    """History tab: browse and search everything processed so far."""
    import tkinter as tk
    from tkinter import ttk, messagebox, scrolledtext

    FONT = "Segoe UI"
    win = parent_frame
    win.configure(bg="#ffffff")

    top = tk.Frame(win, bg="#ffffff")
    top.pack(fill="x", padx=12, pady=(12, 6))
    tk.Label(top, text="Search:", bg="#ffffff", font=(FONT, 10, "bold")).pack(side="left")
    q_var = tk.StringVar()
    q_entry = tk.Entry(top, textvariable=q_var, font=(FONT, 11), width=40)
    q_entry.pack(side="left", padx=6)
    tk.Label(top, text="(titles, languages and the full text of transcripts & summaries)",
             bg="#ffffff", fg="#5f6368", font=(FONT, 9)).pack(side="left")
    count = tk.Label(top, bg="#ffffff", fg="#5f6368", font=(FONT, 9))
    count.pack(side="right")

    pane = ttk.PanedWindow(win, orient="horizontal")
    pane.pack(fill="both", expand=True, padx=12)

    left = tk.Frame(pane)
    cols = ("when", "type", "title", "langs", "len")
    tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
    for c, t, w in zip(cols, ("Date", "Type", "Title", "Languages", "Length"),
                       (125, 80, 170, 125, 60)):
        tree.heading(c, text=t)
        tree.column(c, width=w, anchor="w", stretch=(c == "title"))
    tree.tag_configure("missing", foreground="#9aa0a6")
    sb = ttk.Scrollbar(left, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    pane.add(left, weight=3)

    right = tk.Frame(pane, bg="#ffffff")
    frow = tk.Frame(right, bg="#ffffff")
    frow.pack(fill="x")
    tk.Label(frow, text="File:", bg="#ffffff", font=(FONT, 9, "bold")).pack(side="left")
    file_var = tk.StringVar()
    file_box = ttk.Combobox(frow, textvariable=file_var, state="readonly", width=48)
    file_box.pack(side="left", padx=4, fill="x", expand=True)
    preview = scrolledtext.ScrolledText(right, wrap="word", font=(FONT, 10), relief="solid", bd=1)
    preview.pack(fill="both", expand=True, pady=(4, 0))
    preview.tag_configure("hit", background="#fde293")
    pane.add(right, weight=2)

    btns = tk.Frame(win, bg="#ffffff")
    btns.pack(fill="x", padx=12, pady=10)

    state = {"items": [], "shown": [], "cache": {}, "job": None}

    def text_of(path):
        if path not in state["cache"]:
            try:
                state["cache"][path] = Path(path).read_text(encoding="utf-8", errors="replace")
            except Exception:
                state["cache"][path] = ""
        return state["cache"][path]

    def readable(e):
        return [f for f in e.get("files", []) if f.lower().endswith((".txt", ".md"))]

    def matches(e, q):
        if not q:
            return True
        meta = f"{e.get('title', '')} {e.get('source', '')} {e.get('languages', '')}".lower()
        return q in meta or any(q in text_of(f).lower() for f in readable(e))

    def fill():
        state["items"] = list(reversed(load_history()))
        q = q_var.get().strip().lower()
        state["shown"] = [e for e in state["items"] if matches(e, q)]
        tree.delete(*tree.get_children())
        for i, e in enumerate(state["shown"]):
            try:
                when = datetime.datetime.fromisoformat(e["time"]).strftime("%d %b %Y %H:%M")
            except Exception:
                when = e.get("time", "")
            exists = any(Path(f).exists() for f in e.get("files", []))
            tree.insert("", "end", iid=str(i), tags=(() if exists else ("missing",)),
                        values=(when, KIND_LABELS.get(e.get("kind"), e.get("kind", "")),
                                e.get("title", ""), e.get("languages", ""),
                                fmt(e.get("duration") or 0)))
        count.configure(text=f"{len(state['shown'])} of {len(state['items'])}")
        preview.delete("1.0", "end")
        file_box.configure(values=[])
        file_var.set("")
        if state["shown"]:
            tree.selection_set("0")

    def current():
        sel = tree.selection()
        return state["shown"][int(sel[0])] if sel else None

    def show_file(*_):
        e = current()
        preview.delete("1.0", "end")
        if not e:
            return
        path = next((f for f in readable(e) if Path(f).name == file_var.get()), None)
        if not path:
            return
        if not Path(path).exists():
            preview.insert("1.0", f"(File not found - it may have been moved or deleted)\n\n{path}")
            return
        preview.insert("1.0", text_of(path))
        q = q_var.get().strip()
        if q:
            start, first = "1.0", None
            while True:
                pos = preview.search(q, start, stopindex="end", nocase=True)
                if not pos:
                    break
                end = f"{pos}+{len(q)}c"
                preview.tag_add("hit", pos, end)
                first = first or pos
                start = end
            if first:
                preview.see(first)

    def on_select(*_):
        e = current()
        if not e:
            return
        names = [Path(f).name for f in readable(e)]
        file_box.configure(values=names)
        q = q_var.get().strip().lower()
        pick = next((Path(f).name for f in readable(e) if q and q in text_of(f).lower()), None)
        file_var.set(pick or (names[0] if names else ""))
        show_file()

    def on_search(*_):
        if state["job"]:
            win.after_cancel(state["job"])
        state["job"] = win.after(300, fill)

    def open_selected():
        e = current()
        path = next((f for f in readable(e) if Path(f).name == file_var.get()), None) if e else None
        if path and Path(path).exists():
            open_path(path)

    def open_folder():
        e = current()
        if not e:
            return
        f = next((f for f in e.get("files", []) if Path(f).exists()), None)
        if f:
            open_path(f, select=True)
        else:
            messagebox.showinfo("History", "The files for this item no longer exist.", parent=win)

    def remove():
        e = current()
        if not e or not messagebox.askyesno(
                "Remove", f"Remove '{e.get('title')}' from history?\n(The files themselves are kept.)",
                parent=win):
            return
        items = load_history()
        items = [x for x in items if not (x.get("time") == e.get("time") and x.get("title") == e.get("title"))]
        save_history(items)
        fill()

    tk.Button(btns, text="Open file", font=(FONT, 10, "bold"), bg="#1a73e8", fg="white",
              relief="flat", padx=14, pady=5, command=open_selected).pack(side="right")
    tk.Button(btns, text="Show in folder", font=(FONT, 10), relief="flat", padx=12, pady=5,
              command=open_folder).pack(side="right", padx=6)
    tk.Button(btns, text="Remove from history", font=(FONT, 10), relief="flat", padx=12, pady=5,
              command=remove).pack(side="left")
    tk.Button(btns, text="Refresh", font=(FONT, 10), relief="flat", padx=12, pady=5,
              command=fill).pack(side="left", padx=6)

    q_var.trace_add("write", on_search)
    tree.bind("<<TreeviewSelect>>", on_select)
    tree.bind("<Double-1>", lambda e: open_selected())
    file_box.bind("<<ComboboxSelected>>", show_file)
    fill()
    q_entry.focus_set()


# ---------------------------------------------------------------- sources
def pick_folder() -> str:
    from tkinter import filedialog
    path = filedialog.askdirectory(parent=ROOT, title="Select a folder of videos to process")
    return path


def list_videos(folder: Path, recursive: bool):
    files = folder.rglob("*") if recursive else folder.iterdir()
    return sorted(f for f in files
                  if f.is_file() and f.suffix.lower() in BATCH_EXTENSIONS and not f.name.startswith("."))


def already_done(f: Path) -> bool:
    return (f.parent / f"{f.stem}_transcript.txt").exists()


def download_url(url: str):
    """Download a video (or a whole playlist) with yt-dlp. Returns [(path, title, page_url)]."""
    try:
        import yt_dlp
    except ImportError:
        print("\n[!] Link downloads need one more library. Run:\n    pip install yt-dlp\n")
        return []

    out = SAVE_DIR / "Downloads"
    out.mkdir(parents=True, exist_ok=True)
    h = DOWNLOAD_MAX_HEIGHT
    if DOWNLOAD_AUDIO_ONLY:
        fmt_sel = "ba/b"
    elif shutil.which("ffmpeg"):
        fmt_sel = f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b"
    else:
        fmt_sel = f"b[height<={h}]/b"   # no ffmpeg: only formats that don't need merging

    def hook(d):
        name = Path(d.get("filename", "")).name[:50]
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes", 0)
            pct = f"{done * 100 / total:5.1f}%" if total else f"{done / 1e6:6.1f} MB"
            print(f"\r  Downloading {name}: {pct}", end="", flush=True)
        elif d["status"] == "finished":
            print(f"\r  Downloaded  {name}          ")

    opts = {"format": fmt_sel, "outtmpl": str(out / "%(title).80s [%(id)s].%(ext)s"),
            "windowsfilenames": True, "noplaylist": True, "ignoreerrors": True,
            "quiet": True, "no_warnings": True, "noprogress": True, "progress_hooks": [hook]}
    if not DOWNLOAD_AUDIO_ONLY and shutil.which("ffmpeg"):
        opts["merge_output_format"] = "mp4"

    print(f"Fetching: {url}")
    results = []
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                print("[!] Nothing could be downloaded from this link.")
                return []
            entries = list(info.get("entries") or []) if "entries" in info else [info]
            if "entries" in info:
                print(f"Playlist: {info.get('title', '')} ({len(entries)} videos)")
            for e in entries:
                if not e:
                    continue
                path = None
                for rd in e.get("requested_downloads") or []:
                    if rd.get("filepath"):
                        path = rd["filepath"]
                path = Path(path or ydl.prepare_filename(e))
                if path.exists():
                    results.append((path, e.get("title") or path.stem,
                                    e.get("webpage_url") or url))
    except Exception as e:
        print(f"\n[!] Download failed: {e}")
    return results


# ---------------------------------------------------------------- processing
def process_video(vpath: Path, cfg, model, online, kind="file", source=None, open_result=True):
    """Transcribe, translate and summarize one video. Returns the list of files created."""
    _notes_cache.clear()
    print(f"\nProcessing: {vpath}\n")
    clip = cfg.get("clip")
    tmpdir = Path(tempfile.mkdtemp(prefix="vidsum_audio_"))
    try:
        audio_src, offset = prepare_audio(vpath, clip, cfg.get("noise", "off"), tmpdir, online)
        return _process(vpath, audio_src, offset, clip, cfg, model, online, kind, source, open_result)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _process(vpath, audio_src, offset, clip, cfg, model, online, kind, source, open_result):
    noisy = cfg.get("noise", "off") != "off"
    # ---- Which languages are spoken?
    detections = detect_languages(model, audio_src) if DETECT_LANGUAGES else []
    detections = [(t + offset, c, p) for t, c, p in detections]
    stats = language_stats(detections, end_limit=(clip[1] if clip and clip[1] else None))
    used = [s for s in stats if s["share"] >= MIN_LANGUAGE_SHARE]
    mixed = len(used) > 1
    if stats:
        print_language_stats(stats)
        if mixed:
            print("This video mixes languages - each part will be transcribed in its own language.\n")

    # ---- Original transcript
    stamped, _, info = transcribe(
        model, audio_src, cfg["language"],
        multilingual=(mixed and cfg["language"] is None),
        detections=detections if mixed else None, offset=offset, noisy=noisy)
    body = "\n".join(stamped)

    if not used:
        used = [{"code": info.language, "name": lang_name(info.language), "share": 1.0}]
        print(f"Language: {lang_name(info.language)} ({info.language_probability:.0%})")
    main_code = cfg["language"] or used[0]["code"]
    main_name = lang_name(main_code)
    lang_desc = ", ".join(f"{s['name']} ({s['share']:.0%})" for s in used) if mixed else main_name
    lang_line = f"Languages spoken: {lang_desc}"

    out_dir, base = vpath.parent, vpath.stem
    note = ""
    if clip:
        end = offset + info.duration
        base += f"_part_{fmt(offset).replace(':', '-')}_to_{fmt(end).replace(':', '-')}"
        note = f"Part of the video: {fmt(offset)} to {fmt(end)}\n"
    if noisy:
        note += f"Voice cleanup: {dict((v, k) for k, v in NOISE_CHOICES).get(cfg['noise'], cfg['noise'])}\n"
    files = []
    if noisy and cfg.get("keep_clean") and audio_src != str(vpath):
        clean = out_dir / f"{base}_cleaned_voice.wav"
        shutil.copyfile(audio_src, clean)
        files.append(clean)
        print(f"Cleaned voice saved: {clean}  (listen to check the cleanup)")
    orig_file = out_dir / f"{base}_transcript.txt"
    write_transcript(orig_file, vpath.name, lang_line, info.duration, body, note)
    files.append(orig_file)
    print(f"Transcript saved: {orig_file}\n")

    # ---- Output languages
    targets, seen = [], set()
    for o in cfg["outputs"]:
        if o == "Original":
            name, is_orig = main_name, True
        else:
            name, is_orig = o, (not mixed and LANG_CODES.get(o) == main_code)
        if name not in seen:
            seen.add(name)
            targets.append((name, is_orig))

    # ---- Translated transcripts (+ spoken audio)
    for name, is_orig in targets:
        if is_orig or not body:
            continue
        text, by = translate_transcript(body, name, online)
        if not text and name == "English":
            text, by = whisper_translate_english(model, audio_src, cfg["language"], offset, noisy), "Whisper"
        if not text:
            print(f"  [!] No translator available for {name} (needs Claude Code, Ollama or LM Studio).")
            continue
        f = out_dir / f"{base}_transcript_{safe_name(name)}.txt"
        write_transcript(f, vpath.name, f"{lang_line}  |  Translated to {name} by {by}",
                         info.duration, text, note)
        files.append(f)
        print(f"Translation saved: {f}\n")
        if cfg.get("speak_save"):
            plain = re.sub(r"^\[\d\d:\d\d:\d\d\]\s*(\([^)]*\)\s*)?", "", text, flags=re.M)
            print(f"Creating {name} speech audio...")
            sp, info_ = tts_to_file(plain, name, out_dir / f"{base}_{safe_name(name)}_speech", online)
            if sp:
                files.append(sp)
                print(f"  Speech saved: {sp}  ({info_})\n")
            else:
                print(f"  [!] {info_}\n")

    # ---- Summaries
    summaries = []
    workdir = Path(tempfile.mkdtemp(prefix="vidsum_"))
    try:
        (workdir / "transcript.txt").write_text(body or "(No speech detected)", encoding="utf-8")
        frames, interval = [], 0
        if USE_FRAMES:
            print("Extracting key frames...")
            frames, interval = extract_frames(str(vpath), info.duration, workdir, start=offset)
            print(f"  {len(frames)} frames\n")

        for name, _ in targets:
            print(f"Creating {name} summary...")
            res = summarize(workdir, body, vpath.name, frames, interval, lang_desc, name, online)
            if not res:
                print(f"  [!] Could not create the {name} summary.\n")
                continue
            summary, by = res
            suffix = "" if len(targets) == 1 else f"_{safe_name(name)}"
            f = out_dir / f"{base}_summary{suffix}.md"
            f.write_text(f"{summary}\n\n---\n_{lang_line}. {note.strip()} Summary by: {by}_\n",
                         encoding="utf-8")
            files.append(f)
            summaries.append((name, f, summary))
            print(f"  Saved: {f}\n")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    add_history(kind, base, source or vpath, lang_desc, info.duration, files + [vpath])

    # ---- Done
    print("=" * 60)
    if stats:
        print(lang_line)
    print("Files created:")
    for f in files:
        print(f"  {f}")
    print("=" * 60)
    if open_result:
        if summaries:
            print(f"\n{summaries[0][2]}\n")
        open_path(summaries[0][1] if summaries else orig_file)
    return files


def run_watch(folder: Path, cfg, model, online, stop_event=None):
    """Keep watching a folder; every new video that appears is processed automatically."""
    import traceback
    cfg = dict(cfg, clip=None)
    recursive = cfg.get("subfolders", False)
    print("\n" + "=" * 70)
    print(f"Watching: {folder}" + ("  (and subfolders)" if recursive else ""))
    print("Drop or copy videos into this folder - they are processed automatically.")
    print("Videos already processed (with a _transcript.txt next to them) are skipped.")
    print("Press Ctrl+C to stop watching.")
    print("=" * 70)
    seen, failed, done = {}, set(), 0
    try:
        while not (stop_event and stop_event.is_set()):
            for f in list_videos(folder, recursive):
                if f in failed or already_done(f):
                    continue
                try:
                    stt = f.stat()
                except OSError:
                    continue
                sig = (stt.st_size, stt.st_mtime)
                prev = seen.get(f)
                if not prev or prev[0] != sig:          # new, or still being copied
                    seen[f] = (sig, time.time())
                    continue
                if time.time() - prev[1] < WATCH_STABLE_SEC:
                    continue
                try:                                   # still locked by the copy?
                    with open(f, "rb"):
                        pass
                except OSError:
                    continue
                print(f"\n[{datetime.datetime.now():%H:%M:%S}] New video: {f.name}")
                keep_awake(True)
                try:
                    process_video(f, cfg, model, online, kind="watch", open_result=False)
                    done += 1
                    try:
                        import winsound
                        winsound.MessageBeep(winsound.MB_OK)
                    except Exception:
                        pass
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    traceback.print_exc()
                    print(f"[!] Failed: {f.name}: {e}  - it will be skipped.")
                    failed.add(f)
                finally:
                    keep_awake(False)
                print(f"\n[{datetime.datetime.now():%H:%M:%S}] Watching {folder} ... "
                      f"({done} processed so far)")
            if stop_event:
                stop_event.wait(WATCH_INTERVAL_SEC)
            else:
                time.sleep(WATCH_INTERVAL_SEC)
    except KeyboardInterrupt:
        pass
    print(f"\nStopped watching. {done} video(s) processed.")


def run_batch(items, cfg, model, online, report_dir: Path):
    """Process many videos one after another; one failure never stops the rest."""
    import traceback
    cfg = dict(cfg, clip=None)      # a clip range only makes sense for a single video
    started = time.time()
    results = []
    keep_awake(True)
    try:
        for i, it in enumerate(items, 1):
            print("\n" + "#" * 70)
            print(f"#  [{i}/{len(items)}]  {it['path'].name}")
            print("#" * 70)
            t0 = time.time()
            try:
                files = process_video(it["path"], cfg, model, online, kind=it["kind"],
                                      source=it.get("source"), open_result=False)
                results.append((it["path"], "OK", time.time() - t0, len(files)))
            except KeyboardInterrupt:
                print("\n[!] Stopped by you (Ctrl+C).")
                results.append((it["path"], "STOPPED", time.time() - t0, 0))
                break
            except Exception as e:
                traceback.print_exc()
                print(f"[!] Failed: {it['path'].name}: {e}  - moving on to the next one.")
                results.append((it["path"], f"FAILED: {e}", time.time() - t0, 0))
    finally:
        keep_awake(False)

    ok = sum(1 for r in results if r[1] == "OK")
    lines = [f"Batch report - {datetime.datetime.now():%d %b %Y %H:%M}",
             f"Done: {ok} of {len(items)}   |   Total time: {fmt(time.time() - started)}", ""]
    for path, status, secs, n in results:
        lines.append(f"[{status if status == 'OK' else status[:80]}]  {fmt(secs)}  {path}")
    for it in items[len(results):]:
        lines.append(f"[NOT STARTED]  {it['path']}")
    report = report_dir / f"batch_report_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt"
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        report = None
    print("\n" + "=" * 70)
    print("\n".join(lines))
    print("=" * 70)
    if report:
        print(f"Report saved: {report}")
        open_path(report)


# ---------------------------------------------------------------- voice cleanup tab
def build_voice_cleanup_tab(parent_frame, online_var):
    """Dedicated Voice Cleanup module, shared by every feature (live capture, file,
    folder, URL, watch). Changes save immediately - this is a standing settings surface,
    not part of a Start flow. The Online/Offline toggle only changes its DEFAULT choice;
    every option always stays selectable regardless of toggle position."""
    import tkinter as tk
    from tkinter import ttk

    WHITE, MUTED = "#ffffff", "#5f6368"
    FONT = "Segoe UI"
    root = parent_frame
    root.configure(bg=WHITE)
    saved = load_settings()

    tk.Label(root, text="Voice cleanup (noise removal + voice isolation)", bg=WHITE,
             font=(FONT, 12, "bold")).pack(anchor="w", padx=16, pady=(12, 4))
    tk.Label(root, text="Used automatically by every feature - live capture, file, folder, URL, watch.",
             bg=WHITE, fg=MUTED, font=(FONT, 9)).pack(anchor="w", padx=16)

    nrow = tk.Frame(root, bg=WHITE)
    nrow.pack(fill="x", padx=12, pady=(10, 0))
    tk.Label(nrow, text="Mode:", bg=WHITE, font=(FONT, 10, "bold")).pack(side="left")
    saved_noise = {"ai": "studio"}.get(saved.get("noise", "off"), saved.get("noise", "off"))
    noise_var = tk.StringVar(value=dict((v, l) for l, v in NOISE_CHOICES).get(saved_noise, "Off"))
    noise_box = ttk.Combobox(nrow, textvariable=noise_var, values=[l for l, _ in NOISE_CHOICES],
                             state="readonly", width=22)
    noise_box.pack(side="left", padx=6)
    keep_var = tk.BooleanVar(value=saved.get("keep_clean", False))
    tk.Checkbutton(nrow, text="also save the cleaned voice (to listen to)", variable=keep_var, bg=WHITE,
                   activebackground=WHITE, font=(FONT, 9), bd=0, highlightthickness=0).pack(side="left", padx=6)
    key_btn = tk.Button(nrow, font=(FONT, 9), relief="flat", bg="#e8f0fe", padx=10,
                        command=lambda: ask_key())
    noise_help = tk.Label(root, bg=WHITE, fg=MUTED, font=(FONT, 9), anchor="w", justify="left", wraplength=860)
    noise_help.pack(fill="x", padx=16, pady=(4, 0))

    def persist():
        s = load_settings()
        s["noise"] = dict(NOISE_CHOICES)[noise_var.get()]
        s["keep_clean"] = bool(keep_var.get())
        save_settings(s)

    def key_text():
        key_btn.configure(text="ElevenLabs key saved - change" if elevenlabs_key() else "Enter ElevenLabs API key")

    def ask_key():
        from tkinter import simpledialog
        k = simpledialog.askstring(
            "ElevenLabs API key",
            "Paste your ElevenLabs API key\n(elevenlabs.io > Developers > API keys).\n"
            "It is saved only on this PC, in the settings file.", show="*", parent=ROOT)
        if k and k.strip():
            s = load_settings()
            s["elevenlabs_key"] = k.strip()
            save_settings(s)
        key_text()

    def on_noise(*_):
        v = dict(NOISE_CHOICES)[noise_var.get()]
        noise_help.configure(text=NOISE_HELP[v])
        if v == "online":
            key_text()
            key_btn.pack(side="right")
            if not elevenlabs_key():
                root.after(100, ask_key)
        else:
            key_btn.pack_forget()
        persist()

    def default_by_online(*_):
        target = "online" if online_var.get() else "studio"
        noise_var.set(dict((v, l) for l, v in NOISE_CHOICES).get(target, noise_var.get()))
        on_noise()

    noise_box.bind("<<ComboboxSelected>>", on_noise)
    keep_var.trace_add("write", lambda *_: persist())
    online_var.trace_add("write", default_by_online)
    on_noise()


# ---------------------------------------------------------------- offline settings tab
def build_offline_settings_tab(parent_frame, online_var):
    """Pick which installed Ollama / LM Studio model is used for summaries and
    translations (both already route through the same picked model)."""
    import tkinter as tk
    from tkinter import ttk

    WHITE, MUTED = "#ffffff", "#5f6368"
    FONT = "Segoe UI"
    root = parent_frame
    root.configure(bg=WHITE)
    saved = load_settings()
    AUTO = "(auto - first available)"

    tk.Label(root, text="Offline settings", bg=WHITE, font=(FONT, 12, "bold")).pack(
        anchor="w", padx=16, pady=(12, 4))
    tk.Label(root, text="Choose which installed model Ollama / LM Studio uses for summaries and "
                        "translations. Leave on \"" + AUTO + "\" to use whichever model comes "
                        "first in each app's own list.", bg=WHITE, fg=MUTED, font=(FONT, 9),
             wraplength=860, justify="left").pack(anchor="w", padx=16)

    def section(title, list_fn, setting_key, not_running_hint):
        head = tk.Frame(root, bg=WHITE)
        head.pack(fill="x", padx=12, pady=(14, 0))
        tk.Label(head, text=title, bg=WHITE, font=(FONT, 10, "bold")).pack(side="left")
        status_lbl = tk.Label(head, bg=WHITE, fg=MUTED, font=(FONT, 9))
        status_lbl.pack(side="left", padx=8)

        prow = tk.Frame(root, bg=WHITE)
        prow.pack(fill="x", padx=12, pady=(2, 0))
        var = tk.StringVar(value=saved.get(setting_key) or AUTO)
        box = ttk.Combobox(prow, textvariable=var, state="readonly", width=36)
        box.pack(side="left")
        refresh_btn = tk.Button(prow, text="Refresh list", font=(FONT, 9), relief="flat",
                                bg="#e8f0fe", padx=10)
        refresh_btn.pack(side="left", padx=6)

        def refresh(*_):
            try:
                names = list_fn()
                status_lbl.configure(text=(f"{len(names)} model(s) found." if names
                                           else not_running_hint), fg=(MUTED if names else "#c5221f"))
            except Exception:
                names = []
                status_lbl.configure(text=not_running_hint, fg="#c5221f")
            box.configure(values=[AUTO] + names)
            if var.get() not in ([AUTO] + names):
                var.set(AUTO)

        def persist(*_):
            s = load_settings()
            s[setting_key] = "" if var.get() == AUTO else var.get()
            save_settings(s)

        box.bind("<<ComboboxSelected>>", persist)
        refresh_btn.configure(command=refresh)
        refresh()

    section("Ollama", list_ollama_models, "ollama_model", "Ollama not running - start it first.")
    section("LM Studio", list_lmstudio_models, "lmstudio_model",
            "LM Studio server not running - open LM Studio > Developer tab > Start server.")


# ---------------------------------------------------------------- history tab (on demand)
def open_history_tab():
    existing = APP_STATE.get("history_frame")
    if existing is not None and existing.winfo_exists():
        NOTEBOOK.select(existing)
        return
    frame = open_feature_tab("History", open_history)
    APP_STATE["history_frame"] = frame


# ---------------------------------------------------------------- feature dispatch
def _run_url_job(cfg, model, online):
    """URL mode: download via yt-dlp, then process like a file/folder job."""
    items = [{"path": p, "kind": "url", "source": page} for p, _, page in download_url(cfg["url"])]
    if not items:
        return
    print(f"  Saved in: {SAVE_DIR / 'Downloads'}")
    if len(items) == 1:
        keep_awake(True)
        try:
            process_video(items[0]["path"], cfg, model, online, kind=items[0]["kind"],
                          source=items[0].get("source"), open_result=True)
        finally:
            keep_awake(False)
    else:
        run_batch(items, cfg, model, online, SAVE_DIR)


def launch_feature(res, online_var):
    """Home's Start button: open the chosen feature as a NEW tab. Home stays as it was."""
    from tkinter import messagebox
    online = online_var.get()
    mode = res.get("mode", "file")
    s = load_settings()               # Voice Cleanup tab is the source of truth for these
    res["noise"] = s.get("noise", "off")
    res["keep_clean"] = s.get("keep_clean", False)

    global VOCAB
    VOCAB = load_vocab()

    if mode in ("mic", "system", "call"):
        label = {"mic": "Live Mic", "system": "Live System Audio", "call": "Live Call"}[mode]
        open_feature_tab(label, run_mic, res, online, source=mode)
        return

    if mode == "watch":
        folder = pick_folder()
        if not folder:
            return
        model = load_whisper(res["model"])
        open_log_tab(f"Watch: {Path(folder).name}", run_watch, Path(folder), res, model, online,
                     stoppable=True, stop_event=threading.Event())
        return

    if mode == "file":
        video = pick_video()
        if not video:
            return
        model = load_whisper(res["model"])
        open_log_tab(f"File: {Path(video).name}", process_video, Path(video), res, model, online,
                     kind="file", source=None, open_result=True)
        return

    if mode == "folder":
        folder = pick_folder()
        if not folder:
            return
        report_dir = Path(folder)
        vids = list_videos(report_dir, res.get("subfolders", False))
        skipped = [v for v in vids if res.get("skip_done", True) and already_done(v)]
        todo = [v for v in vids if v not in skipped]
        if not todo:
            messagebox.showinfo("Folder", f"{len(vids)} file(s) found - all {len(skipped)} already done.",
                                parent=ROOT)
            return
        items = [{"path": v, "kind": "file"} for v in todo]
        model = load_whisper(res["model"])
        open_log_tab(f"Folder: {report_dir.name}", run_batch, items, res, model, online, report_dir)
        return

    if mode == "url":
        if not online:
            messagebox.showwarning("Offline", "Downloading a link needs internet.", parent=ROOT)
            return
        model = load_whisper(res["model"])
        open_log_tab("URL", _run_url_job, res, model, online)
        return


# ---------------------------------------------------------------- main
def main():
    global ROOT, NOTEBOOK
    import tkinter as tk
    from tkinter import ttk

    online0 = internet_ok()
    saved = load_settings()

    ROOT = tk.Tk()
    ROOT.title("Cursed_Vishleshan")
    ROOT.geometry("980x760")
    ROOT.minsize(800, 600)

    toolbar = tk.Frame(ROOT, bg="#f1f3f4")
    toolbar.pack(fill="x", side="top")
    online_var = tk.BooleanVar(value=saved.get("mode_online", online0))
    APP_STATE["online_var"] = online_var
    tk.Checkbutton(toolbar, text="Online", variable=online_var, bg="#f1f3f4",
                   activebackground="#f1f3f4", font=("Segoe UI", 10, "bold")).pack(
        side="left", padx=8, pady=4)
    net_lbl = tk.Label(toolbar, text=("Internet: connected" if online0 else "Internet: offline"),
                       bg="#f1f3f4", fg=("#1e8e3e" if online0 else "#c5221f"), font=("Segoe UI", 9))
    net_lbl.pack(side="left", padx=6)

    if not online0:   # REAL connectivity, not the tool-preference toggle above
        os.environ["HF_HUB_OFFLINE"] = "1"   # use cached models, don't try to download

    def _persist_online(*_):
        s = load_settings()
        s["mode_online"] = bool(online_var.get())
        save_settings(s)
    online_var.trace_add("write", _persist_online)
    _persist_online()

    NOTEBOOK = ttk.Notebook(ROOT)
    NOTEBOOK.pack(fill="both", expand=True)

    home_frame = tk.Frame(NOTEBOOK, bg="#ffffff")
    NOTEBOOK.add(home_frame, text="Home")
    build_home_tab(home_frame, online0, lambda res: launch_feature(res, online_var))

    vc_frame = tk.Frame(NOTEBOOK, bg="#ffffff")
    NOTEBOOK.add(vc_frame, text="Voice Cleanup")
    build_voice_cleanup_tab(vc_frame, online_var)

    off_frame = tk.Frame(NOTEBOOK, bg="#ffffff")
    NOTEBOOK.add(off_frame, text="Offline Settings")
    build_offline_settings_tab(off_frame, online_var)

    ROOT.protocol("WM_DELETE_WINDOW", on_app_close)
    ROOT.mainloop()


if __name__ == "__main__":
    main()
