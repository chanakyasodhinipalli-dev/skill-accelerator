# PROMPT 1 — Leadership Briefing Deck

Copy everything below the line into a fresh session.

---

Build me a PowerPoint deck (.pptx) for a senior leadership audience. It must have a title slide plus **exactly four content slides — no more**. Dense, infographic-led, data-carrying. No bullet-point filler.

## Context you are working from

I lead work on an enterprise ECM platform team. ECM provides repository services to partner applications so they can bring content in through various channels for storage, archival and records management, with metadata compliance and document classification applied on arrival. Around that we provide partner onboarding, API enablement, and migration pipeline establishment.

Two streams of demand hit the same teams: planned partner onboarding, and migration of content off non-compliant and legacy repositories. Both are delivered identically — a development team in a dedicated capacity arrangement with the partner, from inception through to release. Three scrum teams, thirty-plus engineers.

**The structural problem.** Capacity required = number of concurrent intakes × a fixed engineering depth applied to every intake. Partner demand sets the first term and we do not control it. The second is fixed by our delivery model. With both outside our control, the only lever is headcount. This is an *allocation* problem, not a throughput problem — we spend the same engineering depth on an intake that repeats a pattern already built ten times as on one requiring genuinely new design. Adding engineers restores throughput temporarily without changing the equation.

**Two independent causes:**

1. **The data deficit.** The requirement for a piece of information is discovered incrementally, by a person, after the intake has landed. Each discovery starts a cycle: engineer reaches a step and finds data missing → works out who on the partner side knows it → explains why it is needed (the expensive part) → waits days → clarifies an imprecise answer → resumes until the next missing item. The enabling squads' working estimate is that this consumes **30–40% of total elapsed time**. It is also the most draining work they do — repetitive, explanatory rather than technical, repeated from scratch for every partner. Critically, it is **tier-independent**: it costs the same in any operating model, so no re-tiering fixes it, and fixing it needs no re-organisation, no headcount movement and no systems integration.

2. **Uniform allocation.** We assessed all 38 onboarding scenarios we support against what each actually requires. 8 need no design at all, 14 need a judgement or two, 14 genuinely need a dedicated pod, 2 are not onboardings at all but migration campaigns. **All 38 currently receive the same dedicated team.**

## The proposal

**Move 1 — Complete the intake** (immediate, benefits all models). Capture every required data point at intake, with the reason explained at the point of asking, and register every remaining unknown as a dated, owned gap tied to the gate it blocks. Design goal, stated precisely: *capture everything knowable now, and convert everything else from an unknown-unknown into a scheduled-known.* A blank field and a field marked "not yet known — owner: partner solution architect — due 14 November — blocks: repository profile design" are entirely different artefacts. Key figures: **54 data points** catalogued, each with why it is required and what it blocks; **zero** re-organisation or headcount needed; **~2 weeks** of two experienced engineers plus a governance analyst to author the catalogue of reasons. The asset is the catalogue, not the chatbot.

**Move 2 — Tier the engagement, not the partner** (structural, compounds). Each *intake* — not each partner — is assigned a model based on what that specific work requires. The same partner may run three intakes in three tiers at once. Tier is assigned by ECM against a published **7-determinant rubric** with **4 hard overrides**, never chosen by the partner. If partners self-select, every partner selects Dedicated — not out of bad faith, but because from any one partner's view more attention is always better.

**The three models:**

| | Lean | Lean+ | Dedicated |
|---|---|---|---|
| Allocated capacity | None | None — shared pool | Dedicated pod |
| ECM involvement | Platform only; humans on gate failure | Two mandatory design checkpoints plus a named guide | End-to-end delivery |
| Start latency | Days | Weeks | Planning increment |
| Cost of next identical intake | Near zero | Checkpoint hours | Full allocation |
| **Scaling** | **Flat** | **Sub-linear** | **Linear** |

**The reframing that must land:** Dedicated is not the premium service, it is the *slowest* one — it queues for scarce capacity. Lean partners go live sooner precisely because nothing has to become free first. Without this, every partner negotiates for Dedicated and the model fails on day one.

**Distribution:** Today all 38 are Dedicated. At entry: Lean 8, Lean+ 14, Dedicated 14, Factory 2. Steady state after ~2 years of pattern investment: Lean 16, Lean+ 13, Dedicated 7, Factory 2. Nothing migrates on its own — every leftward move is a pattern a dedicated pod built and platform engineering hardened. That makes pattern harvesting a **closure condition** on every Dedicated intake, not an aspiration.

**The ask:** 4 sprints, 5–6 people, protected from delivery work. Sprint 1 — Complete the intake (data catalogue and why-register, intake copilot, gap register, handoff contract). Sprint 2 — Make intake drive delivery (scope derivation, tiering assistant, pattern matcher, precedent, patterns to M1). Sprint 3 — Guardrails and the Clinic (gate engine, routing rules codified, artefact generation, clinic rhythm). Sprint 4 — Prove Lean end to end (self-service provisioning on one pattern, certification, cockpit, dashboard). No structural change, no headcount commitment, no partner forced to do anything differently.

## The four slides

