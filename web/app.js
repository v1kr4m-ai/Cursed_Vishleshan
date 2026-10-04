// Cursed_Vishleshan - Home tab logic. Talks to Python via window.pywebview.api.*
// Falls back to mock data when previewed as a plain HTML file (no pywebview bridge),
// so the design can be checked in an ordinary browser too.

const SOURCE_MODES = [
  { id: "file", label: "Video / audio file" },
  { id: "folder", label: "Folder (batch)" },
  { id: "url", label: "YouTube / link" },
  { id: "watch", label: "Watch folder" },
  { id: "mic", label: "Live microphone" },
  { id: "system", label: "System audio" },
  { id: "call", label: "Call (mic + PC)" },
];

const MOCK_HOME = {
  historyCount: 12,
  gpu: "cuda",
  models: [
    { name: "tiny", size: "~75 MB", desc: "Fastest, lowest accuracy", downloaded: true },
    { name: "base", size: "~145 MB", desc: "Very fast, basic accuracy", downloaded: true },
    { name: "small", size: "~485 MB", desc: "Good balance of speed and accuracy", downloaded: false, onDisk: true, diskMB: 261 },
    { name: "medium", size: "~1.5 GB", desc: "More accurate, slower", downloaded: false },
    { name: "large-v3-turbo", size: "~1.6 GB", desc: "Near-best accuracy, fast", downloaded: false },
    { name: "large-v3", size: "~3.1 GB", desc: "Best accuracy, slowest", downloaded: false },
    { name: "distil-large-v3", size: "~1.5 GB", desc: "English audio only", downloaded: false },
  ],
  selectedModel: "small",
  spokenLanguage: "Auto-detect",
  speedChoices: ["Normal", "85%", "75%", "65%", "50%"],
  speed: "Normal",
  speakerChoices: ["Off", "Auto-detect", "2 speakers", "3 speakers", "4 speakers", "5 speakers", "6 speakers"],
  speakers: "Off",
  preset: "Custom",
  outputDir: "",
  spokenChoices: ["Auto-detect", "English", "Hindi", "Urdu", "French", "German", "Spanish"],
  outputChoices: ["Original", "English", "Hindi", "Urdu", "French", "German", "Spanish"],
  outputs: ["Original", "English"],
  mode: "file",
  skipDone: true,
  subtitles: "srt",
  export: "none",
  chapters: false,
  wordTiming: false,
  subfolders: false,
  speakSave: false,
  onlineReal: true,
  onlinePref: true,
  noiseLabel: "Studio AI - Demucs + DeepFilterNet (Offline)",
};

const MOCK_CLEANUP = {
  choices: ["Off", "Light filter (Offline)", "Strong filter (Offline)",
    "Studio AI - Demucs + DeepFilterNet (Offline)", "ElevenLabs Voice Isolator (Online)"],
  values: ["off", "light", "strong", "studio", "online"],
  help: {
    off: "No cleanup.", light: "Quick, gentle hiss/hum reduction.",
    strong: "Quick, heavy noise reduction.",
    studio: "Demucs isolates voices, then DeepFilterNet removes noise.",
    online: "ElevenLabs Voice Isolator - needs an API key.",
  },
  noise: "studio", keepClean: false, hasKey: false,
};
const MOCK_OFFLINE = {
  options: { backend_order: ["ollama", "claude"], ollama_url: "http://localhost:11434", lmstudio_url: "http://localhost:1234",
    ollama_num_ctx: 16384, send_frames: false, max_frames: 6, timeout_min: 30, chunk_chars: 12000, translate_chunk_chars: 4000 },
  claudeFound: true,
  ollamaModels: ["phi4:latest", "llama3.2:latest", "qwen2.5:7b"], ollamaErr: null, ollamaPicked: "phi4:latest",
  lmstudioModels: [], lmstudioErr: "LM Studio server not running.", lmstudioPicked: "",
};
const MOCK_HISTORY = [
  { time: "2026-09-20T10:00:00", title: "Team meeting", media: { path: "C:/fake/meeting.mp4", kind: "video" }, when: "20 Sep 2026 10:00", kind: "Video",
    languages: "English", length: "00:12:30",
    files: [{ path: "C:/fake/meeting_transcript.txt", name: "meeting_transcript.txt" }], exists: true },
];

const _mockTicks = {};
const _mockDone = new Set(), _mockGone = new Set();

function callApi(name, ...args) {
  if (window.pywebview && window.pywebview.api && window.pywebview.api[name]) {
    return window.pywebview.api[name](...args);
  }
  console.warn("[mock]", name, args);
  if (name === "get_home_data") return Promise.resolve(MOCK_HOME);
  if (name === "get_voice_cleanup") return Promise.resolve(MOCK_CLEANUP);
  if (name === "get_offline_settings") return Promise.resolve(MOCK_OFFLINE);
  if (name === "get_history") return Promise.resolve(MOCK_HISTORY);
  if (name === "read_history_file") return Promise.resolve(["Transcript of: meeting.mp4", "", "===== TIMESTAMPED =====",
    "[00:00:00] Speaker 1: Good morning everyone.", "[00:00:05] Speaker 2: Thanks. The budget is on track.",
    "[00:00:11] Speaker 1: Understood.", "", "===== PLAIN TEXT =====", "Good morning everyone."].join(String.fromCharCode(10)));
  if (name === "get_media_url") return Promise.resolve("");
  if (name === "pick_file") return Promise.resolve("C:/fake/song.mp3");
  if (name === "pick_folder") return Promise.resolve("C:/fake/out");
  if (name === "start_job") return Promise.resolve({
    ok: true, jobId: "mock-job-" + Math.random().toString(36).slice(2),
    title: "Mock " + args[0].mode + " job", stoppable: args[0].mode === "watch",
    ...(["mic", "system", "call"].includes(args[0].mode) ? { live: true, sid: "mock-live", mode: args[0].mode,
      devices: { mic: ["Default microphone"], sys: [], call: false, source: args[0].mode }, outputs: ["English"] } : {}),
  });
  if (name === "live_poll") {
    const n = (_mockTicks["l"] = (_mockTicks["l"] || 0) + 1);
    const ev = n === 1 ? [["ready", "tiny"]] : n === 3 ? [["commit", "mic", "hello from the mock", "en", null, "English"]] : [];
    return Promise.resolve({ events: ev, next: args[1] + ev.length, recording: false, finalizing: false,
      ready: true, busy: false, hasEntries: n >= 3, speaking: false, levels: { mic: 30 }, language: "English (100%)" });
  }
  if (name === "live_caption_settings") return Promise.resolve({ opacity: 0.85, position: "Bottom", width: 70,
    font: "Segoe UI", size: 22, lines: 2, fg: "#ffffff", bg: "#000000", show_original: false, no_bg: false,
    speak: false, lang: "English (fast, offline)" });
  if (name === "get_models") return Promise.resolve(MOCK_HOME.models.map((m) => {
    const ok = (m.downloaded && !_mockGone.has(m.name)) || _mockDone.has(m.name);
    return { ...m, downloaded: ok, onDisk: ok || m.onDisk, diskMB: ok ? 300 : m.diskMB };
  }));
  if (name === "download_model" || name === "model_redownload") { _mockDone.add(args[0]); _mockGone.delete(args[0]); return Promise.resolve(true); }
  if (name === "model_delete") { _mockGone.add(args[0]); _mockDone.delete(args[0]); return Promise.resolve({ ok: true }); }
  if (name === "model_open_folder") return Promise.resolve({ ok: true });
  if (name === "get_model_progress") {
    const key = "m:" + args[0];
    const n = (_mockTicks[key] = (_mockTicks[key] || 0) + 1);
    const pct = Math.min(100, n * 25);
    return Promise.resolve({ pct, err: null, done: pct >= 100 });
  }
  if (name === "get_job_log") {
    const [jobId, offset] = args;
    const key = "j:" + jobId;
    const n = (_mockTicks[key] = (_mockTicks[key] || 0) + 1);
    const lines = n <= 3 ? [`mock log line ${n}\n`] : [];
    return Promise.resolve({ lines, done: n > 3, nextOffset: offset + lines.length });
  }
  if (name.startsWith("start_")) return Promise.resolve("mock-job-" + Math.random().toString(36).slice(2));
  return Promise.resolve({ ok: true, mock: true });
}

let state = null;

function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._h);
  toast._h = setTimeout(() => t.classList.remove("show"), 2600);
}

