# Graph Report - .  (2026-11-03)

## Corpus Check
- Corpus is ~38,646 words - fits in a single context window. You may not need a graph.

## Summary
- 490 nodes · 957 edges · 55 communities (26 shown, 29 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 32 edges (avg confidence: 0.7)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Frontend UI Logic
- Live Session Management
- Application API
- Whisper Configuration
- Job Processing & History
- Transcription Pipeline
- Core App Lifecycle
- Task Queue Worker
- Transcription Engine
- Local AI Backends
- Summarization Logic
- Export System
- Audio Stemming
- Audio Cleanup
- URL Downloads
- File Handling
- Model Management
- Session History
- TTS & Language
- Speech Playback
- Caption Overlay
- Subtitle Generation
- Media Serving
- Offline Settings
- Job Buffer
- Exception Handling
- Demucs Isolation
- Step Execution
- Transcript Editing
- Model Tagging
- App Entry
- Caption Node
- Claude Code
- Project Root
- DeepFilterNet
- Demucs
- Edge TTS
- ElevenLabs
- History Tab
- Home Screen
- Img Home
- Img Model Deck
- Img Offline Settings
- Img Voice Cleanup
- Live Logic
- LM Studio
- Offline Tab
- Ollama
- PyWebView
- Sherpa-ONNX
- Summarizer Logic
- Voice Cleanup Tab
- Web UI
- Whisper
- yt-dlp

## God Nodes (most connected - your core abstractions)
1. `Api` - 67 edges
2. `LiveSession` - 36 edges
3. `_process()` - 25 edges
4. `callApi()` - 25 edges
5. `fmt()` - 16 edges
6. `transcribe()` - 16 edges
7. `boot()` - 14 edges
8. `prepare_audio()` - 13 edges
9. `regenerate_outputs()` - 13 edges
10. `toast()` - 12 edges

## Surprising Connections (you probably didn't know these)
- `apply_offline_settings()` --calls--> `load_settings()`  [EXTRACTED]
  app.py → video_summarizer.py
- `_with_model()` --calls--> `is_downloaded()`  [EXTRACTED]
  app.py → video_summarizer.py
- `_with_model()` --calls--> `load_whisper()`  [EXTRACTED]
  app.py → video_summarizer.py
- `_migrate_defaults()` --calls--> `save_settings()`  [EXTRACTED]
  app.py → video_summarizer.py
- `main()` --calls--> `internet_ok()`  [EXTRACTED]
  app.py → video_summarizer.py

## Import Cycles
- None detected.

## Communities (55 total, 29 thin omitted)

### Community 0 - "Frontend UI Logic"
Cohesion: 0.07
Nodes (75): activateTab(), activeModel(), addJobPanel(), addLivePanel(), applyPreset(), boot(), buildFileTool(), buildOutputBody() (+67 more)

### Community 1 - "Live Session Management"
Cohesion: 0.08
Nodes (5): LiveSession, _Loopback, Live capture engine (microphone / PC sound / call) - GUI-free. Extracted from…, Clean the whole recording (voice isolation + noise removal) and transcribe it…, PC-sound (WASAPI loopback) stream via PyAudioWPatch.

### Community 2 - "Application API"
Cohesion: 0.06
Nodes (3): Api, {'Speaker 1': 'Alice', ...} applied to every text file of the entry…, Steps to leave out of a queued (or running) job: speakers, translation,…

### Community 3 - "Whisper Configuration"
Cohesion: 0.11
Nodes (25): _add_nvidia_dlls(), all_whisper_models(), apply_hints(), custom_whisper_models(), diarize(), _dpapi_protect(), _dpapi_unprotect(), elevenlabs_key() (+17 more)

### Community 4 - "Job Processing & History"
Cohesion: 0.09
Nodes (19): _history_media(), Save the user's edit of a transcript/summary. The first save keeps the…, Export a summary .md from History as Word or PDF next to it; returns {ok,…, The recording a history entry came from (so the preview can play it), if it…, Stop a job. Waiting in the queue: dropped. Running: stopped as soon as it next…, Skip the step a running job is in right now (translation, summary, chapters,…, Path, already_done() (+11 more)

### Community 5 - "Transcription Pipeline"
Cohesion: 0.12
Nodes (24): extract_frames(), fmt(), _hms(), make_chapters(), open_path(), parse_transcript_file(), print_language_stats(), _process() (+16 more)

### Community 6 - "Core App Lifecycle"
Cohesion: 0.13
Nodes (19): _job_finished_notice(), main(), _migrate_defaults(), _notify(), _on_closing(), _queue_position(), _quit_app(), Cursed_Vishleshan - pywebview host + JS bridge. All… (+11 more)

### Community 7 - "Task Queue Worker"
Cohesion: 0.16
Nodes (11): _qadd(), _qfile(), _qread(), _qremove(), _queue_worker(), _qwrite(), Rebuild subtitles, translations, summaries, chapters and exports from an edited…, Run target_fn in a background thread (one job at a time, like the Tk app's… (+3 more)

### Community 8 - "Transcription Engine"
Cohesion: 0.15
Nodes (15): decode_kwargs(), is_hallucination(), LoopGuard, Whisper settings. 'noisy' = safer decoding for rough audio (fewer made-up…, Whisper sometimes gets stuck repeating one line. Real speech repeats too…, The speaker whose turns overlap [t0, t1] the most (None if nobody does)., Whisper info for slowed audio, with the duration put back to original-recording…, offset = where the audio starts inside the full video (clip range), added to… (+7 more)

### Community 9 - "Local AI Backends"
Cohesion: 0.20
Nodes (15): ensure_lmstudio(), ensure_ollama(), http_json(), list_lmstudio_models(), list_ollama_models(), lmstudio_chat(), lmstudio_model(), local_backend() (+7 more)

### Community 10 - "Summarization Logic"
Cohesion: 0.18
Nodes (14): backend_order(), claude_text(), detect_languages(), pick_evenly(), Check the language of each ~30s piece of audio. Returns [(start_sec, code,…, Yield (label, fn(system, user) -> text) for each usable backend, in order., split_chunks(), summarize() (+6 more)

### Community 11 - "Export System"
Cohesion: 0.26
Nodes (12): _add_runs(), build_docx(), build_html(), _edge(), export_summary(), html_to_pdf(), _is_rtl(), Export a summary (and chapters) to Word (.docx) and PDF. GUI-free. Word files… (+4 more)

### Community 12 - "Audio Stemming"
Cohesion: 0.21
Nodes (13): demucs_stems(), has_video_stream(), _mode_with_speed(), True when the file has a real picture (not just cover art)., Standalone: save the chosen stems (vocals / drums / bass / other /…, Standalone: isolate the background music/instrumental from a song and save it., Standalone voice cleanup: clean one file's audio and save it - no transcription., Separate a song into the wanted stems in ONE pass. stems: any of vocals, drums,… (+5 more)

### Community 13 - "Audio Cleanup"
Cohesion: 0.20
Nodes (12): deepfilter_denoise(), elevenlabs_isolate(), ensure_deepfilter_exe(), _ff(), mux_clean_video(), prepare_audio(), The original picture with the cleaned voice as its sound track (picture copied,…, The standalone DeepFilterNet program (no Python packages needed). Downloaded… (+4 more)

### Community 14 - "URL Downloads"
Cohesion: 0.17
Nodes (8): download_url(), keep_awake(), Stop Windows from going to sleep while a long job runs., Send yt-dlp errors to the job log (print) instead of the hidden stderr., Download a video (or a whole playlist) with yt-dlp. Returns [(path, title,…, URL mode: download via yt-dlp, then process like a file/folder job., _run_url_job(), _YtLog

### Community 15 - "File Handling"
Cohesion: 0.20
Nodes (6): _parse_time(), Queue a second pass over [start, end] of the recording with another model., Job body: load the Whisper model, then fn(model). load_whisper() calls…, 90', '1:30', '01:02:03', '1h2m3s' -> seconds (None when empty). Raises…, Files / folders dropped on the window: a folder becomes a Folder job, each…, _with_model()

### Community 16 - "Model Management"
Cohesion: 0.25
Nodes (6): _model_dir(), _model_info(), _noise_label(), Folder in the Hugging Face cache that holds this Whisper model's files., is_downloaded(), repo_for()

### Community 17 - "Session History"
Cohesion: 0.29
Nodes (8): add_history(), _audio_job_history(), history_entry_for(), load_history(), The history entry whose files include `path` (or None)., History entry for a cleanup / music job: what went in, how, what came out., save_history(), update_history_files()

### Community 18 - "TTS & Language"
Cohesion: 0.29
Nodes (8): _edge_voice(), lang_name(), language_stats(), -> [{code, name, share, ranges}] sorted by share., Speech for `text` in language `lang` (name). Online: Microsoft neural voices…, stamped_from_entries(), tts_to_file(), _windows_tts()

### Community 19 - "Speech Playback"
Cohesion: 0.25
Nodes (4): play_audio(), Play a sound file (blocking) until it ends or stop_event is set. Windows only., Reads texts aloud one after another in a background thread., SpeechPlayer

### Community 20 - "Caption Overlay"
Cohesion: 0.29
Nodes (3): _caption_close(), _caption_geometry(), Pixel size/position of the caption overlay for the given caption settings.

### Community 21 - "Subtitle Generation"
Cohesion: 0.29
Nodes (7): Wrap to at most two balanced-ish lines of ~width characters, the usual subtitle…, A long segment becomes several cues, split at the pauses between words (needs…, segs = [(start, end, text)]. Writes base_path.srt and/or .vtt per `fmts` (e.g.…, _split_cue(), _sub_text(), _sub_time(), write_subtitles()

### Community 22 - "Media Serving"
Cohesion: 0.33
Nodes (3): _MediaServer, A URL the page's audio/video player can play for this recording. Formats the…, Tiny loopback-only web server so the page's <video> can play local recordings…

### Community 25 - "Exception Handling"
Cohesion: 0.40
Nodes (5): BaseException, JobCancelled, Raised inside a running job when the user presses Stop. BaseException on…, Raised inside a running step when the user presses 'Skip step'; the step's…, StepSkipped

### Community 26 - "Demucs Isolation"
Cohesion: 0.40
Nodes (5): demucs_isolate(), demucs_isolate_music(), _demucs_run(), Separate the voices from everything else with Demucs (offline AI). Returns out…, Separate the background music/instrumental from the voices with Demucs (offline…

### Community 29 - "Model Tagging"
Cohesion: 0.50
Nodes (4): model_tag(), cloud' (needs sign-in), 'base' (not chat-tuned), 'vision/other', or '' for an…, Local chat-capable models, best known families first - what 'auto' picks from., suitable_models()

## Knowledge Gaps
- **17 isolated node(s):** `SOURCE_MODES`, `MOCK_HOME`, `MOCK_CLEANUP`, `MOCK_OFFLINE`, `MOCK_HISTORY` (+12 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **29 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Api` connect `Application API` to `Job Processing & History`, `Core App Lifecycle`, `Task Queue Worker`, `File Handling`, `Model Management`, `Caption Overlay`, `Media Serving`, `Offline Settings`, `Transcript Editing`?**
  _High betweenness centrality (0.151) - this node is a cross-community bridge._
- **Why does `export_summary()` connect `Export System` to `Job Processing & History`?**
  _High betweenness centrality (0.020) - this node is a cross-community bridge._
- **Are the 21 inferred relationships involving `Path` (e.g. with `.cancel_job()` and `.export_file()`) actually correct?**
  _`Path` has 21 INFERRED edges - model-reasoned connections that need verification._
- **What connects `SOURCE_MODES`, `MOCK_HOME`, `MOCK_CLEANUP` to the rest of the system?**
  _17 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Frontend UI Logic` be split into smaller, more focused modules?**
  _Cohesion score 0.07017543859649122 - nodes in this community are weakly interconnected._
- **Should `Live Session Management` be split into smaller, more focused modules?**
  _Cohesion score 0.08181818181818182 - nodes in this community are weakly interconnected._
- **Should `Application API` be split into smaller, more focused modules?**
  _Cohesion score 0.05873015873015873 - nodes in this community are weakly interconnected._