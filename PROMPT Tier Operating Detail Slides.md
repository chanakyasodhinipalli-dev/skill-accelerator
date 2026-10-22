# PROMPT — Two Slides · Tier Operating Detail (checkpoints, design decisions, personas)

Copy everything below the line into a fresh session.

---

Build me a **two-slide** PowerPoint deck (.pptx) — no title slide. One slide per enablement tier, each setting out in full operational detail: the complete checkpoint sequence, every design decision with its named owner, and how each persona is involved. Audience is architects, triage leads and governance functions. Dense, infographic-led, with substantial speaker notes.

Write both slides from one shared set of helper functions — the two slides are deliberately the same shape so the room can compare them side by side.

## Context you are working from

I lead work on an enterprise ECM platform team providing repository services to partner applications — storage, archival and records management, with metadata compliance and document classification applied on arrival. We are moving from an always-dedicated delivery model to **two enablement tiers**:

- **Partner Express** — *partner-owned delivery*. No allocated cell. ECM defines every checkpoint and design decision but does not run the delivery. 29 of 38 scenario types at steady state.
- **Commissioned Cell** — *requires executive sanction*. An allocated Partner Enablement cell, inception to release. 9 of 38 at steady state.

Tier is assigned by ECM against a published seven-determinant rubric scored 0–3 each (max 21): **0–5** Express self-served · **6–11** Express assisted · **12–21** Commissioned Cell. Five hard overrides force Commissioned regardless of score.

**Call them "design decisions", never "guardrails".** The framing matters: these are the decisions any ECM onboarding requires, and the tiers differ in *who makes them and when*, not in whether they get made.

**Domain vocabulary:** iDocs (document classification); the DKE — Document Knowledge Engine, maintained by Imaging Governance, which trains the model iDocs uses for untrusted content; Imaging Governance determines trusted vs untrusted and allocates category/type/subtype; Records Management owns retention, INV160 and WORM; SPLI is load testing; KEES is Kafka Enablement Engagement Services; DCT performs virus scanning; Apigee is the API gateway; PAA zone placement.

## The seventeen design decisions

The same seventeen apply in both tiers. What differs is whether they are already settled.

1. Trust posture — trusted or untrusted · 2. Category, type and subtype allocation · 3. DKE change and model training · 4. Retention schedule and disposition rules · 5. WORM and INV160 applicability · 6. Zone placement and zone controls · 7. Ingestion channel and pattern · 8. Metadata model and index strategy · 9. Virus scan policy (DCT) · 10. Volume envelope and performance profile · 11. Entitlement model and access routing · 12. Environments and cutover plan · 13. Support model and on-call owner · 14. Pattern deviation and re-tier · 15. Formal change control on baselined scope · 16. Joint delivery plan and cadence · 17. Commissioning sanction

---

## SLIDE 1 — Partner Express

Title: **"Partner Express — every checkpoint, decision and persona."** Subtitle: *Partner-owned delivery. ECM defines every checkpoint and design decision; most of them the pattern has already settled.* Section tag: "Partner Express". Accent colour teal `0B6E6E`, tint `E6F2F1`.

### Left — the checkpoint sequence (table, ~7.6" wide)

Columns *Checkpoint / When / Owner / What it establishes*. Give the rows that are ECM-run a coloured left edge bar and a coloured checkpoint name; leave the confirmation rows plain.

| Checkpoint | When | Owner | What it establishes |
|---|---|---|---|
| **Intake Triage Check** | Wk 0 | Triage Lead | Pattern matched, determinants scored, completeness band met, tier and charter issued |
| **Design Checkpoint**<br>(assisted only, score 6–11) | Wk 2 | Cell rota + Architecture | Solution shape against the pattern; corrections raised before any build starts |
| Classification Confirmation | Wk 0–1 | Imaging Governance | Trust posture, and that every document type already sits in the taxonomy |
| Records Confirmation | Wk 0–1 | Records Management | That an existing retention schedule applies, and binds it to the content |
| Security Confirmation | Wk 1 | Security Review | That the entitlement model matches an already-approved access pattern |
| Volume Confirmation | Wk 1 | SPLI | That the stated volume sits inside a certified envelope — desk check, no test |
| Promotion Gate | Per env | Platform Engineering | Environments promoted in order, with evidence attached at each step |
| **Exit Check & Support Acceptance** | Pre-live | Triage Lead + Support | Evidence complete, runbook accepted, named on-call owner confirmed |