// ---------------------------------------------------------------- card deck
// A stack of cards: hover fans it out into a scrollable list, click pins it open for choosing.
const ICONS = {
  folder: '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
  refresh: '<svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 4v5h-5"/></svg>',
  redownload: '<svg viewBox="0 0 24 24"><path d="M12 4v11"/><path d="M7 11l5 5 5-5"/><path d="M5 20h14"/></svg>',
  trash: '<svg viewBox="0 0 24 24"><path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/></svg>',
  up: '<svg viewBox="0 0 24 24"><path d="M6 15l6-6 6 6"/></svg>',
  down: '<svg viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>',
};

function createDeck(host, o) {
  if (o.hostClass) host.classList.add(o.hostClass);
  host.innerHTML = `<div class="deck ${o.deckClass || ""}"><div class="deck-card">
      <div class="deck-head"><h2>${o.title}</h2>
        <span class="deck-tools" data-t="tools"></span><span class="deck-count" data-t="count"></span></div>
      <div class="deck-sub" data-t="sub"></div>
      <div class="deck-list" data-t="list"></div></div></div>`;
  const deck = host.querySelector(".deck");
  const q = (n) => host.querySelector(`[data-t="${n}"]`);
  const isOpen = () => deck.classList.contains("open");
  const setOpen = (v) => {
    if (v) document.querySelectorAll(".deck.open").forEach((d) => { if (d !== deck) { d.classList.remove("open"); d.parentElement.classList.remove("deckhost-open"); } });
    deck.classList.toggle("open", v);
    host.classList.toggle("deckhost-open", v);   // lifts this whole deck above the decks below it
  };

  // header click toggles; a click anywhere else on a collapsed card opens it
  host.querySelector(".deck-card").addEventListener("click", (e) => {
    if (e.target.closest(".ic")) return;
    if (e.target.closest(".deck-head")) setOpen(!isOpen());
    else if (!isOpen()) setOpen(true);
  });
  document.addEventListener("click", (e) => { if (isOpen() && !deck.contains(e.target)) setOpen(false); });

  (o.tools || []).forEach((t) => {
    const b = document.createElement("button");
    b.className = "ic"; b.title = t.title; b.innerHTML = ICONS[t.icon];
    b.addEventListener("click", (e) => { e.stopPropagation(); t.run(b); });
    q("tools").appendChild(b);
  });

  if (o.body) q("list").appendChild(o.body());

  function render() {
    q("count").textContent = o.count ? o.count() : "";
    q("sub").textContent = o.sub ? o.sub() : "";
    if (o.body) return;
    const items = o.items();
    const list = q("list");
    const scroll = list.scrollTop;
    list.innerHTML = "";
    for (const it of items) {
      const row = document.createElement("div");
      row.className = "modelrow" + (it.selected ? " selected-row" : "");
      if (it.title) row.title = it.title;
      const status = it.pct != null ? `<span class="statuscircle downloading">${it.pct}%</span>`
        : it.selected ? `<span class="statuscircle selected">&#10003;</span>`
        : it.ready ? `<span class="statuscircle downloaded">&#10003;</span>` : `<span class="statuscircle"></span>`;
      row.innerHTML = `
        <div class="modelrow-left">
          <span class="modelicon">${it.badge}</span>
          <div class="modelrow-text">
            <div class="modelrow-name">${it.name}${it.tag ? `<span class="modelrow-tag ${it.tagWarn ? "warn" : ""}">${it.tag}</span>` : ""}</div>
            <div class="modelrow-size">${it.sub || ""}</div>
          </div>
        </div>
        <span class="rowactions"></span>${status}`;
      const acts = row.querySelector(".rowactions");
      (it.actions || []).forEach((a) => {
        const b = document.createElement("button");
        b.className = "ic " + (a.cls || ""); b.title = a.title; b.innerHTML = ICONS[a.icon];
        b.addEventListener("click", (e) => { e.stopPropagation(); o.onAction(it.id, a.id, b); });
        acts.appendChild(b);
      });
      row.addEventListener("click", () => { if (isOpen()) o.onSelect(it.id); });
      list.appendChild(row);
    }
    list.scrollTop = scroll;
  }
  return { deck, render, open: () => setOpen(true), close: () => setOpen(false) };
}

// ---------------------------------------------------------------- Whisper model deck (Home)
let modelDeck = null;

// the selected model only counts when it is fully downloaded
function activeModel() {
  const m = state.models.find((x) => x.name === state.selectedModel);
  return m && m.downloaded ? m.name : null;
}

function renderModels() {
  if (!modelDeck) {
    modelDeck = createDeck(document.getElementById("modelDeck"), {
      title: "Speech-to-text model",
      tools: [{ icon: "refresh", title: "Re-check all models on disk", run: refreshModels }],
      count: () => state.models.filter((m) => m.downloaded).length + "/" + state.models.length,
      sub: () => activeModel() ? `In use: ${activeModel()}` : "No usable model - open and pick or download one",
      items: () => state.models.map((m) => {
        const incomplete = m.onDisk && !m.downloaded && !m._downloading;
        const actions = [{ id: "refresh", icon: "refresh", title: "Re-check this model" }];
        if (m.onDisk) actions.unshift({ id: "folder", icon: "folder", title: "Open the model's folder" });
        if (m.onDisk || m.downloaded) actions.push({ id: "redownload", icon: "redownload", title: "Delete and download again" });
        if (m.onDisk) actions.push({ id: "delete", icon: "trash", title: "Delete this model from disk", cls: "warn" });
        return {
          id: m.name, badge: m.name.slice(0, 2), name: m.name, title: m.desc,
          tag: incomplete ? "incomplete" : "", tagWarn: incomplete,
          sub: m.size + (m.diskMB ? ` · ${m.diskMB} MB on disk` : ""),
          selected: m.name === state.selectedModel && m.downloaded,
          ready: m.downloaded, pct: m._downloading ? (m._progress || 0) : null, actions,
        };
      }),
      onSelect: (name) => onModelClick(state.models.find((m) => m.name === name)),
      onAction: (name, act, btn) => onModelAction(state.models.find((m) => m.name === name), act, btn),
    });
  }
  modelDeck.render();
}

function onModelClick(m) {
  if (m.downloaded) {
    state.selectedModel = m.name;
    renderModels(); renderStats(); persistHome();
    return;
  }
  if (m._downloading) return;
  startModelDownload(m, m.onDisk ? "Finishing" : "Downloading");
}

function startModelDownload(m, verb) {
  m._downloading = true; m._progress = 0;
  renderModels();
  toast(`${verb} ${m.name}...`);
  pollModelProgress(m);
}

async function refreshModels(btn) {
  if (btn) btn.classList.add("spin");
  const fresh = await callApi("get_models");
  for (const f of fresh) {
    const m = state.models.find((x) => x.name === f.name);
    if (m) Object.assign(m, f);
  }
  if (!state.models.some((m) => m.name === state.selectedModel && m.downloaded)) {
    const first = state.models.find((m) => m.downloaded);
    state.selectedModel = first ? first.name : null;
    persistHome();
  }
  if (btn) btn.classList.remove("spin");
  renderModels(); renderStats();
  toast("Model list refreshed");
}

async function onModelAction(m, act, btn) {
  if (act === "refresh") return refreshModels(btn);
  if (act === "folder") {
    const r = await callApi("model_open_folder", m.name);
    if (!r.ok) toast(r.message);
    return;
  }
  if (act === "delete") {
    if (!confirm(`Delete the '${m.name}' model from disk?\n\nIt will have to be downloaded again to use it.`)) return;
    await callApi("model_delete", m.name);
    Object.assign(m, { downloaded: false, onDisk: false, diskMB: 0, _downloading: false });
    if (state.selectedModel === m.name) {
      const first = state.models.find((x) => x.downloaded);
      state.selectedModel = first ? first.name : null;
      persistHome();
    }
    renderModels(); renderStats();
    toast(`${m.name} deleted`);
    return;
  }
  if (act === "redownload") {
    if (!confirm(`Delete '${m.name}' and download it again?`)) return;
    Object.assign(m, { downloaded: false, onDisk: false, diskMB: 0 });
    await callApi("model_redownload", m.name);
    startModelDownload(m, "Re-downloading");
  }
}

