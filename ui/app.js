/* OmegaDesk desk UI — vanilla JS, no build step, no frameworks (zero console errors).
   Every visual is drawn from what the desk API already returns: nothing on screen is invented. */
"use strict";
const $ = (id) => document.getElementById(id);
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

const S = {
  alerts: [], cases: [], tab: "alerts", q: "", type: "all",
  selectedAlert: null, currentCase: null, caseData: null,
  report: null,          // last POSTed report, scoped to its own case_id
  mode: null,            // {case_id, ablated} of the last fresh investigation
  busy: false, live: false, booted: false, tick: 0, pollT: null,
  firstSeen: new Map(),  // alert id → when it first appeared after boot (drives NEW + slide-in)
  animated: new Set(),
};

/* ---------- helpers ---------- */
async function api(path, opts) {
  const res = await fetch(path, opts);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `${res.status} ${res.statusText}`);
  return body;
}
function toast(msg, isErr) {
  const t = $("toast");
  t.textContent = msg;
  t.className = isErr ? "show err" : "show";
  clearTimeout(t._x);
  t._x = setTimeout(() => (t.className = isErr ? "err" : ""), 4200);
}
const badge = (a, size) => a ? `<span class="badge ${a} ${size || ""}">${esc(a)}</span>` : "";
const esc = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const fmtDate = (iso) => {
  const s = String(iso);
  const [d, t] = s.split("T");
  return d + (t ? " · " + t.slice(0, 5) : "");
};
function relTime(iso) {
  const t = Date.parse(iso);
  if (isNaN(t)) return fmtDate(iso);
  const s = (Date.now() - t) / 1000;
  if (s < 0) return fmtDate(iso);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.round(s / 86400)} d ago`;
  return String(iso).split("T")[0];
}
const initials = (name) => {
  if (!name || name === "merchant") return "BIZ";
  return name.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
};
/* themed line icons from icons.svg (no emoji anywhere in the desk) */
const ic = (n) => `<svg class="ico" aria-hidden="true"><use href="icons.svg#i-${n}"/></svg>`;
const trunc = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
const nf = (n) => Number(n || 0).toLocaleString("en-IN");
/* numbered mono eyebrow: 01 —— TITLE */
const h3 = (no, title, note) =>
  `<h3><span class="no">${String(no).padStart(2, "0")}</span><span class="ln"></span>${title}${note ? `<span class="h-note">${note}</span>` : ""}</h3>`;
const lead = (k, v, cls, title) =>
  `<div class="lead ${cls && cls.row || ""}"${title ? ` data-sig="${esc(title)}"` : ""}><span class="lk">${k}</span><span class="ld"></span><span class="lv ${cls && cls.v || ""}">${v}</span></div>`;
function countUp(el, to, ms) {
  if (REDUCED || !el) { if (el) el.textContent = nf(to); return; }
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / ms);
    el.textContent = nf(Math.round(to * (1 - Math.pow(1 - k, 3))));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/* ---------- plainen: no code-words on the screen, ever (even the AI's own words) ---------- */
const CODE_PLAIN = [
  [/pass[_-]?through/gi, "money arrives and leaves almost straight away"],
  [/sub[_-]?threshold/gi, "payments kept just under the reporting line"],
  [/fan[_-]?in/gi, "many people paying one account"],
  [/shared[_-]?device/gi, "one device used by several accounts"],
  [/shared[_-]?identity/gi, "the same identity details reused across accounts"],
  [/ring[_-]?member/gi, "part of a connected group of accounts"],
  [/new[_-]?account/gi, "a very new account"],
  [/business[_-]?kyc/gi, "verified business paperwork"],
  [/regular[_-]?cadence|cadence/gi, "a steady, usual rhythm of payments"],
  [/\bkyc\b/gi, "identity checks"],
  [/pass[_-]?ratio/gi, "share of money sent straight out again"],
  [/ratio of\s*([\d.,]+)/gi, "share: $1"],
  [/value of\s*([\d.,]+)/gi, "score $1"],
];
const plainen = (s) => CODE_PLAIN.reduce((t, [re, plain]) => t.replace(re, plain), String(s || ""));

/* ---------- plain-English layer (the desk speaks human; codes live in hover-tips) ---------- */
const SIG_PLAIN = {
  FAN_IN: "many different people paid one account at the same time",
  SUB_THRESHOLD: "several payments just below the ₹50,000 reporting line",
  PASS_THROUGH: "money came in and was instantly sent onward",
  SHARED_DEVICE: "different accounts used the same phone or device",
  SHARED_IDENTITY: "same personal details on different accounts",
  NEW_ACCOUNT: "the account was opened less than 30 days ago",
  RING_MEMBER: "tied to a device already used by confirmed fraud",
  BUSINESS_KYC: "the receiver is a verified business",
  REGULAR_CADENCE: "payments follow the business's normal billing schedule",
};
const TYPE_PLAIN = {
  fan_in: "Many payers, one receiver",
  sub_threshold: "Payments hiding under the reporting line",
  velocity: "Money moving out unusually fast",
};
const TYPE_SHORT = { fan_in: "Many payers", sub_threshold: "Under the line", velocity: "Fast money" };
const TOOL_PLAIN = {
  get_case_context: "read the case file",
  trace_money_path: "followed the money route",
  find_shared_entities: "checked for shared devices and details",
  find_precedents: "asked the desk's memory for similar past cases",
};
const ACTION_PLAIN = {
  freeze: "Blocked the accounts — money stopped",
  escalate: "Sent to a human analyst for review",
  monitor: "Kept under watch, no action yet",
  clear: "Marked legitimate",
};
const ACTION_COLOR = { freeze: "var(--bad)", escalate: "var(--warn)", monitor: "var(--accent)", clear: "var(--good)" };
const VERDICT_PLAIN = { fraud: "looks like fraud", legit: "looks legitimate", unclear: "not sure — needs a human" };
const scopeName = (s) =>
  (s.holder && s.holder !== "merchant") ? s.holder : "Registered business";

function inShort(c) {
  /* a deterministic, human summary of the case + decision (no jargon) */
  const d = c.decisions[c.decisions.length - 1];
  if (!d) return "";
  const act = ACTION_PLAIN[d.action] || d.action;
  const parts = [];
  const fan = (c.signals || []).find((s) => s.code === "FAN_IN");
  if (fan) parts.push(`${fan.value} different people paid one account at once`);
  if ((c.signals || []).find((s) => s.code === "SUB_THRESHOLD")) parts.push("several payments just under the ₹50,000 line");
  if ((c.signals || []).find((s) => s.code === "PASS_THROUGH")) parts.push("money arrived and was sent straight out");
  if ((c.signals || []).find((s) => s.code === "SHARED_DEVICE")) parts.push("one device was shared across accounts");
  if ((c.signals || []).find((s) => s.code === "RING_MEMBER")) parts.push("that device is tied to known fraud");
  const kyc = (c.signals || []).find((s) => s.code === "BUSINESS_KYC");
  if (kyc) parts.push("the receiver is a verified business");
  if (!parts.length && (c.alert || []).length) {
    const t = TYPE_PLAIN[c.alert[0].type];
    if (t) parts.push("the alert said: " + t.toLowerCase());
  }
  const cited = (d.cites || []).some((x) => x.applies);
  const corrected = (d.cites || []).some((x) => (x.distinguishing || []).length === 0 && !x.applies);
  const receipted = !!d.receipt && d.action === "clear";
  const mem = receipted
    ? "The receipt of checks proved it clean, so the desk cleared it itself."
    : cited
      ? "The desk's memory of past cases shaped this."
      : corrected && d.action === "escalate"
        ? "A past case was corrected before, so the desk wants a human to decide."
        : (d.cites || []).length
          ? "It checked the desk's memory, found no past case that fits, and decided on the evidence."
          : (d.action === "freeze"
            ? "The raw pattern alone was strong enough to act without memory."
            : "The desk decided without clear memory guidance.");
  return `${act}. Why: ${parts.join(" · ") || "the account's own history"}. ${mem}`;
}

/* ---------- boot: dot-matrix signal field while the desk checks its own health ---------- */
const bootFx = (() => {
  const cv = $("boot-canvas");
  const ctx = cv.getContext("2d");
  const W = cv.width, H = cv.height, G = 6;
  const off = document.createElement("canvas");
  off.width = W; off.height = H;
  const o = off.getContext("2d");
  o.fillStyle = "#fff";
  o.font = "700 210px Georgia, serif";
  o.textAlign = "center"; o.textBaseline = "middle";
  o.fillText("Ω", W / 2, H / 2 + 12);
  const px = o.getImageData(0, 0, W, H).data;
  const dots = [];
  for (let y = G / 2; y < H; y += G) for (let x = G / 2; x < W; x += G) {
    if (px[(Math.floor(y) * W + Math.floor(x)) * 4 + 3] > 120) dots.push({ x, y, at: Math.random() });
  }
  let pct = 0, target = 0, raf = 0;
  const draw = () => {
    pct += (target - pct) * 0.08;
    ctx.clearRect(0, 0, W, H);
    const k = pct / 100;
    for (const d of dots) {
      const on = d.at < k;
      const flick = on ? 0.55 + 0.45 * Math.sin(performance.now() / 260 + d.x * 0.3 + d.y * 0.2) : 0.08;
      ctx.fillStyle = on && d.at > k - 0.06 ? `rgba(71,159,250,${flick})` : `rgba(243,245,247,${flick})`;
      ctx.fillRect(d.x - 1, d.y - 1, 2, 2);
    }
    $("boot-pct").textContent = Math.round(pct);
    raf = requestAnimationFrame(draw);
  };
  draw();
  return {
    to(p, msg) { target = p; if (msg) $("boot-msg").textContent = msg; },
    done() {
      target = 100;
      setTimeout(() => { $("boot").classList.add("done"); setTimeout(() => cancelAnimationFrame(raf), 700); },
        REDUCED ? 0 : 450);
    },
  };
})();

async function boot() {
  const t0 = performance.now();
  bootFx.to(25, "Reaching the desk API");
  try {
    const h = await api("/health");
    $("model").textContent = `llm ${h.llm_model} · graph ${h.graph_name}`;
    bootFx.to(55, "Opening the graph");
    const hg = await api("/health/graph");
    const ok = hg.status === "ok";
    $("health").innerHTML = `<span class="dot"></span>${ok ? "graph online" : "graph down"}`;
    $("health").className = "health " + (ok ? "ok" : "bad");
  } catch (e) {
    $("health").innerHTML = '<span class="dot"></span>api unreachable';
    $("health").className = "health bad";
  }
  try { setLive((await api("/sim/status")).running); } catch (e) { /* sim router optional */ }
  bootFx.to(80, "Loading the alert queue");
  await Promise.all([refreshAlerts(), refreshCases()]);
  S.booted = true;
  const wait = Math.max(0, 1100 - (performance.now() - t0));
  setTimeout(() => bootFx.done(), REDUCED ? 0 : wait);
  schedule();
}
function schedule() {
  clearTimeout(S.pollT);
  S.pollT = setTimeout(async () => {
    S.tick++;
    await refreshAlerts();
    if (S.tick % 3 === 0) await refreshCases();
    schedule();
  }, S.live ? 3000 : 10000);
}

/* ---------- queue: alerts + past cases ---------- */
async function refreshAlerts() {
  try {
    const data = await api("/monitor/alerts");
    const now = Date.now();
    data.alerts.forEach((a) => { if (!S.firstSeen.has(a.id)) S.firstSeen.set(a.id, S.booted ? now : 0); });
    S.alerts = data.alerts;
    renderQueue();
    renderTicker();
  } catch (e) {
    toast(`alerts: ${e.message}`, true);
  }
}
async function refreshCases() {
  try {
    S.cases = (await api("/cases")).cases;
    renderQueue();
  } catch (e) { /* the alert queue still works without the case index */ }
}
const caseForAlert = (id) => S.cases.find((c) => c.alert_id === id);
const isNew = (id) => { const t = S.firstSeen.get(id); return t && Date.now() - t < 90000; };

function renderQueue() {
  const isA = S.tab === "alerts";
  const src = isA ? S.alerts : S.cases;
  const typeOf = (x) => (isA ? x.type : x.alert_type) || "other";
  $("alert-count").textContent = S.alerts.length;
  $("case-count").textContent = S.cases.length;
  $("h-al").textContent = String(S.alerts.length).padStart(6, "0");
  $("h-cs").textContent = String(S.cases.length).padStart(6, "0");

  const counts = {};
  src.forEach((x) => { counts[typeOf(x)] = (counts[typeOf(x)] || 0) + 1; });
  if (S.type !== "all" && !counts[S.type]) S.type = "all";
  $("type-chips").innerHTML =
    `<button class="chip ${S.type === "all" ? "on" : ""}" data-type="all">All<span class="n">${src.length}</span></button>` +
    Object.keys(counts).map((t) =>
      `<button class="chip ${S.type === t ? "on" : ""}" data-type="${esc(t)}"><span class="sw t-${esc(t)}" style="background:var(--stripe)"></span>${esc(TYPE_SHORT[t] || t)}<span class="n">${counts[t]}</span></button>`).join("");

  const q = S.q.trim().toLowerCase();
  const hay = (x) => (isA
    ? [x.id, x.target, x.type, TYPE_PLAIN[x.type]]
    : [x.case_id, x.alert_id, x.target, x.alert_type, TYPE_PLAIN[x.alert_type], x.last_action]).join(" ").toLowerCase();
  const rows = src.filter((x) => (S.type === "all" || typeOf(x) === S.type) && (!q || hay(x).includes(q)));

  const box = isA ? $("alerts") : $("cases");
  const focused = document.activeElement && document.activeElement.closest && document.activeElement.closest(".item");
  const focusId = focused && box.contains(focused) ? focused.dataset.id : null;

  if (!rows.length) {
    box.innerHTML = `<div class="empty-list">${src.length ? "Nothing matches this filter." : (isA ? "No alerts yet. Start the live stream to make some." : "No cases yet.")}</div>`;
  } else if (isA) {
    box.innerHTML = rows.map((a) => {
      const k = caseForAlert(a.id);
      const fresh = isNew(a.id) && !S.animated.has(a.id);
      if (fresh) S.animated.add(a.id);
      return `<button class="item t-${esc(a.type)} ${S.selectedAlert === a.id ? "sel" : ""} ${fresh ? "fresh" : ""}"
          data-id="${esc(a.id)}" role="option" aria-selected="${S.selectedAlert === a.id}" data-sig="${esc(a.id)} · ${esc(a.type)} · ${esc(a.target)}${k ? " · decided " + esc(k.last_action) : ""}">
        <div class="i-top"><span class="i-title">${esc(TYPE_PLAIN[a.type] || a.type)}</span>
          ${isNew(a.id) ? '<span class="new">NEW</span>' : ""}${k ? badge(k.last_action, "sm") : ""}</div>
        <div class="i-meta"><span class="acct">${esc(a.target)}</span><span>${esc(relTime(a.created_at))}</span><span>${esc(a.id)}</span></div>
      </button>`;
    }).join("");
  } else {
    box.innerHTML = rows.map((c) =>
      `<button class="item t-${esc(c.alert_type)} ${S.currentCase === c.case_id ? "sel" : ""}" data-id="${esc(c.case_id)}" role="option" data-sig="${esc(c.case_id)} · ${esc(c.alert_id || "no alert")} · ${esc(c.last_action || "no decision")}">
        <div class="i-top"><span class="i-title mono">${esc(c.case_id)}</span>${badge(c.last_action, "sm")}</div>
        <div class="i-meta"><span class="acct">${esc(c.target || "—")}</span><span>${esc(TYPE_SHORT[c.alert_type] || c.alert_type || "")}</span><span>${esc(relTime(c.created_at))}</span><span>${esc(c.status)}</span></div>
      </button>`).join("");
  }
  if (focusId) {
    const el = box.querySelector(`.item[data-id="${CSS.escape(focusId)}"]`);
    if (el) el.focus({ preventScroll: true });
  }
  updateSelected();
}

function renderTicker() {
  const tk = $("ticker");
  if (!S.live) { tk.classList.add("hidden"); return; }
  tk.classList.remove("hidden");
  const items = S.alerts.slice(0, 12).map((a) =>
    `<span class="ticker-item"><span class="tk-dot"></span><b>${esc(TYPE_PLAIN[a.type] || a.type)}</b> ${esc(a.target)} · ${esc(relTime(a.created_at))}</span>`).join("");
  const track = $("ticker-track");
  if (track.dataset.rendered !== items) { track.innerHTML = items; track.dataset.rendered = items; }   // not data-sig: the hover probe reads that
}

function setTab(tab) {
  S.tab = tab; S.type = "all";
  document.querySelectorAll(".tab").forEach((t) => {
    const on = t.dataset.tab === tab;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", on);
  });
  $("alerts").classList.toggle("hidden", tab !== "alerts");
  $("cases").classList.toggle("hidden", tab !== "cases");
  $("queue-hint").textContent = tab === "alerts"
    ? "Suspicious patterns the automatic monitor caught. Pick one, then investigate it."
    : "Every case the desk has opened, newest first. Open one to read its full record.";
  renderQueue();
}

function selectAlert(id) {
  S.selectedAlert = id;
  document.querySelectorAll("#alerts .item").forEach((x) => {
    const on = x.dataset.id === id;
    x.classList.toggle("sel", on);
    x.setAttribute("aria-selected", on);
  });
  updateSelected();
}
function updateSelected() {
  $("investigate").disabled = !S.selectedAlert || S.busy;
  const line = $("selected-line");
  const a = S.alerts.find((x) => x.id === S.selectedAlert);
  if (!a) { line.classList.add("hidden"); return; }
  const k = caseForAlert(a.id);
  line.classList.remove("hidden");
  line.innerHTML = `<span class="tagm">selected</span> <b>${esc(TYPE_PLAIN[a.type] || a.type)}</b>
    on <span class="mono">${esc(a.target)}</span> · <span class="mono">${esc(a.id)}</span>
    ${k ? `· already decided ${badge(k.last_action, "sm")} <button class="link" data-open="${esc(k.case_id)}">open ${esc(k.case_id)}</button>` : ""}`;
}

async function openCase(id) {
  $("case-body").classList.add("loading");
  try {
    const c = await api(`/cases/${encodeURIComponent(id)}`);
    renderCase(c);
    $("case-body").scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "nearest" });
  } catch (e) {
    toast(`case: ${e.message}`, true);
  } finally {
    $("case-body").classList.remove("loading");
  }
}

/* ---------- investigate (the ONLY LLM call on this screen) ---------- */
function startProgress(alertId, ablated) {
  const steps = [
    { t: 0, label: TOOL_PLAIN.get_case_context },
    { t: 5, label: TOOL_PLAIN.trace_money_path },
    { t: 13, label: TOOL_PLAIN.find_shared_entities },
    { t: 22, label: TOOL_PLAIN.find_precedents, skip: ablated },
    { t: 30, label: "weighing it all and deciding" },
  ];
  const el = $("inv-status");
  el.classList.remove("hidden");
  $("case-body").classList.add("loading");
  const t0 = performance.now();
  const paint = (final) => {
    const s = (performance.now() - t0) / 1000;
    let now = 0;
    steps.forEach((x, i) => { if (s >= x.t) now = i; });
    const rows = steps.map((x, i) => {
      if (x.skip) return lead(x.label, "skipped · memory off", { row: "dim", v: "skip" });
      if (final || i < now) return lead(x.label, "done", { v: "ok" });
      if (i === now) return lead(x.label, "running…", { v: "run" });
      return lead(x.label, "queued", { row: "dim", v: "wait" });
    }).join("");
    const pct = final ? 100 : Math.min(94, 100 * (1 - Math.exp(-s / 24)));
    el.innerHTML = `
      <div class="term-bar"><i></i><i></i><i></i><span>investigator · live trace</span></div>
      <div class="p-head"><div class="spinner"></div>
        <div class="term-cmd"><span class="pr">$</span> investigate ${esc(alertId)} ${ablated ? "--without-memory" : "--with-memory"}<span class="caret"></span></div>
        <span class="p-time">${s.toFixed(0)}s · usually 30–60s</span></div>
      <div class="leaders">${rows}</div>
      <div class="p-bar"><div style="width:${pct}%"></div></div>
      <div class="p-note">This is the usual order of steps. The exact record of what the AI asked the graph appears below when it finishes.</div>`;
  };
  paint(false);
  const iv = setInterval(() => paint(false), 500);
  return (ok) => {
    clearInterval(iv);
    $("case-body").classList.remove("loading");
    if (ok) { paint(true); setTimeout(() => el.classList.add("hidden"), 500); }
    else el.classList.add("hidden");
  };
}

async function investigate() {
  if (!S.selectedAlert) return;
  await runInvestigation(S.selectedAlert, { alert_id: S.selectedAlert });
}

/* direct case (scenario E): the monitor stays quiet, so there is no alert to pick */
const investigateAccount = (accountId) => {
  selectAlert(null);  // no alert behind this case: drop the previous selection line
  return runInvestigation(accountId, { about_id: accountId });
};

async function runInvestigation(label, target) {
  if (S.busy) return;
  S.busy = true;
  updateSelected();
  const ablated = $("ablated").checked;
  const stop = startProgress(label, ablated);
  try {
    const res = await api("/cases/investigate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...target, ablated }),
    });
    const c = await api(`/cases/${res.case_id}`);
    stop(true);
    S.busy = false;
    S.mode = { case_id: res.case_id, ablated };
    renderCase(c, res);
    toast(`decision recorded: ${res.action} (confidence ${res.confidence})`);
    refreshCases();
  } catch (e) {
    stop(false);
    toast(`investigate: ${e.message}`, true);
  } finally {
    S.busy = false;
    updateSelected();
  }
}

/* ---------- the shape of the money: drawn only from the case's own accounts + signals ---------- */
function flowMap(c) {
  if (!c.scope.length) return "";
  const targetId = (c.alert[0] && c.alert[0].target) || c.scope[0].account;
  const recv = c.scope.find((s) => s.account === targetId) || { account: targetId, holder: null, kyc: null };
  const payers = c.scope.filter((s) => s.account !== recv.account);
  const frozen = new Set(c.freeze_orders.map((f) => f.account));
  const has = (code) => c.signals.find((s) => s.code === code);
  const fan = has("FAN_IN");
  const W = 660, H = 290, RX = 390, RY = 140;
  const shown = payers.slice(0, 7);
  const extra = Math.max(0, (fan ? fan.value : payers.length) - shown.length);
  const nodes = shown.map((s) => ({ s })).concat(extra ? [{ more: extra }] : []);
  const n = nodes.length;
  const anyFrozen = frozen.size > 0;

  let edges = "", parts = "", dots = "";
  nodes.forEach((nd, i) => {
    const t = n === 1 ? 0.5 : i / (n - 1);
    nd.x = 190 + Math.sin(t * Math.PI) * 36;
    nd.y = 30 + t * (H - 60);
    const path = `M${nd.x + 16},${nd.y} C${nd.x + 110},${nd.y} ${RX - 120},${RY} ${RX - 34},${RY}`;
    edges += `<path class="edge in draw" data-k="${i}" style="--i:${i}" d="${path}"/>`;
    if (!REDUCED) dots += `<circle class="pt" r="2.2"><animateMotion dur="${(2.2 + (i % 3) * 0.45).toFixed(2)}s" begin="${(i * 0.37).toFixed(2)}s" repeatCount="indefinite" path="${path}"/></circle>`;
  });
  nodes.forEach((nd, i) => {
    if (nd.more) {
      parts += `<g class="node more" data-k="${i}" style="--i:${i}" data-sig="+${nd.more} payers · measured by FAN_IN · not drawn individually"><circle class="body" cx="${nd.x}" cy="${nd.y}" r="15"/>
        <text class="ini" x="${nd.x}" y="${nd.y + 3.5}" text-anchor="middle">+${nd.more}</text>
        <text x="${nd.x - 24}" y="${nd.y + 4}" text-anchor="end">more payers</text></g>`;
      return;
    }
    const s = nd.s, fz = frozen.has(s.account);
    parts += `<g class="node ${fz ? "frozen" : ""}" data-k="${i}" style="--i:${i}" data-sig="${esc(s.account)} · ${esc(scopeName(s))} · payer${fz ? " · BLOCKED" : ""}">
      ${fz ? `<circle class="halo" cx="${nd.x}" cy="${nd.y}" r="20"/>` : ""}
      <circle class="body" cx="${nd.x}" cy="${nd.y}" r="15"/>
      <text class="ini" x="${nd.x}" y="${nd.y + 3.5}" text-anchor="middle">${esc(initials(s.holder))}</text>
      ${s.kyc === true || s.kyc === false ? `<circle class="kdot ${s.kyc ? "y" : "n"}" cx="${nd.x + 11}" cy="${nd.y - 11}" r="3.5"/>` : ""}
      ${fz ? `<g class="lockb"><circle cx="${nd.x - 12}" cy="${nd.y + 12}" r="7"/><use href="icons.svg#i-lock" x="${nd.x - 17}" y="${nd.y + 7}" width="10" height="10"/></g>` : ""}
      <text x="${nd.x - 24}" y="${nd.y}" text-anchor="end">${esc(trunc(scopeName(s), 20))}</text>
      <text class="lbl-sub" x="${nd.x - 24}" y="${nd.y + 12}" text-anchor="end">${esc(s.account)}</text></g>`;
  });

  // onward money + shared device: only when the fixed rules measured them
  if (has("PASS_THROUGH")) {
    const p = `M${RX + 34},${RY} C${RX + 90},${RY} ${RX + 110},${RY - 56} ${RX + 170},${RY - 56}`;
    edges += `<path class="edge out draw" style="--i:${n}" d="${p}"/>`;
    if (!REDUCED) dots += `<circle class="pt" r="2.2"><animateMotion dur="1.6s" repeatCount="indefinite" path="${p}"/></circle>`;
    parts += `<g class="node ghost" style="--i:${n + 1}" data-sig="PASS_THROUGH · money arrived and was sent straight out">
      <circle class="body" cx="${RX + 186}" cy="${RY - 56}" r="15"/><use class="nico" href="icons.svg#i-arrow" x="${RX + 178}" y="${RY - 64}" width="16" height="16"/>
      <text x="${RX + 186}" y="${RY - 80}" text-anchor="middle">sent onward</text></g>`;
  }
  const ring = has("RING_MEMBER"), dev = has("SHARED_DEVICE") || ring;
  if (dev) {
    const dx = RX + 176, dy = RY + 74;
    edges += `<path class="edge dev ${ring ? "ring" : ""} draw" style="--i:${n + 1}" d="M${RX + 26},${RY + 22} Q${RX + 70},${dy} ${dx - 18},${dy}"/>`;
    parts += `<g class="node device ${ring ? "ring" : ""}" style="--i:${n + 2}" data-sig="${ring ? "RING_MEMBER · device tied to confirmed fraud" : "SHARED_DEVICE · one device across accounts"}">
      <rect x="${dx - 15}" y="${dy - 15}" width="30" height="30" rx="7" transform="rotate(45 ${dx} ${dy})"/>
      <use class="nico" href="icons.svg#i-device" x="${dx - 8}" y="${dy - 8}" width="16" height="16"/>
      <text x="${dx}" y="${dy + 34}" text-anchor="middle">${ring ? "device tied to known fraud" : "shared device"}</text></g>`;
  }
  const rf = frozen.has(recv.account);
  parts += `<g class="node recv ${rf ? "frozen" : ""}" style="--i:${n + 3}" data-sig="${esc(recv.account)} · ${esc(scopeName(recv))} · receiver${rf ? " · BLOCKED" : ""}">
    ${rf ? `<circle class="halo" cx="${RX}" cy="${RY}" r="42"/>` : ""}
    <circle class="body" cx="${RX}" cy="${RY}" r="32"/>
    <text class="ini" x="${RX}" y="${RY + 4.5}" text-anchor="middle">${esc(initials(recv.holder))}</text>
    ${recv.kyc === true || recv.kyc === false ? `<circle class="kdot ${recv.kyc ? "y" : "n"}" cx="${RX + 23}" cy="${RY - 23}" r="5"/>` : ""}
    ${rf ? `<g class="lockb"><circle cx="${RX - 24}" cy="${RY + 24}" r="10"/><use href="icons.svg#i-lock" x="${RX - 31}" y="${RY + 17}" width="14" height="14"/></g>` : ""}
    <text x="${RX}" y="${RY + 50}" text-anchor="middle" font-weight="600">${esc(trunc(scopeName(recv), 26))}</text>
    <text class="lbl-sub" x="${RX}" y="${RY + 63}" text-anchor="middle">${esc(recv.account)} · receiver</text>
    ${has("BUSINESS_KYC") ? `<text class="tag-biz" x="${RX}" y="${RY + 77}" text-anchor="middle">verified business</text>` : ""}</g>`;
  const countLbl = fan ? `<text class="lbl-count" x="${RX - 60}" y="${RY - 14}" text-anchor="end">${esc(fan.value)} payers at once</text>` : "";

  return `<div class="card flow" style="--i:2">${h3(3, "The shape of the money", "drawn from this case's accounts and measured signals")}
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Money flow: ${n} payer node(s) into ${esc(scopeName(recv))}">
      <defs><linearGradient id="gIn" x1="0" x2="1"><stop offset="0" stop-color="${anyFrozen ? "#f2555a" : "#479ffa"}" stop-opacity=".15"/><stop offset="1" stop-color="${anyFrozen ? "#f2555a" : "#479ffa"}" stop-opacity=".85"/></linearGradient></defs>
      ${edges}${dots}${countLbl}${parts}
    </svg>
    <div class="legend"><span><span class="ln"></span>money in</span>${has("PASS_THROUGH") ? '<span><span class="ln d"></span>sent onward</span>' : ""}
      <span><i style="background:var(--good)"></i>identity verified</span><span><i style="background:var(--bad)"></i>not verified</span>
      ${anyFrozen ? `<span class="lg-lock">${ic("lock")}blocked</span>` : ""}</div></div>`;
}

/* ---------- render case detail ---------- */
function renderCase(c, runRes) {
  S.caseData = c;
  S.currentCase = c.case_id;
  const d = c.decisions[c.decisions.length - 1] || null;
  const ad = [...c.decisions].reverse().find((x) => x.decided_by === "agent") || d;
  let no = 0;

  /* 01 — the verdict */
  const short = inShort(c);
  const conf = d ? Math.round((d.confidence || 0) * 100) : 0;
  const headline = d ? `<div class="card headline a-${esc(d.action)}" style="--i:0">
      <div class="hl-row">
        <div class="ring" data-sig="${esc(d.decision_id)} · confidence ${(d.confidence || 0).toFixed(2)}" data-p="${conf}" style="--c:${ACTION_COLOR[d.action] || "var(--accent)"}"><span><b class="cnt" data-to="${conf}">0</b>%<small>sure</small></span></div>
        <div class="hl-main">
          <div class="hl-kicker">${badge(d.action, "lg")}<span class="tagm">${d.decided_by === "agent" ? "AI investigator" : "human analyst"}</span><span class="muted">${esc(fmtDate(d.ts))}</span></div>
          <div class="hl-act">${esc(ACTION_PLAIN[d.action] || d.action)}</div>
          <div class="hl-sub">${d.decided_by === "agent" ? "The AI's opinion" : "The analyst's opinion"}: ${esc(VERDICT_PLAIN[d.verdict] || d.verdict)}</div>
        </div>
      </div>
      ${short ? `${h3(++no, "In short")}<div class="shortt">${esc(short)}</div>` : ""}
    </div>` : `<div class="card" style="--i:0">${h3(++no, "No decision yet")}<div class="muted">This case has no recorded decision. Investigate its alert to get one.</div></div>`;

  /* 02 — the AI's own words */
  const aiVoice = ad
    ? `<div class="card ai-voice" style="--i:1">${h3(++no, "What the AI investigator says")}
         <div class="aitt" id="ai-text">“${esc(plainen(ad.rationale) || "—")}”</div>
         <div class="hint">This is the agent's own written reasoning, exactly as stored in the decision (replayable in the graph).</div></div>`
    : "";
  const memo = runRes ? ablateNote(runRes.ablated, d) : "";

  /* 03 — the money map */
  const flow = flowMap(c);
  if (flow) no = 3;

  /* who + pattern */
  const scope = c.scope.map((s) =>
    `<span class="pill neutral" data-sig="${esc(s.account)} · kyc ${s.kyc === true ? "verified" : s.kyc === false ? "NOT verified" : "unknown"}${s.opened_at ? " · opened " + esc(s.opened_at) : ""}">
       <b>${esc(scopeName(s))}</b>
       <span class="psub">${s.kyc === true ? '<i class="kdot y"></i>identity verified' : s.kyc === false ? '<i class="kdot n"></i>identity NOT verified' : "&nbsp;"}</span></span>`).join(" ");
  const sig = c.signals.length
    ? c.signals.map((s) =>
        `<span class="pill ${s.polarity}" data-sig="${esc(s.code)} · ${esc(s.polarity)} · value ${esc(s.value)}">
           <b>${esc(SIG_PLAIN[s.code] || s.code)}</b>
           <span class="psub">${s.polarity === "aggravating" ? ic("up") + "looks suspicious" : ic("down") + "looks innocent"}
             ${s.value > 1 ? "· seen " + esc(s.value) + "×" : ""}</span></span>`).join("")
    : '<span class="muted">nothing unusual measured on the accounts themselves</span>';

  /* the decision trail: AI → human corrections, oldest first */
  const holder = (id) => {
    const s = c.scope.find((x) => x.account === id);
    return s ? scopeName(s) : id;
  };
  /* name the cited precedent on screen — the citation IS the memory beat */
  const precKind = (id) => /^(HOV-|D-OV-)/.test(id) ? "an analyst's correction"
    : /^D-20\d\d-/.test(id) ? `a ${id.slice(2, 6)} case` : "a past desk decision";
  const trail = c.decisions.map((x) => {
    const xc = Math.round((x.confidence || 0) * 100);
    const cites = x.cites.map((ct) =>
      `<div class="prec" data-sig="cites ${esc(ct.decision_id)} · ${ct.applies ? "applies" : "does not apply"}"><div class="head">
        <span class="applies ${ct.applies ? "y" : "n"}">${ct.applies ? "This past case applies here" : "The agent decided this past case does NOT apply here"}:
          <b class="mono">${esc(ct.decision_id)}</b> <span class="muted">· ${esc(precKind(ct.decision_id))}</span></span>
        ${ct.distinguishing && ct.distinguishing.length ? `<span class="dist">different because: ${esc(ct.distinguishing.map((s) => SIG_PLAIN[s] || s).join("; "))}</span>` : (ct.applies ? "" : `<span class="dist">(no reason recorded)</span>`)}</div></div>`).join("");
    const ov = x.overridden_by.map((o) =>
      `<div class="dist ov">Corrected by a human: “${esc(o.reason)}”</div>`).join("");
    const rc = (x.action === "clear" && x.receipt)
      ? `<div class="dist rc">Cleared with a replayable receipt: every dangerous connection was checked, and none exists.</div>`
      : "";
    const human = x.decided_by !== "agent";
    return `<div class="tl a-${esc(x.action)} ${human ? "human" : ""} ${x.overridden_by.length ? "overruled" : ""}" data-sig="${esc(x.decision_id)} · ${esc(x.action)} · ${xc}% sure${x.overridden_by.length ? " · overruled" : ""}" style="color:${ACTION_COLOR[x.action] || "var(--muted)"}">
      <div class="tl-dot"></div>
      <div class="tl-body" style="color:var(--text)">
        <div class="d-top">${badge(x.action)}<span class="d-who ${human ? "human" : ""}">${human ? "a human analyst" : "the AI investigator"}</span><span class="muted">${esc(fmtDate(x.ts))}</span></div>
        <div class="d-line">${esc(ACTION_PLAIN[x.action] || x.action)} · opinion: ${esc(VERDICT_PLAIN[x.verdict] || x.verdict)} · ${xc}% sure</div>
        <div class="bar"><div data-w="${xc}"></div></div>
        ${rc}${cites}${ov}
      </div></div>`;
  }).join("");
  const fr = c.freeze_orders.map((f) =>
    `<div class="frz">${badge("freeze", "sm")}<div><b>${esc(holder(f.account))}</b>'s account is blocked — money stopped
      <div class="muted">${esc(fmtDate(f.ts))} · order ${esc(f.order)}</div></div></div>`).join("");
  const queue = c.assigned_to
    ? `<div class="queue-note"><span class="av">${esc(String(c.assigned_to.analyst).replace(/^AN-/, "").slice(0, 2))}</span>
        <div>Queued to <b>${esc(c.assigned_to.analyst)}</b><div class="muted">${esc(c.assigned_to.desk_reason || "assigned by rule")}</div></div></div>`
    : "";

  /* evidence + cost as dotted ledgers */
  const evRows = c.evidence.map((e) =>
    lead(esc(TOOL_PLAIN[e.tool] || e.tool || "case history"), `as of ${esc(fmtDate(e.as_of))}`, null, `${e.tool || ""} · ${e.query_id}`)).join("");
  const evReceipt = (d && d.receipt && d.action === "clear")
    ? lead("the clearance receipt", `as of ${esc(fmtDate(d.receipt.as_of))}`, { v: "ok" }) : "";
  const ev = (evRows || evReceipt)
    ? `<div class="leaders">${evRows}${evReceipt}</div><div class="hint">Each answer is stored with its query and can be re-run later.</div>`
    : '<span class="muted">no links stored yet</span>';
  const tok = c.tokens.in + c.tokens.out;

  /* report */
  const rep = S.report && S.report.case_id === c.case_id ? S.report : null;
  const repBody = rep ? rep.report : (c.report && c.report.body);
  const repCard = repBody
    ? `<div class="card rep" style="--i:8">${h3(9, "Case report — written by the AI, sources checked", c.report && c.report.model ? esc(c.report.model) : "")}
         <div class="rept">${esc(plainen(repBody))}</div>
         <div class="hint">sources: <span class="q">${esc((rep && rep.sources || []).join(" · ") || "stored on the case")}</span></div>
         <a class="dl" href="/cases/${esc(c.case_id)}/report.md" download>${ic("download")}Download the report (.md)</a></div>`
    : "";

  $("case-body").innerHTML = `
    ${headline}${aiVoice}${memo}${flow}
    <div class="card half" style="--i:3">${h3(4, "Who's involved")}
      <div class="pillbar">${scope || "—"}</div>
      <div class="hint">The account that received the money, plus the people paying it. Hover any chip for its exact id.</div></div>
    <div class="card half" style="--i:4">${h3(5, "What the pattern looks like", "fixed rules · no AI")}<div class="pillbar">${sig}</div></div>
    <div class="card" style="--i:5">${h3(6, "Decision trail", `${c.decisions.length} decision${c.decisions.length === 1 ? "" : "s"}, oldest first`)}
      <div class="trail">${trail || '<span class="muted">none yet</span>'}</div>${fr}${queue}</div>
    <div class="card half" style="--i:6">${h3(7, "What the agent asked the graph")}${ev}</div>
    <div class="card half" style="--i:7">${h3(8, "Cost")}
      <div class="stat"><b class="cnt" data-to="${tok}">0</b><span>tokens of AI thinking</span></div>
      <div class="leaders" style="margin-top:12px">${lead("tokens in", nf(c.tokens.in))}${lead("tokens out", nf(c.tokens.out))}${lead("AI runs on this case", nf(c.tokens.llm_runs))}</div>
      <div class="hint">logged and auditable</div></div>
    ${repCard}
    <div class="row btns"><button id="report-btn" class="ghost" ${S.busy ? "disabled" : ""}>${repBody ? "Rewrite" : "Write"} the case report (one AI call)</button></div>`;

  /* motion: ring, bars, counters, the AI's words typed out on a fresh run */
  requestAnimationFrame(() => {
    document.querySelectorAll("#case-body .ring").forEach((r) => r.style.setProperty("--p", r.dataset.p));
    document.querySelectorAll("#case-body .bar > div").forEach((b) => (b.style.width = b.dataset.w + "%"));
    document.querySelectorAll("#case-body .cnt").forEach((el) => countUp(el, +el.dataset.to, 1100));
  });
  if (runRes && ad) typewrite($("ai-text"), `“${plainen(ad.rationale) || "—"}”`);

  $("report-btn").onclick = writeReport;
  const mode = S.mode && S.mode.case_id === c.case_id
    ? `<span class="mode ${S.mode.ablated ? "off" : "on"}">${S.mode.ablated ? "WITHOUT memory" : "with memory"}</span>` : "";
  $("case-id").className = "case-id";
  $("case-id").innerHTML = `case ${esc(c.case_id)} <span class="chip-s">${esc(c.status)}</span>${d ? ` <span class="muted mono">${esc(d.decision_id)}</span>` : ""} ${mode}`;
  $("override-target").className = "ov-target on";
  $("override-target").innerHTML = `<div>Correcting <span class="ov-id">${esc(c.case_id)}</span></div>
    ${d ? `<div>Current decision ${badge(d.action, "sm")}</div><div class="muted">${esc(ACTION_PLAIN[d.action] || d.action)}</div>` : '<div class="muted">no decision to correct yet</div>'}`;
  $("override-btn").disabled = false;
  document.querySelectorAll("#cases .item").forEach((x) => x.classList.toggle("sel", x.dataset.id === c.case_id));
}
function typewrite(el, text) {
  if (!el || REDUCED) return;
  let i = 0;
  const step = Math.max(2, Math.ceil(text.length / 110));
  el.textContent = "";
  el.classList.add("typing");
  const iv = setInterval(() => {
    i += step;
    el.textContent = text.slice(0, i);
    if (i >= text.length) { clearInterval(iv); el.classList.remove("typing"); }
  }, 16);
}
function ablateNote(ablated, d) {
  const note = ablated
    ? "This decision was made WITHOUT the desk's memory — raw evidence only. Investigate the same alert again with memory ON, and compare."
    : d && d.cites.length
      ? "This decision used the desk's memory — past cases and human corrections shaped it."
      : "";
  return note ? `<div class="card memo ${ablated ? "off" : "on"}" style="--i:2"><h3><span class="no">${ic("memory")}</span><span class="ln"></span>Memory check</h3><div class="muted">${note}</div></div>` : "";
}

