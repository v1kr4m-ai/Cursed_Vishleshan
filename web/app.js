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
  });
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