// Polling, not a push from Python: window.evaluate_js() called from a background
// thread can hang pywebview's EdgeChromium backend, so Python only ever buffers
// progress and the page pulls it on an interval via the normal js_api call path.
function pollModelProgress(m) {
  const tick = async () => {
    const p = await callApi("get_model_progress", m.name);
    if (p.err) {
      m._downloading = false;
      toast(`${m.name} failed: ${p.err}`);
      renderModels();
      return;
    }
    m._progress = p.pct;
    if (p.done) {
      m._downloading = false;
      await refreshModels();
      const fresh = state.models.find((x) => x.name === m.name);
      if (fresh && fresh.downloaded) {
        state.selectedModel = m.name; persistHome(); renderModels(); renderStats();
        toast(`${m.name} downloaded`);
      }
      return;
    }
    renderModels();
    setTimeout(tick, 500);
  };
  tick();
}

function renderSpoken() {
  const sel = document.getElementById("spokenSelect");
  sel.innerHTML = state.spokenChoices.map((c) =>
    `<option ${c === state.spokenLanguage ? "selected" : ""}>${c}</option>`).join("");
  sel.onchange = () => { state.spokenLanguage = sel.value; persistHome(); };
  const sp = document.getElementById("speedSelect");
  sp.innerHTML = state.speedChoices.map((c) => `<option ${c === state.speed ? "selected" : ""}>${c}</option>`).join("");
  sp.onchange = () => { state.speed = sp.value; persistHome(); };
  const sk = document.getElementById("speakerSelect");
  sk.innerHTML = state.speakerChoices.map((c) => `<option ${c === state.speakers ? "selected" : ""}>${c}</option>`).join("");
  sk.onchange = () => { state.speakers = sk.value; persistHome(); };
}

// Output languages: same stack-of-cards behaviour as the model deck (hover peeks, click pins open)
let outputDeck = null;

function buildOutputBody() {
  const body = document.createElement("div");
  body.innerHTML = `
    <p class="deck-hint">For every language ticked you get a translated transcript and a summary in it.
      <b>Original</b> keeps the language as spoken.</p>
    <div class="checklist">${state.outputChoices.map((name) => `
      <label class="checkrow"><input type="checkbox" data-out="${name}" ${state.outputs.includes(name) ? "checked" : ""}> ${name}</label>`).join("")}
    </div>
    <label class="checkrow" style="margin-top:8px;"><input type="checkbox" id="speakSave"> Also save each translation as spoken audio</label>`;
  body.querySelectorAll("[data-out]").forEach((cb) => cb.addEventListener("change", () => {
    const name = cb.dataset.out;
    state.outputs = cb.checked ? [...state.outputs, name] : state.outputs.filter((n) => n !== name);
    outputDeck.render();
    persistHome();
  }));
  const speak = body.querySelector("#speakSave");
  speak.checked = state.speakSave;
  speak.addEventListener("change", () => { state.speakSave = speak.checked; persistHome(); });
  return body;
}

function renderOutputs() {
  if (!outputDeck) {
    outputDeck = createDeck(document.getElementById("outputDeck"), {
      title: "Output languages", deckClass: "fold", hostClass: "fold",
      count: () => state.outputs.length,
      sub: () => state.outputs.length ? state.outputs.join(", ") : "None ticked - tick at least one",
      body: buildOutputBody,
    });
  }
  outputDeck.render();
}

function renderSources() {
  const grid = document.getElementById("sourceGrid");
  grid.innerHTML = SOURCE_MODES.map((s) =>
    `<div class="sourcecard ${s.id === state.mode ? "selected" : ""}" data-mode="${s.id}">${s.label}</div>`
  ).join("");
  grid.querySelectorAll(".sourcecard").forEach((el) => el.addEventListener("click", () => {
    state.mode = el.dataset.mode;
    renderSources();
    persistHome();
  }));
  document.getElementById("urlRow").style.display = state.mode === "url" ? "flex" : "none";
  document.getElementById("clipRow").style.display = ["file", "url"].includes(state.mode) ? "flex" : "none";
  document.getElementById("folderOpts").style.display = ["folder", "watch"].includes(state.mode) ? "flex" : "none";
  // live capture has its own pipeline: no extras, speed or speaker options there
  const live = ["mic", "system", "call"].includes(state.mode);
  document.querySelector(".extrasrow").style.display = live ? "none" : "flex";
  document.getElementById("speedSelect").parentElement.style.display = live ? "none" : "";
  document.getElementById("speakerSelect").parentElement.style.display = live ? "none" : "";
  document.getElementById("skipDone").checked = state.skipDone;
  const chk = (id, key) => {
    const el = document.getElementById(id);
    el.checked = !!state[key];
    el.onchange = () => { state[key] = el.checked; persistHome(); };
  };
  chk("chaptersChk", "chapters");
  chk("wordsChk", "wordTiming");
  const expSel = document.getElementById("exportSelect");
  expSel.value = state.export || "none";
  expSel.onchange = () => { state.export = expSel.value; persistHome(); };
  const subsSel = document.getElementById("subsSelect");
  subsSel.value = state.subtitles || "srt";
  subsSel.onchange = () => { state.subtitles = subsSel.value; persistHome(); };
  document.getElementById("subfolders").checked = state.subfolders;
}

function shortClean(label) {
  return (label || "Off").replace(/ \((Offline|Online)\)$/, "").replace(/ - .*/, "");
}

function renderStats() {
  document.getElementById("statModels").textContent =
    state.models.filter((m) => m.downloaded).length + "/" + state.models.length;
  document.getElementById("statGpu").textContent = state.gpu === "cuda" ? "GPU · CUDA" : "CPU";
  document.getElementById("statModel").textContent = activeModel() || "none";
  document.getElementById("statClean").textContent = shortClean(state.noiseLabel);

  const dot = document.getElementById("netDot");
  dot.classList.toggle("ok", !!state.onlineReal);
  dot.title = state.onlineReal ? "Internet connected" : "Offline";
  document.getElementById("onlineToggle").checked = !!state.onlinePref;
  document.getElementById("onlineLabel").textContent =
    state.onlinePref ? "Prefers online tools" : "Prefers offline tools";
}

function wireStats() {
  const toggle = document.getElementById("onlineToggle");
  toggle.addEventListener("change", () => {
    state.onlinePref = toggle.checked;
    document.getElementById("onlineLabel").textContent =
      state.onlinePref ? "Prefers online tools" : "Prefers offline tools";
    callApi("set_online", state.onlinePref);
  });
  document.getElementById("statGpuCard").addEventListener("click", () => {
    toast(state.gpu === "cuda"
      ? "Transcription runs on the NVIDIA GPU (CUDA) - fastest."
      : "No usable NVIDIA GPU found - transcription runs on the CPU (slower).");
  });
  document.getElementById("statHistoryCard").addEventListener("click", () => activateTab("history"));
  document.getElementById("statCleanCard").addEventListener("click", () => activateTab("cleanup"));
  // re-check what is on disk, then open the model list
  document.getElementById("statModelCard").addEventListener("click", async (e) => {
    e.stopPropagation();
    await refreshModels();
    document.getElementById("modelDeck").scrollIntoView({ behavior: "smooth", block: "start" });
    if (modelDeck) modelDeck.open();
  });
}

function persistHome() {
  return callApi("save_home", {
    model: state.selectedModel,
    spokenLanguage: state.spokenLanguage,
    speed: state.speed,
    speakers: state.speakers,
    preset: state.preset,
    outputDir: state.outputDir,
    outputs: state.outputs,
    mode: state.mode,
    skipDone: document.getElementById("skipDone").checked,
    subtitles: state.subtitles,
    export: state.export,
    chapters: state.chapters,
    wordTiming: state.wordTiming,
    subfolders: document.getElementById("subfolders").checked,
    speakSave: state.speakSave,
  });
}

// ---------------------------------------------------------------- tabs (fixed + one per running tool)
const TAB_LOADERS = { cleanup: loadCleanupTab, offline: () => { loadOfflineTab(); loadAppSettings(); }, history: () => loadHistoryTab() };

async function loadAppSettings() {
  const a = await callApi("get_app_settings");
  if (!a || typeof a.notify === "undefined") return;
  const n = document.getElementById("notifyChk"), t = document.getElementById("trayChk");
  n.checked = a.notify; t.checked = a.tray;
  const save = () => callApi("save_app_settings", { notify: n.checked, tray: t.checked });
  n.onchange = t.onchange = save;
  document.getElementById("trayNote").textContent = a.trayAvailable ? "" :
    "No tray icon: install the 'pystray' package (pip install pystray) to enable notifications and the tray.";
}

