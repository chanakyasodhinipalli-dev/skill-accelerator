# PROMPT — Leadership Briefing · Intake Portfolio, Tiered Model, Four Phases

Copy everything below the line into a fresh session.

---

Build me a PowerPoint deck (.pptx) for a senior leadership audience. Title slide plus **7 content slides**, in this exact order: (1) the problem, (2) the tiered model, (3) Phase 1, (4) Phase 2, (5) Phase 3, (6) Phase 4, (7) the compounding view and the ask.

**Keep on-slide text minimal and carry the content in infographics** — tables, stacked bars, colour-coded strips, tiles. The full argument lives in the **speaker notes**, which must be substantial enough that the presenter can answer any question the slide provokes. Treat the notes as a primary deliverable, not an afterthought.

## Context you are working from

I lead work on an enterprise ECM platform team. ECM provides repository services to partner applications for storage, archival and records management, with metadata compliance and document classification applied on arrival. Three scrum teams, thirty-plus engineers. Every partner intake is currently delivered through a dedicated capacity model from inception to release.

**Domain vocabulary to use correctly:** ICMP; iDocs (document classification); the DKE — Document Knowledge Engine, maintained by Imaging Governance, which trains the model iDocs uses for untrusted content; Imaging Governance determines trusted vs untrusted on the flow and allocates category/type/subtype for trusted content; Records Management owns retention, INV160 and WORM; SPLI is load testing; KEES is Kafka Enablement Engagement Services; DCT performs virus scanning; Apigee is the API gateway.

---

## SLIDE 1 — The problem

Three blocks: the intake portfolio, where enabler-squad time actually goes, and the gaps in the always-dedicated model.

### The intake portfolio — ten categories, 38 distinct scenario types

Render as **two compact tables side by side**, five rows each, with columns *Intake category / Types / Effort / ECM days*. The Effort cell is a coloured pill — High in rust on a rust tint, Medium in amber on an amber tint, Low in green on a green tint.

| Intake category | Types | Effort | ECM days |
|---|---|---|---|
| New partner onboarding (greenfield) | 4 | High | 35–60 |
| New document types / content extension | 7 | Medium | 8–20 |
| Channel & integration additions | 5 | High | 20–40 |
| Volume & performance uplift | 3 | Medium | 10–18 |
| Metadata & data model changes | 4 | Medium | 8–16 |
| Retention & records changes | 3 | High | 15–30 |
| Security & access changes | 3 | Low | 4–8 |
| Environment & cutover requests | 3 | Low | 3–6 |
| Migration & remediation campaigns | 2 | High | 40–90 |
| Support & ownership changes | 4 | Low | 2–5 |

Totals: 38 types — **10 Low, 14 Medium, 14 High**. The spread is the point: two to five days at one end, forty to ninety at the other, and all of them handled with the same dedicated pod.

### Where an enabler squad member's time goes

A **full-width 100% stacked bar**, each segment carrying its percentage in large white type and its label beneath:

| Segment | Share | Colour |
|---|---|---|
| Design judgement | 18% | navy `15304F` |
| ECM build & config | 24% | steel `3E6686` |
| Chasing partner-owned inputs | 31% | rust `A44A2A` |
| Chasing external teams | 15% | light rust `C86B45` |
| Tracking & admin | 12% | slate `7C8798` |

Colour the two chasing segments in the rust family so **46% of the bar reads visually as chasing rather than engineering**.

### The subsidy argument — a rust callout band under the bar

Kicker: **"A dedicated resource is a subsidy for incomplete intake."** Body: forty-six per cent of time is chasing rather than engineering, and two thirds of that is for inputs the partner owns — document inventory and samples · volume and peak projections · retention requirements and their regulatory basis · the business meaning of metadata · the entitlement model · test data · UAT participants · the support and on-call owner. Because someone is always assigned to chase, the cost of supplying none of it up front falls on us instead of on the partner.