**Slide 1 — "Why capacity keeps running out"** · subtitle: *Two causes, both structural — neither solved by adding engineers*
- Full-width navy band at the top carrying the capacity equation, with "a fixed engineering depth, applied to every intake" in a warm accent colour so the broken term is visually obvious. One italic line beneath explaining that both terms are outside ECM's control.
- Two side-by-side cards. **Left — Cause 1:** a huge "30–40%" figure beside a short explanatory line, then the six-step cycle as numbered circles in two columns. **Right — Cause 2:** two stacked horizontal segmented bars — "WHAT THEY ACTUALLY NEED" (8 / 14 / 14 / 2, colour-coded by tier) and "WHAT THEY GET TODAY" (one solid bar reading "All 38 receive a dedicated team, inception to release"). Legend beneath.
- A navy-tinted band: "THE DIAGNOSIS THAT MATTERS" — not a throughput problem, an allocation problem.
- A closing note: the two causes are independent; the first can start immediately.

**Slide 2 — "Two moves"** · subtitle: *One pays immediately and needs no decision beyond building it. One changes how capacity behaves.*
- Two large cards side by side, each with a kicker ("MOVE 1 · IMMEDIATE · ALL MODELS" / "MOVE 2 · STRUCTURAL · COMPOUNDS"), a headline, a paragraph, a tinted strip carrying the one-line principle, and three stat callouts (54 / 0 / 2 wks for move 1; 7 / 38 / 4 for move 2).
- Below: the three enablement models as three cards with coloured header bars, each listing allocated capacity, ECM involvement, start latency, cost of next identical intake, and scaling — label on the left, value right-aligned in bold.
- Bottom note in an accent-outlined box: the Dedicated-is-slowest reframing.

**Slide 3 — "What changes, and what it is worth"** · subtitle: *The distribution is not static — it is a function of pattern investment, which ECM controls*
- Left: three stacked horizontal segmented bars labelled Today / At entry / Steady state, with a legend. This is the most important visual in the deck.
- Right: a card titled "Every leftward move is earned" explaining the compounding mechanism.
- Lower left: a "What leadership is actually buying" table — rows for dominant source of delay, capacity behaviour, response to a demand spike, cost of the tenth identical onboarding, senior engineer time, what an onboarding leaves behind, risk posture; columns Today vs With the tiered model.
- Lower right: gains by audience as five colour-barred entries (Leadership, Partners, Enabling squads, Governance, Enterprise).
- Closing note: read the distribution honestly — only a fifth qualifies for Lean on day one; the trajectory is the case.

**Slide 4 — "The ask: four sprints, five to six people"** · subtitle: *No structural change, no headcount commitment, and no partner forced to do anything differently*
- A four-step chevron chain across the top, one per sprint, each colour-coded with sprint number, theme and deliverables.
- A row of four proof-point boxes beneath, one per sprint.
- Two side-by-side panels: "YOU WILL SEE" (green-outlined, six items) and "YOU WILL NOT SEE" (grey-outlined, six items including *a reduction in headcount*, *all partners migrated*, *a validated full-year capacity saving*).
- A navy band at the foot carrying three numbered asks.

## Design system

- 13.3 × 7.5 inches (`LAYOUT_WIDE`). Margins 0.45" left and right.
- Palette — navy `15304F` (primary, Dedicated), teal `0B6E6E` (Lean), amber `9A6410` (Lean+), plum `5B4A72` (Factory), rust `A44A2A` (accent / alert), ink `1B2432`, muted `55606E`, line `D4DAE2`, panel `F4F7FA`. Tints: `E6F2F1` / `FAF1DF` / `E8EDF4` / `F1EEF6` / `FBF0EB` / `E9EEF4`.
- Fonts — Cambria for titles and big numbers, Calibri for everything else. Nothing else.
- Every tier keeps the same colour on every slide, without exception.
- Consistent slide header: a small numbered navy square, a 24pt Cambria title, a 10.5pt muted subtitle, a right-aligned section tag, and a hairline rule beneath.
- Title slide: full navy background, a teal vertical bar at the far left edge, kicker in letter-spaced caps, large Cambria title, subtitle, a short teal rule, then four metadata columns, and a footer rule with "Draft for review".
- Rounded rectangles (radius ~0.05), soft shadows, hairline borders. No gradients, no accent stripes under titles, no decorative colour bars.

## Build instructions

Use `pptxgenjs` in Node. Set `pres.layout` before adding slides. Hex colours with **no** `#` and no alpha. Build a fresh options object for every `addShape`/`addText` — never share one. Shadow offsets must be ≥ 0. Use `charSpacing`, not `letterSpacing`. Put `isTextBox: true` on every `addText` and `margin: 0` wherever text must align to a shape edge. `rectRadius` only works on `ROUNDED_RECTANGLE`.

Write a small shared helper library first (slide header, stat tile, card, segmented bar, legend, chevron chain, table, note band, callout band) and compose the slides from it — it is what keeps four dense slides visually consistent.

**Speaker notes are mandatory on every slide**, via `slide.addNotes()`. Write them as what a presenter would actually say — the argument, the number to point at, the objection to pre-empt, the line to deliver verbatim. Several hundred words per slide. They are half the deliverable.

**QA before you hand it over:** convert to PDF, render every slide to an image, and look at each one. Check first for text overflowing or being cut off at a shape boundary — especially the last wrapped line inside bordered callout boxes, which is the most common failure. Then check for overlapping elements, tables colliding with the band below them, content running off the slide edge, and large dead gaps. Fix what you find and re-render.

## Tone

Executive register, no hedging, no filler. Where a number is an estimate rather than a measurement, say so on the slide. Do not inflate the entry distribution — 21% qualifying for Lean on day one is the honest figure and a flatter number would not survive scrutiny. Lead with how capacity *behaves*, not with an efficiency percentage.
