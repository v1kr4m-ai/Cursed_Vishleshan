"""
Cursed_Vishleshan
-----------------
Processing backend (no GUI) - the interface lives in app.py + web/. Run `python app.py`.
Choose model + languages + what to process -> get:
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
import textwrap
import threading
import subprocess
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
NOISE_CHOICES = [("Off", "off"), ("Light filter (Offline)", "light"),
                 ("Strong filter (Offline)", "strong"),
                 ("Studio AI - Demucs + DeepFilterNet (Offline)", "studio"),
                 ("ElevenLabs Voice Isolator (Online)", "online")]
NOISE_HELP = {
    "off": "No cleanup.",
    "light": "Light filter (Offline): ffmpeg only, quick, gentle hiss/hum reduction.",
    "strong": "Strong filter (Offline): ffmpeg only, quick, heavy noise reduction (can dull quiet voices).",
    "studio": "Studio AI (Offline): Demucs isolates the voices from music/crowd/background, then "
              "DeepFilterNet removes noise. Slow on CPU (about real time), much faster with an NVIDIA GPU. "
              "Falls back to the Strong filter for whichever step's model isn't installed.",
    "online": "ElevenLabs Voice Isolator (Online): excellent on very noisy audio. Needs an API key, "
              "uses credits, and the audio is uploaded to ElevenLabs.",
}
NOISE_FILTERS = {
    # measured on noisy test audio: Light ~ +5-8 dB cleaner, Strong ~ +30-40 dB (speech level kept)
    "light": "highpass=f=80,lowpass=f=7600,afftdn=nr=12:nf=-30:tn=1",
    "strong": "highpass=f=100,lowpass=f=7000,afftdn=nr=25:nf=-20:tn=1,afftdn=nr=15:nf=-30",
}
# Speech speed: Whisper struggles with very fast speech (rap, songs). Slowing the audio down
# (pitch kept) before recognition helps. _SPEED is set per job in process_video; all timestamps
# from the slowed audio are multiplied back by it so they match the original recording.
SPEED_CHOICES = [("Normal", 1.0), ("Slightly slower (85%)", 0.85), ("Slower (75%)", 0.75),
                 ("Much slower (65%)", 0.65), ("Half speed (50%)", 0.5)]
_SPEED = 1.0


def _with_tempo(af, speed):
    return ",".join(x for x in (af, f"atempo={speed}" if speed < 1.0 else "") if x)


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
    """Separate the voices from everything else with Demucs (offline AI). Returns out or None.
    Mono - this feeds Whisper, which doesn't need stereo."""
    return _demucs_run(src44, out, keep="vocals", mono=True, what="voices")


def demucs_isolate_music(src44: Path, out: Path):
    """Separate the background music/instrumental from the voices with Demucs (offline AI).
    Returns out or None. Stereo - this is meant to be listened to."""
    return _demucs_run(src44, out, keep="music", mono=False, what="background music")


STEM_CHOICES = [("instrumental", "Instrumental (everything but the voice)"), ("vocals", "Vocals"),
                ("drums", "Drums"), ("bass", "Bass"), ("other", "Other (guitars, keys, synths...)")]


def demucs_stems(src44: Path, outdir: Path, stems, _retry=True):
    """Separate a song into the wanted stems in ONE pass. stems: any of vocals, drums, bass, other,
    instrumental (= everything but vocals). Writes outdir/<stem>.wav (stereo) and returns {stem: path}."""
    try:
        import numpy as np
        import torch
        from demucs.pretrained import get_model
        from demucs.apply import apply_model
    except ImportError:
        print("  [i] Separating stems needs:  pip install demucs")
        return {}
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    name = DEMUCS_MODEL if DEMUCS_MODEL != "auto" else ("htdemucs_ft" if dev == "cuda" else "htdemucs")
    print(f"  Separating stems with Demucs ({name}, {'GPU' if dev == 'cuda' else 'CPU'}) - "
          f"the model downloads only the first time, then is reused...")
    outs = {s: Path(outdir) / f"{s}.wav" for s in stems}
    writers = {}
    try:
        model = get_model(name)
        model.eval()
        index = {s: model.sources.index(s) for s in stems if s in model.sources}
        with wave.open(str(src44), "rb") as r:
            sr, ch, n = r.getframerate(), r.getnchannels(), r.getnframes()
            for s, path in outs.items():
                w = writers[s] = wave.open(str(path), "wb")
                w.setnchannels(2)
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
                m, sd = ref.mean(), ref.std() + 1e-8
                with torch.no_grad():
                    y = apply_model(model, ((x - m) / sd)[None], device=dev, split=True,
                                    overlap=0.25, progress=False)[0]
                sl = slice(start - a, start - a + min(step, n - start))
                for s, w in writers.items():
                    chosen = (y.sum(0) - y[model.sources.index("vocals")]) if s == "instrumental" else y[index[s]]
                    piece = (chosen * sd + m).cpu().numpy()[:, sl].T.reshape(-1)
                    w.writeframes((np.clip(piece, -1, 1) * 32767).astype(np.int16).tobytes())
                done = min(start + step, n) / n
                el = time.time() - t0
                print(f"\r    {done:4.0%}  (about {fmt(el / done - el)} left)", end="", flush=True)
        print()
        return outs
    except Exception as e:
        if dev == "cuda" and _retry and "cudnn" in str(e).lower():
            print("\n  [i] cuDNN version clash - retrying on the GPU without cuDNN...")
            torch.backends.cudnn.enabled = False
            for w in writers.values():
                w.close()
            return demucs_stems(src44, outdir, stems, _retry=False)
        print(f"\n  [!] Separating stems failed ({str(e)[:150]}).")
        return {}
    finally:
        for w in writers.values():
            try:
                w.close()
            except Exception:
                pass


