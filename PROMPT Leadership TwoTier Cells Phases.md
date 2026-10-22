# PROMPT — Leadership Briefing · Two Tiers, Partner Enablement Cells, Four Phases

Copy everything below the line into a fresh session.

---

Build me a PowerPoint deck (.pptx) for a senior leadership audience. Title slide plus **7 content slides**, in this exact order: (1) the problem, (2) the two-tier model and the cell structure, (3) Phase 1, (4) Phase 2, (5) Phase 3, (6) Phase 4, (7) the compounding view and the ask.

**Keep on-slide text minimal and carry the content in infographics** — tables, stacked bars, colour-coded strips, tiles. The full argument lives in the **speaker notes**, which must be substantial enough that the presenter can answer any question the slide provokes. Treat the notes as a primary deliverable, not an afterthought.

## Context you are working from

I lead work on an enterprise ECM platform team. ECM provides repository services to partner applications for storage, archival and records management, with metadata compliance and document classification applied on arrival. Three scrum teams, thirty-plus engineers. Every partner intake is currently delivered through a dedicated capacity model from inception to release.

**Domain vocabulary to use correctly:** ICMP; iDocs (document classification); the DKE — Document Knowledge Engine, maintained by Imaging Governance, which trains the model iDocs uses for untrusted content; Imaging Governance determines trusted vs untrusted on the flow and allocates category/type/subtype for trusted content; Records Management owns retention, INV160 and WORM; SPLI is load testing; KEES is Kafka Enablement Engagement Services; DCT performs virus scanning; Apigee is the API gateway.

**The two tiers are named `Partner Express` and `Commissioned Cell`.** Put both names in constants at the top of the generator so they can be renamed in one edit. Partner Express always carries the descriptor *"Partner-owned delivery"*; Commissioned Cell always carries *"Requires executive sanction"*. There are only two tiers — no third or fourth tier, no shared pool, and no scrum squads in the target model.

---

## SLIDE 1 — The problem

### The intake portfolio — ten categories, 38 distinct scenario types

Render as **two compact tables side by side**, five rows each, columns *Intake category / Types / Effort / ECM days*. The Effort cell is a coloured pill — High in rust on a rust tint, Medium in amber on an amber tint, Low in green on a green tint.

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

Totals: 38 types — **10 Low, 14 Medium, 14 High**. Two to five days at one end, forty to ninety at the other, and all of them handled the same way.

### Where an enabler squad member's time goes

A **full-width 100% stacked bar**, each segment carrying its percentage in large white type with its label beneath:

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

1. **Depth is uniform, need is not** — 10 of the 38 types need under ten ECM days. Every one is given a full dedicated team anyway.
2. **The hard intakes are starved** — the 14 genuinely complex types compete for the same attention as 24 that are not.
3. **Ownership transfers quietly** — with someone always assigned to chase, the partner never owns the inputs or feels the cost of withholding them.
4. **Growth has only one answer** — capacity = demand × fixed depth, so every uplift in partner demand becomes a headcount request.

Close with a note: the effort split is the squads' own estimate, not a measurement; producing that measurement is an explicit Phase 1 deliverable.

---

## SLIDE 2 — The two-tier model and the cell structure

This is the densest slide. Four blocks stacked.

### Four advantages — a row of four green-outlined cards

1. **Depth matches assessed need** — engineering depth becomes a variable set by a published rubric, instead of a constant applied to all 38.
2. **Ownership sits where the work sits** — Express delivery is owned by the partner; ECM sets the checkpoints and guardrails but does not run it.
3. **Capacity stops scaling linearly** — Express costs us almost nothing per intake, so growth in partner demand stops meaning growth in headcount.
4. **Commissioning becomes a decision** — an allocated cell needs named executive sanction; it stops being the default and becomes the exception.

### The two tiers — a hand-drawn two-row table, four columns

Column headers must read exactly **"Tier" · "ECM allocates" · "Checkpoints — defined by ECM" · "Guardrails — defined by ECM"**. The "defined by ECM" wording is not optional: it is what makes clear that Partner Express is partner-owned in execution but not partner-governed. Suggested widths 2.10 / 2.20 / 4.05 / 4.05 inches, row height ~1.00.

The tier cell carries the tier name in its colour, the descriptor in bold italic beneath, and the steady-state count in muted grey, on a tinted background with a solid colour bar at the left edge.

