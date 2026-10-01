# Partner Onboarding Transformation — Copilot Slide Notes for Leadership Proposal

Oct 1, 2026 · @Chanakya Sodhinipalli

## How to use this pack with Copilot

This pack turns the Partner Onboarding current-state and target-state document into a 50-slide leadership deck plus a 3-slide appendix, written so Microsoft Copilot in PowerPoint can build each slide with minimal rework.

Every slide entry below carries four things: a ready-to-paste **Copilot prompt**, the **layout and visual** to ask for, the **on-slide content** (the facts Copilot must use, no invention), and **speaker notes** that carry the thought process behind the slide.

Recommended workflow:

1. Export this doc to Word and save it to OneDrive or SharePoint so Copilot can reference it.
2. In PowerPoint, start a blank deck on your corporate template, then paste the **Master prompt** (next section) once so Copilot sets the tone, structure and design rules.
3. Build section by section: paste each slide's Copilot prompt, then paste its on-slide content table as the source material. Building one section at a time gives far better results than asking for 50 slides in one prompt.
4. Paste the speaker notes into the Notes pane of each slide (Copilot will draft notes, but these carry the argument you want leadership to hear).
5. After the deck is built, run the final polish prompts in the appendix section to check consistency, terminology and length.

Two rules keep the deck credible. First, Copilot must not invent numbers: effort and elapsed-time figures are shown as `[baseline]` placeholders until the current-state measurement in slide 47 is done. Second, the deck must always distinguish what the agent does from what named humans decide, especially the Imaging Governance determination.

## Master prompt, design system and slide anatomy

Paste the master prompt once at the start of the Copilot session; every per-slide prompt below assumes it is in force.

### Master Copilot prompt

> You are building a leadership proposal deck titled "Partner Onboarding Transformation: From Person-Held Process to Agent-Assisted Execution with Onboard360AI". The audience is senior technology and business leadership who will approve investment. Tone: confident, precise, executive; no marketing language, no exclamation marks. Use only the facts I provide for each slide; never invent metrics, dates, costs or team names. Where a number is not supplied, show the placeholder \[baseline\]. Every slide must carry an action title (a full-sentence takeaway of at most 14 words), not a topic label. Keep to a maximum of 6 bullets per slide and 12 words per bullet; move detail into speaker notes. Use consistent terms: ICMP, Onboard360AI, Partner Onboarding Resource, Imaging Governance, sub-agent, skill, stage, workstream. Always make clear that Onboard360AI assists and enforces rules but does not approve; named humans keep every decision. Add a small breadcrumb in the top-right corner of each slide showing the section and stage (for example "Phase A · Stage 2 of 9").

### Design system to request

| Element | Instruction for Copilot |
| --- | --- |
| Template | Corporate template; 16:9; light background |
| Colour coding | Phase A Intake & Prioritisation = blue; Phase B Planning & Commitment = amber; Phase C Build & Go-Live = green; Target state = purple; Risks and impediments = red accents only |
| Breadcrumb | Top-right: Section · Stage n of 9, using the phase colour |
| Process strip | A thin 9-stage chevron strip along the bottom of every stage slide, with the current stage highlighted |
| Fonts | Template defaults; titles 28–32 pt, body no smaller than 14 pt |
| Icons | Simple line icons only; one icon per element, never decorative clip art |
| Tables | Max 5 columns, max 7 rows on a slide; bigger tables go to the appendix |
| Callout box | One red-bordered "Where it breaks" box on each current-state slide; one purple "With Onboard360AI" box on each target-state slide |
| Human-authority marker | A small person icon labelled "Human decision" on any element a named role still decides |

### Standard anatomy of a process or sub-process slide

Every stage slide and every Stage 8 workstream slide uses the same seven-panel layout, so leadership can read any slide in isolation and see the whole thought process.

| Panel | What it answers | Position on slide |
| --- | --- | --- |
| 1. Aim | Why this stage exists, in one sentence | Top band under the title |
| 2. Goals | 2–4 outcomes the stage must achieve | Left column, top |
| 3. Artifacts at exit | What is produced and the exit criteria | Left column, bottom |
| 4. Current BAU | How it runs today and who owns it | Middle column, top |
| 5. Impediments & challenges | Where it breaks and what it costs downstream | Middle column, bottom, red callout |
| 6. Target state | Onboard360AI sub-agents and key skills applied | Right column, purple callout |
| 7. Thought process | The one-line logic linking problem to fix, plus the human decision retained | Bottom band above the process strip |

When a stage is too dense for one slide, Copilot should keep panels 1, 4, 5, 6 and 7 on the slide and move goals and artifacts into the speaker notes.

## Agenda and slide map

The deck runs in eight sections: it opens with the case, walks all nine stages and ten delivery workstreams in process order, proves the pattern with the AGRIA use case, then lands the target state, governance, roadmap and the ask.

| # | Slide | Section | Type |
| --- | --- | --- | --- |
| 1 | Title | 1. Opening | Title |
| 2 | Executive summary | 1. Opening | Summary |
| 3 | The problem and why now | 1. Opening | Argument |
| 4 | Agenda | 1. Opening | Agenda |
| 5 | End-to-end flow: 9 stages, 3 phases | 2. Current-state foundations | Process map |
| 6 | The Partner Onboarding Resource | 2. Current-state foundations | Role |
| 7 | Imaging Governance decision rights | 2. Current-state foundations | Role |
| 8 | The four lifecycle deliverables | 2. Current-state foundations | Artifacts |
| 9 | Accountability handoffs and effort profile | 2. Current-state foundations | Analysis |
| 10 | Phase A overview: Intake & Prioritisation | 3. Phase A | Divider |
| 11 | Stage 1: Partner Request | 3. Phase A | Process |
| 12 | Stage 2: Intake Review | 3. Phase A | Process |
| 13 | Stage 2 deep dive: triage label state machine | 3. Phase A | Sub-process |
| 14 | Stage 3: LOB Priority | 3. Phase A | Process |
| 15 | Stage 4: Discovery & Triage | 3. Phase A | Process |
| 16 | Phase B overview: Planning & Commitment | 4. Phase B | Divider |
| 17 | Stage 5: Product Epic Creation | 4. Phase B | Process |
| 18 | Stage 6: Quarterly Big Room Planning | 4. Phase B | Process |
| 19 | Stage 7: Capacity Assessment | 4. Phase B | Process |
| 20 | Phase C overview: Stage 8 workstream map | 5. Phase C | Divider |
| 21 | 8.1 Connectivity, security and foundational setup | 5. Phase C | Sub-process |
| 22 | 8.2 Apigee onboarding and subscription | 5. Phase C | Sub-process |
| 23 | 8.3 KEES Kafka enablement | 5. Phase C | Sub-process |
| 24 | 8.4 Content processing configuration | 5. Phase C | Sub-process |
| 25 | 8.5 Metadata, repository and retrieval | 5. Phase C | Sub-process |
| 26 | 8.6 Records Management and retention | 5. Phase C | Sub-process |
| 27 | 8.7 Capacity engineering and SPLI | 5. Phase C | Sub-process |
| 28 | 8.8 Testing | 5. Phase C | Sub-process |
| 29 | 8.9 Environment progression | 5. Phase C | Sub-process |
| 30 | 8.10 Documentation and operational readiness | 5. Phase C | Sub-process |
| 31 | Stage 9: Partner Live | 5. Phase C | Process |
| 32 | Current-state synthesis: impediment heatmap | 5. Phase C | Analysis |
| 33 | Worked use case: RIA Platform (AGRIA) | 6. Proof | Case |
| 34 | What AGRIA demonstrates | 6. Proof | Insight |
| 35 | Target-state vision | 7. Target state | Vision |
| 36 | Platform architecture: iDocs Canvas to skills | 7. Target state | Architecture |
| 37 | The governing design rule: sub-agent or skill | 7. Target state | Principle |
| 38 | Integration maturity P1–P3 and runtime disclosure | 7. Target state | Model |
| 39 | Sub-agent roster mapped to stages | 7. Target state | Roster |
| 40 | Skills catalogue: 138 skills, 12 domains | 7. Target state | Catalogue |
| 41 | Skills by user type | 7. Target state | Personas |
| 42 | Why the orchestrator carries state | 7. Target state | Principle |
| 43 | Governance rules encoded as skills | 8. Governance & case | Controls |
| 44 | Human authority and approval | 8. Governance & case | Controls |
| 45 | Where the benefit comes from | 8. Governance & case | Benefit |
| 46 | Build sequencing: five waves | 8. Governance & case | Roadmap |
| 47 | What must be measured first | 8. Governance & case | Measurement |
| 48 | Delivery risks and mitigations | 8. Governance & case | Risk |
| 49 | The leadership ask | 8. Governance & case | Decision |
| 50 | Next 90 days | 8. Governance & case | Plan |
| A1 | Glossary | Appendix | Reference |
| A2 | Skills catalogue detail by domain | Appendix | Reference |
| A3 | Enabler user journey: skills by lifecycle point | Appendix | Reference |

### Slide-level Copilot prompt for the agenda (slide 4)

> Create an agenda slide with eight numbered sections: 1 Opening, 2 Current-state foundations, 3 Phase A Intake & Prioritisation (Stages 1–4), 4 Phase B Planning & Commitment (Stages 5–7), 5 Phase C Build & Go-Live (Stage 8 workstreams and Stage 9), 6 Proof: AGRIA worked use case, 7 Target state: Onboard360AI, 8 Governance, roadmap and the ask. Show sections 3, 4 and 5 in their phase colours as a horizontal flow, and sections 6 to 8 as the "so what" band below it. Action title: "We walk the process stage by stage, then show how Onboard360AI changes it."

## Section 1 — Opening (slides 1–4)

The opening states the decision up front: approve Onboard360AI as an orchestrating sub-agent that externalises the onboarding record and enforces the rules that fail silently today.

### Slide 1 — Title

**Copilot prompt:**

> Create a title slide. Title: "Partner Onboarding Transformation". Subtitle: "From a person-held process to agent-assisted execution with Onboard360AI on iDocs Canvas". Footer line: "ECM / ICMP · Leadership proposal · Draft for review". Add a subtle background graphic of a nine-step chevron flow fading into a connected network of nodes.

