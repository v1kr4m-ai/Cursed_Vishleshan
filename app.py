"""
Cursed_Vishleshan - pywebview host + JS bridge.

All transcription/translation/summarization/voice-cleanup/history logic lives in
video_summarizer.py, untouched. This file only bridges the web UI (web/) to it -
no processing logic belongs here.

Stage 1: shell + Home tab (model picker with real download progress, language/source
picker, settings persistence). Job dispatch (Start) is a stub until Stage 3.
"""
import contextlib
import datetime
import hashlib
import re
import sys
from pathlib import Path

# Started with pythonw (no console window): stdout/stderr don't exist, which crashes libraries
# that write progress bars. Send them to a log file instead - also the place to look for errors.
if sys.stdout is None or sys.stderr is None:
    _log = open(Path(__file__).with_name("app.log"), "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log

# Same reason: without a console of its own, every ffmpeg / claude / lms child process would pop up
# a console window. Make "no window" the default for all child processes (ours and libraries').
_PROCS = []   # child processes started since the current job began (Stop ends them)
if sys.platform == "win32":
    import subprocess
    _popen_init = subprocess.Popen.__init__

    def _quiet_popen(self, *a, **kw):
        kw["creationflags"] = kw.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        _popen_init(self, *a, **kw)
        _PROCS.append(self)   # so Stop can end the helper program (ffmpeg, claude...) of the running job
    subprocess.Popen.__init__ = _quiet_popen

import shutil
import threading
import uuid
from pathlib import Path

import webview

import live
import video_summarizer as vs

WEB_DIR = Path(__file__).with_name("web")

# Background threads write here; the page POLLS these via js_api getters instead of
# Python pushing into the page (window.evaluate_js() called from a non-GUI thread can
# deadlock pywebview's EdgeChromium backend - this avoids that class of hang entirely).
DROPS = []            # results of jobs started by dropping files on the window, waiting for the page
JOBS = {}             # job_id -> {"lines": [str, ...], "done": bool}
MODEL_PROGRESS = {}   # model_name -> {"pct": int|None, "err": str|None, "done": bool}
WATCH_EVENTS = {}     # job_id -> threading.Event, for the Watch mode Stop button
LIVE = {}             # session_id -> live.LiveSession
CAPTION = {"sid": None, "window": None}   # the single always-on-top caption overlay


def _model_dir(name):
    """Folder in the Hugging Face cache that holds this Whisper model's files."""
    from huggingface_hub.constants import HF_HUB_CACHE
    return Path(HF_HUB_CACHE) / ("models--" + vs.repo_for(name).replace("/", "--"))


def _model_info(n, s, d):
    folder = _model_dir(n)
    size = 0
    if folder.exists():
        size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
    return {"name": n, "size": s, "desc": d, "downloaded": vs.is_downloaded(n),
            "onDisk": folder.exists(), "diskMB": round(size / 1024 / 1024)}


# Engine settings that vs reads as module globals; applied at start-up and after every save.
OFFLINE_DEFAULTS = {"backend_order": ["claude", "ollama", "lmstudio"],
                    "ollama_url": "http://localhost:11434", "lmstudio_url": "http://localhost:1234",
                    "ollama_num_ctx": 16384, "send_frames": False, "max_frames": 6,
                    "timeout_min": 30, "chunk_chars": 12000, "translate_chunk_chars": 4000}


def apply_offline_settings():
    s = vs.load_settings()
    o = {k: s.get(k, v) for k, v in OFFLINE_DEFAULTS.items()}
    order = [b for b in o["backend_order"] if b in ("claude", "ollama", "lmstudio")]
    vs.BACKEND, vs.BACKEND_ORDER = "auto", order or list(OFFLINE_DEFAULTS["backend_order"])
    vs.OLLAMA_URL, vs.LMSTUDIO_URL = o["ollama_url"].rstrip("/"), o["lmstudio_url"].rstrip("/")
    vs.OLLAMA_NUM_CTX = int(o["ollama_num_ctx"])
    vs.LOCAL_SEND_FRAMES, vs.LOCAL_MAX_FRAMES = bool(o["send_frames"]), int(o["max_frames"])
    vs.LOCAL_TIMEOUT_SEC = int(o["timeout_min"]) * 60
    vs.CHUNK_CHARS, vs.TRANSLATE_CHUNK_CHARS = int(o["chunk_chars"]), int(o["translate_chunk_chars"])
    return o


def _noise_label(value: str) -> str:
    return dict((v, l) for l, v in vs.NOISE_CHOICES).get(value, "Off")


class _JobBuffer:
    """File-like object that buffers print() output for a job; polled, never pushed."""
    def __init__(self, job_id):
        self.job_id = job_id

    def write(self, s):
        if s:
            JOBS[self.job_id]["lines"].append(s)

    def flush(self):
        pass


def _run_job(target_fn, *args, **kwargs):
    """Run target_fn in a background thread (one job at a time, like the Tk app's
    PROCESSING_LOCK), buffering its print() output for get_job_log() to poll."""
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"lines": [], "done": False}
    _QUEUE.append((job_id, target_fn, args, kwargs))
    _QUEUE_WAKE.release()
    global _WORKER
    if _WORKER is None:
        _WORKER = threading.Thread(target=_queue_worker, daemon=True)
        _WORKER.start()
    return job_id