// tell Python whether the window is in front, so it only sends a notification when you are not looking
(function reportFocus() {
  const send = () => callApi("report_focus", document.hasFocus() && document.visibilityState === "visible");
  window.addEventListener("focus", send); window.addEventListener("blur", send);
  document.addEventListener("visibilitychange", send);
  setTimeout(send, 1500);
})();
const TOOL_TABS = {};
let toolSeq = 0;

function activateTab(id) {
  document.querySelectorAll("#pillnav .pill").forEach((b) => b.classList.toggle("active", b.dataset.tab === id));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + id));
  if (TAB_LOADERS[id]) TAB_LOADERS[id]();
  window.scrollTo(0, 0);
}

function wireNav() {
  document.getElementById("pillnav").addEventListener("click", (e) => {
    const pill = e.target.closest(".pill");
    if (!pill) return;
    if (e.target.closest(".x")) closeToolTab(pill.dataset.tab);
    else activateTab(pill.dataset.tab);
  });
}

// Every tool run (file / folder / link / watch / live / cleanup / music) opens its own tab up
// in the nav bar, so it can be switched to without scrolling.
// One tab per feature (key): a second run of the same feature reuses that tab and its job
// panels stack inside it; the jobs themselves queue in Python and start one after another.
function openToolTab(title, key) {
  const existing = key && Object.values(TOOL_TABS).find((t) => t.key === key);
  if (existing) { activateTab(existing.id); return existing; }
  const id = "tool" + (++toolSeq);
  const pill = document.createElement("button");
  pill.className = "pill tool"; pill.dataset.tab = id;
  pill.innerHTML = '<span class="dot"></span><span class="t"></span><i class="x" title="Close tab">&times;</i>';
  pill.querySelector(".t").textContent = title;
  pill.title = title;
  document.getElementById("toolTabs").appendChild(pill);
  const view = document.createElement("main");
  view.className = "view toolview"; view.id = "view-" + id;
  document.querySelector(".page").appendChild(view);
  const tab = {
    id, key, view, pill, onClose: [], pending: 0,
    jobStarted() { tab.pending++; pill.classList.remove("done"); },
    jobDone() { if (--tab.pending <= 0) pill.classList.add("done"); },
    setOnClose(fn) { tab.onClose.push(fn); },
    close() { closeToolTab(id); },
  };
  TOOL_TABS[id] = tab;
  activateTab(id);
  return tab;
}

function closeToolTab(id) {
  const tab = TOOL_TABS[id];
  if (!tab) return;
  tab.onClose.forEach((fn) => fn());
  tab.pill.remove(); tab.view.remove();
  delete TOOL_TABS[id];
  activateTab("home");
}

// ---------------------------------------------------------------- job log panels
// Polling, not a push from Python - see pollModelProgress() above for why.
function addJobPanel(tab, jobId, title) {
  const containerEl = tab.view;
  tab.jobStarted();
  // closing the tab drops jobs still waiting (and stops a watch) but lets a running job finish
  tab.setOnClose(() => callApi("cancel_job", jobId, true));
  const wrap = document.createElement("div");
  wrap.className = "joblog";
  wrap.innerHTML = `<div class="joblog-head"><span>${title}</span>
      <span class="joblog-actions">
        <button class="ghostbtn tiny danger" data-a="stop" title="Stop this job (a waiting job is dropped from the queue)">Stop</button>
        <span class="joblog-status">Running...</span>
      </span></div>
    <pre class="joblog-body"></pre>`;
  containerEl.prepend(wrap);
  const statusEl = wrap.querySelector(".joblog-status");
  const bodyEl = wrap.querySelector(".joblog-body");
  const stopBtn = wrap.querySelector('[data-a="stop"]');
  let stopping = false;
  stopBtn.addEventListener("click", async () => {
    stopBtn.disabled = true; stopping = true;
    statusEl.textContent = "Stopping...";
    await callApi("cancel_job", jobId);
  });

  let offset = 0;
  const tick = async () => {
    const r = await callApi("get_job_log", jobId, offset);
    if (r.lines.length) {
      bodyEl.textContent += r.lines.join("");
      bodyEl.scrollTop = bodyEl.scrollHeight;
      offset = r.nextOffset;
    }
    if (r.done) {
      statusEl.textContent = r.cancelled ? "Stopped" : "Done";
      statusEl.classList.add("done");
      stopBtn.style.display = "none";
      tab.jobDone();
      wrap.classList.add("finished");
      return;
    }
    if (!stopping) statusEl.textContent = r.queued ? `Queued - ${r.queued} ahead` : "Running...";
    setTimeout(tick, 500);
  };
  tick();
}

// ---------------------------------------------------------------- Voice Cleanup tab

// Cleanup and music jobs run inside the Voice Cleanup tab: their panels stack in the Queue card.
function cuQueue() {
  const list = document.getElementById("cuQueueList"), empty = document.getElementById("cuQueueEmpty");
  let pending = 0;
  empty.style.display = "none";
  document.getElementById("cuQueueClear").onclick = () => {
    list.querySelectorAll(".joblog.finished").forEach((w) => w.remove());
    empty.style.display = list.children.length ? "none" : "";
  };
  return { view: list, jobStarted() { pending++; }, jobDone() { pending--; }, setOnClose() {} };
}
let cleanupState = null;

let noiseDeck = null;

async function loadCleanupTab() {
  cleanupState = await callApi("get_voice_cleanup");
  renderNoiseDeck();
  document.getElementById("keepCleanChk").checked = cleanupState.keepClean;
  document.getElementById("keepCleanChk").onchange = (e) => {
    cleanupState.keepClean = e.target.checked;
    saveCleanup();
  };
  document.getElementById("saveKeyBtn").onclick = async () => {
    const key = document.getElementById("keyInput").value;
    const ok = await callApi("save_key", key);
    cleanupState.hasKey = ok;
    document.getElementById("keyStatus").textContent = ok ? "Key saved." : "No key saved.";
    document.getElementById("keyInput").value = "";
  };
  buildFileTool("cuTool", "Clean up", async (src, outDir, speed) =>
    callApi("start_cleanup_job", src, outDir, cleanupState.noise, speed, document.getElementById("cuVideoChk").checked));
  buildFileTool("muTool", "Extract music", async (src, outDir, speed) => {
    const stems = [...document.querySelectorAll("#stemRow input:checked")].map((i) => i.dataset.stem);
    return callApi("start_music_job", src, outDir, speed, stems.length ? stems : ["instrumental"]);
  });
}

function noiseParts(label) {
  const m = label.match(/^(.*) \((Offline|Online)\)$/);
  return m ? { name: m[1], net: m[2] } : { name: label, net: "" };
}

function renderNoiseDeck() {
  const cs = cleanupState;
  if (!noiseDeck) {
    noiseDeck = createDeck(document.getElementById("noiseDeck"), {
      title: "Cleanup mode",
      count: () => noiseParts(cs.choices[cs.values.indexOf(cs.noise)] || "Off").net,
      sub: () => "In use: " + noiseParts(cs.choices[cs.values.indexOf(cs.noise)] || "Off").name,
      items: () => cs.choices.map((label, i) => {
        const p = noiseParts(label);
        return { id: cs.values[i], badge: p.name.slice(0, 2), name: p.name, tag: p.net,
                 sub: (cs.help[cs.values[i]] || "").split(":")[0].slice(0, 60),
                 title: cs.help[cs.values[i]], selected: cs.values[i] === cs.noise, ready: false };
      }),
      onSelect: (v) => {
        cs.noise = v; renderNoiseDeck(); saveCleanup();
        if (state) { state.noiseLabel = cs.choices[cs.values.indexOf(v)]; renderStats(); }
      },
      onAction: () => {},
    });
  }
  noiseDeck.render();
  document.getElementById("noiseHelp").textContent = cs.help[cs.noise] || "";
  document.getElementById("keyRow").style.display = cs.noise === "online" ? "flex" : "none";
  document.getElementById("keyStatus").textContent = cs.hasKey ? "Key saved - paste a new one to change it." : "No key saved.";
}

function saveCleanup() {
  callApi("save_voice_cleanup", { noise: cleanupState.noise, keepClean: cleanupState.keepClean });
}

