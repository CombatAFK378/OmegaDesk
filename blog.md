*A hackathon project for the Graph Hacks hackathon (WeMakeDevs × FalkorDB). Repo: [github.com/CombatAFK378/OmegaDesk](https://github.com/CombatAFK378/OmegaDesk)*

**🎥 Watch the demo:**

{% embed https://www.youtube.com/watch?v=cW1pdClr3EA %}

Every fraud analyst knows this day: you clear an account after an hour of work, write your reasons, close the case — and four days later the same pattern walks in, and nobody remembers. The work is done again. The lesson is gone. Worse, a *wrong* call — freezing an honest business — can repeat for months because nothing in the system carries *why it was wrong*.

That's the problem we picked: **not "detect fraud" — memory. A desk that grows smarter with every human decision.**

## The idea: case law for fraud analysts

Our working idea is simple. In any real bank, yesterday's decisions are the most valuable data in the building — and the least used. Somewhere in a shared folder is a note that says *"this merchant is fine, the payments are his monthly rent."* When the same shape shows up next month, that note could have saved an hour and an apology. But nothing connects them.

So we built the desk around one principle: **what a desk decides, and why a human corrected it, becomes law for future cases** — searchable, citable, and impossible to silently forget.

## How a case actually moves

A day at OmegaDesk looks like this:

1. **A watcher with plain maths.** Simple, fixed rules watch the money — did one account receive from many different people? is money leaving the same day it arrives? are payments hiding just under the reporting line? does one device sit on many accounts? No AI here — by design. If these rules are allowed to shout, everything looks suspicious.
2. **A case file, not a single suspect.** When a shape is strong enough, the desk opens a case that captures the *whole crowd*: the receiver, the payers, the devices they share, in that time window. The fraud shape is in the relationships, not in one account.
3. **The AI detective — one job.** An agent model reads the file and asks the graph questions, one at a time: *who else uses this device? where did the money go next? do these accounts look brand new?* Then it reads the memory: past cases, past verdicts, and every human correction. It must answer in a fixed form: a verdict, a confidence number, and — the part we care most about — **a named list of the past cases it leaned on, marking for each whether it really applies and, if not, exactly how today differs.**
4. **Code pulls the trigger, not the AI.** The verdict converts to an action by an unchangeable ladder: 85%+ freeze, 60–85% escalate to a human, below that just watch. Two locks the AI can never open by argument: *clearing* an account requires fresh proof run today (see the receipt below) — an old case alone can never set someone free; and an AI that leans on a decision a human later corrected must name precisely how today differs, or the case goes to a human.
5. **A receipt for every release.** When the action is a clearance, a checklist tool actually proves the clean look — and seals the result to the decision like a signed slip, re-runnable any time. Freezes were always defensible; now release is too.
6. **The human correction becomes a lesson.** Analysts can override any decision — with a written reason, enforced by the form. That reason lands in the graph next to the case it corrected. The next similar case finds both and follows the newer one. The overruled decision is marked *never cite again*. There is no learning loop without the analyst's own words — and no loop without remembering them, which is the whole point.

## Why a graph (and why FalkorDB)

The memory in this system is a graph, and that's not a fashion choice — it's what the data *is*. Accounts, devices, merchants and money paths exist as connections: shared devices across accounts, money hopping through chains. "Show me everyone who shares a device with this frozen account, and whether any of those is already marked bad" is one traversal on a graph — and a pile of joins everywhere else. We run FalkorDB for exactly that shape. Even the graph algorithm runs inside it: the agent's "who is the hub of this money?" tool uses FalkorDB's built-in betweenness centrality. The agent's tool calls run graph queries and the results are stored back *in* the same graph: cases, decisions, citations and overrides live beside the money data they interpret. When you ask "why did the desk decide this in June?", the answer is literally a short walk through connected nodes — not a scroll through logs.

## The honest numbers

We wrote down the expected outcome for six known cases before the final run, then replayed each one twice — once with memory, once with memory deliberately switched off.

All six matched what we expected, and **memory changed two decisions**:

- **A clean funnel** — eight unrelated people paying one wallet, no shared device, no shared identity. With memory, the desk sent it to a human; without memory, it froze the wallet.
- **A trap** — a brand-new account shaped exactly like an old case the desk once *froze*, which an analyst later corrected to a review. With memory, the desk cited the analyst's correction (never the overruled freeze) and sent it to a human; without memory, it froze the account again.

The other four behaved the same either way — which is also the point: a fraud ring sharing one phone gets frozen with or without memory, and an honest shop gets cleared with or without memory, because the evidence alone is enough.

The numbers are small and illustrative, not statistical, and live runs vary. The clean-funnel case sits right on the confidence line, so in our repeated runs it goes to a human only about half the time; the trap goes to a human in most runs (6 of 7 in our tests). When it misses, it misses toward a freeze that the analyst then corrects — and that correction becomes the next lesson. When the AI cloud hiccups, the desk falls back to a safe "watch, investigator unavailable", never to an action. The design's answer is the confidence ladder and the human gate, not a bigger model.

## What we'd do next

Three directions, in order of what we'd bet on: per-tenant desks (one graph per customer team — the memory must not leak between banks); a *challenger* agent that re-investigates a sample of closed cases each week and reports if its answers now differ from what the desk stored — drift detection for the desk's own judgement; and real streaming ingestion so the monitor runs on live bank money instead of our simulated stream.

**The line we keep returning to:** an AI that remembers is a tool; an AI that remembers *what you corrected it on*, and shows you exactly which lesson it used, is a colleague. That's what the graph gave us — and why this hackathon was the right place to build it.

*Repo: [github.com/CombatAFK378/OmegaDesk](https://github.com/CombatAFK378/OmegaDesk) — the with/without benchmark, the override loop and the receipts are all runnable from the README in minutes. Demo video: [youtube.com/watch?v=cW1pdClr3EA](https://www.youtube.com/watch?v=cW1pdClr3EA)*