def _demucs_run(src44: Path, out: Path, keep: str, mono: bool, what: str, _retry=True):
    try:
        import numpy as np
        import torch
        from demucs.pretrained import get_model
        from demucs.apply import apply_model
    except ImportError:
        print(f"  [i] Isolating {what} needs:  pip install demucs   - skipping this step.")
        return None
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    name = DEMUCS_MODEL if DEMUCS_MODEL != "auto" else ("htdemucs_ft" if dev == "cuda" else "htdemucs")
    print(f"  Isolating {what} with Demucs ({name}, {'GPU' if dev == 'cuda' else 'CPU'}) - "
          f"the model downloads only the first time, then is reused...")
    try:
        model = get_model(name)
        model.eval()
        vi = model.sources.index("vocals")
        with wave.open(str(src44), "rb") as r, wave.open(str(out), "wb") as w:
            sr, ch, n = r.getframerate(), r.getnchannels(), r.getnframes()
            w.setnchannels(1 if mono else 2)
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
                chosen = y[vi] if keep == "vocals" else (y.sum(0) - y[vi])   # (channels, time)
                piece = (chosen * s + m).cpu().numpy()
                sl = slice(start - a, start - a + min(step, n - start))
                piece = piece.mean(0)[sl] if mono else piece[:, sl].T.reshape(-1)
                w.writeframes((np.clip(piece, -1, 1) * 32767).astype(np.int16).tobytes())
                done = min(start + step, n) / n
                el = time.time() - t0
                print(f"\r    {done:4.0%}  (about {fmt(el / done - el)} left)", end="", flush=True)
        print()
        return out
    except Exception as e:
        if dev == "cuda" and _retry and "cudnn" in str(e).lower():
            # Whisper's CUDA-12 cuDNN DLLs (see _add_nvidia_dlls) can shadow the cuDNN that
            # PyTorch's own CUDA build ships. Run the same GPU work without cuDNN instead.
            print("\n  [i] cuDNN version clash - retrying on the GPU without cuDNN...")
            torch.backends.cudnn.enabled = False
            return _demucs_run(src44, out, keep, mono, what, _retry=False)
        print(f"\n  [!] Isolating {what} failed ({str(e)[:150]}) - continuing without it.")
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


def _dpapi_protect(data: bytes) -> bytes:
    """Encrypt bytes so only this Windows user account can decrypt them again (DPAPI)."""
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    in_blob = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out_blob = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    in_blob = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out_blob = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def save_elevenlabs_key(key: str):
    """Store the key DPAPI-encrypted (tied to this Windows account), not plaintext."""
    s = load_settings()
    try:
        s["elevenlabs_key_enc"] = base64.b64encode(_dpapi_protect(key.encode("utf-8"))).decode("ascii")
        s.pop("elevenlabs_key", None)
    except Exception:
        s["elevenlabs_key"] = key   # DPAPI unavailable - fall back to plaintext rather than lose it
    save_settings(s)


def elevenlabs_key():
    env = os.environ.get("ELEVENLABS_API_KEY")
    if env:
        return env
    s = load_settings()
    enc = s.get("elevenlabs_key_enc")
    if enc:
        try:
            return _dpapi_unprotect(base64.b64decode(enc)).decode("utf-8")
        except Exception:
            return ""
    legacy = s.get("elevenlabs_key", "")
    if legacy:
        save_elevenlabs_key(legacy)   # one-time migration off plaintext
    return legacy


def prepare_audio(video, clip, noise, tmpdir, online=False, speed=None, out_sr=None):
    """Cut the clip range and/or clean up the voice into a temporary WAV for Whisper.
    Returns (path_for_whisper, start_offset_seconds)."""
    noise = {"ai": "studio"}.get(noise, noise or "off")
    start = float(clip[0] or 0) if clip else 0.0
    end = clip[1] if clip else None
    speed = _SPEED if speed is None else speed
    if not clip and noise == "off" and speed >= 1.0:
        return str(video), 0.0
    if not shutil.which("ffmpeg"):
        print("[!] ffmpeg not found - clip range / voice cleanup skipped.")
        return str(video), 0.0
    tmp = Path(tmpdir)
    what = []
    if clip:
        what.append(f"part {fmt(start)} - {fmt(end) if end else 'end'}")
    if speed < 1.0:
        what.append(f"slowed to {speed:.0%} speed")
    if noise != "off":
        what.append("voice cleanup: " + dict((v, k) for k, v in NOISE_CHOICES)[noise])
    print("Preparing audio (" + ", ".join(what) + ")...")
    cut = (["-ss", f"{start:.3f}"] if start else []) + ["-i", str(video), "-vn"] + \
          (["-t", f"{max(end - start, 0.1):.3f}"] if end else [])
    t0 = time.time()

    if noise in ("off", "light", "strong"):
        out = tmp / "audio.wav"
        af = _with_tempo(NOISE_FILTERS.get(noise, ""), speed)
        _ff(*cut, "-ac", 1, "-ar", out_sr or SR, *(["-af", af] if af else []), out)
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
    _ff("-i", voice, "-ac", 1, "-ar", out_sr or SR, "-af", _with_tempo(FINAL_LEVEL, speed), out)
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


# ---------------------------------------------------------------- job runner
# ponytail: one job at a time app-wide (matches the old fully-sequential app); move to
# per-job contextvars-based stdout capture if concurrent file/folder/url/watch jobs are wanted.
PROCESSING_LOCK = threading.Lock()


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
            results.append((s / SR * _SPEED, code, prob))
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


def decode_kwargs(model, noisy, raw=False):
    """Whisper settings. 'noisy' = safer decoding for rough audio (fewer made-up words).
    raw = the exact-transcript settings: nothing is skipped (no voice-activity cut, no
    silence/confidence cut-offs) and no custom-vocabulary nudging, so Whisper writes what it hears."""
    k = {"vad_filter": True, "beam_size": 5}
    if raw:
        k = {"vad_filter": False, "beam_size": 5, "no_speech_threshold": None, "log_prob_threshold": None}
    elif noisy:
        k.update(best_of=5, condition_on_previous_text=False,   # stops runaway repeated lines
                 no_speech_threshold=0.6, compression_ratio_threshold=2.2, log_prob_threshold=-1.0,
                 vad_parameters={"threshold": 0.4, "min_silence_duration_ms": 600, "speech_pad_ms": 400})
    if not raw:
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


