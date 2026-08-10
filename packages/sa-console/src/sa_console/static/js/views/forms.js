/* Forms: the catalogue, one definition in full, and version management. */

import { api } from "../api.js";
import { badge, card, el, modal, reportError, table, toast, withBusy } from "../ui.js";
import { state } from "../state.js";

const STATUS_TONE = { active: "ok", draft: "warn", deprecated: "", archived: "bad" };

export async function render(root, params) {
  if (params.name) return renderOne(root, params.name);
  return renderCatalogue(root);
}

// -- catalogue --------------------------------------------------------------

async function renderCatalogue(root) {
  const search = el("input", {
    type: "search",
    placeholder: "Search titles, tags, field labels…",
    "aria-label": "Search forms",
  });
  const includeInactive = el("input", { type: "checkbox" });
  const body = el("div", {});

  async function load() {
    await withBusy(body, async () => {
      const data = await api.get("/forms", {
        query: search.value || undefined,
        include_inactive: includeInactive.checked || undefined,
      });
      body.replaceChildren(
        table(
          [
            {
              label: "Form",
              render: (f) => el("a", { href: `#/forms/${f.name}`, text: f.title }),
            },
            { label: "Name", render: (f) => el("code", { text: f.name }) },
            { label: "Version", render: (f) => f.version },
            {
              label: "Status",
              render: (f) => badge(f.status, STATUS_TONE[f.status] ?? ""),
            },
            // An agreement form is measured in agreements. Shown as "0 required
            // / 0" it reads as an empty form somebody forgot to finish.
            { label: "Kind", render: (f) => badge(f.kind ?? "intake", f.kind === "agreement" ? "accent" : "") },
            {
              label: "Asks for",
              render: (f) =>
                f.kind === "agreement"
                  ? `${f.required_agreements} agreement(s)${f.total_fields ? ` + ${f.total_fields} field(s)` : ""}`
                  : `${f.required_fields} required / ${f.total_fields} fields`,
            },
            { label: "Owner", render: (f) => f.owner ?? "—" },
            {
              label: "",
              render: (f) =>
                el("button", {
                  class: "primary",
                  text: f.kind === "agreement" ? "Review and accept" : "Fill in",
                  disabled: f.status !== "active",
                  title: f.status === "active" ? "" : "Only an active version can be filled in",
                  onClick: () => startSession(f.name),
                }),
            },
          ],
          data.forms,
          { emptyMessage: "No forms match. Build one from a sample on the Form builder page." },
        ),
      );
    });
  }

  search.addEventListener("input", () => {
    window.clearTimeout(search._timer);
    search._timer = window.setTimeout(load, 220);
  });
  includeInactive.addEventListener("change", load);

  root.append(
    el(
      "div",
      { class: "page-head" },
      el("h1", { text: "Forms" }),
      el("p", {
        class: "lede",
        text: "A form is data, not code. Every version is kept; sessions always start on the latest active one.",
      }),
    ),
    card(
      null,
      el(
        "div",
        { class: "spread" },
        el("div", { class: "row" }, search),
        el(
          "label",
          { class: "row tight" },
          includeInactive,
          el("span", { class: "muted", text: "Show drafts and deprecated" }),
        ),
      ),
      body,
    ),
  );
  await load();
}

async function startSession(formName) {
  try {
    const started = await api.post(`/forms/${formName}/sessions`, {
      participant: state.participant,
      resume: true,
    });
    window.location.hash = `#/session/${started.session_id}`;
  } catch (error) {
    reportError(error, "Could not start the session");
  }
}

// -- one form ---------------------------------------------------------------

