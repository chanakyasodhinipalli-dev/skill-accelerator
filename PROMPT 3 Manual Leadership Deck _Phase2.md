# PROMPT 3 — Phase 1 Manual Approach · Leadership Briefing

Copy everything below the line into a fresh session.

---

Build me a PowerPoint deck (.pptx) for a senior leadership audience. Title slide plus **exactly four content slides — no more**. Dense, infographic-led, data-carrying. No bullet-point filler.

The deck argues for adopting a tiered partner-enablement model **manually first**, with no platform, no automation and no new headcount — and earning the evidence to build the automated version afterwards.

## Context you are working from

I lead work on an enterprise ECM platform team. ECM provides repository services to partner applications for storage, archival and records management, with metadata compliance and document classification applied on arrival. Three scrum teams, thirty-plus engineers, every partner intake delivered through a dedicated capacity model from inception to release.

**The structural problem.** Capacity required = number of concurrent intakes × a fixed engineering depth applied to every intake. Partner demand sets the first term and we do not control it; the second is fixed by our own delivery model. With both outside our control, the only lever is headcount. This is an allocation problem, not a throughput problem.

**Two causes.** (1) *The data deficit* — the requirement for a piece of information is discovered a step at a time, by an engineer, after the intake has landed; each discovery costs days of waiting; the squads estimate **30–40% of total elapsed time**; it is tier-independent, so no re-tiering fixes it, and it is the most draining work the squads do. (2) *Uniform allocation* — of 38 onboarding scenarios assessed against what each actually requires, 8 need no design, 14 need a judgement or two, 14 genuinely need a dedicated pod, 2 are migration campaigns — and **all 38 currently get the same dedicated team**.

**The response** is a tiered enablement model: Lean (self-service on a proven pattern, no allocated capacity, flat scaling), Lean+ (shared pool, two mandatory design checkpoints, a named guide, sub-linear scaling), Dedicated (allocated pod, inception to release, linear scaling), plus a Migration Factory for remediation run as campaigns. Tier is assigned by ECM against a published seven-determinant rubric with hard overrides, never chosen by the partner.

## The argument this deck makes

There are two ways to adopt that model, and the deck is about choosing the second.

**Build first:** commit four sprints of engineering to a platform, then run the model on it. The business case rests on design assumptions; no baseline exists; if the model is wrong the investment is stranded.

**Prove first (the recommendation):** run the model by hand for one quarter, then build what the evidence says to build. Two weeks of preparation, no build at all, no new headcount. The business case then rests on measured results, the baseline is produced as a by-product of running, and if the model is wrong nothing is stranded.

### What Phase 1 actually is — four changes, nothing built

1. **A deeper triage conversation.** Triage becomes the session where the full requirement is established, not just classified. A pre-read issued to the partner, a 90-minute Discovery Triage worked from a written question guide with the reason explained at the point of asking, a 30-minute internal Tiering Review, and a one-page Triage Outcome Record issued afterwards.
2. **Triage leads assign the tier.** The lead scores seven determinants on a sheet, applies the overrides, assigns the tier outright, selects which guardrails apply, and records the justification. Calibrated before start, fortnightly review, one appeal per intake within five days.
3. **A shared pool drawn from existing squads.** Four to six people — a permanent core of two plus rotating six-to-eight-week secondments — serving Lean and Lean+ with two mandatory checkpoints per intake, published office hours and escalation duty. No new headcount.
4. **One tracker, maintained by hand.** A spreadsheet or an existing board. Tier scores, open gaps with owners and dates, gate status, clarification cycles counted, stage dates. This is the measurement instrument and the primary output of Phase 1.

**The only thing written** is a Triage Guide: the tier model, the seven determinants and their scoring, the thresholds and overrides, the full 54-point question set with the reason for each item, the completeness bands, the guardrails by tier, the escalation triggers, and four templates. Roughly one week of two experienced engineers plus a governance analyst. Be precise with the audience: writing guidance is days of work by people who already hold the knowledge; building a platform is months of engineering. And none of it is discarded — the question set becomes the intake data catalogue, the scoring sheet and its deviations become the tiering rules and calibration data, the Outcome Record becomes the handoff contract, the pattern log becomes the pattern catalogue.

### The ceiling — state it plainly, it is what makes the proposal credible

| Distribution | Lean | Lean+ | Dedicated | Factory |
|---|---|---|---|---|
| Today | 0 | 0 | 38 | 0 |
| Phase 1 — manual | 5 | 17 | 14 | 2 |
| Phase 2 — at entry | 8 | 14 | 14 | 2 |
| Phase 2 — steady state | 16 | 13 | 7 | 2 |

**Lean+ works well by hand; Lean largely does not.** Lean+ is a human process by design — scheduled design assurance from a shared pool, all of which people with a calendar can do. Lean assumes the partner can self-serve: instantiate a pattern, provision within policy bounds, clear automated gates, see their own state. Without a platform they can do none of those. **Eleven scenarios sit in that gap, and that is the clearest single statement of what Phase 2 actually buys.**

**Phase 1 delivers:** most of the Lean+ benefit (17 scenarios move from continuous allocation to scheduled assurance); a measurable fall in clarification cycles from the deeper triage alone; long-lead items started at triage rather than mid-delivery; the effort and elapsed-time baseline measured for the first time; the real tier distribution against live demand; a calibrated rubric and trained leads.

**Phase 1 does not deliver:** removal of the clerical load (artefacts, routing and tracking stay manual); scale (manual effort per intake is roughly constant); consistency independent of people; gates that cannot be waived under pressure; a durable asset; most of the Lean tier.

### The plan and the gate

