"""
Cursed_Vishleshan - pywebview host + JS bridge.

All transcription/translation/summarization/voice-cleanup/history logic lives in
video_summarizer.py, untouched. This file only bridges the web UI (web/) to it -
no processing logic belongs here.

Stage 1: shell + Home tab (model picker with real download progress, language/source
picker, settings persistence). Job dispatch (Start) is a stub until Stage 3.
"""
import json
import threading
from pathlib import Path

import webview

import video_summarizer as vs

WEB_DIR = Path(__file__).with_name("web")


def _noise_label(value: str) -> str:
    return dict((v, l) for l, v in vs.NOISE_CHOICES).get(value, "Off")


class Api:
    def __init__(self):
        self.window = None

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
        def worker():
            def progress(pct):
                self._push("onModelProgress", name, pct, None)
            try:
                vs.download_whisper(name, progress)
                self._push("onModelProgress", name, 100, None)
            except Exception as e:
                self._push("onModelProgress", name, None, str(e)[:300])
        threading.Thread(target=worker, daemon=True).start()
        return True

    def pick_file(self):
        types = ("Video/Audio files (" + ";".join(
            f"*{e}" for e in (".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv",
                              ".mpg", ".mpeg", ".3gp", ".mp3", ".wav", ".m4a", ".aac", ".ogg",
                              ".flac")) + ")", "All files (*.*)")
        result = self.window.create_file_dialog(webview.OPEN_DIALOG, file_types=types)
        return result[0] if result else None

    def pick_folder(self):
        result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        return result[0] if result else None

    def start_job(self, payload):
        # Stage 3 wires real jobs (file/folder/url/watch/mic/system/call) here.
        return {"ok": False, "message": "Job dispatch lands in the next update - "
                                        "this stage is the Home tab shell only."}

    # ---------------------------------------------------------------- plumbing
    def _push(self, fn, *args):
        if not self.window:
            return
        try:
            self.window.evaluate_js(f"{fn}({', '.join(json.dumps(a) for a in args)})")
        except Exception:
            pass


def main():
    if not vs.internet_ok():
        import os
        os.environ["HF_HUB_OFFLINE"] = "1"

    api = Api()
    window = webview.create_window(
        "Cursed_Vishleshan", url=str(WEB_DIR / "index.html"), js_api=api,
        width=1180, height=800, min_size=(900, 620), background_color="#eef0f3")
    api.window = window
    webview.start()


if __name__ == "__main__":
    main()
