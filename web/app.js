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
    { name: "small", size: "~485 MB", desc: "Good balance of speed and accuracy", downloaded: true },
    { name: "medium", size: "~1.5 GB", desc: "More accurate, slower", downloaded: false },
    { name: "large-v3-turbo", size: "~1.6 GB", desc: "Near-best accuracy, fast", downloaded: false },
    { name: "large-v3", size: "~3.1 GB", desc: "Best accuracy, slowest", downloaded: false },
    { name: "distil-large-v3", size: "~1.5 GB", desc: "English audio only", downloaded: false },
  ],
  selectedModel: "small",
  spokenLanguage: "Auto-detect",
  spokenChoices: ["Auto-detect", "English", "Hindi", "Urdu", "French", "German", "Spanish"],
  outputChoices: ["Original", "English", "Hindi", "Urdu", "French", "German", "Spanish"],
  outputs: ["Original", "English"],
  mode: "file",
  skipDone: true,
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
  ollamaModels: ["phi4:latest", "llama3.2:latest", "qwen2.5:7b"], ollamaErr: null, ollamaPicked: "phi4:latest",
  lmstudioModels: [], lmstudioErr: "LM Studio server not running.", lmstudioPicked: "",
};
const MOCK_HISTORY = [
  { time: "2026-09-20T10:00:00", title: "Team meeting", when: "20 Sep 2026 10:00", kind: "Video",
    languages: "English", length: "00:12:30",
    files: [{ path: "C:/fake/meeting_transcript.txt", name: "meeting_transcript.txt" }], exists: true },
];

const _mockTicks = {};

function callApi(name, ...args) {
  if (window.pywebview && window.pywebview.api && window.pywebview.api[name]) {
    return window.pywebview.api[name](...args);
  }
  console.warn("[mock]", name, args);
  if (name === "get_home_data") return Promise.resolve(MOCK_HOME);
  if (name === "get_voice_cleanup") return Promise.resolve(MOCK_CLEANUP);
  if (name === "get_offline_settings") return Promise.resolve(MOCK_OFFLINE);
  if (name === "get_history") return Promise.resolve(MOCK_HISTORY);
  if (name === "read_history_file") return Promise.resolve("(mock file contents)");
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

function renderModels() {
  const list = document.getElementById("modelGrid");
  list.innerHTML = "";
  for (const m of state.models) {
    const selected = m.name === state.selectedModel;
    const pct = m._progress || 0;
    const row = document.createElement("div");
    row.className = "modelrow" + (selected ? " selected-row" : "");
    row.title = m.desc;
    let status;
    if (m._downloading) status = `<span class="statuscircle downloading">${pct}%</span>`;
    else if (selected) status = `<span class="statuscircle selected">&#10003;</span>`;
    else if (m.downloaded) status = `<span class="statuscircle downloaded">&#10003;</span>`;
    else status = `<span class="statuscircle"></span>`;
    row.innerHTML = `
      <div class="modelrow-left">
        <span class="modelicon">${m.name.slice(0, 2)}</span>
        <div class="modelrow-text">
          <div class="modelrow-name">${m.name}</div>
          <div class="modelrow-size">${m.size}</div>
        </div>
      </div>
      ${status}`;
    row.addEventListener("click", () => onModelClick(m));
    list.appendChild(row);
  }
  document.getElementById("modelsCount").textContent =
    state.models.filter((m) => m.downloaded).length + "/" + state.models.length;
}

function onModelClick(m) {
  if (m.downloaded) {
    state.selectedModel = m.name;
    renderModels();
    persistHome();
    return;
  }
  if (m._downloading) return;
  m._downloading = true;
  renderModels();
  toast(`Downloading ${m.name}...`);
  callApi("download_model", m.name);
  pollModelProgress(m);
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
    renderModels();
    if (p.done) {
      m.downloaded = true;
      m._downloading = false;
      state.selectedModel = m.name;
      toast(`${m.name} downloaded`);
      renderModels();
      return;
    }
    setTimeout(tick, 500);
  };
  tick();
}

function renderSpoken() {
  const sel = document.getElementById("spokenSelect");
  sel.innerHTML = state.spokenChoices.map((c) =>
    `<option ${c === state.spokenLanguage ? "selected" : ""}>${c}</option>`).join("");
  sel.addEventListener("change", () => { state.spokenLanguage = sel.value; persistHome(); });
}