class JobCancelled(BaseException):
    """Raised inside a running job when the user presses Stop. BaseException on purpose: the
    'except Exception' blocks all over the processing code must not swallow it."""


_CURRENT = {"job": None, "tid": None}  # the job running right now and its thread
_CANCELLED = set()                     # job ids the user stopped
_QUEUE = []                           # waiting jobs, first in first out
_QUEUE_WAKE = threading.Semaphore(0)  # one release per queued job
_WORKER = None


def _queue_worker():
    """Runs queued jobs one after another; a job starts as soon as the previous one finishes."""
    while True:
        _QUEUE_WAKE.acquire()
        job_id, target_fn, args, kwargs = _QUEUE.pop(0)
        try:
            _PROCS.clear()
            _CURRENT.update(job=job_id, tid=threading.get_ident())
            try:
                with contextlib.redirect_stdout(_JobBuffer(job_id)):
                    target_fn(*args, **kwargs)
            except JobCancelled:
                JOBS[job_id]["lines"].append(chr(10) + "Stopped." + chr(10))
            except Exception as e:
                JOBS[job_id]["lines"].append(chr(10) + f"[!] {e}" + chr(10))
            finally:
                _CURRENT.update(job=None, tid=None)
                JOBS[job_id]["done"] = True
        except JobCancelled:
            pass   # Stop arrived just as the job was finishing


def _queue_position(job_id):
    """0 = running now (or done); n = number of jobs ahead of it."""
    for i, item in enumerate(_QUEUE):
        if item[0] == job_id:
            return i + 1
    return 0


def _with_model(model_name, fn):
    """Job body: load the Whisper model, then fn(model). load_whisper() calls sys.exit() on
    failure, which would silently kill a bridge thread - here it becomes a visible log line."""
    if not vs.is_downloaded(model_name):
        print(f"[!] The '{model_name}' model isn't fully downloaded. Click it in the model list on "
              f"Home to download it (or pick another model), then press Start again.")
        return
    try:
        model = vs.load_whisper(model_name)
    except SystemExit:
        print(f"[!] Could not load the '{model_name}' model - see the message above.")
        return
    return fn(model)


def _caption_geometry(cs):
    """Pixel size/position of the caption overlay for the given caption settings."""
    try:
        scr = webview.screens[0]
        sw, sh = scr.width, scr.height
    except Exception:
        sw, sh = 1920, 1080
    width = max(300, int(sw * cs["width"] / 100))
    height = int(cs["lines"]) * int(int(cs["size"]) * 1.45) + 34 + (int(int(cs["size"]) * 0.8) if cs["show_original"] else 0)
    x = (sw - width) // 2
    y = 30 if cs["position"] == "Top" else sh - height - 90
    return x, y, width, height


