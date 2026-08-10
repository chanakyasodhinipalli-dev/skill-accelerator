/* Session workspace: the conversation, what it has learned, and the artifact.
 *
 * The layout is the point. Chat on the left, the form's live state on the right.
 * A conversational intake tool that hides the field list asks people to trust
 * that their answers landed somewhere; showing the state as it fills — with the
 * evidence behind each value — is what makes it reviewable.
 */

import { api, download } from "../api.js";
import {
  badge,
  bar,
  card,
  clear,
  displayValue,
  el,
  field,
  modal,
  reportError,
  table,
  tabs,
  toast,
  withBusy,
} from "../ui.js";
import { state } from "../state.js";

const STATE_GLYPH = {
  confirmed: ["✓", "filled"],
  answered: ["✓", "filled"],
  proposed: ["?", "pending"],
  conflicted: ["!", "pending"],
  skipped: ["–", "empty"],
  empty: ["○", "empty"],
};

let context = null; // { sessionId, session, status, definition }

export async function render(root, params) {
  context = { sessionId: params.id };
  await load();

  root.append(el("div", { id: "session-head" }));
  root.append(
    el(
      "div",
      { class: "split" },
      el("div", { id: "session-left" }),
      el("div", { id: "session-right" }),
    ),
  );

  draw();
}

async function load() {
  const [session, status] = await Promise.all([
    api.get(`/forms/sessions/${context.sessionId}`),
    api.get(`/forms/sessions/${context.sessionId}/status`),
  ]);
  context.session = session;
  context.status = status;
  context.definition = await api.get(`/forms/${session.form_name}`, {
    version: session.form_version,
  });
}

async function refresh() {
  await load();
  draw();
}

function draw() {
  drawHead();
  drawLeft();
  drawRight();
}

// -- header -----------------------------------------------------------------

function drawHead() {
  const { session, status, definition } = context;
  const completeness = status.completeness ?? {};
  const percent = completeness.overall_percent ?? 0;
  const [answered, total] = String(completeness.mandatory ?? "0/0").split("/").map(Number);
  const [agreed, agreements] = String(completeness.agreements ?? "0/0").split("/").map(Number);

  // An agreement form has no fields, so a field-count progress bar sits at 100%
  // while nobody has agreed to anything. Measure it in what it is made of.
  const isAgreement = definition.kind === "agreement";
  const primary = isAgreement
    ? { label: `Agreed ${completeness.agreements ?? "—"}`, done: agreed, of: agreements }
    : { label: `Required ${completeness.mandatory ?? "—"}`, done: answered, of: total };
  const complete = isAgreement ? completeness.agreements_complete : completeness.mandatory_complete;

  clear(document.getElementById("session-head")).append(
    el(
      "div",
      { class: "page-head" },
      el("a", { href: "#/sessions", class: "muted", text: "← All sessions" }),
      el("h1", { text: session.title || definition.title }),
      el(
        "div",
        { class: "row" },
        badge(session.status, session.status === "collecting" ? "accent" : "ok"),
        isAgreement ? badge("agreement form", "accent") : null,
        el("code", { text: `${session.form_name}@${session.form_version}` }),
        el("span", { class: "muted", text: (session.participants ?? []).join(", ") }),
        complete ? badge(isAgreement ? "all agreed" : "required fields complete", "ok") : null,
        (completeness.agreements_declined ?? []).length
          ? badge(`${completeness.agreements_declined.length} declined`, "bad")
          : null,
      ),
    ),
    card(
      null,
      el(
        "div",
        { class: "spread" },
        el("div", {}, el("strong", { text: primary.label })),
        el("div", {
          class: "muted",
          text: isAgreement
            ? total
              ? `plus ${completeness.mandatory ?? "—"} identifying details`
              : "nothing else to fill in"
            : `${percent}% of all fields`,
        }),
      ),
      bar(primary.of ? (primary.done / primary.of) * 100 : 0, { done: complete }),
    ),
  );
}

// -- conversation -----------------------------------------------------------