# ---------------------------------------------------------------- speaker labels (diarization)
# Offline: sherpa-onnx runs a small speaker-segmentation model + a speaker-embedding model on the CPU.
# The two models (about 46 MB) are downloaded once into Documents/Cursed_Vishleshan/models/diarization.
SPEAKER_CHOICES = [("Off", "off"), ("Auto-detect", "auto"), ("2 speakers", "2"), ("3 speakers", "3"),
                   ("4 speakers", "4"), ("5 speakers", "5"), ("6 speakers", "6")]
_DIAR_BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
_DIAR_SEG_URL = _DIAR_BASE + "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
_DIAR_EMB_URL = (_DIAR_BASE + "speaker-recongition-models/"
                 "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx")


def diarization_ready():
    d = SAVE_DIR / "models" / "diarization"
    return (d / "segmentation.onnx").exists() and (d / "embedding.onnx").exists()


def _fetch(url, dest):
    print(f"  Downloading {dest.name} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "video-summarizer"})
    with urllib.request.urlopen(req, timeout=60) as r, open(str(dest) + ".part", "wb") as f:
        shutil.copyfileobj(r, f)
    os.replace(str(dest) + ".part", dest)


def ensure_diarization_models(online):
    d = SAVE_DIR / "models" / "diarization"
    seg, emb = d / "segmentation.onnx", d / "embedding.onnx"
    if seg.exists() and emb.exists():
        return seg, emb
    if not online:
        print("  [!] Speaker labels need a one-time download of two small models (about 46 MB) - "
              "connect to the internet once.")
        return None
    try:
        import tarfile
        d.mkdir(parents=True, exist_ok=True)
        if not seg.exists():
            tar = d / "seg.tar.bz2"
            _fetch(_DIAR_SEG_URL, tar)
            with tarfile.open(tar) as t:
                member = next(m for m in t.getmembers() if m.name.endswith("model.onnx"))
                with t.extractfile(member) as src, open(seg, "wb") as out:
                    shutil.copyfileobj(src, out)
            tar.unlink()
        if not emb.exists():
            _fetch(_DIAR_EMB_URL, emb)
        return seg, emb
    except Exception as e:
        print(f"  [!] Could not download the speaker models: {str(e)[:150]}")
        return None


def diarize(audio_path, speakers, online):
    """Who spoke when. Returns [(start_sec, end_sec, speaker_number)] in the audio's own time
    (speaker numbers start at 1, in order of first appearance), or [] if unavailable / one speaker."""
    if speakers in (None, "", "off"):
        return []
    try:
        import sherpa_onnx
    except ImportError:
        print("  [!] Speaker labels need one more library. Run:  pip install sherpa-onnx")
        return []
    models = ensure_diarization_models(online)
    if not models:
        return []
    print("Finding who speaks when...")
    try:
        from faster_whisper.audio import decode_audio
        n = int(speakers) if str(speakers).isdigit() else -1
        cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(models[0])),
                num_threads=4),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(models[1]), num_threads=4),
            clustering=sherpa_onnx.FastClusteringConfig(num_clusters=n, threshold=0.5),
            min_duration_on=0.3, min_duration_off=0.5)
        sd = sherpa_onnx.OfflineSpeakerDiarization(cfg)
        audio = decode_audio(str(audio_path), sampling_rate=sd.sample_rate)
        result = sd.process(audio).sort_by_start_time()
    except Exception as e:
        print(f"  [!] Speaker detection failed: {str(e)[:150]}")
        return []
    order, out = {}, []
    for r in result:
        order.setdefault(r.speaker, len(order) + 1)
        out.append((r.start, r.end, order[r.speaker]))
    if len(order) < 2:
        print("  Only one speaker found - no labels added.")
        return []
    print(f"  {len(order)} speakers found.")
    return out


def speaker_at(diar, t0, t1):
    """The speaker whose turns overlap [t0, t1] the most (None if nobody does)."""
    best, score = None, 0.0
    tot = {}
    for a, b, spk in diar:
        ov = min(b, t1) - max(a, t0)
        if ov > 0:
            tot[spk] = tot.get(spk, 0.0) + ov
    for spk, ov in tot.items():
        if ov > score:
            best, score = spk, ov
    return best


def _scaled_info(info):
    """Whisper info for slowed audio, with the duration put back to original-recording time."""
    if _SPEED >= 1.0:
        return info
    import types
    return types.SimpleNamespace(duration=info.duration * _SPEED, language=info.language,
                                 language_probability=info.language_probability)


def transcribe(model, video, language, multilingual=False, detections=None, offset=0.0, noisy=False, diar=None,
               words=False):
    """offset = where the audio starts inside the full video (clip range), added to timestamps."""
    kwargs = {"language": language, "task": "transcribe"}
    if multilingual and "multilingual" in inspect.signature(model.transcribe).parameters:
        kwargs["multilingual"] = True
    kwargs.update(decode_kwargs(model, noisy, raw=True))
    if words:
        kwargs["word_timestamps"] = True
    segments, info = model.transcribe(video, **kwargs)
    info = _scaled_info(info)
    print(f"Duration: {fmt(info.duration)}")
    print("Transcribing...")

    det_times = [d[0] for d in detections] if detections else []
    stamped, plain, prev, guard, dropped, marked = [], [], None, LoopGuard(), 0, 0
    raw_stamped, raw_plain, rprev = [], [], None   # the exact transcript: every line, untouched
    raw_segs = []                                   # (start, end, text) in original-recording time, for subtitles
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        rt, rcode = seg.start * _SPEED + offset, None
        if detections:
            rcode = detections[max(0, sum(1 for d in det_times if d <= rt) - 1)][1]
        rpre = f"({lang_name(rcode)}) " if rcode and rcode != rprev else ""
        rprev = rcode or rprev
        spk = speaker_at(diar, rt, seg.end * _SPEED + offset) if diar else None
        if spk:
            text = f"Speaker {spk}: {text}"
        raw_stamped.append(f"[{fmt(rt)}] {rpre}{text}")
        raw_plain.append(text)
        wl = [(w.start * _SPEED + offset, w.end * _SPEED + offset, w.word.strip(), getattr(w, "probability", 1.0))
              for w in (getattr(seg, "words", None) or []) if w.word.strip()] if words else None
        raw_segs.append((rt, seg.end * _SPEED + offset, text, wl))
        if is_hallucination(text, seg) or guard.repeat(text):
            dropped += 1
            continue
        if unclear(seg):
            text += " [unclear]"
            marked += 1
        t = seg.start * _SPEED + offset
        prefix = ""
        if detections:  # mixed-language video: mark where the language changes
            idx = max(0, sum(1 for d in det_times if d <= t) - 1)
            code = detections[idx][1]
            if code != prev:
                prefix = f"({lang_name(code)}) "
                prev = code
        stamped.append(f"[{fmt(t)}] {prefix}{text}")
        plain.append(text)
        print(f"\r  {fmt(seg.end * _SPEED)} / {fmt(info.duration)}", end="", flush=True)
    print()
    if dropped:
        print(f"  Filtered copy: {dropped} made-up / repeated line(s) removed (the exact transcript keeps them).")
    if marked:
        print(f"  Filtered copy: {marked} line(s) marked [unclear].")
    return raw_stamped, " ".join(raw_plain), info, stamped, dropped, marked, raw_segs