function buildFileTool(containerId, verb, onRun) {
  const el = document.getElementById(containerId);
  const tool = { src: null, outDir: null };
  el.innerHTML = `
    <div class="pickrow"><button class="ghostbtn" data-a="src">Browse file...</button>
      <span class="pickpath muted" data-t="src">(none selected)</span></div>
    <div class="pickrow"><button class="ghostbtn" data-a="out">Browse folder...</button>
      <span class="pickpath muted" data-t="out">(same folder as the file)</span></div>
    <div class="pickrow"><select class="select" data-a="speed" title="Slow the saved audio down (pitch kept) - handy for picking out fast lyrics">${(state.speedChoices || []).map((c) => `<option>Speed: ${c}</option>`).join("")}</select></div>
    <button class="startbtn small" data-a="run" disabled>${verb}&ensp;&#9654;</button>
    <div class="joblogs"></div>`;
  const runBtn = el.querySelector('[data-a="run"]');
  el.querySelector('[data-a="src"]').addEventListener("click", async () => {
    const path = await callApi("pick_file");
    if (path) {
      tool.src = path;
      const t = el.querySelector('[data-t="src"]');
      t.textContent = path.split(/[\\/]/).pop();
      t.classList.remove("muted");
      runBtn.disabled = false;
    }
  });
  el.querySelector('[data-a="out"]').addEventListener("click", async () => {
    const path = await callApi("pick_folder");
    if (path) {
      tool.outDir = path;
      const t = el.querySelector('[data-t="out"]');
      t.textContent = path;
      t.classList.remove("muted");
    }
  });
  runBtn.addEventListener("click", async () => {
    const jobId = await onRun(tool.src, tool.outDir, el.querySelector('[data-a="speed"]').value.replace("Speed: ", ""));
    const name = tool.src.split(/[\\/]/).pop();
    addJobPanel(cuQueue(), jobId, `${verb}: ${name}`, false);
  });
}

// ---------------------------------------------------------------- Offline Settings tab
const ENGINES = {
  claude: { name: "Claude Code", hint: "needs internet + the `claude` CLI" },
  ollama: { name: "Ollama", hint: "local models" },
  lmstudio: { name: "LM Studio", hint: "local models" },
};
let offlineData = null;
let engineOrder = [], engineOn = {};

async function loadOfflineTab() {
  const d = offlineData = await callApi("get_offline_settings");
  const o = d.options;
  engineOn = { claude: false, ollama: false, lmstudio: false };
  o.backend_order.forEach((b) => { engineOn[b] = true; });
  engineOrder = [...o.backend_order, ...Object.keys(ENGINES).filter((b) => !o.backend_order.includes(b))];
  renderEngines();

  const $ = (id) => document.getElementById(id);
  $("ollamaUrl").value = o.ollama_url; $("lmstudioUrl").value = o.lmstudio_url;
  $("ollamaCtx").value = o.ollama_num_ctx; $("sendFrames").checked = !!o.send_frames;
  $("maxFrames").value = o.max_frames; $("timeoutMin").value = o.timeout_min;
  $("chunkChars").value = o.chunk_chars; $("translateChunk").value = o.translate_chunk_chars;
  fillOfflineSelect("ollama", d.ollamaModels, d.ollamaPicked, d.ollamaErr);
  fillOfflineSelect("lmstudio", d.lmstudioModels, d.lmstudioPicked, d.lmstudioErr);

  ["ollamaUrl", "lmstudioUrl", "ollamaCtx", "sendFrames", "maxFrames", "timeoutMin", "chunkChars", "translateChunk"]
    .forEach((id) => { $(id).onchange = saveOffline; });
  $("ollamaRefresh").onclick = async () => { await saveOffline(); loadOfflineTab(); };
  $("lmstudioRefresh").onclick = async () => { await saveOffline(); loadOfflineTab(); };
}

function renderEngines() {
  const box = document.getElementById("engineList");
  let n = 0;
  box.innerHTML = engineOrder.map((id, i) => {
    const e = ENGINES[id];
    const on = engineOn[id];
    const hint = id === "claude" ? (offlineData.claudeFound ? "CLI found" : "CLI not found") : e.hint;
    return `<div class="engine ${on ? "" : "off"}" data-id="${id}">
      <span class="n">${on ? ++n : "-"}</span>
      <span class="name">${e.name}<span class="hint">${hint}</span></span>
      <button class="ic" data-m="up" title="Higher priority" ${i === 0 ? "disabled" : ""}>${ICONS.up}</button>
      <button class="ic" data-m="down" title="Lower priority" ${i === engineOrder.length - 1 ? "disabled" : ""}>${ICONS.down}</button>
      <label class="checkrow"><input type="checkbox" data-m="on" ${on ? "checked" : ""}> Use</label>
    </div>`;
  }).join("");
  box.querySelectorAll(".engine").forEach((row) => {
    const id = row.dataset.id;
    row.querySelector('[data-m="on"]').addEventListener("change", (e) => {
      engineOn[id] = e.target.checked; renderEngines(); saveOffline();
    });
    ["up", "down"].forEach((dir) => row.querySelector(`[data-m="${dir}"]`).addEventListener("click", () => {
      const i = engineOrder.indexOf(id), j = dir === "up" ? i - 1 : i + 1;
      if (j < 0 || j >= engineOrder.length) return;
      [engineOrder[i], engineOrder[j]] = [engineOrder[j], engineOrder[i]];
      renderEngines(); saveOffline();
    }));
  });
}

function saveOffline() {
  const $ = (id) => document.getElementById(id);
  const num = (id, lo, fallback) => Math.max(lo, parseInt($(id).value, 10) || fallback);
  return callApi("save_offline_options", {
    backend_order: engineOrder.filter((b) => engineOn[b]),
    ollama_url: $("ollamaUrl").value.trim() || "http://localhost:11434",
    lmstudio_url: $("lmstudioUrl").value.trim() || "http://localhost:1234",
    ollama_num_ctx: num("ollamaCtx", 2048, 16384), send_frames: $("sendFrames").checked,
    max_frames: num("maxFrames", 1, 6), timeout_min: num("timeoutMin", 1, 30),
    chunk_chars: num("chunkChars", 2000, 12000), translate_chunk_chars: num("translateChunk", 1000, 4000),
  });
}

function fillOfflineSelect(kind, models, picked, err) {
  const sel = document.getElementById(kind + "Select");
  const AUTO = "(auto - first available)";
  sel.innerHTML = [AUTO, ...models].map((m) =>
    `<option ${m === (picked || AUTO) ? "selected" : ""}>${m}</option>`).join("");
  sel.onchange = () => callApi("save_offline_model", kind, sel.value === AUTO ? "" : sel.value);
  document.getElementById(kind + "Status").textContent =
    err ? "Not reachable: " + err.slice(0, 90) : `${models.length} model(s) found.`;
}

// ---------------------------------------------------------------- History tab
let historyItems = [];
let historySelected = null;

async function loadHistoryTab(query) {
  historyItems = await callApi("get_history", query || "");
  renderHistoryList();
  document.getElementById("historySearch").oninput = (e) => loadHistoryTab(e.target.value);
}

function renderHistoryList() {
  const list = document.getElementById("historyList");
  if (!historyItems.length) {
    list.innerHTML = `<div class="historyempty">Nothing processed yet.</div>`;
    return;
  }
  list.innerHTML = historyItems.map((e, i) => `
    <div class="historyrow ${e.exists ? "" : "missing"}" data-i="${i}">
      <div>
        <div class="historyrow-title">${e.title || "(untitled)"}</div>
        <div class="historyrow-meta">${e.kind} - ${e.languages} - ${e.length}</div>
      </div>
      <div class="historyrow-when">${e.when}</div>
    </div>`).join("");
  list.querySelectorAll(".historyrow").forEach((row) =>
    row.addEventListener("click", () => selectHistory(+row.dataset.i)));
  if (historyItems.length) selectHistory(0);
}

function selectHistory(i) {
  historySelected = historyItems[i];
  document.querySelectorAll(".historyrow").forEach((r, idx) => r.classList.toggle("selected", idx === i));
  const sel = document.getElementById("historyFileSelect");
  sel.innerHTML = historySelected.files.map((f) => `<option>${f.name}</option>`).join("");
  sel.onchange = showHistoryFile;
  setupHistoryPlayer();
  showHistoryFile();
}