### The gaps — four rust-outlined cards with a coloured left edge

1. **Depth is uniform, need is not** — 10 of the 38 types need under ten ECM days. Every one is given a full pod anyway.
2. **The hard intakes are starved** — the 14 genuinely complex types compete for the same attention as 24 that are not.
3. **Responsibility transfers quietly** — with someone always assigned to chase, the partner never feels the cost of an incomplete intake.
4. **Growth has only one answer** — capacity = demand × fixed depth, so every uplift in partner demand becomes a headcount request.

Close with a note: the effort split is the squads' own estimate, not a measurement; producing that measurement is an explicit Phase 1 deliverable.

---

## SLIDE 2 — The solution: the tiered model

### Four advantages — a row of four green-outlined cards

1. **Depth matches assessed need** — engineering depth becomes a variable set by a published rubric, instead of a constant applied to everything.
2. **Capacity stops scaling linearly** — Lean costs almost nothing per intake and one shared pool serves every Lean+ intake, so demand growth stops meaning headcount growth.
3. **Partner obligations become explicit** — each tier states what the partner must do to receive it; responsibility stops transferring silently to whoever was assigned.
4. **Allocation stops being political** — a published rubric with hard overrides replaces escalation; an appeal argues a determinant, never importance or urgency.

### The four tiers — a five-column table

Columns: *Tier / ECM allocates / Checkpoints / Guardrails specific to the tier / Steady*. The tier cell gets a tinted background and coloured bold text, with the pill capped at about 0.30" high so it does not fill a tall row.

| Tier | ECM allocates | Checkpoints | Guardrails specific to the tier | Steady |
|---|---|---|---|---|
| **Lean** | No dedicated capacity | Entry check at triage — pattern confirmed and completeness band met. Exit check before go-live. No scheduled design review. | All eight invariants, evidenced by checklist · any deviation from the pattern forces escalation to Lean+ · partner must already have completed one prior intake. | 16 |
| **Lean+** | A shared pool, part-time | Two mandatory design checkpoints — solution shape after triage, build readiness before configuration — plus a pre-go-live gate walk. | All eight invariants · the named guide signs the design record · no artefact means no review, rebook · scope beyond the pattern forces a re-tier. | 13 |
| **Dedicated** | A full pod, inception to release | Continuous: architecture review · design authority sign-off · integration readiness · pre-UAT · pre-go-live · post-go-live review. | All eight invariants plus full design authority review · a joint delivery plan with the partner · formal change control on any scope movement. | 7 |
| **Factory** | A campaign team, time-boxed | Campaign entry certification · mid-campaign sampling audit · campaign exit certification. | All eight invariants applied to a batch remediation standard signed off once per campaign · sampling assurance to a defined confidence level. | 2 |

### Closing navy band — the compliance position

**"A lighter tier is a lighter allocation of judgement — never a lighter standard."** All four tiers meet the same eight compliance invariants: classification determination · retention approval · security and access review · volume certification · promotion ladder · support acceptance · audit trail · new document type re-review. What changes between tiers is how much design judgement ECM allocates to reaching them, and how that judgement is scheduled. Tier is assigned by ECM against a seven-determinant rubric with hard overrides — never chosen by the partner, and appealable on a determinant but not on preference.

---

## SLIDES 3–6 — One slide per phase, all on an identical template

Write a single `phaseSlide()` function and call it four times. Every phase slide has, top to bottom:

**A. A phase identity band** in the phase colour, full width, ~0.72" high: "PHASE n" kicker, the phase name in large serif white, and three right-aligned fact columns.

**B. The partner journey strip** — the recurring visual that carries the whole narrative. Five stages across the full width: *Raise the intake · Establish requirements · Build & configure · Clear the gates · Go live & support*. Each stage is a box with a coloured top rule, a bold stage name, one line of description, and a small footer label naming **who drives it**, colour-coded: **ECM drives** navy `15304F`, **Shared** steel `3E6686`, **Partner drives** green `2E6B4F`, each on a matching tint. Put a small three-item legend at the top right of the strip. Chevrons between the boxes.