| Tier | ECM allocates | Checkpoints — defined by ECM | Guardrails — defined by ECM |
|---|---|---|---|
| **Partner Express**<br>*Partner-owned delivery*<br>29 of 38 at steady state | No allocated cell. Scheduled assurance drawn from the cell rota only. | Entry check at triage — pattern confirmed and completeness band met · one scheduled design checkpoint from the cell rota, dropped only once the pattern is fully proven and the partner has prior history · exit check before go-live. | All eight invariants · any deviation from the published pattern forces a re-tier to Commissioned · the partner must already have completed one prior intake · ECM sets the policy bounds inside which the partner provisions. |
| **Commissioned Cell**<br>*Requires executive sanction*<br>9 of 38 at steady state | An allocated Partner Enablement cell, inception to release. | Architecture review · design authority sign-off · integration readiness · pre-UAT · pre-go-live · post-go-live review. | All eight invariants plus full design authority review · a joint delivery plan with the partner · formal change control on any scope movement · the commissioning decision recorded with its justification and reviewed quarterly. |

### The delivery unit — a row of four navy-outlined cards

1. **5 cells, ~6 people each** — a lead plus four or five engineers, formed from the three squads we already have. No new headcount.
2. **1–2 commissioned intakes per cell** — concurrent. The remainder of each cell's capacity goes to the assurance rota and pattern work.
3. **A rota, not a shared pool** — every cell contributes a standing assurance slot for Partner Express, so there is no separate pool to be reclaimed.
4. **Commissioning needs sanction** — a named executive approves each commissioned cell; the decision is recorded with its justification and reviewed quarterly.

### Closing navy band

**"A lighter tier is a lighter allocation of ECM judgement — never a lighter standard."** Both tiers meet the same eight compliance invariants: classification determination · retention approval · security and access review · volume certification · promotion ladder · support acceptance · audit trail · new document type re-review. Tier is assigned by ECM against a seven-determinant rubric with hard overrides — never chosen by the partner, and appealable on a determinant but not on preference.

---

## SLIDES 3–6 — One slide per phase, all on an identical template

Write a single `phaseSlide()` function and call it four times. Each phase slide has, top to bottom:

**A. A phase identity band** in the phase colour, full width, ~0.72" high: "PHASE n" kicker, the phase name in large serif white, and three right-aligned fact columns.

**B. The partner journey strip** — the recurring visual that carries the whole narrative. Five stages across the full width: *Raise the intake · Establish requirements · Build & configure · Clear the gates · Go live & support*. Each stage is a box with a coloured top rule, a bold stage name, one line of description, and a small footer label naming **who drives it**, colour-coded: **ECM drives** navy `15304F`, **Shared** steel `3E6686`, **Partner drives** green `2E6B4F`, each on a matching tint. A small three-item legend at the top right. Chevrons between the boxes. Height ~1.04" so a three-line description cannot collide with the driver label.

The strip must visibly "green up" from Phase 1 to Phase 4 — that progression *is* the self-service story and is the most important recurring element in the deck.

**C. Two cards side by side** — "What changes in this phase" (left) and "Automation, AI and agentic capability" (right). On Phase 1 the right-hand card is deliberately panel grey, not a phase colour.

**D. A value tile** (left, ~7.3" wide, phase-coloured top rule, three body lines, and a **green footer strip carrying the delta against the preceding phase**) beside a **rust "what this phase cannot fix" card** (right, ~4.9"). Size the value tile at about 1.64" high so three body lines fit without the last clipping.

### Phase 1 — Evaluate

Facts: Dependency **ECM leadership only** · Builds **Nothing at all** · Duration **One quarter**.

Journey: Raise — *partner raises it; ECM triage classifies, scores and assigns the tier* (ECM). Establish requirements — *90-minute Discovery Triage from a written guide; every gap dated and owned* (Shared). Build — *partner builds on the pattern for Express; a commissioned cell builds the rest* (**Shared**). Gates — *checklist walked by the lead and the rota; every waiver recorded* (ECM). Go live — *ECM-led cutover, handover and support acceptance* (ECM).

What changes — "Six workstreams of operating discipline, one of design": tier model published and socialised · triage template rebuilt around the 54-point question set, every item carrying its reason · triage leads assign the tier and select the guardrails, with the basis recorded · partner tier charter issued with every assignment (what you own, what you receive, why this tier) · **three squads re-formed into five Partner Enablement Cells, with the assurance rota established** · commissioning sanction route agreed, plus governance, approvals and a waiver log reviewed fortnightly.

AI card — **"None — and deliberately so"**: nothing built, nothing procured, no agent deployed; every mechanism has a human equivalent we already have the knowledge to run. The only forward-looking work is design — an architecture evaluation that specifies and costs Phase 2 (target architecture, the agentic authority model, the integration inventory, a build estimate). Roughly two weeks of architect time across the quarter, which is why Phase 1 ends with a costed proposal rather than a request for more time.