function renderOutputs() {
  const box = document.getElementById("outputChecks");
  box.innerHTML = state.outputChoices.map((name) => `
    <label class="checkrow">
      <input type="checkbox" data-out="${name}" ${state.outputs.includes(name) ? "checked" : ""}>
      ${name}
    </label>`).join("");
  box.querySelectorAll("input").forEach((cb) => cb.addEventListener("change", () => {
    const name = cb.dataset.out;
    state.outputs = cb.checked ? [...state.outputs, name] : state.outputs.filter((n) => n !== name);
    persistHome();
  }));
  const speak = document.getElementById("speakSave");
  speak.checked = state.speakSave;
  speak.addEventListener("change", () => { state.speakSave = speak.checked; persistHome(); });
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
  document.getElementById("skipDone").checked = state.skipDone;
  document.getElementById("subfolders").checked = state.subfolders;
}

function renderStats() {
  document.getElementById("statModels").textContent =
    state.models.filter((m) => m.downloaded).length + " / " + state.models.length;
  document.getElementById("statGpu").textContent = state.gpu === "cuda" ? "GPU (CUDA)" : "CPU";
  document.getElementById("statHistory").textContent = state.historyCount;
  document.getElementById("statOnline").textContent = state.onlinePref ? "Online" : "Offline";
  document.getElementById("noiseSummary").textContent = state.noiseLabel;

  const dot = document.getElementById("netDot");
  dot.classList.toggle("ok", !!state.onlineReal);
  dot.title = state.onlineReal ? "Internet connected" : "Offline";

  const toggle = document.getElementById("onlineToggle");
  toggle.checked = !!state.onlinePref;
  document.getElementById("onlineLabel").textContent =
    state.onlinePref ? "Prefers online tools" : "Prefers offline tools";
  toggle.addEventListener("change", () => {
    state.onlinePref = toggle.checked;
    document.getElementById("onlineLabel").textContent =
      state.onlinePref ? "Prefers online tools" : "Prefers offline tools";
    document.getElementById("statOnline").textContent = state.onlinePref ? "Online" : "Offline";
    callApi("set_online", state.onlinePref);
  });
}

function persistHome() {
  return callApi("save_home", {
    model: state.selectedModel,
    spokenLanguage: state.spokenLanguage,
    outputs: state.outputs,
    mode: state.mode,
    skipDone: document.getElementById("skipDone").checked,
    subfolders: document.getElementById("subfolders").checked,
    speakSave: state.speakSave,
  });
}

const TAB_LOADERS = { cleanup: loadCleanupTab, offline: loadOfflineTab, history: () => loadHistoryTab() };

function wireNav() {
  document.querySelectorAll(".pill").forEach((btn) => btn.addEventListener("click", () => {
    document.querySelectorAll(".pill").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    document.getElementById("view-" + btn.dataset.tab).classList.add("active");
    if (TAB_LOADERS[btn.dataset.tab]) TAB_LOADERS[btn.dataset.tab]();
  }));
}

// ---------------------------------------------------------------- job log panels
// Polling, not a push from Python - see pollModelProgress() above for why.
function addJobPanel(containerEl, jobId, title, stoppable) {
  const wrap = document.createElement("div");
  wrap.className = "joblog";
  wrap.innerHTML = `<div class="joblog-head"><span>${title}</span>
      <span class="joblog-actions">
        ${stoppable ? '<button class="ghostbtn tiny" data-a="stop">Stop</button>' : ""}
        <span class="joblog-status">Running...</span>
      </span></div>
    <pre class="joblog-body"></pre>`;
  containerEl.prepend(wrap);
  const statusEl = wrap.querySelector(".joblog-status");
  const bodyEl = wrap.querySelector(".joblog-body");
  if (stoppable) {
    wrap.querySelector('[data-a="stop"]').addEventListener("click", () => callApi("stop_watch_job", jobId));
  }

  let offset = 0;
  const tick = async () => {
    const r = await callApi("get_job_log", jobId, offset);
    if (r.lines.length) {
      bodyEl.textContent += r.lines.join("");
      bodyEl.scrollTop = bodyEl.scrollHeight;
      offset = r.nextOffset;
    }
    if (r.done) {
      statusEl.textContent = "Done";
      statusEl.classList.add("done");
      return;
    }
    setTimeout(tick, 500);
  };
  tick();
}

// ---------------------------------------------------------------- Voice Cleanup tab
let cleanupState = null;

async function loadCleanupTab() {
  cleanupState = await callApi("get_voice_cleanup");
  renderNoiseGrid();
  document.getElementById("keepCleanChk").checked = cleanupState.keepClean;
  document.getElementById("keepCleanChk").onchange = (e) => {
    cleanupState.keepClean = e.target.checked;
    saveCleanup();
  };
  document.getElementById("saveKeyBtn").onclick = async () => {
    const key = document.getElementById("keyInput").value;
    const ok = await callApi("save_key", key);
    document.getElementById("keyStatus").textContent = ok ? "Key saved." : "No key saved.";
    document.getElementById("keyInput").value = "";
  };
  buildFileTool("cuTool", "Clean up", async (src, outDir) =>
    callApi("start_cleanup_job", src, outDir, cleanupState.noise));
  buildFileTool("muTool", "Extract music", async (src, outDir) =>
    callApi("start_music_job", src, outDir));
}