The strip must visibly "green up" from Phase 1 to Phase 4 — that progression *is* the self-service story and is the single most important recurring element in the deck.

**C. Two cards side by side** — "What changes in this phase" (left) and "Automation, AI and agentic capability" (right). On Phase 1 the right-hand card is deliberately the panel grey, not a phase colour.

**D. A value tile** (left, ~7.3" wide, phase-coloured top rule, three body lines, and a **green footer strip carrying the delta against the preceding phase**) beside a **rust "what this phase cannot fix" card** (right, ~4.9"). Size the value tile so three body lines fit without the last one clipping — about 1.64" high.

### Phase 1 — Evaluate

Facts: Dependency **ECM leadership only** · Builds **Nothing at all** · Duration **One quarter**.

Journey: Raise — *partner raises it; ECM triage classifies and routes* (ECM). Establish requirements — *90-minute Discovery Triage from a written guide; every gap dated and owned* (Shared). Build — *pod, shared pool or published pattern, by assigned tier* (ECM). Gates — *checklist walked by lead and pool; every waiver recorded* (ECM). Go live — *ECM-led cutover, handover and support acceptance* (ECM).

What changes — "Six workstreams of operating discipline, one of design": tier model published and socialised to the three squads and the partner community · triage template rebuilt around the 54-point question set, every item carrying its reason · triage leads assign the tier and select the guardrails, with the basis recorded · partner tier charter issued with every assignment (what you receive, what you owe, why this tier) · a shared pool of four to six stood up from the three existing squads · governance, approvals and a waiver log reviewed fortnightly.

AI card — **"None — and deliberately so"**: nothing is built, nothing is procured, no agent is deployed; every mechanism the model needs has a human equivalent we already have the knowledge to run. The only forward-looking work is design, not construction — an architecture evaluation that specifies and costs Phase 2 (target architecture, the agentic authority model, the integration inventory, a build estimate). Roughly two weeks of architect time across the quarter, which is why Phase 1 ends with a costed proposal rather than a request for more time.

Value — "Depth stops being uniform": 17 scenarios move from a continuous pod to scheduled design assurance, Dedicated falls 38 → 14 · clarification cycles fall on the deeper triage alone and long-lead items are raised at triage · the first measured effort and elapsed-time baseline we have ever had. Delta: *better than today — the 14 genuinely complex intakes stop competing with 24 that are not, at a cost of about two weeks of writing.*

Cannot fix: clerical load untouched · per-intake effort roughly constant, so it still does not scale · the partner still cannot act unaided and external queue time is unchanged · guardrails enforced by people under schedule pressure can still be waived.

### Phase 2 — Automate inside ECM

Facts: Dependency **ECM engineering only** · Builds **What ECM owns outright** · AI **Agentic, inside the perimeter**.

Journey: Raise — *partner raises it unaided through a guided intake* (**Partner**). Establish requirements — *AI copilot asks the catalogue questions and explains why each is needed* (Shared). Build — *ECM artefacts generated from the matched pattern* (ECM). Gates — *ECM gates enforced by the gate engine; external gates still manual* (ECM). Go live — *ECM-led, but with live state visible to the partner* (ECM).

What changes — "Everything inside the ECM perimeter": guided intake with the why-register, completeness enforced at source rather than discovered in week six · gap register that ages open items, chases owners and escalates on the due date · tiering assistant scores the determinants and proposes a tier, the lead still decides · pattern matcher and automatic scope derivation from the catalogue seeded in Phase 1 · ECM artefacts generated (repository definitions, metadata mappings, retention bindings, configuration) · partner cockpit showing read-only state, open gaps, next action and due dates.

