const PRESETS = {
  Groq: { model: "qwen/qwen3.8-27b", hint: "бесплатно, ключ gsk_ с console.groq.com/keys" },
  OpenAI: { model: "gpt-4o", hint: "платно, ключ sk- с platform.openai.com" },
  "OpenAI Codex": { model: "gpt-5-codex", hint: "платно, тот же ключ OpenAI, модель gpt-5-codex" },
};

const logEl = document.getElementById("log");
const rowsEl = document.getElementById("rows");
const thumbsEl = document.getElementById("thumbs");
const busy = document.getElementById("busy");
const runBtn = document.getElementById("run");
const stopBtn = document.getElementById("stop");
const jobsEl = document.getElementById("jobs");
const editorEl = document.getElementById("editor");
const edImg = document.getElementById("ed-img");
const edCanvas = document.getElementById("ed-canvas");
const edList = document.getElementById("ed-list");
let poll = null;
let currentJob = "";
let lastSheets = [];
let lastJobs = [];
let editorView = null;
let editorBusy = false;

document.querySelectorAll(".header__links a, .header__logo").forEach((a) => {
  a.addEventListener("click", (e) => {
    e.preventDefault();
    showPage(a.dataset.page);
  });
});

function showPage(name) {
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("is-on", p.id === "page-" + name));
  document.querySelectorAll(".header__links a").forEach((a) => a.classList.toggle("is-on", a.dataset.page === name));
}

document.querySelectorAll(".api").forEach((card) => {
  card.addEventListener("click", () => selectApi(card.querySelector("input").value));
});

function selectApi(name) {
  document.querySelectorAll(".api").forEach((c) => c.classList.remove("is-on"));
  const card = [...document.querySelectorAll(".api")].find((c) => c.querySelector("input").value === name);
  if (card) {
    card.classList.add("is-on");
    card.querySelector("input").checked = true;
  }
  document.getElementById("model").value = PRESETS[name].model;
  document.getElementById("hint").textContent = PRESETS[name].hint;
  document.getElementById("stat-api").textContent = name;
  localStorage.setItem("iso_api", name);
}

const savedApi = localStorage.getItem("iso_api");
if (savedApi && PRESETS[savedApi]) selectApi(savedApi);

document.getElementById("pdf").addEventListener("change", () => {
  const f = document.getElementById("pdf").files[0];
  document.getElementById("pdf-name").textContent = f ? f.name : "файл не выбран — можно перетащить сюда";
  if (f) document.getElementById("use-default").checked = false;
});

const drop = document.getElementById("drop");
["dragenter", "dragover"].forEach((ev) => {
  drop.addEventListener(ev, (e) => {
    e.preventDefault();
    drop.classList.add("is-on");
  });
});
["dragleave", "drop"].forEach((ev) => {
  drop.addEventListener(ev, (e) => {
    e.preventDefault();
    drop.classList.remove("is-on");
  });
});
drop.addEventListener("drop", (e) => {
  const f = e.dataTransfer.files[0];
  if (!f || !f.name.toLowerCase().endsWith(".pdf")) return;
  const dt = new DataTransfer();
  dt.items.add(f);
  document.getElementById("pdf").files = dt.files;
  document.getElementById("pdf").dispatchEvent(new Event("change"));
});

function setRunning(on) {
  runBtn.disabled = on;
  stopBtn.disabled = !on;
  busy.classList.toggle("is-on", on);
}

document.getElementById("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData();
  const file = document.getElementById("pdf").files[0];
  if (file) fd.append("pdf", file);
  fd.append("use_default", document.getElementById("use-default").checked ? "1" : "0");
  fd.append("api", document.querySelector("input[name=api]:checked").value);
  fd.append("model", document.getElementById("model").value);
  fd.append("key", document.getElementById("key").value);
  fd.append("pages", document.getElementById("pages").value);
  fd.append("replay", document.getElementById("replay").checked ? "1" : "0");
  fd.append("fresh", document.getElementById("fresh").checked ? "1" : "0");
  setRunning(true);
  logEl.textContent = "запуск...\n";
  const r = await fetch("/api/start", { method: "POST", body: fd });
  const data = await r.json();
  if (!r.ok) {
    logEl.textContent += "ошибка: " + (data.error || r.status) + "\n";
    setRunning(false);
    return;
  }
  poll = setInterval(tick, 800);
});

