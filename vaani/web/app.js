// VaaniNotes frontend. Talks only to this machine (same-origin /api); no external requests.
"use strict";

const $ = (id) => document.getElementById(id);
const TARGET_RATE = 16000;
const state = { wav: null, jobId: null, polling: null, recorder: null, sections: {}, shown: {}, segments: 0 };

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v);
  }
  node.append(...children);
  return node;
}

function fmtTime(seconds) {
  const s = Math.floor(seconds);
  const pad = (n) => String(n).padStart(2, "0");
  const h = Math.floor(s / 3600);
  return (h ? pad(h) + ":" : "") + pad(Math.floor((s % 3600) / 60)) + ":" + pad(s % 60);
}

/* ---------- Audio: everything becomes 16 kHz mono WAV in the browser ---------- */

function encodeWav(samples, rate) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); str(8, "WAVE"); str(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, "data"); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const x = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, x < 0 ? x * 0x8000 : x * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

async function resampleToWav(audioBuffer) {
  const length = Math.ceil(audioBuffer.duration * TARGET_RATE);
  const offline = new OfflineAudioContext(1, length, TARGET_RATE);
  const src = offline.createBufferSource();
  src.buffer = audioBuffer;
  src.connect(offline.destination);
  src.start();
  const rendered = await offline.startRendering();
  return encodeWav(rendered.getChannelData(0), TARGET_RATE);
}

async function fileToWav(file) {
  if (/\.wav$/i.test(file.name)) return file; // the server resamples WAV itself
  const ctx = new AudioContext();
  try {
    return await resampleToWav(await ctx.decodeAudioData(await file.arrayBuffer()));
  } finally {
    ctx.close();
  }
}

function setSource(blob, label) {
  state.wav = blob;
  const src = $("source");
  src.textContent = label;
  src.classList.toggle("is-ready", Boolean(blob));
  $("generate-btn").disabled = !blob;
}

async function handleFile(file) {
  if (!file) return;
  setSource(null, `Preparing ${file.name}…`);
  try {
    setSource(await fileToWav(file), `Ready: ${file.name}`);
  } catch (e) {
    setSource(null, `Could not read ${file.name}. Try a WAV or MP3 file.`);
  }
}

/* ---------- Microphone recording ---------- */

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  const ctx = new AudioContext();
  await ctx.audioWorklet.addModule("/static/recorder-worklet.js");
  const node = new AudioWorkletNode(ctx, "recorder");
  const chunks = [];
  let frames = 0;
  const started = Date.now();
  node.port.onmessage = (e) => {
    chunks.push(e.data);
    frames += e.data.length;
    let peak = 0;
    for (const x of e.data) peak = Math.max(peak, Math.abs(x));
    $("meter-bar").style.transform = `scaleX(${Math.min(1, peak * 1.6).toFixed(2)})`;
  };
  ctx.createMediaStreamSource(stream).connect(node);
  const mute = ctx.createGain(); // keeps the graph pulling without playing the mic back
  mute.gain.value = 0;
  node.connect(mute).connect(ctx.destination);
  const timer = setInterval(() => {
    $("record-label").textContent = `Stop recording · ${fmtTime((Date.now() - started) / 1000)}`;
  }, 500);
  state.recorder = { stream, ctx, chunks, timer, frames: () => frames };
  $("record-btn").setAttribute("aria-pressed", "true");
  $("record-label").textContent = "Stop recording · 00:00";
  setSource(null, "Recording…");
}

async function stopRecording() {
  const { stream, ctx, chunks, timer, frames } = state.recorder;
  state.recorder = null;
  clearInterval(timer);
  stream.getTracks().forEach((t) => t.stop());
  $("record-btn").setAttribute("aria-pressed", "false");
  $("record-label").textContent = "Record with microphone";
  $("meter-bar").style.transform = "scaleX(0)";
  const total = frames();
  if (total < ctx.sampleRate) { await ctx.close(); return setSource(null, "Recording was too short. Try again."); }
  const buffer = ctx.createBuffer(1, total, ctx.sampleRate);
  const data = buffer.getChannelData(0);
  let offset = 0;
  for (const c of chunks) { data.set(c, offset); offset += c.length; }
  const wav = await resampleToWav(buffer);
  await ctx.close();
  setSource(wav, `Ready: microphone recording (${fmtTime(total / buffer.sampleRate)})`);
}

/* ---------- Rendering (DOM only, never innerHTML: model output is untrusted text) ---------- */

const clean = (s) => s.replace(/\*\*/g, "").replace(/^#+\s*/, "").trim();

function renderBlocks(text, lang) {
  const frag = document.createDocumentFragment();
  let list = null;
  for (const raw of text.split(/\n+/)) {
    const line = raw.trim();
    if (!line) continue;
    const bullet = line.match(/^(?:[-*•]|\d+[.)])\s+(.*)/);
    if (bullet) {
      if (!list) { list = el("ul", { lang }); frag.append(list); }
      list.append(el("li", { text: clean(bullet[1]) }));
    } else {
      list = null;
      frag.append(el("p", { lang, text: clean(line) }));
    }
  }
  return frag;
}