function drawLeft() {
  const left = clear(document.getElementById("session-left"));
  const { session } = context;
  const locked = !(session.editable ?? session.status === "collecting");

  const log = el("div", { class: "chat-log" });
  for (const entry of session.transcript) {
    const role = entry.role === "user" ? "user" : entry.role === "assistant" ? "assistant" : "system";
    log.append(
      el(
        "div",
        { class: `bubble ${role}` },
        role === "system"
          ? null
          : el("div", {
              class: "bubble-meta",
              text: `${entry.author}${entry.channel && entry.channel !== "chat" ? ` · ${entry.channel}` : ""}`,
            }),
        el("span", { text: entry.text }),
      ),
    );
  }

  const input = el("textarea", {
    placeholder: locked
      ? "This session is locked. Reopen it to make changes."
      : "Answer in your own words — one message can settle several fields.",
    disabled: locked,
    "aria-label": "Your message",
  });

  async function send(text) {
    const message = (text ?? input.value).trim();
    if (!message) return;
    input.value = "";
    log.append(el("div", { class: "bubble user" }, el("span", { text: message })));
    log.scrollTop = log.scrollHeight;

    try {
      const result = await withBusy(log, () =>
        api.post(`/forms/sessions/${context.sessionId}/messages`, {
          message,
          author: state.participant,
          channel: "chat",
        }),
      );
      if (result.captured?.length) {
        toast(`Captured ${result.captured.length} field(s)`, {
          detail: result.captured.join(", "),
          tone: "success",
        });
      }
      if (result.conflicts?.length) {
        toast("Conflicting values recorded", { detail: result.conflicts.join(", "), tone: "error" });
      }
      await refresh();
    } catch (error) {
      reportError(error, "The message could not be processed");
    }
  }

  input.addEventListener("keydown", (event) => {
    // Enter sends; Shift+Enter is a newline. Matches every chat tool people
    // already use, and a form answer is rarely multi-paragraph.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  });

  const chat = el(
    "div",
    { class: "chat" },
    log,
    el(
      "div",
      { class: "composer" },
      input,
      el("button", { class: "primary", text: "Send", disabled: locked, onClick: () => send() }),
    ),
  );

  left.append(
    card(
      null,
      chat,
      el(
        "div",
        { class: "row", style: "margin-top:10px" },
        el("button", {
          class: "ghost",
          text: "Why do you need this?",
          disabled: locked,
          onClick: () => send("Why do you need that?"),
        }),
        // The two rungs of the help ladder that a person would otherwise have
        // to know to ask for. The first is answered from the form itself; the
        // second goes to whoever owns this part of it.
        el("button", {
          class: "ghost",
          text: "What does this mean?",
          disabled: locked,
          onClick: () => send("What do you mean by that?"),
        }),
        el("button", {
          class: "ghost",
          text: "Who can I ask?",
          disabled: locked,
          onClick: () => send("Who can I ask about this?"),
        }),
        el("button", {
          class: "ghost",
          text: "Where are we?",
          disabled: locked,
          onClick: () => send("Where are we up to?"),
        }),
        el("button", {
          class: "ghost",
          text: "Skip this one",
          // "Skip" is not one of the answers to a term. Offering it next to an
          // agreement invites a click that the engine will read as neither an
          // acceptance nor a refusal and simply put the agreement again.
          disabled: locked || (context.status.agreements?.awaiting ?? []).length > 0,
          onClick: () => send("Skip that one for now."),
        }),
        el("button", {
          class: "ghost",
          text: "I'll come back later",
          disabled: locked,
          onClick: () => send("I'll come back to this later."),
        }),
      ),
    ),
  );

  const consent = consentPanel(locked, send);
  if (consent) left.prepend(consent);

  // Nothing to mine a thread *for* on a form with no fields. The panel is the
  // largest thing on the screen and would be pure noise on an agreement form.
  if (context.definition.sections?.some((section) => section.fields?.length)) {
    left.append(ingestCard(locked));
  }
  // Show the newest turn without animating past the whole history.
  log.scrollTop = log.scrollHeight;
}

// -- consent ----------------------------------------------------------------

/** Agreements the conversation is waiting on, or null when it is not.
 *
 * The text comes from the form definition, not from the chat bubble it was
 * announced in: what somebody accepts here has to be the declared wording, and
 * reading it back out of a transcript would put a copy between the two.
 */
function consentPanel(locked, send) {
  const awaiting = context.status.agreements?.awaiting ?? [];
  if (!awaiting.length) return null;

  const declared = new Map((context.definition.agreements ?? []).map((a) => [a.id, a]));
  const pending = awaiting.map((id) => declared.get(id)).filter(Boolean);
  if (!pending.length) return null;

  const body = el("div", { class: "consent" });
  for (const agreement of pending) {
    body.append(
      el(
        "div",
        { class: "consent-item" },
        el(
          "div",
          { class: "row tight" },
          el("strong", { text: agreement.title }),
          badge(agreement.kind, agreement.kind === "user" ? "accent" : ""),
          agreement.required ? badge("required", "warn") : badge("optional"),
          el("span", { class: "muted", text: `v${agreement.version ?? "1.0.0"}` }),
        ),
        el("p", { class: "consent-text", text: agreement.text }),
      ),
    );
  }

  // All of them in one request. Looping over the single endpoint makes each
  // acceptance announce the next term, so accepting two produced a transcript
  // that put the second agreement to the participant and then accepted it on
  // their behalf a moment later, with nobody having said anything in between.
  async function decide(chosen, accept, node) {
    try {
      await withBusy(node, () =>
        api.post(`/forms/sessions/${context.sessionId}/agreements`, {
          agreement_ids: chosen.map((a) => a.id),
          accept,
          actor: state.participant,
          stated: accept ? "Accepted in the console." : "Declined in the console.",
        }),
      );
      const what = chosen.length === 1 ? chosen[0].title : `${chosen.length} agreements`;
      toast(accept ? `Accepted: ${what}` : `Declined: ${what}`, {
        tone: accept ? "success" : "error",
        detail: "Recorded against this submission with the exact wording shown.",
      });
      await refresh();
    } catch (error) {
      reportError(error, "That decision could not be recorded");
    }
  }

  const single = pending.length === 1;
  body.append(
    el(
      "div",
      { class: "row", style: "margin-top:12px" },
      el("button", {
        class: "primary",
        text: single ? "I agree" : "I agree to all of these",
        disabled: locked,
        onClick: (event) => decide(pending, true, event.target),
      }),
      // A refusal is a recorded outcome, not a dead end — so it is a button,
      // not something someone has to argue their way to in prose. With more
      // than one term on the table it has to be attributed, so that goes back
      // to the conversation rather than guessing which one they meant.
      single
        ? el("button", {
            class: "ghost",
            text: "I can't accept this",
            disabled: locked,
            onClick: (event) => decide([pending[0]], false, event.target),
          })
        : el("button", {
            class: "ghost",
            text: "I can't accept one of these",
            disabled: locked,
            onClick: () => send("I can't accept one of these."),
          }),
      el("button", {
        class: "ghost",
        text: "Ask about this first",
        disabled: locked,
        onClick: () => send("What does this mean, exactly?"),
      }),
    ),
  );

  return card(
    pending.length === 1 ? "Before we start" : "Before we start — a couple of things",
    el("p", {
      class: "hint",
      text: "Nothing is recorded against this submission until this is settled. The wording below is what gets stored, with your name and the time.",
    }),
    body,
  );
}

// -- ingestion --------------------------------------------------------------

function ingestCard(locked) {
  const holder = el("div", {});
  let current = "email_file";

  const CHANNELS = [
    { id: "email_file", label: "Email file" },
    { id: "jira", label: "JIRA" },
    { id: "email", label: "Email thread" },
    { id: "meeting", label: "Transcript" },
    { id: "document", label: "Document" },
  ];

  function drawPanel() {
    clear(holder).append(
      current === "email_file" ? emailFilePanel(locked) : textPanel(current, locked),
    );
  }

  const tabBar = tabs(CHANNELS, {
    selected: current,
    onSelect: (id) => {
      current = id;
      tabBar.querySelectorAll("button").forEach((button, index) => {
        button.setAttribute("aria-selected", String(CHANNELS[index].id === id));
      });
      drawPanel();
    },
  });

  drawPanel();
  return card(
    "Mine an existing discussion",
    el("p", {
      class: "hint",
      text: "Run this before answering anything. Quoted history and signatures are stripped, messages are processed oldest-first so later corrections win, and every value keeps a link back to who said it.",
    }),
    tabBar,
    holder,
  );
}

function emailFilePanel(locked) {
  const emailInput = el("input", { type: "file", accept: ".eml,message/rfc822" });
  const attachmentInput = el("input", { type: "file", multiple: true });
  const report = el("div", {});

  return el(
    "div",
    {},
    field("Email (.eml)", emailInput, "Save the mail as MIME. Outlook .msg is a different format and is rejected with an explanation."),
    field(
      "Extra attachments (optional)",
      attachmentInput,
      "Attachments inside the mail are read automatically. Add files here when a forward dropped them.",
    ),
    el("button", {
      class: "primary",
      text: "Ingest",
      disabled: locked,
      onClick: async (event) => {
        const [file] = emailInput.files;
        if (!file) {
          toast("Choose an .eml file first");
          return;
        }
        const body = new FormData();
        body.append("email", file);
        for (const attachment of attachmentInput.files) body.append("attachments", attachment);

        try {
          const result = await withBusy(event.target, () =>
            api.upload(`/forms/sessions/${context.sessionId}/ingest/email`, body),
          );
          clear(report).append(ingestReport(result));
          toast(`Mined ${result.messages_processed} message(s)`, {
            detail: `${(result.captured ?? []).length} field(s) captured`,
            tone: "success",
          });
          await refresh();
        } catch (error) {
          reportError(error, "That email could not be ingested");
        }
      },
    }),
    report,
  );
}

const PLACEHOLDERS = {
  jira: '{"key": "OPS-1421", "fields": {"description": "...", "comment": {"comments": []}}}',
  email: "Paste the mail chain, or a JSON array of {from, subject, body} objects.",
  meeting: "Alice: we're going on the 15th\nBen: rollback is a redeploy of 2.14",
  document: "Paste any document text.",
};

function textPanel(channel, locked) {
  const input = el("textarea", { class: "code", placeholder: PLACEHOLDERS[channel] });
  const report = el("div", {});

  return el(
    "div",
    {},
    input,
    el("button", {
      class: "primary",
      style: "margin-top:10px",
      text: "Ingest",
      disabled: locked,
      onClick: async (event) => {
        const raw = input.value.trim();
        if (!raw) return;
        let payload = raw;
        if (channel === "jira" || raw.startsWith("{") || raw.startsWith("[")) {
          try {
            payload = JSON.parse(raw);
          } catch {
            if (channel === "jira") {
              toast("That is not valid JSON", { tone: "error" });
              return;
            }
            payload = raw; // free text is fine for the other channels
          }
        }
        try {
          const result = await withBusy(event.target, () =>
            api.post(`/forms/sessions/${context.sessionId}/ingest`, { channel, payload }),
          );
          clear(report).append(ingestReport(result));
          toast(`Mined ${result.messages_processed} message(s)`, { tone: "success" });
          await refresh();
        } catch (error) {
          reportError(error, "That thread could not be ingested");
        }
      },
    }),
    report,
  );
}

function ingestReport(result) {
  const wrapper = el("div", { style: "margin-top:12px" });
  wrapper.append(
    el(
      "div",
      { class: "row" },
      badge(`${result.messages_processed} message(s)`),
      badge(`${(result.captured ?? []).length} captured`, "ok"),
    ),
  );
  if (result.email) {
    const attachments = result.email.attachments ?? [];
    wrapper.append(
      el("p", { class: "hint", text: `Subject: ${result.email.subject || "(none)"}` }),
      attachments.length
        ? table(
            [
              { label: "Attachment", render: (a) => a.filename },
              { label: "Type", render: (a) => a.content_type },
              {
                label: "Read",
                render: (a) =>
                  a.extracted
                    ? badge(`${a.characters} chars`, "ok")
                    : badge(a.note || "not read", "warn"),
              },
            ],
            attachments,
          )
        : el("p", { class: "hint", text: "No attachments." }),
    );
  }
  if (result.next_message) {
    wrapper.append(el("p", { class: "muted", text: result.next_message }));
  }
  return wrapper;
}

// -- form state -------------------------------------------------------------

/** The fields the last question covered — highlighted so the grouping is visible.
 *
 * Topics are computed from how fields relate, not from the section they were
 * filed in, so one question routinely covers two cards. Without this, that reads
 * as the assistant wandering; with it, you can see the group it chose.
 */
function currentlyAsked() {
  const transcript = context.session.transcript ?? [];
  for (let index = transcript.length - 1; index >= 0; index -= 1) {
    const entry = transcript[index];
    if (entry.role === "assistant" && entry.targeted_fields?.length) {
      return new Set(entry.targeted_fields);
    }
  }
  return new Set();
}

function askingCard(asked) {
  const { definition } = context;
  if (!asked.size) return null;

  const rows = [];
  for (const section of definition.sections) {
    for (const definitionField of section.fields) {
      if (asked.has(definitionField.id)) rows.push({ section, definitionField });
    }
  }
  if (!rows.length) return null;

  const sections = [...new Set(rows.map((row) => row.section.title))];
  return card(
    "Asking about now",
    el(
      "div",
      { class: "row tight" },
      ...rows.map((row) => badge(row.definitionField.label, "accent")),
    ),
    el("p", {
      class: "hint",
      text:
        sections.length > 1
          ? `Grouped across ${sections.join(" and ")} — these are one question to the person answering, whichever part of the form they were filed in.`
          : `All from ${sections[0]}.`,
    }),
  );
}

function drawRight() {
  const right = clear(document.getElementById("session-right"));
  const { session, status, definition } = context;
  const locked = !(session.editable ?? session.status === "collecting");
  const asked = currentlyAsked();

  const asking = askingCard(asked);
  if (asking) right.append(asking);

  for (const section of [...definition.sections].sort((a, b) => a.order - b.order)) {
    const list = el("ul", { class: "field-list" });
    for (const definitionField of section.fields) {
      const answer = session.answers[definitionField.id];
      const answerState = answer?.state ?? "empty";
      const [glyph, tone] = STATE_GLYPH[answerState] ?? STATE_GLYPH.empty;

      list.append(
        el(
          "li",
          { class: asked.has(definitionField.id) ? "asking" : null },
          el("span", { class: `field-state ${tone}`, text: glyph, title: answerState }),
          el(
            "div",
            { class: "field-body" },
            el(
              "div",
              { class: "row tight" },
              el("span", { class: "field-name", text: definitionField.label }),
              definitionField.importance === "mandatory" ? badge("required", "accent") : null,
              answerState === "proposed" ? badge("unconfirmed", "warn") : null,
              asked.has(definitionField.id) && answerState === "empty"
                ? badge("being asked", "warn")
                : null,
            ),
            el("div", {
              class: "field-value",
              text: definitionField.sensitive && answer?.value
                ? "[recorded — hidden]"
                : displayValue(answer?.value),
            }),
            // The typed text, shown beside the written-up version. Someone has
            // to be able to see what was changed on their behalf.
            answer?.polished && answer.raw_value
              ? el("div", { class: "hint", text: `as typed: ${answer.raw_value}` })
              : null,
            answer?.provenance
              ? el("div", {
                  class: "hint",
                  text: `${answer.provenance.author} · ${answer.provenance.channel} · confidence ${Math.round((answer.confidence ?? 0) * 100)}%`,
                })
              : null,
          ),
          el("button", {
            class: "ghost",
            text: "Edit",
            title: "Set this value directly",
            disabled: locked,
            onClick: () => editField(definitionField, answer),
          }),
        ),
      );
    }
    right.append(card(section.title, list));
  }

  // Cross-field findings sit above the action items: an outstanding one is a
  // question waiting on the owner, and a noted one carries the reason the
  // approver would otherwise have to chase.
  const findings = status.consistency ?? {};
  const outstanding = findings.outstanding ?? [];
  const noted = findings.noted ?? [];
  if (outstanding.length || noted.length) {
    const list = el("ul", {});
    for (const finding of outstanding) {
      list.append(
        el(
          "li",
          {},
          el(
            "div",
            { class: "row tight" },
            badge(finding.severity === "blocking" ? "blocks sign-off" : finding.severity, finding.severity === "blocking" ? "warn" : "accent"),
            el("span", { text: finding.message }),
          ),
          finding.evidence ? el("div", { class: "hint", text: finding.evidence }) : null,
        ),
      );
    }
    for (const finding of noted) {
      list.append(
        el(
          "li",
          {},
          el(
            "div",
            { class: "row tight" },
            badge("noted", "ok"),
            el("span", { class: "muted", text: finding.message }),
          ),
          finding.resolution ? el("div", { class: "hint", text: `“${finding.resolution}”` }) : null,
        ),
      );
    }
    right.append(card("Consistency", list));
  }

  const agreementsCard = agreementCard(locked);
  if (agreementsCard) right.append(agreementsCard);

  const questionsCard = questionCard(locked);
  if (questionsCard) right.append(questionsCard);

  const openItems = status.action_items ?? [];
  right.append(
    card(
      "Action items",
      openItems.length
        ? el(
            "ul",
            {},
            ...openItems.map((item) =>
              el(
                "li",
                {},
                el("span", { text: item.description }),
                item.owner ? el("span", { class: "muted", text: ` — ${item.owner}` }) : null,
              ),
            ),
          )
        : el("p", {
            class: "muted",
            text: "Derived when the document is produced, from commitments made in the conversation and any required field nobody closed.",
          }),
    ),
  );

  right.append(artifactCard(locked));
}

// -- agreements and questions on the record ---------------------------------

/** Every agreement this form declares and where each one stands.
 *
 * Both the decision and the words it was taken against are shown. A row saying
 * "accepted" with nothing to read is not evidence of anything, and it is the
 * text — not the tick — that an approver or an auditor needs.
 */
function agreementCard(locked) {
  const { status, definition } = context;
  const declared = definition.agreements ?? [];
  const decided = status.agreements?.decided ?? [];
  const outstanding = status.agreements?.outstanding ?? [];
  const awaiting = new Set(status.agreements?.awaiting ?? []);
  const blocking = new Set(status.agreements?.blocking ?? []);
  if (!declared.length && !decided.length) return null;

  const byId = new Map(declared.map((agreement) => [agreement.id, agreement]));
  const latest = new Map();
  for (const record of decided) latest.set(record.agreement_id, record);
  // Undecided is not the same as askable: a confirmation of accuracy is
  // undecided from the first turn and cannot honestly be taken until there is a
  // submission to confirm. The server says which are reachable; offering a
  // button for the rest would be offering an attestation to nothing.
  const pending = new Set(
    outstanding.filter((entry) => entry.decidable !== false).map((entry) => entry.id),
  );

  const list = el("ul", { class: "field-list" });
  for (const agreement of declared.length ? declared : decided.map((r) => byId.get(r.agreement_id))) {
    if (!agreement) continue;
    const record = latest.get(agreement.id);
    const accepted = record?.decision === "accepted";
    const glyph = record ? (accepted ? ["✓", "filled"] : ["!", "pending"]) : ["○", "empty"];

    list.append(
      el(
        "li",
        {},
        el("span", { class: `field-state ${glyph[1]}`, text: glyph[0] }),
        el(
          "div",
          { class: "field-body" },
          el(
            "div",
            { class: "row tight" },
            el("span", { class: "field-name", text: agreement.title }),
            badge(agreement.kind, agreement.kind === "user" ? "accent" : ""),
            record
              ? badge(accepted ? "accepted" : "declined", accepted ? "ok" : "bad")
              : awaiting.has(agreement.id)
                ? badge("awaiting reply", "warn")
                : badge(`due ${String(agreement.stage).replace(/_/g, " ")}`),
            blocking.has(agreement.id) ? badge("blocks the document", "bad") : null,
          ),
          // The wording, verbatim, from the record where there is one — an
          // agreement reworded on the form afterwards must not change what this
          // says was agreed to.
          el("div", { class: "consent-text", text: record?.text ?? agreement.text }),
          record
            ? el("div", {
                class: "hint",
                text: `${record.actor} · v${record.version} · ${new Date(record.decided_at * 1000).toLocaleString()}${record.stated ? ` · “${record.stated}”` : ""}`,
              })
            : null,
        ),
        // Only what is genuinely outstanding is decidable here. Re-deciding a
        // settled agreement from a side panel is not a thing anyone should be
        // able to do by mis-clicking.
        !record && pending.has(agreement.id) && !locked
          ? el(
              "div",
              { class: "row tight" },
              el("button", {
                class: "ghost",
                text: "Accept",
                onClick: (event) => decideAgreement(agreement, true, event.target),
              }),
              el("button", {
                class: "ghost",
                text: "Decline",
                onClick: (event) => decideAgreement(agreement, false, event.target),
              }),
            )
          : null,
      ),
    );
  }

  return card(
    "Agreements",
    el("p", {
      class: "hint",
      text: "Presented and stored word for word, hashed, and carried onto the document with who decided and when. Rewording one means a new version, and it is asked again.",
    }),
    list,
  );
}

async function decideAgreement(agreement, accept, node) {
  try {
    await withBusy(node, () =>
      api.post(`/forms/sessions/${context.sessionId}/agreements/${agreement.id}`, {
        accept,
        actor: state.participant,
        stated: accept ? "Accepted in the console." : "Declined in the console.",
      }),
    );
    toast(`${accept ? "Accepted" : "Declined"}: ${agreement.title}`, {
      tone: accept ? "success" : "error",
    });
    await refresh();
  } catch (error) {
    reportError(error, "That decision could not be recorded");
  }
}

/** Questions the participant asked, and what became of each.
 *
 * The open ones are why a field is empty. Without them on screen the gap reads
 * as something the owner forgot rather than something nobody could answer.
 */
function questionCard(locked) {
  const open = context.status.questions?.open ?? [];
  const answered = context.status.questions?.answered ?? [];
  if (!open.length && !answered.length) return null;

  const list = el("ul", { class: "field-list" });
  for (const request of open) {
    list.append(
      el(
        "li",
        {},
        el("span", { class: "field-state pending", text: "?" }),
        el(
          "div",
          { class: "field-body" },
          el("div", { class: "field-name", text: `“${request.question}”` }),
          el("div", {
            class: "hint",
            text: `with ${request.team}${request.contact ? ` (${request.contact})` : ""}${request.fields?.length ? ` · about ${request.fields.join(", ")}` : ""}`,
          }),
        ),
        locked
          ? null
          : el("button", {
              class: "ghost",
              text: "They came back",
              title: "Record what the team said and close the question",
              onClick: () => closeQuestion(request),
            }),
      ),
    );
  }
  for (const request of answered) {
    list.append(
      el(
        "li",
        {},
        el("span", { class: "field-state filled", text: "✓" }),
        el(
          "div",
          { class: "field-body" },
          el("div", { class: "field-name", text: `“${request.question}”` }),
          el("div", {
            class: "hint",
            text: `answered ${request.tier === "definition" ? "from the form itself" : request.tier === "grounded" ? "from the reference notes" : `by ${request.team}`}${request.sources?.length ? ` · ${request.sources.join(", ")}` : ""}`,
          }),
          request.answer ? el("div", { class: "field-value", text: request.answer }) : null,
          request.resolution ? el("div", { class: "field-value", text: request.resolution }) : null,
        ),
      ),
    );
  }

  return card(
    open.length ? `Questions raised — ${open.length} still open` : "Questions raised",
    el("p", {
      class: "hint",
      text: "Answered from the form, then from its reference notes, then by the team that owns it. An open one travels onto the document, so a value nobody could settle is visibly one nobody could settle.",
    }),
    list,
  );
}

function closeQuestion(request) {
  const input = el("textarea", { placeholder: "What did they say?" });
  modal(
    "Record the team's answer",
    el(
      "div",
      {},
      el("p", { class: "lede", text: `“${request.question}”` }),
      el("p", { class: "hint", text: `Raised with ${request.team}.` }),
      field("Their answer", input),
    ),
    [
      {
        label: "Close the question",
        run: async () => {
          const resolution = input.value.trim();
          if (!resolution) {
            toast("Write down what they said first");
            return;
          }
          try {
            await api.post(
              `/forms/sessions/${context.sessionId}/questions/${request.id}`,
              { resolution },
            );
            toast("Question closed", { tone: "success" });
            await refresh();
          } catch (error) {
            reportError(error, "That question could not be closed");
          }
        },
      },
    ],
  );
}

function editField(definitionField, answer) {
  const control =
    definitionField.options?.length > 0
      ? el(
          "select",
          {},
          el("option", { value: "", text: "—" }),
          ...definitionField.options.map((option) =>
            el("option", { value: option, text: option, selected: answer?.value === option }),
          ),
        )
      : el("input", {
          type: definitionField.type === "date" ? "date" : "text",
          value: answer?.value ?? "",
        });

  modal(
    definitionField.label,
    el(
      "div",
      {},
      definitionField.rationale
        ? el("p", { class: "lede", text: definitionField.rationale })
        : null,
      field("Value", control),
      el("p", {
        class: "hint",
        text: "Setting a value here marks it confirmed, so later extraction from a ticket or an email cannot overwrite it.",
      }),
    ),
    [
      {
        label: "Save",
        run: async () => {
          try {
            await api.put(`/forms/sessions/${context.sessionId}/answers`, {
              field_id: definitionField.id,
              value: control.value,
              author: state.participant,
            });
            toast(`${definitionField.label} set`, { tone: "success" });
            await refresh();
          } catch (error) {
            reportError(error, "That value was rejected");
          }
        },
      },
    ],
  );
}

// -- artifacts --------------------------------------------------------------

function artifactCard(locked) {
  const { session, definition, status } = context;
  const complete = status.completeness?.mandatory_complete;

  const formats = definition.output_formats ?? ["xlsx", "pdf", "markdown"];
  const chosen = new Set(formats.slice(0, 2));
  const allowIncomplete = el("input", { type: "checkbox" });

  const boxes = formats.map((format) => {
    const box = el("input", { type: "checkbox", checked: chosen.has(format) });
    box.addEventListener("change", () =>
      box.checked ? chosen.add(format) : chosen.delete(format),
    );
    return el("label", { class: "row tight" }, box, el("span", { text: format }));
  });

  return card(
    "Produce the document",
    complete
      ? el("p", { class: "hint" }, badge("ready", "ok"), el("span", { text: " Every required field is answered." }))
      : el(
          "p",
          { class: "hint" },
          badge("incomplete", "warn"),
          el("span", {
            text: ` ${(status.completeness?.outstanding_mandatory ?? []).length} required field(s) still open.`,
          }),
        ),
    el("div", { class: "row" }, ...boxes),
    complete
      ? null
      : el(
          "label",
          { class: "row tight", style: "margin-top:8px" },
          allowIncomplete,
          el("span", {
            class: "muted",
            text: "Render anyway — the gaps are recorded as action items",
          }),
        ),
    el(
      "div",
      { class: "row", style: "margin-top:10px" },
      el("button", {
        class: "primary",
        text: "Generate",
        disabled: locked,
        onClick: async (event) => {
          if (!chosen.size) {
            toast("Choose at least one format");
            return;
          }
          try {
            const result = await withBusy(event.target, () =>
              api.post(`/forms/sessions/${context.sessionId}/generate`, {
                formats: [...chosen],
                allow_incomplete: allowIncomplete.checked,
              }),
            );
            toast(`${result.count} artifact(s) produced`, { tone: "success" });
            showArtifacts(result.artifacts);
            await refresh();
          } catch (error) {
            reportError(error, "The document could not be produced");
          }
        },
      }),
      locked
        ? el("button", {
            text: "Reopen for edits",
            onClick: async () => {
              try {
                await api.post(`/forms/sessions/${context.sessionId}/reopen`, undefined, {
                  reason: "reopened from the console",
                });
                toast("Session reopened");
                await refresh();
              } catch (error) {
                reportError(error, "Could not reopen the session");
              }
            },
          })
        : null,
      el("a", { href: "#/artifacts", class: "button", text: "Review and approve" }),
    ),
    session.artifacts?.length
      ? el("p", { class: "hint", text: `${session.artifacts.length} artifact(s) produced so far.` })
      : null,
  );
}

function showArtifacts(artifacts) {
  modal(
    "Artifacts produced",
    table(
      [
        { label: "Format", render: (a) => a.format },
        { label: "File", render: (a) => a.filename },
        { label: "Checksum", render: (a) => el("code", { text: (a.checksum ?? "").slice(0, 12) }) },
        {
          label: "",
          render: (a) =>
            el("button", {
              text: "Download",
              onClick: () => download(`/forms/artifacts/${a.id}/content`, a.filename),
            }),
        },
      ],
      artifacts,
    ),
  );
}
