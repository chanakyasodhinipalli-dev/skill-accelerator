/* The assistant: ask about any form conversation, across every session.
 *
 * Answers arrive with citations because they are built from retrieved records
 * rather than recalled. The citations are rendered as links, so the claim and
 * the record it came from are one click apart.
 */

import { api } from "../api.js";
import { badge, card, el, reportError, withBusy } from "../ui.js";
import { state } from "../state.js";

const SUGGESTIONS = [
  "What is waiting on me?",
  "Which of my forms are unfinished?",
  "What did we decide about the December release?",
  "Who approved the last change request?",
  "What forms can I fill in?",
];

export async function render(root, _params) {
  root.append(
    el(
      "div",
      { class: "page-head" },
      el("h1", { text: "Assistant" }),
      el("p", {
        class: "lede",
        text: "Ask about any form, session, or artifact. Evidence is retrieved deterministically and cited by id — nothing is answered from memory, and with no model configured you get the same evidence in plainer words.",
      }),
    ),
  );

  const log = el("div", { class: "chat-log" });
  const input = el("textarea", {
    placeholder: "Ask about a form, a decision, a person, or a value you remember…",
    "aria-label": "Your question",
  });

  async function ask(text) {
    const question = (text ?? input.value).trim();
    if (!question) return;
    input.value = "";
    log.append(el("div", { class: "bubble user" }, el("span", { text: question })));
    log.scrollTop = log.scrollHeight;

    try {
      const answer = await withBusy(log, () =>
        api.post("/forms/assistant/ask", {
          question,
          conversation_id: state.assistantConversationId ?? undefined,
          participant: state.participant,
        }),
      );
      state.assistantConversationId = answer.conversation_id;
      log.append(renderAnswer(answer));
      log.scrollTop = log.scrollHeight;
    } catch (error) {
      reportError(error, "The assistant could not answer");
    }
  }

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      ask();
    }
  });

  root.append(
    card(
      null,
      el(
        "div",
        { class: "chat" },
        log,
        el(
          "div",
          { class: "composer" },
          input,
          el("button", { class: "primary", text: "Ask", onClick: () => ask() }),
        ),
      ),
      el(
        "div",
        { class: "row", style: "margin-top:10px" },
        ...SUGGESTIONS.map((suggestion) =>
          el("button", { class: "ghost", text: suggestion, onClick: () => ask(suggestion) }),
        ),
        el("button", {
          class: "ghost",
          text: "New thread",
          onClick: () => {
            state.assistantConversationId = null;
            log.replaceChildren();
          },
        }),
      ),
    ),
  );

  root.append(await searchCard());
}

function renderAnswer(answer) {
  const bubble = el("div", { class: "bubble assistant" });
  bubble.append(el("span", { text: answer.answer }));

  if (!answer.generated) {
    bubble.append(
      el(
        "div",
        { style: "margin-top:8px" },
        badge("composed without a model", "warn"),
      ),
    );
  }

  for (const citation of answer.citations ?? []) {
    const href =
      citation.kind === "session"
        ? `#/session/${citation.id}`
        : citation.kind === "form"
          ? `#/forms/${citation.form ?? citation.id.split("@")[0]}`
          : "#/artifacts";
    bubble.append(
      el(
        "a",
        { class: "citation", href },
        el("strong", { text: `${citation.kind}: ${citation.title}` }),
        el("div", { class: "muted", text: citation.summary ?? "" }),
      ),
    );
  }

  if (answer.actions?.length) {
    bubble.append(
      el(
        "div",
        { class: "row", style: "margin-top:8px" },
        ...answer.actions.map((action) =>
          el("a", {
            class: "button",
            text: action.label,
            href:
              action.action === "open_session"
                ? `#/session/${action.session_id}`
                : action.action === "start_session"
                  ? `#/forms/${action.form}`
                  : "#/artifacts",
          }),
        ),
      ),
    );
  }

  return bubble;
}

async function searchCard() {
  const input = el("input", { type: "search", placeholder: "Search every session, form, and artifact" });
  const kind = el(
    "select",
    {},
    el("option", { value: "", text: "Everything" }),
    el("option", { value: "session", text: "Sessions" }),
    el("option", { value: "form", text: "Forms" }),
    el("option", { value: "artifact", text: "Artifacts" }),
  );
  const results = el("div", {});

  async function run() {
    try {
      const data = await api.get("/forms/assistant/search", {
        q: input.value,
        kind: kind.value || undefined,
        limit: 12,
      });
      results.replaceChildren(
        ...(data.results.length
          ? data.results.map((hit) =>
              el(
                "a",
                {
                  class: "citation",
                  href:
                    hit.kind === "session"
                      ? `#/session/${hit.id}`
                      : hit.kind === "form"
                        ? `#/forms/${hit.form ?? hit.id.split("@")[0]}`
                        : "#/artifacts",
                },
                el(
                  "div",
                  { class: "row tight" },
                  badge(hit.kind),
                  el("strong", { text: hit.title }),
                  el("span", { class: "muted", text: `score ${hit.score}` }),
                ),
                el("div", { class: "muted", text: hit.summary ?? "" }),
              ),
            )
          : [el("p", { class: "muted", text: "Nothing matched." })]),
      );
    } catch (error) {
      reportError(error, "Search failed");
    }
  }

  input.addEventListener("input", () => {
    window.clearTimeout(input._timer);
    input._timer = window.setTimeout(run, 250);
  });
  kind.addEventListener("change", run);

  const node = card("Search", el("div", { class: "row" }, input, kind), results);
  await run();
  return node;
}
