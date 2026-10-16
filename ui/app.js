/* OmegaDesk desk UI — vanilla JS, no build step, no frameworks (zero console errors). */
"use strict";
const $ = (id) => document.getElementById(id);
let selectedAlert = null;
let currentCase = null;

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
  t._x = setTimeout(() => (t.className = ""), 4200);
}
const badge = (a) => `<span class="badge ${a}">${a}</span>`;
const esc = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/* ---------- boot ---------- */
async function boot() {
  try {
    const h = await api("/health");
    $("model").textContent = `llm: ${h.llm_model} · graph: ${h.graph_name}`;
    const hg = await api("/health/graph");
    $("health").textContent = hg.status === "ok" ? "● graph online" : "○ graph down";
    $("health").className = "health " + (hg.status === "ok" ? "ok" : "bad");
  } catch (e) {
    $("health").textContent = "○ api unreachable";
    $("health").className = "health bad";
  }
  await refreshAlerts();
  setInterval(refreshAlerts, 10000);
}

/* ---------- alerts ---------- */
async function refreshAlerts() {
  try {
    const data = await api("/monitor/alerts");
    $("alerts").innerHTML = data.alerts.map((a) => {
      const hist = /^AL-H/.test(a.id) ? "hist" : "";
      const sel = selectedAlert === a.id ? "sel" : "";
      return `<div class="alert ${sel}" data-id="${esc(a.id)}" title="${esc(a.id)} · ${esc(a.type)}">
        <div class="a-plain"><b>${esc(TYPE_PLAIN[a.type] || a.type)}</b></div>
        <div class="a-meta">received by ${esc(a.target)} · ${esc(fmtDate(a.created_at))}</div>
      </div>`;
    }).join("");
    $("alerts").querySelectorAll(".alert").forEach((el) =>
      el.addEventListener("click", () => selectAlert(el)));
    $("investigate").disabled = !selectedAlert || busy;
  } catch (e) {
    toast(`alerts: ${e.message}`, true);
  }
}
function selectAlert(el) {
  document.querySelectorAll(".alert").forEach((x) => x.classList.remove("sel"));
  el.classList.add("sel");
  selectedAlert = el.dataset.id;
  $("investigate").disabled = busy;
}

/* ---------- investigate (the ONLY LLM call on this screen) ---------- */
let busy = false;
async function investigate() {
  if (!selectedAlert || busy) return;
  busy = true;
  $("investigate").disabled = true;
  const ablated = $("ablated").checked;
  $("inv-status").textContent = "LLM investigating — reading context, asking the graph, judging precedents… (~30-60s)";
  try {
    const res = await api("/cases/investigate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ alert_id: selectedAlert, ablated }),
    });
    currentCase = res.case_id;
    $("case-id").textContent = `case ${res.case_id} · ${res.dec_id} · ${ablated ? "WITHOUT memory" : "with memory"}`;
    $("case-id").className = "muted";
    renderCase(await api(`/cases/${res.case_id}`), res);
    toast(`decision recorded: ${res.action} (confidence ${res.confidence})`);
  } catch (e) {
    toast(`investigate: ${e.message}`, true);
  } finally {
    busy = false;
    $("investigate").disabled = !selectedAlert;
    $("override-btn").disabled = !currentCase;
    $("inv-status").textContent = "";
  }
}

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
const VERDICT_PLAIN = { fraud: "looks like fraud", legit: "looks legitimate", unclear: "not sure — needs a human" };

function inShort(c) {
  /* a deterministic, human summary of the case + decision (no jargon) */
  const d = c.decisions[c.decisions.length - 1];
  if (!d) return "";
  const act = ACTION_PLAIN[d.action] || d.action;
  const why = [];
  for (const s of c.signals) {
    const p = SIG_PLAIN[s.code];
    if (p && (s.code !== "BUSINESS_KYC" || !why.length)) { /* keep only first two */
    }
  }
  const parts = [];
  const fan = c.signals.find((s) => s.code === "FAN_IN");
  if (fan) parts.push(`${fan.value} different people paid one account at once`);
  if (c.signals.find((s) => s.code === "SUB_THRESHOLD")) parts.push("several payments just under the ₹50,000 line");
  if (c.signals.find((s) => s.code === "PASS_THROUGH")) parts.push("money arrived and was sent straight out");
  if (c.signals.find((s) => s.code === "SHARED_DEVICE")) parts.push("one device was shared across accounts");
  if (c.signals.find((s) => s.code === "RING_MEMBER")) parts.push("that device is tied to known fraud");
  const kyc = c.signals.find((s) => s.code === "BUSINESS_KYC");
  if (kyc) parts.push("the receiver is a verified business");
  const cited = (d.cites || []).some((x) => x.applies);
  const corrected = (d.cites || []).some((x) => (x.distinguishing || []).length === 0 && !x.applies);
  const mem = cited
    ? "The desk's memory of past cases shaped this."
    : corrected
      ? "A past case was corrected before, so the desk wants a human to decide."
      : "The desk decided without clear memory guidance.";
  return `${act}. Why: ${parts.join(" · ") || "the account's own history"}. ${mem}`;
}

