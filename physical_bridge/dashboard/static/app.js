// Physical Bridge dashboard - plain JS, no build step.
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return el;
};
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

let ws = null;
let state = null;
const streamEls = new Map();
const virtualEls = new Map();
const valueRanges = new Map();
const DYNAMIC = new Set(["smooth", "ease", "limits", "rate_limit"]);

// ------------------------------------------------------------------ socket
function connect() {
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onopen = () => setConn(true);
  ws.onclose = () => { setConn(false); setTimeout(connect, 1000); };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "state") { state = msg; render(); }
  };
}
function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }
function setConn(ok) {
  const c = $("#conn");
  c.querySelector(".dot").className = "dot " + (ok ? "ok" : "bad");
  c.querySelector("span:last-child").textContent = ok ? "live" : "offline";
}

$("#arm").addEventListener("click", () => {
  if (!state) return;
  if (state.armed || confirm("Re-arm hardware outputs? Motors may move.")) send({ cmd: "arm", armed: !state.armed });
});

// ------------------------------------------------------------- decoding
function decode(frame) {
  if (!frame) return null;
  if (frame.kind === "bits") {
    const px = new Uint8Array(frame.data.length);
    for (let i = 0; i < px.length; i++) px[i] = frame.data.charCodeAt(i) === 49 ? 255 : 0;
    return { ...frame, px };
  }
  if (frame.kind === "grid") {
    const px = new Uint8Array(frame.data.length / 2);
    for (let i = 0; i < px.length; i++) px[i] = parseInt(frame.data.substr(i * 2, 2), 16);
    return { ...frame, px };
  }
  return frame;
}