**Speaker notes:** Today's ask is a build decision, not a technology tour. We will show how onboarding works now, where it breaks, and the specific design that fixes it while leaving every real decision with the people who own it.

### Slide 2 — Executive summary

**Action title:** Onboarding is a stable procedure held in one person's memory; we propose encoding it.

**Copilot prompt:**

> Create an executive summary slide with three columns titled "Today", "Proposal" and "Decision needed". Use the content below verbatim as bullets. Add a single bottom banner stating: "Onboard360AI assists and enforces. It does not approve."

**On-slide content:**

| Today | Proposal | Decision needed |
| --- | --- | --- |
| 9 fixed stages, 3 phases, every partner | Onboard360AI as orchestrating sub-agent under the Platform Specialist Agent | Approve Wave 1: cross-cutting skills + 8 MVP1 sub-agents |
| Accountability changes hands at least 6 times | 19 goal-bearing sub-agents, 138 skills in 12 domains | Fund the current-state baseline measurement |
| One role engaged in 8 of 9 stages | Rules enforced, not remembered; waiting made visible | Name business owners for governance and RM integration |
| Critical rules fail silently (routing, access, ladder) | Integration phased P1 Link → P2 Guide → P3 Direct | Agree success measures before build |

**Speaker notes:** The process does not vary by partner; the content does. That is the profile of work that benefits from agent assistance: stable procedure, variable input. We are not replacing judgement. We are removing rework, hidden waiting and lost context.

### Slide 3 — The problem and why now

**Action title:** Three structural traits make onboarding slow, fragile and hard to scale.

**Copilot prompt:**

> Create a slide with three large numbered cards in a row, each with an icon, a headline and two short supporting lines. Under the cards, add a red-bordered callout box titled "What it costs" with three bullets. Use only the content provided.

**On-slide content:**

1. **Accountability moves repeatedly** — partner team, ECM intake, LOB sponsor, product owner, L3 PM, engineering, onboarding resource. Each handoff rebuilds context instead of carrying it.
2. **One role spans everything** — the Partner Onboarding Resource is the only participant in 8 of 9 stages. Continuity depends on their working memory.
3. **The pattern repeats almost identically** — same stages, workstreams, artifacts, routing rules, approval paths. Only the content differs.

"What it costs": misrouted tickets and access requests that fail days later; designs built on assumed classifications and reworked; waiting for clarifications, approvals and queues that nobody can see. Effort and elapsed time: `[baseline]`.

**Speaker notes:** None of these are performance problems of the people involved. They are structural. The third trait is the opportunity: because the shape is fixed, the rules can be written once and enforced every time.

### Slide 4 — Agenda

Use the agenda prompt in the Agenda and slide map section above.

**Speaker notes:** Sections 3 to 5 follow the process in order; each stage slide shows aim, goals, artifacts, current BAU, impediments, target state and the thought process linking them. Sections 6 to 8 are the so-what.

## Section 2 — Current-state foundations (slides 5–9)

These five slides give leadership the frame they need before the stage walk: the flow, the two roles that shape it, the deliverables, and where accountability changes hands.

### Slide 5 — End-to-end flow: 9 stages, 3 phases

**Action title:** Every onboarding runs the same nine stages; only duration and teams vary.

**Copilot prompt:**

> Create a process map slide: a horizontal chevron flow of nine stages grouped under three coloured phase brackets. Under each phase bracket, add one line stating what the phase establishes and one line stating what dominates it. Add a footnote: "No stage is skipped; the sequence does not vary by partner type or request size."

**On-slide content:**

| Phase | Stages | Establishes | Dominated by |
| --- | --- | --- | --- |
| A · Intake & Prioritisation (blue) | 1 Partner Request · 2 Intake Review · 3 LOB Priority · 4 Discovery & Triage | Demand is real, complete, understood and worth doing | Information gathering and judgement |
| B · Planning & Commitment (amber) | 5 Product Epic Creation · 6 Quarterly Big Room Planning · 7 Capacity Assessment | Delivery will take the work against a planning increment | Negotiation and sequencing |
| C · Build & Go-Live (green) | 8 Development & Delivery · 9 Partner Live | Solution works, is compliant, supportable and operable by others | Engineering execution and validation |

**Speaker notes:** The phases fail in different ways, so the interventions differ too. Improving Phase A does little for Phase C. That is why the target state is organised by stage and workstream, not as one generic assistant.

### Slide 6 — The Partner Onboarding Resource

**Action title:** One role carries the onboarding's memory across eight of nine stages.

**Copilot prompt:**

> Create a role slide. Left: a profile card for "Partner Onboarding Resource — the ICMP ambassador" with three defining traits. Right: a 3×4 grid of twelve responsibility tiles, each with a small icon. Bottom: a red callout titled "Structural constraint". Use only the content provided.

**On-slide content:**

- **Purpose:** help the partner integrate with ICMP so the business meets its goals, while keeping content valuable to the enterprise.
- **Traits:** accountable for on-time completion; SME from first call to deployment validation call; absorbs the variability the standard process does not anticipate.
- **Twelve responsibility tiles:** Project engagement · Partner System Agreement · Capacity planning · SPLI engagement · Security analysis · Apigee · Technology notes · KEES · Records Management · Readiness · Release transition · Go-live.
- **Structural constraint:** what was agreed, what is outstanding, who owes what, and which approval blocks which activity lives in one person's working memory, not in a system.

**Speaker notes:** This is not a criticism of how the role is performed; it is excellent work under a design that depends on memory. A partner optimising for its own timeline will not naturally optimise for metadata quality, retention correctness or searchability. Reconciling those is the role's real job, and it should spend its time there, not on follow-up and routing.

### Slide 7 — Imaging Governance decision rights

**Action title:** Imaging Governance holds a decision right that sets the whole content design.

**Copilot prompt:**

> Create a slide with two decision cards side by side, each marked with a "Human decision" icon. Below them, a two-row consequence strip with arrows pointing to downstream impact. Add a purple footer line: "A service can be accelerated. A decision right can be prepared for, tracked and carried forward, but not taken over by an agent."

**On-slide content:**

| Decision | What it governs |
| --- | --- |
| Trusted vs untrusted determination | Whether a document path needs virus scanning, AI classification and human-in-the-loop, or bypasses classification. Sets the scope of an entire workstream. |
| Document classification allocation (trusted content) | Category, type and subtype applied on arrival; retention, search filters and audit retrieval are keyed to it. |

Consequences: samples are needed at discovery, not delivery, because the determination is made by viewing documents on the flow. Designing against an assumed classification forces rework of profiles, classification configuration and retention keying.

**Speaker notes:** Other specialist teams provide services; Imaging Governance decides. That distinction drives one of our most important design choices: the agent prepares the submission, tracks the decision and registers the outcome, but never makes the determination.

### Slide 8 — The four lifecycle deliverables

**Action title:** Four deliverables are hand-assembled from information that already exists.

**Copilot prompt:**

> Create a four-quadrant slide, one quadrant per deliverable, each with an icon, a purpose line and the stage where it is produced. Add a bottom banner: "Each is assembled by hand, largely from information already captured elsewhere in the process."

**On-slide content:**

| Deliverable | Purpose | Produced in |
| --- | --- | --- |
| Production Release Transition Page | Makes the solution supportable by Platform Support, Delivery Management and Cloud/Hosting Engineering | Stage 9 |
| Partner System Agreement | Records the partner's use of ICMP, sign-off evidence, email and copied teams | Stage 8.1 |
| RM Onboarding Questionnaire | Turns a business retention requirement into an enforced retention schedule | Stage 8.6 |
| TS Profile Updates & Configuration Changes | Technical specification and configuration for the partner to run on ICMP | Stage 8 |

**Speaker notes:** These documents are generation problems once the onboarding record exists. That is why release readiness is late in the build sequence: it becomes cheap once everything upstream is captured.

### Slide 9 — Accountability handoffs and effort profile

**Action title:** Ownership changes hands at least six times; context is rebuilt at each.

**Copilot prompt:**

> Create a swimlane-style slide: nine stage columns across the top and one row showing the accountable owner per stage, with a handoff arrow icon wherever the owner changes. Add a second row showing the Partner Onboarding Resource as a continuous bar across stages 1–9 except Stage 3. Add a right-side panel with three effort-profile notes per phase.

**On-slide content:**

| Stage | Accountable owner |
| --- | --- |
| 1 Partner Request | Partner or application team |
| 2 Intake Review | ECM intake team (L4/L3 PMs) |
| 3 LOB Priority | LOB sponsor |
| 4 Discovery & Triage | Product owner |
| 5 Product Epic Creation | L3 product manager |
| 6 Big Room Planning | L3 product manager |
| 7 Capacity Assessment | Enabling and engineering teams |
| 8 Development & Delivery | Engineering and enabling teams |
| 9 Partner Live | Partner Onboarding Resource |

Effort and elapsed days per stage: `[baseline]`.

**Speaker notes:** Every arrow is a point where context can be lost. The one continuous bar is the onboarding resource, which is exactly what Onboard360AI externalises into a shared onboarding record.

## Section 3 — Phase A: Intake & Prioritisation (slides 10–15)

Phase A decides whether demand is real, complete, understood and worth doing; its errors are cheap to fix here and expensive three stages later.

For every stage slide from here on, the Copilot prompt follows one pattern. Paste it, then paste that slide's seven-panel table as source content:

> Using the standard seven-panel stage layout and the phase colour from the master prompt, create a slide for \[Stage name\]. Use the action title provided. Fill each panel from the table I paste next, keeping each panel to 2–4 short bullets. Put the Impediments panel in the red "Where it breaks" callout and the Target state panel in the purple "With Onboard360AI" callout. Mark any human decision with the "Human decision" icon. Highlight \[Stage n\] in the 9-stage strip at the bottom.

### Slide 10 — Phase A overview

**Action title:** Phase A converts a business need into a validated, ranked, scoped demand.

**Copilot prompt:**

> Create a blue section divider titled "Phase A · Intake & Prioritisation". Show stages 1–4 as four connected tiles, each with its one-line purpose. Add a right-hand panel "What goes wrong in this phase" with three bullets.