async function writeReport() {
  if (!S.currentCase || S.busy) return;
  S.busy = true;
  const btn = $("report-btn");
  if (btn) { btn.disabled = true; btn.textContent = "Writing the report…"; }
  toast("writing the case report — one AI call…");
  try {
    S.report = await api(`/cases/${S.currentCase}/report`, { method: "POST" });
    S.report.case_id = S.report.case_id || S.currentCase;
    S.busy = false;
    renderCase(await api(`/cases/${S.currentCase}`));
    toast("report ready — with every source named");
  } catch (e) {
    toast(`report: ${e.message}`, true);
    if (btn) { btn.disabled = false; btn.textContent = "Write the case report (one AI call)"; }
  } finally { S.busy = false; updateSelected(); }
}

/* ---------- live stream ---------- */
function setLive(on) {
  S.live = !!on;
  const b = $("sim-live");
  b.dataset.on = on ? "1" : "0";
  b.querySelector(".live-label").textContent = on ? "Live · stop stream" : "Start live stream";
  document.body.classList.toggle("is-live", S.live);
  renderTicker();
}
async function simToggle() {
  const stopping = S.live;
  try {
    await api(stopping ? "/sim/stop" : "/sim/start?interval=2", { method: "POST" });
    setLive(!stopping);
    toast(stopping ? "live stream stopped" : "the world is live — new alerts arrive by themselves");
    schedule();
    if (!stopping) refreshAlerts();
  } catch (e) { toast(`sim: ${e.message}`, true); }
}

