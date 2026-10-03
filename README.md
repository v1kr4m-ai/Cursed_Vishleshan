# Cursed_Vishleshan

A Windows desktop app that **transcribes, translates and summarizes** video, audio and live sound, cleans up noisy voices, and pulls the background music out of a song. Speech recognition runs **locally** with Whisper (GPU-accelerated on NVIDIA cards); summaries and translations use whichever AI backend you have - online (Claude Code) or fully offline (Ollama / LM Studio).

The interface is a native `pywebview` window (HTML/CSS/JS in `web/`). No browser, no server address - run it like any desktop app.

---

## Current features

### Sources - what you can process
| Source | What it does |
|---|---|
| **Video / audio file** | Transcribe, translate and summarize a single file (mp4, mkv, mov, avi, webm, mp3, wav, m4a, flac and more) |
| **Folder (batch)** | Process every media file in a folder (optionally including subfolders), skipping ones already done; writes a batch report |
| **YouTube / link** | Download via yt-dlp (playlists too) and process. Needs internet |
| **Watch folder** | Keeps watching a folder and processes new files automatically as they finish copying. Has a Stop button |
| **Live microphone** | Real-time transcript as you speak |
| **System audio** | Captures PC sound (WASAPI loopback) and transcribes it live |
| **Call** | Mic ("You") + PC sound ("Them") together, labelled per speaker |

### Transcription and language handling
- **Whisper models** from `tiny` to `large-v3` (plus `distil-large-v3`), downloaded on demand from the Home screen with live progress. Selected model is remembered.
- **GPU acceleration** is automatic (CUDA via CTranslate2); falls back to CPU when no usable GPU/libraries are found.
- **Spoken-language detection** across the whole recording - mixed-language audio is transcribed piece by piece in each detected language.
- **Custom vocabulary** (names, terms, abbreviations) that Whisper is nudged toward and that translations/summaries keep.
- Hallucination and repetition filtering on silent or noisy stretches.

### Outputs
Per file, next to the source: `<name>_transcript.txt` (original language), `<name>_transcript_<Language>.txt` for every translation you choose, and `<name>_summary[_<Language>].md`. Optional extras: the cleaned voice (`_cleaned_voice.wav`) and spoken-audio versions of translations (text-to-speech). Live recordings, downloads and history are kept in `Documents\Cursed_Vishleshan`.

### Translation and summaries
Tried in order, first one that works wins:
1. **Claude Code CLI** (`claude -p`) - best quality, needs internet
2. **Ollama** - any model installed locally
3. **LM Studio** - any model served locally
4. English only, as a last resort: Whisper's own offline translation

Long transcripts are summarized in parts first, so length is not a limit. Key video frames can be given to vision-capable models.

### Voice cleanup (Voice Cleanup tab)
Applied automatically to every feature, and available as a standalone tool.

| Mode | Engine | Network |
|---|---|---|
| Off | - | - |
| Light filter | ffmpeg | Offline |
| Strong filter | ffmpeg | Offline |
| Studio AI | **Demucs** voice isolation + **DeepFilterNet** noise removal | Offline |
| ElevenLabs Voice Isolator | ElevenLabs API | Online |

- **Clean up a file:** pick any audio/video file and a folder; get a cleaned `.wav`.
- **Extract background music:** pick a song; Demucs removes the vocals and saves the instrumental as a **stereo** `.wav`.
- Studio AI falls back step by step (e.g. to the Strong filter) if a model is missing, instead of failing.
- The ElevenLabs key is stored **encrypted with Windows DPAPI** (tied to your Windows account), never in plain text.

### Live capture (microphone / system audio / call)
Record/Stop, input level meters, device pickers, committed text vs. provisional text while you speak, per-speaker labels in call mode, **alert words** (flags when a keyword is spoken), **Translate** to another language, **Read aloud**, **Save** (transcript + audio + history entry), Copy and Clear.

### Settings and quality-of-life
- **Online / Offline preference toggle:** sets which tools are preferred by default (Claude/ElevenLabs/edge-tts vs. Ollama/LM Studio/local cleanup). It never disables an option; an internet-status light shows real connectivity separately.
- **Offline Settings:** choose exactly which installed **Ollama** and **LM Studio** model is used for summaries and translations.
- **History:** searchable list of everything processed (titles, languages, and the full text of transcripts and summaries), with preview, open file, show in folder and remove.
- Read-aloud/text-to-speech: Microsoft neural voices when online (edge-tts), built-in Windows voices offline.
- Keeps Windows awake during long batch jobs.

---

## Setup