// --------------------------------------------------------------- drawing
function fitCell(w, h, maxW = 240, maxH = 170) {
  return Math.max(2, Math.floor(Math.min(maxW / w, maxH / h)));
}
function setupCanvas(canvas, cssW, cssH) {
  const dpr = window.devicePixelRatio || 1;
  if (canvas.width !== cssW * dpr || canvas.height !== cssH * dpr) {
    canvas.width = cssW * dpr; canvas.height = cssH * dpr;
    canvas.style.width = cssW + "px"; canvas.style.height = cssH + "px";
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}
function hexToRgb(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  const n = m ? parseInt(m[1], 16) : 0xff4d2e;
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function drawPixels(canvas, f) {
  const cell = fitCell(f.w, f.h);
  const ctx = setupCanvas(canvas, f.w * cell, f.h * cell);
  const img = ctx.createImageData(f.w, f.h);
  const [r, g, b] = f.kind === "bits" ? [255, 255, 255] : [255, 255, 255];
  for (let i = 0; i < f.px.length; i++) {
    const v = f.px[i] / 255;
    img.data[i * 4] = r * v; img.data[i * 4 + 1] = g * v; img.data[i * 4 + 2] = b * v; img.data[i * 4 + 3] = 255;
  }
  const tmp = drawPixels.tmp || (drawPixels.tmp = document.createElement("canvas"));
  tmp.width = f.w; tmp.height = f.h;
  tmp.getContext("2d").putImageData(img, 0, 0);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(tmp, 0, 0, f.w * cell, f.h * cell);
}

function drawLEDs(canvas, f, color) {
  const cell = fitCell(f.w, f.h, 260, 220);
  const ctx = setupCanvas(canvas, f.w * cell, f.h * cell);
  const [r, g, b] = hexToRgb(color);
  ctx.fillStyle = css("--screen"); ctx.fillRect(0, 0, f.w * cell, f.h * cell);
  const rad = Math.max(1, cell * 0.38);
  for (let y = 0; y < f.h; y++) for (let x = 0; x < f.w; x++) {
    const v = f.px[y * f.w + x] / 255;
    ctx.beginPath();
    ctx.arc(x * cell + cell / 2, y * cell + cell / 2, rad, 0, Math.PI * 2);
    ctx.fillStyle = v > 0 ? `rgba(${r},${g},${b},${0.15 + 0.85 * v})` : css("--led-off");
    ctx.fill();
  }
}

function drawServos(canvas, angles) {
  const n = Math.max(angles.length, 1);
  const per = Math.min(4, n), rows = Math.ceil(n / per);
  const cw = 64, ch = 48;
  const ctx = setupCanvas(canvas, per * cw, rows * ch);
  ctx.clearRect(0, 0, per * cw, rows * ch);
  angles.forEach((a, i) => {
    const cx = (i % per) * cw + cw / 2, cy = Math.floor(i / per) * ch + 36, R = 26;
    ctx.strokeStyle = css("--border"); ctx.lineWidth = 6;
    ctx.beginPath(); ctx.arc(cx, cy, R, Math.PI, 0); ctx.stroke();
    const t = Math.max(0, Math.min(180, a));
    ctx.strokeStyle = css("--accent"); ctx.beginPath(); ctx.arc(cx, cy, R, Math.PI, Math.PI + (t / 180) * Math.PI); ctx.stroke();
    const rad = Math.PI + (((a % 360) + 360) % 360) / 180 * Math.PI;
    ctx.strokeStyle = css("--text"); ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx + Math.cos(rad) * (R - 4), cy + Math.sin(rad) * (R - 4)); ctx.stroke();
    ctx.fillStyle = css("--muted"); ctx.font = "10px ui-monospace, monospace"; ctx.textAlign = "center";
    ctx.fillText(`${i}: ${a.toFixed(1)}°`, cx, cy + 11);
  });
}

function renderBars(container, key, values) {
  const range = valueRanges.get(key) || { lo: 0, hi: 1 };
  for (const v of values) { range.lo = Math.min(range.lo, v); range.hi = Math.max(range.hi, v); }
  valueRanges.set(key, range);
  const span = range.hi - range.lo || 1;
  container.replaceChildren(...values.map((v, i) =>
    h("div", { class: "bar" }, h("span", {}, i),
      h("div", { class: "track" }, h("div", { class: "fill", style: `width:${((v - range.lo) / span) * 100}%` })),
      h("span", { class: "num" }, v.toFixed(2)))));
}

function renderFrame(view, frame, key) {
  const body = view.querySelector(".body");
  const f = decode(frame);
  if (!f) { body.replaceChildren(h("span", { class: "hint" }, "no data yet")); body.dataset.kind = ""; return; }
  if (body.dataset.kind !== f.kind) {
    body.dataset.kind = f.kind;
    body.replaceChildren(f.kind === "bits" || f.kind === "grid" ? h("canvas") : h("div", { class: "bars" }));
  }
  view.querySelector(".view-label .info").textContent =
    f.kind === "bits" || f.kind === "grid" ? `${f.kind} ${f.w}×${f.h}` :
    f.kind === "angles" ? `${f.data.length} angles` : "value";
  if (f.kind === "bits" || f.kind === "grid") drawPixels(body.firstChild, f);
  else if (f.kind === "angles") renderBars(body.firstChild, key, f.data);
  else renderBars(body.firstChild, key, [f.data]);
}

// -------------------------------------------------------------- side bar
function statusDot(ok, warn) { return h("span", { class: "dot " + (ok ? "ok" : warn ? "warn" : "bad") }); }

function renderInputs() {
  const el = $("#inputs");
  const entries = Object.entries(state.inputs);
  if (!entries.length) { el.replaceChildren(h("div", { class: "empty" }, "No inputs enabled.")); return; }
  el.replaceChildren(...entries.map(([k, i]) => {
    const recent = i.last_seen_s !== null && i.last_seen_s < 2;
    return h("div", { class: "card" },
      h("div", { class: "card-head" },
        h("div", { class: "card-title" }, statusDot(i.listening && recent, i.listening), k.toUpperCase()),
        h("span", { class: "tag" }, i.listening ? (recent ? "receiving" : "listening") : "down")),
      h("dl", { class: "kv" },
        h("dt", {}, "on"), h("dd", {}, i.detail || "-"),
        h("dt", {}, "rate"), h("dd", {}, `${i.rate} msg/s  (${i.messages} total)`),
        h("dt", {}, "last"), h("dd", {}, i.last_address ? `${i.last_address}  ${i.last_seen_s}s ago` : "-"),
        h("dt", {}, k === "websocket" ? "clients" : "senders"), h("dd", {}, i.clients)),
      i.error ? h("div", { class: "err" }, i.error) : "");
  }));
}

function renderOutputs() {
  const el = $("#outputs");
  const entries = Object.entries(state.outputs);
  if (!entries.length) { el.replaceChildren(h("div", { class: "empty" }, "No outputs configured.")); return; }
  el.replaceChildren(...entries.map(([name, o]) => {
    const devs = o.devices && Array.isArray(o.devices) ? o.devices : [];
    const alive = devs.some((d) => d.alive);
    const ok = o.connected && (o.type === "virtual" || o.type === "osc" || alive);
    return h("div", { class: "card" },
      h("div", { class: "card-head" },
        h("div", { class: "card-title" }, statusDot(ok, o.connected), name, h("span", { class: "tag" }, o.type)),
        h("span", { class: "tag" }, !o.physical ? "sim" : state.armed ? `${o.fps} fps` : "disarmed")),
      h("dl", { class: "kv" },
        h("dt", {}, "link"), h("dd", {}, o.detail || "-"),
        h("dt", {}, "status"), h("dd", {}, o.connected ? (devs.length ? (alive ? "device responding" : "port open, device silent") : "connected") : "disconnected"),
        ...devs.flatMap((d) => [h("dt", {}, `dev ${d.address}`), h("dd", {}, `${d.name || "?"} · ${d.alive ? "alive" : "no reply"}`)]),
        h("dt", {}, "sent"), h("dd", {}, `${o.frames_sent} frames · ${(o.bytes_sent / 1024).toFixed(1)} KiB · ${o.frames_dropped} skipped`),
        o.crc_errors ? [h("dt", {}, "crc err"), h("dd", {}, o.crc_errors)] : []),
      o.error ? h("div", { class: "err" }, o.error) : "",
      o.log && o.log.length ? h("div", { class: "log" }, o.log.join("\n")) : "");
  }));
}

function renderUnrouted() {
  const el = $("#unrouted");
  if (!state.unrouted.length) { el.replaceChildren(h("div", { class: "empty" }, "Everything is routed.")); return; }
  el.replaceChildren(...state.unrouted.map((u) =>
    h("div", { class: "row", title: u.sample }, h("span", {}, u.address), h("span", {}, `${u.origin} ×${u.count}`))));
}

// --------------------------------------------------------------- streams
function buildStream(s) {
  const inView = h("div", { class: "view" }, h("div", { class: "view-label" }, h("span", {}, "input"), h("span", { class: "info" })), h("div", { class: "body" }));
  const outView = h("div", { class: "view" }, h("div", { class: "view-label" }, h("span", {}, "output"), h("span", { class: "info" })), h("div", { class: "body" }));
  const chips = h("div", { class: "chips" },
    s.pipeline.length ? s.pipeline.map((p) => [h("span", { class: "chip" + (DYNAMIC.has(p) ? " dyn" : "") }, p), h("span", { class: "arrow" }, "↓")]).flat().slice(0, -1)
      : h("span", { class: "arrow" }, "→ pass-through →"));
  const el = h("div", { class: "stream" },
    h("div", { class: "stream-head" },
      h("div", {}, h("span", { class: "stream-name" }, s.name), " ", h("span", { class: "tag" }, s.kind)),
      h("div", { class: "stream-meta" }, h("span", { class: "rates" }), h("span", {}, s.sources.join(", ")))),
    h("div", { class: "flow" }, inView, chips, outView),
    h("div", { class: "dests" }, "→ ", s.outputs.map((o) => h("span", { class: "chip" }, o))),
    h("div", { class: "err stream-err" }),
    buildTest(s));
  return { el, inView, outView };
}

function renderStreams() {
  const root = $("#streams");
  const names = Object.keys(state.streams);
  if (!names.length && !root.firstChild) root.append(h("div", { class: "empty" }, "No streams configured - add some under 'streams:' in your YAML file."));
  for (const name of names) {
    const s = state.streams[name];
    let rec = streamEls.get(name);
    if (!rec) {
      if (root.querySelector(".empty")) root.replaceChildren();
      rec = buildStream(s); streamEls.set(name, rec); root.append(rec.el);
    }
    rec.state = s;
    renderFrame(rec.inView, s.input, name + ":in");
    renderFrame(rec.outView, s.output, name + ":out");
    rec.el.querySelector(".rates").textContent = `in ${s.in_rate}/s · out ${s.out_rate}/s${s.settled ? "" : " · moving"}`;
    rec.el.querySelector(".stream-err").textContent = s.error || "";
  }
}

// ----------------------------------------------------------- test signals
function rangeOf(s, fallback) { return s.input_range || fallback; }

function buildTest(s) {
  const body = h("div", { class: "test-body" });
  const det = h("details", { class: "test" }, h("summary", {}, "Test signal (inject from the dashboard)"), body);
  let timer = null;
  const play = (btn, fn, hz = 20) => {
    if (timer) { clearInterval(timer); timer = null; btn.classList.remove("playing"); btn.textContent = "▶ play"; return; }
    const t0 = performance.now();
    timer = setInterval(() => fn((performance.now() - t0) / 1000), 1000 / hz);
    btn.classList.add("playing"); btn.textContent = "■ stop";
  };
  const inject = (data) => send({ cmd: "inject", stream: s.name, data });

  if (s.kind === "grid" || s.kind === "bits") {
    const sel = h("select", {}, ...["gradient", "circle", "wave", "checker", "noise", "blank"].map((p) => h("option", { value: p }, p)));
    const btn = h("button", {}, "▶ play");
    const gen = (t) => {
      const cur = streamEls.get(s.name)?.state?.input;
      const W = cur ? cur.w : 32, H = cur ? cur.h : 32;
      const [lo, hi] = rangeOf(s, s.kind === "bits" ? [0, 1] : [0, 255]);
      const data = new Array(W * H);
      for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
        const u = x / (W - 1 || 1), v = y / (H - 1 || 1);
        let val;
        switch (sel.value) {
          case "gradient": val = (u + t * 0.25) % 1; break;
          case "circle": { const cx = 0.5 + 0.3 * Math.cos(t * 1.5), cy = 0.5 + 0.3 * Math.sin(t * 1.5);
            val = Math.max(0, 1 - Math.hypot(u - cx, v - cy) * 3); break; }
          case "wave": val = 0.5 + 0.5 * Math.sin(u * 6.28 * 1.5 + t * 3) * Math.cos(v * 3.14 + t); break;
          case "checker": val = ((x >> 2) + (y >> 2) + Math.floor(t * 2)) % 2; break;
          case "noise": val = Math.random(); break;
          default: val = 0;
        }
        if (s.kind === "bits") val = val > 0.5 ? 1 : 0;
        data[y * W + x] = +(lo + val * (hi - lo)).toFixed(3);
      }
      inject({ w: W, h: H, data });
    };
    btn.addEventListener("click", () => play(btn, gen));
    body.append("pattern", sel, btn, h("button", { onclick: () => gen(0) }, "send once"));
  } else {
    const [lo, hi] = rangeOf(s, [0, 1]);
    const count = s.kind === "value" ? 1 : Math.max(1, s.input ? s.input.data.length : (s.sources.length > 1 ? s.sources.length : 3));
    const sliders = Array.from({ length: count }, () =>
      h("input", { type: "range", min: lo, max: hi, step: (hi - lo) / 1000, value: (lo + hi) / 2 }));
    const out = () => (s.kind === "value" ? +sliders[0].value : sliders.map((x) => +x.value));
    sliders.forEach((sl, i) => {
      sl.addEventListener("input", () => inject(out()));
      body.append(h("label", { class: "slider" }, s.kind === "value" ? "value" : `#${i}`, sl));
    });
    const btn = h("button", {}, "▶ sweep");
    btn.addEventListener("click", () => play(btn, (t) => {
      sliders.forEach((sl, i) => { sl.value = lo + (hi - lo) * (0.5 + 0.5 * Math.sin(t * 1.2 + i * 0.9)); });
      inject(out());
    }));
    btn.textContent = "▶ play";
    body.append(btn);
  }
  return det;
}