### Right — the persona panel (~4.6" wide)

A bordered panel of ten rows, each with a small coloured tick bar, the persona in bold, and **one line** on what they do. Keep each role line under about 75 characters so it never wraps.

Partner — *Owns delivery; configures against the pattern; supplies inputs at triage.* · Triage Lead (ECM) — *Scores the rubric, assigns the tier, runs the entry and exit checks.* · Cell rota member — *The one design checkpoint when the score is 6–11; office hours otherwise.* · Architecture — *Owns the pattern. Pulled in only when an intake deviates from it.* · Imaging Governance — *Confirms trust posture and that every type is already in the taxonomy.* · Records Management — *Confirms the existing retention schedule applies, and binds it.* · Security Review — *Confirms the entitlement model matches an approved pattern.* · SPLI — *Desk-confirms the volume sits inside a certified envelope.* · Platform Engineering — *Provisions Apigee, KEES and DCT from the standard configuration.* · Support & Operations — *Accepts the runbook and confirms the named on-call owner.*

### Below — the seventeen design decisions, as four cards

Each card has a coloured header with its title on the left and the **count in large serif on the right**, a bulleted item list, and a tinted footer strip carrying an italic one-line summary.

1. **Inherited from the pattern — 5** (teal): Zone placement · Ingestion channel and pattern · Metadata model and index strategy · Virus scan policy (DCT) · Environment and cutover approach. Footer: *Pre-decided. The partner follows; any deviation forces a re-tier.*
2. **Confirmed by desk check — 5** (mid teal `3E8F8F`): Trust posture — Imaging Governance · Classification allocation — Imaging Gov. · Retention schedule — Records Mgmt · Entitlement model — Security Review · Volume envelope — SPLI. Footer: *Checked against the pattern by their owner, not re-designed.*
3. **Decided per intake — 3** (amber `9A6410`): Whether a DKE change is needed — Imaging Governance · Support model and on-call owner — Support + Partner · Pattern deviation and re-tier — Triage Lead. Footer: *The only genuinely open decisions in this tier.*
4. **Not applicable here — 4** (slate, muted): WORM / INV160 binding · Formal change control on scope · Joint delivery plan and cadence · Commissioning sanction. Footer: *Each of these forces, or implies, a Commissioned Cell.*

### Closing teal band

**"Why this tier is safe without a design review."** Express works because the pattern has already made ten of the seventeen design decisions, and because the five confirmations are performed by the same owners who would review them in any other tier — Imaging Governance still determines trust posture, Records Management still binds retention, Security Review still approves the entitlement model. Nothing is skipped; it is checked against a settled answer rather than decided afresh. And the moment an intake moves outside the pattern, that deviation is itself a trigger and the intake re-tiers.

---

## SLIDE 2 — Commissioned Cell

Title: **"Commissioned Cell — every checkpoint, decision and persona."** Subtitle: *An allocated Partner Enablement cell, inception to release, sanctioned by name — and every design decision taken afresh.* Section tag: "Commissioned Cell". Accent colour navy `15304F`, tint `E8EDF4`.

### Left — the checkpoint sequence (same table shape, twelve rows)