Value — "Ownership moves, and depth stops being uniform": 22 of 38 scenario types become partner-owned Partner Express, commissioned cells fall 38 → 16 · clarification cycles fall on the deeper triage alone · the first measured effort and elapsed-time baseline. Delta: *better than today — the 14 genuinely complex intakes stop competing with 24 that are not, at a cost of about two weeks of writing.*

Cannot fix: clerical load untouched · only 5 of the 22 Express intakes are truly self-served, the rest still need a scheduled checkpoint · external queue time unchanged and per-intake effort roughly constant · guardrails enforced by people under schedule pressure can still be waived.

### Phase 2 — Automate inside ECM

Facts: Dependency **ECM engineering only** · Builds **What ECM owns outright** · AI **Agentic, inside the perimeter**.

Journey: Raise — *partner raises it unaided through a guided intake* (**Partner**). Establish requirements — *AI copilot asks the catalogue questions and explains why each is needed* (Shared). Build — *partner self-serves on the pattern; ECM artefacts generated automatically* (Shared). Gates — *ECM gates enforced by the gate engine; external gates still manual* (ECM). Go live — *ECM-led, but with live state visible to the partner* (ECM).

What changes — "Everything inside the ECM perimeter": guided intake with the why-register, completeness enforced at source · gap register that ages open items, chases owners and escalates on due date · tiering assistant scores the determinants and proposes a tier, the triage lead still decides · pattern matcher and automatic scope derivation · ECM artefacts generated (repository definitions, metadata mappings, retention bindings, configuration) · partner cockpit showing read-only state, open gaps, next action and due dates.

AI card — **"Agentic, with authority that stops at the perimeter"**: an Onboard360AI orchestrator with sub-agents bounded strictly by the ECM perimeter — intake copilot, completeness agent, tiering assistant, pattern matcher, scope composer, artefact generator, gate checker. The authority boundary is **architectural, not a setting**: agents propose and prepare, a named person decides, anything irreversible or compliance-bearing takes a second explicit authorisation. No agent holds a credential that can promote, approve, clear — or commission a cell.

Value — "The data deficit attacked at source": completeness enforced at intake, aimed squarely at the 31% spent chasing partner-owned inputs · self-served Express rises from 5 to 8 of 22 · ECM artefacts generated rather than assembled. Delta: *better than Phase 1 — effort per intake finally falls, instead of only being better aimed.*

Cannot fix: every external hand-off is still a manual submission into another team's queue · those queues become the dominant share of elapsed time · **commissioned cells stay at 16** — automating our work does not make a complex intake less complex · Phase 2 makes ECM efficient, it does not yet make onboarding fast.

### Phase 3 — Orchestrate outward

Facts: Dependency **In-house partner teams** · Builds **Across the boundary** · AI **Agents assemble, validate, chase**.

Journey: Raise (Partner) · Establish requirements — *copilot-guided, long-lead items raised on day one* (**Partner**) · Build — *partner self-serves; external provisioning requested in parallel* (Shared) · Gates — *external requests assembled, validated and tracked end to end* (**Shared**) · Go live — *ECM-led, with every dependency visible and chased* (ECM).

What changes — "Every hand-off outside the ECM perimeter": contract-first integration with Imaging Governance, Records Management, Security, Apigee, KEES, DCT and SPLI · requests assembled from the intake record and validated against each team's acceptance criteria **before** submission · long-lead items (DKE changes, new retention bindings, SPLI certification) raised at triage rather than at the point of need · status tracked, SLAs measured, escalation automatic on breach · what we ask of those teams is modest — written acceptance criteria, a structured channel, a readable status signal.

AI card — **"Agents that assemble and chase, but never decide"**: agents build each external request from the intake record, check it against published acceptance criteria, submit, track and chase on SLA breach. They influence no determination — Imaging Governance still determines trust posture and allocates category, type and subtype; Records Management still approves retention and certifies WORM. Requests arrive complete and explained, converting a three-cycle hand-off into a one-cycle hand-off.

Value — "Queue time stops dominating": rework cycles with external teams removed · the 15% spent chasing external teams largely disappears · commissioned cells fall 16 → 13. Delta: *better than Phase 2 — cuts waiting, a different quantity from effort that no ECM automation can reach.*

Cannot fix: go-live and support still ECM-led · thirteen scenarios remain commissioned through genuine novelty · the backlog still competes with new demand for the same cell capacity · dependency on external SLAs is now measured rather than hidden, an improvement but not control.

### Phase 4 — Partner self-service

Facts: Dependency **The partners themselves** · Builds **Partner-facing** · AI **Guided; judgement gates retained**.

