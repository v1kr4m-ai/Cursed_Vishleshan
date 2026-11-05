"""
Hindi (and 16 other languages) speech with the XTTS-v2 voice from the Cursed_Ai project.

Nothing is copied: this runs Cursed_Ai's own Python environment and its xtts_run.py script as a separate process
(train/speech/tts/env, trainTool/scripts, train/speech/models/XTTS-v2), fully offline. GUI-free.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

DEFAULT_DIR = r"D:\Claude\In_Progress\02_Web_Apps\Cursed_Ai"

# Whisper-style language code (what the rest of this app uses) -> XTTS language id
LANGS = {"hi": "hi", "en": "en", "ar": "ar", "zh": "zh-cn", "es": "es", "fr": "fr", "de": "de", "it": "it",
         "pt": "pt", "pl": "pl", "tr": "tr", "ru": "ru", "nl": "nl", "cs": "cs", "hu": "hu", "ko": "ko", "ja": "ja"}
_MAX = {"ar": 160, "zh-cn": 80, "ja": 70, "ko": 90, "ru": 180, "cs": 180}   # characters per piece the model reads well


def paths(settings):
    root = Path(settings.get("xtts_dir") or DEFAULT_DIR)
    return {"root": root,
            "python": root / "train" / "speech" / "tts" / "env" / "Scripts" / "python.exe",
            "script": root / "trainTool" / "scripts" / "xtts_run.py",
            "model": root / "train" / "speech" / "models" / "XTTS-v2"}


def missing(settings):
    """What is not where it should be (an empty list = ready to use)."""
    p = paths(settings)
    out = []
    if not p["root"].exists():
        return [f"the Cursed_Ai folder ({p['root']})"]
    if not p["python"].exists():
        out.append("its Python environment (train/speech/tts/env)")
    if not p["script"].exists():
        out.append("trainTool/scripts/xtts_run.py")
    if not all((p["model"] / f).exists() for f in ("model.pth", "dvae.pth", "mel_stats.pth", "config.json")):
        out.append("the XTTS-v2 model (train/speech/models/XTTS-v2)")
    return out


def available(settings):
    return not missing(settings)


def code_for(lang_code):
    """XTTS language id for a language code, or None when XTTS has no voice for it (Urdu, Tamil, ...)."""
    return LANGS.get((lang_code or "").lower())


_HI = ("शून्य एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस बीस "
       "इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस छत्तीस सैंतीस अड़तीस उनतालीस चालीस "
       "इकतालीस बयालीस तैंतालीस चौवालीस पैंतालीस छियालीस सैंतालीस अड़तालीस उनचास पचास इक्यावन बावन तिरपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ "
       "इकसठ बासठ तिरसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर छिहत्तर सतहत्तर अठहत्तर उनासी अस्सी "
       "इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी नवासी नब्बे इक्यानवे बानवे तिरानवे चौरानवे पंचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे").split()


def _hindi_number(n):
    """Whole number as Hindi words (up to 99 crore); the model cannot read digits in Hindi."""
    if n < 100:
        return _HI[n]
    parts = []
    for unit, word in ((10_000_000, "करोड़"), (100_000, "लाख"), (1000, "हज़ार"), (100, "सौ")):
        q, n = divmod(n, unit)
        if q:
            parts.append(f"{_HI[q] if q < 100 else _hindi_number(q)} {word}")
    if n:
        parts.append(_HI[n])
    return " ".join(parts) or _HI[0]


def prepare_text(text, lang):
    """XTTS cannot expand numbers in Hindi (it fails on any digit), so write them out as words."""
    if lang != "hi":
        return text
    text = text.translate(str.maketrans("०१२३४५६७८९", "0123456789"))
    text = re.sub(r"(?<=\d),(?=\d{2,3}(?!\d))", "", text)             # 1,500 and 1,25,000 -> plain numbers
    text = re.sub(r"(\d+)[.](\d+)", lambda m: f"{_hindi_number(int(m.group(1)))} दशमलव " +
                  " ".join(_HI[int(c)] for c in m.group(2)), text)     # 3.5 -> तीन दशमलव पाँच
    text = re.sub(r"(?<=\d):(?=\d)", " ", text)                        # 10:30 -> 10 30
    text = re.sub(r"\d+", lambda m: _hindi_number(int(m.group(0))) if len(m.group(0)) < 10 else " ".join(_HI[int(c)] for c in m.group(0)), text)
    return text


def split_text(text, lang):
    """The text in pieces of at most ~230 characters (less for some languages): at sentence ends, joined while they
    fit, long sentences cut at commas then spaces. XTTS cuts or garbles longer pieces."""
    mx = _MAX.get(lang, 230)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?।॥؟…])\s+|(?<=[。！？])", " ".join((text or "").split())) if s.strip()]

    def cut(s):
        if len(s) <= mx:
            return [s]
        at = [m.end() for m in re.finditer(r"[,;:،，、]\s*", s) if m.end() < len(s)]
        i = at[-1] if at and mx * 0.3 <= at[-1] <= mx else s.rfind(" ", 0, mx)
        if i < mx * 0.3:
            i = mx
        return [p for p in [s[:i].strip()] + cut(s[i:].strip()) if p]

    out = []
    for piece in [p for s in sentences for p in cut(s)]:
        if out and len(out[-1]) + 1 + len(piece) <= mx:
            out[-1] += " " + piece
        else:
            out.append(piece)
    return out


def speak(items, settings, log=print):
    """items: [{'text', 'language' (XTTS id), 'output' (.wav path)}]. Loads the model once for all of them.
    Returns the list of files that were made."""
    problems = missing(settings)
    if problems:
        log("  [xtts] Not available - missing " + ", ".join(problems))
        return []
    p = paths(settings)
    ref = (settings.get("xtts_reference") or "").strip()
    speaker = (settings.get("xtts_speaker") or "").strip()
    job_items = []
    for it in items:
        txt = prepare_text(it["text"], it["language"])
        d = {"text": txt, "parts": split_text(txt, it["language"]), "language": it["language"],
             "output": str(it["output"])}
        if ref and Path(ref).exists():
            d["referenceAudio"] = ref
        elif speaker:
            d["speaker"] = speaker
        job_items.append(d)
    tmp = Path(tempfile.mkdtemp(prefix="vidsum_xtts_"))
    proc = None
    try:
        job = tmp / "job.json"
        job.write_text(json.dumps({"modelDir": str(p["model"]), "items": job_items}, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        proc = subprocess.Popen([str(p["python"]), str(p["script"]), str(job)], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env,
                                cwd=str(p["root"]), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("[xtts]") and "warning" not in line.lower():
                log("  " + line)
        proc.wait()
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
        shutil.rmtree(tmp, ignore_errors=True)
    return [Path(i["output"]) for i in items if Path(i["output"]).exists()]


def speak_one(text, lang_id, out_wav, settings, log=print):
    """One text -> one wav. Returns (ok, info)."""
    made = speak([{"text": text, "language": lang_id, "output": out_wav}], settings, log)
    return (True, f"XTTS voice ({lang_id}, offline)") if made else (False, "XTTS could not make the speech.")