// -------------------------------------------------------- virtual devices
function renderVirtual() {
  const root = $("#virtual");
  const items = [];
  for (const [oname, o] of Object.entries(state.outputs)) {
    if (o.type !== "virtual") continue;
    for (const [sname, d] of Object.entries(o.devices || {})) items.push({ key: `${oname}/${sname}`, o, sname, d });
  }
  $("#virtual-section").style.display = items.length || Object.values(state.outputs).some((o) => o.type === "virtual") ? "" : "none";
  if (!items.length && !root.firstChild) root.append(h("div", { class: "empty" }, "Virtual devices appear here once a stream sends to them."));
  for (const it of items) {
    let rec = virtualEls.get(it.key);
    if (!rec) {
      if (root.querySelector(".empty")) root.replaceChildren();
      const el = h("div", { class: "vdev" },
        h("div", { class: "card-head" }, h("div", { class: "card-title" }, it.sname), h("span", { class: "tag" }, it.o.name)),
        h("div", { class: "vbody" }), h("div", { class: "hex" }), h("div", { class: "hint vstats" }));
      rec = { el }; virtualEls.set(it.key, rec); root.append(el);
    }
    const f = decode(it.d.frame);
    const display = it.o.display === "auto" ? (f.kind === "angles" ? "servos" : f.kind === "value" ? "meter" : "matrix") : it.o.display;
    const vb = rec.el.querySelector(".vbody");
    if (vb.dataset.display !== display) {
      vb.dataset.display = display;
      vb.replaceChildren(display === "meter" ? h("div", { class: "bigval" }) : h("canvas"));
      if (display === "meter") vb.append(h("div", { class: "bars" }));
    }
    if (display === "matrix" && f.px) drawLEDs(vb.firstChild, f, it.o.color);
    else if (display === "servos") drawServos(vb.firstChild, f.kind === "angles" ? f.data : [f.data]);
    else if (display === "meter") {
      const vals = f.kind === "angles" ? f.data : [f.data];
      vb.firstChild.textContent = vals.length === 1 ? Number(vals[0]).toFixed(2) : "";
      renderBars(vb.lastChild, it.key, vals);
    }
    rec.el.querySelector(".hex").textContent = it.d.packet_hex;
    rec.el.querySelector(".vstats").textContent =
      `${it.d.packet_bytes} B/frame · ${it.d.fps} fps · ${it.d.link_load}% of ${it.o.baud} baud serial`;
  }
}

// ------------------------------------------------------------------ main
function render() {
  $("#cfgpath").textContent = `${state.config_path || "config"} · up ${state.uptime}s`;
  const arm = $("#arm");
  arm.textContent = state.armed ? "● ARMED — click to stop hardware" : "■ DISARMED — click to arm";
  arm.className = "arm " + (state.armed ? "on" : "off");
  renderInputs();
  renderOutputs();
  renderUnrouted();
  renderStreams();
  renderVirtual();
}

connect();