Journey: Raise (Partner) · Establish requirements (Partner) · Build — *partner provisions within the policy bounds ECM has set* (**Partner**) · Gates — *partner clears deterministic gates; judgement gates stay with ECM* (Shared) · Go live — *partner-led, with a cell on escalation only* (**Partner**).

What changes — "Self-service, plus the discipline to hold the line on commissioning": partners instantiate a proven pattern and initiate without a conversation · provisioning within pre-approved policy bounds, anything outside them re-tiers to Commissioned · self-serve clearance of deterministic gates, every judgement gate and all eight invariants staying with ECM · guided remediation from published diagnostics before escalating to a cell · commissioned cells reserved for the nine scenarios that genuinely need them, sanction reviewed quarterly · the accumulated backlog drained through self-service rather than competing for cell capacity.

AI card — **"Guided self-service, with judgement never handed over"**: partner-facing pattern recommendation, requirement explanation, diagnostics and next-action prompts. The precondition that makes this responsible rather than reckless — self-service only sits on gates that are deterministic, automated and trustworthy, which is exactly what Phases 2 and 3 produce. Judgement gates are never handed over, and pattern deviation always forces a conversation with a cell rather than a dismissible warning.

Value — "Partners stop waiting on us": Partner Express reaches 29 of 38, with 16 fully self-served · commissioned cells settle at 9, sanctioned individually · the backlog drains through a separate route. Delta: *better than Phase 3 — turnaround improves for the partner, not only cost for us.*

Remains permanently: nine scenarios need a commissioned cell and always will · holding commissioning to nine is an organisational commitment, not a build, and is the easiest part to let slip · self-service widens the blast radius of a bad pattern, so pattern curation becomes a standing cell responsibility.

---

## SLIDE 7 — The compounding view and the ask

Five labelled horizontal stacked bars, all normalised to 38. **The Express band is split into two shades** — self-served and assisted — because that split is where Phase 2's value appears; with only two flat tiers Phase 2 would look like it does nothing.

| | Express — self-served | Express — assisted | Commissioned Cell |
|---|---|---|---|
| Today | 0 | 0 | 38 |
| After Phase 1 | 5 | 17 | 16 |
| After Phase 2 | 8 | 14 | 16 |
| After Phase 3 | 12 | 13 | 13 |
| After Phase 4 | 16 | 13 | 9 |

Colours: Express self-served deep teal `0B6E6E`, Express assisted light teal `6FAFAF`, Commissioned Cell navy `15304F`. Legend beneath.

To the right, a panel with an **illustrative partner-turnaround index** as five descending bars (today = 100 → 82 → 64 → 46 → 32) and an italic caveat line reading "a shape, not a forecast".

Then four stat tiles — **~2 wks** preparation · **0** new headcount (five cells formed from the three squads we already have) · **0** lines of code · **1 qtr** to a decision — under a label saying this is the only phase being approved today.

Finally a navy band with the three numbered asks, beside a green-outlined card "What would justify Phase 2".

**The three asks:**
1. Run Phase 1 for one quarter — the operating discipline, not a build.
2. Approve re-forming the three squads into five Partner Enablement Cells, and protect the assurance rota from being consumed by commissioned work.
3. Make commissioning an executive decision from day one, and agree the evidence criteria for the week-twelve review.

**What would justify Phase 2:** distribution holds — 55%+ route to Partner Express · Express holds, with re-tier to Commissioned under 25% · clarification cycles measurably down · partners accept assigned tiering · the effort baseline exists · the bottleneck is quantified · no compliance regression.

---

## Design system

- 13.3 × 7.5 inches (`LAYOUT_WIDE`). Margins 0.45" left and right.
- **Tier palette** — Express self-served `0B6E6E`, Express assisted `6FAFAF`, Commissioned Cell `15304F`; tints `E6F2F1`, `EDF7F7`, `E8EDF4`.
- **Phase palette — a navy depth ramp, chosen so it never competes with the tier colours:** `5E7D96`, `3E6686`, `264E72`, `15304F`; tints `EEF2F6`, `EAF0F5`, `E7ECF3`, `E9EEF4`.
- **Journey "who drives" palette** — ECM `15304F`, Shared `3E6686`, Partner `2E6B4F`, on tints `E9EEF4`, `EAF0F5`, `ECF3EE`.
- Supporting: rust `A44A2A` + `FBF0EB`, light rust `C86B45`, green `2E6B4F` + `ECF3EE`, ink `1B2432`, muted `55606E`, slate `7C8798`, line `D4DAE2`, panel `F4F7FA`.
- Fonts — Cambria for titles and big numbers, Calibri for everything else. Nothing else.
- Every tier, every phase and every "who drives" value keeps its colour on every slide, without exception.
- Consistent slide header: a small numbered navy square, a 24pt Cambria title, a 10.5pt muted subtitle, a right-aligned section tag, a hairline rule beneath. Keep titles under ~66 characters so they never wrap into the subtitle.
- Title slide: full navy background, a teal vertical bar at the far left edge, kicker in letter-spaced caps, large Cambria title, subtitle, a short teal rule, four metadata columns, a footer rule reading "Draft for review".
- Rounded rectangles (radius ~0.05), soft shadows, hairline borders. No gradients.

