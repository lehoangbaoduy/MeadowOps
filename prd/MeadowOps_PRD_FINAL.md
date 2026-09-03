# MeadowOps
## Product Requirements Document — Persistent Supply Chain Work Simulation Platform

**Status:** FINAL — ready for implementation
**Team:** 2 people (1 CS/technical Builder, 1 IS + Supply Chain domain Analyst)
**Target Operating Cost:** ≤ $20/month
**Tech Stack:** PostgreSQL (Docker Compose locally, managed host in deployment) + Python/FastAPI + Next.js/React + Claude API
**Frontend Templates:** `orbynadmin` (Subsystem 1), `shadcn-dashboard` — Next.js version (Subsystem 2) — see Appendix D
**Simulated Company:** Meadow Packaging & Supply (MPS)

---

## 1. Purpose, Principles & Definition of Done

### 1.1 Problem statement
Supply chain and IS education is heavy on frameworks (SCOR, EOQ, ERP process theory) and light on the lived experience of real project work: ambiguous requests, conflicting stakeholders, messy data, iterative back-and-forth, and decisions made before perfect information exists. Someone about to enter the industry benefits far more from *practicing* these dynamics than from reading another case study.

### 1.2 Project goal
Build a two-subsystem platform that (a) functions as a real, working supply chain information system with live data, grounding everything in an actual (simulated) company, and (b) uses that live system as the substrate for AI-generated business scenarios requiring real analyst judgment — so the Analyst can rehearse the rhythm of IS + supply chain work before her first job, inside a company that remembers what she did and what happened afterward.

**Core promise:** *Practice supply-chain and IS work as if you already had the job — inside a company that remembers what you did.*

### 1.3 Two phases of this project
This PRD covers two distinct phases with different owners and different definitions of success:

- **Build & Test (current phase, Builder-owned):** design, implement, and thoroughly test both subsystems until they work correctly and seamlessly together. The Analyst's active participation is **not required** for this phase to be complete — the Builder validates the system using synthetic/QA test data and scripted test runs. This phase's completion criteria are in Section 1.6.
- **Active Use (next phase, Analyst-owned):** once the platform is delivered, the Analyst begins her actual hands-on work — exception thresholds, KPI SQL, and running real scenarios. This is where the platform's actual educational purpose is realized. Its own completion criteria live in Section 11 and are deliberately separate from Section 1.6 — a fully built, fully tested platform with zero real scenarios run is **Done**; it is not yet **Program Complete**.

Keeping these separate matters: it lets the team focus entirely on engineering correctness right now, without the Analyst's limited time being a build-phase constraint, while every design decision in this document still respects her time budget for when Active Use begins.

### 1.4 Guiding principles

1. **Correctness and test coverage come first, right now.** The current job is building both subsystems and proving — with tests, not assumptions — that they work, including at the edges. Nothing here should be marked "done" on the strength of a demo alone.
2. **Her time is the hardest constraint on the *product's design*, not on the current build effort.** Once Active Use begins, the Analyst has roughly 5 hours/week. The system must be built to respect that from day one (async pacing, 10–12 scenarios not more, three competency clusters not ten) — but building and testing that system does not consume her time.
3. **Depth over volume.** 10–12 substantial scenarios once in use, not more. Three tracked competency clusters, not ten. One consolidated persistence mechanism, not three.
4. **Reality over artificial difficulty.** Difficulty comes from ambiguity, competing stakeholder incentives, and incomplete information — not from hiding information a real analyst would simply have access to.
5. **Evidence over LLM authority.** Every scenario claim traces to real data or an explicitly-labeled stakeholder statement/belief. The AI evaluator is never the final word.
6. **Consequences over isolated answers.** Decisions can echo forward into later scenarios; she's evaluated on the quality of her reasoning at decision time, not on whether the simulated world got lucky afterward.
7. **Learning over grading.** Draft evaluations exist to develop her, not to score her. Difficulty and evaluation trends stay invisible in the moment; monthly review is where she actually sees her growth.

### 1.5 Non-goals
- Not a production-grade or commercially viable ERP/control-tower product.
- Not a machine learning research project — the LLM is a tool, not the point.
- Not a replacement for mentorship, internships, or real work experience.
- Not a benchmark certifying objective professional competence — it's structured practice.
- Not a high-volume system.
- **The current Build & Test phase is not a rehearsal for the Analyst** — no real scenario needs to be run by her, no portfolio needs to exist, and no monthly human review needs to have happened, for this phase to be considered complete.

### 1.6 Definition of Done — Build & Test phase
The project is **Done** when:
- both subsystems are fully implemented per this specification;
- the full automated test suite (Section 9) passes — unit, integration, and end-to-end — including every edge case in the catalog (9.2);
- the subsystems integrate seamlessly: Subsystem 2 reads Subsystem 1 exclusively through its API (never direct SQL), the Decision & Event Ledger behaves correctly across its full lifecycle, and the evaluation pipeline runs end-to-end without manual intervention;
- the full scenario loop (generation → investigation → response → pushback → revision → draft evaluation → difficulty recommendation) has been exercised via **QA test runs** (a scripted or Builder-operated stand-in acting as the Analyst) across all 6 scenario types at least once each — proving the mechanism works, independent of any real practice having occurred;
- the system contains **zero demo/fake/fabricated data** from either frontend template — only real Meadow Packaging & Supply data generated by the platform itself;
- the system is deployed and reachable per Section 8.2, with backups and migrations verified (not just configured — an actual restore has been tested);
- documentation is complete: schema diagram, data dictionary, data-flow doc, and a testing report summarizing coverage and results;
- a live walkthrough can be given end-to-end, using QA/synthetic data, without improvisation.

**Explicitly not required for Done:** any real scenario completed by the Analyst, any completed monthly human review, any portfolio content, or an identified/onboarded external reviewer. These belong to Section 11.

### 1.7 Program Complete — Active Use phase
Once Done, the platform enters Active Use. That phase is considered complete on its own separate criteria (Section 11.5) — roughly, 10–12 real scenarios completed, a compiled portfolio, at least one difficulty-tier adjustment confirmed by the external reviewer, and at least one decision-callback scenario. This PRD documents both, but only Section 1.6 gates the engineering handoff.

---

## 2. Users & Roles

| Role | Description | Involved during Build & Test? | Responsibilities |
|---|---|---|---|
| **Builder** | CS master's student, 5 yrs industry experience | Yes — primary owner of this phase | Builds both subsystems, writes and runs the test suite, operates the admin panel, stands in as the QA "test analyst" for end-to-end validation, sources the external reviewer for later |
| **Analyst** | IS + Supply Chain double major, no industry experience | No — her involvement begins in Active Use (Section 11) | Once Active Use begins: authors/adjusts exception thresholds, writes/reviews core KPI SQL, works scenarios as the acting analyst |
| **AI** | Claude API | Yes — exercised via QA test runs during Build & Test | Generates scenarios grounded in real data, plays stakeholder roles, produces draft evaluations and difficulty recommendations — **never authoritative**, never writes to the operational database directly |
| **External Human Reviewer** | Professor or working IS/SC professional — sourced independently by the Builder | No — only needed once real evaluations exist | Independently reviews a sample of scenarios/evaluations, explicitly assesses difficulty-tier calls, can override AI recommendations, records disagreements |

---

## 3. The Simulated Company

**Meadow Packaging & Supply (MPS)** — a fictional, mid-sized regional B2B distributor of warehouse and packaging supplies. Large enough to produce meaningful supply-chain and IS problems; small enough that two people can hold the whole system in their heads.

All master data below is **starter data**, generated now so the build isn't blocked on a workshop. Every field is editable through the admin panel (5.6) at any point.

