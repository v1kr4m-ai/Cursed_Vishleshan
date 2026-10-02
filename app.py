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
import threading
import uuid
from pathlib import Path

import webview

import video_summarizer as vs

WEB_DIR = Path(__file__).with_name("web")

# Background threads write here; the page POLLS these via js_api getters instead of
# Python pushing into the page (window.evaluate_js() called from a non-GUI thread can
# deadlock pywebview's EdgeChromium backend - this avoids that class of hang entirely).
JOBS = {}             # job_id -> {"lines": [str, ...], "done": bool}
MODEL_PROGRESS = {}   # model_name -> {"pct": int|None, "err": str|None, "done": bool}
WATCH_EVENTS = {}     # job_id -> threading.Event, for the Watch mode Stop button


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

    def worker():
        with vs.PROCESSING_LOCK:
            try:
                with contextlib.redirect_stdout(_JobBuffer(job_id)):
                    target_fn(*args, **kwargs)
            except Exception as e:
                JOBS[job_id]["lines"].append(f"\n[!] {e}\n")
            finally:
                JOBS[job_id]["done"] = True
    threading.Thread(target=worker, daemon=True).start()
    return job_id


class Api:
    def __init__(self):
        self._window = None

    # ---------------------------------------------------------------- Home tab
    def get_home_data(self):
        saved = vs.load_settings()
        online0 = vs.internet_ok()
        models = [{"name": n, "size": s, "desc": d, "downloaded": vs.is_downloaded(n)}
                  for n, s, d in vs.WHISPER_MODELS]
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
            "outputChoices": vs.OUTPUT_CHOICES,
            "outputs": saved.get("outputs", vs.OUTPUT_LANGUAGES),
            "mode": saved.get("mode", "file"),
            "skipDone": bool(saved.get("skip_done", True)),
            "subfolders": bool(saved.get("subfolders", False)),
            "speakSave": bool(saved.get("speak_save", False)),
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
            "outputs": data.get("outputs", []),
            "mode": data.get("mode", "file"),
            "skip_done": bool(data.get("skipDone", True)),
            "subfolders": bool(data.get("subfolders", False)),
            "speak_save": bool(data.get("speakSave", False)),
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

    def get_model_progress(self, name):
        return MODEL_PROGRESS.get(name, {"pct": None, "err": None, "done": False})

    def pick_file(self):
        types = ("Video/Audio files (" + ";".join(
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
            return {"ok": False, "message": "Live capture lands in a future update."}

        if mode == "watch":
            folder = self.pick_folder()
            if not folder:
                return {"ok": False, "message": "No folder selected."}
            model = vs.load_whisper(s["model"])
            stop_event = threading.Event()
            job_id = _run_job(vs.run_watch, Path(folder), s, model, online, stop_event=stop_event)
            WATCH_EVENTS[job_id] = stop_event
            return {"ok": True, "jobId": job_id, "title": f"Watch: {Path(folder).name}", "stoppable": True}

        if mode == "file":
            video = self.pick_file()
            if not video:
                return {"ok": False, "message": "No file selected."}
            model = vs.load_whisper(s["model"])
            job_id = _run_job(vs.process_video, Path(video), s, model, online,
                              kind="file", source=None, open_result=True)
            return {"ok": True, "jobId": job_id, "title": f"File: {Path(video).name}"}

        if mode == "folder":
            folder = self.pick_folder()
            if not folder:
                return {"ok": False, "message": "No folder selected."}
            report_dir = Path(folder)
            vids = vs.list_videos(report_dir, s.get("subfolders", False))
            skipped = [v for v in vids if s.get("skip_done", True) and vs.already_done(v)]
            todo = [v for v in vids if v not in skipped]
            if not todo:
                return {"ok": False, "message": f"{len(vids)} file(s) found - all {len(skipped)} already done."}
            items = [{"path": v, "kind": "file"} for v in todo]
            model = vs.load_whisper(s["model"])
            job_id = _run_job(vs.run_batch, items, s, model, online, report_dir)
            return {"ok": True, "jobId": job_id, "title": f"Folder: {report_dir.name}"}

        if mode == "url":
            url = (payload.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                return {"ok": False, "message": "Paste a link starting with http:// or https://"}
            if not online:
                return {"ok": False, "message": "Downloading a link needs internet."}
            cfg = dict(s, url=url)
            model = vs.load_whisper(s["model"])
            job_id = _run_job(vs._run_url_job, cfg, model, online)
            return {"ok": True, "jobId": job_id, "title": "URL: " + url[:40]}

        return {"ok": False, "message": f"Unknown mode: {mode}"}

    def stop_watch_job(self, job_id):
        ev = WATCH_EVENTS.get(job_id)
        if ev:
            ev.set()
        return True

    def get_job_log(self, job_id, offset=0):
        j = JOBS.get(job_id)
        if not j:
            return {"lines": [], "done": True}
        lines = j["lines"][offset:]
        return {"lines": lines, "done": j["done"], "nextOffset": offset + len(lines)}

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

    def start_cleanup_job(self, src_path, out_dir, noise_mode):
        out_dir = Path(out_dir) if out_dir else Path(src_path).parent
        return _run_job(vs._run_cleanup_job, Path(src_path), out_dir, noise_mode, self._online())

    def start_music_job(self, src_path, out_dir):
        out_dir = Path(out_dir) if out_dir else Path(src_path).parent
        return _run_job(vs._run_music_job, Path(src_path), out_dir)

    # ---------------------------------------------------------------- Offline Settings tab
    def get_offline_settings(self):
        s = vs.load_settings()

        def safe_list(fn):
            try:
                return fn(), None
            except Exception as e:
                return [], str(e)[:200]

        ollama, ollama_err = safe_list(vs.list_ollama_models)
        lmstudio, lmstudio_err = safe_list(vs.list_lmstudio_models)
        return {
            "ollamaModels": ollama, "ollamaErr": ollama_err, "ollamaPicked": s.get("ollama_model", ""),
            "lmstudioModels": lmstudio, "lmstudioErr": lmstudio_err,
            "lmstudioPicked": s.get("lmstudio_model", ""),
        }

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
                "files": [{"path": f, "name": Path(f).name} for f in readable(e)],
                "exists": any(Path(f).exists() for f in e.get("files", [])),
            })
        return out

    def read_history_file(self, path):
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
    if not vs.internet_ok():
        import os
        os.environ["HF_HUB_OFFLINE"] = "1"

    api = Api()
    window = webview.create_window(
        "Cursed_Vishleshan", url=str(WEB_DIR / "index.html"), js_api=api,
        width=1180, height=800, min_size=(900, 620), background_color="#eef0f3")
    api._window = window
    webview.start()


if __name__ == "__main__":
    main()