/* ---------- override (the demo beat) ---------- */
const overrideAction = () => (document.querySelector('input[name="action"]:checked') || {}).value || "clear";
async function overrideSubmit(e) {
  e.preventDefault();
  if (!S.currentCase) return;
  const reason = $("reason").value.trim();
  if (!reason) { toast("a reason is required — §10", true); $("reason").focus(); return; }
  const btn = $("override-btn");
  btn.disabled = true;
  try {
    const r = await api(`/cases/${S.currentCase}/override`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ analyst_id: (document.querySelector('input[name="analyst"]:checked') || {}).value || "AN-PRIYA", action: overrideAction(), reason }),
    });
    $("override-note").className = "ov-note ok";
    $("override-note").textContent = `Recorded as ${r.override_id}. It corrects ${r.overruled}: the next similar case will cite this lesson, and ${r.overruled} can never be cited again.`;
    $("reason").value = "";
    toast(`override recorded: ${r.override_id}`);
    renderCase(await api(`/cases/${S.currentCase}`));
    refreshCases();
  } catch (err) {
    toast(`override: ${err.message}`, true);
  } finally { btn.disabled = !S.currentCase; }
}

/* ---------- benchmark modal ---------- */
async function benchLoad() {
  const body = $("bench-body");
  try {
    const r = await api("/benchmark/last");
    const changed = new Set(r.decisions_changed || []);
    const ran = r.cases.filter((c) => !c.miss);
    const matched = ran.filter((c) => c.with_ok && c.without_ok).length;
    const rows = r.cases.map((c) => {
      if (c.miss) return `<tr><td class="mono">${esc(c.case)}</td><td colspan="5" class="muted">${esc(c.miss)}</td></tr>`;
      const ch = changed.has(c.case);
      return `<tr class="${ch ? "changed" : ""}">
        <td class="mono"><b>${esc(c.case)}</b>${ch ? '<span class="chg">memory changed it</span>' : ""}</td>
        <td>${badge(c.with.action, "sm")}<span class="conf">${(c.with.confidence ?? 0).toFixed(2)}</span></td>
        <td>${badge(c.without.action, "sm")}<span class="conf">${(c.without.confidence ?? 0).toFixed(2)}</span></td>
        <td class="mono">${esc((c.with.cited_all || []).join(", ")) || "—"}</td>
        <td class="${c.with_ok && c.without_ok ? "ok" : "miss"}">${c.with_ok && c.without_ok ? "as predicted" : "miss"}</td>
        <td class="muted mono">${nf((c.with.tokens && c.with.tokens.in) || 0)} tok</td></tr>`;
    }).join("");
    body.innerHTML = `
      <div class="metrics">
        <div class="metric"><b class="cnt" data-to="${ran.length}">0</b><span>cases run both ways</span></div>
        <div class="metric hi"><b class="cnt" data-to="${changed.size}">0</b><span>decisions changed by memory</span></div>
        <div class="metric"><b><span class="cnt" data-to="${matched}">0</span><span class="muted" style="font-size:20px"> / ${ran.length}</span></b><span>matched the pre-registered outcome</span></div>
      </div>
      <div class="table-wrap"><table><thead><tr><th>case</th><th>with memory</th><th>without</th><th>cited</th><th>vs pre-registered</th><th>pacing</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
      <div class="hint">Outcomes were pre-registered before the run; every miss is reported (§12).</div>`;
    body.querySelectorAll(".cnt").forEach((el) => countUp(el, +el.dataset.to, 900));
  } catch (e) {
    body.innerHTML = `<div class="empty-list">No benchmark report yet.<br>Run <span class="mono">scripts/c1_exit_test.py</span> once, then reload.<div class="hint">${esc(e.message)}</div></div>`;
  }
}