function renderNoiseGrid() {
  const grid = document.getElementById("noiseGrid");
  grid.innerHTML = cleanupState.choices.map((label, i) =>
    `<div class="sourcecard ${cleanupState.values[i] === cleanupState.noise ? "selected" : ""}"
          data-value="${cleanupState.values[i]}">${label}</div>`).join("");
  grid.querySelectorAll(".sourcecard").forEach((el) => el.addEventListener("click", () => {
    cleanupState.noise = el.dataset.value;
    renderNoiseGrid();
    document.getElementById("keyRow").style.display = cleanupState.noise === "online" ? "flex" : "none";
    saveCleanup();
  }));
  document.getElementById("noiseHelp").textContent = cleanupState.help[cleanupState.noise] || "";
  document.getElementById("keyRow").style.display = cleanupState.noise === "online" ? "flex" : "none";
  document.getElementById("keyStatus").textContent = cleanupState.hasKey ? "Key saved - change above." : "No key saved.";
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
    const jobId = await onRun(tool.src, tool.outDir);
    addJobPanel(el.querySelector(".joblogs"), jobId, tool.src.split(/[\\/]/).pop());
  });
}

// ---------------------------------------------------------------- Offline Settings tab
async function loadOfflineTab() {
  const data = await callApi("get_offline_settings");
  fillOfflineSelect("ollama", data.ollamaModels, data.ollamaPicked, data.ollamaErr);
  fillOfflineSelect("lmstudio", data.lmstudioModels, data.lmstudioPicked, data.lmstudioErr);
  document.getElementById("ollamaRefresh").onclick = loadOfflineTab;
  document.getElementById("lmstudioRefresh").onclick = loadOfflineTab;
}

function fillOfflineSelect(kind, models, picked, err) {
  const sel = document.getElementById(kind + "Select");
  const AUTO = "(auto - first available)";
  sel.innerHTML = [AUTO, ...models].map((m) =>
    `<option ${m === (picked || AUTO) ? "selected" : ""}>${m}</option>`).join("");
  sel.onchange = () => callApi("save_offline_model", kind, sel.value === AUTO ? "" : sel.value);
  document.getElementById(kind + "Status").textContent =
    err ? err : `${models.length} model(s) found.`;
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
  showHistoryFile();
}

async function showHistoryFile() {
  const sel = document.getElementById("historyFileSelect");
  const f = historySelected.files.find((x) => x.name === sel.value) || historySelected.files[0];
  document.getElementById("historyText").textContent = f ? await callApi("read_history_file", f.path) : "";
}

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

function wireStart() {
  document.getElementById("startBtn").addEventListener("click", async () => {
    await persistHome();
    const startBtn = document.getElementById("startBtn");
    const payload = { mode: state.mode };
    if (state.mode === "url") payload.url = document.getElementById("urlInput").value.trim();
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
    if (res.live) { addLivePanel(res); return; }
    addJobPanel(document.getElementById("jobPanels"), res.jobId, res.title, res.stoppable);
  });
}

async function boot() {
  state = await callApi("get_home_data");
  renderModels();
  renderSpoken();
  renderOutputs();
  renderSources();
  renderStats();
  wireNav();
  wireStart();
}

boot();

// ---------------------------------------------------------------- Live capture panel
// Polls live_poll() - Python never pushes into the page.
function addLivePanel(info) {
  const wrap = document.createElement("div");
  wrap.className = "livepanel card full";
  const d = info.devices;
  const opt = (arr) => arr.map((n) => `<option>${n}</option>`).join("");
  wrap.innerHTML = `
    <div class="joblog-head"><span>${info.title}</span>
      <span class="joblog-actions"><span class="joblog-status" data-t="status">Loading Whisper model...</span>
        <button class="ghostbtn tiny" data-a="close">Close</button></span></div>
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
      <button class="ghostbtn" data-a="redo" disabled title="Clean the whole recording and transcribe it again at full quality">Clean up &amp; re-transcribe</button>
    </div>`;
  document.getElementById("livePanels").prepend(wrap);
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
    const r = await callApi("live_redo", sid);
    if (!r.ok) toast(r.message);
  });
  a("clear").addEventListener("click", async () => {
    if (!(await callApi("live_clear", sid))) return;
    textEl.innerHTML = ""; lastLabel = null; prov = {}; t("out").textContent = ""; t("msg").textContent = "";
  });
  a("close").addEventListener("click", async () => { closed = true; await callApi("live_close", sid); wrap.remove(); });
}
