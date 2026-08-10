/* Sessions: every in-flight and finished form conversation. */

import { api } from "../api.js";
import { badge, card, el, reportError, table, timeAgo, withBusy } from "../ui.js";
import { state } from "../state.js";

const TONE = {
  collecting: "accent",
  ready_for_review: "warn",
  in_review: "warn",
  approved: "ok",
  baselined: "ok",
  abandoned: "",
};

export async function render(root, _params) {
  const onlyMine = el("input", { type: "checkbox" });
  const formFilter = el("input", { type: "search", placeholder: "filter by form name" });
  const body = el("div", {});

  async function load() {
    await withBusy(body, async () => {
      const data = await api.get("/forms/sessions", {
        participant: onlyMine.checked ? state.participant : undefined,
        form_name: formFilter.value || undefined,
        limit: 100,
      });
      body.replaceChildren(
        table(
          [
            {
              label: "Session",
              render: (s) =>
                el("a", {
                  href: `#/session/${s.session_id}`,
                  text: s.title || s.form,
                }),
            },
            { label: "Form", render: (s) => el("code", { text: s.form }) },
            { label: "Status", render: (s) => badge(s.status, TONE[s.status] ?? "") },
            { label: "Participants", render: (s) => (s.participants ?? []).join(", ") || "—" },
            { label: "Updated", render: (s) => timeAgo(s.updated_at) },
            {
              label: "",
              render: (s) =>
                el("a", {
                  href: `#/session/${s.session_id}`,
                  class: "button",
                  text: s.status === "collecting" ? "Continue" : "Open",
                }),
            },
          ],
          data.sessions,
          { emptyMessage: "No sessions yet. Start one from the Forms page." },
        ),
      );
    });
  }

  formFilter.addEventListener("input", () => {
    window.clearTimeout(formFilter._timer);
    formFilter._timer = window.setTimeout(load, 220);
  });
  onlyMine.addEventListener("change", load);

  root.append(
    el(
      "div",
      { class: "page-head" },
      el("h1", { text: "Sessions" }),
      el("p", {
        class: "lede",
        text: "A session holds one person's — or one group's — progress through a form. It survives a restart, and resumes where it was left.",
      }),
    ),
    card(
      null,
      el(
        "div",
        { class: "spread" },
        formFilter,
        el(
          "label",
          { class: "row tight" },
          onlyMine,
          el("span", { class: "muted", text: `Only ${state.participant}'s` }),
        ),
      ),
      body,
    ),
  );

  await load().catch((error) => reportError(error, "Could not list sessions"));
}