def _caption_close():
    w, CAPTION["window"], CAPTION["sid"] = CAPTION["window"], None, None
    if w:
        try:
            w.destroy()
        except Exception:
            pass


class _MediaServer:
    """Tiny loopback-only web server so the page's <video> can play local recordings (the page itself is
    served over http, which browsers don't let load file:// URLs). Only files registered through
    url_for() are served, under an unguessable token, with Range support so seeking works."""
    _inst = None

    def __init__(self):
        import http.server
        import mimetypes
        import os
        import re
        import secrets
        files = self.files = {}
        self._secrets = secrets

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _serve(self, head):
                tok = self.path.split("/")[-1].split("?")[0]
                path = files.get(tok)
                if not path or not os.path.exists(path):
                    self.send_error(404)
                    return
                size = os.path.getsize(path)
                start, end = 0, size - 1
                m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
                if m and (m.group(1) or m.group(2)):
                    if m.group(1):
                        start = int(m.group(1))
                        end = int(m.group(2)) if m.group(2) else size - 1
                    else:
                        start = max(size - int(m.group(2)), 0)
                    end = min(end, size - 1)
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                else:
                    self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(path)[0] or "application/octet-stream")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(end - start + 1))
                self.end_headers()
                if head:
                    return
                try:
                    with open(path, "rb") as f:
                        f.seek(start)
                        left = end - start + 1
                        while left > 0:
                            chunk = f.read(min(1 << 16, left))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            left -= len(chunk)
                except (ConnectionError, OSError):
                    pass

            def do_GET(self):
                self._serve(False)

            def do_HEAD(self):
                self._serve(True)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @classmethod
    def url_for(cls, path):
        self = cls._inst = cls._inst or cls()
        tok = next((t for t, p in self.files.items() if p == str(path)), None) or self._secrets.token_hex(12)
        self.files[tok] = str(path)
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/media/{tok}"


_PLAYABLE = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".mp4", ".m4v", ".webm"}
_VIDEO = {".mp4", ".m4v", ".webm", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".mpg", ".mpeg", ".3gp"}


def _history_media(e):
    """The recording a history entry came from (so the preview can play it), if it still exists."""
    for f in reversed(e.get("files", [])):
        p = Path(f)
        if p.suffix.lower() in vs.BATCH_EXTENSIONS and p.exists():
            return {"path": str(p), "kind": "video" if p.suffix.lower() in _VIDEO else "audio"}
    return None