async function renderOne(root, name) {
  const [definition, history] = await Promise.all([
    api.get(`/forms/${name}`),
    api.get(`/forms/${name}/history`),
  ]);

  root.append(
    el(
      "div",
      { class: "page-head" },
      el("a", { href: "#/forms", class: "muted", text: "← All forms" }),
      el("h1", { text: definition.title }),
      el(
        "div",
        { class: "row" },
        badge(definition.status, STATUS_TONE[definition.status] ?? ""),
        badge(
          definition.kind === "agreement" ? "agreement form" : "intake form",
          definition.kind === "agreement" ? "accent" : "",
        ),
        el("code", { text: `${definition.name}@${definition.version}` }),
        definition.owner ? el("span", { class: "muted", text: `owner: ${definition.owner}` }) : null,
      ),
      definition.description ? el("p", { class: "lede", text: definition.description }) : null,
    ),
  );

  root.append(
    el(
      "div",
      { class: "row" },
      el("button", {
        class: "primary",
        text: definition.kind === "agreement" ? "Review and accept" : "Fill this in",
        disabled: definition.status !== "active",
        onClick: () => startSession(name),
      }),
      definition.status === "draft"
        ? el("button", { text: "Activate", onClick: () => activate(name, definition.version) })
        : null,
      definition.status === "draft"
        ? el("button", { text: "Refine in plain language", onClick: () => refine(name) })
        : null,
      el("button", { text: "Duplicate as draft", onClick: () => fork(name) }),
      el("button", {
        class: "danger",
        text: "Delete this version",
        onClick: () => remove(name, definition.version, definition.status),
      }),
    ),
  );

  if (definition.guidance) {
    root.append(card("Conversation guidance", el("p", { class: "lede", text: definition.guidance })));
  }

  for (const section of [...definition.sections].sort((a, b) => a.order - b.order)) {
    root.append(
      card(
        section.title,
        section.description ? el("p", { class: "muted", text: section.description }) : null,
        table(
          [
            { label: "Field", render: (f) => el("strong", { text: f.label }) },
            { label: "Id", render: (f) => el("code", { text: f.id }) },
            { label: "Type", render: (f) => f.type },
            {
              label: "Importance",
              render: (f) =>
                badge(f.importance, f.importance === "mandatory" ? "accent" : ""),
            },
            {
              label: "Rules",
              render: (f) =>
                el(
                  "div",
                  { class: "row tight" },
                  f.require_explicit ? badge("never inferred", "warn") : null,
                  f.sensitive ? badge("sensitive", "bad") : null,
                  f.ask_when ? badge("conditional") : null,
                  f.options?.length ? badge(`${f.options.length} options`) : null,
                ),
            },
            {
              label: "Why it is asked",
              render: (f) => el("span", { class: "muted", text: f.rationale || "—" }),
            },
          ],
          section.fields,
        ),
      ),
    );
  }

  // What they will have to agree to is part of "what will this form ask me?".
  // Finding out at the end is how someone abandons a half-filled submission.
  if (definition.agreements?.length) {
    root.append(
      card(
        "Agreements",
        el("p", {
          class: "hint",
          text: "Presented word for word and stored with a hash, so a later edit to the wording cannot change what somebody agreed to. Rewording one means a new version, and everyone is asked again.",
        }),
        table(
          [
            { label: "Agreement", render: (a) => el("strong", { text: a.title }) },
            { label: "Whose statement", render: (a) => badge(a.kind, a.kind === "user" ? "accent" : "") },
            { label: "Taken", render: (a) => String(a.stage).replace(/_/g, " ") },
            { label: "Version", render: (a) => a.version ?? "1.0.0" },
            { label: "Required", render: (a) => (a.required ? badge("required", "warn") : badge("optional")) },
            // A clause with nothing to explain it with becomes a ticket the
            // first time somebody asks what it means, and they always ask.
            {
              label: "Answers questions",
              render: (a) =>
                a.explanation || a.faqs?.length
                  ? badge(
                      `${a.faqs?.length ?? 0} answered${a.explanation ? " + plain English" : ""}`,
                      "ok",
                    )
                  : badge("escalates", "warn"),
            },
            { label: "Wording", render: (a) => el("span", { class: "muted", text: a.text }) },
          ],
          definition.agreements,
        ),
      ),
    );
  }

  if (definition.escalation?.length || definition.knowledge?.length) {
    root.append(
      card(
        "When it can't answer",
        el("p", {
          class: "hint",
          text: "A question is answered from the field definitions, then from these notes, then by the team that owns it. Nothing outside the notes is invented — an unsupported question is routed rather than guessed at.",
        }),
        definition.knowledge?.length
          ? table(
              [
                { label: "Note", render: (n) => el("strong", { text: n.title || n.id }) },
                { label: "Covers", render: (n) => (n.applies_to?.length ? n.applies_to.join(", ") : "the whole form") },
                { label: "Source", render: (n) => n.source || "—" },
              ],
              definition.knowledge,
            )
          : null,
        definition.escalation?.length
          ? table(
              [
                { label: "Team", render: (r) => el("strong", { text: r.team }) },
                { label: "Contact", render: (r) => r.contact || "—" },
                { label: "Answers about", render: (r) => (r.covers?.length ? r.covers.join(", ") : "anything else") },
                { label: "Turnaround", render: (r) => r.sla || "—" },
              ],
              definition.escalation,
            )
          : el("p", {
              class: "hint",
              text: "No escalation route is declared, so a question nobody can answer falls back to naming the form's owner. Declare one.",
            }),
      ),
    );
  }

  root.append(
    card(
      "Version history",
      table(
        [
          { label: "Version", render: (v) => v.version },
          { label: "Status", render: (v) => badge(v.status, STATUS_TONE[v.status] ?? "") },
          { label: "Fields", render: (v) => v.fields },
          { label: "Note", render: (v) => v.change_note || "—" },
          {
            label: "",
            render: (v) =>
              v.status === "draft"
                ? el("button", { text: "Activate", onClick: () => activate(name, v.version) })
                : el("span", { class: "muted", text: "" }),
          },
        ],
        history.versions,
      ),
      el("p", {
        class: "hint",
        text: "Publishing a version deprecates the previous one. Sessions already in flight keep the version they started on.",
      }),
    ),
  );
}