AI card — **"Agentic, with authority that stops at the perimeter"**: an Onboard360AI orchestrator with sub-agents bounded strictly by the ECM perimeter — intake copilot, completeness agent, tiering assistant, pattern matcher, scope composer, artefact generator, gate checker. The authority boundary is **architectural, not a setting**: agents propose and prepare, a named person decides, and anything irreversible or compliance-bearing takes a second explicit authorisation. No agent holds a credential that can promote, approve or clear — if one is wrong, the blast radius is a bad proposal that a person rejects.

Value — "The data deficit attacked at source": completeness enforced at intake, the intervention aimed squarely at the 31% spent chasing partner-owned inputs · ECM artefacts generated rather than assembled, removing the clerical load Phase 1 could not touch · three scenarios move Lean+ → Lean. Delta: *better than Phase 1 — effort per intake finally falls, instead of only being better aimed.*

Cannot fix: every external hand-off is still a manual submission into another team's queue · those queues become the dominant share of elapsed time once our own effort has fallen · **Dedicated does not move at all** — automating our work does not make a complex intake less complex · Phase 2 makes ECM efficient, it does not yet make onboarding fast.

### Phase 3 — Orchestrate outward

Facts: Dependency **In-house partner teams** · Builds **Across the boundary** · AI **Agents assemble, validate, chase**.

Journey: Raise (Partner) · Establish requirements — *copilot-guided, with long-lead items identified and raised on day one* (**Partner**) · Build — *ECM artefacts generated; external provisioning requested in parallel* (ECM) · Gates — *external requests assembled, validated and tracked end to end* (**Shared**) · Go live — *ECM-led, with every dependency visible and chased* (ECM).

What changes — "Every hand-off outside the ECM perimeter": contract-first integration with Imaging Governance, Records Management, Security, Apigee, KEES, DCT and SPLI · requests assembled from the intake record and validated against each team's acceptance criteria **before** submission · long-lead items (DKE changes, new retention bindings, SPLI certification) raised at triage rather than at the point of need · status tracked, SLAs measured, escalation automatic on breach · what we ask of those teams is modest — written acceptance criteria, a structured channel, a readable status signal.

AI card — **"Agents that assemble and chase, but never decide"**: agents build each external request from the intake record, check it against the receiving team's published acceptance criteria, submit, track status and chase on SLA breach. They influence no determination whatsoever — Imaging Governance still determines trust posture and allocates category, type and subtype; Records Management still approves retention and certifies WORM. What changes is that requests arrive complete and explained, converting a three-cycle hand-off into a one-cycle hand-off.

Value — "Queue time stops dominating": rework cycles with external teams removed · the 15% of squad time spent chasing external teams largely disappears · Dedicated finally moves 14 → 11. Delta: *better than Phase 2 — cuts waiting, a different quantity from effort that no ECM automation can reach.*

Cannot fix: partner still depends on us to initiate every build step, cockpit still read-only · eleven scenarios stay Dedicated through genuine novelty · the backlog still competes with new demand · dependency on external SLAs is now measured rather than hidden, which is an improvement but not control.

### Phase 4 — Partner self-service

Facts: Dependency **The partners themselves** · Builds **Partner-facing** · AI **Guided; judgement gates retained**.

Journey: Raise — *partner initiates against a proven pattern, no conversation needed* (Partner) · Establish requirements — *self-served with guidance; the pattern carries most of the answers* (Partner) · Build — *partner provisions within pre-approved policy bounds* (**Partner**) · Gates — *partner clears deterministic gates; judgement gates stay with ECM* (Shared) · Go live — *partner-led, with ECM on escalation only* (**Partner**).

What changes — "Self-service, plus the discipline to use the tiers properly": partners instantiate a proven pattern and initiate without a conversation · provisioning within pre-approved policy bounds, anything outside them still comes to us · self-serve clearance of gates with deterministic criteria, every judgement gate and all eight invariants staying with ECM · guided remediation from published diagnostics · Dedicated pods reserved for the seven scenarios that genuinely need them and the shared pool sized on measured load · the accumulated backlog drained through self-service rather than competing for pod capacity.

