"""
Live capture engine (microphone / PC sound / call) - GUI-free.

Extracted from the Tkinter run_mic(): same audio feed, chunking and commit logic, but
instead of touching widgets it appends events to a list that the web UI POLLS
(never pushed - see app.py for why). One LiveSession per Live tab.
"""
import datetime
import queue
import re
import threading
import time
import wave
from collections import Counter
from pathlib import Path

import video_summarizer as vs

SR = vs.SR

CAPTION_DEFAULTS = {"opacity": 0.85, "position": "Bottom", "width": 70, "font": "Segoe UI",
                    "size": 22, "lines": 2, "fg": "#ffffff", "bg": "#000000",
                    "show_original": False, "no_bg": False, "speak": False}
CAP_ORIGINAL = "Original (as spoken)"
CAP_FAST_EN = "English (fast, offline)"


class LiveSession:
    def __init__(self, cfg, online, source):
        self.cfg, self.online, self.source = cfg, online, source
        self.call = source == "call"
        self.use_mic = source in ("mic", "call")
        self.use_sys = source in ("system", "call")
        self.src_name = {"mic": "Microphone", "system": "System audio", "call": "Call"}[source]
        self.events = []                       # polled by the page
        self._last_prov = {}
        saved = vs.load_settings()
        self.cs = dict(CAPTION_DEFAULTS)
        self.cs.update({k: v for k, v in saved.get("captions", {}).items() if k in CAPTION_DEFAULTS})
        self.cap = {"on": False, "lang": saved.get("caption_lang", CAP_FAST_EN), "done": [],
                    "prov": {}, "orig": "", "last_who": None, "alert_until": 0.0}
        self.cap_q, self.cap_llm = queue.Queue(), None
        self.lock, self.model_lock = threading.Lock(), threading.Lock()
        self.S = {"model": None, "recording": False, "entries": [], "finalize": False,
                  "closing": False, "busy": False, "translations": {}, "alerts": [],
                  "streams": [], "alert_words": [], "pa": None, "ready": False}
        self.error = None
        self.sd = self.pyaudio = self.np = self.nr = None
        self.mic_devices, self.sys_devices = [], []
        self.player = vs.SpeechPlayer(online, on_status=lambda s: self._emit("speech", s))
        self.chans = []
        self._setup()

    # ------------------------------------------------------------ setup
    def _emit(self, *ev):
        if ev[0] == "prov":
            self.cap["prov"][ev[1]] = (ev[2], ev[4])
        if ev[0] == "prov":   # skip repeats of the same provisional text for a channel
            if self._last_prov.get(ev[1]) == ev[2:4]:
                return
            self._last_prov[ev[1]] = ev[2:4]
        self.events.append(list(ev))

    def _setup(self):
        try:
            import numpy as np
            self.np = np
            if self.use_mic:
                import sounddevice as sd
                self.sd = sd
            if self.use_sys:
                import pyaudiowpatch as pyaudio
                self.pyaudio = pyaudio
        except ImportError:
            libs = [l for l, need in (("sounddevice", self.use_mic), ("PyAudioWPatch", self.use_sys)) if need]
            self.error = f"This needs:  pip install {' '.join(libs)}"
            return
        np = self.np
        if self.cfg.get("noise", "off") != "off":
            try:
                import noisereduce as nr
                self.nr = nr
            except ImportError:
                pass

        def new_ch(key, label):
            return {"key": key, "label": label, "parts": [], "pending": np.zeros(0, np.float32),
                    "offset": 0.0, "last_len": 0, "all": [], "level": 0.0, "rate": SR,
                    "t0": None, "received": 0}
        if self.use_mic:
            self.chans.append(new_ch("mic", "You" if self.call else None))
            self.mic_devices = [("Default microphone", None)]
            try:
                api = self.sd.default.hostapi
                for i, d in enumerate(self.sd.query_devices()):
                    if d["max_input_channels"] > 0 and (api is None or d["hostapi"] == api):
                        self.mic_devices.append((d["name"], i))
            except Exception:
                pass
        if self.use_sys:
            self.chans.append(new_ch("sys", "Them" if self.call else None))
            try:
                pa = self.pyaudio
                self.S["pa"] = pa.PyAudio()
                wasapi = self.S["pa"].get_host_api_info_by_type(pa.paWASAPI)
                default_out = self.S["pa"].get_device_info_by_index(wasapi["defaultOutputDevice"])["name"]
                loops = sorted(self.S["pa"].get_loopback_device_info_generator(),
                               key=lambda d: default_out not in d["name"])
                self.sys_devices = [(d["name"], d["index"]) for d in loops]
            except Exception as e:
                self._emit("error", f"Could not list PC sound devices: {e}")
            if not self.sys_devices:
                self.sys_devices = [("(no PC sound device found)", None)]
        threading.Thread(target=self._worker, daemon=True).start()
        threading.Thread(target=self._cap_worker, daemon=True).start()

    def devices(self):
        return {"mic": [n for n, _ in self.mic_devices], "sys": [n for n, _ in self.sys_devices],
                "call": self.call, "source": self.source, "error": self.error}

    # ------------------------------------------------------------ audio input
    def _feed(self, ch, chunk):
        np = self.np
        if ch["rate"] != SR:
            n = int(len(chunk) * SR / ch["rate"])
            if n <= 0:
                return
            chunk = np.interp(np.linspace(0, len(chunk) - 1, n), np.arange(len(chunk)),
                              chunk).astype(np.float32)
        with self.lock:
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

    def _pad_to_now(self, ch):
        np = self.np
        with self.lock:
            if ch["t0"] is None:
                return
            gap = int((time.time() - ch["t0"]) * SR) - ch["received"]
            if gap > 0:
                z = np.zeros(gap, np.float32)
                ch["parts"].append(z)
                ch["all"].append(z)
                ch["received"] += gap

    def _open_stream(self, ch, mic_name, sys_name):
        np, sd = self.np, self.sd
        if ch["key"] == "sys":
            idx = dict(self.sys_devices).get(sys_name)
            if idx is None:
                raise RuntimeError("No PC sound device found.")
            return _Loopback(self, ch, idx)
        dev = dict(self.mic_devices).get(mic_name)
        cb = lambda indata, f, t, s_: self._feed(ch, indata[:, 0].astype(np.float32))
        ch["rate"] = SR
        try:
            return sd.InputStream(samplerate=SR, channels=1, dtype="float32", device=dev,
                                  blocksize=int(SR * 0.1), callback=cb)
        except Exception:
            ch["rate"] = int(sd.query_devices(dev, "input")["default_samplerate"])
            return sd.InputStream(samplerate=ch["rate"], channels=1, dtype="float32", device=dev,
                                  blocksize=int(ch["rate"] * 0.1), callback=cb)

    # ------------------------------------------------------------ recognition
    def _cut(self, ch, sec):
        with self.lock:
            n = int(sec * SR)
            ch["pending"] = ch["pending"][n:]
            ch["offset"] += n / SR
            ch["last_len"] = 0

    def _check_alerts(self, text, t, who):
        low = text.lower()
        hits = [w for w in self.S["alert_words"] if w.lower() in low]
        if hits:
            self.S["alerts"].append({"t": t, "who": who, "words": hits, "text": text})
            self.cap["alert_until"] = time.time() + 1.5
            self._emit("alert", hits, t, who, len(self.S["alerts"]))

    def _commit(self, ch, segs, code, audio, upto):
        text = " ".join(s.text.strip() for s in segs)
        t = ch["offset"] + segs[0].start
        self.S["entries"].append({"t": t, "lang": code, "text": text, "who": ch["label"],
                                  "dur": max(segs[-1].end - segs[0].start, 0.5)})
        self._emit("commit", ch["key"], text, code, ch["label"], vs.lang_name(code))
        self._check_alerts(text, t, ch["label"])
        self._caption_commit(ch, segs, code, audio, upto, text)

    # ------------------------------------------------------------ captions
    def _cap_add(self, text, who, original="", speak_lang=None):
        cap = self.cap
        if self.call and who and who != cap["last_who"]:
            text = f"{who}: {text}"
        cap["last_who"] = who
        cap["done"].append(text)
        cap["orig"] = original
        if self.cs["speak"] and speak_lang:
            self.player.say(re.sub(r"^(You|Them): ", "", text), speak_lang)

    def _caption_commit(self, ch, segs, code, audio, upto, text):
        cap = self.cap
        if not cap["on"]:
            return
        cap["prov"].pop(ch["key"], None)
        if cap["lang"] == CAP_ORIGINAL:
            self._cap_add(text, ch["label"])
        elif cap["lang"] == CAP_FAST_EN:
            piece = audio[int(segs[0].start * SR): int(upto * SR)]
            try:
                with self.model_lock:
                    tsegs, _ = self.S["model"].transcribe(piece, language=code, task="translate", beam_size=1,
                                                          vad_filter=True, condition_on_previous_text=False)
                    tr = " ".join(s.text.strip() for s in tsegs if s.text.strip())
            except Exception:
                tr = ""
            self._cap_add(tr or text, ch["label"], text, "English")
        else:
            self.cap_q.put((text, cap["lang"], ch["label"]))

    def _cap_worker(self):   # AI translation of captions into any language
        while not self.S["closing"]:
            try:
                text, target, who = self.cap_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if self.cap_q.qsize() > 2:   # falling behind: merge what's waiting
                more = [text]
                while not self.cap_q.empty():
                    more.append(self.cap_q.get_nowait()[0])
                text = " ".join(more)
            if self.cap_llm is None:
                self.cap_llm = next(iter(vs.text_llms(self.online)), False)
            if not self.cap_llm:
                self._emit("speech", f"No AI translator for {target} captions (needs Claude Code, "
                                     f"Ollama or LM Studio) - showing the original words")
                self._cap_add(text, who)
                continue
            try:
                tr = self.cap_llm[1]("You translate live subtitles. Output ONLY the translation, nothing else.",
                                     f"Translate into {target}:\n{text}{vs.vocab_note()}")
                self._cap_add(vs.strip_thinking(tr).strip(), who, text, target)
            except Exception as e:
                self._emit("speech", f"Caption translation failed: {str(e)[:80]}")
                self._cap_add(text, who)

    def caption_set(self, on, lang=None):
        cap = self.cap
        if lang and lang != cap["lang"]:
            cap["lang"] = lang
            cap["done"].clear()
            self._save_caption_settings()
        cap["on"] = bool(on)
        return True

    def caption_settings(self, new=None):
        if new:
            for k, v in new.items():
                if k in CAPTION_DEFAULTS:
                    self.cs[k] = v
            self._save_caption_settings()
        return dict(self.cs, lang=self.cap["lang"])

    def _save_caption_settings(self):
        s = vs.load_settings()
        s.update(captions=dict(self.cs), caption_lang=self.cap["lang"])
        vs.save_settings(s)

    def caption_state(self):
        cap = self.cap
        main = " ".join(cap["done"][-40:])
        if cap["lang"] == CAP_ORIGINAL:
            provs = [f"{w}: {x}" if (self.call and w) else x for (x, w) in cap["prov"].values() if x]
            main = (main + " " + " ".join(provs)).strip()
        sub = cap["orig"] if self.cs["show_original"] and cap["lang"] != CAP_ORIGINAL else ""
        return {"on": cap["on"], "main": main, "sub": sub, "settings": dict(self.cs),
                "alert": time.time() < cap["alert_until"]}

    def clear_captions(self):
        self.cap.update(done=[], prov={}, last_who=None, orig="")

    def _process(self, ch, audio, final):
        np = self.np
        dur = len(audio) / SR
        lang = self.cfg["language"]
        mine = [e for e in self.S["entries"] if e["who"] == ch["label"]]
        if not lang and dur < 3 and mine:
            lang = mine[-1]["lang"]   # too short to detect reliably: keep this speaker's language
        if self.nr is not None:
            try:
                audio = self.nr.reduce_noise(y=audio, sr=SR, stationary=True,
                                             prop_decrease=0.8).astype(np.float32)
            except Exception:
                pass
        m = self.S["model"]
        with self.model_lock:
            segs, info = m.transcribe(
                audio, language=lang, beam_size=(5 if final else vs.LIVE_BEAM_SIZE),
                vad_filter=True, condition_on_previous_text=False, **vs.vocab_kwargs(m))
            segs = [s for s in segs if s.text.strip() and not vs.is_hallucination(s.text, s)]
        code = lang or info.language
        if not segs:
            if final:
                self._cut(ch, dur)
            elif dur > 4:
                self._cut(ch, dur - 1.0)   # drop the silence, keep the last second
            self._emit("prov", ch["key"], "", None, ch["label"])
            return
        if final or dur - segs[-1].end >= vs.LIVE_SILENCE_COMMIT_SEC:
            self._commit(ch, segs, code, audio, dur)
            self._cut(ch, dur)
            self._emit("prov", ch["key"], "", code, ch["label"])
        elif (dur >= vs.LIVE_COMMIT_SEC or dur >= vs.LIVE_MAX_PENDING_SEC) and len(segs) > 1:
            self._commit(ch, segs[:-1], code, audio, segs[-2].end)
            self._cut(ch, segs[-2].end)
            self._emit("prov", ch["key"], segs[-1].text.strip(), code, ch["label"])
        elif dur >= vs.LIVE_MAX_PENDING_SEC:
            self._commit(ch, segs, code, audio, segs[-1].end)
            self._cut(ch, segs[-1].end)
            self._emit("prov", ch["key"], "", code, ch["label"])
        else:
            self._emit("prov", ch["key"], " ".join(s.text.strip() for s in segs), code, ch["label"])

    def _take(self, ch):
        np = self.np
        with self.lock:
            if ch["parts"]:
                ch["pending"] = np.concatenate([ch["pending"]] + ch["parts"])
                ch["parts"] = []
            return ch["pending"]

    def _worker(self):
        np, S = self.np, self.S
        try:
            S["model"] = vs.load_whisper(self.cfg["model"])
        except BaseException as e:
            self._emit("error", f"Could not load the Whisper model: {e}")
            return
        S["ready"] = True
        self._emit("ready", self.cfg["model"])
        while not S["closing"]:
            try:
                if S["finalize"] and not S["recording"]:
                    for ch in self.chans:
                        pending = self._take(ch)
                        if len(pending) / SR >= 0.3:
                            self._process(ch, pending, final=True)
                        with self.lock:
                            ch["offset"] += len(ch["pending"]) / SR
                            ch["pending"] = np.zeros(0, np.float32)
                    end = max(ch["offset"] for ch in self.chans)   # line the channels up again
                    for ch in self.chans:
                        pad = int((end - ch["offset"]) * SR)
                        with self.lock:
                            if pad > 0:
                                ch["all"].append(np.zeros(pad, np.float32))
                            ch["offset"] = end
                    S["finalize"] = False
                    self._emit("stopped")
                    continue
                did = False
                for ch in self.chans:
                    pending = self._take(ch)
                    if S["recording"] and len(pending) / SR >= 1.0 and len(pending) != ch["last_len"]:
                        ch["last_len"] = len(pending)
                        self._process(ch, pending, final=False)
                        did = True
                if not did:
                    time.sleep(0.12)
            except Exception as e:
                self._emit("error", f"Recognition error: {e}")
                time.sleep(1)

    # ------------------------------------------------------------ controls
    def start(self, mic_name=None, sys_name=None):
        S = self.S
        if S["recording"] or not S["ready"]:
            return {"ok": False, "message": "Not ready yet." if not S["ready"] else "Already recording."}
        opened = []
        try:
            for ch in self.chans:
                opened.append(self._open_stream(ch, mic_name, sys_name))
            now = time.time()
            for ch in self.chans:
                ch["t0"], ch["received"] = now, 0
            for s_ in opened:
                s_.start()
        except Exception as e:
            for s_ in opened:
                try:
                    s_.close()
                except Exception:
                    pass
            return {"ok": False, "message": f"Could not start capturing: {e}"}
        S["streams"], S["recording"] = opened, True
        return {"ok": True}

    def stop(self):
        S = self.S
        if not S["recording"]:
            return
        S["recording"] = False
        for s_ in S["streams"]:
            try:
                s_.stop()
                s_.close()
            except Exception:
                pass
        for ch in self.chans:
            self._pad_to_now(ch)
            ch["t0"] = None
            ch["level"] = 0
        S["finalize"] = True

    def poll(self, offset):
        new = self.events[offset:]
        return {"events": new, "next": offset + len(new), "recording": self.S["recording"],
                "finalizing": self.S["finalize"], "ready": self.S["ready"], "busy": self.S["busy"],
                "hasEntries": bool(self.S["entries"]), "speaking": bool(self.player.busy),
                "levels": {ch["key"]: (min(100, ch["level"] * 400) if self.S["recording"] else 0)
                           for ch in self.chans},
                "language": self.lang_summary()}

    def set_alert_words(self, words):
        self.S["alert_words"] = [w.strip() for w in words.split(",") if w.strip()]

    def lang_summary(self):
        tot = Counter()
        for e in self.S["entries"]:
            tot[e["lang"]] += e["dur"]
        total = sum(tot.values()) or 1
        return ", ".join(f"{vs.lang_name(c)} ({d / total:.0%})" for c, d in tot.most_common())

    def _main_lang(self):
        tot = Counter()
        for e in self.S["entries"]:
            tot[e["lang"]] += e["dur"]
        return vs.lang_name(tot.most_common(1)[0][0]) if tot else "English"

    def plain_text(self):
        es = sorted(self.S["entries"], key=lambda e: e["t"])
        return vs.stamped_from_entries(es) if self.call else " ".join(e["text"] for e in es)

    def _whisper_english(self):
        np, lines = self.np, []
        for ch in self.chans:
            with self.lock:
                audio = np.concatenate(ch["all"]) if ch["all"] else np.zeros(0, np.float32)
            if not len(audio):
                continue
            with self.model_lock:
                segs, _ = self.S["model"].transcribe(audio, language=self.cfg["language"], task="translate",
                                                     vad_filter=True, **vs.vocab_kwargs(self.S["model"]))
                for s in segs:
                    if s.text.strip():
                        who = f"{ch['label']}: " if ch["label"] else ""
                        lines.append((s.start, f"[{vs.fmt(s.start)}] {who}{s.text.strip()}"))
        return "\n".join(l for _, l in sorted(lines))

    def translate(self, target):
        stamped = vs.stamped_from_entries(self.S["entries"])
        self.S["busy"] = True

        def job():
            try:
                text, by = vs.translate_transcript(stamped, target, self.online)
                if not text and target == "English":
                    text, by = self._whisper_english(), "Whisper"
            except Exception as e:
                text, by = None, str(e)
            self.S["busy"] = False
            if text:
                self.S["translations"][target] = (text, by)
            self._emit("translated", target, text, by)
        threading.Thread(target=job, daemon=True).start()

    def read_aloud(self, text, lang):
        if self.player.busy:
            self.player.stop()
            return
        if not (text or "").strip():
            text, lang = " ".join(e["text"] for e in sorted(self.S["entries"], key=lambda e: e["t"])), self._main_lang()
        if text.strip():
            import re
            self.player.say(re.sub(r"\b(You|Them): ", "", text), lang)

    def save(self):
        np, S = self.np, self.S
        vs.SAVE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base = vs.SAVE_DIR / f"{self.source}_{stamp}"
        with self.lock:
            tracks = [np.concatenate(ch["all"]) if ch["all"] else np.zeros(0, np.float32) for ch in self.chans]
        n = max(len(t) for t in tracks) if tracks else 0
        audio = np.zeros(n, np.float32)
        for t in tracks:
            audio[:len(t)] += t
        if len(tracks) > 1:
            audio /= len(tracks)
        duration = n / SR
        title = f"{self.src_name} recording"
        lang_line = f"Languages spoken: {self.lang_summary()}"
        note = ""
        if S["alerts"]:
            note = "\n===== ALERTS =====\n" + "\n".join(
                f"[{vs.fmt(a['t'])}] {(a['who'] + ': ') if a['who'] else ''}{', '.join(a['words'])}  ->  {a['text']}"
                for a in S["alerts"]) + "\n"
        files = [Path(f"{base}_transcript.txt")]
        vs.write_transcript(files[0], title, lang_line, duration, vs.stamped_from_entries(S["entries"]), note)
        for target, (text, by) in S["translations"].items():
            f = Path(f"{base}_transcript_{vs.safe_name(target)}.txt")
            vs.write_transcript(f, title, f"{lang_line}  |  Translated to {target} by {by}", duration, text)
            files.append(f)
        wav = Path(f"{base}_audio.wav")
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        files.append(wav)
        vs.add_history(self.source, f"{title} {datetime.datetime.now():%d %b %Y %H:%M}", self.src_name,
                       self.lang_summary(), duration, files)
        vs.open_path(vs.SAVE_DIR)
        return {"dir": str(vs.SAVE_DIR), "name": base.name}

    def clear(self):
        np, S = self.np, self.S
        if S["recording"]:
            return False
        with self.lock:
            for ch in self.chans:
                ch.update(all=[], parts=[], offset=0.0, last_len=0, received=0,
                          pending=np.zeros(0, np.float32))
            S.update(entries=[], translations={}, alerts=[])
        self.clear_captions()
        return True

    def close(self):
        self.S["closing"] = True
        self.stop()
        self.player.stop()
        if self.S["pa"]:
            try:
                self.S["pa"].terminate()
            except Exception:
                pass


class _Loopback:
    """PC-sound (WASAPI loopback) stream via PyAudioWPatch."""
    def __init__(self, sess, ch, index):
        np, pa = sess.np, sess.pyaudio
        info = sess.S["pa"].get_device_info_by_index(index)
        nch = max(1, int(info["maxInputChannels"]))
        ch["rate"] = int(info["defaultSampleRate"])

        def pcb(in_data, frame_count, time_info, status_):
            a = np.frombuffer(in_data, np.int16).reshape(-1, nch).mean(axis=1)
            sess._feed(ch, (a / 32768.0).astype(np.float32))
            return (None, pa.paContinue)

        self.s = sess.S["pa"].open(format=pa.paInt16, channels=nch, rate=ch["rate"], input=True,
                                   input_device_index=index, frames_per_buffer=int(ch["rate"] * 0.1),
                                   stream_callback=pcb)

    def start(self):
        self.s.start_stream()

    def stop(self):
        self.s.stop_stream()

    def close(self):
        self.s.close()