Requires **Windows**, **Python 3.10+** and [ffmpeg](https://ffmpeg.org/) on `PATH`.

```bash
pip install -r requirements.txt
```

`requirements.txt` is pinned to what is tested here and is split into core and optional parts (GPU acceleration, Demucs, live noise reduction). Its header explains what to drop if you have no NVIDIA GPU or an older one. In short:

| Feature | Needs |
|---|---|
| Core transcription + UI | `faster-whisper`, `pywebview`, `sounddevice`, `PyAudioWPatch`, `yt-dlp`, `edge-tts` |
| GPU transcription | `nvidia-cublas-cu12`, `nvidia-cudnn-cu12` |
| Studio AI cleanup + music isolation | `demucs` and `torch` (a CUDA 13 build for RTX 50-series GPUs; see `requirements.txt`). DeepFilterNet downloads itself the first time it is used - the `deepfilternet` pip package is **not** needed |
| ElevenLabs cleanup | An ElevenLabs API key (Voice Cleanup tab) |
| Offline summaries/translations | [Ollama](https://ollama.com) or [LM Studio](https://lmstudio.ai) with a model downloaded |
| Best-quality summaries/translations | [Claude Code](https://claude.com/claude-code) installed and logged in |

## Usage

```bash
python app.py
```

or double-click `Cursed_Vishleshan.bat`.

1. **Home** - pick a Whisper model (click one to select; click a grey one to download it), the spoken language, the output languages, and what to process, then press **Start**. Progress streams into a log panel under the button.
2. **Voice Cleanup** - choose a cleanup mode (applies everywhere) and use the standalone cleanup / music tools.
3. **Offline Settings** - pick your Ollama / LM Studio models.
4. **History** - search and reopen past results.

The first run of anything that needs a model (Whisper, Demucs, DeepFilterNet) downloads it once and reuses it afterwards.

## How it is built

- `app.py` - pywebview host and the JS bridge (`Api`). Long jobs run in background threads; the page **polls** Python for job logs, download progress and live-capture events. Python never pushes into the page (calling `evaluate_js` from background threads deadlocked pywebview on this setup).
- `live.py` - GUI-free live capture engine (microphone / PC sound / call).
- `video_summarizer.py` - the processing backend: transcription, translation, summaries, voice cleanup, history, settings. It contains no GUI code.
- `web/` - `index.html`, `style.css`, `app.js`. Opening it outside pywebview uses built-in mock data, which is handy for design work.

Settings live in `video_summarizer_settings.json` (not committed). The earlier Tkinter interface was removed in the "Stage 5" commit and is still in git history.

---

## Known limitations

- **Windows only for now.** System-audio capture uses WASAPI loopback via PyAudioWPatch, and offline text-to-speech uses Windows' built-in voices.
- GPU libraries are version-sensitive. Whisper's CUDA 12 cuDNN and PyTorch's CUDA 13 cuDNN can clash in one process; Demucs retries without cuDNN automatically when that happens.
- A Whisper model whose download was interrupted shows up as not downloaded - click it again to re-download (needs internet).
- The first Studio AI run is slow while models download; CPU-only Studio AI runs at roughly real-time speed.
- Not carried over from the old interface: the always-on-top live caption bar, the "clean up & re-transcribe" action for live recordings, and the "only this part (e.g. 10:00-25:00)" clip range.

## Roadmap - future features

**Next up (parity with the old interface)**
- Live caption overlay: always-on-top translated subtitle bar as a second window, with font / colour / position settings
- "Clean up & re-transcribe" for live recordings
- Clip range ("only this part") for file and link jobs
- Stop/cancel for every running job, not just Watch
- Reopen the produced files directly from a finished job's log panel

**Interface**
- Light/dark themes and further polish toward a production-grade look
- Drag-and-drop files and folders onto the window
- A job queue view with per-job progress rather than one log panel per job
- Notifications when a long job finishes

**Capabilities**
- Speaker diarization (who spoke when) for recordings and calls
- Subtitle export (`.srt` / `.vtt`) and burned-in subtitles
- Export summaries to `.docx` / `.pdf`
- Chapter detection and timestamped key points
- Cleaned **video** output (cleaned audio remuxed over the original picture)
- More music tools: separate drums / bass / other stems, not just vocals vs. instrumental
- Bring-your-own-API backends beyond Claude Code / Ollama / LM Studio

**Platform and distribution**
- Cross-platform support (macOS, Linux): alternatives for system-audio capture and offline speech
- A packaged installer / standalone `.exe`. Note: a GPU-enabled build is about 5 GB because of PyTorch + CUDA; a CPU-only build would be roughly 300-500 MB
- Automated tests for the processing backend and the bridge
- A separate Android version, built as its own project from this one rather than changing it

---

## License

No license has been chosen yet. All rights reserved until one is added.