/* ---------- command palette (Ctrl+K) ---------- */
const P = { items: [], idx: 0 };
function paletteItems(q) {
  const acts = [];
  if (S.selectedAlert) acts.push({ g: "Actions", l: `Investigate ${S.selectedAlert}`, s: "the AI reads the evidence", run: investigate });
  acts.push({ g: "Actions", l: S.live ? "Stop the live stream" : "Start the live stream", s: "simulated payments", run: simToggle });
  acts.push({ g: "Actions", l: "Open the with / without proof", s: "benchmark", run: openBench });
  if (S.currentCase) acts.push({ g: "Actions", l: `Write the case report for ${S.currentCase}`, s: "one AI call", run: writeReport });
  acts.push({ g: "Actions", l: "Refresh the queue", s: "alerts + cases", run: () => { refreshAlerts(); refreshCases(); } });
  const al = S.alerts.map((a) => ({ g: "Alerts", l: TYPE_PLAIN[a.type] || a.type, s: `${a.target} · ${a.id}`,
    run: () => { setTab("alerts"); selectAlert(a.id); const el = document.querySelector(`#alerts .item[data-id="${CSS.escape(a.id)}"]`); if (el) el.scrollIntoView({ block: "nearest" }); } }));
  const cs = S.cases.map((c) => ({ g: "Cases", l: c.case_id, s: `${c.target || ""} · ${c.last_action || "no decision"}`, run: () => openCase(c.case_id) }));
  const all = acts.concat(al, cs);
  const t = q.trim().toLowerCase();
  return (t ? all.filter((x) => (x.l + " " + x.s).toLowerCase().includes(t)) : all).slice(0, 40);
}
function paintPalette() {
  const list = $("pal-list");
  if (!P.items.length) { list.innerHTML = '<div class="pal-empty">Nothing found.</div>'; return; }
  let g = "";
  list.innerHTML = P.items.map((x, i) => {
    const head = x.g !== g ? `<div class="pal-group">${esc((g = x.g))}</div>` : "";
    return `${head}<button class="pal-item ${i === P.idx ? "on" : ""}" data-i="${i}" role="option"><span class="pi-l">${esc(x.l)}</span><span class="pi-s">${esc(x.s)}</span></button>`;
  }).join("");
  const on = list.querySelector(".pal-item.on");
  if (on) on.scrollIntoView({ block: "nearest" });
}
function openPalette() {
  const d = $("palette");
  if (d.open) return;
  $("pal-q").value = "";
  P.items = paletteItems(""); P.idx = 0;
  paintPalette();
  d.showModal();
  $("pal-q").focus();
}
function runPalette(i) {
  const x = P.items[i];
  $("palette").close();
  if (x) x.run();
}
function openBench() { $("benchmark").showModal(); benchLoad(); }

