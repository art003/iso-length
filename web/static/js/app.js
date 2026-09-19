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
let poll = null;

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
  card.addEventListener("click", () => {
    document.querySelectorAll(".api").forEach((c) => c.classList.remove("is-on"));
    card.classList.add("is-on");
    const name = card.querySelector("input").value;
    document.getElementById("model").value = PRESETS[name].model;
    document.getElementById("hint").textContent = PRESETS[name].hint;
    document.getElementById("stat-api").textContent = name;
  });
});

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
  runBtn.disabled = true;
  busy.classList.add("is-on");
  logEl.textContent = "запуск...\n";
  const r = await fetch("/api/start", { method: "POST", body: fd });
  const data = await r.json();
  if (!r.ok) {
    logEl.textContent += "ошибка: " + (data.error || r.status) + "\n";
    runBtn.disabled = false;
    busy.classList.remove("is-on");
    return;
  }
  poll = setInterval(tick, 800);
});

document.getElementById("open-out").addEventListener("click", () => {
  fetch("/api/open-output", { method: "POST" });
});

async function tick() {
  const r = await fetch("/api/status");
  const s = await r.json();
  logEl.textContent = (s.log || []).join("\n") || "работаю...";
  logEl.scrollTop = logEl.scrollHeight;
  if (!s.running) {
    clearInterval(poll);
    poll = null;
    runBtn.disabled = false;
    busy.classList.remove("is-on");
    fillResults(s);
    showPage("results");
  }
}

function badge(status) {
  const cls = status === "ok" ? "ok" : status === "review" ? "review" : "error";
  return `<span class="badge badge-${cls}">${status || ""}</span>`;
}

function fillResults(s) {
  const sheets = (s.metrics && s.metrics.sheets) || [];
  document.getElementById("stat-pages").textContent = sheets.length || "—";
  document.getElementById("stat-cost").textContent = s.metrics ? "$" + (s.metrics.cost_total_usd ?? 0) : "$0";
  rowsEl.innerHTML = sheets
    .map(
      (x) =>
        `<tr><td>${x.sheet_no}</td><td>${x.line_id}</td><td>${x.length_mm}</td><td>${x.length_m}</td><td>${badge(
          x.status
        )}</td><td>${x.formula || ""}</td></tr>`
    )
    .join("");
  thumbsEl.innerHTML = (s.thumbs || [])
    .map((t) => `<a href="${t}" target="_blank"><img src="${t}" alt=""></a>`)
    .join("");
}

fetch("/api/status")
  .then((r) => r.json())
  .then((s) => {
    if (s.metrics) fillResults(s);
  });