## Build instructions

Use `pptxgenjs` in Node. Set `pres.layout` before adding slides. Hex colours with **no** `#` and no alpha. Build a fresh options object for every `addShape`/`addText` — never share one. Shadow offsets must be ≥ 0. Use `charSpacing`, not `letterSpacing`. Put `isTextBox: true` on every `addText` and `margin: 0` wherever text must align to a shape edge. `rectRadius` only works on `ROUNDED_RECTANGLE`.

Two renderer quirks that will bite:
- Cambria has no reliable arrow glyph — use the word "to" in a Calibri run rather than "→" inside a Cambria text block.
- A shape drawn with `line: { width: 0 }` still renders a dark hairline in some renderers. For any filled pill, bar segment or strip that should have no visible border, pass `line: { color: <same as fill>, width: 0 }`.

Write a shared helper library first — slide header, stat tile, card, stacked bar, legend, chevron chain, note band, callout band, section label, **phase identity band**, **journey strip with its legend**, **value tile with a delta footer**, **descending index bars**, **category rows with an effort pill** — and compose all seven slides from it. Make heading heights adaptive on *measured width*, not on string length alone, or one-line headings will leave large dead gaps above their body text.

## Speaker notes

`slide.addNotes()` on every slide, **700–1,000 words each**, structured as: the purpose of the slide; a walk-through of each element with the argument behind it; the numbers to be careful about; and a closing **"likely questions"** section with four or five questions and their answers. Required content:

- **Slide 1:** the subsidy argument is the key insight — a dedicated resource removes the partner's incentive to arrive prepared, and exhortation has already failed because the cost of non-compliance falls on someone else. Read the list of partner-owned items aloud. Concede immediately that the effort split is an estimate.
- **Slide 2:** point at the two column headings *before* reading any content — Partner Express is partner-owned in execution but not partner-governed. Cover the three rules that make Express safe (pattern deviation forces a re-tier; no first-time partner can be Express; ECM sets the policy bounds). Explain that the commissioning sanction is what stops the model collapsing back to today, and that the assurance **rota** is deliberately not a pool, because a pool is a nameable thing that gets reclaimed under pressure whereas a rota slot owed by each cell is visible to the other four when withdrawn.
- **Phase slides:** on each, compare the journey strip with the previous phase's and name which stages changed colour. On Phase 2 deliver "Phase 2 makes ECM efficient; it does not make partner onboarding fast" verbatim, and explain why Commissioned stays flat at 16. On Phase 3 open with the distinction between effort and waiting, and walk one external hand-off (Imaging Governance) end to end. On Phase 4 walk the "what ECM retains" column rather than the partner column, and flag that self-service widens the blast radius of a bad pattern.
- **Slide 7:** explain that the Express band is split into self-served and assisted because that is where Phase 2 shows up — with flat tiers Phase 2 would appear to do nothing. Narrow the ask explicitly: no build funding, no headcount, no commitment to Phases 2–4.
- **Throughout:** frame released capacity as absorbing demand growth, never as headcount reduction — the cells will resist every phase if they hear otherwise.

## QA before handing it over

Convert to PDF, render all eight slides to images and inspect each one. Check first for text overflowing or cut off at a shape boundary — especially the last line inside bordered cards, value tiles and table cells, and watch for a card silently dropping a line that did not fit. Then check for cards or tables colliding with the element below, section labels wrapping onto content, the journey legend colliding with the label beside it, content off the slide edge, and dead gaps over about 0.8 inch. Slide 2 is the densest — scrutinise it hardest. The four phase slides share one function but carry different text, so inspect all four; the longest text clips first. Fix everything found and re-render to confirm.

## Tone

Executive register, no hedging, no bullet-point filler. The discipline that makes this deck credible is honesty about each phase's ceiling: Phase 1 reallocates depth without removing work; Phase 2 makes ECM efficient without making onboarding fast; nine scenarios will always need a commissioned cell. Every phase's value is real and bankable on its own, which is exactly why none of them needs to be oversold.