**On-slide content:** Stage 1 captures the need · Stage 2 checks it is understood · Stage 3 decides if it is worth doing · Stage 4 turns it into a design. What goes wrong: incomplete packages chased in discovery; misrouting through missing labels; scope set on assumed classification.

**Speaker notes:** Phase A is judgement-heavy and information-heavy. The target state here focuses on completeness before submission, routing without manual label edits, and preparing the Imaging Governance decision early.

### Slide 11 — Stage 1: Partner Request

**Action title:** A complete intake package is the cheapest fix in the whole lifecycle.

| Panel | Content |
| --- | --- |
| Aim | Give product teams enough to judge scope, readiness and alignment before engineering is invested. |
| Goals | Business need and objectives stated in evaluable terms · ICMP capabilities named (archival, retention, search, retrieval, viewing, notification) · Document profile captured: types, sizes, traits · Dependencies listed |
| Artifacts at exit | Completed Definition of Ready (DOR) workbook · Submitted request with supporting detail · Exit: request submitted (completeness judged in Stage 2) |
| Current BAU | Requestor downloads and completes the DOR workbook by hand; onboarding resource explains the process. Accountable: partner or application team. |
| Impediments & challenges | Gaps surface three stages later in discovery · Requestors don't know how each field is used downstream · Samples, volumes and retention often missing, yet they drive classification, capacity and repository design |
| Target state | Intake Authoring Assistance + POC Assistance sub-agents · DOR Walkthrough (SK-IN-01), Document Profile and Volume Capture (SK-IN-03, 04), Sample Availability Check (SK-IN-13), Retention Capture (SK-IN-06), Intake Completeness Pre-Check (SK-IN-09), Intake Ticket Creation (SK-IN-10) · Trusted/untrusted pre-assessment (SK-IN-05) labelled provisional |
| Thought process | Missing information costs most when found late, so check completeness before submission. Human retained: the requestor owns completeness; Imaging Governance owns the real determination. |

**Speaker notes:** Document types drive classification design; sizes and traits drive the trusted/untrusted determination and profile design; volumes decide whether load testing is needed at all. Every one of those decisions is sourced here, which is why we invest in Stage 1.

### Slide 12 — Stage 2: Intake Review

**Action title:** Intake Review protects engineering capacity, but routing depends on manual labels.

| Panel | Content |
| --- | --- |
| Aim | Confirm the request is understood well enough for anyone to judge it, and name who must attend discovery. |
| Goals | Validate completeness, accuracy, readiness · Open the triage state · Return or clarify incomplete requests · Identify POs, architects and SMEs for discovery |
| Artifacts at exit | Validated intake record · Triage label opened · Named discovery participant list · Exit: intake meets minimum criteria |
| Current BAU | ECM intake team (L4/L3 PMs) reviews by hand; intake coordinator applies first label; clarifications brokered by the onboarding resource. |
| Impediments & challenges | No validation that labels, area tags and date are all set · A missing impact tag silently never reaches the right team · Follow-ups rely on notes being read · Discovery held without the right SME produces scope that must be revisited |
| Target state | Intake Verification + Triage Classification sub-agents · Completeness Validation (SK-TR-01), Gap Report (SK-TR-02), Label State Transition (SK-TR-03), SME & Participant Identification (SK-TR-09), Triage Readiness Brief (SK-TR-10), Audit Trail (SK-TR-11) |
| Thought process | Routing is a rule, not a judgement, so encode it; completeness on a marginal intake remains a human call. Human retained: ECM intake team decides if the intake advances. |

**Speaker notes:** Stage 2 is not about whether the demand is worth doing; that is Stage 3. It is about whether it is understood. The second job, naming discovery participants, is easy to overlook and expensive to miss.

### Slide 13 — Stage 2 deep dive: triage label state machine

**Action title:** Four manual edits complete triage, and nothing checks they were all made.

**Copilot prompt:**

> Create a state-diagram slide with four states as rounded boxes connected by arrows: TRIAGE-NOT-STARTED → TRIAGE-AWAITING-DETAILS → TRIAGE-COMPLETED → Intake-Done, plus a direct arrow from NOT-STARTED to COMPLETED labelled "no follow-up needed". Under each state, show who applies it. Add a red callout listing the fragile points and a purple callout listing the encoding skills.

**On-slide content:**

| State | Applied by | Required action |
| --- | --- | --- |
| TRIAGE-NOT-STARTED | Intake coordinator | Intake in queue, not yet picked up |
| TRIAGE-AWAITING-DETAILS | Triage lead | Remove NOT-STARTED; add follow-up tags; note what is needed and by when |
| TRIAGE-COMPLETED | Triage lead | Remove prior labels; add DCRS area labels; enter completion date |
| Intake-Done | Intake coordinator | Closes the loop |

Impact tags also applied by hand: image capture, document generation, print-and-mail data flow, SHRP, AI document classification, impacted components.

With Onboard360AI: Triage Completion Field Set (SK-TR-06) performs the full sequence atomically; Follow-Up Loop Registration (SK-TR-07) and Nudge & Ageing Report (SK-TR-08) enforce the follow-up date; Area Label and Impact Tag Derivation (SK-TR-04, 05) propose labels with reasoning.

**Speaker notes:** This is the clearest example of a rule that fails silently. An intake with a missing impact tag does not error; the specialist team simply never sees it. Atomic completion removes the class of error entirely.

### Slide 14 — Stage 3: LOB Priority

**Action title:** The business ranks demand, and that ranking is the argument at capacity.

| Panel | Content |
| --- | --- |
| Aim | Let the people accountable for the outcome decide sequencing, not whoever pushes hardest or submits first. |
| Goals | Assess business value · Weigh regulatory impact and customer commitments · Assess operational risk, including of not doing it · Check strategic alignment |
| Artifacts at exit | Prioritised ranking within the LOB portfolio · Exit: ranking established and communicated |
| Current BAU | LOB sponsors and liaisons assemble evidence and rank; ECM product management supports. |
| Impediments & challenges | Evidence assembled ad hoc for each demand · Regulatory drivers not always surfaced, though they turn discretionary work into obligation · An under-invested ranking leaves no basis to argue for a slot in Stage 7 |
| Target state | Prioritisation Support sub-agent · LOB Priority Evidence Pack (SK-PL-01), Regulatory Driver Summary (SK-PL-02), Operational Risk Framing (SK-PL-03), Onboarding Status View (SK-XC-01), Ageing & Bottleneck Report (SK-XC-11) |
| Thought process | Sponsors need evidence, not procedure; the agent assembles it, the sponsor ranks. Human retained: LOB sponsor decides whether the demand is worth doing. |

**Speaker notes:** Demand always exceeds capacity. The ranking becomes a formal input to planning, capacity and delivery commitments. A clean evidence pack shortens the conversation without taking the decision.

### Slide 15 — Stage 4: Discovery & Triage

**Action title:** Discovery turns a request into a design and fixes three lifelong determinations.

| Panel | Content |
| --- | --- |
| Aim | Identify every impacted area early and give all participants one shared understanding of the approach. |
| Goals | Map requirements, dependencies, architecture and integration touchpoints · Surface compliance: retention, regulatory storage, legal hold, audit · Obtain Imaging Governance trusted/untrusted determination and, for trusted content, category/type/subtype · Refine volume picture · Apply area and impact labels |
| Artifacts at exit | Agreed scope · Governance determination and classification · Area and impact labels · Triage completion date · Dependencies and risks · Exit: triage complete or held in awaiting-details |
| Current BAU | Product owner accountable; architects, SMEs, partner, onboarding resource, Imaging Governance, specialist teams and engineering all engaged at once. |
| Impediments & challenges | All five team groups needed in the same sessions · Samples not available, so governance cannot decide · Designs advance on an assumed classification · Regulatory position found late invalidates repository design · Missing labels misroute work |
| Target state | POC Assistance, Triage Classification, Imaging Governance Liaison, Records & Retention, Volume Assessment sub-agents · Governance Submission Pack (SK-CN-12), Determination Tracking (SK-CN-13), Classification Registration (SK-CN-14), Regulatory Storage Check (SK-RM-06), Volume Assessment (SK-CP-01), Onboarding Pattern Reuse (SK-XC-12) |
| Thought process | Discovering an impacted area in delivery costs an order of magnitude more, so prepare decisions early and reuse precedent. Human retained: Imaging Governance determination and allocation; product owner owns scope. |

**Speaker notes:** The three determinations that run to the end of the lifecycle are the governance determination, the retention and regulatory position, and the volume picture. Holding an intake in awaiting-details is better than advancing it on an assumption; the agent makes that waiting visible instead of hidden.

## Section 4 — Phase B: Planning & Commitment (slides 16–19)

Phase B turns a scoped demand into a dated commitment or an explicit refusal; its failure mode is a commitment given without understanding.

### Slide 16 — Phase B overview

**Action title:** Phase B converts an agreed scope into a formal delivery commitment.

**Copilot prompt:**

> Create an amber section divider titled "Phase B · Planning & Commitment". Show stages 5–7 as three connected tiles with one-line purposes. On the right, show the four commitment indicators (TBD, ATL, ATL+, BTL) as coloured chips with their meaning.

**On-slide content:** Stage 5 makes demand visible in the planning system · Stage 6 puts it in front of the people who must resource it · Stage 7 returns a commitment position. Indicators: TBD = not yet determined · ATL = committed in the increment · ATL+ = committed with extra confidence or scope · BTL = understood but not committed.

**Speaker notes:** The value of Phase B lies as much in the refusals as the acceptances. A BTL position stated early lets the business re-prioritise or reset partner expectations; an unstated capacity problem shows up later as a missed date.

### Slide 17 — Stage 5: Product Epic Creation

**Action title:** The epic is the spine every later commitment and report hangs from.