AI card — **"Guided self-service, with judgement never handed over"**: partner-facing pattern recommendation, requirement explanation, diagnostics and next-action prompts. The precondition that makes this responsible rather than reckless — self-service only sits on gates that are deterministic, automated and trustworthy, which is exactly what Phases 2 and 3 produce. Judgement gates are never handed over, and pattern deviation always forces a conversation rather than a dismissible warning.

Value — "Partners stop waiting on us": Lean becomes genuinely self-service at 16 scenarios, Dedicated settles at 7 · the backlog drains through a separate route · released capacity absorbs demand growth. Delta: *better than Phase 3 — turnaround improves for the partner, not only cost for us.*

Remains permanently: seven scenarios need a dedicated pod and always will · tier utilisation discipline is an organisational commitment, not a build, and is the easiest part to let slip · self-service widens the blast radius of a bad pattern, so pattern curation becomes a standing ECM responsibility.

---

## SLIDE 7 — The compounding view and the ask

Five labelled horizontal stacked bars, all normalised to 38, in the tier colours with in-bar counts, plus a legend:

| | Lean | Lean+ | Dedicated | Factory |
|---|---|---|---|---|
| Today | 0 | 0 | 38 | 0 |
| After Phase 1 | 5 | 17 | 14 | 2 |
| After Phase 2 | 8 | 14 | 14 | 2 |
| After Phase 3 | 12 | 13 | 11 | 2 |
| After Phase 4 | 16 | 13 | 7 | 2 |

To the right, a panel with an **illustrative partner-turnaround index** as five descending bars (today = 100 → 82 → 64 → 46 → 32) and an italic caveat line reading "a shape, not a forecast".

Then a row of four stat tiles — **~2 wks** preparation · **0** new headcount · **0** lines of code · **1 qtr** to a decision — under a label saying this is the only phase being approved today.

Finally a navy band with the three numbered asks (run Phase 1 for a quarter; protect the shared pool from reclaim with a named escalation route; agree the evidence criteria now and take the Phase 2 decision against them at week twelve) beside a green-outlined card "What would justify Phase 2" listing the criteria as one run-on line separated by middots: distribution holds, half or more route to Lean or Lean+ · lighter tiers hold, escalation under 25% · clarification cycles measurably down · partners accept assigned tiering · the effort baseline exists · the bottleneck is quantified · no compliance regression.

---

## Design system

- 13.3 × 7.5 inches (`LAYOUT_WIDE`). Margins 0.45" left and right.
- **Tier palette** — Lean `0B6E6E`, Lean+ `9A6410`, Dedicated `15304F`, Factory `5B4A72`; tints `E6F2F1` / `FAF1DF` / `E8EDF4` / `F1EEF6`.
- **Phase palette — a navy depth ramp, chosen so it never competes with the tier colours:** `5E7D96`, `3E6686`, `264E72`, `15304F`; tints `EEF2F6`, `EAF0F5`, `E7ECF3`, `E9EEF4`.
- **Journey "who drives" palette** — ECM `15304F`, Shared `3E6686`, Partner `2E6B4F`, on tints `E9EEF4`, `EAF0F5`, `ECF3EE`.
- Supporting: rust `A44A2A` + `FBF0EB`, light rust `C86B45`, green `2E6B4F` + `ECF3EE`, ink `1B2432`, muted `55606E`, slate `7C8798`, line `D4DAE2`, panel `F4F7FA`.
- Fonts — Cambria for titles and big numbers, Calibri for everything else. Nothing else.
- Every tier, every phase and every "who drives" value keeps its colour on every slide, without exception.
- Consistent slide header: a small numbered navy square, a 24pt Cambria title, a 10.5pt muted subtitle, a right-aligned section tag, and a hairline rule beneath. Keep titles under ~66 characters so they never wrap into the subtitle.
- Title slide: full navy background, a teal vertical bar at the far left edge, kicker in letter-spaced caps, large Cambria title, subtitle, a short teal rule, four metadata columns, a footer rule reading "Draft for review".
- Rounded rectangles (radius ~0.05), soft shadows, hairline borders. No gradients.