class Api:
    def __init__(self):
        self._window = None

    # ---------------------------------------------------------------- Home tab
    def get_home_data(self):
        saved = vs.load_settings()
        online0 = vs.internet_ok()
        models = [_model_info(n, s, d) for n, s, d in vs.WHISPER_MODELS]
        spoken_code = saved.get("language")
        device, _ = vs.pick_device()
        return {
            "historyCount": len(vs.load_history()),
            "gpu": device,
            "models": models,
            "selectedModel": saved.get("model", vs.WHISPER_MODEL) if any(
                m["name"] == saved.get("model") and m["downloaded"] for m in models) else next(
                (m["name"] for m in models if m["downloaded"]), None),
            "spokenLanguage": vs.lang_name(spoken_code) if spoken_code else "Auto-detect",
            "spokenChoices": vs.SPOKEN_CHOICES,
            "speedChoices": [n for n, _ in vs.SPEED_CHOICES],
            "speed": next((n for n, v in vs.SPEED_CHOICES if v == saved.get("speed", 1.0)), vs.SPEED_CHOICES[0][0]),
            "outputChoices": vs.OUTPUT_CHOICES,
            "outputs": saved.get("outputs", vs.OUTPUT_LANGUAGES),
            "mode": saved.get("mode", "file"),
            "skipDone": bool(saved.get("skip_done", True)),
            "subfolders": bool(saved.get("subfolders", False)),
            "speakSave": bool(saved.get("speak_save", False)),
            "subtitles": saved.get("subtitles", "srt"),
            "chapters": bool(saved.get("chapters", False)),
            "export": saved.get("export", "none"),
            "wordTiming": bool(saved.get("word_timing", False)),
            "speakerChoices": [n for n, _ in vs.SPEAKER_CHOICES],
            "speakers": next((n for n, v in vs.SPEAKER_CHOICES if v == saved.get("speakers", "off")), "Off"),
            "onlineReal": online0,
            "onlinePref": bool(saved.get("mode_online", online0)),
            "noiseLabel": _noise_label(saved.get("noise", "off")),
        }

    def save_home(self, data):
        s = vs.load_settings()
        s.update({
            "model": data.get("model"),
            "language": None if data.get("spokenLanguage", "Auto-detect") == "Auto-detect"
                        else vs.LANG_CODES.get(data.get("spokenLanguage")),
            "speed": dict(vs.SPEED_CHOICES).get(data.get("speed"), 1.0),
            "outputs": data.get("outputs", []),
            "mode": data.get("mode", "file"),
            "skip_done": bool(data.get("skipDone", True)),
            "subfolders": bool(data.get("subfolders", False)),
            "speak_save": bool(data.get("speakSave", False)),
            "speakers": dict(vs.SPEAKER_CHOICES).get(data.get("speakers"), "off"),
            "chapters": bool(data.get("chapters", False)),
            "export": data.get("export") if data.get("export") in ("none", "docx", "pdf", "both") else "none",
            "word_timing": bool(data.get("wordTiming", False)),
            "subtitles": data.get("subtitles", "srt") if data.get("subtitles") in ("none", "srt", "vtt", "both") else "srt",
        })
        vs.save_settings(s)
        return True

    def set_online(self, value: bool):
        s = vs.load_settings()
        s["mode_online"] = bool(value)
        vs.save_settings(s)
        return True

    def download_model(self, name):
        MODEL_PROGRESS[name] = {"pct": 0, "err": None, "done": False}

        def worker():
            def progress(pct):
                MODEL_PROGRESS[name] = {"pct": pct, "err": None, "done": False}
            try:
                vs.download_whisper(name, progress)
                MODEL_PROGRESS[name] = {"pct": 100, "err": None, "done": True}
            except Exception as e:
                MODEL_PROGRESS[name] = {"pct": None, "err": str(e)[:300], "done": True}
        threading.Thread(target=worker, daemon=True).start()
        return True

    def get_models(self):
        return [_model_info(n, s, d) for n, s, d in vs.WHISPER_MODELS]

    def model_open_folder(self, name):
        folder = _model_dir(name)
        if not folder.exists():
            return {"ok": False, "message": f"'{name}' has no files on disk yet."}
        vs.open_path(str(folder))
        return {"ok": True}

    def model_delete(self, name):
        MODEL_PROGRESS.pop(name, None)
        folder = _model_dir(name)
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        return {"ok": not folder.exists()}

    def model_redownload(self, name):
        self.model_delete(name)
        return self.download_model(name)

    def get_model_progress(self, name):
        return MODEL_PROGRESS.get(name, {"pct": None, "err": None, "done": False})

    def pick_file(self):
        types = ("Video and audio files (" + ";".join(
            f"*{e}" for e in (".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv",
                              ".mpg", ".mpeg", ".3gp", ".mp3", ".wav", ".m4a", ".aac", ".ogg",
                              ".flac")) + ")", "All files (*.*)")
        result = self._window.create_file_dialog(webview.OPEN_DIALOG, file_types=types)
        return result[0] if result else None

    def pick_folder(self):
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        return result[0] if result else None

    def start_job(self, payload):
        s = vs.load_settings()
        mode = payload.get("mode", s.get("mode", "file"))
        online = self._online()
        vs.VOCAB = vs.load_vocab()

        if mode in ("mic", "system", "call"):
            sess = live.LiveSession(dict(s), online, mode)
            if sess.error:
                return {"ok": False, "message": sess.error}
            sid = str(uuid.uuid4())
            LIVE[sid] = sess
            title = {"mic": "Live microphone", "system": "System audio", "call": "Live call"}[mode]
            return {"ok": True, "live": True, "sid": sid, "mode": mode, "title": title,
                    "devices": sess.devices(), "outputs": [o for o in s.get("outputs", []) if o != "Original"]}

        if mode == "watch":
            folder = self.pick_folder()
            if not folder:
                return {"ok": False, "message": "No folder selected."}
            stop_event = threading.Event()
            job_id = _run_job(_with_model, s["model"], lambda m: vs.run_watch(
                Path(folder), s, m, online, stop_event=stop_event))
            WATCH_EVENTS[job_id] = stop_event
            return {"ok": True, "jobId": job_id, "title": f"Watch: {Path(folder).name}", "stoppable": True}

        if mode == "file":
            video = payload.get("path") or self.pick_file()
            if not video:
                return {"ok": False, "message": "No file selected."}
            job_id = _run_job(_with_model, s["model"], lambda m: vs.process_video(
                Path(video), s, m, online, kind="file", source=None, open_result=True))
            return {"ok": True, "jobId": job_id, "title": f"File: {Path(video).name}"}

        if mode == "folder":
            folder = payload.get("path") or self.pick_folder()
            if not folder:
                return {"ok": False, "message": "No folder selected."}
            report_dir = Path(folder)
            vids = vs.list_videos(report_dir, s.get("subfolders", False))
            skipped = [v for v in vids if s.get("skip_done", True) and vs.already_done(v)]
            todo = [v for v in vids if v not in skipped]
            if not todo:
                return {"ok": False, "message": f"{len(vids)} file(s) found - all {len(skipped)} already done."}
            items = [{"path": v, "kind": "file"} for v in todo]
            job_id = _run_job(_with_model, s["model"], lambda m: vs.run_batch(
                items, s, m, online, report_dir))
            return {"ok": True, "jobId": job_id, "title": f"Folder: {report_dir.name}"}

        if mode == "url":
            url = (payload.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                return {"ok": False, "message": "Paste a link starting with http:// or https://"}
            if not online:
                return {"ok": False, "message": "Downloading a link needs internet."}
            cfg = dict(s, url=url)
            job_id = _run_job(_with_model, s["model"], lambda m: vs._run_url_job(cfg, m, online))
            return {"ok": True, "jobId": job_id, "title": "URL: " + url[:40]}

        return {"ok": False, "message": f"Unknown mode: {mode}"}

    # ---------------------------------------------------------------- Live capture
    def live_record(self, sid, mic_name=None, sys_name=None):
        return LIVE[sid].start(mic_name, sys_name)

    def live_stop(self, sid):
        LIVE[sid].stop()
        return True

    def live_poll(self, sid, offset=0):
        s = LIVE.get(sid)
        return s.poll(offset) if s else {"events": [], "next": offset, "closed": True}

    def live_alert_words(self, sid, words):
        LIVE[sid].set_alert_words(words)
        return True

    def live_translate(self, sid, target):
        LIVE[sid].translate(target)
        return True

    def live_read(self, sid, text, lang):
        LIVE[sid].read_aloud(text, lang)
        return True

    def live_text(self, sid):
        return LIVE[sid].plain_text()

    def live_save(self, sid):
        return LIVE[sid].save()

    def live_redo(self, sid, speed=None):
        return LIVE[sid].redo(dict(vs.SPEED_CHOICES).get(speed, 1.0))

    def live_clear(self, sid):
        return LIVE[sid].clear()

    def live_close(self, sid):
        if CAPTION["sid"] == sid:
            _caption_close()
        s = LIVE.pop(sid, None)
        if s:
            s.close()
        return True

    # ---------------------------------------------------------------- Live captions overlay
    def live_caption_set(self, sid, on, lang):
        sess = LIVE[sid]
        sess.caption_set(on, lang)
        if on:
            if CAPTION["sid"] != sid:
                _caption_close()
                x, y, w, h = _caption_geometry(sess.cs)
                CAPTION["window"] = webview.create_window(
                    "captions", url=str(WEB_DIR / "caption.html"), js_api=self, x=x, y=y, width=w, height=h,
                    frameless=True, on_top=True, easy_drag=True, resizable=False, transparent=True,
                    background_color="#000000")
                CAPTION["sid"] = sid
        elif CAPTION["sid"] == sid:
            _caption_close()
        return sess.caption_settings()

    def live_caption_settings(self, sid, new=None):
        sess = LIVE[sid]
        res = sess.caption_settings(new)
        if new and CAPTION["sid"] == sid and CAPTION["window"]:
            x, y, w, h = _caption_geometry(sess.cs)
            try:
                CAPTION["window"].resize(w, h)
                CAPTION["window"].move(x, y)
            except Exception:
                pass
        return res

    def caption_state_active(self):
        sess = LIVE.get(CAPTION["sid"])
        return sess.caption_state() if sess else {"on": False, "main": "", "sub": "", "alert": False,
                                                  "settings": dict(live.CAPTION_DEFAULTS)}

    def caption_hide(self):
        sid = CAPTION["sid"]
        if sid in LIVE:
            LIVE[sid].caption_set(False)
        _caption_close()
        return True

    # ---------------------------------------------------------------- drag and drop
    def _handle_drop(self, paths):
        """Files / folders dropped on the window: a folder becomes a Folder job, each media file a File
        job (they queue). The page picks the results up with take_drops()."""
        for p in paths:
            path = Path(p)
            if path.is_dir():
                mode = "folder"
            elif path.suffix.lower() in vs.BATCH_EXTENSIONS:
                mode = "file"
            else:
                DROPS.append({"ok": False, "message": f"Not a video or audio file: {path.name}"})
                continue
            try:
                res = self.start_job({"mode": mode, "path": str(path)})
            except Exception as e:
                res = {"ok": False, "message": str(e)[:150]}
            res["mode"] = mode
            DROPS.append(res)

    def take_drops(self):
        out = list(DROPS)
        del DROPS[:len(out)]
        return out

    def stop_watch_job(self, job_id):
        ev = WATCH_EVENTS.get(job_id)
        if ev:
            ev.set()
        return True

    def cancel_job(self, job_id, only_queued=False):
        """Stop a job. Waiting in the queue: dropped. Running: stopped as soon as it next returns to
        Python code (its helper programs are ended at once). only_queued=True leaves a running job alone."""
        for i, item in enumerate(_QUEUE):
            if item[0] == job_id:
                if not _QUEUE_WAKE.acquire(blocking=False):
                    break  # the worker just took it
                _QUEUE.pop(i)
                JOBS[job_id]["lines"].append("Cancelled before it started." + chr(10))
                JOBS[job_id]["cancelled"] = True
                JOBS[job_id]["done"] = True
                return True
        ev = WATCH_EVENTS.get(job_id)
        if ev:
            ev.set()
        if only_queued or _CURRENT["job"] != job_id or JOBS.get(job_id, {}).get("done"):
            return bool(ev)
        JOBS[job_id]["cancelled"] = True
        JOBS[job_id]["lines"].append(chr(10) + "Stopping..." + chr(10))
        tid = _CURRENT["tid"]
        if tid is None:
            return False
        import ctypes
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), ctypes.py_object(JobCancelled))
        for p in list(_PROCS):
            try:   # only the job's helper programs - never e.g. an Ollama server it started
                exe = Path(str(p.args[0] if isinstance(p.args, (list, tuple)) else p.args)).stem.lower()
                if exe in ("ffmpeg", "deep-filter", "claude", "yt-dlp") and p.poll() is None:
                    p.terminate()
            except Exception:
                pass
        return True

    def get_job_log(self, job_id, offset=0):
        j = JOBS.get(job_id)
        if not j:
            return {"lines": [], "done": True}
        lines = j["lines"][offset:]
        return {"lines": lines, "done": j["done"], "nextOffset": offset + len(lines),
                "queued": _queue_position(job_id), "cancelled": bool(j.get("cancelled"))}

    def _online(self):
        s = vs.load_settings()
        return bool(s.get("mode_online", vs.internet_ok()))

    # ---------------------------------------------------------------- Voice Cleanup tab
    def get_voice_cleanup(self):
        s = vs.load_settings()
        return {
            "choices": [l for l, _ in vs.NOISE_CHOICES],
            "values": [v for _, v in vs.NOISE_CHOICES],
            "help": vs.NOISE_HELP,
            "noise": s.get("noise", "off"),
            "keepClean": bool(s.get("keep_clean", False)),
            "hasKey": bool(vs.elevenlabs_key()),
        }

    def save_voice_cleanup(self, data):
        s = vs.load_settings()
        s["noise"] = data.get("noise", "off")
        s["keep_clean"] = bool(data.get("keepClean", False))
        vs.save_settings(s)
        return True

    def save_key(self, key):
        if key and key.strip():
            vs.save_elevenlabs_key(key.strip())
        return bool(vs.elevenlabs_key())

    def start_cleanup_job(self, src_path, out_dir, noise_mode, speed=None):
        out_dir = Path(out_dir) if out_dir else Path(src_path).parent
        return _run_job(vs._run_cleanup_job, Path(src_path), out_dir, noise_mode, self._online(),
                         dict(vs.SPEED_CHOICES).get(speed, 1.0))

    def start_music_job(self, src_path, out_dir, speed=None):
        out_dir = Path(out_dir) if out_dir else Path(src_path).parent
        return _run_job(vs._run_music_job, Path(src_path), out_dir, dict(vs.SPEED_CHOICES).get(speed, 1.0))

    # ---------------------------------------------------------------- Offline Settings tab
    def get_offline_settings(self):
        s = vs.load_settings()

        def safe_list(fn):
            try:
                return fn(), None
            except Exception as e:
                return [], str(e)[:200]

        apply_offline_settings()
        ollama, ollama_err = safe_list(vs.list_ollama_models)
        lmstudio, lmstudio_err = safe_list(vs.list_lmstudio_models)
        return {
            "options": {k: s.get(k, v) for k, v in OFFLINE_DEFAULTS.items()},
            "claudeFound": bool(shutil.which("claude")),
            "ollamaModels": ollama, "ollamaErr": ollama_err, "ollamaPicked": s.get("ollama_model", ""),
            "lmstudioModels": lmstudio, "lmstudioErr": lmstudio_err,
            "lmstudioPicked": s.get("lmstudio_model", ""),
        }

    def save_offline_options(self, data):
        s = vs.load_settings()
        for k in OFFLINE_DEFAULTS:
            if k in data:
                s[k] = data[k]
        vs.save_settings(s)
        apply_offline_settings()
        return True

    def save_offline_model(self, kind, name):
        s = vs.load_settings()
        s[f"{kind}_model"] = name
        vs.save_settings(s)
        return True

    # ---------------------------------------------------------------- History tab
    def get_history(self, query=""):
        items = list(reversed(vs.load_history()))
        q = (query or "").strip().lower()

        def text_of(path):
            try:
                return Path(path).read_text(encoding="utf-8", errors="replace")
            except Exception:
                return ""

        def readable(e):
            return [f for f in e.get("files", []) if f.lower().endswith((".txt", ".md"))]

        def shown(e):  # audio-result entries list their output file too
            return e.get("files", []) if e.get("kind") in ("cleanup", "music") else readable(e)

        def matches(e):
            if not q:
                return True
            meta = f"{e.get('title', '')} {e.get('source', '')} {e.get('languages', '')}".lower()
            return q in meta or any(q in text_of(f).lower() for f in readable(e))

        out = []
        for e in items:
            if not matches(e):
                continue
            try:
                when = datetime.datetime.fromisoformat(e["time"]).strftime("%d %b %Y %H:%M")
            except Exception:
                when = e.get("time", "")
            out.append({
                "time": e.get("time"), "title": e.get("title", ""),
                "when": when, "kind": vs.KIND_LABELS.get(e.get("kind"), e.get("kind", "")),
                "languages": e.get("languages", ""), "length": vs.fmt(e.get("duration") or 0),
                "files": [{"path": f, "name": Path(f).name} for f in shown(e)],
                "details": e.get("details", ""),
                "media": _history_media(e),
                "exists": any(Path(f).exists() for f in e.get("files", [])),
            })
        return out

    def get_media_url(self, path, force_convert=False):
        """A URL the page's audio/video player can play for this recording. Formats the player can't
        handle (or a failed attempt, force_convert) are turned into a small mp3 in the cache folder."""
        p = Path(path)
        if not p.exists():
            return ""
        if not force_convert and p.suffix.lower() in _PLAYABLE:
            return _MediaServer.url_for(p)
        cache = vs.SAVE_DIR / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        key = hashlib.md5(f"{p}|{p.stat().st_mtime_ns}".encode()).hexdigest()[:16]
        out = cache / f"{p.stem[:40]}_{key}.mp3"
        if not out.exists():
            ff = shutil.which("ffmpeg")
            if not ff:
                return ""
            r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", str(p), "-vn",
                                "-ac", "1", "-b:a", "64k", str(out)], capture_output=True)
            if r.returncode != 0 or not out.exists():
                return ""
        return _MediaServer.url_for(out)

    def export_file(self, path, fmt):
        """Export a summary .md from History as Word or PDF next to it; returns {ok, path|message}."""
        import exporter
        p = Path(path)
        ch = p.with_name(re.sub(r"_summary(_[^_]+)?$", "", p.stem) + "_chapters.md")
        try:
            out = exporter.export_summary(p, fmt, ch if ch.exists() else None)
        except Exception as e:
            return {"ok": False, "message": str(e)[:150]}
        if not out:
            return {"ok": False, "message": "Nothing was exported."}
        vs.open_path(out[0], select=True)
        return {"ok": True, "path": str(out[0]), "name": out[0].name}

    def read_history_file(self, path):
        if not str(path).lower().endswith((".txt", ".md")):
            return ""
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"(Could not read file: {e})"

    def open_history_file(self, path):
        vs.open_path(path)
        return True

    def open_history_folder(self, path):
        vs.open_path(path, select=True)
        return True

    def remove_history_item(self, time_, title):
        items = vs.load_history()
        items = [x for x in items if not (x.get("time") == time_ and x.get("title") == title)]
        vs.save_history(items)
        return True

def main():
    apply_offline_settings()
    if not vs.internet_ok():
        import os
        os.environ["HF_HUB_OFFLINE"] = "1"

    api = Api()
    window = webview.create_window(
        "Cursed_Vishleshan", url=str(WEB_DIR / "index.html"), js_api=api,
        width=1180, height=800, min_size=(900, 620), background_color="#eef0f3")
    api._window = window

    def bind_drop():
        from webview.dom import DOMEventHandler

        def on_drop(e):
            files = (e.get("dataTransfer") or {}).get("files", [])
            paths = [f["pywebviewFullPath"] for f in files if f.get("pywebviewFullPath")]
            if paths:
                api._handle_drop(paths)
        window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
    window.events.loaded += bind_drop
    webview.start()


if __name__ == "__main__":
    main()