function renderFlashcards(text, lang) {
  const cards = [...text.matchAll(/Q\s*[:：]\s*([\s\S]*?)\n\s*A\s*[:：]\s*([\s\S]*?)(?=\n\s*(?:\d+[.)]\s*)?Q\s*[:：]|$)/g)];
  if (!cards.length) return renderBlocks(text, lang);
  const grid = el("div", { class: "flashcards" });
  cards.forEach(([, q, a], i) => {
    const btn = el("button", { type: "button", class: "flashcard", "aria-pressed": "false", "aria-label": `Flashcard ${i + 1}. Activate to flip.` },
      el("span", { class: "flashcard__inner" },
        el("span", { class: "flashcard__face", lang }, el("span", { class: "flashcard__kicker", text: `Question ${i + 1}` }), clean(q)),
        el("span", { class: "flashcard__face flashcard__face--back", lang }, el("span", { class: "flashcard__kicker", text: "Answer" }), clean(a))));
    btn.addEventListener("click", () => btn.setAttribute("aria-pressed", btn.getAttribute("aria-pressed") === "true" ? "false" : "true"));
    grid.append(btn);
  });
  return grid;
}

const LANG_CODES = { English: "en", Hindi: "hi", Bengali: "bn", Tamil: "ta", Telugu: "te", Marathi: "mr", Gujarati: "gu", Kannada: "kn", Malayalam: "ml", Punjabi: "pa", Urdu: "ur" };

function renderSections(sections) {
  const lang = LANG_CODES[$("notes-language").value] || "en";
  for (const key of Object.keys(state.sections)) {
    if (!(key in sections) || state.shown[key]) continue;
    state.shown[key] = true;
    $("notes-empty").hidden = true;
    const body = key === "flashcards" ? renderFlashcards(sections[key], lang) : renderBlocks(sections[key], lang);
    $("notes").append(el("article", { class: "note rise" + (key === "flashcards" ? " note--wide" : "") }, el("h3", { text: state.sections[key] }), body));
  }
}

function renderSegments(segments, lang) {
  const list = $("transcript");
  for (const seg of segments.slice(state.segments)) {
    if (!seg.text) continue;
    list.append(el("li", {}, el("time", { text: fmtTime(seg.start) }), el("p", { lang: lang || "und", text: seg.text })));
  }
  state.segments = segments.length;
  if (list.children.length) $("transcript-empty").hidden = true;
}

function renderPerf(p) {
  const tiles = [
    ["Speed", `${p.speed_x_realtime}×`, "faster than real time"],
    ["Transcription", `${p.asr_seconds} s`, `for ${fmtTime(p.audio_seconds)} of audio`],
    ["Per 30 s window", `${p.avg_window_ms} ms`, p.asr_backend],
    ["Notes writing", `${p.llm_seconds} s`, p.llm_backend],
  ];
  if (p.llm_tokens_per_second) tiles.push(["LLM speed", `${p.llm_tokens_per_second}`, "tokens per second"]);
  tiles.push(["Sent to internet", `${p.bytes_sent_to_internet} B`, "everything ran on this device"]);
  $("metrics").replaceChildren(...tiles.map(([k, v, note]) =>
    el("div", { class: "metric" }, el("dt", { text: k }), el("dd", {}, v, el("small", { text: note })))));
  $("perf-empty").hidden = true;
}

/* ---------- Job lifecycle ---------- */

function setProgress(fraction, message) {
  const pct = Math.round(fraction * 100);
  $("progress-bar").style.width = pct + "%";
  $("progress").setAttribute("aria-valuenow", String(pct));
  if ($("progress-text").textContent !== message) $("progress-text").textContent = message;
}

function showError(message) {
  $("error").textContent = message;
  $("error").hidden = !message;
}

function setBusy(busy) {
  $("generate-btn").disabled = busy || !state.wav;
  $("generate-btn").textContent = busy ? "Working…" : "Generate notes";
  $("record-btn").disabled = busy;
}

async function poll() {
  let job;
  try {
    const res = await fetch(`/api/jobs/${state.jobId}`);
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    job = await res.json();
  } catch (e) {
    clearInterval(state.polling); setBusy(false);
    return showError("Lost contact with the local app. Is it still running?");
  }
  setProgress(job.progress, job.message);
  renderSegments(job.segments, job.language);
  renderSections(job.sections);
  if (job.status === "done") {
    clearInterval(state.polling); setBusy(false);
    renderPerf(job.perf);
    $("download").href = `/api/jobs/${state.jobId}/notes.md`;
    $("download").hidden = false;
    $("ask-btn").disabled = false;
    $("progress-wrap").hidden = true;
  } else if (job.status === "error") {
    clearInterval(state.polling); setBusy(false);
    $("progress-wrap").hidden = true;
    showError(`Something went wrong: ${job.message}`);
  }
}