Twelve weeks: **1–2 Prepare** (write the guide, calibrate the leads, stand up the pool, build the tracker, publish the tier model to partners) · **3–6 Run in parallel** (every intake gets deep triage and a tier but is still delivered under the current model — real data, zero delivery risk) · **7–10 Operate the tiers** (assignments take effect, Lean+ with named guides and checkpoints, first Lean intakes on the simplest patterns) · **11–12 Evidence review**.

The evidence gate, agreed in advance: distribution holds (50%+ route to Lean or Lean+); lighter tiers hold (escalation below 25%); clarification cycles fall measurably; partners accept assigned tiering (appeal rate below 20%, most unsuccessful); the baseline exists; **the bottleneck is identified** (a quantified statement of where manual effort concentrates — this is the criterion that specifies the Phase 2 build); no compliance regression.

Cost: ~2 weeks preparation · 0 new headcount · 0 lines of code · 1 quarter before the Phase 2 decision.

## The four slides

**Slide 1 — "The problem, and a choice about how to respond."** Navy band carrying the capacity equation with the fixed-depth term in a warm accent colour. One italic line beneath on both terms being outside our control. Two compact cause cards with a large figure each (30–40%, and 38 of 38). Then the adoption choice as two large side-by-side cards — BUILD FIRST (muted, four drawbacks) and PROVE FIRST (accent-coloured and visually favoured, four advantages). Close with an accent note recommending prove-first because the business case numbers do not currently exist.

**Slide 2 — "What the manual approach actually is."** Four numbered change cards down the left two-thirds, each with a title, a description and a coloured one-line summary of its mechanics. Right-hand column: a card titled "The only thing that gets written" describing the Triage Guide and its one-week cost, and beneath it a card titled "And it is reused, not discarded" mapping each Phase 1 artefact to its Phase 2 successor. A navy band at the foot: "Being precise about 'no effort'". Closing note on the triage conversation carrying most of the benefit.

**Slide 3 — "What Phase 1 delivers — and the ceiling."** Four stacked segmented bars (Today / Phase 1 manual / Phase 2 at entry / Phase 2 steady) with a legend. A card explaining why Lean+ works by hand and Lean does not, ending on the eleven-scenario gap. Below, two side-by-side panels: "Phase 1 delivers" (green-outlined, six items) and "Phase 1 does not deliver" (accent-outlined, six items). Closing note: stating the ceiling is what makes the proposal credible rather than a way of deferring the investment.

**Slide 4 — "The ask: one quarter, no build, no new headcount."** A four-step chevron chain across the top, one per fortnight block. The evidence gate as a seven-row table (criterion / what good looks like / what it proves). A row of four cost tiles (~2 wks, 0, 0, 1 qtr). A navy band at the foot with three numbered asks: approve Phase 1; commit to protecting the shared pool from reclaim; agree the evidence gate now and take the Phase 2 decision against it at week 12.

## Design system

- 13.3 × 7.5 inches (`LAYOUT_WIDE`). Margins 0.45" left and right.
- Palette — navy `15304F` (primary, Dedicated), teal `0B6E6E` (Lean), amber `9A6410` (Lean+), plum `5B4A72` (Factory), rust `A44A2A` (accent / alert), green `2E6B4F` (positive), ink `1B2432`, muted `55606E`, slate `7C8798`, line `D4DAE2`, panel `F4F7FA`. Tints: `E6F2F1` / `FAF1DF` / `E8EDF4` / `F1EEF6` / `FBF0EB` / `E9EEF4`.
- Fonts — Cambria for titles and big numbers, Calibri for everything else. Nothing else.
- Every tier keeps the same colour on every slide, without exception.
- Consistent slide header: a small numbered navy square, a 24pt Cambria title, a 10.5pt muted subtitle, a right-aligned section tag, and a hairline rule beneath.
- Title slide: full navy background, a teal vertical bar at the far left edge, kicker in letter-spaced caps, large Cambria title, subtitle, a short teal rule, four metadata columns, and a footer rule with "Draft for review". Keep the title short enough for one line.
- Rounded rectangles (radius ~0.05), soft shadows, hairline borders. No gradients, no accent stripes under titles, no decorative colour bars.

## Build instructions

Use `pptxgenjs` in Node. Set `pres.layout` before adding slides. Hex colours with **no** `#` and no alpha. Build a fresh options object for every `addShape`/`addText` — never share one. Shadow offsets must be ≥ 0. Use `charSpacing`, not `letterSpacing`. Put `isTextBox: true` on every `addText` and `margin: 0` wherever text must align to a shape edge. `rectRadius` only works on `ROUNDED_RECTANGLE`.

Write a small shared helper library first (slide header, stat tile, card, segmented bar, legend, chevron chain, table, note band, callout band) and compose the slides from it.

**Speaker notes are mandatory on every slide** via `slide.addNotes()` — what a presenter would actually say: the argument, the number to point at, the objection to pre-empt, the line to deliver verbatim. Several hundred words per slide.

**QA before handing it over:** convert to PDF, render every slide to an image and inspect each one. Check first for text overflowing or cut off at a shape boundary — especially the last wrapped line inside bordered callout boxes, which is the most common failure. Then check for cards colliding with the band below them, content off the slide edge, and large dead gaps. Fix and re-render.

## Tone

Executive register, no hedging. The central discipline is honesty about the ceiling: do not oversell Phase 1. Make clear it reallocates depth rather than removing work, that the clerical load is almost entirely untouched, and that manual Lean reaches five scenarios against sixteen at platform steady state. That honesty is what makes the two-phase proposal credible rather than a way of deferring an investment — and it is what prevents a successful Phase 1 becoming an argument against Phase 2 later.
