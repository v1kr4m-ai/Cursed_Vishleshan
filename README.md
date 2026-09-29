# Cursed_Vishleshan

A Windows desktop app that transcribes, translates and summarizes videos, audio files and live audio — with local voice cleanup and an NVIDIA GPU used automatically when available.

## Features

- **Sources:** a single video/audio file, a whole folder (batch), a YouTube/other link (playlists too), a watched folder (new files processed automatically), live microphone, live system audio (PC sound), or a call (mic + PC sound together)
- **Live capture:** on-screen transcript as you speak, translated live captions (always-on-top bar), keyword alerts, read-aloud
- **Outputs, per language you choose:** a raw transcript (`_transcript.txt` / `_transcript_<Lang>.txt`) and a summary (`_summary[_<Lang>].md`)
- **Voice cleanup:** offline filters (Light/Strong), offline AI cleanup (Demucs voice isolation + DeepFilterNet noise removal), or online AI cleanup (ElevenLabs Voice Isolator) — plus a standalone tool to clean up any file and save the result on its own
- **Language detection:** automatically detects which languages are spoken, and where, in mixed-language recordings
- **Searchable History** of everything processed
- **GPU acceleration:** uses an NVIDIA GPU automatically when available, falls back to CPU otherwise
- **Online/Offline toggle:** one switch that sets sensible tool defaults (which never disables any option) — summaries/translations try, in order: Claude Code CLI → Ollama → LM Studio → (English only) Whisper's own offline translation
- **Offline Settings:** pick exactly which installed Ollama / LM Studio model is used, instead of whatever happens to be listed first

Every feature opens as its own tab in one persistent window — nothing closes or gets replaced when you start something new.

## Setup

Requires Python 3.10+ and [ffmpeg](https://ffmpeg.org/) on `PATH`.

```bash
pip install faster-whisper sounddevice PyAudioWPatch yt-dlp edge-tts
```

Optional extras:

| Feature | Install |
|---|---|
| GPU acceleration | `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12==9.*` |
| Voice cleanup "Studio AI" (offline) | `pip install demucs` (DeepFilterNet downloads itself once) |
| Voice cleanup "Online AI" | an [ElevenLabs](https://elevenlabs.io) API key, entered in the Voice Cleanup tab |
| Live noise cleanup | `pip install noisereduce` |
| Offline summaries/translations | [Ollama](https://ollama.com) or [LM Studio](https://lmstudio.ai) with a model downloaded |
| Best-quality summaries/translations | [Claude Code](https://claude.com/claude-code) installed and logged in |

## Usage

```bash
python video_summarizer.py
```

or double-click `Cursed_Vishleshan.bat`. Pick a Whisper model, spoken language and source on the **Home** tab, then **Start** — the feature opens in its own tab. Voice cleanup mode, background-music isolation, and which Ollama/LM Studio model gets used are all under **Settings** (menu bar, or the button on Home) and apply everywhere.

## Install

```bash
pip install -r requirements.txt
```

See `requirements.txt` for what's core vs. optional (GPU acceleration, Demucs voice/music isolation, live noise reduction) — it mirrors the table above with versions pinned to what's tested.
