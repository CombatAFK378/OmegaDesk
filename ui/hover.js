/* OmegaDesk hover layer — shared by the desk and the home page.
   A live dot "signal field" that lights up under the cursor, a reticle that follows it, and a probe
   label that reads the real data-sig of whatever is under the pointer. No dependencies. */
(() => {
"use strict";
const $ = (id) => document.getElementById(id);
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const esc = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
if (!$("field")) return;

const field = (() => {
  const cv = $("field");
  const ctx = cv.getContext("2d");
  /* two layers: a sparse grid of faint dots that is always there, over a dense fine-grain lattice
     that is nearly invisible until the cursor's comet trail lights it up */
  const G = 18, g = 6, LIFE = 1150, FAST = 2.2;   // FAST: px per ms; above it the trail reads as "velocity"
  let W = 0, H = 0, cols = 0, rows = 0, base = null, raf = 0;
  let lit = new Float32Array(0), hot = new Uint8Array(0);
  const trail = [];
  function resize() {
    const dpr = Math.min(2, devicePixelRatio || 1);
    W = innerWidth; H = innerHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cols = Math.ceil(W / g); rows = Math.ceil(H / g);
    lit = new Float32Array(cols * rows); hot = new Uint8Array(cols * rows);
    base = document.createElement("canvas");
    base.width = cv.width; base.height = cv.height;
    const b = base.getContext("2d");
    b.setTransform(dpr, 0, 0, dpr, 0, 0);
    b.fillStyle = "rgba(255,255,255,.03)";             // the grain
    for (let y = g / 2; y < H; y += g) for (let x = g / 2; x < W; x += g) b.fillRect(x - .5, y - .5, 1, 1);
    b.fillStyle = "rgba(255,255,255,.11)";             // the grid
    for (let y = G / 2; y < H; y += G) for (let x = G / 2; x < W; x += G) b.fillRect(x - .7, y - .7, 1.4, 1.4);
    frame();
  }
  function frame() {
    raf = 0;
    const now = performance.now();
    while (trail.length && now - trail[0].t > LIFE) trail.shift();
    ctx.clearRect(0, 0, W, H);
    ctx.drawImage(base, 0, 0, W, H);
    const touched = [];
    for (const p of trail) {
      const age = (now - p.t) / LIFE, R = 120 * (1 - age * .5), k = 1 - age;
      const gx0 = Math.max(0, Math.floor((p.x - R) / g)), gx1 = Math.min(cols - 1, Math.ceil((p.x + R) / g));
      const gy0 = Math.max(0, Math.floor((p.y - R) / g)), gy1 = Math.min(rows - 1, Math.ceil((p.y + R) / g));
      for (let gy = gy0; gy <= gy1; gy++) for (let gx = gx0; gx <= gx1; gx++) {
        const dx = gx * g + g / 2 - p.x, dy = gy * g + g / 2 - p.y, dd = Math.sqrt(dx * dx + dy * dy);
        if (dd >= R) continue;
        const v = k * Math.pow(1 - dd / R, 1.6), i = gy * cols + gx;
        if (lit[i] === 0) touched.push(i);
        if (v > lit[i]) { lit[i] = v; hot[i] = p.sp > FAST ? 1 : 0; }
      }
    }
    for (const i of touched) {
      const v = lit[i], gx = i % cols, gy = (i - gx) / cols, sz = 1 + v * 1.6;
      // fresh trail is signal blue, the tail cools to a deep blue (ember when moving fast)
      ctx.fillStyle = hot[i]
        ? `rgba(230,140,60,${Math.min(1, v * 1.5).toFixed(3)})`
        : `rgba(${Math.round(20 + 40 * v)},${Math.round(110 + 70 * v)},${Math.round(200 + 40 * v)},${Math.min(1, v * 1.5).toFixed(3)})`;
      ctx.fillRect(gx * g + g / 2 - sz / 2, gy * g + g / 2 - sz / 2, sz, sz);
      lit[i] = 0;
    }
    if (trail.length) raf = requestAnimationFrame(frame);
  }
  addEventListener("resize", resize);
  resize();
  return {
    move(x, y) {
      if (REDUCED) return;
      const t = performance.now(), prev = trail[trail.length - 1];
      const sp = prev && t > prev.t ? Math.hypot(x - prev.x, y - prev.y) / (t - prev.t) : 0;
      trail.push({ x, y, t, sp: prev ? prev.sp * .6 + sp * .4 : 0 });
      if (trail.length > 64) trail.shift();
      if (!raf) raf = requestAnimationFrame(frame);
    },
  };
})();

const probe = (() => {
  const ret = $("reticle"), lab = $("probe");
  if (!matchMedia("(pointer: fine)").matches) return { move() {}, hide() {} };
  let tx = -100, ty = -100, x = -100, y = -100, raf = 0, sig = null;
  const ease = REDUCED ? 1 : .24;
  function loop() {
    x += (tx - x) * ease; y += (ty - y) * ease;
    ret.style.transform = `translate(${x}px, ${y}px)`;
    lab.style.transform = `translate(${x + 20}px, ${y + 16}px)`;
    raf = Math.abs(tx - x) + Math.abs(ty - y) > .3 ? requestAnimationFrame(loop) : 0;
  }
  return {
    move(e) {
      tx = e.clientX; ty = e.clientY;
      const t = e.target && e.target.closest ? e.target : null;
      const off = !t || t.closest("input, textarea, select, dialog");
      ret.classList.toggle("on", !off);
      const el = !off && t.closest("[data-sig]");
      const s = el ? el.dataset.sig : null;
      if (s !== sig) {
        sig = s;
        if (s) {
          const [head, ...rest] = s.split(" · ");
          lab.innerHTML = `<b>${esc(head)}</b>${rest.length ? `<span>${esc(rest.join(" · "))}</span>` : ""}`;
        }
        lab.classList.toggle("on", !!s);
        ret.classList.toggle("lock", !!s);
      }
      // flip the label left when it would run off the right edge
      lab.classList.toggle("flip", tx > innerWidth - 300);
      if (!raf) raf = requestAnimationFrame(loop);
    },
    hide() { ret.classList.remove("on"); lab.classList.remove("on"); ret.classList.remove("lock"); sig = null; },
  };
})();

let hudRaf = 0, hudE = null;
document.addEventListener("pointermove", (e) => {
  field.move(e.clientX, e.clientY);
  probe.move(e);
  const card = e.target.closest && e.target.closest(".card");
  if (card) {
    const r = card.getBoundingClientRect();
    card.style.setProperty("--mx", `${e.clientX - r.left}px`);
    card.style.setProperty("--my", `${e.clientY - r.top}px`);
  }
  hudE = e;
  if (!hudRaf) hudRaf = requestAnimationFrame(() => {
    hudRaf = 0;
    if ($("hx")) $("hx").textContent = (hudE.clientX / innerWidth).toFixed(3);
    if ($("hy")) $("hy").textContent = (hudE.clientY / innerHeight).toFixed(3);
  });
}, { passive: true });
document.documentElement.addEventListener("pointerleave", () => probe.hide());
})();