| Panel | Content |
| --- | --- |
| Aim | Make the onboarding visible and trackable inside the delivery organisation's planning system. |
| Goals | Raise the Product Epic · Create and link features, stories and work items · Assign ownership per feature · Give end-to-end visibility of activities and deliverables |
| Artifacts at exit | Product Epic with linked L2 features, stories and work items · Exit: hierarchy complete with ownership assigned |
| Current BAU | L3 product manager builds the hierarchy by hand from the triage outcome, with POs and the onboarding resource. |
| Impediments & challenges | Decomposition by use case instead of workstream stops teams committing independently · Unowned features surface as gaps in planning · Linkage checked manually |
| Target state | Epic & Feature Composition sub-agent · Product Epic Draft Generation (SK-PL-04), Feature Decomposition by Workstream (SK-PL-05), User Story Generation (SK-PL-06), Hierarchy Linkage Validation (SK-PL-07) |
| Thought process | A badly decomposed epic fails two stages later, so decompose by workstream and validate links and owners before planning. Human retained: L3 PM and POs approve the hierarchy. |

**Speaker notes:** Decomposing by workstream (connectivity, events, untrusted content, trusted content, RM, metadata, search and viewing, capacity, testing, documentation) is what lets each specialist team commit to its own feature.

### Slide 18 — Stage 6: Quarterly Big Room Planning

**Action title:** A commitment without understanding is a scheduling assumption that fails later.

| Panel | Content |
| --- | --- |
| Aim | Put the demand in front of the people who must resource it, and make trade-offs visibly in one room. |
| Goals | Walk top-ranked epics with L1/L2 POs · Clarify queries · Get feature-level review from L1 POs · Seek commitment against capacity |
| Artifacts at exit | Reviewed feature set with PO commitment positions · Exit: features reviewed and positions understood |
| Current BAU | L3 PM runs a quarterly session with L1/L2 POs and engineering and enabling teams. |
| Impediments & challenges | Planning packs assembled by hand · Cross-team dependencies not visible to each PO · Unresolved queries become Stage 7 blockers · Quarterly cadence adds waiting when a demand just misses the cycle |
| Target state | Epic & Feature Composition sub-agent · Big Room Planning Pack (SK-PL-08), Cross-Team Dependency Map (SK-PL-10), Commitment Indicator Explainer (SK-PL-09) |
| Thought process | Each team must see its own dependency to commit honestly, so the pack shows it per feature. Human retained: L1/L2 POs give commitment positions. |

**Speaker notes:** Holding planning in one room compresses many bilateral negotiations. The agent's contribution is preparation: everyone arrives having seen the scope, the dependency map and the open queries.

### Slide 19 — Stage 7: Capacity Assessment

**Action title:** Capacity assessment returns a stated position, including an honest no.

| Panel | Content |
| --- | --- |
| Aim | Convert a prioritised, understood demand into a dated commitment or an explicit refusal. |
| Goals | Evaluate capacity and competing priorities · Check technical dependencies · Assess implementation readiness · Identify blockers · Confirm delivery team allocation |
| Artifacts at exit | Commitment indicator per feature (TBD/ATL/ATL+/BTL) · Identified blockers · Exit: position returned for each feature |
| Current BAU | Enabling and engineering teams assess; ECM product management and onboarding resource support. |
| Impediments & challenges | One unavailable team blocks the whole flow · BTL not always communicated early · Team allocation not carried forward, so later tickets go to the wrong project · No allocated team means only the first environment is reachable |
| Target state | Volume Assessment sub-agent with planning skills · Capacity Planning Request Assembly (SK-CP-03), Delivery Team Resolution (SK-CP-04), Capacity Ticket Creation (SK-CP-05), Delivery Team Allocation Check (SK-TE-11), Determination Carry-Forward (SK-XC-04) |
| Thought process | Team allocation decides where tickets go and how far delivery can climb, so resolve it once and carry it forward. Human retained: engineering teams own the commitment. |

**Speaker notes:** Stage 7 sets a hard gate for Stage 8: a partner without an allocated scrum team cannot progress beyond the first environment. Delivery Team Resolution never guesses; it fails explicitly if the team cannot be resolved from the intake.

## Section 5 — Phase C: Stage 8 Development & Delivery (slides 20–30)

Stage 8 is the largest stage by a wide margin: ten parallel workstreams converge on a configuration that is functional, compliant, performant and supportable by people who did not build it.

For slides 21–30 use the same stage prompt pattern from Section 3, replacing "Stage" with "Stage 8 workstream 8.n", and highlight Stage 8 in the bottom strip plus the workstream number in a secondary 10-dot tracker.

### Slide 20 — Phase C overview: Stage 8 workstream map

**Action title:** Ten workstreams run in parallel and must converge on one production configuration.

**Copilot prompt:**

> Create a green section divider titled "Phase C · Build & Go-Live". In the centre, show ten workstream tiles arranged as parallel lanes that converge into one box labelled "Production-ready configuration", which then leads to "Stage 9 · Partner Live". Colour the tiles that depend on an upstream determination with a small purple tag showing which one (governance determination, volume profile, retention position, team allocation).

**On-slide content:**

| # | Workstream | Depends on upstream |
| --- | --- | --- |
| 8.1 | Connectivity, security, foundational setup | Application identity |
| 8.2 | Apigee onboarding and subscription | Capability requirements |
| 8.3 | KEES Kafka enablement | Volume profile |
| 8.4 | Content processing configuration | Governance determination |
| 8.5 | Metadata, repository, retrieval | Governance classification |
| 8.6 | Records Management and retention | Retention position |
| 8.7 | Capacity engineering and SPLI | Volume profile, team allocation |
| 8.8 | Testing | All of the above |
| 8.9 | Environment progression | Team allocation |
| 8.10 | Documentation and operational readiness | All of the above |

**Speaker notes:** Every workstream consumes a determination made earlier. That cross-cutting state is why the target state needs an orchestrator holding the onboarding record, not just a set of independent helpers.

### Slide 21 — 8.1 Connectivity, security and foundational setup

**Action title:** Access routes by request type, and a wrong route fails silently, days later.

| Panel | Content |
| --- | --- |
| Aim | Give the partner a single, credentialled, connected application identity across the required environments. |
| Goals | Register application identity · Open firewall from partner zone to ICMP APIs · Issue and install certificates · Create service accounts and group membership · Provision human access · Complete system and user security analysis · Sign Partner System Agreement |
| Artifacts at exit | Registered identity · Certificates · Service accounts · Access grants · Security sign-offs · Signed Partner System Agreement |
| Current BAU | Onboarding resource raises each request by hand; security and network teams act on them. |
| Impediments & challenges | Firewall is a long lead-time item that blocks integration testing if late · Service accounts route via access tooling in both environments; human access routes by domain · A request in the wrong queue is rejected only after the delay · Requests not tied to one identity become orphaned |
| Target state | Foundational Setup sub-agent · Application Identity Lookup & Registration (SK-FS-01), Access Route Determination (SK-FS-07), Service Account and Group Requests (SK-FS-04, 05), Human User Access Routing (SK-FS-06), Firewall Request (SK-FS-09), Access Request Status Tracking (SK-FS-12), Partner System Agreement Assembly (SK-FS-13) |
| Thought process | Routing is a rule applied from memory today; encode it once and call it first for every access request. Human retained: security teams approve access through existing tooling. |

**Speaker notes:** This workstream is a strong candidate for early P3 integration because routing errors here are the most expensive in elapsed time.

### Slide 22 — 8.2 Apigee onboarding and subscription

**Action title:** Gateway subscription is approval-gated and tracked by hand today.

| Panel | Content |
| --- | --- |
| Aim | Grant the partner the ability to call ICMP services through the Apigee gateway. |
| Goals | Onboard to the Apigee marketplace · Identify the right ICMP API products · Register and subscribe · Obtain approvals and clearances |
| Artifacts at exit | Active API subscriptions · Approvals · Current Apigee Onboarding Tracker |
| Current BAU | Onboarding resource and partner team drive marketplace onboarding; resource obtains approvals and maintains the tracker. |
| Impediments & challenges | Approvals gate the subscription and are chased manually · Tracker currency depends on discipline · Partners hand-build API requests to start testing |
| Target state | Apigee Subscription + Postman Collection Generation sub-agents · Marketplace Walkthrough (SK-AK-01), API Product Discovery (SK-AK-02), Registration & Subscription (SK-AK-03), Approval Tracking (SK-AK-04), Tracker Maintenance (SK-AK-05), Postman Collection Generation (SK-AK-06) |
| Thought process | Subscription is procedural; approvals are not. Automate the procedure, make approvals visible and aged. Human retained: Apigee approvers. |

**Speaker notes:** The generated partner-specific API collection removes a real source of early friction: partners can call ICMP services with the right endpoints, authentication and sample payloads from day one.

### Slide 23 — 8.3 KEES Kafka enablement

**Action title:** Reconciliation is a stated outcome, not an optional extra to descope.

| Panel | Content |
| --- | --- |
| Aim | Enable event notifications so the partner can reconcile every ingestion, success and failure. |
| Goals | Initiate KEES engagement · Onboard to Kafka · Create consumer groups on the ICMP topic · Enable request- and document-level notifications · Define reconciliation, retry and exception handling · Design ingestion against volume |
| Artifacts at exit | Consumer groups · Notifications live · Reconciliation, retry and exception design · Current Kafka Onboarding Tracker |
| Current BAU | Onboarding resource initiates KEES; KEES team provisions; partner and architects design reconciliation. |
| Impediments & challenges | Separate engagement with its own approvals and lead time · Reconciliation descoped under pressure when treated as detail · Failure-path behaviour assumed, not designed |
| Target state | KEES Enablement sub-agent · Engagement Initiation (SK-AK-07), Topic & Consumer Group Design (SK-AK-08), Consumer Group Provisioning (SK-AK-09), Notification Configuration (SK-AK-10), Reconciliation Pattern Guidance (SK-AK-11), Retry & Exception Design (SK-AK-12), Ingestion Sizing Guidance (SK-CP-09) |
| Thought process | Reconciliation protects the business outcome, so the agent keeps it in scope and designs the failure path explicitly. Human retained: KEES team provisions. |

**Speaker notes:** The ingestion design must absorb the migration and peak volumes captured back in Stage 1, which is another example of a determination carried forward.

### Slide 24 — 8.4 Content processing configuration

**Action title:** Content configuration must follow the governance decision, never an assumption.