### 3.1 Product catalog
~20 SKUs across 3 categories — Corrugated Packaging, Protective Packaging (bubble mailers, foam inserts, wrap, void-fill), Shipping/Labeling Supplies (tape, labels, stretch wrap). Non-perishable — no lot tracking, expiration, serial numbers, reverse logistics. The full SKU list is seeded by the data generator in Phase 1 (Section 10) following this category structure, and is editable the same way as warehouses/suppliers/carriers below.

### 3.2 Warehouses

| ID | Name | Region | Approx. Capacity | Character |
|---|---|---|---|---|
| WH-EAST | East Warehouse | Northeast US | ~4,000 pallet positions | Steady demand, slight Q4 peak |
| WH-CENTRAL | Central Warehouse | Midwest US | ~6,000 pallet positions | Largest — primary distribution center, broadest SKU coverage |
| WH-WEST | West Warehouse | Southwest US | ~3,000 pallet positions | Leaner, more exposed to longer/variable supplier lead times |

Warehouse-to-warehouse transfers are supported as a lightweight operation between any two of the three.

### 3.3 Suppliers

| ID | Name | Category Focus | Unit Cost Tier | Base Lead Time | Lead-Time Variability | Historical OTIF | Notes |
|---|---|---|---|---|---|---|---|
| S-001 | Vantage Corrugated Co. | Corrugated Packaging | Mid | 7 days | Low | 96% | Reliable primary carton supplier |
| S-002 | Palmetto Protective Supply | Protective Packaging | Low (cheapest) | 10 days | Medium | 89% | Cheap but inconsistent — cost-vs-reliability tradeoff scenarios |
| S-003 | Ironclad Freight Materials | Shipping/Labeling Supplies | Mid | 5 days | Low | 97% | Fast and reliable, slightly pricier |
| S-004 | Meridian Packaging Partners | Corrugated + Protective | High | 6 days baseline | Drifts to ~12 days over 6 weeks per the seeded root-cause storyline (4.3) | 93% baseline, declining | **Used in the seeded root-cause scenario** |
| S-005 | Coastal Supply Exchange | Shipping/Labeling Supplies | Low | 12 days | High | 82% | Least reliable — cheap-but-risky supplier-decision scenarios |
| S-006 | Timber & Twine Co. | Protective Packaging (niche) | High | 9 days | Low | 95% | Smaller supplier, minimum-order-quantity scenarios |

### 3.4 Carriers

| ID | Name | Normal Transit Time | Variability | Reliability | Notes |
|---|---|---|---|---|---|
| C-001 | Ridgeline Freight Lines | 2 days (regional) | Low | ~98% on-time | Default for East/Central |
| C-002 | Summit National Carriers | 3–4 days (long-haul) | Medium | ~91% on-time | Used for West and cross-region shipments |
| C-003 | ValueHaul Logistics | 4–5 days | High | ~85% on-time | Cheapest — cost-vs-service tradeoff scenarios |

### 3.5 Customers
Represented through Sales Orders (ID, name, service priority, warehouse assignment, region, order history) — no CRM functionality needed.

---

## 4. Data, Simulation & Persistence Model

*(Entirely Builder-side complexity. The Analyst never interacts with any of this directly — only with its effects: a dashboard, a scenario, a stakeholder who remembers last month.)*

### 4.1 Source-system realism — scoped as metadata, not four systems
Operational records are tagged with a conceptual origin — **ERP** (orders, product/supplier/customer master data), **WMS** (inventory, receiving, pick/pack/ship events), or **Procurement** (sourcing, quoted prices, supplier performance observations) — via a `source_system` field, not four separate physical systems. On top of the single operational database sits **one deliberately-lagged Reporting layer**, which creates realistic "the dashboard hasn't caught up" and "two systems disagree" situations, satisfying SR-2's latency requirement and SR-4's conflicting-sources requirement concretely.

### 4.2 Simulation clock & world state
- A simulated business date, independent of the real calendar.
- Every scenario stores its `scenario_start_date`, `scenario_due_date`, `simulation_date`, `world_state_id`, `scenario_seed`, `template_version`, `prompt_version`.
- Supported operations: **Clean Baseline**, **Injected State**, **Snapshot**, **Reset**, **Advance Simulation**, **Controlled Event Injection**. Every activated scenario must be reproducible from its stored world-state reference and seed. **A reset must never invalidate an in-flight scenario** — each scenario is pinned to its own `world_state_id`, so global resets and an individual scenario's continuity are independent (tested explicitly, 9.2).

### 4.3 Seeded randomness & causal storylines
Randomness adds texture but must never make a scenario's answer unknowable. Diagnosable scenario types use an **explicit seeded storyline** — the canonical one for this project: **Supplier S-004's lead time drifts from ~6 to ~12 days over six weeks, causing delayed POs → declining inventory → SKU stockouts → reduced fill rate.** The causal chain is known to the simulator, hidden from the Analyst.

### 4.4 The Decision & Event Ledger
One consolidated mechanism. Every record is either an **operational event** or a **decision**, and decisions carry a lifecycle:

**Proposed → Clarification Requested → Accepted / Rejected → Implemented / Partially Implemented → Observed Outcome**

- **Approval authority** is scenario-dependent (an operational parameter change needs manager approval; a supplier reallocation needs procurement/operations approval; low-impact analysis may be informational only).
- **Implementation** produces controlled downstream effects via deterministic rules plus seeded randomness.
- **Outcome** is recorded as succeeded / partially succeeded / failed / unintended consequence / insufficient evidence. **Decision quality is evaluated separately from outcome quality.**
- **Callback scenarios:** at least one scenario (once in Active Use) should explicitly reopen an earlier decision — *"Last month you recommended moving 40% of SKU-100 volume to Supplier S-002. Did it actually improve service?"* This is the strongest realism mechanism in the whole project, and the QA test suite validates the *mechanism* works even before any real decision exists to call back to.
- A decision left unresolved (never accepted or rejected) is a defined **stale-decision state**, not an undefined one — flagged after a configurable period rather than sitting in limbo indefinitely.
- Stakeholders can "remember" a prior recommendation or disagreement simply because the AI reads the ledger before generating a scenario — no separate memory system needed.

---

## 5. Subsystem 1: The Operational System

### 5.1 Scope boundaries

**In scope:** entities/flows below; procure-to-stock; order-to-ship; realistic imperfections (5.5); warehouse transfers; carrier variability; world-state snapshot/reset (4.2); the Decision & Event Ledger (4.4); full master-data CRUD via admin panel (5.6); the SQL Query Playground (5.9); **the Analyst's persona-chat inbox (S1-FR-15, 6.13 — added 2026-09-02)**.

**Out of scope:** multi-currency/region, batch/lot or serial tracking, returns/reverse logistics, GL/invoicing beyond basic PO cost, real supplier/carrier API integrations, route optimization, live carrier integrations, auth/multi-tenant complexity beyond two users.

**Amended 2026-09-02 — role-based login:** "beyond two users" still means exactly two users — no self-registration, no password reset flow, no email verification, no third role — but those two users are no longer a single shared bearer token. Each has a real account (email + password) that declares which of the two roles they hold, so the system can tell Admin (Builder) apart from Analyst by identity rather than by which secret was pasted in. See 8.4 for the resulting write/view split.

### 5.2 Data model (summary — field-level schema finalized during implementation)

**Dimensions:** Product, Warehouse, Supplier, Customer, Carrier, Date.
**Facts:** Inventory Snapshot, Inventory Transaction, Purchase Order, Sales Order, Shipment, Warehouse Transfer, the unified **Decision & Event record** (4.4).

### 5.3 KPI definitions
See Appendix A. Exact inclusion/exclusion rules are defined by the Builder during implementation and versioned thereafter; the Analyst reviews and can adjust them once Active Use begins (S1-FR-11).

### 5.4 Functional requirements

