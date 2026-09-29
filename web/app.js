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

function callApi(name, ...args) {
  if (window.pywebview && window.pywebview.api && window.pywebview.api[name]) {
    return window.pywebview.api[name](...args);
  }
  console.warn("[mock]", name, args);
  if (name === "get_home_data") return Promise.resolve(MOCK_HOME);
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

function ringSvg(pct, extraClass) {
  const r = 16, c = 2 * Math.PI * r;
  const off = c * (1 - pct / 100);
  return `<svg class="modelring ${extraClass || ""}" viewBox="0 0 40 40">
    <circle class="bg" cx="20" cy="20" r="${r}" fill="none" stroke-width="4"/>
    <circle class="fg" cx="20" cy="20" r="${r}" fill="none" stroke-width="4"
      stroke-dasharray="${c}" stroke-dashoffset="${off}" stroke-linecap="round"
      transform="rotate(-90 20 20)"/>
  </svg>`;
}

function renderModels() {
  const grid = document.getElementById("modelGrid");
  grid.innerHTML = "";
  for (const m of state.models) {
    const div = document.createElement("div");
    const selected = m.name === state.selectedModel;
    div.className = "modelcard" + (selected ? " selected" : "") + (m.downloaded ? " downloaded" : "");
    div.dataset.name = m.name;
    const pct = m.downloaded ? 100 : (m._progress || 0);
    div.innerHTML = `
      ${ringSvg(pct)}
      <div class="modelname">${m.name}</div>
      <div class="modelsize">${m.size}</div>
      <div class="modelstatus">${m.downloaded ? (selected ? "Selected" : "Downloaded")
        : (m._downloading ? pct + "%" : "Click to download")}</div>`;
    div.title = m.desc;
    div.addEventListener("click", () => onModelClick(m));
    grid.appendChild(div);
  }
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
}

window.onModelProgress = function (name, pct, err) {
  const m = state.models.find((x) => x.name === name);
  if (!m) return;
  if (err) {
    m._downloading = false;
    toast(`${name} failed: ${err}`);
    renderModels();
    return;
  }
  m._progress = pct;
  if (pct >= 100) {
    m.downloaded = true;
    m._downloading = false;
    state.selectedModel = name;
    toast(`${name} downloaded`);
  }
  renderModels();
};

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
  callApi("save_home", {
    model: state.selectedModel,
    spokenLanguage: state.spokenLanguage,
    outputs: state.outputs,
    mode: state.mode,
    skipDone: document.getElementById("skipDone").checked,
    subfolders: document.getElementById("subfolders").checked,
    speakSave: state.speakSave,
  });
}

function wireNav() {
  document.querySelectorAll(".pill").forEach((btn) => btn.addEventListener("click", () => {
    document.querySelectorAll(".pill").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    document.getElementById("view-" + btn.dataset.tab).classList.add("active");
  }));
}

function wireStart() {
  document.getElementById("startBtn").addEventListener("click", async () => {
    const res = await callApi("start_job", { mode: state.mode });
    if (res && res.message) toast(res.message);
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