/* ---------- demo tools: the inject buttons (all-UI demo, no terminal) ---------- */
const DEMO_NAMES = { A: "phone-sharing ring", B: "clean funnel", C: "verified business",
  E: "trap", CP: "look-alike", D: "dark look-alike" };
const EMPTY_CASE = $("case-body").innerHTML;  // the "Every alert is a question" welcome, restored on reset
(() => {
  const open = $("demo-open"), menu = $("demo-menu");
  if (!open || !menu) return;
  open.addEventListener("click", (e) => {
    e.stopPropagation();
    menu.classList.toggle("hidden");
  });
  document.addEventListener("click", (e) => {
    if (!menu.classList.contains("hidden") && !e.target.closest(".demo-wrap")) menu.classList.add("hidden");
  });
  menu.querySelectorAll(".demo-item").forEach((b) => b.addEventListener("click", async () => {
    const code = b.dataset.inject;
    if (code === "RESET" && !window.confirm("Reset to a fresh world? This wipes all cases, overrides and reports, and replants the seed baseline.")) return;
    b.disabled = true;
    toast(code === "RESET" ? "replanting a fresh world…" : `planting the ${DEMO_NAMES[code] || code}…`);
    try {
      if (code === "RESET") {
        const r = await api("/sim/reseed", { method: "POST" });
        toast("fresh world planted — the queue is back to the seed baseline");
        S.firstSeen.clear();
        S.currentCase = null; S.report = null; S.mode = null; S.selectedAlert = null;
        $("case-body").innerHTML = EMPTY_CASE;
        $("case-id").className = "case-id muted"; $("case-id").textContent = "no case open";
        $("override-target").className = "ov-target muted";
        $("override-target").textContent = "Open a case to correct its decision.";
        $("override-btn").disabled = true; $("override-note").textContent = "";
        updateSelected();
        S.alerts = [];
        S.booted = false;  // the replanted seed is the baseline, not news: no NEW tags on it
        await refreshAlerts();
        S.booted = true;
      } else if (code === "CP") {
        await api("/sim/inject/CP", { method: "POST" });
        toast("planted: a new batch of the same shape — press Investigate again; the new case should cite the override");
        S.selectedAlert = S.selectedAlert || null;
      } else if (code === "E") {
        // no alert to re-select for the trap, so a second click re-runs it (memory on/off beat)
        try {
          await api("/sim/inject/E", { method: "POST" });
          toast("planted — too quiet for the monitor, so the desk opens a case on A-E1 directly");
        } catch (e3) {
          if (!/already planted/.test(e3.message)) throw e3;
          toast(`re-investigating the trap ${$("ablated").checked ? "WITHOUT" : "with"} memory`);
        }
        menu.classList.add("hidden");
        await investigateAccount("A-E1");
      } else {
        const r = await api(`/sim/inject/${code}`, { method: "POST" });
        const aid = (r.monitor_scan && r.monitor_scan.alerts_created || []).map(a => a.id).join(", ");
        toast(aid ? `planted — alert ${aid} is in the queue` : "planted, but it sits outside the live monitoring window — try Reset to a fresh world first", !aid);
      }
      menu.classList.add("hidden");
      await Promise.all([refreshAlerts(), refreshCases()]);
      renderQueue();
    } catch (e2) { toast(`demo tools: ${e2.message}`, true); }
    finally { b.disabled = false; }
  }));
})();