async function activate(name, version) {
  try {
    await api.post(`/forms/${name}/versions/${version}/activate`);
    toast(`${name} v${version} is now the active version`, { tone: "success" });
    window.location.hash = `#/forms/${name}`;
    window.location.reload();
  } catch (error) {
    reportError(error, "Could not activate that version");
  }
}

function refine(name) {
  const input = el("textarea", {
    placeholder: "e.g. make cost centre optional, and add a field for the rollback plan",
  });
  modal(
    "Refine this draft",
    el(
      "div",
      {},
      el("p", {
        class: "lede",
        text: "Describe the change in plain language. The draft is edited in place; published versions are never touched.",
      }),
      input,
    ),
    [
      {
        label: "Apply",
        run: async () => {
          try {
            await api.post(`/forms/${name}/refine`, { instructions: input.value });
            toast("Draft updated", { tone: "success" });
            window.location.reload();
          } catch (error) {
            reportError(error, "Could not refine the draft");
          }
        },
      },
    ],
  );
}

function fork(name) {
  const note = el("input", { type: "text", placeholder: "why are you changing it?" });
  modal(
    "Duplicate as a new draft",
    el(
      "div",
      {},
      el("p", {
        class: "lede",
        text: "A published version is never edited in place — someone may already be filling it in, and a baselined artifact names the exact version it came from. This forks a new draft instead.",
      }),
      note,
    ),
    [
      {
        label: "Create draft",
        run: async () => {
          try {
            const draft = await api.patch(`/forms/${name}`, {
              changes: {},
              bump: "minor",
              change_note: note.value,
            });
            toast(`Draft v${draft.version} created`, { tone: "success" });
            window.location.reload();
          } catch (error) {
            reportError(error, "Could not create the draft");
          }
        },
      },
    ],
  );
}

function remove(name, version, status) {
  modal(
    `Delete ${name} v${version}?`,
    el("p", {
      class: "lede",
      text:
        status === "draft"
          ? "This draft has never been published, so nothing references it."
          : "This version is published. Deleting it needs force, and any artifact produced from it will name a version that no longer exists.",
    }),
    [
      {
        label: "Delete",
        class: "danger",
        run: async () => {
          try {
            await api.del(`/forms/${name}`, { version, force: status !== "draft" });
            toast("Deleted", { tone: "success" });
            window.location.hash = "#/forms";
          } catch (error) {
            reportError(error, "Could not delete that version");
          }
        },
      },
    ],
  );
}