| Panel | Content |
| --- | --- |
| Aim | Configure the trusted and untrusted content paths exactly as Imaging Governance determined. |
| Goals | Untrusted: virus scanning, AI classification profile, human-in-the-loop with pre- and post-capture profiles, untrusted ICMP profile · Trusted: trusted ICMP profile configured with the governance-allocated category/type/subtype · Route new document types back for fresh decision |
| Artifacts at exit | Untrusted and trusted ICMP profiles · Classification profiles · HITL profiles · Registered classification |
| Current BAU | Onboarding resource carries the determination forward from memory; iDocs, IRM, scanning and engineering configure. |
| Impediments & challenges | Configuring on an assumed classification builds unneeded work or misses needed work · Allocated but unconfigured classification is a silent gap · New document types silently inherit an existing classification · Samples needed but late |
| Target state | Content Processing Configuration + Imaging Governance Liaison sub-agents · Untrusted and Trusted Profile Design (SK-CN-01, 02), Virus Scanning (SK-CN-03), Classification and HITL engagement (SK-CN-04, 07), Pre/Post-Capture Profiles (SK-CN-08, 09), Profile Validation (SK-CN-11), Classification Registration (SK-CN-14), New Type Re-Review Trigger (SK-CN-16) |
| Thought process | One registered determination is the single source of truth, and every profile keys to it. Human retained: Imaging Governance determination and allocation. |

**Speaker notes:** A partner may need both paths. Trusted documents bypass classification and HITL but still carry a governance-allocated classification that retention and search depend on.

### Slide 25 — 8.5 Metadata, repository and retrieval

**Action title:** Metadata decides what can be found later and cannot be cheaply retrofitted.

| Panel | Content |
| --- | --- |
| Aim | Make content searchable, retrievable, viewable and correctly secured for partner, business, audit and operations users. |
| Goals | Run metadata discovery workshops · Define search filters and retrieval needs · Map security keys, legal entity and RCC · Onboard repository and map metadata · Enable search and view APIs · Configure viewer · Provision access · Train users |
| Artifacts at exit | Metadata model and mappings · Configured repository · Search and view APIs · Viewer integration · Access grants · User manuals |
| Current BAU | Architects and business users design; engineering configures; onboarding resource owns access, demos and training with the UI team. |
| Impediments & challenges | Retrofitting metadata means reprocessing content · Mappings are a security control, not just data design · Adoption fails without training and manuals |
| Target state | Metadata & Retrieval Design sub-agent · Metadata Discovery Facilitation (SK-MD-01), Search Filter Definition (SK-MD-02), Security Key & Entity Mapping (SK-MD-03), Search and View API Enablement (SK-MD-05, 06), Access Provisioning (SK-MD-08), UI Demonstration Pack (SK-MD-09), User Manual Generation (SK-MD-10) |
| Thought process | Design-led work benefits most from guided structure (P2), not automation. Human retained: business users approve the metadata model. |

**Speaker notes:** Repository configuration follows metadata design, never the other way round. The agent structures workshops so the right questions are asked once.

### Slide 26 — 8.6 Records Management and retention

**Action title:** Retention is a business obligation enforced by configuration, not by documents.

| Panel | Content |
| --- | --- |
| Aim | Convert a business retention obligation into an approved, enforced retention configuration. |
| Goals | Gather retention requirements from the business owner · Draft RM questionnaire · Secure RM approval · Hand off to RM · Configure retention code, period, destruction policy · Enable regulatory WORM where applicable · Confirm legal hold and audit support |
| Artifacts at exit | Approved RM Onboarding Questionnaire · Configured retention schedules · Regulatory storage compliance |
| Current BAU | Onboarding resource gathers and drafts; RM reviews, approves and configures. |
| Impediments & challenges | Requirement must come from the accountable business owner, not be inferred · RM approval is a gate often chased by hand · Regulated storage discovered late invalidates repository design |
| Target state | Records & Retention sub-agent · Retention Requirement Gathering (SK-RM-01), RM Questionnaire Drafting (SK-RM-02), Review & Approval Tracking (SK-RM-03), Retention Code Advisory (SK-RM-04), Configuration Handoff (SK-RM-05), Regulatory Storage Check (SK-RM-06), Legal Hold Support (SK-RM-07), Destruction Policy Advisory (SK-RM-08) |
| Thought process | The questionnaire is generated from what was captured at intake, so RM reviews instead of re-asking. Human retained: Records Management decides the retention position. |

**Speaker notes:** In the AGRIA case this meant a defined retention code, a ten-year period and write-once-read-many storage, all of which were knowable at intake.

### Slide 27 — 8.7 Capacity engineering and SPLI

**Action title:** Load testing is volume-driven, and its tickets must land in the right project.

| Panel | Content |
| --- | --- |
| Aim | Prove the design holds at migration, business-as-usual and peak volumes, and scales for growth. |
| Goals | Collect three volume classes · Complete capacity planning · Decide if SPLI applies · Run SPLI and obtain approvals · Raise tickets against the allocated team's project · Validate scalability |
| Artifacts at exit | Capacity plan · SPLI applicability decision and approval · Correctly routed tickets |
| Current BAU | Onboarding resource collects volumes and raises tickets; engineering plans capacity; SPLI team assesses. |
| Impediments & challenges | Migration is a one-time peak often missed in sizing · Testing skipped when needed, or run when not · Tickets raised in the intake project are invisible to the team that must act |
| Target state | Volume Assessment + Load Testing sub-agents · Volume Class Modelling (SK-CP-02), Load Testing Applicability (SK-CP-06), Engagement Request (SK-CP-07), Approval Tracking (SK-CP-08), Scalability Checklist (SK-CP-10), Ticket Routing Guard (SK-XC-03) |
| Thought process | Apply the volume thresholds as a rule and refuse to create a ticket where the project cannot be resolved. Human retained: SPLI team approval. |

**Speaker notes:** The Ticket Routing Guard never defaults or guesses. A ticket it cannot route correctly is a ticket it does not create, which is better than one nobody sees.

### Slide 28 — 8.8 Testing

**Action title:** Each test cycle catches a different failure class; skipping one moves it to production.

**Copilot prompt addition:** Show the five test types as a left-to-right funnel of failure classes, then the seven panels below it.

| Panel | Content |
| --- | --- |
| Aim | Prove the solution works, matches intake objectives, holds at volume and reconciles on failure. |
| Goals | Unit testing (component defects) · Integration testing (mismatches between independently configured systems) · UAT (gap between build and intake objectives) · SPLI where applicable (volume failures) · End-to-end reconciliation (success and failure paths) · Continuous defect and conflict resolution |
| Artifacts at exit | Test evidence per cycle · UAT sign-off · Resolved defects · Production-readiness validation |
| Current BAU | Engineering, partner and business users test; onboarding resource brokers defect and conflict resolution across sides. |
| Impediments & challenges | Config mismatches surface late in integration testing · Failure paths assumed rather than proven · Defect routing depends on one person's knowledge of both sides |
| Target state | Test Orchestration sub-agent · Integration Test Plan (SK-TE-02), Reconciliation Test Design (SK-TE-03), UAT Plan & Sign-Off Tracking (SK-TE-04), Load Test Support (SK-TE-05), Defect Triage & Routing (SK-TE-06), Configuration Conflict Detection (SK-TE-07), Production Readiness Validation (SK-TE-08) |
| Thought process | Detect configuration conflicts before integration testing finds them, and route defects with context. Human retained: business users give UAT sign-off. |

**Speaker notes:** UAT is the only test that closes the loop back to the objectives stated at intake, which is why the UAT plan is assembled from the intake record.

### Slide 29 — 8.9 Environment progression

**Action title:** The environment ladder is fixed; gates must be enforced, not remembered.

| Panel | Content |
| --- | --- |
| Aim | Promote the partner through every environment, each validating what the previous one cannot. |
| Goals | Progress through the fixed ladder with no skips · Use the correct service account per environment · Exclude the internal-only environment from partner progression · Confirm team allocation before full progression |
| Artifacts at exit | Promotion record per environment · Gate evidence |
| Current BAU | Engineering and onboarding resource promote; account and gate rules applied from memory. |
| Impediments & challenges | Wrong environment account fails late and confusingly · Skip requests under schedule pressure · No allocated team limits the partner to the first environment |
| Target state | Environment Progression sub-agent · Environment Gate Check (SK-TE-09), Promotion Ladder Enforcement (SK-TE-10), Delivery Team Allocation Check (SK-TE-11), Environment Account Validation (SK-TE-12), Environment Account Mapping (SK-FS-08) |
| Thought process | The ladder is a rule; the agent refuses skips and explains what the skipped environment validates. Human retained: release and engineering approvals. |

**Speaker notes:** This is where Stage 7 becomes a hard gate: team allocation decided in planning determines how far delivery can physically go.

### Slide 30 — 8.10 Documentation and operational readiness

**Action title:** Readiness documents become generation work once the onboarding record exists.

| Panel | Content |
| --- | --- |
| Aim | Produce the evidence and documentation that let others support and audit the solution. |
| Goals | Keep Apigee and Kafka trackers current · Produce technical design and technology notes · Produce user guides and runbooks · Complete Release Transition documentation · Obtain technical and business validation sign-offs |
| Artifacts at exit | Current trackers · Technical design docs · Runbooks and user guides · Technical and business sign-offs |
| Current BAU | Onboarding resource and architects assemble documents by hand from information scattered across the lifecycle. |
| Impediments & challenges | Same facts re-typed into multiple documents · Trackers drift from reality · Sign-offs chased individually |
| Target state | Release Readiness sub-agent · Technical Design Documentation (SK-RL-07), Operational Runbook Generation (SK-RL-08), Tracker Maintenance (SK-AK-05, SK-AK-13), Sign-Off Tracking (SK-RL-04), Artefact Index (SK-XC-07) |
| Thought process | Write facts once into the onboarding record and generate every document from it. Human retained: sign-off holders. |

**Speaker notes:** Runbooks are what let Platform Support operate a solution it did not build. Generating them from the configuration record makes them accurate by construction.

## Stage 9 and current-state synthesis (slides 31–32)

Stage 9 transfers ownership to people who did not build the solution; the synthesis slide then shows leadership where the five failure types concentrate across all stages.

### Slide 31 — Stage 9: Partner Live

**Action title:** Go-live is a transfer of ownership, and gaps become support incidents.

