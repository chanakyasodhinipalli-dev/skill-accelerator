/* Overview: is the platform wired up, and what needs attention. */

import { api } from "../api.js";
import { badge, card, el, table, timeAgo } from "../ui.js";
import { state } from "../state.js";

function metric(label, value, detail) {
  return el(
    "section",
    { class: "card" },
    el("div", { class: "metric", text: String(value) }),
    el("div", { class: "metric-label", text: label }),
    detail ? el("div", { class: "hint", text: detail }) : null,
  );
}

export async function render(root, _params) {
  root.append(
    el(
      "div",
      { class: "page-head" },
      el("h1", { text: "Overview" }),
      el("p", {
        class: "lede",
        text: "Everything below is read from the live API. If a number here is wrong, it is wrong for every client, not just this console.",
      }),
    ),
  );

  const [health, info, forms, sessions, pending, providers, tools] = await Promise.all([
    api.get("/health/ready").catch(() => null),
    api.get("/health").catch(() => ({})),
    api.get("/forms").catch(() => ({ count: 0, forms: [] })),
    api.get("/forms/sessions", { limit: 100 }).catch(() => ({ count: 0, sessions: [] })),
    api.get("/forms/reviews/pending").catch(() => ({ count: 0, artifacts: [] })),
    api.get("/providers").catch(() => ({ count: 0, profiles: [], active: "—" })),
    api.get("/tools").catch(() => ({ count: 0 })),
  ]);

  const mine = sessions.sessions.filter((s) => (s.participants ?? []).includes(state.participant));

  root.append(
    el(
      "div",
      { class: "grid" },
      metric("Published forms", forms.count),
      metric("Open sessions", sessions.count, `${mine.length} yours`),
      metric("Awaiting review", pending.count),
      metric("Model profiles", providers.count, `active: ${providers.active}`),
      metric("Registered tools", tools.count ?? 0),
    ),
  );

  const active = providers.profiles.find((p) => p.name === providers.active);
  root.append(
    card(
      "Model routing",
      el(
        "div",
        { class: "row" },
        badge(active?.vendor ?? "—", "accent"),
        el("span", { text: active?.model ?? "no active profile" }),
        active?.via_gateway ? badge("via gateway", "warn") : null,
        active && !active.credential_present ? badge("no credential", "bad") : null,
        state.profileOverride
          ? badge(`this console pinned: ${state.profileOverride}`, "warn")
          : null,
      ),
      el("p", {
        class: "hint",
        text: "The picker in the header pins a profile for requests from this console only, using the X-LLM-Profile header. Changing the server default is on the Models page.",
      }),
    ),
  );

  root.append(
    card(
      "Needs attention",
      table(
        [
          { label: "What", render: (r) => r.what },
          { label: "Detail", render: (r) => r.detail },
          { label: "", render: (r) => r.action },
        ],
        [
          ...pending.artifacts.slice(0, 5).map((artifact) => ({
            what: badge("review", "warn"),
            detail: `${artifact.form} · ${artifact.format} · rev ${artifact.revision}`,
            action: el("a", { href: "#/artifacts", text: "Review" }),
          })),
          ...mine
            .filter((s) => s.status === "collecting")
            .slice(0, 5)
            .map((session) => ({
              what: badge("in progress", "accent"),
              detail: `${session.form} · updated ${timeAgo(session.updated_at)}`,
              action: el("a", { href: `#/session/${session.session_id}`, text: "Continue" }),
            })),
        ],
        { emptyMessage: "Nothing is waiting on you." },
      ),
    ),
  );

  if (health) {
    const checks = Object.entries(health.checks ?? {});
    root.append(
      card(
        "Health",
        el(
          "div",
          { class: "row" },
          badge(health.status ?? "unknown", health.status === "healthy" ? "ok" : "warn"),
          el("span", {
            class: "muted",
            text: `${info.service ?? "platform"} ${info.version ?? ""} · ${info.environment ?? ""}`,
          }),
        ),
        checks.length
          ? table(
              [
                { label: "Check", render: ([name]) => name },
                {
                  label: "Status",
                  render: ([, result]) =>
                    badge(result.status, result.status === "healthy" ? "ok" : "bad"),
                },
                { label: "Message", render: ([, result]) => result.message ?? "" },
              ],
              checks,
            )
          : null,
      ),
    );
  }
}