def whisper_translate_english(model, video, language, offset=0.0, noisy=False):
    print("Translating to English with Whisper...")
    segments, info = model.transcribe(video, language=language, task="translate",
                                      **decode_kwargs(model, noisy))
    lines, guard = [], LoopGuard()
    for seg in segments:
        if seg.text.strip() and not is_hallucination(seg.text, seg) and not guard.repeat(seg.text):
            lines.append(f"[{fmt(seg.start * _SPEED + offset)}] {seg.text.strip()}")
            print(f"\r  {fmt(seg.end * _SPEED)} / {fmt(info.duration * _SPEED)}", end="", flush=True)
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
    subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
                    f"output line per input line, drop the (Language) markers, keep any \"Speaker N:\" labels exactly as written, and output ONLY "
                    f"the translated lines - no notes or explanations.{vocab_note()}\n\n{ch}"))
            print()
            return "\n".join(o.strip() for o in out), label
        except Exception as e:
            print(f"\n  [{label}] Translation failed: {e}")
    return None, None


# ---------------------------------------------------------------- chapters + key points
_CH_RE = re.compile(r"^\W*(CHAPTER|POINT)\W*\|\W*\[?(\d{1,2}):(\d\d):?(\d\d)?\]?\W*\|\s*(.+?)\s*$", re.I)


def _hms(h, m, s):
    return int(h) * 3600 + int(m) * 60 + int(s or 0)


def make_chapters(body, duration, target, online, min_gap=None):
    """Chapters and timestamped key points from a '[HH:MM:SS] text' transcript, written in `target`
    language. Returns (markdown, backend_label) or (None, None)."""
    if not body.strip():
        return None, None
    if min_gap is None:
        min_gap = 60 if duration > 600 else 20   # short clips get closer chapters
    chunks = split_chunks(body, CHUNK_CHARS)
    system = "You analyse video transcripts and structure them precisely. Follow the output format exactly."
    for label, fn in text_llms(online):
        try:
            chapters, points = [], []
            for i, ch in enumerate(chunks, 1):
                print(f"\r  Finding chapters ({label}): part {i}/{len(chunks)}", end="", flush=True)
                reply = fn(system,
                           f"This is part {i} of {len(chunks)} of a timestamped transcript.\n"
                           f"1. List the chapters that START in this part: one for each distinct topic or change of subject (even a short video can have 2-3), "
                           f"roughly one every 2-5 minutes, at least one per part.\n"
                           f"2. List 2-5 key points (important facts, decisions, claims or moments).\n"
                           f"Output ONLY lines in exactly this format, with the timestamp copied from a transcript line:\n"
                           f"CHAPTER|HH:MM:SS|short chapter title (max 8 words)\n"
                           f"POINT|HH:MM:SS|one-sentence key point\n"
                           f"Write titles and points in {target}.{vocab_note()}\n\n{ch}")
                for line in reply.splitlines():
                    m = _CH_RE.match(line)
                    if m:
                        (chapters if m.group(1).upper() == "CHAPTER" else points).append(
                            (_hms(m.group(2), m.group(3), m.group(4)), m.group(5)))
            print()
            if not chapters:
                continue
            chapters.sort()
            kept = []
            for t, title in chapters:
                if not kept or t - kept[-1][0] >= min_gap:
                    kept.append((t, title))
            if kept[0][0] > 0:
                kept.insert(0, (0, "Intro"))
            kept[0] = (0, kept[0][1])
            points.sort()
            nl = chr(10)
            out = ["## Chapters", ""] + [f"{fmt(t)} {title}" for t, title in kept] + ["", "## Key points", ""]
            for k, (t, title) in enumerate(kept):
                end = kept[k + 1][0] if k + 1 < len(kept) else duration + 1
                inside = [(pt, tx) for pt, tx in points if t <= pt < end]
                out.append(f"### {fmt(t)} {title}")
                out += [f"- {fmt(pt)} {tx}" for pt, tx in inside] or ["- (no key points)"]
                out.append("")
            return nl.join(out), label
        except Exception as e:
            print(f"\n  [{label}] Chapters failed: {e}")
    return None, None