| ID | Requirement |
|---|---|
| S1-FR-1 | Simulate/ingest data for all core entities on a scheduled basis, advancing along the simulation clock (4.2) |
| S1-FR-2 | Store all data in PostgreSQL using a star schema, with `source_system` tags per 4.1 |
| S1-FR-3 | Calculate and display OTIF, fill rate, days of supply, order cycle time, perfect order rate |
| S1-FR-4 | Flag exceptions via configurable business rules; thresholds are Analyst-adjustable once Active Use begins (5.7), with reasonable Builder-set defaults during Build & Test |
| S1-FR-5 | Dashboard supports drill-down from any KPI/exception to underlying records, across Executive, Inventory, Supplier, Order, and Data-Quality views |
| S1-FR-6 | Expose an API layer Subsystem 2 queries directly for scenario grounding and evidence retrieval |
| S1-FR-7 | Support world-state snapshot, clean-baseline reset, and controlled injected-state/event operations (4.2) |
| S1-FR-8 | Maintain the Decision & Event Ledger (4.4) so later scenarios can reference earlier outcomes |
| S1-FR-9 | Maintain a deliberately-lagged Reporting layer (4.1) distinct from live operational data |
| S1-FR-12 | Admin panel supports full CRUD (create, edit, deactivate) for Warehouse, Supplier, and Carrier master data — the data in Section 3 is the seeded starting point, not a fixed constant |
| S1-FR-13 | A "Query" page provides a SQL playground: free-form SQL execution against a sandboxed replica of the operational schema, with a syntax-highlighted editor and tabular results (5.9) |
| S1-FR-14 | Every query submitted through the Query page — read or write, executed or cancelled — is logged (timestamp, user, query text, statement type, result status) for the admin history view (6.12) |
| S1-FR-15 | *(Added 2026-09-02)* A real-time, persona-threaded chat inbox delivers and receives persona-chat messages (6.13) with unread-thread badges and Analyst-side file attachments |
| S1-FR-16 | *(Added 2026-09-02)* Email+password login declares which of the two roles (Admin/Analyst) the session holds (5.1, 8.4); Admin can write master data and use every admin panel control, Analyst can view all of Subsystem 1 but cannot write anywhere — enforced server-side on every request, not just hidden in the UI |

### 5.5 Realistic data imperfections

| ID | Requirement |
|---|---|
| SR-1 | At least one data source has inconsistent formatting requiring cleaning |
| SR-2 | The Reporting layer (4.1) lags live operational data on a realistic delay |
| SR-3 | System supports injectable "bad data" (missing fields, duplicates, orphaned references) |
| SR-4 | At least one instance of conflicting data between the operational and Reporting layers, or between ERP- and WMS-tagged records, not resolvable by timing alone |

### 5.6 Master data management (Admin Panel)
The Builder's operational control surface, distinct from the Analyst's hands-on role (5.7):

- Full CRUD for Product/SKU, Warehouse, Supplier, and Carrier records (S1-FR-12).
- Edits take effect going forward from the current simulation date — they must never silently rewrite historical records or already-completed scenarios (tested explicitly, 9.2).
- Starter data (Section 3) is generated so the team can start building immediately.

### 5.7 The Analyst's hands-on role in Subsystem 1 (Active Use)
Her one direct technical touchpoint outside the scenario loop, beginning once the platform is delivered.

| ID | Requirement |
|---|---|
| S1-FR-10 | Analyst authors and iterates on exception-rule thresholds, refining at least one after observing real behavior |
| S1-FR-11 | Analyst writes or reviews the SQL logic behind at least the three core KPIs (OTIF, fill rate, days of supply) |

During Build & Test, the Builder implements sensible default thresholds and KPI SQL so the system is fully functional and testable; these are explicitly designed to be reviewed and adjusted by the Analyst later, not treated as final.

### 5.9 SQL Query Playground
A page where the Analyst (or the Builder, during testing) can write and run **any** SQL, for open-ended practice rather than a specific task.

**Two-layer safety design — a confirmation dialog alone isn't a real safety boundary, so this uses both:**
- **Hard boundary (database-enforced):** the Query page connects through a dedicated Postgres role scoped only to a **sandboxed replica schema** — a copy of the operational tables, refreshed nightly and on-demand via a "Refresh sandbox" button. This role has no privileges on the live operational schema or on Subsystem 2's ledger/evaluation/portfolio tables, regardless of what's typed. This means "do whatever she wants" is genuinely safe — nothing here can corrupt the live simulation, the Decision & Event Ledger, or evaluation history, even by accident. **This permission boundary must be tested directly** (9.2), not just asserted by design.
- **Soft boundary (UX, builds good habit):** SELECT and other read-only statements run immediately. **INSERT, UPDATE, DELETE, and DDL statements (ALTER, DROP, TRUNCATE, CREATE) trigger a confirmation dialog** showing the exact statement before execution — including when chained in a multi-statement submission, so a destructive statement can't slip through hidden behind a harmless one.

**Interface:** a syntax-highlighted SQL editor (CodeMirror 6 or Monaco — net-new, neither template ships one) plus a results panel reusing the same data-table component used everywhere else in Subsystem 1 (Appendix D). Query history (S1-FR-14) is visible here too — a learning log, not just an audit trail.

**Operational limits:** a statement timeout (to catch runaway queries) and a row-limit/pagination on results (to catch accidentally-huge result sets) are required, not optional — see the edge case catalog (9.2).

### 5.8 Non-functional requirements
- Runs locally or on low-cost hosting.
- Codebase organized enough that both people can reason about the schema.
- Schema diagram, data dictionary, and a short "how data flows" doc exist before Done.

---

## 6. Subsystem 2: The Analyst Work Simulation Engine

### 6.1 The in-app work experience
**Amended 2026-09-02 (see 6.13):** a **real-time, persona-threaded chat interface** — Messenger/Instagram-style, one thread per stakeholder persona, delivered live over a websocket connection — replaces the earlier email/Slack-inbox model. A scenario begins with the Builder, acting as a stakeholder persona (6.5), sending the thread's opening chat message from Subsystem 2's persona composer (6.4/6.13); the Analyst receives and works it from her chat inbox in Subsystem 1 (6.13).

- **Home page:** Open Threads, Company Status, Notifications, Completed Work. **Difficulty tier and evaluation scores are never shown here** (6.7).
- **Notifications:** unread-thread badges in both the Analyst's inbox (Subsystem 1) and the Builder's composer (Subsystem 2) — new message, deadline approaching/missed, scenario completed, monthly review available.
- **Drafting:** composer content (the Builder's persona message or the Analyst's reply) can be saved and edited indefinitely before Send. **Once a message is sent it is immutable — no edit, no unsend** (6.13), consistent with the Decision & Event Ledger's never-silently-rewritten principle (4.4/ER-6), even though this diverges from a real Messenger/Instagram app.
- **Response windows:** default **3–5 real-world days per round**, once Active Use begins, surfaced as a deadline banner on the open thread.
- **Late handling:** marked late, Builder notified; lateness affects evaluation only when explicitly part of what's assessed.
- **External tools:** explicitly permitted (Excel, SQL tools, Python, search, even other AI tools) — the evaluator judges reasoning and communication, not tool use.
- **Work states:** Draft → Open → Awaiting Analyst → Awaiting Stakeholder Reply → Deadline Approaching → Overdue → Under AI Evaluation → Pending Human Review → Completed.

### 6.2 Scenario types (cover at least 5 of 6)

