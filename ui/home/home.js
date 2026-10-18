/* OmegaDesk home — reads the desk API for its live status; holds no desk logic. */
"use strict";
(() => {
const $ = (id) => document.getElementById(id);
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const get = (path) => fetch(path).then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.status))));
const set = (id, text, cls) => { const el = $(id); el.textContent = text; el.className = "lv " + (cls || ""); };

function countUp(id, to) {
  const el = $(id);
  if (REDUCED) { el.textContent = to; return; }
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / 900);
    el.textContent = Math.round(to * (1 - Math.pow(1 - k, 3)));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

async function status() {
  get("/health").then((h) => set("s-model", h.llm_model)).catch(() => set("s-model", "api unreachable", "bad"));
  get("/health/graph").then((g) => set("s-graph", g.status === "ok" ? "online" : "down", g.status === "ok" ? "ok" : "bad"))
    .catch(() => set("s-graph", "unreachable", "bad"));
  get("/monitor/alerts").then((a) => {
    countUp("s-alerts", a.alerts.length);
    $("h-al").textContent = String(a.alerts.length).padStart(6, "0");
  }).catch(() => set("s-alerts", "—", "off"));
  get("/cases").then((c) => countUp("s-cases", c.cases.length)).catch(() => set("s-cases", "—", "off"));
  get("/sim/status").then((s) => set("s-sim", s.running ? `live · ${s.ticks} ticks` : "paused", s.running ? "ok" : "off"))
    .catch(() => set("s-sim", "—", "off"));
}

/* legend: how many of the 11 steps each actor owns, so it is plain that the AI does very little */
const steps = [...document.querySelectorAll(".step")];
const ACTORS = [["sim", "simulator"], ["rules", "fixed rules"], ["ai", "AI"], ["code", "code"], ["human", "human"]];
$("legend").innerHTML = ACTORS.map(([k, label]) => {
  const n = steps.filter((s) => s.dataset.actor === k).length;
  return `<button class="actor ${k}" data-actor="${k}" type="button" style="background:none;cursor:pointer" title="Highlight the ${label} steps">${label}<b>${n}</b></button>`;
}).join("");
/* hovering a legend chip spotlights that actor's steps */
$("legend").addEventListener("pointerover", (e) => {
  const b = e.target.closest("[data-actor]");
  steps.forEach((s) => s.classList.toggle("dimmed", !!b && s.dataset.actor !== b.dataset.actor));
});
$("legend").addEventListener("pointerleave", () => steps.forEach((s) => s.classList.remove("dimmed")));

/* scroll reveal + the rail fills as you read */
const io = new IntersectionObserver((entries) => entries.forEach((e) => {
  if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
}), { rootMargin: "0px 0px -12% 0px" });
steps.forEach((s) => io.observe(s));
const story = document.querySelector(".story");
const fill = () => {
  const r = story.getBoundingClientRect();
  const k = Math.max(0, Math.min(1, (innerHeight * .7 - r.top) / r.height));
  story.style.setProperty("--fill", `${(k * 100).toFixed(1)}%`);
};
addEventListener("scroll", fill, { passive: true });
fill();

/* measured-tags ticker: the same tags the desk writes on every case (hover one for its rule) */
const TAGS = [
  ["many pay one", "bad", "FAN_IN · many different payers into one account"],
  ["under the line", "bad", "SUB_THRESHOLD · payments just below ₹50,000"],
  ["pass-through", "bad", "PASS_THROUGH · money in, straight back out"],
  ["one device", "bad", "SHARED_DEVICE · one phone across accounts"],
  ["tied to known fraud", "bad", "RING_MEMBER · device used by confirmed fraud"],
  ["brand-new account", "bad", "NEW_ACCOUNT · opened under 30 days ago"],
  ["known business", "good", "BUSINESS_KYC · the receiver is a verified business"],
  ["regular billing", "good", "REGULAR_CADENCE · the business's normal schedule"],
];
const mq = TAGS.map(([t, c, sig]) => `<span class="mq-item ${c}" data-sig="${sig} · ${c === "bad" ? "looks suspicious" : "looks innocent"}">${t}<span class="mq-sep"></span></span>`).join("");
$("mq-track").innerHTML = mq + mq;   // doubled for a seamless loop

/* ---------- the watcher: fixed rules, run live on the visitor's own cursor ----------
   Your pointer is treated like money moving through the bank. Plain maths, no AI:
   too fast = velocity · steady just under the limit = under the line · circling one spot = many into one ·
   in and straight out of a card = pass-through. A tripped rule raises an alert where it happened. */