| Panel | Content |
| --- | --- |
| Aim | Move the solution from the project team that knows it to a support organisation that does not. |
| Goals | Create and finalise the Release Transition page · Confirm UAT sign-off and support readiness · Confirm all deployed changes are in the handoff · Obtain go-live sign-offs · Deploy and support release night · Attend deployment validation call · Verify final production call · Hand over to Platform Support |
| Artifacts at exit | Release Transition page · Production deployment · Validated operation · Completed support handover · Exit: final production call verified |
| Current BAU | Onboarding resource accountable; Platform Support, Delivery Management, Cloud and Hosting Engineering and partner support. |
| Impediments & challenges | Transition page assembled by hand; completeness matters more than length · Production-specific failures need the builders still engaged · Sign-offs tracked individually · Anything deployed but unknown to support becomes an incident |
| Target state | Release Readiness sub-agent · Release Transition Page Generation (SK-RL-01), Completeness Check (SK-RL-02), Support Readiness Checklist (SK-RL-03), Sign-Off Tracking (SK-RL-04), Validation Call Brief (SK-RL-05), Release-Night Runbook (SK-RL-06), Handover Pack (SK-RL-09), Post-Go-Live Validation (SK-RL-10) |
| Thought process | The transition page is generated from the onboarding record and checked against what each support team needs. Human retained: named sign-off holders authorise go-live; the agent blocks progression without them. |

**Speaker notes:** A solution that passes UAT can still fail on production specifics, and the people who can diagnose it in minutes are the ones who built it. The onboarding resource stays engaged through validation by design; the agent prepares the brief so that time is spent diagnosing, not reconstructing.

### Slide 32 — Current-state synthesis: impediment heatmap

**Action title:** Five failure types repeat across the lifecycle, and all are addressable by design.

**Copilot prompt:**

> Create a heatmap table: rows are the five failure types, columns are Stages 1–9. Shade cells dark red where the failure type is a primary issue (●) and light red where it is secondary (○); leave blank otherwise. Add a right-hand column "Design response" naming the Onboard360AI mechanism. Label the slide footnote: "Qualitative assessment from the current-state process analysis; to be validated by the baseline measurement."

**On-slide content:**

| Failure type | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 | S9 | Design response |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Context lost at handoff | ○ | ○ | ○ | ● | ○ | ○ | ● | ● | ● | Onboarding record and carry-forward (SK-XC-01, 04, 07) |
| Rules that fail silently |  | ● |  | ● | ○ |  | ● | ● | ○ | Encoded rules and guards (SK-XC-03, SK-FS-07, SK-TE-10, SK-TR-06) |
| Invisible waiting | ○ | ● | ○ | ● |  | ● | ○ | ● | ○ | Ageing, nudges, notifications (SK-TR-08, SK-FS-12, SK-XC-06, 11) |
| Decisions not prepared for | ● | ○ | ○ | ● |  |  | ○ | ● |  | Governance liaison (SK-IN-13, SK-CN-12 to 14) |
| Manual re-assembly of known facts | ● | ○ | ● | ○ | ● | ● | ○ | ● | ● | Generation from the record (SK-PL-04, SK-RM-02, SK-RL-01) |

**Speaker notes:** This is the bridge from problem to solution. Every red cell maps to a named mechanism in the target state. None of the mechanisms replace a human decision; they remove rework, waiting and re-derivation around those decisions.

## Section 6 — Proof: RIA Platform (AGRIA) worked use case (slides 33–34)

AGRIA proves the pattern: one partner application, two document paths, nine stages, ten workstreams, five team groups and about a dozen systems, with every routing rule and approval path exercised at least once.

### Slide 33 — Worked use case: RIA Platform (AGRIA)

**Action title:** One partner, two document paths, almost the entire ICMP capability surface.

**Copilot prompt:**

> Create a case-study slide. Top-left: a fact card for the partner. Top-right: an orange callout "One onboarding, not two". Bottom: two horizontal flow diagrams stacked, labelled "Untrusted: FinTech agreements" and "Trusted: billing records", each drawn as connected boxes with arrows. Bottom-right: five expected business outcomes as small check-mark bullets.

**On-slide content:**

| Attribute | Value |
| --- | --- |
| Partner application | RIA Platform (AGRIA), wealth platform for Registered Investment Advisors |
| Business Application ID | APM0009695 |
| Zone | Publicly Accessible Application (PAA) |
| Integration route | ICMP API services through the Apigee gateway |
| Document paths | Two: one untrusted, one trusted |

Untrusted flow: AGRIA portal → DCT virus scan → iDocs AI classification → IRM human-in-the-loop (only when needed) → Apigee → ICMP → Kafka notifications → AGRIA reconciles.

Trusted flow: billing application → AGRIA → event-based ingestion → regulated ICMP repository (retention code, 10-year period, WORM) → search and view APIs for AGRIA, internal and audit users.

One onboarding, not two: billing sits inside AGRIA, so one application identity needs both a trusted and an untrusted profile. Splitting it duplicates intake, security analysis and capacity conversations.

Outcomes: end manual email-based archival · meet regulatory retention · automated reconciliation · audit, legal hold and RM support · a reusable onboarding pattern for future partners.

**Speaker notes:** Today FinTech agreements arrive by email and are uploaded by hand through the ICMP interface. The target automates ingestion, applies retention and reconciles through events. This case touches almost every specialist team, which is why it is a good test of the design.

### Slide 34 — What AGRIA demonstrates

**Action title:** The work is highly structured but not automated; decisions are few.

**Copilot prompt:**

> Create a three-column insight slide, each column with an icon, a bold headline and two supporting lines. Under the columns, add a strip showing examples of "Rules that can be written down" on the left and "Genuine decisions" on the right, with a human-decision icon on the right side.

**On-slide content:**

1. **Structured, not automated** — almost every activity follows a rule that is known and written down, applied by people from memory one onboarding at a time.
2. **A few genuine decisions** — the Imaging Governance determination needs a team to view documents and decide; the procedure around it can still be prepared, tracked and carried forward.
3. **Variable content, fixed shape** — the next partner differs in document types, volumes, retention codes and objectives, not in stages, workstreams, artifacts or routing.

Rules examples: which access route applies to which request type · which project a ticket belongs to · which profile a document path needs · whether load testing is warranted at a given volume.

Decisions examples: trusted vs untrusted · category/type/subtype allocation · retention position · capacity commitment · go-live authorisation.

**Speaker notes:** Stable procedure plus variable input is exactly the profile that benefits from agent-assisted execution rather than wholesale replacement. This is the hinge of the deck: from here we show the design.

## Section 7 — Target state: Onboard360AI on iDocs Canvas (slides 35–42)

The target state introduces Onboard360AI as an orchestrating sub-agent that holds the onboarding record, routes to 19 goal-bearing sub-agents and invokes 138 skills across 12 domains. Use purple as the dominant colour for this section.

### Slide 35 — Target-state vision

**Action title:** Onboard360AI externalises the onboarding's memory and enforces its rules.

**Copilot prompt:**

> Create a before-and-after slide. Left half "Today" in grey: one person icon at the centre with lines to nine stage tiles, labelled "Context held in one person's memory". Right half "With Onboard360AI" in purple: a central "Onboarding record" hub connected to the same nine stage tiles, with the person icon beside it labelled "Focuses on judgement and partner outcomes". Add three outcome chips under the right half.

**On-slide content:** Outcome chips: Context externalised, not remembered · Rules enforced, not recalled · Decisions prepared for, not waited on.

**Speaker notes:** The role does not go away; it becomes more valuable. The agent holds what was agreed, what is outstanding and who owes what, so the onboarding survives a handover, an absence or a reassignment without loss.

### Slide 36 — Platform architecture: from iDocs Canvas to skills

**Action title:** Onboard360AI sits under the existing Platform Specialist Agent on iDocs Canvas.

**Copilot prompt:**

> Create a layered architecture diagram with six stacked horizontal layers, top to bottom, each with a one-line role description on the right. Highlight the Onboard360AI layer in bold purple and label it "New". Show the sub-agent and skill layers as many small boxes to suggest breadth.

**On-slide content:**

| Layer | Role |
| --- | --- |
| iDocs Canvas | Enterprise document intelligence platform: runtime, tool surface, conversational interface, governance controls |
| Tachyon SDK | Config-driven runtime composition; local and MCP tools; pre- and post-condition contracts on every invocation |
| Platform Specialist Agent | Existing agent for platform-level assistance |
| Onboard360AI — Master Onboarding Agent (new) | Owns the onboarding journey end to end, routes to sub-agents, holds onboarding state |
| Sub-agents (19) | Goal-bearing components, each owning an outcome |
| Skills (138) | Single procedures, rule sets or knowledge domains that return a result |

**Speaker notes:** We build on an existing platform and agent, not a new stack. Config-driven composition means sub-agents and skills are assembled from configuration and can be versioned and tested independently.

### Slide 37 — The governing design rule: sub-agent or skill

**Action title:** Goals become sub-agents; rules and knowledge become reusable skills.

**Copilot prompt:**

> Create a decision-tree slide: one question box "Does the component own an outcome and choose between courses of action?" with a Yes branch to "Sub-agent" and a No branch to "Skill". Under each, one worked example. Add a footer of three benefits of small skills.

**On-slide content:** Sub-agent example: "Get this partner through foundational setup." Skill example: "Determine which access route applies to this request type." Benefits: skills are small and testable · reused across sub-agents · independently versionable, so a rule is written once and called everywhere.

**Speaker notes:** This rule keeps the design maintainable. When access routing changes, one skill changes, and every sub-agent that calls it picks up the change.

### Slide 38 — Integration maturity P1–P3 and runtime disclosure

**Action title:** Every skill declares its integration level and says so before it acts.

**Copilot prompt:**

> Create a three-step staircase graphic rising left to right, labelled P1, P2, P3, each with a name and what the agent can do. Above the staircase, add a purple banner "Runtime disclosure rule" with one sentence.

**On-slide content:**

| Phase | Level | What the agent can do |
| --- | --- | --- |
| P1 | Link | Points the user to the authoritative Confluence or knowledge base page |
| P2 | Read and guide | Reads the source and guides the user step by step; writes to no system |
| P3 | Direct integration | Calls the target system through MCP or API; reads live state and acts where authorised |

