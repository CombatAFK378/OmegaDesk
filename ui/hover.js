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
  const G = 22, LIFE = 750, FAST = 2.2;   // px per ms: above this the trail reads as "velocity"
  let W = 0, H = 0, base = null, raf = 0;
  const trail = [];
  function resize() {
    const dpr = Math.min(2, devicePixelRatio || 1);
    W = innerWidth; H = innerHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    base = document.createElement("canvas");
    base.width = cv.width; base.height = cv.height;
    const b = base.getContext("2d");
    b.setTransform(dpr, 0, 0, dpr, 0, 0);
    b.fillStyle = "rgba(255,255,255,.075)";
    for (let y = G / 2; y < H; y += G) for (let x = G / 2; x < W; x += G) b.fillRect(x - .75, y - .75, 1.5, 1.5);
    frame();
  }
  function frame() {
    raf = 0;
    const now = performance.now();
    while (trail.length && now - trail[0].t > LIFE) trail.shift();
    ctx.clearRect(0, 0, W, H);
    ctx.drawImage(base, 0, 0, W, H);
    const lit = new Map();
    for (const p of trail) {
      const age = (now - p.t) / LIFE, R = 110 * (1 - age * .45), k = 1 - age;
      const gx0 = Math.max(0, Math.floor((p.x - R) / G)), gx1 = Math.ceil((p.x + R) / G);
      const gy0 = Math.max(0, Math.floor((p.y - R) / G)), gy1 = Math.ceil((p.y + R) / G);
      for (let gy = gy0; gy <= gy1; gy++) for (let gx = gx0; gx <= gx1; gx++) {
        const dx = gx * G + G / 2 - p.x, dy = gy * G + G / 2 - p.y, dd = Math.sqrt(dx * dx + dy * dy);
        if (dd >= R) continue;
        const v = k * Math.pow(1 - dd / R, 2), key = gy * 100000 + gx;
        const cur = lit.get(key);
        if (!cur || v > cur.v) lit.set(key, { v, fast: p.sp > FAST });
      }
    }
    for (const [key, { v, fast }] of lit) {
      const gx = key % 100000, gy = (key - gx) / 100000, sz = 1.5 + v * 2.2;
      ctx.fillStyle = `rgba(${fast ? "245,158,75" : "71,159,250"},${Math.min(1, v * 1.5).toFixed(3)})`;
      ctx.fillRect(gx * G + G / 2 - sz / 2, gy * G + G / 2 - sz / 2, sz, sz);
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
      if (trail.length > 48) trail.shift();
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