async function generate(event) {
  event.preventDefault();
  if (!state.wav) return;
  const form = new FormData($("options"));
  const sections = form.getAll("section");
  if (!sections.length) return showError("Choose at least one thing to include.");
  const body = new FormData();
  body.append("audio", state.wav, "audio.wav");
  body.append("language", form.get("language"));
  body.append("task", form.get("task"));
  body.append("notes_language", form.get("notes_language"));
  body.append("sections", sections.join(","));

  showError("");
  $("notes").replaceChildren(); $("transcript").replaceChildren(); $("answer").replaceChildren();
  $("download").hidden = true; $("ask-btn").disabled = true;
  $("notes-empty").hidden = false; $("transcript-empty").hidden = false;
  state.shown = {}; state.segments = 0;
  $("progress-wrap").hidden = false; setProgress(0, "Sending audio to the local engine…");
  setBusy(true);
  try {
    const res = await fetch("/api/jobs", { method: "POST", body });
    if (!res.ok) throw new Error((await res.json()).detail || `Server returned ${res.status}`);
    state.jobId = (await res.json()).id;
    history.replaceState(null, "", `?job=${state.jobId}`);
    state.polling = setInterval(poll, 700);
    $("results").focus();
  } catch (e) {
    setBusy(false); $("progress-wrap").hidden = true;
    showError(`Could not start: ${e.message}`);
  }
}

async function ask(event) {
  event.preventDefault();
  const question = $("question").value.trim();
  if (!question || !state.jobId) return;
  $("ask-btn").disabled = true;
  $("answer").textContent = "Thinking on-device…";
  try {
    const res = await fetch(`/api/jobs/${state.jobId}/ask`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.status);
    $("answer").replaceChildren(renderBlocks((await res.json()).answer, LANG_CODES[$("notes-language").value] || "en"));
  } catch (e) {
    $("answer").textContent = `Could not answer: ${e.message}`;
  } finally {
    $("ask-btn").disabled = false;
  }
}

/* ---------- Tabs (WAI-ARIA pattern: arrows move, Home/End jump) ---------- */

function initTabs() {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  const select = (tab, focus = true) => {
    tabs.forEach((t) => {
      const on = t === tab;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      $(t.getAttribute("aria-controls")).hidden = !on;
    });
    if (focus) tab.focus();
  };
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => select(tab, false));
    tab.addEventListener("keydown", (e) => {
      const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
      if (next === undefined) return;
      e.preventDefault();
      select(tabs[(next + tabs.length) % tabs.length]);
    });
  });
}

/* ---------- Boot ---------- */

function chip(text, kind) {
  return el("li", { class: "chip" + (kind ? ` chip--${kind}` : "") }, text);
}

async function init() {
  initTabs();
  $("options").addEventListener("submit", generate);
  $("ask-form").addEventListener("submit", ask);
  $("file-input").addEventListener("change", (e) => handleFile(e.target.files[0]));
  const zone = $("dropzone");
  ["dragenter", "dragover"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.add("is-dragover"); }));
  ["dragleave", "drop"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.remove("is-dragover"); }));
  zone.addEventListener("drop", (e) => handleFile(e.dataTransfer.files[0]));
  $("record-btn").addEventListener("click", async () => {
    try {
      if (state.recorder) await stopRecording(); else await startRecording();
    } catch (e) {
      setSource(null, "Microphone unavailable. Check the Windows microphone permission.");
    }
  });

  try {
    const s = await (await fetch("/api/status")).json();
    state.sections = s.sections;
    $("language").replaceChildren(...Object.entries(s.languages).map(([code, name]) => el("option", { value: code, text: name })));
    $("notes-language").replaceChildren(...s.output_languages.map((name) => el("option", { value: name, text: name })));
    for (const [key, title] of Object.entries(s.sections)) {
      $("sections-field").append(el("label", { class: "check" },
        el("input", { type: "checkbox", name: "section", value: key, checked: "" }), title));
    }
    $("status-chips").replaceChildren(
      chip("Offline · nothing leaves this device", "device"),
      chip(`Speech: ${s.asr}`, s.asr_on_npu ? "device" : "warn"),
      chip(`Notes: ${s.llm}`, s.llm_on_npu ? "device" : s.llm_is_extractive ? "warn" : ""));
    $("device-table").querySelector("tbody").replaceChildren(...Object.entries(s.device).map(([k, v]) =>
      el("tr", {}, el("th", { scope: "row", text: k }), el("td", { text: v }))));
  } catch (e) {
    showError("Could not reach the local engine. Restart VaaniNotes.");
  }

  // Deep link: /?job=<id> reopens a finished or running job (handy after a refresh).
  const params = new URLSearchParams(location.search);
  if (/^[0-9a-f]{32}$/.test(params.get("job") || "")) {
    state.jobId = params.get("job");
    $("progress-wrap").hidden = false;
    state.polling = setInterval(poll, 700);
    poll();
    const tab = $("tab-" + params.get("tab"));
    if (tab) tab.click();
  }
}

init();