stopBtn.addEventListener("click", async () => {
  stopBtn.disabled = true;
  await fetch("/api/stop", { method: "POST" });
});

document.getElementById("open-out").addEventListener("click", () => {
  fetch("/api/open-output", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job: currentJob }),
  });
});

jobsEl.addEventListener("change", async () => {
  const id = jobsEl.value;
  if (!id) return;
  const r = await fetch("/api/job/" + encodeURIComponent(id));
  const s = await r.json();
  if (!r.ok) return;
  fillResults(s);
  showPage("results");
});

async function tick() {
  const r = await fetch("/api/status");
  const s = await r.json();
  logEl.textContent = (s.log || []).join("\n") || "работаю...";
  logEl.scrollTop = logEl.scrollHeight;
  if (!s.running) {
    clearInterval(poll);
    poll = null;
    setRunning(false);
    fillResults(s);
    showPage("results");
  }
}

function badge(status) {
  const cls = status === "ok" ? "ok" : status === "review" ? "review" : "error";
  return `<span class="badge badge-${cls}">${status || ""}</span>`;
}

function fillJobs(jobs, selected) {
  jobs = jobs || [];
  lastJobs = jobs;
  jobsEl.innerHTML = jobs
    .map(
      (j) =>
        `<option value="${j.id}" ${j.id === selected ? "selected" : ""}>${j.pdf || j.id} · ${j.pages || 0} л. · ${
          j.total_m ?? ""
        } м</option>`
    )
    .join("");
}

function fillResults(s, bust) {
  const m = s.metrics || {};
  const sheets = m.sheets || [];
  lastSheets = sheets;
  currentJob = m.job || "";
  document.getElementById("stat-pages").textContent = sheets.length || "—";
  document.getElementById("stat-total").textContent =
    m.total_m != null ? String(m.total_m).replace(".", ",") : "—";
  document.getElementById("stat-cost").textContent = m.cost_total_usd != null ? "$" + m.cost_total_usd : "$0";
  document.getElementById("results-title").textContent = m.pdf ? m.pdf : "Таблица длин";
  document.getElementById("results-pdf").textContent = currentJob
    ? "папка output\\" + currentJob + " · " + (m.updated || "") + " · клик по строке — правка размеров"
    : "";
  document.getElementById("totals").innerHTML = sheets.length
    ? `<b>${m.total_mm || 0} мм</b> · ${m.total_m || 0} м · ok ${m.ok ?? "—"} · review ${m.review ?? "—"}`
    : "";
  document.getElementById("dl-xlsx").href = currentJob ? "/media/" + currentJob + "/lengths.xlsx" : "#";
  document.getElementById("dl-html").href = currentJob ? "/media/" + currentJob + "/report.html" : "#";
  fillJobs(s.jobs || lastJobs, currentJob);
  rowsEl.innerHTML = sheets
    .map(
      (x, i) =>
        `<tr data-i="${i}"><td>${x.sheet_no}</td><td>${x.line_id}</td><td>${x.length_mm}</td><td>${x.length_m}</td><td>${badge(
          x.status
        )}</td><td>${x.formula || ""}</td></tr>`
    )
    .join("");
  if (sheets.length) {
    const tot = m.total_mm || sheets.reduce((a, x) => a + (x.length_mm || 0), 0);
    rowsEl.innerHTML += `<tr class="total"><td></td><td>итого</td><td>${tot}</td><td>${(tot / 1000).toFixed(
      3
    )}</td><td></td><td></td></tr>`;
  }
  const q = bust ? "?t=" + Date.now() : "";
  const thumbs = s.thumbs || [];
  thumbsEl.innerHTML = thumbs
    .map((t, i) => `<a href="${t}" data-i="${i}"><img src="${t}${q}" alt=""></a>`)
    .join("");
  rowsEl.querySelectorAll("tr[data-i]").forEach((tr) => {
    tr.addEventListener("click", () => {
      rowsEl.querySelectorAll("tr").forEach((x) => x.classList.remove("is-on"));
      tr.classList.add("is-on");
      const i = Number(tr.dataset.i);
      const img = thumbsEl.querySelector(`[data-i="${i}"] img`);
      thumbsEl.querySelectorAll("img").forEach((x) => x.classList.remove("is-on"));
      if (img) {
        img.classList.add("is-on");
        img.parentElement.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
      }
      const sheet = lastSheets[i];
      if (sheet) openSheet(sheet.sheet_no);
    });
  });
  thumbsEl.querySelectorAll("a").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      const i = Number(a.dataset.i);
      const sheet = lastSheets[i];
      if (sheet) openSheet(sheet.sheet_no);
    });
  });
}