| Checkpoint | When | Owner | What it establishes |
|---|---|---|---|
| **Commissioning Case** | Wk 0 | Triage Lead | Score of 12+ or a hard override; the written case for allocating a cell |
| **Commissioning Sanction** | Wk 0–1 | Executive Sponsor | Named approval to allocate a cell, recorded with its justification |
| Architecture Review | Wk 1–2 | Architecture | Target design, zone placement, channel pattern, integration shape |
| Classification & DKE Determination | Wk 2 | Imaging Governance | Trust posture, new category / type / subtype, whether DKE training is needed |
| Records & Retention Approval | Wk 2–3 | Records Management | New schedule, disposition rules, WORM and INV160 applicability |
| Security & Access Review | Wk 3 | Security Review | Entitlement model, access routing, role shape and zone controls |
| **Design Authority Sign-off** | Wk 4 | Design Authority | The complete design accepted; scope baselined under change control |
| Integration Readiness | Wk 5–6 | Platform Engineering | Apigee, KEES and DCT provisioned and verified against the signed design |
| Volume Certification | Wk 7 | SPLI | Load test executed against the volume model; envelope certified |
| Pre-UAT Review | Wk 8 | Cell + Partner | Build complete against baselined scope; UAT entry criteria met |
| **Pre-Go-Live Gate** | Wk 10 | Cell lead + Support | All evidence complete, runbook accepted, on-call confirmed, cutover agreed |
| **Post-Go-Live Review** | Wk 12 | Cell + Design Authority | Outcome reviewed, pattern candidate harvested, the commission closed |

### Right — the persona panel (ten rows, same shape)

Executive Sponsor — *Sanctions the commission by name; the live set is reviewed quarterly.* · Partner — *Commits to a joint delivery plan, a cadence and UAT participation.* · Triage Lead (ECM) — *Builds the commissioning case and hands over to the cell at sanction.* · Partner Enablement Cell — *Allocated inception to release; designs, builds and walks every gate.* · Architecture — *Target design, zone placement, channel and integration shape.* · Design Authority — *Signs off the design and baselines scope under formal change control.* · Imaging Governance — *Determines trust posture, allocates taxonomy, runs DKE training.* · Records Management — *Approves a new retention schedule and certifies WORM / INV160.* · Security Review — *Reviews the entitlement model, access routing and zone controls.* · Platform Eng. & SPLI — *Provisions integration; runs the load test and certifies the envelope.*

### Below — the same seventeen design decisions, grouped by deciding function

Use a navy depth ramp across the four cards (`5E7D96`, `3E6686`, `264E72`, `15304F`) so they read as one family and do not compete with slide 1's teal.

1. **Content & classification — 3**: Trust posture — trusted or untrusted · Category, type and subtype allocation · DKE change and model training. Footer: *Imaging Governance decides all three.*
2. **Records & security — 4**: Retention schedule and disposition rules · WORM and INV160 applicability · Entitlement model and access routing · Zone placement and zone controls. Footer: *Records Management and Security Review.*
3. **Design & integration — 5**: Ingestion channel and pattern · Metadata model and index strategy · Virus scan policy (DCT) · Volume envelope and performance profile · Formal change control on baselined scope. Footer: *Architecture, Design Authority and Platform Engineering.*
4. **Delivery & ownership — 5**: Joint delivery plan and cadence · Environments and cutover plan · UAT entry and acceptance criteria · Support model and on-call owner · Commissioning sanction. Footer: *The cell, the partner, Support and the Executive Sponsor.*

### Closing note

The post-go-live review is the one checkpoint with no equivalent in Partner Express, and it is what makes the two tiers a system rather than two unrelated paths: every commissioned delivery is mined for a pattern candidate, and a pattern harvested here is what allows the next intake of that shape to run as Express. Commissioned work is therefore how the Express catalogue grows.

---

## Design system

- 13.3 × 7.5 inches (`LAYOUT_WIDE`). Margins 0.45" left and right.
- Partner Express teal `0B6E6E` + tint `E6F2F1`; Commissioned navy `15304F` + tint `E8EDF4`; navy ramp `5E7D96` / `3E6686` / `264E72` / `15304F` with tints `EEF2F6` / `EAF0F5` / `E7ECF3` / `E9EEF4`; amber `9A6410` + `FAF1DF`; slate `7C8798`; ink `1B2432`, muted `55606E`, line `D4DAE2`, panel `F4F7FA`.
- Fonts — Cambria for titles and the large decision counts; Calibri for everything else.
- Slide header on both: a 24pt Cambria title, a 10.5pt muted subtitle, a right-aligned section tag, a hairline rule beneath. No slide-number square — these drop into an existing deck.
- Rounded rectangles (radius ~0.05), soft shadows, hairline borders. No gradients.