async function showHistoryFile() {
  const sel = document.getElementById("historyFileSelect");
  const f = historySelected.files.find((x) => x.name === sel.value) || historySelected.files[0];
  const text = (f ? await callApi("read_history_file", f.path) : "") || historySelected.details || "";
  renderHistoryText(text);
  const isSummary = !!f && /_summary[^\\/]*\.md$/i.test(f.name);
  document.getElementById("historyWordBtn").style.display = isSummary ? "" : "none";
  updateEditButtons(f, text);
  document.getElementById("historyPdfBtn").style.display = isSummary ? "" : "none";
}

// ---- editing: Edit / Save / Cancel / Revert, Rename speakers, Rebuild outputs
let editing = false;
const $h = (id) => document.getElementById(id);

function currentHistoryFile() {
  const sel = $h("historyFileSelect");
  return historySelected && (historySelected.files.find((x) => x.name === sel.value) || historySelected.files[0]);
}

function setEditing(on) {
  editing = on;
  $h("historyEdit").style.display = on ? "" : "none";
  $h("historyText").style.display = on ? "none" : "";
  $h("historySaveBtn").style.display = on ? "" : "none";
  $h("historyCancelBtn").style.display = on ? "" : "none";
  $h("historyEditBtn").style.display = on ? "none" : ($h("historyEditBtn").dataset.can === "1" ? "" : "none");
}

function updateEditButtons(f, text) {
  const textual = !!f && /\.(txt|md)$/i.test(f.name) && !!historySelected.files.length;
  const main = !!f && /_transcript\.txt$/i.test(f.name);
  $h("historyEditBtn").dataset.can = textual ? "1" : "0";
  $h("historyRevertBtn").style.display = textual && f.orig ? "" : "none";
  $h("historySpeakersBtn").style.display = textual && /Speaker \d+/.test(text || "") ? "" : "none";
  $h("historyRegenBtn").style.display = main ? "" : "none";
  $h("historySpeakerPanel").style.display = "none";
  setEditing(false);
}

$h("historyEditBtn").addEventListener("click", async () => {
  const f = currentHistoryFile();
  if (!f) return;
  $h("historyEdit").value = await callApi("read_history_file", f.path);
  setEditing(true);
  $h("historyEdit").focus();
});
$h("historyCancelBtn").addEventListener("click", () => setEditing(false));
$h("historySaveBtn").addEventListener("click", async () => {
  const f = currentHistoryFile();
  const r = await callApi("save_history_text", f.path, $h("historyEdit").value);
  if (!r || !r.ok) { toast((r && r.message) || "Could not save"); return; }
  f.orig = true;
  toast("Saved. Use \"Rebuild outputs\" to refresh the summary and translations from it.");
  await showHistoryFile();
});
$h("historyRevertBtn").addEventListener("click", async () => {
  const f = currentHistoryFile();
  if (!f || !confirm("Put back the original file as it was before your edits?")) return;
  const r = await callApi("revert_history_text", f.path);
  if (r && r.ok) { f.orig = false; toast("Original restored"); await showHistoryFile(); } else toast((r && r.message) || "Could not revert");
});
$h("historyRegenBtn").addEventListener("click", async () => {
  const f = currentHistoryFile();
  if (!f) return;
  const r = await callApi("regenerate_transcript", f.path);
  if (!r || !r.ok) { toast((r && r.message) || "Could not start"); return; }
  showStartedJob(r, "regen");
});
$h("historySpeakersBtn").addEventListener("click", async () => {
  const panel = $h("historySpeakerPanel");
  if (panel.style.display !== "none") { panel.style.display = "none"; return; }
  const f = currentHistoryFile();
  const text = await callApi("read_history_file", f.path);
  const names = [...new Set(text.match(/Speaker \d+/g) || [])].sort();
  panel.innerHTML = names.map((n) => `<label>${n} <input type="text" data-from="${n}" placeholder="name"></label>`).join("") +
    '<button class="startbtn small" data-a="apply">Apply to all files</button>';
  panel.style.display = "";
  panel.querySelector('[data-a="apply"]').addEventListener("click", async () => {
    const mapping = {};
    panel.querySelectorAll("input").forEach((i) => { if (i.value.trim()) mapping[i.dataset.from] = i.value.trim(); });
    if (!Object.keys(mapping).length) return;
    const r = await callApi("rename_speakers", f.path, mapping);
    toast(r && r.ok ? `Renamed in ${r.changed} file(s)` : ((r && r.message) || "Could not rename"));
    panel.style.display = "none";
    await showHistoryFile();
  });
});

for (const [id, fmt] of [["historyWordBtn", "docx"], ["historyPdfBtn", "pdf"]]) {
  document.getElementById(id).addEventListener("click", async (e) => {
    const sel = document.getElementById("historyFileSelect");
    const f = historySelected && historySelected.files.find((x) => x.name === sel.value);
    if (!f) return;
    const btn = e.currentTarget, label = btn.textContent;
    btn.disabled = true; btn.textContent = "Exporting...";
    const r = await callApi("export_file", f.path, fmt);
    btn.disabled = false; btn.textContent = label;
    toast(r && r.ok ? `Saved ${r.name}` : ((r && r.message) || "Export failed"));
  });
}