| Type | Example trigger |
|---|---|
| Stakeholder request | "VP wants a dashboard that 'just shows what's broken'" |
| Data quality issue | Reporting layer and WMS disagree on a SKU's stock level |
| Root-cause investigation | 3 stockouts on one SKU in one month (S-004's drifting lead time) |
| Supplier/vendor decision | S-002 (cheap, inconsistent) vs. S-001 (reliable, pricier) |
| Process breakdown | PO approval taking 2x longer than target |
| Executive reporting | "Explain this quarter's OTIF trend to the CFO" |

Every type must be exercised at least once via a QA test run during Build & Test (9.1), independent of any real Analyst usage.

### 6.3 Scenario design patterns
- **Requirements-first scenarios:** some deliberately open with an ambiguous business request where the expected artifact is itself a requirements document, KPI definition, or UAT plan.
- **Ambiguous success criteria:** some intentionally omit a measurable target. The evaluator **rewards responsible uncertainty** rather than penalizing the absence of invented requirements.

### 6.4 Scenario ground truth & evidence trust hierarchy
Hidden ground-truth package per diagnosable scenario: **Known Cause, Evidence, Supporting Signals, Distractors, Expected Considerations, Acceptable/Unacceptable Conclusions, Uncertainty.** Facts are trust-leveled: **Level 1 — Database Fact, Level 2 — Derived Fact, Level 3 — Stakeholder Statement, Level 4 — Stakeholder Belief** (may be wrong). The AI never presents a fabricated number as Level 1/2.

**Scenario validation** before reaching the Analyst: referenced IDs/values match the database, dates are consistent, KPI claims are correct, no contradiction with world state, ground-truth evidence exists, difficulty is valid. On failure: reject, notify Builder, regenerate or edit. **The failure path itself is a required test case** (9.2) — the system must handle a scenario that fails validation gracefully, not silently.

**Builder scenario controls:** select type/storyline/injected issue, set difficulty, preview, inspect evidence/ground truth, edit, regenerate, approve/cancel/activate. **Amended 2026-09-02:** also includes the live persona composer and the on-demand AI sufficiency check (6.13).

### 6.5 Stakeholder personas & information asymmetry

| Persona | Priorities | Style |
|---|---|---|
| Operations Manager | Service level, throughput, warehouse execution | Operational, concrete, impatient with abstraction |
| Procurement Manager | Price, supplier reliability, lead time, contract risk | Cost-focused, comparative |
| Warehouse Manager | Inventory accuracy, workload, practical execution | Operational, may resist workload-increasing changes |
| IT Manager | Data integrity, system behavior, feasibility, risk | Technical, scope-conscious |
| Operations Director / VP | Business outcomes, service level, risk, decisions | Concise, outcome-focused |
| CFO | Financial impact, cost, risk, measurable outcomes | Concise, financially oriented |

### 6.6 The iterative interaction loop
**Amended 2026-09-02:** steps 2 and 5–7 are now live chat turns in the persona thread (6.13), not scripted inbox events.
1. **Trigger** — Builder (or, in Active Use, the ongoing cadence) approves a scenario at the current difficulty tier, optionally referencing the Decision & Event Ledger for continuity.
2. **Notification & initial request** — the Builder, as the chosen persona, composes and sends the thread's opening chat message (typed or AI-suggested, 6.13).
3. **Investigation.**
4. **Initial response**, within the response window, sent as a chat message by the Analyst.
5. **Stakeholder pushback** — the Builder, optionally after invoking the AI sufficiency check (6.13), composes and sends a pushback message as the persona.
6. **Revision** — the Analyst's next chat message.
7. *(Optional additional round.)*
8. **Final submission** — the Builder marks the thread Completed, informed by the AI sufficiency check's recommendation but never automatically triggered by it (6.13); the Analyst's most recent message is the submission of record. Immutable, same as every prior message.
9. **Draft AI evaluation** plus a difficulty-tier recommendation.
10. **Decision recording** into the Ledger, if applicable.
11. **Human review (monthly, Active Use only)** — tier recommendations approved or rejected.
12. **Learning record update** for the portfolio.

Steps 1–10 must all be provable via QA test runs during Build & Test; steps 11–12 are validated structurally (the mechanism exists and works) without requiring a real reviewer or real portfolio content yet.

### 6.7 Competency clusters & adaptive difficulty

| Cluster | Rolls up |
|---|---|
| **Analysis & Diagnosis** | KPI interpretation, data investigation/SQL literacy, root-cause analysis, data-quality awareness |
| **Judgment & Delivery** | Requirements elicitation, decision-making, process improvement, technical delivery/UAT |
| **Communication** | Stakeholder and executive/business communication |

Three clusters, not ten independent competencies — with only 10–12 scenarios expected once in Active Use, ten independent tracks would leave most with one or two data points each, not enough for a meaningful adaptive signal. Most scenarios naturally exercise two of the three clusters.

**Tiers:** Foundational → Standard → Stretch, per cluster. A tier change requires evidence across multiple relevant interactions, not one response — and an explicit **"hold, insufficient evidence"** outcome is a defined, valid result, not a forced guess. **Visibility:** hidden during normal use, revealed together with the human reviewer's assessment once a month, once Active Use begins.

### 6.8 AI evaluation framework
Every evaluation is **DRAFT — NOT AUTHORITATIVE**, built from ground truth, evidence, stakeholder context, expected cluster behaviors, the Analyst's responses, and the outcome. Contains: Strengths, Gaps, Evidence, Senior Analyst Pushback, Final Verdict, Suggested Next Skill Focus, Difficulty Recommendation per cluster. No single number is the sole representation of performance. The AI only receives the structured evidence package, never the full database, and never has direct write access. **The evaluator's own output is schema-validated** — a malformed or incomplete AI response is caught and retried/flagged, never silently accepted (9.2).

### 6.9 Human oversight — non-negotiable (Active Use)

| ID | Requirement |
|---|---|
| ER-1 | AI evaluation always labeled "draft," never authoritative |
| ER-2 | At least one scenario per type reviewed by someone outside the two-person team each month |
| ER-3 | Reviewer disagreements logged as learning artifacts, not failures |
| ER-4 | Reviewer explicitly assesses whether the current tier matches demonstrated level |
| ER-5 | Tier and evaluation trend hidden during normal use, revealed only at monthly review |
| ER-6 | Historical evaluation records never silently rewritten; prompts/templates versioned |

The mechanism behind ER-1 through ER-6 must be fully built and tested during Build & Test; the actual monthly cadence of reviews only starts once Active Use begins and a reviewer is onboarded.

### 6.10 Portfolio & lessons-learned artifact
Compiled per scenario: trigger, responses, pushback rounds, draft evaluation, reviewer notes, and a 7-question reflection (what happened, what I initially thought, what evidence mattered, what I missed, what changed after pushback, what I'd do differently, what skill improved). The export mechanism is built and tested during Build & Test using QA test-run content; real portfolio content accumulates during Active Use.

### 6.12 Admin visibility into SQL practice
The admin panel surfaces Query-page activity (5.9, S1-FR-14) — a table of submitted queries with timestamp, statement type, and result status, expandable to the full query text. Reads from the same query-log table Subsystem 1 writes to. Framed and used as a **coaching signal, not a surveillance one** — consistent with Principle 7 (learning over grading, 1.4).

### 6.11 Non-functional requirements
Reusable/templated prompts; versioned prompts that never silently rewrite history; full exportable history.

### 6.13 Live persona chat: delivery, composer & AI sufficiency check
**Added 2026-09-02.** Full mechanics for the chat redesign referenced throughout 6.1/6.4/6.6.

**Thread model:** one persistent thread per stakeholder persona (6.5) per scenario, not one flat inbox — a Messenger/Instagram-style thread list. A given persona can have more than one thread open across different scenarios.

**Split by role, one shared thread store:**
- **Builder's persona composer (Subsystem 2):** pick the persona, pick an attitude, then type a message or accept an AI-suggested one, and send it as that persona. Also where the Builder invokes the on-demand **AI sufficiency check**.
- **Analyst's chat inbox (Subsystem 1):** receives and replies to threads live, with unread-thread badges (Appendix D.1).
- Both sides read and write through their own subsystem's API layer only — see 7's named exception for how the same thread is reachable, live, from both sides without either side reaching into the other's database.

**AI sufficiency check:** Builder-invoked, mid-conversation, on the current thread. The AI reviews the Analyst's latest message against the scenario's ground truth (6.4) and **recommends** either "sufficient — safe to mark this thread Completed" or "insufficient — here's a suggested pushback message." This is a recommendation only, consistent with the AI never being authoritative (ER-1) — the Builder decides whether to act on it. It is distinct from the post-submission **Draft AI evaluation** (6.8), which runs once after a thread is marked Completed and produces the full graded write-up; the sufficiency check never writes an evaluation record itself.

**Immutability:** every sent chat message is permanent — no edit, no unsend, by either role — per 6.1's amended Drafting bullet. Unlike a real Messenger/Instagram app, "send" has no undo here; it is deliberately the same rule already applied to the rest of the Decision & Event Ledger (4.4/ER-6).

**File attachments (Analyst-side, tightly scoped):** allowlisted types only (images, PDF, CSV); a hard per-file size cap; stored in object storage, never in the operational Postgres database; never executed or interpreted server-side; served back only to the two authenticated roles on the thread. See 8.4.

**Identity:** the Builder and Analyst are distinguished by their own account (email + password, role-tagged — still just two users, not a full identity system — 5.1's scope boundary is unchanged, amended 2026-09-02) so the real-time delivery layer knows which inbox a given connection belongs to. See 8.4.

---

## 7. Integration Between Subsystems
Subsystem 2 reads Subsystem 1's data exclusively through its API layer (S1-FR-6) — never via a direct database connection (8.4). Data changes are reflected in scenarios generated afterward. Schema, KPI definitions, and scenario types are designed together, not sequentially, since they're interdependent.

**Amended 2026-09-02 — the one named exception to this boundary:** live persona-chat delivery (6.13) needs bidirectional, real-time message flow between the Builder's composer (Subsystem 2) and the Analyst's inbox (Subsystem 1). This is implemented as a single shared message store that each subsystem's own API layer reads and writes, with a websocket push on top for live delivery — **not** a direct database connection from one subsystem into the other's schema. Each subsystem still only ever queries its own API layer; the real-time transport is the deliberate carve-out, the same pattern 8.4 already uses for the SQL Query Playground's sandboxed-schema exception.

---

## 8. Technical Architecture, Cost & Security

### 8.1 Stack — confirmed
PostgreSQL (star schema + world-state/ledger tables) · Python/FastAPI · Next.js/React · Claude API · APScheduler running in-process for the simulation clock and notification checks (8.7) · Alembic for schema migrations (8.6).

### 8.2 Deployment & access model
The system must be reachable independently, not run only on the Builder's laptop — this matters even during Build & Test, since QA validation should happen against the real deployment target, not just a local machine.

- **Local development:** Postgres run via **Docker Compose**, so the Builder's environment is reproducible and matches the deployed environment.
- **Deployment:** the FastAPI backend + Next.js frontends deployed to a small always-on host (Railway, Render, or Fly.io all fit the cost target at this scale), connected to a **managed Postgres instance** (Supabase, Neon, or Railway's managed Postgres).
- One environment, not separate dev/staging/prod — unnecessary overhead for a two-person project.

### 8.3 Cost — target ≤ $20/month
Low-volume LLM calls, evidence-only retrieval, free-tier hosting where practical, inexpensive Postgres, no GPU, no unnecessary paid SaaS. QA test runs during Build & Test should also stay within this budget — evidence-only retrieval and minimal prompt sizes apply to test traffic too, not just eventual real usage.

### 8.4 Security & safety
Isolate LLM access from direct database write access; **Subsystem 2 reads Subsystem 1's data only through the API layer (S1-FR-6), never via direct SQL** — one boundary, not two overlapping paths; parameterized queries only in application code; secrets (Claude API key, DB credentials) live in environment variables — `.env` locally, the hosting platform's secret store in the deployed environment, never committed to source control; restrict write operations on master data and all admin panel controls to the Admin (Builder) role, enforced server-side by role, not by which UI hides a button; validate all AI-generated scenario references before activation. **The SQL Query Playground (5.9) is the one deliberate exception to "no raw SQL"** — it connects through a Postgres role scoped only to the sandbox replica schema, unable to reach the live operational schema or Subsystem 2's ledger/evaluation tables under any query — a boundary that must be verified with an actual permission test (9.2), not just asserted.

**Amended 2026-09-02 — role-based login:** the single shared Builder bearer token is replaced by real per-user accounts — email + password, hashed (a vetted library, e.g. `passlib`/`argon2`, never hand-rolled), one account each for the Admin (Builder) and Analyst roles. Still just two known users, no self-registration, no password-reset flow, no email verification — 5.1's scope boundary is unchanged, only the credential model is real now instead of a shared secret. Role is carried in a signed session token issued at login and checked server-side on every request; **Admin** can write master data (Product/Warehouse/Supplier/Carrier/Customer) and use every admin panel control, **Analyst** can view everything Subsystem 1 exposes (dashboards, master data lists, reports, query playground results) but cannot write anywhere — enforced by the same dependency-injection pattern `require_builder` already used, split into a write-gating and a read-gating dependency. This is the credential mechanism 6.13's chat identity (346) and the persona-chat bearer amendment below both now use — a single login, not a separate chat-specific credential.

**Amended 2026-09-02 — persona chat (6.13):** the Builder and Analyst are distinguished by their real per-role login (above), still just two known users, not a full identity/session system — consistent with 5.1's "auth/multi-tenant complexity beyond two users" being explicitly out of scope. **File attachments** are the largest new attack surface this feature introduces and are scoped narrowly: an allowlist of file types (images, PDF, CSV), a hard per-file size cap, storage in object storage rather than the operational Postgres database, no server-side execution or interpretation of uploaded content, and files served back only to the two authenticated roles on the owning thread — this boundary must be tested directly (9.2), not just asserted, same as the Query Playground's.

### 8.5 Non-functional requirements
Reliability (drafts/submissions never lost — verified by the test suite in Section 9, not just asserted); maintainability (one Builder can understand the system); observability (can answer "what did the Analyst see/submit/when" for any completed scenario); documentation kept current.

### 8.6 Data durability
Losing the ledger or scenario history would be a real loss, not a minor bug — even during Build & Test, since QA runs are how the mechanism gets proven. **Automated daily backups** of the Postgres instance are a requirement, and **at least one restore must actually be tested**, not just configured, before Done. Schema changes go through **Alembic** migrations rather than ad hoc manual changes.

### 8.7 Operational details
- **Scheduler:** APScheduler running inside the FastAPI process advances the simulation clock and checks for due notifications.
- **Notifications:** delivered via simple polling (on page load and roughly every 60 seconds while a tab is open) rather than websockets.
- **Timezones:** all timestamps stored in UTC, displayed in local time; response-window deadlines are computed against a fixed reference.

---

## 9. Testing & Quality Assurance

This section is the actual heart of the current phase — "built and fully tested with every edge case covered" is the operative standard, and this section defines what that means concretely.

### 9.1 Testing strategy

- **Unit tests:** KPI calculation logic, exception-rule evaluation, ledger state transitions, difficulty-tier recommendation logic, scenario validation rules, statement-type classification in the Query Playground (SELECT vs. DML/DDL).
- **Integration tests:** the Subsystem 2 ↔ Subsystem 1 API boundary, Claude API call/response handling (mocked for deterministic tests, plus periodic live-call smoke tests), Alembic migrations (both upgrade and downgrade), an actual backup/restore drill.
- **End-to-end tests via a QA test-analyst harness:** a scripted or Builder-operated stand-in plays the Analyst role to exercise the full loop (6.6) for each of the 6 scenario types at least once, including multi-round pushback, a decision entering the Ledger, and at least one simulated callback scenario. This is how the system gets proven correct **without** requiring the real Analyst's time — directly addressing the project's current priority.
- **Load/volume sanity checks:** not a priority at two-user scale, but worth confirming the simulation clock doesn't degrade advancing across many simulated days, and that the Query Playground behaves under a large sandbox result set.

### 9.2 Edge case catalog
Every row below needs an explicit test with a defined expected behavior — "undefined" is not an acceptable answer for any of these by the time the system is Done.

**Data & Simulation (Subsystem 1)**

| Edge case | Expected behavior |
|---|---|
| Orphaned foreign key (e.g., a Shipment referencing a deleted Sales Order) | Caught by validation, surfaced as a data-quality exception (S1-FR-4), not a silent null or a crash |
| Duplicate records injected (SR-3) | Detected and flagged, not silently deduplicated or silently accepted |
| Negative or zero inventory quantities | Rejected at the write boundary or flagged as an exception, never displayed as valid stock |
| Partial PO receipt (received quantity ≠ ordered quantity) | Correctly reflected in inventory and OTIF/fill-rate calculations, not treated as either "complete" or "missing" |
| Simulation clock crossing a month/year boundary mid-scenario | KPI period calculations remain correct; no off-by-one-period errors |
| Concurrent snapshot/reset operations | Serialized safely; no corrupted or partial world state |
| Reset triggered while a scenario is active | The in-flight scenario's own `world_state_id` (4.2) is unaffected — explicitly tested, not assumed |
| Reporting-layer lag exceeding its expected window (simulated scheduler downtime) | Detected and surfaced, not silently masked as normal latency |
| Master-data edit (Warehouse/Supplier/Carrier) applied mid-scenario | Historical scenario data referencing the old values is unchanged (5.6) — explicitly tested |

**Decision & Event Ledger (4.4)**

| Edge case | Expected behavior |
|---|---|
| Decision proposed but never approved/rejected | Flagged as stale after a defined period, not left in permanent limbo |
| Decision partially implemented, then the scenario is abandoned | Ledger state accurately reflects "partial," not "complete" or silently dropped |
| Callback scenario referencing a decision whose underlying entity was later deactivated | Handled gracefully — the callback still functions, referencing the entity's state at decision time |
| Two decisions affecting the same entity with conflicting outcomes | Both are preserved in the ledger; no silent overwrite |

**Scenario Engine (Subsystem 2)**

| Edge case | Expected behavior |
|---|---|
| AI generates a scenario referencing non-existent or stale IDs | Caught by scenario validation (6.4), rejected before reaching any user, Builder notified |
| Scenario deadline passes with no response | Marked overdue per the defined work states (6.1), Builder notified, doesn't silently vanish |
| Empty or malformed response submitted | Rejected with a clear message, not silently accepted as a valid submission |
| Maximum pushback rounds exceeded | Loop concludes gracefully and proceeds to evaluation, doesn't hang indefinitely |
| Claude API error/timeout during generation, pushback, or evaluation | Retried once automatically; if it still fails, flagged to the Builder rather than failing silently or corrupting scenario state |
| Two scenarios attempted active simultaneously | Prevented by default — one active scenario at a time, matching realistic single-threaded workload |
| Evaluation call returns malformed/incomplete output | Caught by schema validation on the AI's own response (6.8), retried or flagged, never accepted as-is |

**SQL Query Playground (5.9)**

| Edge case | Expected behavior |
|---|---|
| Long-running/runaway query | Cut off by a statement timeout, with a clear message |
| Query returning a very large result set | Row-limited/paginated, not rendered in full or crashing the browser |
| Multi-statement submission with a destructive statement chained after a harmless one | Confirmation dialog catches the destructive statement regardless of position |
| Malformed SQL / syntax error | Clear, readable error shown — never a raw stack trace |
| Sandbox refresh triggered mid-query | The in-flight query completes against a consistent snapshot or fails cleanly — never a silently corrupted read |
| Attempted write against a table outside the sandbox schema | Rejected at the database permission level (8.4) — this is the test that actually proves the hard boundary works |

**Adaptive Difficulty & Evaluation (6.7, 6.8)**

| Edge case | Expected behavior |
|---|---|
| Insufficient observations in a cluster | Explicit "hold, insufficient evidence" result — never a forced tier change |
| Conflicting signals within one cluster across scenarios | A defined trend rule resolves it (not ad hoc judgment call each time) |
| Reviewer overrides an AI tier recommendation | Logged distinctly from simple agreement (ER-3/ER-4) |

**Notifications, Scheduler & Deployment**

| Edge case | Expected behavior |
|---|---|
| Scheduler downtime (e.g., a server restart) | Simulation clock and pending notifications recover cleanly on restart — no double-fires, no lost events |
| Draft-saving during a network interruption | In-progress text is not lost (8.5's reliability requirement, made concrete) |
| Backup restore | Actually performed at least once as a test, not just configured — an untested backup is not a tested safety net |

### 9.3 Acceptance testing checklist
Mirrors Section 1.6 as literal pass/fail items:

- [ ] Full automated test suite passing (unit, integration, E2E)
- [ ] Every row in 9.2's edge case catalog has a passing test
- [ ] QA test-analyst harness has completed all 6 scenario types at least once, including a simulated callback scenario
- [ ] Zero demo/mock data remains in either frontend template
- [ ] Backup restore tested and confirmed working
- [ ] Query Playground's permission boundary tested and confirmed (cannot reach live/ledger tables)
- [ ] Deployment live, reachable, and matches the Docker Compose local environment
- [ ] Documentation complete (schema diagram, data dictionary, data-flow doc, testing report)
- [ ] End-to-end live walkthrough deliverable without improvisation, using QA/synthetic data

---

## 10. Build Phases & Exit Criteria
No calendar targets — phases are sequential and dependency-based. Each has a concrete, testable exit criterion rather than a date, so progress is judged by what's actually working, not what week it is.

### Phase 1 — Foundation
- [ ] Both frontend templates cloned; **all demo/mock/fabricated data removed** before any real wiring begins (Appendix D)
- [ ] Pages selected per Appendix D scaffolded and connected to the real API layer
- [ ] Database schema implemented (dimensions, facts, ledger tables)
- [ ] Baseline data generator produces a clean, plausible starting Meadow Packaging & Supply state
- [ ] Simulation clock skeleton (advance/pause/snapshot/reset) working
- [ ] Control-tower dashboard skeleton (shell, not yet real KPIs)
- [ ] Admin panel: master-data CRUD for Product/Warehouse/Supplier/Carrier live (S1-FR-12)
- [ ] SQL Query Playground: sandbox schema + scoped DB role provisioned (5.9)
- [ ] Default exception-rule thresholds and starter KPI SQL implemented (S1-FR-10/11's placeholder, pending Analyst review in Active Use)
- [ ] Prompt template skeletons drafted (generation, stakeholder roleplay, evaluation)
- [ ] Unit test suite scaffolded and running in CI (or a local equivalent)

**Exit criterion:** company data flows end-to-end into Postgres, through templates that contain zero demo data; the Builder can browse it; the schema and thresholds exist and are testable.

### Phase 2 — Operational System
- [ ] End-to-end data flow working on schedule (procure-to-stock, order-to-ship)
- [ ] Core KPIs calculating correctly (OTIF, fill rate, days of supply, order cycle time, perfect order rate)
- [ ] Exception engine flags at-risk POs / low stock / late shipments
- [ ] Dashboard live with drill-down across all five views (5.4)
- [ ] API layer exposed for Subsystem 2
- [ ] Reporting-layer lag implemented (SR-2)
- [ ] At least one seeded conflicting-source or bad-data case working (SR-3/SR-4)
- [ ] Scenario builder controls working (select/inject/preview/approve)
- [ ] SQL Query Playground fully functional: editor, results table, confirmation dialog for DML/DDL, query logging, statement timeout, row limits (5.9, S1-FR-13/14)
- [ ] Integration tests covering the Subsystem 1 ↔ Subsystem 2 API boundary passing

**Exit criterion:** the dashboard is demoable with real KPIs and drill-down; a data-quality issue can be injected and observed; a QA test run has exercised the Query Playground including its confirmation flow.

### Phase 3 — Full Simulation Loop
- [ ] In-app work interface complete: real-time persona-chat inbox (Subsystem 1) and composer/thread monitor (Subsystem 2), notifications, drafting, deadlines, file attachments (6.1/6.13, added 2026-09-02)
- [ ] Full multi-round loop working end-to-end (6.6, steps 1–10), validated via QA test-analyst runs
- [ ] Stakeholder personas implemented and behaving distinctly
- [ ] Decision & Event Ledger live with at least one full lifecycle tested (proposed → outcome)
- [ ] Adaptive difficulty engine live (3 clusters, tier recommendations recorded and testable)
- [ ] Admin: SQL query history view live (6.12)
- [ ] Human review workflow built and testable (ER-1 through ER-6 mechanisms functioning, independent of a real reviewer being onboarded yet)
- [ ] Warehouse transfers and carrier variability implemented
- [ ] All 6 scenario types exercised at least once via QA test runs, including a simulated callback scenario
- [ ] Full edge case catalog (9.2) implemented and passing

**Exit criterion:** a full scenario can be demoed live start-to-finish via a QA test run — request, investigation, response, pushback, revision, draft evaluation, ledger recording. A simulated callback scenario has actually run.

### Phase 4 — Hardening & Delivery
- [ ] Full acceptance testing checklist (9.3) passing
- [ ] Backup restore drill completed successfully
- [ ] Query Playground permission boundary explicitly verified
- [ ] System documentation finalized (schema diagram, data dictionary, data-flow doc, testing report)
- [ ] Deployment verified in the actual target environment (8.2), not just locally
- [ ] Final walkthrough script prepared, using QA/synthetic data
- [ ] **Definition of Done (1.6) fully satisfied**

**Exit criterion:** the platform is Done. Active Use (Section 11) can begin whenever the Analyst is ready.

---

## 11. Post-Delivery: Analyst Onboarding & Ongoing Use
This section documents what happens **after** Done — kept separate so it never gets treated as a build-phase dependency, while still being fully specified so the platform actually supports it correctly on day one of real use.

### 11.1 Time budget
Once Active Use begins, the Analyst's time is the real constraint on pacing: roughly 5 hours/week, totaling roughly 85 hours across the full arc of completing 10–12 scenarios plus her hands-on Subsystem 1 role. This has no calendar attached — it's a pacing assumption the system's design already respects (async response windows, capped scenario count, coarse competency clusters), not a deadline.

### 11.2 Her hands-on role begins
- Reviews and adjusts the Builder's placeholder exception-rule thresholds (S1-FR-10), refining at least one after observing real behavior.
- Reviews and adjusts the core KPI SQL (S1-FR-11).
- Uses the SQL Query Playground (5.9) for open-ended practice whenever she wants — the sandbox makes this consequence-free.

### 11.3 Scenario cadence begins
10–12 real scenarios, across at least 5 of the 6 types (6.2), each running the full iterative loop (6.6). Backend complexity (the persistent simulation, the ledger, source-system tagging) stays entirely invisible to her — she only sees a work interface, a dashboard, and stakeholders who remember prior conversations.

### 11.4 External reviewer & monthly review
The Builder sources a real external reviewer (professor or working IS/SC professional) — this can happen anytime before or during early Active Use; it's independent of Section 1.6's Done criteria. Once onboarded, the monthly review cadence (ER-1 through ER-6) begins for real: sampled evaluations reviewed, difficulty tiers confirmed or corrected, disagreements logged as learning artifacts.

### 11.5 Program Complete — criteria
Active Use is considered complete when:
- 10–12 real scenarios are completed across at least 5 of the 6 types;
- the adaptive difficulty tier has shifted at least once for at least one competency cluster, confirmed reasonable by the external reviewer;
- at least one real decision-callback scenario has run;
- at least one AI evaluation per scenario type has been reviewed by the external reviewer, with any disagreements logged;
- a compiled, interview-ready portfolio exists (6.10), built from real scenario history.

A short stabilization window should be expected at the start of Active Use — however thorough the Build & Test phase's QA coverage, real usage tends to surface a handful of issues synthetic testing didn't anticipate. The Builder should stay available for prompt fixes during this window rather than considering the relationship finished at Done.

---

## 12. Scope Priorities (Build Risk Fallback Plan)
If engineering risk threatens the Build & Test phase's completion, cut in this order:

- **Priority 1 — must preserve:** persistent company state, core operational data, core KPIs, scenario grounding, stakeholder interaction, the full iterative loop, evidence validation, the SQL Query Playground's hard permission boundary, the edge case catalog's data-integrity rows (9.2).
- **Priority 2 — preserve where feasible:** decision consequences/callback mechanism, source-system tagging and Reporting-layer lag, adaptive difficulty, warehouse transfers, carrier variability, the full in-app work experience's notification polish.
- **Priority 3 — cut first:** visual polish, secondary dashboard widgets, extra source-system nuance, advanced simulation realism, nonessential automation, the optional Tasks/kanban view (Appendix D).

The target scenario-type coverage for QA validation remains all 6; if genuinely constrained, 5 of 6 is the floor — consistent with 6.2/11.5's own minimum.

---

## 13. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Project becomes an ERP instead of a simulation | Hard subsystem boundaries (5.1) |
| Scenarios reduce to a quiz | Iterative loop required; persistent ledger (4.4) |
| AI invents operational facts | Structured evidence packages + pre-activation validation (6.4) |
| AI evaluation is wrong | Mandatory monthly human review once Active Use begins (ER-2/3) |
| Difficulty calibration is noisy | 3 broad clusters, minimum-observations rule, explicit "hold" state, reviewer authority (ER-4) |
| System ships with untested edge cases | Comprehensive catalog (9.2) with pass/fail acceptance criteria (9.3), gating Done itself |
| QA testing can't fully substitute for real usage | Explicit stabilization-window expectation at the start of Active Use (11.5) |
| Persistent simulation becomes overly complex to build | Builder-only complexity; UI exposure stays minimal (6.1) |
| Decision outcomes distort evaluation | Decision quality evaluated separately from outcome quality (4.4) |
| Source-system complexity overwhelms the build | Tags + one lagged view, not four systems (4.1) |
| External reviewer takes a while to source | Fully decoupled from Done (1.6); only needed once real evaluations exist (11.4) |
| LLM costs exceed budget | $20/month target; evidence-only retrieval, applies to QA test traffic too (8.3) |
| Query Playground's sandbox boundary has a gap | Explicit database-permission test required before Done, not just design intent (9.2) |
| Untested backup turns out not to actually work when needed | Restore drill required before Done, not just backup configuration (8.6, 9.3) |
| Persona-chat's real-time cross-subsystem path erodes the API-only boundary (added 2026-09-02) | Named as the one explicit exception (7), both sides still only query their own API layer, shared message store not a cross-schema DB connection (6.13) |
| Chat file attachments become an injection/storage vector (added 2026-09-02) | Type allowlist, size cap, object storage (not the operational DB), no server-side execution, tested directly like the Query Playground boundary (8.4, 9.2) |

---

## 14. Open Items
Everything substantive has been resolved. What remains is entirely execution, not decisions:

- **External human reviewer:** the Builder sources this independently; fully decoupled from Done, needed only once Active Use produces real evaluations (Section 11.4).
- Exact field-level schema, finalized during implementation rather than pre-specified — the table-level shape (Appendix B) and starter data (Section 3) are enough to start building.

---

## Appendix A: KPI Reference
- **OTIF:** % of qualifying orders delivered on time and complete.
- **Fill rate:** % of demand met immediately from available stock without backorder.
- **Days of supply:** usable inventory ÷ average daily usage.
- **Order cycle time:** elapsed time from order placement to delivery.
- **Perfect order rate:** % of qualifying orders with no defined process/fulfillment errors.

---

## Appendix B: Core Schema Summary (~22 tables)
**Dimensions (6):** Product, Warehouse, Supplier, Customer, Carrier, Date.
**Facts (7):** Inventory Snapshot, Inventory Transaction, Purchase Order, Sales Order, Shipment, Warehouse Transfer, Decision & Event (unified ledger).
**Subsystem 2 supporting tables (~9):** Scenario, Scenario Snapshot, Stakeholder Persona, Interaction, Evaluation, Human Review, Portfolio Artifact, Prompt Version, Template Version.
**Chat (added 2026-09-02, 6.13):** Chat Thread (one per persona per scenario) and Chat Message (individual sent messages, immutable, optionally carrying a file-attachment reference) — Interaction rows for a scenario now correspond to its thread's Chat Messages rather than a separate parallel record.

---

## Appendix C: Representative End-to-End Walkthrough
*(Used as the model for the QA test-analyst harness, Section 9.1 — this is what "the loop works" concretely looks like.)*

An Operations Director messages: *"East's service is getting worse. I need to know what's happening and what we should do."* The test-analyst run has to establish what's actually being asked before investigating. It finds fill rate has dropped, one SKU keeps stocking out, Supplier S-004's lead time has crept up, and WMS-tagged inventory disagrees with the Reporting layer by a day's lag. A stakeholder claims "the warehouse keeps shipping late" — the response verifies that's only part of the story. The recommendation: correct the inventory discrepancy, temporarily raise safety stock, review S-004's allocation, and monitor for four weeks. The Director approves the operational changes; Procurement partially approves the reallocation. The simulation advances — service improves for the SKU, but carrying cost rises at another warehouse. A follow-up scenario then arrives: *"Your changes helped East, but inventory carrying cost is now higher. Should we keep the new policy?"* — the callback mechanism. Proving this entire arc works with a QA stand-in is what Phase 3's exit criterion (Section 10) actually means in practice.

---

## Appendix D: Frontend Template Selection & Page Mapping

Both templates are React/Next.js/shadcn-ui/TanStack Table — an exact match for the confirmed stack (8.1). Both MIT licensed. **Both ship entirely with demo/mock data — every page listed below must have its fabricated content stripped before real wiring begins (Phase 1, Section 10); this is a required build step, not optional cleanup, and is explicitly part of the Definition of Done (1.6).**

### D.1 Subsystem 1 (Control Tower + Admin Panel) — `masondevx/orbynadmin`
Next.js 16, TypeScript, Tailwind v4, shadcn/ui, Recharts, TanStack Table. Demo data lives in `src/data/index.ts` plus inline datasets on a handful of pages — all of it goes.

| Template page | Adapt for | Notes |
|---|---|---|
| Logistics dashboard | Executive/Overview KPI view (5.4) | Closest existing starting point for OTIF/fill rate/days-of-supply cards |
| Analytics dashboard | KPI trend drill-down | Charting backbone (Recharts) reused as-is |
| Reports dashboard | Data-Quality view | Exception and conflicting-source reporting (SR-3/SR-4) |
| Inventory (e-commerce) | Inventory Position / Snapshot view | Direct entity match |
| Orders (e-commerce) | Sales Orders view | Generalize for Purchase Orders — same table pattern, different entity |
| Shipping (e-commerce) | Shipment tracking / OTIF drill-down | Direct entity match |
| Customers (e-commerce) | Customer master data | Direct entity match |
| Customers pattern (duplicated) | Supplier and Carrier master-data pages | No native template page for these — clone the Customers list+detail pattern twice |
| Activity log (project mgmt) | Decision & Event Ledger view (4.4) | Timestamped log pattern fits directly |
| Reusable data table | Every list view, master-data CRUD, and Query results (5.9) | The single most-reused component from this template |
| Settings | Master-data CRUD forms (5.6), exception-threshold config (S1-FR-4/10) | |
| Notifications | Admin-side exception alert feed | Separate from the Analyst's notifications in Subsystem 2 |
| Auth (Login only) | Simple auth (8.4) | Drop Register/OTP/Lock-screen variants |
| 404 | Basic error handling | Drop 403/500/503/Maintenance/Coming-soon |
| — | **Query page (5.9)** | Not in the template — build with CodeMirror 6 or Monaco, results shown in the reused data table |
| Chat | **Analyst's persona-chat inbox (S1-FR-15, 6.13)** | **Added 2026-09-02, reversing the original "discard" call below** — thread list = one row per persona, unread badges, file attachment on the Analyst's replies |

**Discard entirely:** Crypto/Web3, Healthcare, HR, Real Estate dashboards; Cart, Checkout, Discounts, Reviews, Categories; Kanban/Timeline/Gantt/Team/Roles & Permissions/Contacts; AI Assistant, Mail, Calendar, Tasks, Notes, File Manager, Support, Blog; Developers/API-keys, Pricing, Integrations, Help Center; Landing page, Onboarding. *(Chat removed from this list 2026-09-02 — see the table row above.)*

### D.2 Subsystem 2 (Analyst Work Simulation Engine) — `chanseek/shadcn-dashboard`
Use the **Next.js version** (the repo also ships a Vite version) — keeps both subsystems on the same framework. React 19, TypeScript, Tailwind v4, shadcn/ui v3, Zustand, TanStack Table. It's a fork of a landing-page/dashboard combo template — the landing-page half is entirely unrelated and discarded outright.

| Template page | Adapt for | Notes |
|---|---|---|
| Mail (Inbox / Read / Compose) | **Builder's persona composer & thread monitor (6.4/6.13)** | **Amended 2026-09-02** — the Analyst's own work interface moved to Subsystem 1's Chat page (Appendix D.1, 6.13); this page is repurposed as the Builder's side instead: Inbox = all active persona threads, Read = a thread's full history, Compose = pick persona/attitude, type or accept an AI-suggested message, send — and invoke the AI sufficiency check |
| Dashboard (Overview) | Home page (6.1) | Open Threads / Company Status / Notifications / Completed Work — **must not surface difficulty tier or scores here (6.1, ER-5)** |
| Calendar | Response-window deadline view | Across active scenarios |
| Users (advanced table) | **Repurposed** — not literal user management (there's one Analyst) | Reused as the table pattern for scenario/portfolio history and the SQL query-history admin view (6.12) |
| Settings | Analyst notification preferences; separate admin-only area for scenario templates/prompt versions/difficulty overrides | |
| Auth (one variant) | Simple auth (8.4) | Drop the extra style variants |
| Error pages (404 only) | Basic error handling | Drop 401/403/500/Maintenance |
| Tasks (drag & drop) | *Optional* — kanban view of work-queue states (6.1) | Nice-to-have secondary view, not required for Done |

**Discard entirely:** the full Landing Page template (Hero/About/Features/Stats/Logo Carousel/Team/Testimonials/Blog/Pricing/FAQ/Contact/CTA); Chat (the persona conversation lives in the repurposed Mail page above, on the Builder's side — see 6.13; this app's own Chat template page still isn't needed); Billing/Plans, Connections, Pricing, FAQ.