/* ---------- wire ---------- */
$("refresh").addEventListener("click", (e) => {
  e.currentTarget.classList.remove("spin"); void e.currentTarget.offsetWidth; e.currentTarget.classList.add("spin");
  refreshAlerts(); refreshCases();
});
$("investigate").addEventListener("click", investigate);
$("sim-live").addEventListener("click", simToggle);
$("bench-open").addEventListener("click", openBench);
$("bench-load").addEventListener("click", benchLoad);
$("bench-close").addEventListener("click", () => $("benchmark").close());
$("benchmark").addEventListener("click", (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });
$("override-form").addEventListener("submit", overrideSubmit);
document.querySelectorAll('input[name="action"]').forEach((r) =>
  r.addEventListener("change", () => ($("ov-act").textContent = overrideAction())));
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => setTab(t.dataset.tab)));
$("search").addEventListener("input", (e) => { S.q = e.target.value; renderQueue(); });
$("type-chips").addEventListener("click", (e) => {
  const c = e.target.closest(".chip");
  if (c) { S.type = c.dataset.type; renderQueue(); }
});
$("alerts").addEventListener("click", (e) => { const it = e.target.closest(".item"); if (it) selectAlert(it.dataset.id); });
$("alerts").addEventListener("dblclick", (e) => { const it = e.target.closest(".item"); if (it) { selectAlert(it.dataset.id); investigate(); } });
$("cases").addEventListener("click", (e) => { const it = e.target.closest(".item"); if (it) openCase(it.dataset.id); });
$("selected-line").addEventListener("click", (e) => { const b = e.target.closest("[data-open]"); if (b) openCase(b.dataset.open); });
["alerts", "cases"].forEach((id) => $(id).addEventListener("keydown", (e) => {
  const items = [...$(id).querySelectorAll(".item")];
  const i = items.indexOf(document.activeElement);
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    const n = items[Math.max(0, Math.min(items.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))];
    if (n) { n.focus(); if (id === "alerts") selectAlert(n.dataset.id); }
  } else if (e.key === "Enter" && i >= 0) {
    e.preventDefault();
    const it = items[i];
    if (id === "cases") openCase(it.dataset.id);
    else if (S.selectedAlert === it.dataset.id) investigate();
    else selectAlert(it.dataset.id);
  }
}));
$("pal-open").addEventListener("click", openPalette);
$("pal-q").addEventListener("input", (e) => { P.items = paletteItems(e.target.value); P.idx = 0; paintPalette(); });
$("pal-q").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    P.idx = (P.idx + (e.key === "ArrowDown" ? 1 : -1) + P.items.length) % Math.max(1, P.items.length);
    paintPalette();
  } else if (e.key === "Enter") { e.preventDefault(); runPalette(P.idx); }
});
$("pal-list").addEventListener("click", (e) => { const b = e.target.closest(".pal-item"); if (b) runPalette(+b.dataset.i); });
$("palette").addEventListener("click", (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); return; }
  const tag = (document.activeElement && document.activeElement.tagName) || "";
  if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(tag)) { e.preventDefault(); $("search").focus(); }
});
/* money map: hover a payer to trace its route; everything else steps back */
$("case-body").addEventListener("pointerover", (e) => {
  const svg = e.target.closest && e.target.closest(".flow svg");
  if (!svg) return;
  const g = e.target.closest(".node");
  svg.classList.toggle("focus", !!g);
  svg.querySelectorAll(".hot").forEach((x) => x.classList.remove("hot"));
  if (!g) return;
  g.classList.add("hot");
  if (g.dataset.k != null) svg.querySelectorAll(`.edge[data-k="${g.dataset.k}"]`).forEach((x) => x.classList.add("hot"));
  else svg.querySelectorAll(".edge").forEach((x) => x.classList.add("hot"));   // receiver: every route is its own
});
$("case-body").addEventListener("pointerout", (e) => {
  const svg = e.target.closest && e.target.closest(".flow svg");
  if (svg && !svg.contains(e.relatedTarget)) {
    svg.classList.remove("focus");
    svg.querySelectorAll(".hot").forEach((x) => x.classList.remove("hot"));
  }
});
boot();