Disclosure rule: every agent and skill states at the start what is integrated today and what the next phase adds, so no user assumes an action was performed when it was only described.

**Speaker notes:** This prevents over-promising. At P2 the user knows they are the one who will click the button. It also lets us ship value early at P1 and P2 while P3 integrations are negotiated with system owners.

### Slide 39 — Sub-agent roster mapped to stages

**Action title:** Nineteen sub-agents cover every stage; eight form the MVP1 baseline.

**Copilot prompt:**

> Create a matrix slide: rows are the 19 sub-agents, columns are Stages 1–9, with a filled dot where the sub-agent serves a stage. Shade the 8 MVP1 rows in solid purple and the 11 extension rows in light purple. Add a legend. If it does not fit, split into two slides: "MVP1 baseline" and "Extension for full lifecycle".

**On-slide content:**

| Sub-agent | Stages | Tier |
| --- | --- | --- |
| POC Assistance | 1, 4 | MVP1 |
| Intake Verification | 2 | MVP1 |
| Foundational Setup | 8 | MVP1 |
| Volume Assessment | 4, 7, 8 | MVP1 |
| Load Testing | 8 | MVP1 |
| Apigee Subscription | 8 | MVP1 |
| Postman Collection Generation | 8 | MVP1 |
| Environment Progression | 8 | MVP1 |
| Intake Authoring Assistance | 1 | Extension |
| Triage Classification | 2, 4 | Extension |
| Prioritisation Support | 3 | Extension |
| Epic & Feature Composition | 5, 6 | Extension |
| KEES Enablement | 8 | Extension |
| Imaging Governance Liaison | 1, 4, 8 | Extension |
| Content Processing Configuration | 4, 8 | Extension |
| Records & Retention | 4, 8 | Extension |
| Metadata & Retrieval Design | 8 | Extension |
| Test Orchestration | 8 | Extension |
| Release Readiness | 9 | Extension |

**Speaker notes:** MVP1 concentrates on Stage 8 because that is where lead times and routing errors cost most. The extension set closes the front of the flow, where incomplete work creates the most downstream cost.

### Slide 40 — Skills catalogue: 138 skills, 12 domains

**Action title:** One hundred thirty-eight skills in twelve domains, each reusable and phase-tagged.

**Copilot prompt:**

> Create a slide with twelve domain tiles in a 4×3 grid. Each tile shows the domain letter, name, skill count as a large number, and the primary sub-agents served in small text. Make the Cross-Cutting tile visually distinct and label it "Foundation". Add a total of 138 in the bottom-right.

**On-slide content:**

| Domain | Skills | Primary sub-agents |
| --- | --- | --- |
| A · Intake and DOR (SK-IN) | 13 | Intake Authoring; POC Assistance |
| B · Intake Verification and Triage (SK-TR) | 11 | Intake Verification; Triage Classification |
| C · Prioritisation and Planning (SK-PL) | 10 | Prioritisation Support; Epic & Feature Composition |
| D · Volume, Capacity, Load Testing (SK-CP) | 10 | Volume Assessment; Load Testing |
| E · Foundational Setup, Access, Security (SK-FS) | 13 | Foundational Setup; POC Assistance |
| F · Gateway and Event Enablement (SK-AK) | 13 | Apigee; Postman; KEES |
| G · Content Processing and Classification (SK-CN) | 16 | Content Processing; Imaging Governance Liaison |
| H · Records Management and Retention (SK-RM) | 8 | Records & Retention |
| I · Metadata, Repository, Retrieval (SK-MD) | 10 | Metadata & Retrieval Design |
| J · Testing, Defects, Environments (SK-TE) | 12 | Test Orchestration; Environment Progression |
| K · Release Readiness and Handover (SK-RL) | 10 | Release Readiness |
| L · Cross-Cutting (SK-XC) | 12 | All sub-agents and the orchestrator |

**Speaker notes:** Reuse is deliberate. Access Route Determination, Ticket Routing Guard and Determination Carry-Forward are called by many sub-agents. The full skill list is in appendix slide A2.

### Slide 41 — Skills by user type

**Action title:** Each user sees only the skills that match their role and authority.

**Copilot prompt:**

> Create a persona slide with nine persona cards in a 3×3 grid. Each card shows the persona name, what they come to do, and 2–3 representative skills. Make the Partner Onboarding Resource card larger and labelled "Primary persona — sees every domain". Mark the Imaging Governance card with the human-decision icon.

**On-slide content:**

| Persona | Comes to | Representative skills |
| --- | --- | --- |
| Partner / requestor | Understand onboarding, build a complete intake | Journey Explainer, DOR Walkthrough, Completeness Pre-Check, Status View |
| ECM intake team (L4/L3 PMs) | Validate, open triage, compose epic | Completeness Validation, Participant Identification, Epic Draft |
| Triage leads | Derive routing, complete triage | Area/Impact Derivation, Triage Completion Field Set |
| LOB sponsors | Rank demand on evidence | Priority Evidence Pack, Regulatory Driver Summary |
| Partner Onboarding Resource | Run the whole journey | Every domain |
| Engineering and enabling | Build on confirmed determinations | Determination Carry-Forward, Conflict Detection, Gate Check |
| Imaging Governance | Make the determination | Submission Pack, Taxonomy Lookup, Classification Registration |
| Specialist teams | Their own workstream | RM, classification, HITL, Kafka, gateway, load testing, security skills |
| Platform Support | Accept and operate | Completeness Check, Handover Pack, Runbooks |

**Speaker notes:** The requestor never sees skills that write to platform systems. Imaging Governance sees only what it needs to decide: the documents on the flow, path context and the taxonomy, not the delivery procedure.

### Slide 42 — Why the orchestrator carries state

**Action title:** Determinations made early drive work stages later; one component must hold them.

**Copilot prompt:**

> Create a flow slide showing four upstream determinations on the left, each with an arrow running across the 9-stage strip to the downstream decisions it drives on the right. Place a central purple box "Onboard360AI onboarding record" through which every arrow passes. Add a red footnote: "Without it, a downstream step acts on an assumption the upstream stage never confirmed."

**On-slide content:**

| Determination | Made at | Drives |
| --- | --- | --- |
| Volume profile | Stage 1, refined at 4 | Capacity plan and SPLI decision (Stage 8.7), ingestion design (8.3) |
| Governance determination and classification | Stage 4 | Content profiles (8.4), retention keying (8.6), search filters (8.5) |
| Retention and regulatory position | Stage 4 | Repository choice and WORM (8.5, 8.6) |
| Delivery team allocation | Stage 7 | Ticket routing (8.7) and how far the environment ladder can go (8.9) |

**Speaker notes:** This is why the orchestrator is not just a router. It carries determinations forward and stops a downstream sub-agent from acting on anything unconfirmed. This is precisely the context that today lives in one person's working memory.

## Section 8a — Governance and the benefit case (slides 43–45)

These three slides answer the two questions leadership will ask first: what stops the agent overreaching, and where exactly the benefit comes from.

### Slide 43 — Governance rules encoded as skills

**Action title:** Ten rules that fail silently today become rules the platform enforces.

**Copilot prompt:**

> Create a two-column table slide titled with the action title. Left column "Rule", right column "How it is enforced". Add a small shield icon beside each rule. Add a purple banner at the bottom: "Converting a rule that must be remembered into a rule that is enforced is the single highest-value part of this design."

**On-slide content:**

| Rule | How it is enforced |
| --- | --- |
| Ticket routing | SK-XC-03 resolves the project per ticket type; refuses rather than guesses |
| Access routing | SK-FS-07 routes by request type, called first by every access skill |
| Environment accounts | SK-FS-08 and SK-TE-12 ensure the right account; internal-only environment excluded |
| Promotion ladder | SK-TE-10 refuses skips; SK-TE-11 applies first-environment-only without a team |
| Triage completion | SK-TR-06 completes all edits atomically |
| Determination integrity | SK-XC-04 carries confirmed upstream facts forward |
| Governance precedence | SK-CN-14 is the only source of the determination; SK-IN-05 is labelled provisional |
| New type re-review | SK-CN-16 routes new document types back to Imaging Governance |
| Disclosure | SK-XC-05 states the integration phase before any interaction |
| Auditability | SK-XC-08 records every action, the authorising rule and the approving human |

**Speaker notes:** Every one of these rules exists and is known today. They fail because they are applied from memory, and they fail silently, surfacing days later as a request in the wrong queue or a ticket nobody can see.

### Slide 44 — Human authority and approval

**Action title:** Onboard360AI assists and enforces; named humans keep every consequential decision.

**Copilot prompt:**

> Create a RACI-style slide with three columns: "Decision", "Who decides" (with the human-decision icon) and "What the agent does". Use eight rows. Add a bold banner across the top: "The agent does not approve."

**On-slide content:**

| Decision | Who decides | What the agent does |
| --- | --- | --- |
| Is the demand worth doing | LOB sponsor | Assembles evidence; does not rank |
| Is the intake complete enough | ECM intake team | Validates and reports; marginal calls stay human |
| Trusted vs untrusted | Imaging Governance, viewing documents on the flow | Prepares submission, confirms samples, tracks, registers outcome |
| Category, type, subtype (trusted) | Imaging Governance | Supplies taxonomy, records allocation, keys configuration to it |
| Retention position | Records Management, on the business owner's requirement | Drafts questionnaire, tracks approval |
| Capacity commitment | Enabling and engineering teams | Assembles request, resolves routing |
| Security and access approval | Security teams via existing tooling | Routes correctly, tracks; does not grant |
| Go-live authorisation | Named sign-off holders | Tracks sign-offs; blocks progression without them |

**Speaker notes:** This slide is the answer to risk and audit questions. Every action the agent takes is recorded with the rule that authorised it and the human who approved it.

### Slide 45 — Where the benefit comes from

**Action title:** The benefit comes from removing rework and waiting, not replacing judgement.

**Copilot prompt:**

> Create a slide with five horizontal benefit bars, each with an icon, a headline, a one-line mechanism, and the enabling skill IDs in small grey text. Add a right-hand panel "How we will prove it" with two lines. Do not add any numbers.