async function openSheet(sheetNo) {
  if (!currentJob) return;
  const r = await fetch("/api/sheet/" + encodeURIComponent(currentJob) + "/" + sheetNo);
  const view = await r.json();
  if (!r.ok) {
    alert(view.error || "не открылся лист");
    return;
  }
  drawEditor(view);
}

function drawEditor(view) {
  editorView = view;
  document.getElementById("ed-title").textContent = "Лист " + view.sheet_no + "  " + (view.line_id || "");
  document.getElementById("ed-sum").textContent =
    (view.length_mm || 0) +
    " мм · " +
    (view.length_m || 0) +
    " м · " +
    (view.status || "") +
    (view.locked ? " · закрыт" : "") +
    (view.formula ? " · " + view.formula : "");
  edList.innerHTML = (view.items || [])
    .map(
      (it) =>
        `<li><button type="button" class="is-${it.decision}" data-id="${it.id}">${it.id} · ${it.value_mm} · ${it.label}</button></li>`
    )
    .join("");
  edList.querySelectorAll("button").forEach((b) => {
    b.addEventListener("click", () => decide(b.dataset.id));
  });
  editorEl.hidden = false;
  const src = "/media/" + view.overlay + "?t=" + Date.now();
  const same = edImg.dataset.overlay === view.overlay && edImg.complete && edImg.naturalWidth;
  if (!same) {
    edImg.dataset.overlay = view.overlay;
    edImg.onload = () => placeHits(view);
    edImg.src = src;
  } else {
    requestAnimationFrame(() => placeHits(view));
  }
}

function placeHits(view) {
  edCanvas.querySelectorAll(".hit").forEach((x) => x.remove());
  const sx = edImg.clientWidth / (view.width || 1);
  const sy = edImg.clientHeight / (view.height || 1);
  (view.items || []).forEach((it) => {
    if (!it.x && !it.y) return;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "hit hit-" + it.decision;
    b.style.left = it.x * sx + "px";
    b.style.top = it.y * sy + "px";
    b.textContent = it.id + " " + it.value_mm;
    b.title = it.label;
    b.addEventListener("click", () => decide(it.id));
    edCanvas.appendChild(b);
  });
}

async function decide(cid) {
  if (editorBusy || !editorView) return;
  editorBusy = true;
  try {
    const r = await fetch("/api/decide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job: currentJob, sheet_no: editorView.sheet_no, id: cid }),
    });
    const data = await r.json();
    if (!r.ok) {
      alert(data.error || "не сохранилась правка");
      return;
    }
    fillResults(data, true);
    const again = await fetch("/api/sheet/" + encodeURIComponent(currentJob) + "/" + editorView.sheet_no);
    const view = await again.json();
    if (again.ok) drawEditor(view);
  } finally {
    editorBusy = false;
  }
}

function closeEditor() {
  editorEl.hidden = true;
  editorView = null;
}

document.getElementById("ed-close").addEventListener("click", closeEditor);
editorEl.addEventListener("click", (e) => {
  if (e.target === editorEl) closeEditor();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !editorEl.hidden) closeEditor();
});
window.addEventListener("resize", () => {
  if (!editorEl.hidden && editorView) placeHits(editorView);
});

fetch("/api/status")
  .then((r) => r.json())
  .then((s) => {
    if (s.metrics) fillResults(s);
    setRunning(!!s.running);
    if (s.running) poll = setInterval(tick, 800);
  });