/* ---------- render case detail ---------- */
const fmtDate = (iso) => {
  const s = String(iso);
  const [d, t] = s.split("T");
  return d + (t ? " · " + t.slice(0, 5) : "");
};
const scopeName = (s) =>
  (s.holder && s.holder !== "merchant") ? s.holder : "Registered business";

function renderCase(c, runRes) {
  /* signal chips = plain sentences; the raw code survives only as a hover-tip */
  const sig = c.signals.length
    ? c.signals.map((s) =>
        `<span class="pill ${s.polarity}" title="internal code: ${esc(s.code)}">
           <b>${esc(SIG_PLAIN[s.code] || s.code)}</b>
           <span class="psub">${s.polarity === "aggravating" ? "looks suspicious" : "looks innocent"}
             ${s.value > 1 ? "· seen " + esc(s.value) + "×" : ""}</span></span>`).join("")
    : '<span class="muted">nothing unusual measured on the accounts themselves</span>';

  const d = c.decisions[c.decisions.length - 1] || null;
  const acts = c.decisions.map((x) => {
    const cites = x.cites.map((ct) =>
      `<div class="prec"><div class="head" title="stored as decision ${esc(ct.decision_id)}">
        <span class="applies ${ct.applies ? "y" : "n"}">${ct.applies ? "✓ this past case applies here" : "✗ the agent decided this past case does NOT apply here"}</span>
        ${ct.distinguishing && ct.distinguishing.length ? `<span class="dist">different because: ${esc(ct.distinguishing.map((s) => SIG_PLAIN[s] || s).join("; "))}</span>` : (ct.applies ? "" : `<span class="dist">(no reason recorded)</span>`)}</div></div>`).join("");
    const ov = x.overridden_by.map((o) =>
      `<div class="dist">⚠ a human corrected this one — “${esc(o.reason)}”</div>`).join("");
    return `<div class="card">
      <h3>Decision · ${esc(fmtDate(x.ts))} · by ${x.decided_by === "agent" ? "the AI investigator" : "a human analyst"}</h3>
      ${badge(x.action)} <span class="muted">${esc(ACTION_PLAIN[x.action] || x.action)} · AI's opinion: ${esc(VERDICT_PLAIN[x.verdict] || x.verdict)} · ${Math.round((x.confidence || 0) * 100)}% sure</span>
      <div class="bar"><div style="width:${Math.round((x.confidence || 0) * 100)}%"></div></div>
      ${cites}${ov}
    </div>`;
  }).join("");

  const holder = (id) => {
    const s = c.scope.find((x) => x.account === id);
    return s ? scopeName(s) : id;
  };
  const ev = c.evidence.length
    ? `<ol class="evidence">${c.evidence.map((e) =>
        `<li title="${esc(e.tool)} · ${esc(e.query_id)}">${esc(TOOL_PLAIN[e.tool] || e.tool)}
         <span class="q">(re-runnable · as of ${esc(fmtDate(e.as_of))})</span></li>`).join("")}</ol>`
    : '<span class="muted">no evidence links yet</span>';

  const fr = c.freeze_orders.map((f) =>
    `<div class="card"><h3>Blocked</h3>
      <div><b>${esc(holder(f.account))}</b>'s account is blocked — money stopped
      <span class="psub">${esc(fmtDate(f.ts))}</span></div></div>`).join("");

  const scope = c.scope.map((s) =>
    `<span class="pill neutral" title="${esc(s.account)}">
       <b>${esc(scopeName(s))}</b>
       <span class="psub">${s.kyc === true ? "identity verified" : s.kyc === false ? "identity NOT verified" : "&nbsp;"}</span></span>`).join(" ");

  const short = inShort(c);
  const aiVoice = d
    ? `<div class="card ai-voice"><h3>What the AI investigator says</h3>
         <div class="aitt">“${esc(d.rationale || "—")}”</div>
         <div class="hint">This is the agent's own written reasoning — exactly as stored in the decision (replayable in the graph).</div></div>`
    : "";
  $("case-body").innerHTML = `
    ${short ? `<div class="card headline"><h3>In short</h3><div class="shortt">${esc(short)}</div></div>` : ""}
    ${aiVoice}
    <div class="card"><h3>Who's involved</h3>
      <div class="pillbar">${scope || "—"}</div>
      <div class="hint">The account that received the money, plus the people paying it. Hover any chip for its exact id.</div></div>
    <div class="card"><h3>What the pattern looks like (measured by fixed rules — no AI here)</h3><div class="pillbar">${sig}</div></div>
    ${acts}${fr}
    <div class="card"><h3>What the agent asked the graph (each answer re-runnable later)</h3>${ev}</div>
    <div class="card"><h3>Cost</h3><div class="muted">${c.tokens.in + c.tokens.out} tokens of AI thinking — logged, auditable</div></div>`;

  if (runRes) {
    $("case-body").insertAdjacentHTML("beforeend", ablateNote(runRes.ablated, d));
  }
}
function ablateNote(ablated, d) {
  const note = ablated
    ? "This decision was made WITHOUT the desk's memory — raw evidence only. Investigate the same alert again with memory ON, and compare."
    : d && d.cites.length
      ? "This decision used the desk's memory — past cases and human corrections shaped it."
      : "";
  return note ? `<div class="card"><h3>Memory check</h3><div class="muted">${note}</div></div>` : "";
}