**On-slide content:**

| Effect | Mechanism | Enabling skills |
| --- | --- | --- |
| Context externalised, not remembered | Onboarding record survives handover, absence, reassignment | SK-XC-01, 04, 07 |
| Rules enforced, not recalled | Removes a whole class of misrouting rework | SK-XC-03, SK-FS-07, SK-TE-10, SK-TR-06 |
| Waiting made visible | Every wait is aged and owned, the precondition for reducing it | SK-TR-08, SK-FS-12, SK-XC-06, 11 |
| Decisions prepared for, not waited on | Samples ready, submission complete, decision tracked and registered | SK-IN-13, SK-CN-12, 13, 14 |
| Precedent reused | Comparable onboardings shorten discovery and reduce variance | SK-XC-12 |

How we will prove it: effort (person-days per team per stage) and elapsed time (calendar days per stage), baseline vs post-deployment: `[baseline]`.

**Speaker notes:** We separate two claims on purpose: making people faster, and removing time spent waiting. They need different evidence, and most of this design targets the waiting.

## Section 8b — Roadmap, measurement, risks and the ask (slides 46–50)

The close asks leadership for a bounded first decision, Wave 1 plus a baseline study, rather than funding all 138 skills at once. Slides 48–50 are proposed framing built on the source document; adjust owners and timing before presenting.

### Slide 46 — Build sequencing: five waves

**Action title:** Build the foundation first, then the highest-volume and longest-lead work.

**Copilot prompt:**

> Create a roadmap slide with five chevrons in sequence, Wave 1 to Wave 5. Under each chevron, show the focus and a one-line rationale. Mark Wave 1 as "Decision today". Inside Wave 4, add a small purple flag "Pull forward governance liaison skills SK-CN-12 to 16". Do not add dates.

**On-slide content:**

| Wave | Focus | Rationale |
| --- | --- | --- |
| 1 | Cross-cutting skills SK-XC-01 to 05 + 8 MVP1 sub-agents | Onboarding state, carry-forward, routing guards and disclosure underpin everything |
| 2 | Intake and triage (SK-IN, SK-TR) | Highest volume, most repetitive, clearest rules, biggest downstream cost of gaps |
| 3 | Foundational setup, gateway, events (SK-FS, SK-AK) | Longest lead times; routing errors most expensive; early P3 candidates |
| 4 | Content, records, metadata (SK-CN, SK-RM, SK-MD) | Design-led; benefits most from P2 guidance; pull governance liaison forward |
| 5 | Testing, progression, release (SK-TE, SK-RL) | Depends on everything upstream; release readiness becomes generation work |

**Speaker notes:** The catalogue describes the full target and should not be built in one pass. Each wave proves the procedural layer before integration-heavy work begins.

### Slide 47 — What must be measured first

**Action title:** Without a current-state baseline, no benefit claim can be defended.

**Copilot prompt:**

> Create a slide with a two-bar illustrative diagram per stage showing "Effort (person-days)" as a short bar inside a longer "Elapsed (calendar days)" bar, with the gap labelled "Waiting". Use placeholder values only and label them "illustrative". Beside it, list what to measure and the data source.

**On-slide content:**

- Measure: person-days per team per stage, and elapsed calendar days from stage entry to exit.
- Source: completed intakes, not estimates.
- Why: the gap between effort and elapsed is where the waiting sits, and waiting is what most of this design targets.
- Values: `[baseline]` for all stages until the study is complete.

**Speaker notes:** This is a prerequisite, not a formality. It lets us distinguish making people faster from removing time they spend waiting, which are different claims needing different evidence.

### Slide 48 — Delivery risks and mitigations

**Action title:** The main risks are integration access, over-trust and adoption, each with a mitigation.

**Copilot prompt:**

> Create a risk table slide with columns Risk, Impact, Mitigation built into the design. Use a red dot for each risk and a purple check for each mitigation.

**On-slide content:**

| Risk | Impact | Mitigation in the design |
| --- | --- | --- |
| P3 integrations delayed by system owners | Agent guides but cannot act | Phased P1/P2/P3 with runtime disclosure; value ships at P2 |
| Users treat a provisional view as the determination | Rework on assumed classification | SK-IN-05 labelled provisional; SK-CN-14 is the only source of truth |
| Agent action without accountable approval | Audit and control concern | Human authority model; SK-XC-08 audit trail on every action |
| Rules change and skills drift | Wrong routing enforced at scale | One skill per rule, independently versioned and tested |
| Low adoption by specialist teams | Record incomplete, benefit lost | Persona-scoped skills; each team sees only its workstream |
| No baseline | Benefit cannot be proven | Baseline study funded in the same decision as Wave 1 |

**Speaker notes:** Most risks are already addressed by design choices shown earlier. The open risk is integration access, which needs sponsorship from system owners.

### Slide 49 — The leadership ask

**Action title:** We ask for four decisions to start Wave 1 with measurable outcomes.

**Copilot prompt:**

> Create a decision slide with four numbered decision cards, each with a check-box icon, the decision in bold and one line of rationale. Add a footer: "Everything beyond Wave 1 returns for approval with baseline evidence."

**On-slide content:**

1. **Approve Wave 1** — cross-cutting skills SK-XC-01 to 05 and the 8 MVP1 sub-agents; the foundation everything else depends on.
2. **Fund the baseline study** — person-days and elapsed days per stage from completed intakes.
3. **Sponsor P3 integration access** — named owners for access tooling, identity management, Apigee, Kafka and the intake project.
4. **Confirm governance participation** — Imaging Governance and Records Management agree how determinations and approvals are registered.

**Speaker notes:** This is a bounded first step. It proves the onboarding record, the routing guards and disclosure on real onboardings before we extend to the full lifecycle.

### Slide 50 — Next 90 days

**Action title:** In 90 days we will have a baseline, a working foundation and a pilot onboarding.

**Copilot prompt:**

> Create a three-lane timeline across three 30-day blocks. Lanes: Measure, Build, Prove. Place each milestone as a diamond in its lane. Do not add calendar dates; use Days 0–30, 31–60, 61–90.

**On-slide content:**

| Lane | Days 0–30 | Days 31–60 | Days 61–90 |
| --- | --- | --- | --- |
| Measure | Select completed intakes; define data capture | Baseline effort and elapsed per stage | Publish baseline to sponsors |
| Build | Stand up onboarding record and cross-cutting skills | MVP1 sub-agents at P1/P2 | First P3 integrations where access is granted |
| Prove | Pick a pilot onboarding | Run pilot through Stage 8 workstreams | Report against baseline; Wave 2 proposal |

**Speaker notes:** The 90-day plan is proposed; owners and exact scope are confirmed once the decisions on slide 49 are taken.

## Appendix slides and final polish (A1–A3)

The appendix holds reference detail leadership may ask for; A2 and A3 are best built by pointing Copilot at the source Word document rather than retyping 138 skills.

### Slide A1 — Glossary

**Copilot prompt:**

> Create a two-column glossary slide (split across two slides if needed) using the terms below in alphabetical order. Body text 12 pt minimum.

**On-slide content:**

| Term | Meaning |
| --- | --- |
| ATL / ATL+ / BTL / TBD | Commitment indicators: above the line, above with extra confidence or scope, below the line, to be determined |
| BAU | Business as usual; also steady-state volume vs migration and peak |
| DOR | Definition of Ready workbook completed at Stage 1 |
| ECM / CMP | Enterprise content management / content management platform services |
| HITL | Human in the loop, invoked where AI classification cannot confirm |
| iDocs / iDocs Canvas | AI classification engine / enterprise document intelligence platform on Tachyon SDK |
| ICMP | Enterprise repository for archival, retention, search and retrieval |
| Imaging Governance | Decides trusted vs untrusted by viewing documents on the flow; allocates category, type, subtype |
| IRM | Iron Mountain human-in-the-loop validation and classification service |
| KEES | Kafka Enablement Engagement Services |
| MCP | Model Context Protocol, used for P3 direct integration |
| P1 / P2 / P3 | Integration phases: link, read and guide, direct integration |
| PAA | Publicly Accessible Application zone |
| RCC | Organisational mapping applied with legal entity and security keys |
| RM | Records Management |
| SPLI | System Performance Load Ingestion Testing |
| TS | Technical specification |
| WORM | Write once, read many regulated storage |

### Slide A2 — Skills catalogue detail by domain

**Copilot prompt:**

> Using the attached file "Partner\_Onboarding\_Current\_and\_Target\_State.docx", section 3.5, create one appendix slide per skill domain A to L. Each slide is a table with columns Skill ID, Skill name, What it does (shortened to 10 words), Phase (P1/P2/P3). Shade P3 rows purple, P2 rows light purple, P1 rows grey. Title each slide "Appendix A2 · Domain \[letter\] — \[name\] (\[n\] skills)".

**Speaker notes:** Use only if asked. The point to make: each skill does one thing, carries its integration phase, and many are reused across sub-agents.

### Slide A3 — Enabler user journey: skills by lifecycle point

**Copilot prompt:**

> Using section 3.6.5 of the attached source file, create one slide showing the Partner Onboarding Resource journey as a horizontal timeline with segments: Entry, Front of flow (Stages 1–4), Middle (Stages 5–7), Delivery foundational and access, Delivery gateway/events/content/records, Delivery testing and progression, Go-live (Stage 9). Under each segment list the skills invoked as small chips.

**Speaker notes:** The enabler user is the role the design is built around, and the only persona that spans every domain. This slide shows that their whole working journey is supported, not just isolated tasks.

### Final polish prompts

Run these once the deck is assembled:

> Review every slide title. Rewrite any title that is a topic label into an action title of at most 14 words that states the takeaway.

> Check the deck for consistent terminology: ICMP, Onboard360AI, Partner Onboarding Resource, Imaging Governance, sub-agent, skill, stage, workstream. List and fix any inconsistencies.

> Find any slide with more than 6 bullets or bullets longer than 12 words. Shorten them and move the removed detail into the speaker notes.

> Confirm no slide contains a number, cost or date that was not in my source content. Replace any invented figure with \[baseline\].

> Confirm that every slide mentioning the Imaging Governance determination states that it remains a human decision.