// Timestamped transcript lines ("[00:01:23] ...") become clickable: they play the recording from there.
function renderHistoryText(text) {
  const box = document.getElementById("historyText");
  box.textContent = "";
  const media = document.getElementById("historyMedia");
  text.split(String.fromCharCode(10)).forEach((line) => {
    const div = document.createElement("div");
    const m = /^[\s#*-]*\[?(\d\d):(\d\d):(\d\d)\]?/.exec(line);
    div.textContent = line || " ";
    if (m && historySelected && historySelected.media) {
      div.className = "tline";
      div.dataset.t = String(+m[1] * 3600 + +m[2] * 60 + +m[3]);
      div.title = "Play from here";
      div.addEventListener("click", async () => {
        await ensureHistoryMedia();
        media.currentTime = +div.dataset.t;
        media.play().catch(() => {});
      });
    }
    box.appendChild(div);
  });
}

let mediaFor = null, mediaConverted = false;
async function ensureHistoryMedia(force) {
  const media = document.getElementById("historyMedia");
  const path = historySelected.media.path;
  if (mediaFor === path && !force) return;
  mediaFor = path; mediaConverted = !!force;
  const url = await callApi("get_media_url", path, !!force);
  if (url) media.src = url;
}

function setupHistoryPlayer() {
  const player = document.getElementById("historyPlayer");
  const media = document.getElementById("historyMedia");
  media.pause(); media.removeAttribute("src"); media.load(); mediaFor = null;
  const m = historySelected.media;
  player.style.display = m ? "" : "none";
  media.classList.toggle("audio", !!m && m.kind === "audio");
  if (m) ensureHistoryMedia();
}

(function wireHistoryPlayer() {
  const media = document.getElementById("historyMedia");
  // the player can't handle every format: on an error retry once with a converted audio copy
  media.addEventListener("error", () => {
    if (historySelected && historySelected.media && !mediaConverted && media.getAttribute("src")) {
      ensureHistoryMedia(true);
    }
  });
  media.addEventListener("timeupdate", () => {
    const lines = [...document.querySelectorAll("#historyText .tline")];
    let cur = null;
    for (const l of lines) { if (+l.dataset.t <= media.currentTime + 0.25) cur = l; else break; }
    lines.forEach((l) => l.classList.toggle("playing", l === cur));
    if (cur && !media.paused) cur.scrollIntoView({ block: "nearest" });
  });
})();

document.getElementById("historyOpenBtn")?.addEventListener("click", () => {
  const sel = document.getElementById("historyFileSelect");
  const f = historySelected?.files.find((x) => x.name === sel.value) || historySelected?.files[0];
  if (f) callApi("open_history_file", f.path);
});
document.getElementById("historyFolderBtn")?.addEventListener("click", () => {
  const f = historySelected?.files[0];
  if (f) callApi("open_history_folder", f.path);
});
document.getElementById("historyRemoveBtn")?.addEventListener("click", async () => {
  if (!historySelected) return;
  await callApi("remove_history_item", historySelected.time, historySelected.title);
  loadHistoryTab();
});

// ---- presets: one click sets the cleanup mode, speed, speakers, chapters and export for a kind of recording
const PRESETS = {
  "Custom": null,
  "Song / lyrics": { noise: "studio", speed: "75%", speakers: "Off", chapters: false, export: "none", wordTiming: true, subtitles: "srt",
    hint: "Studio AI isolates the voice, audio is slowed to 75%, word timing on." },
  "Meeting": { noise: null, speed: "Normal", speakers: "Auto-detect", chapters: true, export: "docx", wordTiming: false,
    hint: "Speaker labels, chapters and a Word summary." },
  "Lecture / talk": { noise: null, speed: "Normal", speakers: "Off", chapters: true, export: "pdf", wordTiming: false,
    hint: "Chapters and a PDF summary." },
};

async function applyPreset(name) {
  const p = PRESETS[name];
  state.preset = name;
  if (p) {
    state.speed = p.speed; state.speakers = p.speakers; state.chapters = p.chapters;
    state.export = p.export; state.wordTiming = p.wordTiming; state.subtitles = p.subtitles || state.subtitles;
    if (p.noise) {
      const cu = await callApi("get_voice_cleanup");
      if (cu && cu.noise !== undefined) {
        await callApi("save_voice_cleanup", { noise: p.noise, keepClean: cu.keepClean });
        state.noiseLabel = cu.choices[cu.values.indexOf(p.noise)] || state.noiseLabel;
        if (cleanupState) cleanupState.noise = p.noise;
        renderStats();
      }
    }
    toast(`${name}: ${p.hint}`);
  }
  renderSpoken(); renderSources(); persistHome();
}

function renderOutDir() {
  const btn = document.getElementById("outDirBtn"), clr = document.getElementById("outDirClear");
  const name = state.outputDir ? state.outputDir.split(/[\\/]/).filter(Boolean).pop() : "";
  btn.textContent = state.outputDir ? `Save to: ${name}` : "Save to: next to each file";
  btn.title = state.outputDir || "Where transcripts, summaries and other results are saved";
  clr.style.display = state.outputDir ? "" : "none";
}

function wireOutDir() {
  document.getElementById("outDirBtn").onclick = async () => {
    const p = await callApi("pick_folder");
    if (p) { state.outputDir = p; renderOutDir(); persistHome(); }
  };
  document.getElementById("outDirClear").onclick = () => { state.outputDir = ""; renderOutDir(); persistHome(); };
  renderOutDir();
}

function wirePreset() {
  const sel = document.getElementById("presetSelect");
  sel.innerHTML = Object.keys(PRESETS).map((n) => `<option ${n === state.preset ? "selected" : ""}>${n}</option>`).join("");
  sel.addEventListener("change", () => applyPreset(sel.value));
}

function wireStart() {
  document.getElementById("startBtn").addEventListener("click", async () => {
    await persistHome();
    const startBtn = document.getElementById("startBtn");
    const payload = { mode: state.mode };
    if (state.mode === "url") payload.url = document.getElementById("urlInput").value.trim();
    if (["file", "url"].includes(state.mode)) {
      const from = document.getElementById("clipStart").value.trim(), to = document.getElementById("clipEnd").value.trim();
      if (from || to) payload.clip = { start: from, end: to };
    }
    if (["mic", "system", "call"].includes(state.mode)) {
      const open = Object.values(TOOL_TABS).find((t) => t.key === "mode:" + state.mode);
      if (open) { activateTab(open.id); toast("Already open - use this tab."); return; }
    }
    startBtn.disabled = true;
    let res;
    try {
      res = await callApi("start_job", payload);
    } finally {
      startBtn.disabled = false;
    }
    if (!res || !res.ok) {
      toast((res && res.message) || "Could not start.");
      return;
    }
    showStartedJob(res, state.mode);
  });
}

function showStartedJob(res, mode) {
  const tab = openToolTab(res.live ? res.title : ({ file: "File", folder: "Folder", url: "Link", watch: "Watch", regen: "Rebuild" }[mode] || res.title), "mode:" + mode);
  if (res.live) { addLivePanel(res, tab); return; }
  addJobPanel(tab, res.jobId, res.title);
}

// ---- drag and drop: Python receives the drop (it knows the real paths) and starts the jobs;
// the page just picks the results up and shows the veil while something is dragged over it.
function wireDrop() {
  const veil = document.createElement("div");
  veil.className = "dropveil";
  veil.innerHTML = "<div>Drop video / audio files or a folder to process them</div>";
  document.body.appendChild(veil);
  let depth = 0;
  const has = (e) => e.dataTransfer && [...(e.dataTransfer.types || [])].includes("Files");
  document.addEventListener("dragenter", (e) => { if (has(e)) { depth++; veil.classList.add("show"); } });
  document.addEventListener("dragover", (e) => { if (has(e)) e.preventDefault(); });
  document.addEventListener("dragleave", (e) => { if (has(e) && --depth <= 0) { depth = 0; veil.classList.remove("show"); } });
  document.addEventListener("drop", () => { depth = 0; veil.classList.remove("show"); });
  setInterval(async () => {
    const drops = await callApi("take_drops");
    if (!Array.isArray(drops)) return;
    for (const res of drops) {
      if (!res.ok) toast(res.message || "Could not start.");
      else showStartedJob(res, res.mode);
    }
  }, 700);
}

async function boot() {
  state = await callApi("get_home_data");
  renderModels();
  renderSpoken();
  renderOutputs();
  renderSources();
  renderStats();
  wireStats();
  wireNav();
  wireStart();
  wirePreset();
  wireOutDir();
  wireDrop();
}

boot();

// ---------------------------------------------------------------- Live capture panel
// Polls live_poll() - Python never pushes into the page.
function addLivePanel(info, tab) {
  const wrap = document.createElement("div");
  wrap.className = "livepanel card full";
  const d = info.devices;
  const opt = (arr) => arr.map((n) => `<option>${n}</option>`).join("");
  wrap.innerHTML = `
    <div class="joblog-head"><span>${info.title}</span>
      <span class="joblog-actions"><span class="joblog-status" data-t="status">Loading Whisper model...</span>
        <button class="ghostbtn tiny" data-a="close">Close tab</button></span></div>
    <div class="liverow">
      <button class="startbtn small recbtn" data-a="rec" disabled>&#9679;&ensp;Record</button>
      <div class="meters" data-t="meters"></div>
      <span class="muted small" data-t="lang">Language: -</span>
    </div>
    <div class="liverow">
      ${d.mic.length ? `<select class="select" data-t="mic">${opt(d.mic)}</select>` : ""}
      ${d.sys.length ? `<select class="select" data-t="sys">${opt(d.sys)}</select>` : ""}
    </div>
    <div class="livetext" data-t="text"></div>
    <div class="liverow">
      <input type="text" class="select" data-t="alerts" placeholder="Alert words (comma separated)">
    </div>
    <div class="liverow">
      <label class="checkrow"><input type="checkbox" data-t="capon"> Captions on screen</label>
      <select class="select" data-t="caplang" style="max-width:240px;"></select>
      <button class="ghostbtn tiny" data-a="capset">Caption settings</button>
    </div>
    <div class="liverow capsettings" data-t="capbox" style="display:none;">
      <label class="small">Size <input type="number" min="10" max="72" data-c="size" class="select" style="width:70px;"></label>
      <label class="small">Lines <input type="number" min="1" max="5" data-c="lines" class="select" style="width:60px;"></label>
      <label class="small">Width % <input type="number" min="30" max="100" data-c="width" class="select" style="width:70px;"></label>
      <label class="small">Opacity <input type="range" min="20" max="100" data-c="opacity"></label>
      <label class="small">Position <select data-c="position" class="select" style="width:90px;"><option>Bottom</option><option>Top</option></select></label>
      <label class="small">Text <input type="color" data-c="fg"></label>
      <label class="small">Background <input type="color" data-c="bg"></label>
      <label class="checkrow small"><input type="checkbox" data-c="show_original"> Show original words</label>
      <label class="checkrow small"><input type="checkbox" data-c="no_bg"> No background</label>
      <label class="checkrow small"><input type="checkbox" data-c="speak"> Read captions aloud</label>
    </div>
    <div class="liverow">
      <select class="select" data-t="target" style="max-width:180px;"></select>
      <button class="ghostbtn" data-a="translate" disabled>Translate</button>
      <button class="ghostbtn" data-a="read">Read aloud</button>
      <span class="muted small" data-t="msg"></span>
    </div>
    <pre class="historytext" data-t="out" style="min-height:60px;margin:0 14px;"></pre>
    <div class="liverow">
      <button class="startbtn small" data-a="save" disabled>Save</button>
      <button class="ghostbtn" data-a="copy">Copy text</button>
      <button class="ghostbtn" data-a="clear">Clear</button>
      <select class="select" data-a="redospeed" style="width:auto;" title="Slow the recording down before re-transcribing - helps with fast speech">${(state.speedChoices || []).map((c) => `<option ${c === state.speed ? "selected" : ""}>Speed: ${c}</option>`).join("")}</select>
      <button class="ghostbtn" data-a="redo" disabled title="Clean the whole recording and transcribe it again at full quality">Clean up &amp; re-transcribe</button>
    </div>`;
  tab.view.prepend(wrap);
  const t = (n) => wrap.querySelector(`[data-t="${n}"]`);
  const a = (n) => wrap.querySelector(`[data-a="${n}"]`);
  const sid = info.sid;
  const targets = ["English", "Hindi", "Urdu", "French", "German", "Spanish", "Arabic", "Chinese", "Japanese"];
  t("target").innerHTML = opt([...new Set([...(info.outputs || []), ...targets])]);
  const keys = d.call ? ["mic", "sys"] : [d.source === "system" ? "sys" : "mic"];
  t("meters").innerHTML = keys.map((k) => `<span class="meter"><i data-k="${k}"></i></span>`).join("");

  let offset = 0, recording = false, closed = false, lastLabel = null, prov = {};
  const textEl = t("text");
  const renderProv = () => {
    let el = textEl.querySelector(".prov");
    if (!el) { el = document.createElement("span"); el.className = "prov"; textEl.appendChild(el); }
    el.textContent = Object.values(prov).filter(Boolean).join("   ");
  };
  const applyEvent = (ev) => {
    const [kind, ...r] = ev;
    if (kind === "ready") { t("status").textContent = `Ready - press Record (model: ${r[0]})`; a("rec").disabled = false; }
    else if (kind === "error") t("status").textContent = r[0];
    else if (kind === "commit") {
      const [key, text, , who, langName] = r;
      delete prov[key];
      textEl.querySelector(".prov")?.remove();
      const label = [who, langName].filter(Boolean).join(" \u00b7 ");
      if (label !== lastLabel) {
        const tag = document.createElement("span");
        tag.className = "langtag"; tag.textContent = (lastLabel ? "\n" : "") + `[${label}] `;
        textEl.appendChild(tag); lastLabel = label;
      }
      textEl.appendChild(document.createTextNode(text + " "));
      renderProv(); textEl.scrollTop = textEl.scrollHeight;
    } else if (kind === "prov") { prov[r[0]] = r[1]; renderProv(); textEl.scrollTop = textEl.scrollHeight; }
    else if (kind === "alert") t("status").textContent = `ALERT: '${r[0].join(", ")}' at ${Math.round(r[1])}s`;
    else if (kind === "stopped") {
      prov = {}; renderProv(); a("rec").disabled = false; a("rec").innerHTML = "&#9679;&ensp;Record";
      t("status").textContent = "Stopped - press Record to continue, or translate / read / save below";
    } else if (kind === "translated") {
      const [target, text, by] = r;
      t("out").textContent = text ? text.replace(/^\[\d\d:\d\d:\d\d\]\s*/gm, "") : "";
      t("msg").textContent = text ? `${target} - by ${by}` : `No translator available for ${target} (needs Claude Code, Ollama or LM Studio)`;
    } else if (kind === "redone") {
      const [entries, name, unclear, alerts] = r;
      if (entries === null) { t("status").textContent = `Clean-up failed: ${name}`; return; }
      textEl.innerHTML = ""; lastLabel = null; prov = {};
      for (const e of entries) {
        const label = [e.who, e.langName].filter(Boolean).join(" \u00b7 ");
        if (label !== lastLabel) {
          const tag = document.createElement("span");
          tag.className = "langtag"; tag.textContent = (lastLabel ? "\n" : "") + `[${label}] `;
          textEl.appendChild(tag); lastLabel = label;
        }
        textEl.appendChild(document.createTextNode(e.text + " "));
      }
      t("out").textContent = ""; t("msg").textContent = "";
      t("status").textContent = `Re-transcribed after '${name}' cleanup` + (unclear ? ` - ${unclear} line(s) marked [unclear]` : "");
    } else if (kind === "speech") t("msg").textContent = r[0];
  };
  const tick = async () => {
    if (closed) return;
    const p = await callApi("live_poll", sid, offset);
    if (p.closed) return;
    p.events.forEach(applyEvent);
    offset = p.next;
    recording = p.recording;
    wrap.querySelectorAll("[data-k]").forEach((m) => { m.style.width = (p.levels[m.dataset.k] || 0) + "%"; });
    if (p.language) t("lang").textContent = "Language: " + p.language;
    const idle = !p.recording && !p.finalizing;
    a("translate").disabled = !(idle && p.hasEntries && !p.busy);
    a("save").disabled = !(idle && p.hasEntries);
    a("redo").disabled = !(idle && p.hasEntries && !p.busy);
    a("redospeed").disabled = a("redo").disabled;
    a("read").textContent = p.speaking ? "Stop reading" : "Read aloud";
    setTimeout(tick, 400);
  };
  tick();

  // ---- caption overlay (a second always-on-top window; it polls Python itself)
  const CAP_LANGS = ["Original (as spoken)", "English (fast, offline)", ...targets.filter((x) => x !== "English")];
  t("caplang").innerHTML = opt(CAP_LANGS);
  const capNum = { size: 1, lines: 1, width: 1 };
  callApi("live_caption_settings", sid, null).then((cs) => {
    t("caplang").value = cs.lang;
    wrap.querySelectorAll("[data-c]").forEach((el) => {
      const k = el.dataset.c;
      if (el.type === "checkbox") el.checked = !!cs[k];
      else el.value = k === "opacity" ? Math.round(cs[k] * 100) : cs[k];
    });
  });
  t("capon").addEventListener("change", () => callApi("live_caption_set", sid, t("capon").checked, t("caplang").value));
  t("caplang").addEventListener("change", () => callApi("live_caption_set", sid, t("capon").checked, t("caplang").value));
  a("capset").addEventListener("click", () => {
    const b = t("capbox"); b.style.display = b.style.display === "none" ? "flex" : "none";
  });
  wrap.querySelectorAll("[data-c]").forEach((el) => el.addEventListener("input", () => {
    const k = el.dataset.c;
    const v = el.type === "checkbox" ? el.checked : k === "opacity" ? el.value / 100 : capNum[k] ? +el.value : el.value;
    callApi("live_caption_settings", sid, { [k]: v });
  }));

  a("rec").addEventListener("click", async () => {
    if (!recording) {
      const r = await callApi("live_record", sid, t("mic") ? t("mic").value : null, t("sys") ? t("sys").value : null);
      if (!r.ok) { toast(r.message); return; }
      recording = true;
      a("rec").innerHTML = "&#9632;&ensp;Stop";
      t("status").textContent = { mic: "Listening... speak now", system: "Capturing PC sound...", call: "Capturing the call - both sides..." }[d.source];
    } else {
      a("rec").disabled = true; t("status").textContent = "Finishing the last words...";
      await callApi("live_stop", sid);
    }
  });
  t("alerts").addEventListener("input", (e) => callApi("live_alert_words", sid, e.target.value));
  a("translate").addEventListener("click", () => { t("msg").textContent = "Translating..."; callApi("live_translate", sid, t("target").value); });
  a("read").addEventListener("click", () => callApi("live_read", sid, t("out").textContent.trim(), t("target").value));
  a("save").addEventListener("click", async () => { const r = await callApi("live_save", sid); toast("Saved to " + r.dir); });
  a("copy").addEventListener("click", async () => {
    await navigator.clipboard.writeText(await callApi("live_text", sid)); toast("Text copied");
  });
  a("redo").addEventListener("click", async () => {
    if (!confirm("Clean the whole recording (voice isolation + noise removal) and transcribe it again at full quality?\n\nThis replaces the live transcript and can take a while.")) return;
    const r = await callApi("live_redo", sid, a("redospeed").value.replace("Speed: ", ""));
    if (!r.ok) toast(r.message);
  });
  a("clear").addEventListener("click", async () => {
    if (!(await callApi("live_clear", sid))) return;
    textEl.innerHTML = ""; lastLabel = null; prov = {}; t("out").textContent = ""; t("msg").textContent = "";
  });
  tab.setOnClose(async () => { closed = true; await callApi("live_close", sid); });
  a("close").addEventListener("click", () => tab.close());
}