/* ---------- override (the demo beat) ---------- */
async function overrideSubmit(e) {
  e.preventDefault();
  if (!currentCase) return;
  const reason = $("reason").value.trim();
  if (!reason) { toast("a reason is required — §10", true); return; }
  try {
    const r = await api(`/cases/${currentCase}/override`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ analyst_id: $("analyst").value, action: $("action").value, reason }),
    });
    $("override-note").textContent = `recorded as ${r.override_id} — it corrects ${r.overruled}; the next twin (C′) will cite this, and ${r.overruled} is never citable again.`;
    $("reason").value = "";
    toast(`override recorded: ${r.override_id}`);
    setTimeout(() => { if (currentCase) api(`/cases/${currentCase}`).then((c) => renderCase(c)); }, 60);
  } catch (err) {
    toast(`override: ${err.message}`, true);
  }
}

/* ---------- benchmark drawer ---------- */
async function benchLoad() {
  try {
    const r = await api("/benchmark/last");
    const rows = r.cases.map((c) => {
      if (c.miss) return `<tr><td>${esc(c.case)}</td><td colspan="5" class="muted">${esc(c.miss)}</td></tr>`;
      return `<tr>
        <td><b>${esc(c.case)}</b></td>
        <td>${esc(c.with.action)} (${(c.with.confidence ?? 0).toFixed(2)})</td>
        <td>${esc(c.without.action)} (${(c.without.confidence ?? 0).toFixed(2)})</td>
        <td>${esc((c.with.cited_all || []).join(", ")) || "—"}</td>
        <td>${c.with_ok && c.without_ok ? "✓" : "miss"}</td>
        <td class="muted">${esc((c.with.tokens && c.with.tokens.in) || 0)} tok</td></tr>`;
    }).join("");
    $("bench-body").innerHTML = `
      <table><thead><tr><th>case</th><th>with memory</th><th>without</th><th>cited</th><th>vs pre-registered</th><th>pacing</th></tr></thead>
      <tbody>${rows}</tbody></table>
      <div class="hint">decisions changed by memory: ${esc((r.decisions_changed || []).join(", ") || "—")} ·
      pre-registered before the run; every miss reported (§12).</div>`;
  } catch (e) { toast(`benchmark: ${e.message}`, true); }
}

/* ---------- wire ---------- */
$("refresh").addEventListener("click", refreshAlerts);
$("investigate").addEventListener("click", investigate);
$("bench-open").addEventListener("click", () => { $("benchmark").classList.remove("hidden"); benchLoad(); });
$("bench-load").addEventListener("click", benchLoad);
$("bench-close").addEventListener("click", () => $("benchmark").classList.add("hidden"));
$("override-form").addEventListener("submit", overrideSubmit);
boot();