## Build instructions

Use `pptxgenjs` in Node. Set `pres.layout` before adding slides. Hex colours with **no** `#` and no alpha. Build a fresh options object for every `addShape`/`addText` — never share one. Shadow offsets must be ≥ 0. Use `charSpacing`, not `letterSpacing`. Put `isTextBox: true` on every `addText` and `margin: 0` wherever text must align to a shape edge. `rectRadius` only works on `ROUNDED_RECTANGLE`.

Two renderer quirks that will bite:
- Cambria has no reliable arrow glyph — use the word "to" in a Calibri run rather than "→" inside a Cambria text block.
- A shape drawn with `line: { width: 0 }` still renders a dark hairline in some renderers. For any filled pill or strip that should have no visible border, pass `line: { color: <same as fill>, width: 0 }`.

Write a shared helper library first — slide header, stat tile, card, stacked bar, legend, chevron chain, table with tier-cell colouring, note band, callout band, section label, **phase identity band**, **journey strip with its legend**, **value tile with a delta footer**, **descending index bars**, **category rows with an effort pill** — and compose all seven slides from it. Make heading heights adaptive on *measured width*, not on string length alone, or one-line headings will leave large dead gaps above their body text.

## Speaker notes

`slide.addNotes()` on every slide, **700–1,000 words each**, structured as: the purpose of the slide; a walk-through of each element with the argument behind it; the numbers to be careful about; and a closing **"likely questions"** section with four or five questions and their answers. Required content:

- **Slide 1:** the subsidy argument is the key insight — say that a dedicated resource removes the partner's incentive to arrive prepared, and that exhortation has already failed because the cost of non-compliance falls on someone else. Read the list of partner-owned items aloud. Concede immediately that the effort split is an estimate.
- **Slide 2:** walk the tier table by column, not by row. Emphasise the two rules that make Lean safe — deviation from the pattern forces escalation, and a first-time partner can never be Lean. Land the invariants line in exactly those words.
- **Phase slides:** on each, compare the journey strip with the previous phase's and name which stages changed colour. On Phase 2, deliver "Phase 2 makes ECM efficient; it does not make partner onboarding fast" verbatim, and explain why Dedicated stays flat. On Phase 3, open with the distinction between effort and waiting, and walk one external hand-off (Imaging Governance) end to end. On Phase 4, walk the "what ECM retains" column rather than the partner column, and flag the new risk that self-service widens the blast radius of a bad pattern.
- **Slide 7:** narrow the ask explicitly — no build funding, no headcount, no commitment to Phases 2–4. Flag that protecting the shared pool is the ask most likely to be waved through and most likely to kill Phase 1.
- **Throughout:** frame released capacity as absorbing demand growth, never as headcount reduction — the squads will resist every phase if they hear otherwise.

## QA before handing it over

Convert to PDF, render all eight slides to images and inspect each one. Check first for text overflowing or cut off at a shape boundary — especially the last line inside bordered cards and value tiles, which is by far the most common failure, and watch for a card silently dropping a line that did not fit. Then check for cards or tables colliding with the element below, section labels wrapping onto content, the journey legend colliding with the label beside it, content off the slide edge, badges taller than their table rows, and dead gaps over about 0.8 inch. The four phase slides share one function but carry different text, so inspect all four — the longest text clips first. Fix everything found and re-render to confirm.

## Tone

Executive register, no hedging, no bullet-point filler. The discipline that makes this deck credible is honesty about each phase's ceiling: Phase 1 reallocates depth without removing work; Phase 2 makes ECM efficient without making onboarding fast; seven scenarios will always need a dedicated pod. Every phase's value is real and bankable on its own, which is exactly why none of them needs to be oversold.