const watcher = (() => {
  const cv = $("watch");
  const ctx = cv.getContext("2d");
  let W = 0, H = 0;
  const size = () => {
    const d = Math.min(2, devicePixelRatio || 1);
    W = innerWidth; H = innerHeight;
    cv.width = W * d; cv.height = H * d;
    ctx.setTransform(d, 0, 0, d, 0, 0);
  };
  size();
  addEventListener("resize", size);

  const LIMIT = 2.2;   // px per ms: the same line at which the signal field turns ember
  const LIFE = 2600;
  const RULES = {
    VELOCITY: { plain: "moving unusually fast", rgb: "245,158,75" },
    SUB_THRESHOLD: { plain: "held just under the limit", rgb: "245,158,75" },
    FAN_IN: { plain: "circling into one point", rgb: "242,85,90" },
    PASS_THROUGH: { plain: "in and straight out of a card", rgb: "242,85,90" },
  };
  const pts = [], last = {}, marks = [];
  let trips = 0, raf = 0;

  function trip(code, x, y) {
    const now = performance.now();
    if (now - (last[code] || -1e9) < LIFE) return;     // one alert per rule at a time, like a real cooldown
    last[code] = now;
    trips++;
    marks.push({ code, x, y, t: now, id: `AL-YOU-${String(trips).padStart(3, "0")}` });
    $("h-trip").textContent = String(trips).padStart(6, "0");
    const hl = $("h-last");
    hl.textContent = `▲ ${code} · ${RULES[code].plain}`;
    hl.classList.remove("fresh"); void hl.offsetWidth; hl.classList.add("fresh");
    if (!raf) raf = requestAnimationFrame(draw);
  }

  function draw() {
    raf = 0;
    const now = performance.now();
    ctx.clearRect(0, 0, W, H);
    for (let i = marks.length - 1; i >= 0; i--) {
      const m = marks[i], age = (now - m.t) / LIFE;
      if (age >= 1) { marks.splice(i, 1); continue; }
      const a = 1 - age, rgb = RULES[m.code].rgb, ease = 1 - Math.pow(1 - Math.min(1, age * 2.2), 3);
      ctx.strokeStyle = `rgba(${rgb},${(a * .7).toFixed(3)})`;
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(m.x, m.y, 8 + ease * 46, 0, Math.PI * 2); ctx.stroke();
      ctx.beginPath(); ctx.arc(m.x, m.y, 6, 0, Math.PI * 2); ctx.stroke();
      ctx.fillStyle = `rgba(${rgb},${a.toFixed(3)})`;
      ctx.beginPath(); ctx.arc(m.x, m.y, 2.5, 0, Math.PI * 2); ctx.fill();
      // corner brackets: the watcher "locks" the spot
      const r = 14, b = 5;
      ctx.beginPath();
      [[-1, -1], [1, -1], [1, 1], [-1, 1]].forEach(([sx, sy]) => {
        ctx.moveTo(m.x + sx * r, m.y + sy * (r - b)); ctx.lineTo(m.x + sx * r, m.y + sy * r); ctx.lineTo(m.x + sx * (r - b), m.y + sy * r);
      });
      ctx.stroke();
      ctx.font = '500 10.5px "JetBrains Mono", monospace';
      ctx.fillStyle = `rgba(232,237,245,${a.toFixed(3)})`;
      ctx.fillText(`${m.id} · ${m.code}`, m.x + 22, m.y - 10);
      ctx.fillStyle = `rgba(133,145,166,${a.toFixed(3)})`;
      ctx.fillText(`fixed rule · ${RULES[m.code].plain}`, m.x + 22, m.y + 4);
    }
    if (marks.length) raf = requestAnimationFrame(draw);
  }

  function move(e) {
    const t = performance.now(), x = e.clientX, y = e.clientY, p = pts[pts.length - 1];
    const raw = p ? Math.hypot(x - p.x, y - p.y) / Math.max(1, t - p.t) : 0;
    const sp = p ? p.sp * .7 + raw * .3 : 0;
    pts.push({ x, y, t, sp });
    while (pts.length && t - pts[0].t > 1600) pts.shift();

    if (sp > LIMIT) trip("VELOCITY", x, y);

    const win = pts.filter((q) => t - q.t < 1100);
    if (win.length > 14 && t - win[0].t > 950 && win.every((q) => q.sp > LIMIT * .45 && q.sp < LIMIT)) trip("SUB_THRESHOLD", x, y);

    if (pts.length > 24) {
      let cx = 0, cy = 0, len = 0, maxR = 0;
      pts.forEach((q) => { cx += q.x; cy += q.y; });
      cx /= pts.length; cy /= pts.length;
      pts.forEach((q, i) => {
        maxR = Math.max(maxR, Math.hypot(q.x - cx, q.y - cy));
        if (i) len += Math.hypot(q.x - pts[i - 1].x, q.y - pts[i - 1].y);
      });
      if (len > 700 && maxR < 95) trip("FAN_IN", cx, cy);
    }
  }
  return { move, trip };
})();

if (matchMedia("(pointer: fine)").matches && !REDUCED) {
  document.addEventListener("pointermove", watcher.move, { passive: true });
  document.querySelectorAll(".s-body, .who-card").forEach((el) => {
    el.addEventListener("pointerenter", () => { el._in = performance.now(); });
    el.addEventListener("pointerleave", (e) => {
      if (el._in && performance.now() - el._in < 200) watcher.trip("PASS_THROUGH", e.clientX, e.clientY);
    });
  });
}

status();
setInterval(status, 15000);
})();