# ---------------------------------------------------------------- live capture helpers
def stamped_from_entries(entries):
    lines, prev = [], None
    for e in sorted(entries, key=lambda x: x["t"]):
        tag = f"({lang_name(e['lang'])}) " if e["lang"] != prev else ""
        prev = e["lang"]
        who = f"{e['who']}: " if e.get("who") else ""
        lines.append(f"[{fmt(e['t'])}] {tag}{who}{e['text']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- output files
# ---------------------------------------------------------------- subtitles (.srt / .vtt)
def _sub_time(t, comma):
    ms = int(round(max(t, 0) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{',' if comma else '.'}{ms:03d}"


def _sub_text(text, width=42):
    """Wrap to at most two balanced-ish lines of ~width characters, the usual subtitle shape."""
    lines = textwrap.wrap(text, width=width) or [text]
    if len(lines) > 2:
        lines = textwrap.wrap(text, width=max(width, -(-len(text) // 2) + 6))[:2] or lines[:2]
    return chr(10).join(lines)


def _split_cue(a, b, text, words, max_chars=84, max_sec=7.0):
    """A long segment becomes several cues, split at the pauses between words (needs word timings)."""
    if not words or (len(text) <= max_chars and b - a <= max_sec):
        return [(a, b, text)]
    label = ""
    m = re.match(r"^(Speaker \d+: )", text)
    if m:
        label = m.group(1)
    out, cur, start = [], [], words[0][0]
    for i, (ws, we, w, _p) in enumerate(words):
        cur.append(w)
        gap = (words[i + 1][0] - we) if i + 1 < len(words) else 9.0
        line = " ".join(cur)
        full = len(line) >= max_chars * 0.6 or we - start >= max_sec * 0.6
        if (gap >= 0.45 and len(line) >= 20) or len(line) >= max_chars or we - start >= max_sec or \
                (full and w.endswith((".", "?", "!", ","))):
            out.append((start, we, (label if not out else "") + line))
            cur, start = [], words[i + 1][0] if i + 1 < len(words) else we
    if cur:
        out.append((start, words[-1][1], (label if not out else "") + " ".join(cur)))
    return out or [(a, b, text)]


def write_words_csv(path, segs):
    """Every word with its start/end time, confidence and speaker (when known)."""
    rows = ["start,end,word,confidence,speaker"]
    for seg in segs:
        words = seg[3] if len(seg) > 3 else None
        if not words:
            continue
        m = re.match(r"^Speaker (\d+): ", seg[2])
        who = f"Speaker {m.group(1)}" if m else ""
        for ws, we, w, p in words:
            rows.append(f"{ws:.2f},{we:.2f},\"{w.replace(chr(34), chr(34) * 2)}\",{p:.2f},{who}")
    if len(rows) > 1:
        Path(path).write_text(chr(10).join(rows) + chr(10), encoding="utf-8-sig")
        return Path(path)
    return None


def write_subtitles(base_path, segs, fmts):
    """segs = [(start, end, text)]. Writes base_path.srt and/or .vtt per `fmts` (e.g. 'srt', 'vtt', 'both').
    Returns the files written."""
    if not segs or fmts in (None, "", "none"):
        return []
    out = []
    nl = chr(10)
    cues = []
    for i, seg in enumerate(segs):
        a, b, text = seg[:3]
        nxt = segs[i + 1][0] if i + 1 < len(segs) else None
        parts = _split_cue(a, b, text, seg[3] if len(seg) > 3 else None)
        for k, (pa, pb, pt) in enumerate(parts):
            last = k == len(parts) - 1
            pb = max(pb, pa + 0.8)
            lim = nxt if last else parts[k + 1][0]
            if lim is not None and pb > lim:
                pb = max(lim - 0.02, pa + 0.3)
            cues.append((pa, pb, _sub_text(pt)))
    if fmts in ("srt", "both"):
        p = Path(f"{base_path}.srt")
        p.write_text(nl.join(f"{i}{nl}{_sub_time(a, True)} --> {_sub_time(b, True)}{nl}{t}{nl}"
                             for i, (a, b, t) in enumerate(cues, 1)), encoding="utf-8")
        out.append(p)
    if fmts in ("vtt", "both"):
        p = Path(f"{base_path}.vtt")
        p.write_text("WEBVTT" + nl + nl + nl.join(f"{_sub_time(a, False)} --> {_sub_time(b, False)}{nl}{t}{nl}"
                                                   for a, b, t in cues), encoding="utf-8")
        out.append(p)
    return out


def segs_from_stamped(text, total_end):
    """Rebuild (start, end, text) from '[HH:MM:SS] text' lines (used for translated transcripts)."""
    rows = []
    for line in text.splitlines():
        m = re.match(r"^\[(\d\d):(\d\d):(\d\d)\]\s*(?:\([^)]*\)\s*)?(.*)$", line)
        if m and m.group(4).strip():
            rows.append((int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)), m.group(4).strip()))
    return [(t, rows[i + 1][0] if i + 1 < len(rows) else max(total_end, t + 3), x)
            for i, (t, x) in enumerate(rows)]


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
               "call": "Call", "watch": "Watched", "cleanup": "Voice cleanup", "music": "Music extract"}


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


def add_history(kind, title, source, languages, duration, files, details=""):
    items = load_history()
    items.append({"time": datetime.datetime.now().isoformat(timespec="seconds"), "kind": kind,
                  "title": title, "source": str(source), "languages": languages,
                  "duration": duration, "files": [str(f) for f in files], "details": details})
    save_history(items)


# ---------------------------------------------------------------- editing a finished transcript
def parse_transcript_file(path):
    """Read a *_transcript.txt back into its parts."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    head, _, rest = text.partition("===== TIMESTAMPED =====")
    stamped = rest.split("===== PLAIN TEXT =====")[0].strip()
    hl = head.splitlines()
    meta = hl[1] if len(hl) > 1 else ""
    m = re.search(r"Languages spoken: (.*?)(?:\s+\|\s+|$)", meta)
    d = re.search(r"Duration: (\d+):(\d\d):(\d\d)", meta)
    return {
        "video_name": hl[0].replace("Transcript of:", "").strip() if hl else Path(path).stem,
        "lang_desc": m.group(1).strip() if m else "",
        "duration": int(d.group(1)) * 3600 + int(d.group(2)) * 60 + int(d.group(3)) if d else 0,
        "note": chr(10).join(x for x in hl[2:] if x.strip()),
        "stamped": stamped,
    }


def history_entry_for(path):
    """The history entry whose files include `path` (or None)."""
    key = str(Path(path))
    for e in load_history():
        if key in e.get("files", []):
            return e
    return None


def update_history_files(entry_time, entry_title, new_files):
    items = load_history()
    for e in items:
        if e.get("time") == entry_time and e.get("title") == entry_title:
            have = set(e.get("files", []))
            e["files"] = e.get("files", []) + [str(f) for f in new_files if str(f) not in have]
    save_history(items)


def rename_speakers_in_files(files, mapping):
    """Replace 'Speaker N' by a real name in every text-like file. Returns the files changed."""
    pats = [(re.compile(r"\b" + re.escape(old) + r"\b"), new.strip()) for old, new in mapping.items()
            if new.strip() and new.strip() != old]
    changed = []
    for f in files:
        p = Path(f)
        if p.suffix.lower() not in (".txt", ".md", ".srt", ".vtt", ".csv") or not p.exists():
            continue
        raw = p.read_text(encoding="utf-8-sig" if p.suffix.lower() == ".csv" else "utf-8", errors="replace")
        text = raw
        for pat, new in pats:
            text = pat.sub(lambda _m, n=new: n, text)
        if text != raw:
            p.write_text(text, encoding="utf-8-sig" if p.suffix.lower() == ".csv" else "utf-8")
            changed.append(p)
    return changed


def regenerate_outputs(path, cfg, online):
    """After the user edited a transcript: rebuild everything made from it - the plain-text part, subtitles,
    translations, summaries, chapters and Word/PDF exports - in the currently selected output languages."""
    p = Path(path)
    info = parse_transcript_file(p)
    stamped = info["stamped"]
    if not stamped:
        print("[!] This file has no timestamped lines - nothing to rebuild from.")
        return []
    print(f"Rebuilding from the edited transcript: {p.name}")
    out_dir = p.parent
    base = p.stem[:-len("_transcript")] if p.stem.endswith("_transcript") else p.stem
    lang_desc, duration, note = info["lang_desc"], info["duration"], info["note"] + chr(10) if info["note"] else ""
    lang_line = f"Languages spoken: {lang_desc}"
    write_transcript(p, info["video_name"], lang_line, duration, stamped, note)
    files = [p]
    subs = cfg.get("subtitles", "srt")
    for f in write_subtitles(out_dir / f"{base}_subtitles", segs_from_stamped(stamped, duration), subs):
        files.append(f)
        print(f"Subtitles saved: {f}")

    main_name = re.split(r"[,(]", lang_desc)[0].strip() or "English"
    main_code = LANG_CODES.get(main_name)
    targets, seen = [], set()
    for o in cfg.get("outputs", []):
        name, is_orig = (main_name, True) if o == "Original" else (o, bool(main_code) and LANG_CODES.get(o) == main_code)
        if name not in seen:
            seen.add(name)
            targets.append((name, is_orig))
    if not targets:
        targets = [(main_name, True)]

    for name, is_orig in targets:
        if is_orig:
            continue
        text, by = translate_transcript(stamped, name, online)
        if not text:
            print(f"  [!] No translator available for {name}.")
            continue
        f = out_dir / f"{base}_transcript_{safe_name(name)}.txt"
        write_transcript(f, info["video_name"], f"{lang_line}  |  Translated to {name} by {by}", duration, text, note)
        files.append(f)
        for sf in write_subtitles(out_dir / f"{base}_subtitles_{safe_name(name)}", segs_from_stamped(text, duration), subs):
            files.append(sf)
        print(f"Translation saved: {f}")

    if cfg.get("chapters"):
        ch_lang = targets[0][0]
        print(f"Finding chapters and key points ({ch_lang})...")
        md, by = make_chapters(stamped, duration, ch_lang, online)
        if md:
            f = out_dir / f"{base}_chapters.md"
            f.write_text(f"# Chapters and key points: {info['video_name']}" + chr(10) + chr(10) + md + chr(10) + chr(10) +
                         f"---{chr(10)}_{lang_line}. Made by: {by}_{chr(10)}", encoding="utf-8")
            files.append(f)

    summaries = []
    workdir = Path(tempfile.mkdtemp(prefix="vidsum_"))
    try:
        (workdir / "transcript.txt").write_text(stamped, encoding="utf-8")
        _notes_cache.clear()
        for name, _ in targets:
            print(f"Creating {name} summary...")
            res = summarize(workdir, stamped, info["video_name"], [], 0, lang_desc, name, online)
            if not res:
                print(f"  [!] Could not create the {name} summary.")
                continue
            summary, by = res
            suffix = "" if len(targets) == 1 else f"_{safe_name(name)}"
            f = out_dir / f"{base}_summary{suffix}.md"
            f.write_text(f"{summary}{chr(10)}{chr(10)}---{chr(10)}_{lang_line}. Rebuilt from an edited transcript. "
                         f"Summary by: {by}_{chr(10)}", encoding="utf-8")
            files.append(f)
            summaries.append((name, f, summary))
            print(f"  Saved: {f}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    exp = cfg.get("export", "none")
    if exp not in (None, "", "none") and summaries:
        import exporter
        ch_file = out_dir / f"{base}_chapters.md"
        for k, (_, sf, _s) in enumerate(summaries):
            try:
                for ef in exporter.export_summary(sf, exp, ch_file if k == 0 else None):
                    files.append(ef)
                    print(f"Exported: {ef}")
            except Exception as e:
                print(f"  [!] Could not export {sf.name}: {str(e)[:150]}")

    entry = history_entry_for(p)
    if entry:
        update_history_files(entry.get("time"), entry.get("title"), files)
    print(chr(10) + "Done - everything was rebuilt from your edited transcript.")
    return files


# ---------------------------------------------------------------- sources


def list_videos(folder: Path, recursive: bool):
    files = folder.rglob("*") if recursive else folder.iterdir()
    return sorted(f for f in files
                  if f.is_file() and f.suffix.lower() in BATCH_EXTENSIONS and not f.name.startswith("."))


def already_done(f: Path) -> bool:
    return (f.parent / f"{f.stem}_transcript.txt").exists()


class _YtLog:
    """Send yt-dlp errors to the job log (print) instead of the hidden stderr."""
    def debug(self, m): pass
    def info(self, m): pass
    def warning(self, m): pass
    def error(self, m): print(f"  [!] {m}")


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
            "quiet": True, "no_warnings": True, "noprogress": True, "progress_hooks": [hook],
            "logger": _YtLog()}
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
    if not results:
        print("[!] Nothing was downloaded - see the error above. If YouTube refuses the download, "
              "update the downloader:  pip install -U yt-dlp")
    return results


# ---------------------------------------------------------------- processing
def process_video(vpath: Path, cfg, model, online, kind="file", source=None, open_result=True):
    """Transcribe, translate and summarize one video. Returns the list of files created."""
    _notes_cache.clear()
    print(f"\nProcessing: {vpath}\n")
    clip = cfg.get("clip")
    global _SPEED
    _SPEED = min(max(float(cfg.get("speed") or 1.0), 0.5), 1.0)
    tmpdir = Path(tempfile.mkdtemp(prefix="vidsum_audio_"))
    try:
        audio_src, offset = prepare_audio(vpath, clip, cfg.get("noise", "off"), tmpdir, online)
        return _process(vpath, audio_src, offset, clip, cfg, model, online, kind, source, open_result)
    finally:
        _SPEED = 1.0
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

    # ---- Who speaks when (optional)
    diar = [(a * _SPEED + offset, b * _SPEED + offset, s)
            for a, b, s in diarize(audio_src, cfg.get("speakers", "off"), online)]

    # ---- Original transcript
    raw_stamped, _, info, stamped, dropped, marked, raw_segs = transcribe(
        model, audio_src, cfg["language"],
        multilingual=(mixed and cfg["language"] is None),
        detections=detections if mixed else None, offset=offset, noisy=noisy, diar=diar,
        words=bool(cfg.get("word_timing")))
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
    if diar:
        note += f"Speaker labels: {len({s for _, _, s in diar})} speakers detected automatically (they may be imperfect)" + chr(10)
    if _SPEED < 1.0:
        note += f"Audio slowed to {_SPEED:.0%} speed for recognition (timestamps are original time)\n"
    if noisy:
        note += f"Voice cleanup: {dict((v, k) for k, v in NOISE_CHOICES).get(cfg['noise'], cfg['noise'])}\n"
    files = []
    if noisy and cfg.get("keep_clean") and audio_src != str(vpath):
        clean = out_dir / f"{base}_cleaned_voice.wav"
        shutil.copyfile(audio_src, clean)
        files.append(clean)
        print(f"Cleaned voice saved: {clean}  (listen to check the cleanup)")
    orig_file = out_dir / f"{base}_transcript.txt"
    exact = chr(10).join(raw_stamped)
    write_transcript(orig_file, vpath.name, lang_line, info.duration, exact,
                     note + "Exact transcript: every word as the speech model heard it, nothing removed." + chr(10))
    files.append(orig_file)
    wf = write_words_csv(out_dir / f"{base}_words.csv", raw_segs) if cfg.get("word_timing") else None
    if wf:
        files.append(wf)
        print(f"Word timings saved: {wf}")
    subs = cfg.get("subtitles", "srt")
    for f in write_subtitles(out_dir / f"{base}_subtitles", raw_segs, subs):
        files.append(f)
        print(f"Subtitles saved: {f}")
    if body != exact:   # extra copy: made-up/repeated lines removed, [unclear] marks; used for translations/summaries
        filt_file = out_dir / f"{base}_transcript_filtered.txt"
        write_transcript(filt_file, vpath.name, lang_line, info.duration, body,
                         note + f"Filtered copy: {dropped} made-up/repeated line(s) removed, {marked} marked [unclear]. "
                         "Translations and summaries are made from this copy." + chr(10))
        files.append(filt_file)
        print(f"Filtered copy saved: {filt_file}")
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
        for sf in write_subtitles(out_dir / f"{base}_subtitles_{safe_name(name)}",
                                  segs_from_stamped(text, raw_segs[-1][1] if raw_segs else 0), subs):
            files.append(sf)
            print(f"Subtitles saved: {sf}")
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

    # ---- Chapters + key points (written once, in the first output language)
    if cfg.get("chapters") and body:
        ch_lang = targets[0][0] if targets else main_name
        print(f"Finding chapters and key points ({ch_lang})...")
        md, by = make_chapters(body, info.duration, ch_lang, online)
        if md:
            f = out_dir / f"{base}_chapters.md"
            f.write_text(f"# Chapters and key points: {vpath.name}" + chr(10) + chr(10) + md + chr(10) + chr(10) +
                         f"---{chr(10)}_{lang_line}. Made by: {by}_{chr(10)}", encoding="utf-8")
            files.append(f)
            print(f"Chapters saved: {f}" + chr(10))
        else:
            print("  [!] Could not make chapters (needs Claude Code, Ollama or LM Studio)." + chr(10))

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

    exp = cfg.get("export", "none")
    if exp not in (None, "", "none") and summaries:
        import exporter
        ch_file = out_dir / f"{base}_chapters.md"
        for k, (_, sf, _) in enumerate(summaries):
            try:
                for ef in exporter.export_summary(sf, exp, ch_file if k == 0 else None):
                    files.append(ef)
                    print(f"Exported: {ef}")
            except Exception as e:
                print(f"  [!] Could not export {sf.name}: {str(e)[:150]}")

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


def has_video_stream(path):
    """True when the file has a real picture (not just cover art)."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return False
    try:
        r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v", "-show_entries",
                            "stream=index:stream_disposition=attached_pic", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return False
    return any(line.strip().endswith(",0") for line in r.stdout.splitlines())


def mux_clean_video(src_video, clean_audio, out_path):
    """The original picture with the cleaned voice as its sound track (picture copied, not re-encoded;
    re-encoded only when the container can't take the original video stream)."""
    base = ["-i", str(src_video), "-i", str(clean_audio), "-map", "0:v:0", "-map", "1:a:0",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart"]
    try:
        _ff(*base[:6], "-c:v", "copy", *base[6:], out_path)
    except Exception:
        print("  (re-encoding the picture - this takes longer)")
        _ff(*base[:6], "-c:v", "libx264", "-crf", "20", "-preset", "fast", "-pix_fmt", "yuv420p", *base[6:], out_path)
    return Path(out_path).exists()


def _audio_job_history(kind, title, src_path, out_path, mode, started, extra_files=()):
    """History entry for a cleanup / music job: what went in, how, what came out."""
    import wave
    try:
        with wave.open(str(out_path)) as w:
            dur = w.getnframes() / w.getframerate()
    except Exception:
        dur = 0
    size = Path(out_path).stat().st_size / 1e6
    details = "\n".join([
        f"Source:   {src_path}", f"Mode:     {mode}", f"Output:   {out_path}",
        f"Length:   {fmt(dur)}", f"Size:     {size:.1f} MB", f"Took:     {fmt(time.time() - started)}"])
    add_history(kind, title, src_path, mode, dur, [out_path, *extra_files], details)


def _speed_tag(speed):
    return f"_{round(speed * 100)}pct" if speed < 1.0 else ""


def _mode_with_speed(mode, speed):
    return f"{mode}, slowed to {speed:.0%}" if speed < 1.0 else mode


def _run_stems_job(src_path: Path, out_dir: Path, stems, speed=1.0):
    """Standalone: save the chosen stems (vocals / drums / bass / other / instrumental) of a song."""
    names = [s for s, _ in STEM_CHOICES]
    stems = [s for s in names if s in (stems or [])] or ["instrumental"]
    if stems == ["instrumental"]:
        return _run_music_job(src_path, out_dir, speed)
    print(f"Separating stems ({', '.join(stems)}): {src_path}" + chr(10))
    started = time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix="vidsum_stems_"))
    try:
        src44 = tmpdir / "src.wav"
        _ff("-i", str(src_path), "-ac", 2, "-ar", 44100, "-c:a", "pcm_s16le", src44)
        got = demucs_stems(src44, tmpdir, stems)
        if not got:
            print("[!] Could not separate the song - is demucs installed?  pip install demucs")
            return
        tag, saved = _speed_tag(speed), []
        for s in stems:
            out_path = out_dir / f"{src_path.stem}_{s}{tag}.wav"
            n = 2
            while out_path.exists():
                out_path = out_dir / f"{src_path.stem}_{s}{tag}_{n}.wav"
                n += 1
            if speed < 1.0:
                _ff("-i", got[s], "-af", _with_tempo("", speed), out_path)
            else:
                shutil.copyfile(got[s], out_path)
            saved.append(out_path)
            print(f"Saved: {out_path}")
        _audio_job_history("music", f"{src_path.stem} - stems ({', '.join(stems)})", src_path, saved[0],
                           _mode_with_speed("Demucs stems: " + ", ".join(stems) + " (Offline)", speed), started, saved[1:])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _run_music_job(src_path: Path, out_dir: Path, speed=1.0):
    """Standalone: isolate the background music/instrumental from a song and save it."""
    print(f"Isolating background music: {src_path}\n")
    started = time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix="vidsum_music_"))
    try:
        src44 = tmpdir / "src.wav"
        _ff("-i", str(src_path), "-ac", 2, "-ar", 44100, "-c:a", "pcm_s16le", src44)
        result = demucs_isolate_music(src44, tmpdir / "music.wav")
        if not result:
            print("[!] Could not isolate the music - is demucs installed?  pip install demucs")
            return
        tag = _speed_tag(speed)
        out_path = out_dir / f"{src_path.stem}_music{tag}.wav"
        n = 2
        while out_path.exists():
            out_path = out_dir / f"{src_path.stem}_music{tag}_{n}.wav"
            n += 1
        if speed < 1.0:
            print(f"  Slowing to {speed:.0%} speed...")
            _ff("-i", result, "-af", _with_tempo("", speed), out_path)
        else:
            shutil.copyfile(result, out_path)
        print(f"\nSaved: {out_path}")
        _audio_job_history("music", f"{src_path.stem} - background music", src_path, out_path,
                           _mode_with_speed("Demucs vocal removal (Offline)", speed), started)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _run_cleanup_job(src_path: Path, out_dir: Path, noise_mode, online, speed=1.0, video=False):
    """Standalone voice cleanup: clean one file's audio and save it - no transcription."""
    print(f"Cleaning up: {src_path}\n")
    started = time.time()
    if noise_mode == "off":
        print('[!] Mode is "Off" - nothing to clean. Pick a mode in Voice Cleanup above first.')
        return
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix="vidsum_clean_"))
    try:
        want_video = bool(video) and has_video_stream(src_path)
        if want_video and speed < 1.0:
            print("  (A slowed-down video isn't made - the sound would no longer match the picture.)")
            want_video = False
        audio_src, _ = prepare_audio(src_path, None, noise_mode, tmpdir, online, speed,
                                     out_sr=48000 if want_video else None)
        tag = _speed_tag(speed)
        out_path = out_dir / f"{src_path.stem}_cleaned{tag}.wav"
        n = 2
        while out_path.exists():
            out_path = out_dir / f"{src_path.stem}_cleaned{tag}_{n}.wav"
            n += 1
        shutil.copyfile(audio_src, out_path)
        print(f"\nSaved: {out_path}")
        extra = []
        if want_video:
            print("Putting the cleaned voice back on the picture...")
            vid = out_path.with_suffix(".mp4")
            try:
                if mux_clean_video(src_path, out_path, vid):
                    extra.append(vid)
                    print(f"\nSaved video: {vid}")
            except Exception as e:
                print(f"  [!] Could not make the video: {str(e)[:150]}")
        _audio_job_history("cleanup", f"{src_path.stem} - cleaned voice", src_path, out_path,
                           _mode_with_speed(dict((v, k) for k, v in NOISE_CHOICES).get(noise_mode, noise_mode), speed),
                           started, extra)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------- feature dispatch
def _run_url_job(cfg, model, online):
    """URL mode: download via yt-dlp, then process like a file/folder job."""
    items = [{"path": p, "kind": "url", "source": page} for p, _, page in download_url(cfg["url"])]
    if not items:
        return
    if len(items) > 1 and cfg.get("clip"):
        print("  (A playlist was found - the 'only this part' range is ignored and every video is processed in full.)")
        cfg = {k: v for k, v in cfg.items() if k != "clip"}
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