## Build instructions

Use `pptxgenjs` in Node. Set `pres.layout` before adding slides. Hex colours with **no** `#` and no alpha. Fresh options object for every `addShape`/`addText`. Shadow offsets ≥ 0. `charSpacing`, not `letterSpacing`. `isTextBox: true` on every `addText`, `margin: 0` where text aligns to a shape edge. `rectRadius` only on `ROUNDED_RECTANGLE`. A shape with `line: { width: 0 }` still renders a dark hairline in some renderers — pass `line: { color: <same as fill>, width: 0 }` for any filled strip or bar that should have no border.

Write three helpers and reuse them on both slides: a **checkpoint table** (with the optional coloured left edge and coloured name for emphasis rows), a **persona panel** (fixed height divided by the number of rows, hairline dividers between), and a **design-decision card row** (coloured header with title left and count right, bulleted items, tinted footer strip).

**Vertical budget — lay this out arithmetically, both slides are tight.**
- Slide 1: header to 1.02 · section labels 1.12 · table and panel 1.34–4.08 (8 rows at 0.31; panel height 2.74) · section label 4.26 · decision cards 4.48–6.18 (height 1.70) · closing band 6.36–7.20.
- Slide 2: section labels 1.12 · table and panel 1.34–4.60 (12 rows at 0.25; panel height 3.26) · section label 4.78 · decision cards 5.00–6.68 (height 1.68) · closing note 6.74–7.22.
- Inside a decision card: header strip 0.30 · items from +0.38 with height `h − 0.82` at 7.4pt and lineSpacing 8.9 · footer strip at `h − 0.38`. **The commonest failure is the fifth item in a five-item card being cut by the footer strip**, so check that first.

## Speaker notes

`slide.addNotes()` on both, 900–1,100 words each, structured as purpose · a walk-through of each block · and a closing "likely questions" section. Required content:

**Slide 1** — lead with the central argument: Express has no standing design review, and the obvious objection is that intakes go through unexamined. Of the seventeen design decisions, ten are already made and only three are genuinely open. Express is not lighter governance; it is governance applied to decisions settled once for a pattern rather than re-litigated per intake. Stress to governance functions that their authority is unchanged — what changes is the shape of the question, from "design the classification for this intake" to "confirm these types are already in the taxonomy". Highlight that Architecture's time moves from reviewing thirty-eight intakes to curating the patterns that make thirty-eight intakes reviewable. Note that a confirmation *failing* is a feature: it means the intake is not what the pattern assumed, and it re-tiers.

**Slide 2** — make the tier look expensive, because it is. Explain that the commissioning sanction is the control that stops the model collapsing back to today within two quarters. Point out that the governance determinations feed the design sign-off rather than following it, which is the opposite of how these intakes often run today. Dwell on the post-go-live review as the most important checkpoint on the slide — commissioned work is how the Express catalogue grows, and the review is a closure condition on the commission rather than an optional retrospective. Pre-empt "twelve checkpoints sounds like more governance than today" with: it is more *visible* governance, not more governance — most of these happen today informally and often late.

## QA before handing it over

Convert to PDF, render both slides and inspect each. Check first that **no decision-card item is cut by the footer strip** — the five-item cards fail first. Then check the last table row against the section label below it, the persona panel's last row against its border, the closing band or note against the slide edge, and that every persona role line fits on one line. Fix and re-render to confirm.

## Tone

Operational and precise. This is reference material people will come back to and argue with, so every checkpoint needs a named owner and every design decision needs a named decider. Do not soften the Commissioned slide — the cost of a cell should be visible, because making commissioning rare is the entire point of having two tiers.
